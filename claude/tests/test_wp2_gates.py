"""WP2 gates (2026-08-12) — workspace grounding + adjudication/budget/
estimate/rework/commit governance:

  * workspace — Recipe.workspace validated at record time (absolute +
    exists + contains .git) via StartRecipe and the update_object recipe
    patch;
  * reviewer git brief — the dispatcher-composed review brief carries the
    workspace's ACTUAL git state (or an honest note) and forwards each
    reviewed action's recorded acceptance runs verbatim;
  * G-ADJ — a persisted adversarial challenge blocks NON-review dispatch
    until adjudicated via record_context(kind='challenge_adjudication');
    review legs are never blocked;
  * G-BUDGET — warn (>=80%) advises on the spawn success payload; exceeded
    refuses unless a recorded user answer overrides (G-BUDGET:<recipe_id>);
  * G-EST — a spawn_planner step requires an estimate ({tokens?, hours?});
  * G-REWORK — plan_fsm freezes an action at STUCK_HARD_CAP re-dispatches /
    verify failures (pure-function pins), and pool_spawn_worker floors
    `attempt` at the pool's own session history for the handle;
  * G-COMMIT — a succeeded close over a workspace recipe refuses a dirty
    tree (waivable by a recorded user answer) and records head_commit on a
    clean one;
  * inline execution — Action.execution='inline' draws a spawn ADVISORY
    (never a refusal);
  * emission-gate proof — legacy JSON round-trips with none of the new keys.
"""

import subprocess
from datetime import datetime, timedelta, timezone

from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Plan, Recipe

RID = "recipe-wp2"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _err(res):
    assert isinstance(res, ToolError), res
    assert res.code == "tool_precondition"
    return res.message


def _step(sid, status="pending", execution="spawn_planner"):
    return {"step_id": sid, "kind": "work", "description": "d",
            "status": status, "depends_on": [], "execution": execution}


def _recipe(env, rid=RID, steps=None, outcomes=None, state="executing",
            workspace=None, budget=None, created_at=None):
    now = datetime.now(timezone.utc)
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state=state,
        comprehension={"branches": [], "expected_outcomes": outcomes or []},
        steps=steps if steps is not None else [_step("s1")],
        context={},
        workspace=workspace,
        budget=budget,
        created_at=created_at or now,
        updated_at=now,
    )))


def _outcome(oid="o1", met=True):
    o = {"id": oid, "description": "d", "verification": "v"}
    if met:
        o["met"] = True
        o["met_evidence"] = "reviewer verified + user confirmed"
    return o


def _plan(env, rid, sid, state="dispatching", terminal_status=None,
          actions=None):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=f"{rid}-{sid}", recipe_id=rid, recipe_step_id=sid,
        domain="generic", shape="x", goal="g", state=state,
        terminal_status=terminal_status, actions=actions or [],
    )))
    return f"{rid}-{sid}"


def _action(aid="a1", status="pending", **extra):
    a = {"action_id": aid, "description": "d", "status": status,
         "depends_on": [], "executor_mode": "subagent",
         "acceptance": {"kind": "tests_pass"}}
    a.update(extra)
    return a


async def _gate_answer(env, rid, target,
                       answer="yes, go ahead — I accept that (user)"):
    res = await env.call("record_user_answer", recipe_id=rid,
                         gate_target=target, answer=answer)
    return _ok(res)["answer_id"]


_RUN = {"command": "pytest tests -q", "exit_code": 0,
        "output_tail": "1 passed", "at": "2026-08-12T00:00:00+00:00"}


# ── git fixtures ───────────────────────────────────────────────────────────
def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args],
                   check=True, capture_output=True, text=True, timeout=30)


def _make_repo(tmp_path, name="ws", dirty=False):
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "f.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init", "--no-verify")
    if dirty:
        (repo / "f.txt").write_text("hello, modified\n", encoding="utf-8")
    return repo


