"""s26 — shell lifecycle, reviewer verdicts, and cross-step context aliasing.

Three defects, one file (the s26/a4 acceptance gate).

ITEM 1 — A WORKER CAN END ITS TURN BEFORE CLOSING ITSELF.
    Closing was the last line of a TEXT guide, and nothing compels a further
    assistant turn after a worker emits its report. A worker that stops to
    report never resumes: it deletes its cron, replies in chat, and idles at a
    prompt holding RAM until a human closes it. The fix is STRUCTURAL —
    reporting a TERMINAL status ARMS the pool to reap the reporting shell once
    it falls idle, so closure is a CONSEQUENCE of reporting, not an act of will.

    The reproduction below is the test: a worker records `done` and then ENDS
    ITS TURN — it never calls `pool_close_self` — and the shell is still
    scheduled for reaping. Before the fix nothing was armed and it idled forever.
    (The reap ITSELF, against a real OS process, is proved in the edp-pool tree:
    edp-pool/tests/test_s26_close_when_idle.py. `edp_pool` is not importable
    from this venv, so the two halves are tested where each half lives.)

ITEM 6 — THE REVIEWER LEG CANNOT STAMP ITS VERDICT (two stacked defects).
    FUNCTION: `record_branch_verdict` resolved ONLY `recipe.comprehension.
    branches`, so a verdict on a plan ACTION got "no branch <id>". It failed in
    WARN mode, today, independent of role scope.
    ROLE: a planner's only spawn verb hardcoded EDP_ROLE=worker, so a
    planner-authored REVIEWER leg ran as a worker.
    Fixing either alone leaves the other standing. Both directions are asserted:
    a reviewer CAN stamp an action verdict, and a worker still CANNOT bless its
    own action.

ITEM 13 — injected_context ALIASES ACROSS STEPS.
    `pool_spawn_worker` stamped EVERY active load-bearing decision onto EVERY
    action, recipe-wide, with no notion of scope. A decision recorded under plan
    X whose text addressed "Reviewer a4" was stamped verbatim into plan Y's a4,
    which read it as its own instruction. Action ids are meaningful only RELATIVE
    TO A PLAN, and the stamp erased that relativity.

Every assertion here was MUTATION-PROVED: the guarded line was mutated, the test
observed RED at the named site, and the mutation was reverted. See the evidence
recorded on the action.
"""
import os

import pytest
from edp_contracts import ToolOk

# A verdict must clear the ≥40-char substance bar; rubber-stamping is refused.
_SUBSTANTIVE = (
    "Re-ran the acceptance command in a fresh shell: 12 passed, 0 failed. "
    "The mutation reddens test_x at the named site. Passes."
)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _err(res):
    assert not isinstance(res, ToolOk), f"expected a refusal, got ok: {res}"
    return str(getattr(res, "message", res))


async def _plan_with_action(env, action_id="a1", *, goal="g", step="build"):
    """Minimal recipe → step → plan → one generic action (passes Guard B)."""
    rid = _ok(await env.call("start_recipe", goal=goal, domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description=step,
                             execution="spawn_planner", estimate={"hours": 1}))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal=goal))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id=action_id,
                       description="do generic work"))
    return rid, pid


def _be_the_shell_for(monkeypatch, plan_id, action_id, session="sess-1"):
    """Impersonate the pool-spawned shell that OWNS `plan_id:action_id`.

    The pool stamps these vars at spawn (pty_launcher), so within the TOOL layer a
    shell's identity is read from an environment the pool owns rather than from
    anything the shell says about itself.

    STATE THE BOUND, DO NOT OVERSTATE IT (s29/a3b). This docstring used to close by
    claiming a shell is INCAPABLE of forging another's identity, and a reader would
    remember that as a security property. IT IS NOT ONE. It holds only for the
    ENV-var channel these tests monkeypatch. It is FALSE of the plane where identity
    actually travels: `broker_send` takes `from_` AS A PARAMETER, so any shell may
    claim any handle in a message without touching the environment at all. **No
    message field in this system certifies its author** — authorship is established
    out-of-band (by asking the human) or not at all.
    """
    monkeypatch.setenv("EDP_HANDLE", f"{plan_id}:{action_id}")
    monkeypatch.setenv("EDP_SPAWN_SESSION_ID", session)
    monkeypatch.setenv("EDP_ROLE", "worker")


