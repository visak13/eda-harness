"""DESIGN-v6 W10b — spawn model resolution + the stuck→consult escalation
ladder. RE-POINTED (2026-08-12 dead-surface retirement): the MODEL_TIERS
table and its lookups (resolve_model_tier / HOST_DEFAULT_MODEL / SONNET /
DEFAULT_TASK_CLASS) are DELETED — the v7 WS4 seat registry (models.json via
edp_contracts.seats) is the only role→model binding, and `spawn_model_for`
resolves ONLY through it. The old T1–T5 pinned the table's shape and its
never-auto-candidate discipline; their subject is gone, so they are replaced
by seat-registry pins of the SAME properties (an un-configured spawn passes
no --model; the registry binding really reaches the pool).

The bar this pins:

* T2  with NO registry, spawn_model_for resolves None for every role — the
      spawn passes no --model flag and the pool config default rules. The
      legacy `task_class` / `allow_candidate_tier` params are accepted and
      IGNORED (the retired table was their only consumer).
* T3  a registry-mapped role's pinned model reaches the pool spawn VERBATIM,
      driven through the real pool_spawn_worker tool; an un-mapped spawn is
      byte-identical to pre-W10b (model=None).
* T6  the escalation ladder. Two failed acceptance CYCLES emit ESCALATE_CONSULT
      with an auto-composed, non-empty, action-specific question — and ONE cycle
      reported through BOTH d30 seams counts ONCE and emits NOTHING. The
      instruction carries NO `model` key: the tier it used to name was retired
      with the table (how a raised question is answered is the parent's call).
* T6b the emission is LATCHED and ADVISORY: it fires once per signal crossing and
      the very next tick dispatches. An un-latched instruction would wedge the
      plan — the control mechanism d76 forbids.
* T7  NO cost_report tool is registered on the MCP surface (d77, user ruling).
* T8  the legacy fixture 0e7ca8 loads byte-identically with the new counter
      fields present (o6; lazy migration, no rewrite) — recipe AND its plans.
* T9  the residual W10a item is ALREADY LANDED. The brief (inheriting DESIGN-v6
      W10b) said the tool-level planner spawn "still doesn't accept/pass model".
      It does. Pinned rather than re-plumbed, so the claim cannot rot again.

Env discipline (d7): EDP_ROLE/EDP_HANDLE/EDP_TIER_WRITE leaking from the
launching worker shell are neutralised in-process by the autouse conftest
fixture. Every assertion is done in PYTHON — the verify shell has no `grep`
(d8/R11: PowerShell host, no POSIX tools).
"""

import copy
import inspect
import json
from pathlib import Path

from edp_contracts import ToolOk

from edp_claude.fsm.plan_fsm import (
    STUCK_VERIFY_FAILURES_THRESHOLD,
    bump_verify_failure,
    compose_consult_question,
    plan_next_action,
)
from edp_claude.schemas import InstructionKind, Plan, PlanState, Recipe
from edp_claude.tools.roles import spawn_model_for

K = InstructionKind

#: an arbitrary exact model id for pass-through assertions (T3/T9); nothing
#: resolves it — it only proves the wire carries what a caller/registry pins.
PINNED_MODEL = "claude-sonnet-5"

_ROOT = Path(__file__).resolve().parents[1]
_RECIPES = _ROOT / ".recipes"
_PLANS = _ROOT / ".plans"
LEGACY_RID = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