def _head(repo) -> str:
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         check=True, capture_output=True, text=True)
    return out.stdout.strip()


# ═══════════════════════ 1. workspace validation ══════════════════════════
async def test_start_recipe_workspace_bad_paths_refused(env, tmp_path):
    # relative path
    res = await env.call("start_recipe", goal="g", domain="generic",
                         workspace="not/absolute")
    assert "REPO ROOT" in _err(res)
    # absolute dir that exists but has no .git
    plain = tmp_path / "plain"
    plain.mkdir()
    res = await env.call("start_recipe", goal="g", domain="generic",
                         workspace=str(plain))
    assert ".git" in _err(res)
    # absolute path that does not exist
    res = await env.call("start_recipe", goal="g", domain="generic",
                         workspace=str(tmp_path / "nope"))
    _err(res)


async def test_start_recipe_workspace_git_repo_accepted(env, tmp_path):
    repo = _make_repo(tmp_path)
    rid = _ok(await env.call("start_recipe", goal="build it",
                             domain="generic",
                             workspace=str(repo)))["recipe_id"]
    assert env.ctx.recipes.load(rid).workspace == str(repo)


async def test_update_object_recipe_workspace_patch(env, tmp_path):
    repo = _make_repo(tmp_path)
    _recipe(env)
    # bad path refused, nothing stored
    res = await env.call("update_object", type="recipe",
                         ids={"recipe_id": RID},
                         patch={"workspace": "relative/path"})
    assert "REPO ROOT" in _err(res)
    assert env.ctx.recipes.load(RID).workspace is None
    # valid repo accepted (the outcome_waivers-style thread-through)
    _ok(await env.call("update_object", type="recipe",
                       ids={"recipe_id": RID},
                       patch={"workspace": str(repo)}))
    assert env.ctx.recipes.load(RID).workspace == str(repo)


# ═══════════════ 2. reviewer git-diff brief + runs forwarding ═════════════
async def test_reviewer_brief_carries_git_block_and_runs(env, tmp_path):
    repo = _make_repo(tmp_path, dirty=True)
    _recipe(env, workspace=str(repo))
    pid = _plan(env, RID, "s1", actions=[
        _action("a1", status="done",
                acceptance={"kind": "tests_pass", "actual": "green",
                            "runs": [_RUN]}),
        _action("r1", status="pending", leg_kind="review"),
    ])
    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="r1",
                       role="reviewer"))
    inbox = env.ctx.broker.inboxes[f"{pid}:r1"]
    assert len(inbox) == 1
    body = inbox[0].body
    # the git block is the repo's ACTUAL state, each field capped text
    git = body["git"]
    assert "note" not in git
    assert "f.txt" in git["status"]                 # the dirty file
    assert "init" in git["recent_commits"]
    assert "f.txt" in git["diff_stat"]
    # the reviewed target forwards the recorded runs verbatim
    assert body["target"][0]["action_id"] == "a1"
    assert body["target"][0]["runs"] == [_RUN]
    # the criteria carry the re-run + commit sentence
    assert "Re-run the recorded acceptance runs verbatim" in body["criteria"]
    assert "record the hash in your verdict" in body["criteria"]


async def test_reviewer_brief_git_note_when_no_workspace(env):
    _recipe(env)     # no workspace
    pid = _plan(env, RID, "s1", actions=[
        _action("a1", status="done",
                acceptance={"kind": "tests_pass", "actual": "green"}),
        _action("r1", status="pending", leg_kind="review"),
    ])
    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="r1",
                       role="reviewer"))
    body = env.ctx.broker.inboxes[f"{pid}:r1"][0].body
    assert "locate and diff the target repo yourself" in body["git"]["note"]
    assert body["target"][0]["runs"] == []          # none recorded → empty