def _post_grounding_echo(env, plan_id, action_id):
    """v7 P3.1: a worker's terminal record_action_status is refused unless the
    shell posted its grounding echo (restating the directive) first. Tests that
    impersonate a well-behaved worker do what the worker does — the same
    worklog line notify_above(kind='grounding') leaves behind."""
    env.ctx.plans.append_worklog(plan_id, {
        "kind": "message_sent", "agent_role": "worker",
        "to": plan_id, "msg_kind": "grounding",
        "from_handle": f"{plan_id}:{action_id}",
        "summary": "{'restatement': 'do generic work', "
                   "'will_verify_by': 'evidence'}",
    })


# ══════════════════════════════════════════════════════════════════════════
# ITEM 1 — the worker-shell leak
# ══════════════════════════════════════════════════════════════════════════

async def test_worker_that_ends_its_turn_with_a_report_is_reaped(env, monkeypatch):
    """THE REPRODUCTION. The worker reports and STOPS. It never calls
    pool_close_self — that is the whole bug. The shell must still be scheduled
    for reaping, with no human intervention.

    Before the structural fix this asserted nothing that existed: no arm was
    ever recorded, and the shell idled at a prompt until a human closed it.
    """
    _rid, pid = await _plan_with_action(env)
    _be_the_shell_for(monkeypatch, pid, "a1", session="sess-leak")
    _post_grounding_echo(env, pid, "a1")

    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status="done", evidence="wrote the file; suite green"))

    # ...and now the worker's turn ENDS. Nothing else is called. Notably NOT:
    #     await env.call("pool_close_self")

    armed = env.ctx.pool.armed_closes
    assert len(armed) == 1, (
        "a worker recorded a TERMINAL status and ended its turn without "
        "closing itself, and NOTHING armed its reap — this is the leak: the "
        f"shell idles at a prompt holding RAM until a human closes it. {armed}")
    assert armed[0]["session_id"] == "sess-leak"
    assert armed[0]["idle_secs"] > 0, "an arm with no grace window would kill " \
        "a shell mid-flush"
    assert "done" in armed[0]["reason"]


async def test_evidence_is_durable_before_the_reap_is_armed(env, monkeypatch):
    """ORDERING, required by the s26 planner: persist status + evidence, confirm
    the write, THEN arm. Never arm-then-write.

    This matters because the independent REVIEWER's last act is a terminal
    record_action_status. If the reap could race the write, the verdict — the
    objective gate of the whole step — would be lost, and under the scope freeze
    there is no second attempt.

    Proved by reading the STORE from inside the arm call: whatever the pool sees
    at arm time, the evidence is already on disk.
    """
    _rid, pid = await _plan_with_action(env)
    _be_the_shell_for(monkeypatch, pid, "a1")
    _post_grounding_echo(env, pid, "a1")
    seen: dict = {}

    real_arm = env.ctx.pool.close_when_idle

    async def spy(session_id, idle_secs, reason=""):
        # Re-LOAD from the store, not from memory: this is what "durable" means.
        p = env.ctx.plans.load(pid)
        a = next(x for x in p.actions if x.action_id == "a1")
        seen["evidence_at_arm_time"] = a.acceptance.actual
        seen["status_at_arm_time"] = a.status
        return await real_arm(session_id, idle_secs, reason)

    monkeypatch.setattr(env.ctx.pool, "close_when_idle", spy)
    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status="done", evidence="the verdict text"))

    assert seen["evidence_at_arm_time"] == "the verdict text", (
        "the reap was armed BEFORE the evidence reached disk — a reviewer "
        "reaped at that moment would lose its verdict")
    assert seen["status_at_arm_time"] == "done"

    # And it survives after the shell is gone: the store is the record.
    await env.ctx.pool.release("sess-1")
    a = next(x for x in env.ctx.plans.load(pid).actions if x.action_id == "a1")
    assert a.acceptance.actual == "the verdict text"


@pytest.mark.parametrize("status", ["in_progress", "needs_review", "pending"])
async def test_non_terminal_status_never_arms(env, monkeypatch, status):
    """A shell that is still working, or awaiting a bounce-back, is not done."""
    _rid, pid = await _plan_with_action(env)
    _be_the_shell_for(monkeypatch, pid, "a1")
    await env.call("record_action_status", plan_id=pid, action_id="a1",
                   status=status, evidence="still going")
    assert env.ctx.pool.armed_closes == [], (
        f"{status!r} is not terminal — arming here reaps a working shell")