# ── T1/T2 — the table is RETIRED; the resolver is registry-only ────────────
# (T1/T1b/T2b — the measured/candidate discipline and its benchmark-doc sync —
# are REMOVED with their subject, the 2026-08-12 dead-surface retirement of
# MODEL_TIERS. Their doc-side residue is pinned in test_w10b_benchmark.py.)
def test_t2_without_a_registry_every_spawn_resolves_no_model(monkeypatch):
    """The universal the old T2 pinned — an un-opted-in spawn passes NO --model
    flag — survives the table it was pinned on. With no seat registry there is
    nothing to resolve: every role, every task_class, flag or no flag, is None,
    and the pool config's pinned default model rules the spawned shell."""
    monkeypatch.delenv("EDP_AGENT_HOME", raising=False)
    for role in ("neuron", "planner", "worker", "reviewer", "specialist",
                 "curiosity", "no-such-role"):
        assert spawn_model_for(role) is None, role
        # the legacy tier-table params are accepted and IGNORED — the retired
        # table was their only consumer; neither may conjure a model.
        assert spawn_model_for(role, "coding") is None, role
        assert spawn_model_for(role, "narrow",
                               allow_candidate_tier=True) is None, role


def test_t2c_a_registry_binding_wins_and_ignores_the_legacy_flags(
        tmp_path, monkeypatch):
    """A mapped seat's pinned model is returned VERBATIM — and the legacy
    params still change nothing (explicit seat beats every implicit path)."""
    (tmp_path / "models.json").write_text(json.dumps({
        "seats": {"w": {"model": PINNED_MODEL}},
        "roles": {"worker": "w"},
    }), encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    assert spawn_model_for("worker") == PINNED_MODEL
    assert spawn_model_for("worker", "coding") == PINNED_MODEL
    assert spawn_model_for("worker", "narrow",
                           allow_candidate_tier=True) == PINNED_MODEL
    # unmapped role in a PRESENT registry → still no flag
    assert spawn_model_for("planner") is None


# ── T3 ─────────────────────────────────────────────────────────────────────
async def _recipe_with_plan(env, goal="make the CSV totals line up"):
    rid = _ok(await env.call("start_recipe", goal=goal,
                             domain="framework"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="linear", goal="build it"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="do generic narrow work"))
    return rid, sid, pid


async def test_t3_registry_binding_reaches_the_real_worker_spawn(
        env, tmp_path, monkeypatch):
    """Driven through a REAL spawn tool and read off the pool's recorded spawn —
    not off the resolver, which T2 already covers.

    RE-POINTED (2026-08-12): this drove the retired candidate-tier opt-in
    (`allow_candidate_tier=True` → Sonnet from MODEL_TIERS). The PROPERTY under
    test is unchanged and still live — the configured model resolution really
    reaches the pool — so it now drives the SEAT REGISTRY binding through
    `pool_spawn_worker`."""
    (tmp_path / "models.json").write_text(json.dumps({
        "seats": {"w": {"model": PINNED_MODEL}},
        "roles": {"worker": "w"},
    }), encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    _rid, _sid, pid = await _recipe_with_plan(env)

    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="a1"))
    spawned = [s for s in env.ctx.pool.spawns if s["role"] == "worker"]
    assert len(spawned) == 1
    assert spawned[0]["model"] == PINNED_MODEL, (
        f"registry-bound spawn launched on {spawned[0]['model']!r}, expected "
        f"{PINNED_MODEL!r} from models.json")


def test_t3b_default_reviewer_spawn_carries_no_model(monkeypatch):
    """With no registry the reviewer resolves NO model — the pool config
    default (the judgment-class pin) rules. The safety net degrades last
    (d29/d30: the reviewer's re-run IS the gate), and no legacy flag can
    degrade it: the candidate tier it could once opt into is deleted."""
    monkeypatch.delenv("EDP_AGENT_HOME", raising=False)
    assert spawn_model_for("reviewer", "spec") is None
    assert spawn_model_for(
        "reviewer", "spec", allow_candidate_tier=True) is None


async def test_t3c_default_worker_spawn_stays_no_model(env, monkeypatch):
    """And the un-configured worker dispatch path is byte-identical to
    pre-W10b: no registry → no --model key on the wire."""
    monkeypatch.delenv("EDP_AGENT_HOME", raising=False)
    _rid, _sid, pid = await _recipe_with_plan(env)
    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="a1"))
    spawned = [s for s in env.ctx.pool.spawns if s["role"] == "worker"]
    assert len(spawned) == 1
    assert spawned[0]["model"] is None


