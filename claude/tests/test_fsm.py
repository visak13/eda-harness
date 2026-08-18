"""Per-row FSM tests (DESIGN-v4 §2.1/§2.2 transition tables)."""

from datetime import datetime, timezone

from edp_claude.fsm import plan_next_action, recipe_next_action
from edp_claude.schemas import Plan, Recipe


def _r(**over):
    base = dict(
        recipe_id="r", user_goal_verbatim="g", domain="generic",
        state="created",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[], context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    base.update(over)
    return Recipe.model_validate(base)


def test_created_advances_to_comprehending_and_emits_reason():
    # Post-HITL sweep 2026-05-20: the FSM no longer seeds 7 branches.
    # CREATED -> COMPREHENDING and the first instruction is REASON
    # (free reasoning, brief carries curiosity). See
    # docs/design/philosophy/ocak-as-helper-not-enforcer.md.
    r = _r(state="created")
    i = recipe_next_action(r)
    assert r.state == "comprehending"
    assert i.kind == "reason"
    assert "freely" in i.rationale.lower()


def _audited_passed():
    return {
        "scope": "recipe",
        "findings": {"O": "n/a", "C": "ok", "A": "ok", "K": "low"},
        "verdict": "passed",
        "gaps": [],
        "notes": "",
        "at": datetime.now(timezone.utc).isoformat(),
    }


def test_outcomes_declared_goes_straight_to_declare_step():
    # Team-architecture-restoration Phase 1 (2026-05-21): the self-audit
    # gate is removed. Outcomes-declared-without-steps → DECLARE_STEP,
    # no placeholder audit. The brief tells the neuron NOT to self-eval;
    # `/critic` (Phase 5, separate shell) is the real audit surface.
    r = _r(state="comprehending",
           comprehension={
               "branches": [],
               "expected_outcomes": [
                   {"id": "o1", "description": "d", "verification": "v"}],
           })
    i = recipe_next_action(r)
    assert i.kind == "declare_step"


def test_audit_passed_then_declare_step_then_planning():
    # Audit passed + no steps → DECLARE_STEP.
    r = _r(state="comprehending",
           comprehension={
               "branches": [],
               "expected_outcomes": [
                   {"id": "o1", "description": "d", "verification": "v"}],
           },
           ocak_audit=_audited_passed())
    assert recipe_next_action(r).kind == "declare_step"
    # P6 (2026-06-10): outcomes + steps WITHOUT user signoff now hits the
    # comprehension-brief gate (await_user) — this test used to lock in
    # the user-bypass (the map dispatched without the user ever seeing it
    # and flaws surfaced post-dispatch).
    r_gate = _r(state="comprehending",
                comprehension={
                    "branches": [],
                    "expected_outcomes": [
                        {"id": "o1", "description": "d",
                         "verification": "v"}],
                },
                ocak_audit=_audited_passed(),
                steps=[{"step_id": "s1", "kind": "work", "description": "d",
                        "status": "pending", "depends_on": [],
                        "execution": "inline"}])
    g = recipe_next_action(r_gate)
    assert g.kind == "await_user" and r_gate.state == "comprehending"
    # +step +signoff → planning → executing run_inline
    r2 = _r(state="comprehending",
            comprehension={
                "branches": [],
                "expected_outcomes": [
                    {"id": "o1", "description": "d", "verification": "v"}],
                "user_signoff": True,
                "signoff_quote": "proceed",
            },
            ocak_audit=_audited_passed(),
            steps=[{"step_id": "s1", "kind": "work", "description": "d",
                    "status": "pending", "depends_on": [],
                    "execution": "inline"}])
    i = recipe_next_action(r2)
    assert i.kind == "run_inline" and r2.state == "executing"
    assert r2.steps[0].status == "in_progress"


def test_audit_overridden_by_user_also_unblocks():
    # The original framework-ocak.md explicitly allows skipping OCAK
    # for trivial goals — modelled as verdict="overridden_by_user".
    audit = _audited_passed()
    audit["verdict"] = "overridden_by_user"
    r = _r(state="comprehending",
           comprehension={
               "branches": [],
               "expected_outcomes": [
                   {"id": "o1", "description": "d", "verification": "v"}],
           },
           ocak_audit=audit)
    assert recipe_next_action(r).kind == "declare_step"


def _rev(outcomes, step_status):
    return _r(
        state="reviewing",
        comprehension={
            "branches": [{"id": "b1", "question": "?",
                          "status": "resolved", "verdict": "v"}],
            "expected_outcomes": outcomes,
        },
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": step_status, "depends_on": [],
                "execution": "inline"}],
    )


def test_reviewing_no_work_is_partial_not_false_success():
    """F4.c guard: drove no work → PARTIAL, never a clean done.
    Uses a `skipped` step: no step is done (drove_work=False) AND none is
    a ready-pending step (so v2.1 reopen doesn't fire) — the guard path."""
    i = recipe_next_action(_rev([], "skipped"))
    assert i.kind == "done"
    assert i.args.get("partial") is True
    assert "F4.c" in i.rationale or "drove no work" in i.rationale