async def test_a_planner_reporting_a_dead_workers_action_never_reaps_itself(
        env, monkeypatch):
    """THE CATASTROPHIC CASE, and why "a terminal status releases the calling
    session" is unsound as stated.

    `record_action_status` takes an ARBITRARY plan_id + action_id, and the
    PLANNER calls it too: its crash-recovery path records a dead worker's action
    as `failed`. If a terminal status released the CALLER's session, the planner
    would reap ITSELF the moment it cleaned up after a worker.

    The caller is not necessarily the action's owner. So the arm is gated on the
    caller's own handle naming the action.
    """
    _rid, pid = await _plan_with_action(env)
    # The planner's handle is <recipe_id>:<step_id> — never <plan_id>:<action_id>.
    monkeypatch.setenv("EDP_HANDLE", "some-recipe:s1")
    monkeypatch.setenv("EDP_SPAWN_SESSION_ID", "the-planners-own-session")
    monkeypatch.setenv("EDP_ROLE", "planner")

    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status="failed", evidence="worker died at startup"))

    assert env.ctx.pool.armed_closes == [], (
        "the PLANNER armed its own reap while recording a WORKER's failure — "
        "this would kill the planner mid-plan")


async def test_a_shell_with_no_pool_session_is_never_armed(env, monkeypatch):
    """R10: the neuron's foreground shell and the user's terminal are also
    claude.exe. They carry no EDP_SPAWN_SESSION_ID, so they can never be armed.
    Arming requires a session id the pool itself issued."""
    _rid, pid = await _plan_with_action(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.delenv("EDP_SPAWN_SESSION_ID", raising=False)

    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status="done", evidence="done in the foreground"))
    assert env.ctx.pool.armed_closes == []


async def test_a_worker_that_does_close_itself_still_closes_cleanly(
        env, monkeypatch):
    """The path a1/a2/a3 took must not regress: record terminal status, then run
    the close sequence in the same turn. Arming must not make `pool_close_self`
    error, and the arm is a no-op once the shell has closed itself."""
    _rid, pid = await _plan_with_action(env)
    _be_the_shell_for(monkeypatch, pid, "a1", session="sess-clean")
    _post_grounding_echo(env, pid, "a1")

    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status="done", evidence="green"))
    res = await env.call("pool_close_self")   # the well-behaved worker's close
    assert isinstance(res, ToolOk), f"close broke after arming: {res}"


# ══════════════════════════════════════════════════════════════════════════
# ITEM 6 — the reviewer leg's verdict
# ══════════════════════════════════════════════════════════════════════════

async def test_worker_terminal_report_without_grounding_echo_is_refused(
        env, monkeypatch):
    """v7 P3.1 — the silent-consume defense. A worker that never restated its
    directive (notify_above kind='grounding') cannot claim a result; the
    refusal names the fix. d101(4): 'a surface that accepts a directive it
    does not consume, and stays silent' — made structurally impossible."""
    _rid, pid = await _plan_with_action(env)
    _be_the_shell_for(monkeypatch, pid, "a1")
    msg = _err(await env.call("record_action_status", plan_id=pid,
                              action_id="a1", status="done", evidence="green"))
    assert "grounding echo" in msg
    assert "notify_above" in msg
    a = next(x for x in env.ctx.plans.load(pid).actions if x.action_id == "a1")
    assert a.status != "done", "the refusal must record nothing"