# (T4 — "no haiku in the tier table" — and T5 — the tier-row shape — are
# REMOVED with their subject; test_w10b_benchmark.py::test_r2 keeps the d53
# haiku ban pinned on the surviving resolution path.)


# ── T6 — the escalation ladder ─────────────────────────────────────────────
def _plan(**over) -> Plan:
    base = dict(
        plan_id="p-w10b", recipe_id="r-w10b", recipe_step_id="s1",
        domain="framework", shape="linear", goal="make the totals line up",
        state="dispatching",
        actions=[dict(
            action_id="a1", description="reconcile the CSV totals",
            status="in_progress", executor_mode="subagent",
            acceptance=dict(kind="tests_pass",
                            expected="totals match the invoice PDF",
                            actual=None),
        )],
    )
    base.update(over)
    return Plan.model_validate(base)


def _fail_cycle_via_worker(p, aid="a1"):
    """Seam (a): the worker ran the gate in its own shell and it failed."""
    a = next(x for x in p.actions if x.action_id == aid)
    return bump_verify_failure(a)


def _fail_cycle_via_reviewer(p, aid="a1"):
    """Seam (b): the reviewer independently re-ran the gate and it failed."""
    a = next(x for x in p.actions if x.action_id == aid)
    return bump_verify_failure(a)


def _redispatch(p, aid="a1"):
    """Open a fresh acceptance cycle, exactly as the FSM does at dispatch."""
    a = next(x for x in p.actions if x.action_id == aid)
    a.status = "pending"
    instr = plan_next_action(p)          # stamps in_progress, clears the latch
    assert instr.kind == K.DISPATCH_ACTION
    return instr


def test_t6a_one_failed_cycle_through_BOTH_seams_counts_once_and_is_silent():
    """The dual gate is the HEALTHY path, not a stuck one.

    A single failed acceptance cycle is REPORTED twice by design: the worker runs
    the gate and records `failed`, then the reviewer independently re-runs it
    (d30) and records a failing verdict. Naive per-report bumping would double-
    count, firing ESCALATE_CONSULT after ONE failed cycle — convening an Opus
    consult every time a worker fails once and a reviewer agrees.

    Mutation for this assertion: delete the `verify_failure_counted` guard in
    `bump_verify_failure` (the idempotence key) and this goes RED on the count."""
    p = _plan()
    assert _fail_cycle_via_worker(p) is True      # first report counts
    assert _fail_cycle_via_reviewer(p) is False   # same cycle → no-op

    a = p.actions[0]
    assert a.verify_failures == 1, (
        f"one failed cycle reported through both d30 seams counted "
        f"{a.verify_failures} times")
    assert plan_next_action(_plan(actions=[a.model_dump()])) is not None
    # and NOTHING escalates below the threshold
    p2 = _plan()
    _fail_cycle_via_worker(p2)
    _fail_cycle_via_reviewer(p2)
    instr = plan_next_action(p2)
    assert instr.kind != K.ESCALATE_CONSULT, (
        "ESCALATE_CONSULT fired after ONE failed acceptance cycle; the "
        f"threshold is {STUCK_VERIFY_FAILURES_THRESHOLD} DISTINCT cycles")


# ── T6i — the two seams above are the SAME HELPER; these are the real tools ──
#
# t6a proves `bump_verify_failure` is idempotent. It cannot prove that the two
# d30 seams both CALL it: `_fail_cycle_via_worker` and `_fail_cycle_via_reviewer`
# are the same one-line helper. A seam that forgot the call would leave t6a green
# and the escalation ladder mis-counting in production. Drive the actual tools.

async def _one_action_plan(env, action_id="a1"):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id=action_id,
                       description="do generic work"))
    return rid, pid