# ═══════════════════ 3. G-ADJ adversarial adjudication ════════════════════
async def test_successful_plan_challenge_persists_to_sidecar(env,
                                                             monkeypatch):
    from edp_contracts import Tool

    from edp_claude.tools import _tools as T

    _recipe(env)
    pid = _plan(env, RID, "s1", actions=[_action("a1")])

    async def fake_bridge(kind, kind_class, override, *, task,
                          context="", acceptance=""):
        assert kind == "challenge"
        return Tool.ok(T._BridgeOut(ok=True, delegate="sol", model="m",
                                    content="FINDING: the acceptance can "
                                            "pass while the goal fails"))

    monkeypatch.setattr(T, "_bridge_call", fake_bridge)
    _ok(await env.call("adversarial_challenge", target_kind="plan",
                       target_id=pid, content="the plan body",
                       lens="break-the-acceptance"))
    entries = T._read_challenges(env.ctx.plans.root, pid)
    assert len(entries) == 1
    assert entries[0]["lens"] == "break-the-acceptance"
    assert entries[0]["challenge_id"]
    assert "FINDING" in entries[0]["findings_raw"]
    assert entries[0]["at"]
    # a FAILED bridge call persists nothing
    async def failed_bridge(*a, **kw):
        return Tool.ok(T._BridgeOut(ok=False, delegate="sol", model="m",
                                    content="", blocker="window"))
    monkeypatch.setattr(T, "_bridge_call", failed_bridge)
    _ok(await env.call("adversarial_challenge", target_kind="plan",
                       target_id=pid, content="x", lens="hidden-coupling"))
    assert len(T._read_challenges(env.ctx.plans.root, pid)) == 1


async def test_artifact_challenge_persists_to_callers_plan(env, monkeypatch):
    """A non-plan target (artifact/spec_decision/assumption) attaches to the
    CALLING planner's plan sidecar — before this, only target_kind='plan'
    persisted, so an artifact challenge left G-ADJ with nothing to hold and
    the fix-the-findings dispatch sailed through unadjudicated."""
    from edp_contracts import Tool

    from edp_claude.tools import _tools as T

    _recipe(env)
    pid = _plan(env, RID, "s1", actions=[_action("a1")])

    async def fake_bridge(kind, kind_class, override, *, task,
                          context="", acceptance=""):
        return Tool.ok(T._BridgeOut(ok=True, delegate="sol", model="m",
                                    content="FINDING: the artifact lies"))

    monkeypatch.setattr(T, "_bridge_call", fake_bridge)
    monkeypatch.setenv("EDP_HANDLE", f"{RID}:s1")
    res = _ok(await env.call("adversarial_challenge", target_kind="artifact",
                             target_id="delivered-app-abc123",
                             content="the artifact body", lens="break-it"))
    entries = T._read_challenges(env.ctx.plans.root, pid)
    assert len(entries) == 1
    assert entries[0]["target_kind"] == "artifact"
    assert entries[0]["target_id"] == "delivered-app-abc123"
    # the caller gets the sidecar id back to adjudicate against
    returned_cid = (res["challenge_id"] if isinstance(res, dict)
                    else res.challenge_id)
    assert returned_cid == entries[0]["challenge_id"]
    # and the open challenge now gates the plan's non-review dispatch
    msg = _err(await env.call("pool_spawn_worker", plan_id=pid,
                              action_id="a1"))
    assert "G-ADJ" in msg and entries[0]["challenge_id"] in msg
    # a caller with no plan (e.g. the neuron) persists nowhere, still ok
    monkeypatch.setenv("EDP_HANDLE", "no-such-plan")
    _ok(await env.call("adversarial_challenge", target_kind="artifact",
                       target_id="x", content="y", lens="l"))
    assert len(T._read_challenges(env.ctx.plans.root, pid)) == 1