async def test_reviewer_cannot_record_status_on_a_reviewed_action(
        env, monkeypatch):
    """v7 P4.1's other half — the grant is OWN-LEG ONLY. A reviewer stamping
    status on the action it REVIEWED would be the self-blessing-by-proxy d30
    forbids; the refusal points at record_branch_verdict."""
    _rid, pid = await _plan_with_action(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a9")   # my leg is a9
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    msg = _err(await env.call("record_action_status", plan_id=pid,
                              action_id="a1", status="done",
                              evidence="looks good"))
    assert "record_branch_verdict" in msg
    a = next(x for x in env.ctx.plans.load(pid).actions if x.action_id == "a1")
    assert a.status != "done"


async def test_reviewer_can_stamp_an_action_level_verdict(env, monkeypatch):
    """DIRECTION 1. The defect: branch_id='s25' → tool_precondition "no branch
    s25", because only comprehension branches resolved. A reviewer leg could not
    stamp the verdict that d29/d30 make the objective gate."""
    rid, pid = await _plan_with_action(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a9")   # the REVIEWER's own action
    monkeypatch.setenv("EDP_ROLE", "reviewer")

    _ok(await env.call("record_branch_verdict", recipe_id=rid, plan_id=pid,
                       branch_id="a1", verdict=_SUBSTANTIVE))

    a = next(x for x in env.ctx.plans.load(pid).actions if x.action_id == "a1")
    assert a.review_verdict is not None, "the verdict had nowhere to land"
    assert a.review_verdict["verdict"] == _SUBSTANTIVE
    assert a.review_verdict["by"] == f"{pid}:a9"


async def test_a_worker_cannot_bless_its_own_action(env, monkeypatch):
    """DIRECTION 2, and the trap the brief names. A fix that lets ANYONE stamp
    ANYTHING passes direction 1 and guards nothing.

    Note this guard is IN THE TOOL, not in the role table: EDP_ROLE_SCOPE is
    warn-mode, so the role table would only log a violation and proceed.
    """
    rid, pid = await _plan_with_action(env)
    _be_the_shell_for(monkeypatch, pid, "a1")   # I am a1, blessing a1

    msg = _err(await env.call("record_branch_verdict", recipe_id=rid,
                              plan_id=pid, branch_id="a1",
                              verdict=_SUBSTANTIVE))
    assert "own action" in msg.lower()
    a = next(x for x in env.ctx.plans.load(pid).actions if x.action_id == "a1")
    assert a.review_verdict is None, "a worker blessed its own action (d30)"


async def test_record_branch_verdict_is_not_on_the_worker_surface():
    """The (c) remedy is the trap: granting this verb to _WORKER is exactly the
    self-blessing d30 forbids. Independent of the in-tool guard above."""
    from edp_claude.tools.roles import ROLE_TOOLSETS
    assert "record_branch_verdict" not in ROLE_TOOLSETS["worker"]
    assert "record_branch_verdict" in ROLE_TOOLSETS["reviewer"]


@pytest.mark.parametrize("worker_status", ["done", "failed"])
async def test_a_verdict_never_touches_status_or_acceptance(
        env, monkeypatch, worker_status):
    """d30's separation, made structural: a reviewer records a JUDGEMENT; only
    the worker that executed an action records that action's STATUS. A reviewer
    that could flip an action to `done` would be blessing it.

    `failed` is the discriminating case and the reason this is parametrized
    (s26/a5). With `done` alone, `assert a.status == "done"` passes whether or
    not the verdict touched status — the mutation that flips it writes the value
    the WORKER already wrote, so the assertion guards nothing. Only a status the
    verdict would have to CHANGE can witness the separation.
    """
    rid, pid = await _plan_with_action(env)
    _be_the_shell_for(monkeypatch, pid, "a1")
    _post_grounding_echo(env, pid, "a1")
    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status=worker_status,
                       evidence="the worker's own evidence"))

    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a9")
    _ok(await env.call("record_branch_verdict", recipe_id=rid, plan_id=pid,
                       branch_id="a1", verdict=_SUBSTANTIVE))

    a = next(x for x in env.ctx.plans.load(pid).actions if x.action_id == "a1")
    assert a.status == worker_status, (
        "the reviewer's verdict CHANGED the action's status — a reviewer "
        "records a judgement, not a status (d30)")
    assert a.acceptance.actual == "the worker's own evidence", \
        "the reviewer overwrote the worker's evidence"


