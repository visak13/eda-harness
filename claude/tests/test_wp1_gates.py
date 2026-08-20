"""WP1 write-gates (2026-08-12) — the df971d post-mortem class, made
structurally impossible:

  * override mechanism — user authorization is a RECORDED ARTIFACT (a
    `user_gate_answer` event minted by record_user_answer(gate_target=...)),
    never a free-text quote param;
  * G-STEP — a spawn_planner step cannot flip `done` without its plan
    terminal-succeeded (or a recorded user override), and close_recipe
    refuses laundered done-steps;
  * G-OUTCOME — a succeeded (or all-steps-done partial) close requires every
    outcome met or USER-waived;
  * G-SKIP / G-RUNS — a gate action cannot be skipped without a recorded
    user answer, and its `done` requires real execution evidence (runs);
  * terminal-subscription reaping — reconcile sweeps `.reactive`
    subscriptions whose owner is terminal (the 265k-poll storm);
  * emission-gate proof — legacy recipe/plan JSON round-trips with none of
    the new keys emitted.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Plan, Recipe

RID = "recipe-wp1"


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


def _recipe(env, rid=RID, steps=None, outcomes=None, state="executing"):
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state=state,
        comprehension={"branches": [], "expected_outcomes": outcomes or []},
        steps=steps if steps is not None else [_step("s1")],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))


def _outcome(oid="o1", met=False):
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


def _action(aid="a1", status="in_progress", gate=False):
    a = {"action_id": aid, "description": "d", "status": status,
         "depends_on": [], "executor_mode": "subagent",
         "acceptance": {"kind": "tests_pass",
                        "verify": {"check": "command", "cmd": "pytest -q"}}}
    if gate:
        a["gate"] = True
    return a


async def _gate_answer(env, rid, target,
                       answer="yes, go ahead — I accept that (user)"):
    res = await env.call("record_user_answer", recipe_id=rid,
                         gate_target=target, answer=answer)
    return _ok(res)["answer_id"]


# F43#1: the run must MATCH the declared verify cmd ("pytest -q") — the
# gate now reads the authored `cmd` key and matches token-contiguously.
_RUN = {"command": "uv run pytest -q", "exit_code": 0,
        "output_tail": "1 passed", "at": "2026-08-12T00:00:00+00:00"}


# ═══════════════════════════ 1. override mechanism ════════════════════════
async def test_gate_answer_recorded_and_validates(env):
    from edp_claude.tools._tools import _gate_override_ok
    _recipe(env)
    target = f"G-STEP:{RID}:s1"
    aid = await _gate_answer(env, RID, target)
    assert aid
    # the artifact exists on the events trail
    evs = env.ctx.recipes.read_events_tail(
        RID, kinds=["user_gate_answer"], limit=0)
    assert len(evs) == 1
    assert evs[0]["body"]["answer_id"] == aid
    assert evs[0]["body"]["gate_target"] == target
    # validates for the matching target only
    assert _gate_override_ok(env.ctx, RID, aid, target) is True
    assert _gate_override_ok(env.ctx, RID, aid, f"G-STEP:{RID}:s2") is False
    assert _gate_override_ok(env.ctx, RID, "not-an-id", target) is False
    assert _gate_override_ok(env.ctx, RID, None, target) is False


async def test_gate_answer_too_short_refused(env):
    _recipe(env)
    res = await env.call("record_user_answer", recipe_id=RID,
                         gate_target=f"G-STEP:{RID}:s1", answer="ok")
    msg = _err(res)
    assert "verbatim" in msg.lower()
    assert not env.ctx.recipes.read_events_tail(
        RID, kinds=["user_gate_answer"], limit=0)


async def test_gate_answer_mutually_exclusive_modes(env):
    _recipe(env)
    res = await env.call("record_user_answer", recipe_id=RID,
                         branch_id="b1", gate_target="G-STEP:x:y",
                         answer="a real user answer here")
    assert "mutually exclusive" in _err(res)


# ═══════════════════════════════ 2. G-STEP ════════════════════════════════
async def test_update_object_done_flip_refused_without_terminal_plan(env):
    _recipe(env, steps=[_step("s1", "in_progress")])
    _plan(env, RID, "s1", state="dispatching")
    res = await env.call("update_object", type="step",
                         ids={"recipe_id": RID, "step_id": "s1"},
                         patch={"status": "done"})
    msg = _err(res)
    assert "G-STEP" in msg
    assert f"G-STEP:{RID}:s1" in msg          # names the exact gate target
    assert "record_user_answer" in msg        # teaches the recorded path
    assert env.ctx.recipes.load(RID).steps[0].status == "in_progress"


async def test_record_step_result_refused_without_terminal_plan(env):
    _recipe(env, steps=[_step("s1", "in_progress")])
    _plan(env, RID, "s1", state="dispatching")
    res = await env.call("record_step_result", recipe_id=RID,
                         step_id="s1", result={"outputs": []})
    assert "G-STEP" in _err(res)
    assert env.ctx.recipes.load(RID).steps[0].status == "in_progress"


async def test_step_done_passes_on_terminal_succeeded_plan(env):
    _recipe(env, steps=[_step("s1", "in_progress")])
    _plan(env, RID, "s1", state="terminal", terminal_status="succeeded")
    _ok(await env.call("record_step_result", recipe_id=RID,
                       step_id="s1", result={"outputs": ["x"]}))
    assert env.ctx.recipes.load(RID).steps[0].status == "done"


async def test_step_done_with_valid_override_records_event(env):
    _recipe(env, steps=[_step("s1", "in_progress")])
    _plan(env, RID, "s1", state="dispatching")
    ref = await _gate_answer(env, RID, f"G-STEP:{RID}:s1")
    _ok(await env.call("update_object", type="step",
                       ids={"recipe_id": RID, "step_id": "s1"},
                       patch={"status": "done"}, override_ref=ref))
    assert env.ctx.recipes.load(RID).steps[0].status == "done"
    evs = env.ctx.recipes.read_events_tail(
        RID, kinds=["step_forced_done"], limit=0)
    assert len(evs) == 1
    assert evs[0]["step_id"] == "s1"
    assert evs[0]["override_ref"] == ref


async def test_step_override_wrong_target_still_refused(env):
    _recipe(env, steps=[_step("s1", "in_progress"), _step("s2")])
    _plan(env, RID, "s1", state="dispatching")
    ref = await _gate_answer(env, RID, f"G-STEP:{RID}:s2")   # wrong step
    res = await env.call("record_step_result", recipe_id=RID, step_id="s1",
                         result={}, override_ref=ref)
    assert "G-STEP" in _err(res)


async def test_close_refuses_laundered_step(env):
    # A done spawn_planner step whose plan never reached terminal-succeeded
    # (here: no plan at all) with met outcomes — the df971d close shape.
    _recipe(env, steps=[_step("s1", "done")],
            outcomes=[_outcome(met=True)], state="reviewing")
    res = await env.call("close_recipe", recipe_id=RID,
                         final_outcome={"status": "succeeded",
                                        "summary": "x"})
    msg = _err(res)
    assert "s1" in msg and "G-STEP" in msg
    assert env.ctx.recipes.load(RID).state != "closed"


async def test_close_passes_with_step_forced_done_event(env):
    _recipe(env, steps=[_step("s1", "in_progress")],
            outcomes=[_outcome(met=True)], state="reviewing")
    _plan(env, RID, "s1", state="dispatching")
    ref = await _gate_answer(env, RID, f"G-STEP:{RID}:s1")
    _ok(await env.call("record_step_result", recipe_id=RID, step_id="s1",
                       result={}, override_ref=ref))
    _ok(await env.call("close_recipe", recipe_id=RID,
                       final_outcome={"status": "succeeded",
                                      "summary": "forced by user"}))
    assert env.ctx.recipes.load(RID).state == "closed"


# ══════════════════════════════ 3. G-OUTCOME ══════════════════════════════
async def test_succeeded_close_refused_on_unmet_outcome(env):
    _recipe(env, steps=[_step("s1", "done")], outcomes=[_outcome()],
            state="reviewing")
    _plan(env, RID, "s1", state="terminal", terminal_status="succeeded")
    res = await env.call("close_recipe", recipe_id=RID,
                         final_outcome={"status": "succeeded",
                                        "summary": "x"})
    msg = _err(res)
    assert "o1" in msg
    assert f"G-OUTCOME:{RID}:o1" in msg


async def test_succeeded_close_passes_with_valid_waiver(env):
    _recipe(env, steps=[_step("s1", "done")], outcomes=[_outcome()],
            state="reviewing")
    _plan(env, RID, "s1", state="terminal", terminal_status="succeeded")
    ref = await _gate_answer(env, RID, f"G-OUTCOME:{RID}:o1")
    _ok(await env.call("close_recipe", recipe_id=RID,
                       final_outcome={"status": "succeeded", "summary": "x"},
                       outcome_waivers={"o1": ref}))
    r = env.ctx.recipes.load(RID)
    assert r.state == "closed"
    o = r.comprehension.expected_outcomes[0]
    assert o.waived is True
    assert o.waiver_ref == ref
    assert env.ctx.recipes.read_events_tail(
        RID, kinds=["outcome_waived"], limit=0)


async def test_waiver_with_wrong_target_refused(env):
    _recipe(env, steps=[_step("s1", "done")], outcomes=[_outcome()],
            state="reviewing")
    _plan(env, RID, "s1", state="terminal", terminal_status="succeeded")
    ref = await _gate_answer(env, RID, f"G-OUTCOME:{RID}:o2")  # wrong id
    res = await env.call("close_recipe", recipe_id=RID,
                         final_outcome={"status": "succeeded",
                                        "summary": "x"},
                         outcome_waivers={"o1": ref})
    assert "o1" in _err(res)


async def test_partial_all_steps_done_requires_waiver(env):
    # "partial, everything done, nothing met" is the laundering shape.
    _recipe(env, steps=[_step("s1", "done")], outcomes=[_outcome()],
            state="reviewing")
    _plan(env, RID, "s1", state="terminal", terminal_status="succeeded")
    res = await env.call("close_recipe", recipe_id=RID,
                         final_outcome={"status": "partial", "summary": "x"})
    assert f"G-OUTCOME:{RID}:o1" in _err(res)
    # with a recorded waiver it closes
    ref = await _gate_answer(env, RID, f"G-OUTCOME:{RID}:o1")
    _ok(await env.call("close_recipe", recipe_id=RID,
                       final_outcome={"status": "partial", "summary": "x"},
                       outcome_waivers={"o1": ref}))
    assert env.ctx.recipes.load(RID).state == "closed"


async def test_partial_with_unfinished_steps_stays_free(env):
    _recipe(env, steps=[_step("s1", "done"), _step("s2", "pending")],
            outcomes=[_outcome()], state="reviewing")
    _plan(env, RID, "s1", state="terminal", terminal_status="succeeded")
    _ok(await env.call("close_recipe", recipe_id=RID,
                       final_outcome={"status": "partial",
                                      "summary": "honest partial"}))
    assert env.ctx.recipes.load(RID).state == "closed"


# ═══════════════════════════ 4. G-SKIP / G-RUNS ═══════════════════════════
async def test_add_action_gate_derivation(env):
    _recipe(env, outcomes=[_outcome()])
    pid = _plan(env, RID, "s1")
    # serves + executable verify → derived gate=True
    _ok(await env.call("add_action", plan_id=pid, action_id="g1",
                       description="run the e2e suite", serves=["o1"],
                       verify={"check": "command", "cmd": "pytest -q"}))
    # serves, no verify → not derived
    _ok(await env.call("add_action", plan_id=pid, action_id="g2",
                       description="write notes", serves=["o1"]))
    # no serves, verify → not derived
    _ok(await env.call("add_action", plan_id=pid, action_id="g3",
                       description="tidy up",
                       verify={"check": "file_exists", "path": "x"}))
    # F35 R3b#8: UPGRADING stays free; DOWNGRADING a derived gate is the
    # planner waiving the user's gate — refused without a recorded user
    # answer against G-GATE:<plan>:<action>.
    res = await env.call("add_action", plan_id=pid, action_id="g4",
                         description="explicit off", serves=["o1"],
                         verify={"check": "command", "cmd": "pytest -q"},
                         gate=False)
    msg = _err(res)
    assert "G-GATE" in msg and f"G-GATE:{pid}:g4" in msg
    ans = _ok(await env.call(
        "record_user_answer", recipe_id=RID,
        gate_target=f"G-GATE:{pid}:g4",
        question="downgrade g4 from gate?",
        answer="yes — the user says this check is advisory here"))
    _ok(await env.call("add_action", plan_id=pid, action_id="g4",
                       description="explicit off", serves=["o1"],
                       verify={"check": "command", "cmd": "pytest -q"},
                       gate=False, override_ref=ans["answer_id"]))
    _ok(await env.call("add_action", plan_id=pid, action_id="g5",
                       description="explicit on", gate=True))
    gates = {a.action_id: a.gate for a in env.ctx.plans.load(pid).actions}
    assert gates == {"g1": True, "g2": False, "g3": False,
                     "g4": False, "g5": True}


async def test_skip_gate_action_refused_without_override(env):
    _recipe(env)
    pid = _plan(env, RID, "s1", actions=[_action(gate=True)])
    res = await env.call("record_action_status", plan_id=pid,
                         action_id="a1", status="skipped")
    msg = _err(res)
    assert "G-SKIP" in msg and f"G-SKIP:{pid}:a1" in msg
    assert env.ctx.plans.load(pid).actions[0].status == "in_progress"


async def test_skip_gate_action_with_override_records_worklog(env):
    _recipe(env)
    pid = _plan(env, RID, "s1", actions=[_action(gate=True)])
    ref = await _gate_answer(env, RID, f"G-SKIP:{pid}:a1")
    _ok(await env.call("record_action_status", plan_id=pid,
                       action_id="a1", status="skipped", override_ref=ref))
    assert env.ctx.plans.load(pid).actions[0].status == "skipped"
    wl = env.ctx.plans.read_worklog(pid, kinds=["gate_skipped_by_user"])
    assert wl and wl[-1]["override_ref"] == ref


async def test_done_gate_action_refused_without_runs(env):
    _recipe(env)
    pid = _plan(env, RID, "s1", actions=[_action(gate=True)])
    res = await env.call("record_action_status", plan_id=pid,
                         action_id="a1", status="done",
                         evidence="I verified it thoroughly, trust me")
    msg = _err(res)
    assert "G-RUNS" in msg and "not execution proof" in msg
    assert env.ctx.plans.load(pid).actions[0].status == "in_progress"


async def test_done_gate_action_refuses_invalid_run_entries(env):
    _recipe(env)
    pid = _plan(env, RID, "s1", actions=[_action(gate=True)])
    res = await env.call(
        "record_action_status", plan_id=pid, action_id="a1", status="done",
        evidence="e", runs=[{"command": "", "exit_code": 0},
                            {"command": "pytest", "exit_code": "0"},
                            {"command": "pytest", "exit_code": True}])
    assert "G-RUNS" in _err(res)


async def test_done_gate_action_with_runs_persists_them(env):
    _recipe(env)
    pid = _plan(env, RID, "s1", actions=[_action(gate=True)])
    _ok(await env.call("record_action_status", plan_id=pid,
                       action_id="a1", status="done",
                       evidence="suite green", runs=[_RUN]))
    a = env.ctx.plans.load(pid).actions[0]
    assert a.status == "done"
    assert a.acceptance.runs == [_RUN]


async def test_non_gate_action_legacy_done_and_optional_runs(env):
    _recipe(env)
    pid = _plan(env, RID, "s1",
                actions=[_action("a1"), _action("a2")])
    # legacy: evidence-only done still lands (byte-identical behavior)
    _ok(await env.call("record_action_status", plan_id=pid,
                       action_id="a1", status="done", evidence="claim"))
    # runs accepted + persisted when provided, never required
    _ok(await env.call("record_action_status", plan_id=pid,
                       action_id="a2", status="done",
                       evidence="claim", runs=[_RUN]))
    p = env.ctx.plans.load(pid)
    assert p.actions[0].status == "done"
    assert p.actions[0].acceptance.runs == []
    assert p.actions[1].acceptance.runs == [_RUN]
    # skip on a non-gate action needs no override (legacy)
    pid2 = _plan(env, RID, "s2", actions=[_action("b1")])
    _ok(await env.call("record_action_status", plan_id=pid2,
                       action_id="b1", status="skipped"))


# ═════════════════════ 5. terminal-subscription reaping ═══════════════════
def _sub_artifacts(root: Path, sid: str):
    (root / f"{sid}.spec").write_text("rx.worklog(plan_id)",
                                      encoding="utf-8")
    (root / f"{sid}.bindings.json").write_text("{}", encoding="utf-8")
    (root / f"{sid}.effect.json").write_text("{}", encoding="utf-8")


async def test_reap_removes_only_terminal_owner_subscriptions(env):
    from edp_claude.reactive import handle_index as hindex
    from edp_claude.tools._tools import _reap_terminal_subscriptions

    _recipe(env)
    dead_pid = _plan(env, RID, "s1", state="terminal",
                     terminal_status="succeeded")
    live_pid = _plan(env, RID, "s2", state="dispatching")
    root = env.ctx.recipes.root.parent / ".reactive"
    root.mkdir(parents=True, exist_ok=True)
    _sub_artifacts(root, "sub-dead1")
    _sub_artifacts(root, "sub-live1")
    hindex.register_subscription(root, dead_pid, "sub-dead1")
    hindex.register_subscription(root, live_pid, "sub-live1")

    reaped = _reap_terminal_subscriptions(env.ctx, root)
    assert reaped == ["sub-dead1"]
    for suffix in (".spec", ".bindings.json", ".effect.json"):
        assert not (root / f"sub-dead1{suffix}").exists()
        assert (root / f"sub-live1{suffix}").exists()
    idx = json.loads((root / "handle_index.json").read_text("utf-8"))
    assert dead_pid not in idx
    assert idx[live_pid] == ["sub-live1"]


async def test_reap_colon_handle_and_closed_recipe(env):
    from edp_claude.reactive import handle_index as hindex
    from edp_claude.tools._tools import _reap_terminal_subscriptions

    # closed recipe handle + colon-form plan handle both resolve terminal
    _recipe(env, steps=[_step("s1", "done")], state="reviewing")
    _plan(env, RID, "s1", state="terminal", terminal_status="succeeded")
    r = env.ctx.recipes.load(RID)
    from edp_claude.schemas.instruction import RecipeState
    r.state = RecipeState.CLOSED
    r.final_outcome = {"status": "abandoned", "summary": "x"}
    env.ctx.recipes.save(r)

    root = env.ctx.recipes.root.parent / ".reactive"
    root.mkdir(parents=True, exist_ok=True)
    _sub_artifacts(root, "sub-c1")
    _sub_artifacts(root, "sub-r1")
    hindex.register_subscription(root, f"{RID}:s1", "sub-c1")   # colon form
    hindex.register_subscription(root, RID, "sub-r1")           # recipe

    reaped = _reap_terminal_subscriptions(env.ctx, root)
    assert sorted(reaped) == ["sub-c1", "sub-r1"]
    idx = json.loads((root / "handle_index.json").read_text("utf-8"))
    assert idx == {}


# ═══════════════════════ 6. legacy emission-gate proof ════════════════════
def test_legacy_recipe_roundtrip_emits_no_new_keys():
    r = Recipe.model_validate(dict(
        recipe_id="legacy-r", user_goal_verbatim="g", domain="generic",
        state="reviewing",
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v"}]},
        steps=[_step("s1", "done")], context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    dumped = r.model_dump(mode="json")
    o = dumped["comprehension"]["expected_outcomes"][0]
    assert "waived" not in o
    assert "waiver_ref" not in o


def test_legacy_plan_roundtrip_emits_no_new_keys():
    p = Plan.model_validate(dict(
        plan_id="legacy-p", recipe_id="r", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "d",
                  "status": "pending", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "manual_review"}}],
    ))
    dumped = p.model_dump(mode="json")
    a = dumped["actions"][0]
    assert "gate" not in a
    assert "runs" not in a["acceptance"]