async def test_open_challenge_gates_non_review_dispatch_only(env):
    from edp_claude.tools import _tools as T

    _recipe(env)
    pid = _plan(env, RID, "s1", actions=[
        _action("a1"), _action("r1", leg_kind="review")])
    T._append_challenge(env.ctx.plans.root, pid, {
        "challenge_id": "ch-1", "lens": "break-the-acceptance",
        "at": "2026-08-12T00:00:00+00:00", "findings_raw": "FINDING: x"})

    # non-review dispatch refused, naming the open id + the adjudication call
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    msg = _err(res)
    assert "G-ADJ" in msg and "ch-1" in msg
    assert "challenge_adjudication" in msg
    assert env.ctx.pool.spawns == []

    # review legs are NEVER blocked
    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="r1",
                       role="reviewer"))
    assert [s["handle"] for s in env.ctx.pool.spawns] == [f"{pid}:r1"]

    # adjudicate → non-review dispatch proceeds
    _ok(await env.call("record_context", kind="challenge_adjudication",
                       plan_id=pid, challenge_id="ch-1",
                       disposition="accepted_wontfix",
                       text="finding is real but out of scope for this step"))
    entries = T._read_challenges(env.ctx.plans.root, pid)
    adj = [e for e in entries if e.get("adjudication")]
    assert len(adj) == 1
    assert adj[0]["adjudication"]["disposition"] == "accepted_wontfix"
    assert "out of scope" in adj[0]["adjudication"]["rationale"]
    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="a1"))


async def test_adjudication_refusals(env, monkeypatch):
    from edp_claude.tools import _tools as T

    _recipe(env)
    pid = _plan(env, RID, "s1", actions=[_action("a1")])
    T._append_challenge(env.ctx.plans.root, pid, {
        "challenge_id": "ch-1", "lens": "l",
        "at": "2026-08-12T00:00:00+00:00", "findings_raw": "f"})
    # missing required fields
    res = await env.call("record_context", kind="challenge_adjudication",
                         plan_id=pid)
    msg = _err(res)
    assert "challenge_id" in msg and "disposition" in msg
    # unknown challenge id, naming the known ones
    res = await env.call("record_context", kind="challenge_adjudication",
                         plan_id=pid, challenge_id="nope",
                         disposition="rejected", text="r")
    assert "ch-1" in _err(res)
    # a worker shell may not adjudicate (planner/specialist work)
    monkeypatch.setenv("EDP_ROLE", "worker")
    res = await env.call("record_context", kind="challenge_adjudication",
                         plan_id=pid, challenge_id="ch-1",
                         disposition="rejected", text="r")
    assert "planner" in _err(res)
    # absent sidecar = no gate (legacy plans dispatch freely)
    monkeypatch.delenv("EDP_ROLE")
    pid2 = _plan(env, RID, "s2", actions=[_action("b1")])
    _ok(await env.call("pool_spawn_worker", plan_id=pid2, action_id="b1"))


# ═══════════════════════════ 4. G-BUDGET ══════════════════════════════════
def _write_audit(env, cost_usd):
    d = env.ctx.recipes.root.parent / ".bridge"
    d.mkdir(parents=True, exist_ok=True)
    (d / "audit-test.jsonl").write_text(
        '{"ok": true, "tokens_in": 10, "tokens_out": 10, '
        f'"cost_usd": {cost_usd}}}\n', encoding="utf-8")


async def test_budget_check_levels(env):
    from edp_claude.tools._tools import _budget_check

    _recipe(env, budget={"delegate_usd": 10.0})
    assert _budget_check(env.ctx, RID)["level"] == "ok"
    _write_audit(env, 8.5)
    bc = _budget_check(env.ctx, RID)
    assert bc["level"] == "warn" and "delegate_usd" in bc["detail"]
    _write_audit(env, 12.0)
    assert _budget_check(env.ctx, RID)["level"] == "exceeded"
    # no budget → ok regardless of spend (legacy)
    _recipe(env, rid="recipe-nobudget")
    assert _budget_check(env.ctx, "recipe-nobudget")["level"] == "ok"