async def test_a_shallow_action_verdict_is_refused(env, monkeypatch):
    rid, pid = await _plan_with_action(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a9")
    msg = _err(await env.call("record_branch_verdict", recipe_id=rid,
                              plan_id=pid, branch_id="a1", verdict="lgtm"))
    assert "shallow" in msg.lower()


async def test_an_unknown_action_is_refused(env, monkeypatch):
    rid, pid = await _plan_with_action(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a9")
    msg = _err(await env.call("record_branch_verdict", recipe_id=rid,
                              plan_id=pid, branch_id="nope",
                              verdict=_SUBSTANTIVE))
    assert "no action" in msg.lower()


async def test_comprehension_branch_path_is_unchanged(env):
    """Back-compat: without plan_id this is the neuron's OCAK verb, verbatim.
    That is the tool's original and still-correct purpose (ocak.md)."""
    from edp_claude.schemas.recipe import Branch
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    r = env.ctx.recipes.load(rid)
    # next_action seeds the OCAK checklist; construct one directly so this test
    # asserts the verdict path, not the seeding order.
    r.comprehension.branches.append(
        Branch(id="b1", question="what is in scope?", status="open"))
    env.ctx.recipes.save(r)
    bid = "b1"

    _ok(await env.call("record_branch_verdict", recipe_id=rid, branch_id=bid,
                       verdict=_SUBSTANTIVE))
    b = next(b for b in env.ctx.recipes.load(rid).comprehension.branches
             if b.id == bid)
    assert b.status == "resolved" and b.verdict == _SUBSTANTIVE


async def test_missing_branch_error_points_at_the_action_path(env):
    """The old message was a dead end. It now names the escape."""
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    msg = _err(await env.call("record_branch_verdict", recipe_id=rid,
                              branch_id="s25", verdict=_SUBSTANTIVE))
    assert "plan_id" in msg, msg


async def test_spawn_worker_role_defaults_to_worker(env):
    """BINDING (s26 planner): this plan's reviewer leg a5 is already dispatched
    as a worker and RELIES on record_action_status, which the reviewer surface
    does not carry. Flipping the default would sever a5's evidence channel
    mid-plan. Opting in is the planner's explicit act."""
    _rid, pid = await _plan_with_action(env)
    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    assert env.ctx.pool.spawns[-1]["role"] == "worker"


async def test_spawn_worker_can_dispatch_a_reviewer_role_leg(env):
    """ROLE DEFECT fixed: the planner's only spawn verb hardcoded
    EDP_ROLE=worker, so a planner-authored reviewer leg ran as a worker and
    never loaded reviewer.md."""
    _rid, pid = await _plan_with_action(env)
    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1",
                   role="reviewer")
    assert env.ctx.pool.spawns[-1]["role"] == "reviewer"


async def test_spawn_role_is_an_allowlist_not_a_free_string(env):
    """The pool maps role → activator and stamps EDP_ROLE from it. An arbitrary
    role would let a planner mint a shell of ANY role, including `neuron`."""
    _rid, pid = await _plan_with_action(env)
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1",
                         role="neuron")
    assert not isinstance(res, ToolOk), "a planner minted a neuron shell"


async def test_reviewer_surface_record_action_status_is_the_p41_grant():
    """SUPERSEDED PIN, updated with the design (DESIGN-v7 P4.1).

    This test used to pin the ABSENCE of `record_action_status` from _REVIEWER
    (the s26 argument: arbitrary plan_id+action_id = new reach, the d62/d30
    objection). That absence is exactly what degraded review legs into
    worker-role dispatches (the d67/d100 no-op class), so P4.1 grants the verb
    ON THE REVIEWER FLOOR — paired with an in-tool own-leg scope guard (under
    EDP_ROLE=reviewer only `<plan_id>:<action_id> == EDP_HANDLE` is writable),
    which is P4.1's other half and carries its own tests. The w4 ceiling bump
    (reviewer 17 -> 18) landed with the grant; this is its twin pin."""
    from edp_claude.tools.roles import ROLE_TOOLSETS
    assert "record_action_status" in ROLE_TOOLSETS["reviewer"]
    assert "record_action_status" in ROLE_TOOLSETS["worker"]


# ══════════════════════════════════════════════════════════════════════════
# ITEM 13 — cross-step injected_context aliasing
# ══════════════════════════════════════════════════════════════════════════

async def _two_plans(env):
    """One recipe, two plans, each with its OWN action named `a4`. This is the
    exact shape that aliased: "a4" in s18 vs "a4" in s24."""
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    pids = []
    for n in ("first", "second"):
        sid = _ok(await env.call("add_step", recipe_id=rid, description=n,
                                 execution="spawn_planner", estimate={"hours": 1}))["step_id"]
        pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                                 shape="poc-iterate-build", goal=n))["plan_id"]
        _ok(await env.call("add_action", plan_id=pid, action_id="a4",
                           description="do generic work"))
        pids.append(pid)
    return rid, pids[0], pids[1]