#: a verdict must clear the substance bar; rubber-stamping is refused.
_VERDICT = ("Re-ran the acceptance command in a fresh shell: 12 passed, "
            "0 failed. The mutation reddens test_x at the named site.")


def _action(env, pid, aid="a1"):
    return next(x for x in env.ctx.plans.load(pid).actions if x.action_id == aid)


def _post_grounding_echo(env, pid, aid="a1"):
    """v7 P3.1: a worker's terminal record is refused without the grounding
    echo — post the worklog line notify_above(kind='grounding') leaves."""
    env.ctx.plans.append_worklog(pid, {
        "kind": "message_sent", "agent_role": "worker",
        "to": pid, "msg_kind": "grounding",
        "from_handle": f"{pid}:{aid}",
        "summary": "{'restatement': 'do generic work'}",
    })


async def test_t6i_worker_seam_alone_counts_one_cycle(env, monkeypatch):
    """SEAM (a), in isolation: `record_action_status(status="failed")`."""
    _, pid = await _one_action_plan(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_SPAWN_SESSION_ID", "sess-1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _post_grounding_echo(env, pid)
    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status="failed", evidence="ran the gate: 1 failed"))
    assert _action(env, pid).verify_failures == 1, (
        "seam (a) record_action_status(failed) does not count a failed cycle")


async def test_t6i_reviewer_seam_alone_counts_one_cycle(env, monkeypatch):
    """SEAM (b), in isolation. THE NON-VACUITY GUARD for the combined test
    below: were `record_branch_verdict` to never call `bump_verify_failure`,
    the combined worker-then-reviewer test would STILL observe 1 — inherited
    from seam (a) — and pass while pinning nothing about seam (b)."""
    rid, pid = await _one_action_plan(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a9")   # NOT the action's own shell
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    _ok(await env.call("record_branch_verdict", recipe_id=rid, plan_id=pid,
                       branch_id="a1", verdict=_VERDICT, passed=False))
    assert _action(env, pid).verify_failures == 1, (
        "seam (b) record_branch_verdict(passed=False) does not count a cycle")


async def test_t6i_a_passing_reviewer_verdict_counts_nothing(env, monkeypatch):
    """`passed=True` is the gate HOLDING. Counting it would escalate on success.
    `passed=None` (every pre-W10b caller) says nothing and counts nothing."""
    rid, pid = await _one_action_plan(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a9")
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    _ok(await env.call("record_branch_verdict", recipe_id=rid, plan_id=pid,
                       branch_id="a1", verdict=_VERDICT, passed=True))
    assert _action(env, pid).verify_failures == 0


async def test_t6i_one_cycle_through_BOTH_REAL_seams_counts_once(env, monkeypatch):
    """THE CLAIM, through the tools that actually carry it. The worker runs the
    gate in its own shell and reports `failed` (d30 seam a); the reviewer
    independently re-runs it and records a failing verdict (seam b). That is the
    dual gate WORKING — one failed cycle — and it must count ONCE.

    Mutation: delete the `verify_failure_counted` guard in `bump_verify_failure`
    → this observes 2, i.e. the ladder fires at half its stated threshold."""
    rid, pid = await _one_action_plan(env)

    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_SPAWN_SESSION_ID", "sess-1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _post_grounding_echo(env, pid)
    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status="failed", evidence="ran the gate: 1 failed"))

    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a9")
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    _ok(await env.call("record_branch_verdict", recipe_id=rid, plan_id=pid,
                       branch_id="a1", verdict=_VERDICT, passed=False))

    a = _action(env, pid)
    assert a.verify_failures == 1, (
        f"one failed cycle reported through both REAL d30 seams counted "
        f"{a.verify_failures} times")
    assert a.verify_failure_counted is True   # the latch persisted


