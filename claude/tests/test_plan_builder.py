"""Incremental plan builders (2026-05-22) — create_plan + add_action.

Fixes the planner schema-retry token burn (fitness HITL: every planner
reverse-engineered the Plan schema and retried record_plan 2-3×). These
give the plan the same intent-tool treatment the recipe has: small,
obvious per-call schemas; the tool fills scaffolding.
"""

from datetime import datetime, timezone

from edp_contracts import ToolError, ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _recipe(env, rid="recipe-pb", domain="webdev"):
    from edp_claude.schemas import Recipe
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain=domain,
        state="executing",
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "build",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))
    return rid


async def test_create_plan_fills_scaffolding(env):
    rid = await _recipe(env, domain="webdev")
    # planner supplies only shape + goal; tool fills plan_id + domain
    out = _ok(await env.call("create_plan", recipe_id=rid, step_id="s1",
                             shape="linear-build", goal="build the thing"))
    # 2026-05-28 friction #2: create_plan echoes plan_id + domain so the
    # planner doesn't have to infer "<recipe_id>-<step_id>".
    assert out["plan_id"] == f"{rid}-s1"
    assert out["domain"] == "webdev"
    assert out["version"] >= 1
    p = env.ctx.plans.load(f"{rid}-s1")
    assert p.plan_id == f"{rid}-s1"
    assert p.recipe_id == rid and p.recipe_step_id == "s1"
    assert p.domain == "webdev"          # inherited from recipe
    assert p.shape == "linear-build"
    assert p.state == "drafted"
    assert p.actions == []


async def test_add_action_small_flat_schema(env):
    rid = await _recipe(env)
    _ok(await env.call("create_plan", recipe_id=rid, step_id="s1",
                       shape="linear-build", goal="g"))
    # flat params — no nested Acceptance object to hand-author
    _ok(await env.call(
        "add_action", plan_id=f"{rid}-s1", action_id="a1",
        description="write index.html",
        acceptance_kind="file_exists",
        verify={"check": "file_exists", "path": "/tmp/x"}))
    _ok(await env.call(
        "add_action", plan_id=f"{rid}-s1", action_id="a2",
        description="verify build", depends_on=["a1"]))
    p = env.ctx.plans.load(f"{rid}-s1")
    assert [a.action_id for a in p.actions] == ["a1", "a2"]
    assert p.actions[0].acceptance.kind == "file_exists"
    assert p.actions[0].acceptance.verify == {"check": "file_exists",
                                              "path": "/tmp/x"}
    assert p.actions[1].depends_on == ["a1"]
    assert p.actions[1].executor_mode == "subagent"  # default


async def test_action_specialization_surfaces_in_dispatch(env):
    # phase 7: an action's specialization descriptor rides add_action and
    # is surfaced in the dispatch_action instruction so the dispatcher
    # can branch a specialist instead of a fresh worker.
    rid = await _recipe(env)
    _ok(await env.call("create_plan", recipe_id=rid, step_id="s1",
                       shape="linear-build", goal="g"))
    _ok(await env.call("add_action", plan_id=f"{rid}-s1", action_id="a1",
                       description="build the REST layer",
                       specialization="Java Spring Boot REST API"))
    _ok(await env.call("add_action", plan_id=f"{rid}-s1", action_id="a2",
                       description="write the README"))  # ordinary
    p = env.ctx.plans.load(f"{rid}-s1")
    # MULTI-SPEC (2026-06-03): the singular descriptor folds into the
    # canonical list; ordinary actions stay empty.
    assert p.actions[0].effective_specializations() == ["Java Spring Boot REST API"]
    assert p.actions[1].effective_specializations() == []
    # dispatch surfaces it
    d = _ok(await env.call("next_action", handle=f"{rid}-s1",
                           handle_type="plan"))
    assert d["kind"] == "dispatch_action"
    assert d["args"]["action_id"] == "a1"
    assert d["args"]["specialization"] == "Java Spring Boot REST API"


async def test_built_plan_drives_the_fsm(env):
    # The incrementally-built plan behaves identically to a record_plan'd
    # one: next_action(plan) dispatches the first ready action.
    rid = await _recipe(env)
    _ok(await env.call("create_plan", recipe_id=rid, step_id="s1",
                       shape="linear-build", goal="g"))
    _ok(await env.call("add_action", plan_id=f"{rid}-s1",
                       action_id="a1", description="do it"))
    d = _ok(await env.call("next_action", handle=f"{rid}-s1",
                           handle_type="plan"))
    assert d["kind"] == "dispatch_action"
    assert d["args"]["action_id"] == "a1"


async def test_add_action_rejects_duplicate_and_unknown_plan(env):
    rid = await _recipe(env)
    _ok(await env.call("create_plan", recipe_id=rid, step_id="s1",
                       shape="x", goal="g"))
    _ok(await env.call("add_action", plan_id=f"{rid}-s1",
                       action_id="a1", description="d"))
    dup = await env.call("add_action", plan_id=f"{rid}-s1",
                         action_id="a1", description="d2")
    assert isinstance(dup, ToolError) and dup.code == "tool_precondition"
    missing = await env.call("add_action", plan_id="nope",
                             action_id="a1", description="d")
    assert isinstance(missing, ToolError)


async def test_create_plan_refuses_to_clobber_dispatching_plan(env):
    rid = await _recipe(env)
    from edp_claude.schemas import Plan
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=f"{rid}-s1", recipe_id=rid, recipe_step_id="s1",
        domain="webdev", shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "d",
                  "status": "in_progress", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "manual_review"}}],
    )))
    res = await env.call("create_plan", recipe_id=rid, step_id="s1",
                         shape="x", goal="g")
    assert isinstance(res, ToolError)
    assert "drafted" in res.message.lower()
