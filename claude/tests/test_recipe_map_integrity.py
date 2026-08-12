"""v2.1 — recipe-map integrity (2026-05-22).

The recipe is the map; it must never lie and the neuron must never need
to route around it. Covers: (1) a newly-added pending step reopens a
recipe that reached `reviewing` (the deferred-last-step trap); (2)
close_recipe refuses `succeeded` over pending/in_progress steps and
reconciles terminal-plan steps; (3) the wait reminder reinforces the
MCP procedure.
"""

from datetime import datetime, timezone

from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Plan, Recipe


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _recipe(env, rid, steps, state="executing"):
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state=state,
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v"}]},
        steps=steps, context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))


def _step(sid, status="pending", deps=None):
    return {"step_id": sid, "kind": "work", "description": "d",
            "status": status, "depends_on": deps or [],
            "execution": "spawn_planner"}


def _terminal_plan(env, rid, sid, status="succeeded"):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=f"{rid}-{sid}", recipe_id=rid, recipe_step_id=sid,
        domain="generic", shape="x", goal="g", state="terminal",
        terminal_status=status, actions=[],
    )))


# ── (1) deferred-step reopen ──────────────────────────────────────────────
async def test_reviewing_reopens_when_pending_step_added(env):
    rid = "recipe-reopen"
    # s1 done → recipe reached reviewing (only step was s1)
    _recipe(env, rid, [_step("s1", "done")], state="reviewing")
    # neuron adds s2 (deferred until s1's output was known)
    _ok(await env.call("add_step", recipe_id=rid,
                       description="implement the endpoint",
                       execution="spawn_planner", estimate={"hours": 1}))
    # next_action must REOPEN and dispatch s2, not emit done
    d = (await env.call("next_action", handle=rid,
                        handle_type="recipe")).data
    assert d["kind"] == "spawn_planner"
    assert d["args"]["step_id"] == "s2"
    assert env.ctx.recipes.load(rid).state == "executing"


# ── (2) close guard + reconcile ───────────────────────────────────────────
async def test_close_succeeded_refused_over_pending_steps(env):
    rid = "recipe-lie"
    _recipe(env, rid, [_step("s1", "done"), _step("s2", "pending")],
            state="reviewing")
    res = await env.call("close_recipe", recipe_id=rid,
                         final_outcome={"status": "succeeded",
                                        "summary": "all good"})
    assert isinstance(res, ToolError)
    assert "s2" in res.message and "not done" in res.message.lower()
    # recipe stays open
    assert env.ctx.recipes.load(rid).state != "closed"


async def test_close_reconciles_terminal_plan_steps(env):
    rid = "recipe-reconcile"
    _recipe(env, rid, [_step("s1", "done"), _step("s2", "pending")],
            state="reviewing")
    # s2's plan is actually terminal-succeeded — the map just hadn't
    # caught up. close reconciles it, then succeeds honestly. (WP1 G-STEP:
    # the already-done s1 needs its own terminal-succeeded plan too.)
    _terminal_plan(env, rid, "s1", "succeeded")
    _terminal_plan(env, rid, "s2", "succeeded")
    # outcome must be verified for a 'succeeded' close (2026-05-24 gate)
    _ok(await env.call("mark_outcome_met", recipe_id=rid, outcome_id="o1",
                       evidence="reviewer pass + user confirmed running"))
    _ok(await env.call("close_recipe", recipe_id=rid,
                       final_outcome={"status": "succeeded",
                                      "summary": "done"}))
    r = env.ctx.recipes.load(rid)
    assert r.state == "closed"
    assert r.steps[1].status == "done"   # reconciled


async def test_close_succeeded_refused_over_unmet_outcomes(env):
    # 2026-05-24: even with all steps done, 'succeeded' is refused while
    # an outcome is unverified (the 'succeeded with met:false' gap).
    rid = "recipe-unmet"
    _recipe(env, rid, [_step("s1", "done")], state="reviewing")
    # WP1 G-STEP: back the done step with its terminal-succeeded plan so
    # the close reaches the OUTCOME gate under test.
    _terminal_plan(env, rid, "s1", "succeeded")
    res = await env.call("close_recipe", recipe_id=rid,
                         final_outcome={"status": "succeeded", "summary": "x"})
    assert isinstance(res, ToolError)
    assert "o1" in res.message and "not verified" in res.message.lower()
    # mark it met → now it closes
    _ok(await env.call("mark_outcome_met", recipe_id=rid, outcome_id="o1",
                       evidence="verified via reviewer fork + smoke check"))
    _ok(await env.call("close_recipe", recipe_id=rid,
                       final_outcome={"status": "succeeded", "summary": "x"}))
    assert env.ctx.recipes.load(rid).state == "closed"


async def test_partial_close_allowed_over_incomplete_steps(env):
    rid = "recipe-partial"
    _recipe(env, rid, [_step("s1", "done"), _step("s2", "pending")],
            state="reviewing")
    # honest non-success close is permitted over incomplete steps
    _ok(await env.call("close_recipe", recipe_id=rid,
                       final_outcome={"status": "partial",
                                      "summary": "endpoint not built"}))
    assert env.ctx.recipes.load(rid).state == "closed"


# ── (3) wait reminder reinforces the procedure ────────────────────────────
async def test_wait_reminder_reinforces_mcp_procedure(env):
    rid = "recipe-wait"
    _recipe(env, rid, [_step("s1", "in_progress")], state="executing")
    d = (await env.call("next_action", handle=rid,
                        handle_type="recipe")).data
    assert d["kind"] == "wait"
    r = d["rationale"].lower()
    assert "next_action" in r
    assert "hand-dispatch" in r or "route around" in r