def test_t6b_two_distinct_failed_cycles_emit_escalate_consult():
    """Two DISTINCT cycles — each separated by a re-dispatch, which is the
    idempotence key — do emit, with an auto-composed action-specific question."""
    p = _plan()
    _fail_cycle_via_worker(p)                  # cycle 1
    _redispatch(p)                             # dispatch opens cycle 2
    _fail_cycle_via_worker(p)                  # cycle 2
    assert p.actions[0].verify_failures == STUCK_VERIFY_FAILURES_THRESHOLD

    instr = plan_next_action(p)
    assert instr.kind == K.ESCALATE_CONSULT, instr.kind

    q = instr.args["question"]
    assert q.strip(), "the auto-composed question is empty"
    # ACTION-SPECIFIC by construction, not a template
    assert "a1" in q and "p-w10b" in q
    assert "reconcile the CSV totals" in q          # the action's description
    assert "totals match the invoice PDF" in q      # the acceptance EXPECTED
    assert "failed acceptance cycles" in q          # the signal that fired
    assert instr.args["action_id"] == "a1"
    assert instr.args["recipe_id"] == "r-w10b"
    # 2026-08-12: the escalation names NO model — the consult tier went with
    # the retired table; how a raised question is answered is the parent's call.
    assert "model" not in instr.args


def test_t6c_redispatch_churn_alone_escalates():
    """The design's FIRST signal, independent of the acceptance counter:
    `attempt` (crash re-dispatch). Distinct counters, distinct meanings."""
    p = _plan()
    p.actions[0].attempt = 2
    instr = plan_next_action(p)
    assert instr.kind == K.ESCALATE_CONSULT
    assert "re-dispatch churn" in instr.args["question"]


def test_t6d_parked_worker_escalates_and_is_a_caller_computed_input():
    """The THIRD signal enters the PURE FSM as an input, exactly as
    `live_action_ids` does (s27/C7). The FSM holds no clock and reads no
    broker."""
    p = _plan()
    instr = plan_next_action(p, frozenset(), frozenset({"a1"}))
    assert instr.kind == K.ESCALATE_CONSULT
    assert "parked on an unanswered question" in instr.args["question"]

    # without the input, the same plan does NOT escalate (the input is load-
    # bearing, not decorative)
    assert plan_next_action(_plan()).kind != K.ESCALATE_CONSULT


def test_t6e_escalation_is_LATCHED_and_the_next_tick_dispatches():
    """d76 — the FSM ADVISES. An un-latched escalation would re-emit every tick
    and never hand back a dispatch, which is a control mechanism the FSM is
    forbidden from being. Latched, it costs exactly one tick.

    Mutation for this assertion: drop the `p.escalation_emitted` write in
    `plan_escalation_instruction` and the second tick escalates again → RED."""
    p = _plan()
    p.actions[0].attempt = 2
    p.actions[0].status = "pending"

    first = plan_next_action(p)
    assert first.kind == K.ESCALATE_CONSULT
    assert p.escalation_emitted == {"a1": [2, 0, False]}

    second = plan_next_action(p)              # same signal state → latched
    assert second.kind == K.DISPATCH_ACTION, (
        f"escalation re-emitted on the next tick ({second.kind}); it would "
        "wedge the plan and never dispatch")

    # a signal ADVANCE re-arms it (another crash), and only that
    p.actions[0].status = "pending"
    p.actions[0].attempt = 3
    assert plan_next_action(p).kind == K.ESCALATE_CONSULT


def test_t6f_escalation_is_advice_and_convenes_nothing():
    """The instruction DESCRIBES an escalation. It does not make one: the FSM
    is pure (no IO, no pool, no broker).

    2026-07-25: the escalation used to name `convene_consult`, and this test
    asserted that name. The operator retired that verb (roles.py
    `_OPERATOR_RETIRED`), so the rationale now points at `ask_above` instead —
    because d14 forbids instructing a role to call a tool it cannot see, which
    is exactly what leaving the old wording would have done. The ADVISORY
    property this test exists to guard is unchanged and still asserted."""
    p = _plan()
    p.actions[0].attempt = 2
    instr = plan_next_action(p)
    assert instr.kind == K.ESCALATE_CONSULT
    # the escalation must name a verb that some role actually holds
    assert "ask_above" in instr.rationale
    assert "convene_consult(" not in instr.rationale
    assert "ADVICE" in instr.rationale
    src = inspect.getsource(
        __import__("edp_claude.fsm.plan_fsm", fromlist=["x"]))
    for forbidden in ("ctx.pool", "ctx.broker", "await ", "requests.",
                      "open("):
        assert forbidden not in src, (
            f"plan_fsm performs IO ({forbidden!r}); the FSM must stay pure")


