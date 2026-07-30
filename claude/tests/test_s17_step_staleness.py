"""s17 Fix 1 — per-tick, all-steps, disk-grounded step reconciler.

Locks the fix: a step whose plan reached terminal/succeeded ON DISK is
reconciled to `done` on a plain `reconcile`, regardless of how the planner
ended (self-close, crash, or a neuron/planner REAP that fires no plan_closed)
— including a PENDING step, the case the old `_advance_executing`
(in_progress / ip[0] / EXECUTING-only) never checked. And the safety guard:
only `succeeded` advances; a terminal/PARTIAL plan is left for the neuron.
"""
from datetime import datetime, timezone

from edp_contracts import ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _recipe_two_steps(env, rid, s_ip="s1", s_pending="s2"):
    from edp_claude.schemas import Recipe
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [],
                       "expected_outcomes": [{"id": "o1", "description": "d",
                                              "verification": "v"}]},
        steps=[
            {"step_id": s_ip, "kind": "work", "description": "d",
             "status": "in_progress", "depends_on": [],
             "execution": "spawn_planner"},
            {"step_id": s_pending, "kind": "work", "description": "d",
             "status": "pending", "depends_on": [],
             "execution": "spawn_planner"},
        ],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))


def _terminal_plan(env, rid, sid, status="succeeded"):
    from edp_claude.schemas import Plan
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=f"{rid}-{sid}", recipe_id=rid, recipe_step_id=sid,
        domain="generic", shape="x", goal="g",
        state="terminal", terminal_status=status, actions=[], context={},
    )))


async def test_s17_reconcile_advances_pending_step_whose_plan_is_terminal(env):
    # The reap/out-of-band case: the pending step's plan is terminal-succeeded
    # on disk but NO plan_closed was fired. Plain reconcile must converge it.
    rid = "recipe-s17a"
    _recipe_two_steps(env, rid=rid)
    _terminal_plan(env, rid, "s2", status="succeeded")
    rc = _ok(await env.call("reconcile", handle=rid, handle_type="recipe"))
    assert rc["changed"] is True
    r = env.ctx.recipes.load(rid)
    assert next(s for s in r.steps if s.step_id == "s2").status == "done"
    # the in_progress step (no terminal plan) is untouched; still executing.
    assert next(s for s in r.steps if s.step_id == "s1").status == "in_progress"
    assert r.state == "executing"


async def test_s17_reconcile_does_not_advance_partial_plan(env):
    # Safety/monotonicity: only `succeeded` advances a step; a terminal
    # PARTIAL plan is left pending for the neuron to judge (never auto-done).
    rid = "recipe-s17b"
    _recipe_two_steps(env, rid=rid)
    _terminal_plan(env, rid, "s2", status="partial")
    await env.call("reconcile", handle=rid, handle_type="recipe")
    r = env.ctx.recipes.load(rid)
    assert next(s for s in r.steps if s.step_id == "s2").status == "pending"


async def test_s17_reconcile_hands_back_to_planning_when_nothing_running(env):
    # If reconcile advances the LAST in_progress step (its plan terminal on
    # disk, no plan_closed) and nothing else is running, the recipe hands back
    # to PLANNING so next_action re-picks — no EXECUTING-with-nothing stall.
    from edp_claude.schemas import Recipe
    rid = "recipe-s17c"
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [],
                       "expected_outcomes": [{"id": "o1", "description": "d",
                                              "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))
    _terminal_plan(env, rid, "s1", status="succeeded")
    await env.call("reconcile", handle=rid, handle_type="recipe")
    r = env.ctx.recipes.load(rid)
    assert r.steps[0].status == "done"
    assert r.state == "planning"