async def test_budget_wall_clock_exceeded(env):
    from edp_claude.tools._tools import _budget_check

    _recipe(env, budget={"wall_clock_hours": 1.0},
            created_at=datetime.now(timezone.utc) - timedelta(hours=2))
    bc = _budget_check(env.ctx, RID)
    assert bc["level"] == "exceeded" and "wall_clock_hours" in bc["detail"]


async def test_budget_warn_advisory_on_planner_spawn(env):
    _recipe(env, budget={"delegate_usd": 10.0})
    _write_audit(env, 9.0)
    data = _ok(await env.call("pool_spawn_planner", recipe_id=RID,
                              step_id="s1"))
    kinds = [a["kind"] for a in data["advisories"]]
    assert "budget_warning" in kinds


async def test_budget_exceeded_refuses_then_override_spawns(env):
    _recipe(env, budget={"delegate_usd": 10.0})
    _write_audit(env, 12.0)
    res = await env.call("pool_spawn_planner", recipe_id=RID, step_id="s1")
    msg = _err(res)
    assert "G-BUDGET" in msg and f"G-BUDGET:{RID}" in msg
    assert "record_user_answer" in msg
    assert env.ctx.pool.spawns == []
    ref = await _gate_answer(env, RID, f"G-BUDGET:{RID}")
    _ok(await env.call("pool_spawn_planner", recipe_id=RID, step_id="s1",
                       override_ref=ref))
    assert len(env.ctx.pool.spawns) == 1
    evs = env.ctx.recipes.read_events_tail(
        RID, kinds=["budget_overridden"], limit=0)
    assert evs and evs[-1]["override_ref"] == ref


async def test_budget_exceeded_refuses_worker_spawn_and_rolls_back(env):
    _recipe(env, budget={"delegate_usd": 10.0})
    _write_audit(env, 12.0)
    pid = _plan(env, RID, "s1", actions=[_action("a1",
                                                 status="in_progress")])
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    assert "G-BUDGET" in _err(res)
    assert env.ctx.pool.spawns == []
    # the FSM pre-stamp rolled back — no phantom in_progress
    assert env.ctx.plans.load(pid).actions[0].status == "pending"


# ═══════════════════════════ 5. G-EST ═════════════════════════════════════
async def test_spawn_planner_step_requires_estimate(env):
    _recipe(env, state="planning")
    res = await env.call("add_step", recipe_id=RID, description="build",
                         execution="spawn_planner")
    msg = _err(res)
    assert "G-EST" in msg and "tokens" in msg and "hours" in msg
    _ok(await env.call("add_step", recipe_id=RID, description="build",
                       execution="spawn_planner", estimate={"hours": 2}))
    # inline steps are exempt
    _ok(await env.call("add_step", recipe_id=RID, description="tiny",
                       execution="inline"))
    # an estimate with neither key is not an estimate
    res = await env.call("add_step", recipe_id=RID, description="build2",
                         execution="spawn_planner", estimate={"note": "x"})
    assert "G-EST" in _err(res)


# ═══════════════════ 6. G-REWORK — the freeze (pure FSM) ══════════════════
def _fsm_plan(actions):
    return Plan.model_validate(dict(
        plan_id="p1", recipe_id="r1", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=actions))


def test_frozen_action_never_redispatches_and_wait_names_it():
    from edp_claude.schemas import InstructionKind as K

    from edp_claude.fsm.plan_fsm import STUCK_HARD_CAP, plan_next_action

    p = _fsm_plan([_action("a1", attempt=STUCK_HARD_CAP)])
    first = plan_next_action(p)          # the (latched) escalation advisory
    assert first.kind == K.ESCALATE_CONSULT
    nxt = plan_next_action(p)
    assert nxt.kind == K.WAIT
    assert "FROZEN" in nxt.rationale and "a1" in nxt.rationale
    assert "ask_above" in nxt.rationale
    assert p.actions[0].status == "pending"     # never stamped in_progress