def test_t6g_a_done_action_never_escalates():
    """A finished action is not stuck, however it got there."""
    p = _plan()
    p.actions[0].attempt = 5
    p.actions[0].verify_failures = 5
    p.actions[0].status = "done"
    p.actions[0].acceptance.actual = "evidence"
    assert plan_next_action(p).kind != K.ESCALATE_CONSULT


def test_t6h_composed_question_is_never_empty_even_with_nothing_recorded():
    """No template branch can yield an empty or generic question."""
    p = _plan()
    a = p.actions[0]
    a.acceptance.expected = ""
    a.acceptance.actual = None
    q = compose_consult_question(p, a, ["some signal"], worklog_tail=None)
    assert q.strip()
    assert "a1" in q and "EXPECTED" in q and "ACTUAL" in q
    assert "(none recorded)" in q and "(nothing recorded)" in q


async def test_t6i_both_seams_bump_through_the_real_tools(env):
    """The two seams are REAL tool paths, not just the helper. Drives
    record_action_status(status='failed') and record_branch_verdict(passed=False)
    through the registry and reads the counter off disk."""
    _rid, _sid, pid = await _recipe_with_plan(env)

    # seam (a): the worker ran its own acceptance gate and it failed
    _ok(await env.call("record_action_status", plan_id=pid, action_id="a1",
                       status="failed", evidence="pytest exited 1"))
    assert env.ctx.plans.load(pid).actions[0].verify_failures == 1

    # seam (b): the reviewer independently re-ran it and states it failed.
    # SAME cycle (no dispatch between) → idempotent no-op.
    _ok(await env.call(
        "record_branch_verdict", recipe_id=_rid, plan_id=pid, branch_id="a1",
        passed=False,
        verdict="I re-ran pytest in a fresh shell; the totals assertion still "
                "fails at test_totals.py:41. The deliverable does not meet the "
                "acceptance criteria."))
    a = env.ctx.plans.load(pid).actions[0]
    assert a.verify_failures == 1, (
        f"one cycle reported through both seams counted {a.verify_failures}x")
    assert a.review_verdict["passed"] is False

    # a PASSING verdict never counts a failure
    p = env.ctx.plans.load(pid)
    p.actions[0].verify_failure_counted = False   # simulate a fresh cycle
    env.ctx.plans.save(p)
    _ok(await env.call(
        "record_branch_verdict", recipe_id=_rid, plan_id=pid, branch_id="a1",
        passed=True,
        verdict="I re-ran pytest in a fresh shell and it exits 0; the totals "
                "now match the invoice PDF. The acceptance criteria are met."))
    assert env.ctx.plans.load(pid).actions[0].verify_failures == 1