def _stamped_texts(env, pid, action_id="a4"):
    p = env.ctx.plans.load(pid)
    a = next(x for x in p.actions if x.action_id == action_id)
    ids = (a.injected_context_ids or {}).get("load_bearing_decisions", [])
    return [(p.injected_context or {})[i] for i in ids]


async def test_a_decision_scoped_to_one_plan_does_not_alias_into_another(env):
    """THE BUG, reproduced. A decision written under plan ONE addressing
    "Reviewer a4" must not be stamped into plan TWO's same-named a4, which would
    read it as its own instruction."""
    rid, one, two = await _two_plans(env)
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="Reviewer a4 owns the test fix in THIS step",
                       load_bearing=True, scope_plan_id=one))

    await env.call("pool_spawn_worker", plan_id=two, action_id="a4")

    assert not any("Reviewer a4" in t for t in _stamped_texts(env, two)), (
        "a decision scoped to another step was stamped into THIS step's "
        "same-named action — the worker reads another step's instructions "
        "as its own")


async def test_a_scoped_decision_is_still_delivered_to_its_own_plan(env):
    """DIRECTION 2. A fix that just drops scoped decisions everywhere passes the
    test above and silently starves the action the decision was written for."""
    rid, one, _two = await _two_plans(env)
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="Reviewer a4 owns the test fix in THIS step",
                       load_bearing=True, scope_plan_id=one))

    await env.call("pool_spawn_worker", plan_id=one, action_id="a4")

    assert any("Reviewer a4" in t for t in _stamped_texts(env, one)), (
        "the decision never reached the action it was actually addressed to")


async def test_an_unscoped_decision_stays_recipe_wide(env):
    """Back-compat, and the honest bound of this fix: `scope_plan_id=None` — the
    default and EVERY legacy decision — is recipe-wide exactly as before. This
    fix adds the mechanism and honours it at selection; it cannot retroactively
    scope a decision nobody scoped. That remains the neuron's to scope or
    supersede, and is surfaced rather than rewritten here."""
    rid, one, two = await _two_plans(env)
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="MiniLM is the settled embedder; never nomic",
                       load_bearing=True))

    for pid in (one, two):
        await env.call("pool_spawn_worker", plan_id=pid, action_id="a4")
        assert any("never nomic" in t for t in _stamped_texts(env, pid)), (
            "an unscoped (recipe-wide) decision stopped reaching workers — "
            "this fix must be purely additive")


async def test_scope_is_emission_gated_so_legacy_decisions_are_byte_identical(env):
    """o6 discipline: an unscoped decision must serialize byte-shape-identical
    to the pre-change schema, so a pre-restart extra='forbid' reader never sees
    the new key and the 0e7ca8 fixture round-trips."""
    from edp_claude.schemas import Decision
    from datetime import datetime, timezone

    base = dict(id="d1", text="t", rationale="r", by="neuron",
                at=datetime(2026, 7, 9, tzinfo=timezone.utc))
    assert "scope_plan_id" not in Decision(**base).model_dump()
    assert Decision(**base, scope_plan_id="p-s1").model_dump()[
        "scope_plan_id"] == "p-s1"


async def test_review_verdict_is_emission_gated(env):
    """Same discipline for the new Action field: an unreviewed action serializes
    without the key."""
    _rid, pid = await _plan_with_action(env)
    a = next(x for x in env.ctx.plans.load(pid).actions if x.action_id == "a1")
    assert "review_verdict" not in a.model_dump()


async def test_legacy_full_text_injected_context_still_passes_through(env):
    """o6 / pre-RP-A back-compat: an OLD action carries full-text
    `injected_context` and no id pointer. The read view passes it through
    unchanged — the scope filter runs at STAMP time and must not touch it."""
    from edp_claude import objects
    _rid, pid = await _plan_with_action(env)
    p = env.ctx.plans.load(pid)
    p.actions[0].injected_context = {
        "load_bearing_decisions": ["legacy never-nomic text"]}
    env.ctx.plans.save(p)

    view = await objects.read_object(env.ctx, "action", plan_id=pid,
                                     action_id="a1")
    assert view["injected_context"]["load_bearing_decisions"] == [
        "legacy never-nomic text"]
