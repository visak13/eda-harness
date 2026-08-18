"""F33 (2026-08-18) — campaign Round 1 (prompts & cards lens) code fixes.

R1 F#1  G-VERDICT: a recorded FAIL review verdict blocks plan success —
        the FSM reopens the fail-verdicted action at the success
        boundary instead of closing `succeeded` over a known defect.
R1 F#8  dispatch_acceptance is idempotent while a pass is in flight —
        no rival acceptor per heartbeat; force=true is the escape.
"""

from datetime import datetime, timezone

from edp_claude.fsm import plan_next_action
from edp_claude.schemas import Plan, Recipe
from edp_claude.server import make_context
from edp_claude.tools._tools import DispatchAcceptance, _DispatchAcceptanceIn


def _plan(actions, state="dispatching"):
    return Plan.model_validate(dict(
        plan_id="p", recipe_id="r", recipe_step_id="s1",
        domain="software_engineering", shape="linear-build", goal="g",
        state=state, actions=actions, context={}))


def _done_action(aid="a1", verdict=None):
    a = {"action_id": aid, "description": "d", "status": "done",
         "depends_on": [], "executor_mode": "subagent",
         "acceptance": {"kind": "tests_pass", "actual": "green"}}
    if verdict is not None:
        a["review_verdict"] = verdict
    return a


def test_fail_verdict_blocks_success_and_reopens():
    p = _plan([
        _done_action("a1", verdict={
            "verdict": "re-ran pytest; 3 assertions fail on the escrow "
                       "rounding path — this is a correctness failure",
            "passed": False, "by": "reviewer", "at": "2026-08-18T00:00:00Z"}),
        _done_action("r1"),
    ])
    i = plan_next_action(p)
    assert "G-VERDICT" in i.rationale
    assert i.args.get("reopened_action_ids") == ["a1"]
    a1 = next(a for a in p.actions if a.action_id == "a1")
    assert a1.status == "pending"
    assert p.terminal_status is None
    # the reopened action is re-dispatched on the next tick
    i2 = plan_next_action(p)
    assert i2.kind == "dispatch_action"


def test_pass_verdict_still_succeeds():
    p = _plan([_done_action("a1", verdict={
        "verdict": "re-ran the gate; all checks green, conforms to spec",
        "passed": True, "by": "reviewer", "at": "2026-08-18T00:00:00Z"})])
    i = plan_next_action(p)
    assert i.kind == "done"
    assert p.terminal_status == "succeeded"


def test_verdict_without_passed_flag_does_not_reopen():
    # prose-only verdicts (no passed flag) keep the old behaviour —
    # only an explicit passed=False blocks.
    p = _plan([_done_action("a1", verdict={
        "verdict": "looked at it; notes recorded, no explicit gate call",
        "by": "reviewer", "at": "2026-08-18T00:00:00Z"})])
    i = plan_next_action(p)
    assert i.kind == "done" and p.terminal_status == "succeeded"


def test_reopen_bumps_verify_failures_toward_hard_cap():
    p = _plan([_done_action("a1", verdict={
        "verdict": "re-ran pytest; still failing on the same rounding "
                   "path — the rework did not clear the defect",
        "passed": False, "by": "reviewer", "at": "2026-08-18T00:00:00Z"})])
    a1 = p.actions[0]
    before = a1.verify_failures
    plan_next_action(p)
    assert a1.verify_failures == before + 1


# ── R1 F#8 — the acceptor in-flight latch ──────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def _recipe(ctx, rid="recipe-f33"):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="g", user_goal_distilled="g",
        domain="software_engineering", state="reviewing",
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v",
             "met": True, "met_evidence": "e"}]},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "done", "depends_on": [], "execution": "inline"}],
        created_at=_now(), updated_at=_now()))


async def test_dispatch_acceptance_is_idempotent_in_flight(tmp_path):
    ctx = make_context(tmp_path)
    _recipe(ctx)
    r1 = await DispatchAcceptance(ctx)._run(
        _DispatchAcceptanceIn(recipe_id="recipe-f33"))
    assert r1.ok
    d1 = r1.data if isinstance(r1.data, dict) else r1.data.model_dump()
    # second call while no verdict landed → same acceptor, no new spawn
    r2 = await DispatchAcceptance(ctx)._run(
        _DispatchAcceptanceIn(recipe_id="recipe-f33"))
    d2 = r2.data if isinstance(r2.data, dict) else r2.data.model_dump()
    assert d2["acceptor_id"] == d1["acceptor_id"]
    assert "ALREADY IN FLIGHT" in d2["note"]
    assert len([s for s in ctx.pool.spawns
                if s.get("role") == "acceptor"]) == 1


async def test_dispatch_acceptance_respawns_after_verdict(tmp_path):
    ctx = make_context(tmp_path)
    _recipe(ctx)
    r1 = await DispatchAcceptance(ctx)._run(
        _DispatchAcceptanceIn(recipe_id="recipe-f33"))
    d1 = r1.data if isinstance(r1.data, dict) else r1.data.model_dump()
    ctx.recipes.append_worklog("recipe-f33", {
        "kind": "acceptance_verdict", "body": {"verdict": "gaps"}})
    r2 = await DispatchAcceptance(ctx)._run(
        _DispatchAcceptanceIn(recipe_id="recipe-f33"))
    d2 = r2.data if isinstance(r2.data, dict) else r2.data.model_dump()
    assert d2["acceptor_id"] != d1["acceptor_id"]


async def test_dispatch_acceptance_force_overrides_latch(tmp_path):
    ctx = make_context(tmp_path)
    _recipe(ctx)
    r1 = await DispatchAcceptance(ctx)._run(
        _DispatchAcceptanceIn(recipe_id="recipe-f33"))
    d1 = r1.data if isinstance(r1.data, dict) else r1.data.model_dump()
    r2 = await DispatchAcceptance(ctx)._run(
        _DispatchAcceptanceIn(recipe_id="recipe-f33", force=True))
    d2 = r2.data if isinstance(r2.data, dict) else r2.data.model_dump()
    assert d2["acceptor_id"] != d1["acceptor_id"]