async def test_t6j_the_parked_signal_is_actually_FED_in_production(env):
    """d68/C9 — A GREEN GATE IS NOT EVIDENCE THE WIRING EXISTS.

    T6d proves the FSM honours `parked_action_ids`. It proves NOTHING about
    whether anything ever computes that set in the live `next_action` path: a
    perfectly-wired pure function whose caller always passes `frozenset()` is
    dead code with a passing test. So this drives the REAL tool and asserts the
    escalation comes out of it, with the wait clock in the state a genuinely
    parked child would leave it in.

    Mutation: make `_parked_action_ids` return `frozenset()` unconditionally and
    this goes RED while T6d stays green — which is exactly the blind spot."""
    from edp_claude.tools import _tools as T

    _rid, _sid, pid = await _recipe_with_plan(env)
    p = env.ctx.plans.load(pid)
    p.state = PlanState.DISPATCHING     # the enum, not the raw string
    p.actions[0].status = "in_progress"
    env.ctx.plans.save(p)

    # the state two elapsed patience windows leave behind on this handle
    st = T._WaitState(sig=("x",), since=0.0)
    st.escalations = T._PARKED_ESCALATIONS
    T._WAIT_STATE[pid] = st
    try:
        out = _ok(await env.call("next_action", handle=pid,
                                 handle_type="plan"))
    finally:
        T._WAIT_STATE.pop(pid, None)

    assert out["kind"] == K.ESCALATE_CONSULT.value, (
        f"next_action returned {out['kind']!r}; the parked signal is not fed "
        "in the live path")
    assert "parked on an unanswered question" in out["args"]["question"]
    assert "model" not in out["args"]     # the consult tier retired 2026-08-12

    # and the latch PERSISTED, so the next tick does not re-emit
    assert env.ctx.plans.load(pid).escalation_emitted == {"a1": [0, 0, True]}


# ── T7 ─────────────────────────────────────────────────────────────────────
def test_t7_no_cost_report_tool_is_registered(env):
    """d77 (USER RULING, verbatim): "cost report is not shell count. I dont want
    you to build a dumb harness and hardcode the requirements... This discipline
    should exist within its role."

    W10b keeps model tiering + the escalation ladder; cost_report is DROPPED from
    the build. This asserts the ABSENCE — the prose belongs in the orchestrator
    guide and rides Phase 5, not in a tool that computes a number the model then
    obeys (d76: the framework advises, the model decides)."""
    names = set(env.tools)
    assert "cost_report" not in names
    offenders = sorted(n for n in names if "cost" in n.lower())
    assert offenders == [], f"cost-shaped tools registered: {offenders}"

    # and nothing in the source builds a Phoenix query client for it
    src = (_ROOT / "src" / "edp_claude" / "tools" / "_tools.py").read_text(
        encoding="utf-8")
    assert "class CostReport" not in src