def test_verify_failures_freeze_and_others_still_dispatch():
    from edp_claude.schemas import InstructionKind as K

    from edp_claude.fsm.plan_fsm import STUCK_HARD_CAP, plan_next_action

    p = _fsm_plan([_action("a1", verify_failures=STUCK_HARD_CAP),
                   _action("a2")])
    assert plan_next_action(p).kind == K.ESCALATE_CONSULT
    nxt = plan_next_action(p)            # frozen a1 skipped, a2 dispatches
    assert nxt.kind == K.DISPATCH_ACTION
    assert nxt.args["action_id"] == "a2"
    assert p.actions[0].status == "pending"


def test_below_cap_still_dispatches_and_wave_excludes_frozen():
    from edp_claude.fsm.plan_fsm import (STUCK_HARD_CAP, plan_next_action,
                                         plan_ready_wave)

    p = _fsm_plan([_action("a1", attempt=STUCK_HARD_CAP - 1)])
    p.escalation_emitted = {"a1": [STUCK_HARD_CAP - 1, 0, False]}  # latched
    assert plan_next_action(p).kind.value == "dispatch_action"

    w = _fsm_plan([_action("b1", attempt=STUCK_HARD_CAP), _action("b2"),
                   _action("b3", verify_failures=STUCK_HARD_CAP)])
    instrs = plan_ready_wave(w)
    assert [i.args["action_id"] for i in instrs] == ["b2"]
    # frozen members are never absorbed into a batch unit either
    b = _fsm_plan([_action("c1", batch_group="g"),
                   _action("c2", depends_on=["c1"], batch_group="g",
                           attempt=STUCK_HARD_CAP)])
    instrs = plan_ready_wave(b)
    assert instrs[0].args["batch_action_ids"] == ["c1"]
    assert b.actions[1].status == "pending"


async def test_spawn_floors_attempt_at_pool_session_history(env):
    _recipe(env)
    pid = _plan(env, RID, "s1", actions=[_action("a1")])
    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="a1"))
    assert env.ctx.plans.load(pid).actions[0].attempt == 0   # first mint
    # the shell dies; a re-dispatch mints a SECOND session for the handle
    env.ctx.pool.mark_dead(f"{pid}:a1")
    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="a1"))
    assert env.ctx.plans.load(pid).actions[0].attempt == 1


# ═══════════════════════════ 7. G-COMMIT ══════════════════════════════════
def _closable(env, workspace):
    _recipe(env, steps=[_step("s1", "done")], outcomes=[_outcome()],
            state="reviewing", workspace=workspace)
    _plan(env, RID, "s1", state="terminal", terminal_status="succeeded")


async def test_dirty_tree_refuses_succeeded_close(env, tmp_path):
    repo = _make_repo(tmp_path, dirty=True)
    _closable(env, str(repo))
    res = await env.call("close_recipe", recipe_id=RID,
                         final_outcome={"status": "succeeded",
                                        "summary": "x"})
    msg = _err(res)
    assert "G-COMMIT" in msg and "UNCOMMITTED" in msg
    assert f"G-COMMIT:{RID}" in msg
    assert env.ctx.recipes.load(RID).state != "closed"


async def test_dirty_tree_waived_close_passes(env, tmp_path):
    repo = _make_repo(tmp_path, dirty=True)
    _closable(env, str(repo))
    ref = await _gate_answer(env, RID, f"G-COMMIT:{RID}")
    _ok(await env.call("close_recipe", recipe_id=RID,
                       final_outcome={"status": "succeeded", "summary": "x"},
                       commit_waiver_ref=ref))
    r = env.ctx.recipes.load(RID)
    assert r.state == "closed"
    assert "head_commit" not in (r.final_outcome or {})
    evs = env.ctx.recipes.read_events_tail(
        RID, kinds=["commit_gate_waived"], limit=0)
    assert evs and evs[-1]["override_ref"] == ref