def test_reviewing_with_ready_pending_step_reopens(env=None):
    """v2.1: a ready pending step in `reviewing` REOPENS the recipe
    (deferred-step pattern) instead of declaring partial."""
    i = recipe_next_action(_rev([], "pending"))
    assert i.kind == "run_inline"  # s1 is execution=inline, now dispatched


def test_reviewing_work_but_no_outcomes_is_partial():
    i = recipe_next_action(_rev([], "done"))
    assert i.args.get("partial") is True
    assert "no expected_outcomes" in i.rationale


def test_reviewing_outcomes_met_emits_dispatch_acceptance():
    # F31 (2026-08-18): all-outcomes-met no longer goes straight to DONE —
    # the PURE FSM always emits DISPATCH_ACCEPTANCE (it cannot read the
    # events trail); the TOOL layer downgrades to DONE when the latest
    # acceptance_verdict is 'pass' or the gate is off.
    o = [{"id": "o1", "description": "d", "verification": "v", "met": True}]
    i = recipe_next_action(_rev(o, "done"))
    assert i.kind == "dispatch_acceptance"
    assert "dispatch_acceptance" in i.rationale
    assert "pass" in i.rationale


def test_reviewing_outcomes_unmet_is_partial():
    o = [{"id": "o1", "description": "d", "verification": "v",
          "met": False}]
    i = recipe_next_action(_rev(o, "done"))
    assert i.args.get("partial") is True
    assert "not yet verified" in i.rationale


_AUDIT_OK = {"scope": "plan",
             "findings": {"O": "n/a", "C": "ok", "A": "ok", "K": "low"},
             "verdict": "passed", "gaps": [], "notes": "",
             "at": datetime.now(timezone.utc).isoformat()}


def _p(actions, state="drafted", ocak_audit=_AUDIT_OK):
    """Default audit=passed lets most plan tests exercise dispatch
    directly. Pass ocak_audit=None to test the audit-gate path."""
    return Plan.model_validate(dict(
        plan_id="p", recipe_id="r", recipe_step_id="s2",
        domain="software_engineering", shape="linear-build", goal="g",
        state=state, actions=actions, context={},
        ocak_audit=ocak_audit))


def test_plan_drafted_to_dispatch():
    p = _p([{"action_id": "a1", "description": "d", "status": "pending",
             "depends_on": [], "executor_mode": "subagent",
             "acceptance": {"kind": "tests_pass"}}])
    i = plan_next_action(p)
    assert i.kind == "dispatch_action" and p.state == "dispatching"


def test_plan_drafted_to_dispatch_no_audit_gate():
    # Team-architecture-restoration Phase 1 (2026-05-21): the plan-
    # level self-audit gate is removed. DRAFTED with actions → directly
    # to DISPATCHING. Plan-level OCAK audit is `/critic`'s job (Phase 5).
    p = _p([{"action_id": "a1", "description": "d", "status": "pending",
             "depends_on": [], "executor_mode": "subagent",
             "acceptance": {"kind": "tests_pass"}}],
           ocak_audit=None)
    i = plan_next_action(p)
    assert i.kind == "dispatch_action" and p.state == "dispatching"


def test_dispatch_stamps_in_progress_so_wait_is_reachable():
    # Post-HITL sweep A: dispatch must stamp in_progress (mirror the
    # recipe FSM) so the NEXT call no longer re-selects the same action
    # and falls through to WAIT — making the heartbeat tool-FORCED, not
    # inferred from the brief (the 2026-05-20 wake gap).
    p = _p([{"action_id": "a1", "description": "d", "status": "pending",
             "depends_on": [], "executor_mode": "subagent",
             "acceptance": {"kind": "tests_pass"}}])
    i1 = plan_next_action(p)
    assert i1.kind == "dispatch_action"
    assert p.actions[0].status == "in_progress"  # stamped AT dispatch
    # worker still running (a1 in_progress) → no re-dispatch, WAIT.
    i2 = plan_next_action(p)
    assert i2.kind == "wait"


def test_plan_all_done_succeeded():
    p = _p([{"action_id": "a1", "description": "d", "status": "done",
             "depends_on": [], "executor_mode": "subagent",
             "acceptance": {"kind": "tests_pass", "actual": "green"}}],
           state="dispatching")
    i = plan_next_action(p)
    assert i.kind == "done" and p.terminal_status == "succeeded"


def test_plan_done_without_evidence_is_partial():
    """DESIGN-v4 F4.c — done-but-unproven must NOT be 'succeeded'."""
    p = _p([{"action_id": "a1", "description": "d", "status": "done",
             "depends_on": [], "executor_mode": "subagent",
             "acceptance": {"kind": "tests_pass", "actual": None}}],
           state="dispatching")
    plan_next_action(p)
    assert p.terminal_status == "partial"