# ── T8 — the o6 standing bar ───────────────────────────────────────────────
def test_t8_legacy_fixture_loads_byte_identically_with_the_new_counters():
    """o6: the new counter fields default-populate on legacy records WITHOUT
    rewriting them. Migration stays LAZY. Asserted on the RECIPE and — because
    the counters live on `Action` — on the legacy PLANS, which is where they
    would actually leak.

    Mutation for this assertion (d64: a clean corpus cannot prove its own guard):
    RE-INTRODUCE the offending form by removing the emission gate for
    `verify_failures`/`verify_failure_counted` in `Action._ser_legacy_shape`, and
    every legacy plan gains two unrequested keys → RED."""
    from edp_claude.store.tiering import (
        dehydrate_recipe_payload,
        hydrate_recipe_payload,
    )
    import os
    os.environ.pop("EDP_TIER_WRITE", None)

    rdir = _RECIPES / LEGACY_RID
    assert (rdir / "recipe.json").exists(), "legacy fixture 0e7ca8 missing"
    original = (rdir / "recipe.json").read_text(encoding="utf-8")
    raw = json.loads(original)
    model = Recipe.model_validate(
        hydrate_recipe_payload(copy.deepcopy(raw), rdir))
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        payload = dehydrate_recipe_payload(model.model_dump(mode="json"),
                                           Path(td))
    assert json.dumps(payload, indent=2) == original, \
        "legacy 0e7ca8 recipe round-trip is NOT byte-identical after W10b"

    # THE PLANS ARE WHERE THE NEW FIELDS LIVE — `Action` carries the counters, so
    # a leaked key would surface in legacy PLAN json, not in recipe.json.
    #
    # WHAT IS ASSERTED, AND WHY IT IS NOT FULL BYTE-IDENTITY. Exactly one legacy
    # action (…-s16, RP-6c-B2) re-serializes with `actual_ref` and `verify`
    # TRANSPOSED inside its `acceptance` — it was written by an older schema whose
    # field order differed. That drift PREDATES W10b and is untouched by it (the
    # W10b keys appear nowhere in the diff). Asserting raw byte-identity here
    # would be asserting a property this repo has never had, and "fixing" the
    # order would rewrite a legacy record — the exact thing o6's lazy-migration
    # bar forbids. So this asserts CONTENT identity (order-insensitive), which is
    # the property the emission gate actually owns, plus an explicit no-new-keys
    # check. The order drift is recorded as a finding, not masked.
    plan_files = sorted(_PLANS.glob(f"{LEGACY_RID}-s*.json"))
    assert plan_files, "no legacy 0e7ca8 plan JSON to guard"
    for pf in plan_files:
        text = pf.read_text(encoding="utf-8").rstrip("\n")
        orig = json.loads(text)
        p = Plan.model_validate(orig)
        # the fields EXIST on the model (default-populated, lazily, no rewrite)…
        for a in p.actions:
            assert a.verify_failures == 0
            assert a.verify_failure_counted is False
        assert p.escalation_emitted is None
        # …and are ABSENT from the re-serialized bytes
        out = p.model_dump(mode="json")
        for a in out["actions"]:
            assert "verify_failures" not in a, pf.name
            assert "verify_failure_counted" not in a, pf.name
        assert "escalation_emitted" not in out, pf.name
        assert (json.dumps(out, indent=2, sort_keys=True)
                == json.dumps(orig, indent=2, sort_keys=True)), (
            f"legacy plan {pf.name} does not round-trip content-identically "
            "after W10b")
    assert len(plan_files) >= 1


def test_t8b_the_counters_DO_serialize_once_they_carry_a_value():
    """The emission gate must omit at the DEFAULT, not always — otherwise the
    counter would never persist and the ladder would reset every reload."""
    p = _plan()
    p.actions[0].verify_failures = 2
    p.actions[0].verify_failure_counted = True
    p.escalation_emitted = {"a1": [0, 2, False]}
    out = p.model_dump(mode="json")
    assert out["actions"][0]["verify_failures"] == 2
    assert out["actions"][0]["verify_failure_counted"] is True
    assert out["escalation_emitted"] == {"a1": [0, 2, False]}
    # and it survives a round trip
    assert Plan.model_validate(out).actions[0].verify_failures == 2


# ── T9 — the residual W10a item was already landed ─────────────────────────
async def test_t9_planner_spawn_already_accepts_and_passes_model(env):
    """AN HONEST NEGATIVE, PINNED.

    This action's brief said: "RESIDUAL W10a: the TOOL-level planner-spawn entry
    point in _tools.py still does not accept/pass `model`. Thread it." It does.
    The brief inherited that from DESIGN-v6 W10b, which named a stale line number
    (_tools.py:1934) for a passthrough the code comment at `_SpawnPlannerIn`
    already describes as landed.

    Nothing was re-plumbed. The claim is pinned here instead, so it cannot rot
    back into a to-do — and so a reader who finds the design's sentence knows the
    code, not the sentence, is authoritative."""
    rid, sid, _pid = await _recipe_with_plan(env)

    # accepts it, and passes it through to the pool verbatim
    _ok(await env.call("pool_spawn_planner", recipe_id=rid, step_id=sid,
                       model=PINNED_MODEL))
    planners = [s for s in env.ctx.pool.spawns if s["role"] == "planner"]
    assert planners[-1]["model"] == PINNED_MODEL

    # and omitting it still means "host default" (no flag), unchanged
    _ok(await env.call("pool_spawn_planner", recipe_id=rid, step_id=sid))
    planners = [s for s in env.ctx.pool.spawns if s["role"] == "planner"]
    assert planners[-1]["model"] is None