async def test_clean_tree_records_head_commit(env, tmp_path):
    repo = _make_repo(tmp_path)
    _closable(env, str(repo))
    _ok(await env.call("close_recipe", recipe_id=RID,
                       final_outcome={"status": "succeeded",
                                      "summary": "x"}))
    r = env.ctx.recipes.load(RID)
    assert r.state == "closed"
    assert r.final_outcome["head_commit"] == _head(repo)


async def test_no_workspace_close_carries_no_gate(env):
    _closable(env, None)
    _ok(await env.call("close_recipe", recipe_id=RID,
                       final_outcome={"status": "succeeded",
                                      "summary": "x"}))
    assert "head_commit" not in env.ctx.recipes.load(RID).final_outcome


async def test_commit_recorded_on_status_and_verdict(env):
    _recipe(env)
    pid = _plan(env, RID, "s1", actions=[_action("a1",
                                                 status="in_progress")])
    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status="done", evidence="did it",
                       commit="abc1234"))
    assert env.ctx.plans.load(pid).actions[0].acceptance.commit == "abc1234"
    # the reviewer's verdict carries the commit it judged
    _ok(await env.call("record_branch_verdict", recipe_id=RID,
                       plan_id=pid, branch_id="a1",
                       verdict="re-ran the suite at that commit; all "
                               "criteria pass against the compiled doc",
                       passed=True, commit="abc1234"))
    assert env.ctx.plans.load(pid).actions[0] \
        .review_verdict["commit"] == "abc1234"


# ═══════════════════════ 8. inline execution ══════════════════════════════
async def test_add_action_execution_validated_and_persisted(env):
    _recipe(env)
    pid = _plan(env, RID, "s1")
    res = await env.call("add_action", plan_id=pid, action_id="a1",
                         description="d", execution="subagent")
    assert "inline" in _err(res)          # bad value refused, teaching both
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="d", execution="inline"))
    _ok(await env.call("add_action", plan_id=pid, action_id="a2",
                       description="d"))
    p = env.ctx.plans.load(pid)
    assert p.actions[0].execution == "inline"
    assert p.actions[1].execution == "spawn"


async def test_spawning_inline_action_draws_advisory_not_refusal(env):
    _recipe(env)
    pid = _plan(env, RID, "s1",
                actions=[_action("a1", execution="inline")])
    data = _ok(await env.call("pool_spawn_worker", plan_id=pid,
                              action_id="a1"))
    kinds = [a["kind"] for a in data["advisories"]]
    assert "inline_action_spawned" in kinds
    detail = data["advisories"][kinds.index("inline_action_spawned")]["detail"]
    assert "wastes a pool slot" in detail
    assert len(env.ctx.pool.spawns) == 1      # spawned anyway — advisory only


# ═══════════════════ 9. legacy emission-gate proof ════════════════════════
def test_legacy_recipe_and_plan_roundtrip_emit_no_new_keys():
    r = Recipe.model_validate(dict(
        recipe_id="legacy-r", user_goal_verbatim="g", domain="generic",
        state="executing", comprehension={"branches": [],
                                          "expected_outcomes": []},
        steps=[_step("s1")], context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    assert "workspace" not in r.model_dump(mode="json")

    p = Plan.model_validate(dict(
        plan_id="legacy-p", recipe_id="r", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "d",
                  "status": "pending", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "manual_review"}}],
    ))
    a = p.model_dump(mode="json")["actions"][0]
    assert "execution" not in a
    assert "commit" not in a["acceptance"]

    inline = Plan.model_validate(dict(
        plan_id="p2", recipe_id="r", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[_action("a1", execution="inline",
                         acceptance={"kind": "manual_review",
                                     "commit": "abc"})],
    ))
    a = inline.model_dump(mode="json")["actions"][0]
    assert a["execution"] == "inline"          # emitted only when set
    assert a["acceptance"]["commit"] == "abc"
