"""Post-HITL sweep C: `close_recipe` intent tool.

The owner spent 6 rejection round-trips hand-authoring `record_recipe`
to close (the v5 guess-and-resolve friction). `close_recipe` is the
missing intent counterpart to start_recipe/record_outcome/add_step:
the neuron declares the verdict, the tool fills the scaffolding.
"""

from datetime import datetime, timezone

from edp_contracts import ToolError, ToolOk

RID = "recipe-close-x"


def _reviewing_recipe(env):
    from edp_claude.schemas import Recipe

    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=RID, user_goal_verbatim="g", domain="generic",
        state="reviewing",
        comprehension={
            "branches": [{"id": "b1", "question": "?",
                          "status": "resolved", "verdict": "v" * 50}],
            "expected_outcomes": [{"id": "o1", "description": "d",
                                   "verification": "v"}],
        },
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "done", "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))


async def test_close_recipe_flips_state_and_records_outcome(env):
    _reviewing_recipe(env)
    fo = {"status": "partial", "summary": "outcomes not yet verified"}
    res = await env.call("close_recipe", recipe_id=RID, final_outcome=fo)
    assert isinstance(res, ToolOk), res

    r = env.ctx.recipes.load(RID)
    assert r.state == "closed"
    assert r.final_outcome == fo


async def test_close_recipe_unknown_id_is_precondition(env):
    res = await env.call("close_recipe", recipe_id="nope",
                         final_outcome={"status": "partial", "summary": "x"})
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"


async def test_closed_recipe_is_not_resumed(env):
    # closed recipes must NOT come back via resolve_recipe (re-running a
    # finished goal correctly starts fresh — neuron.md invariant).
    _reviewing_recipe(env)
    # 'succeeded' now requires verified outcomes (2026-05-24 gate)
    await env.call("mark_outcome_met", recipe_id=RID, outcome_id="o1",
                   evidence="verified via reviewer fork + user confirm")
    await env.call("close_recipe", recipe_id=RID,
                   final_outcome={"status": "succeeded", "summary": "done"})
    res = await env.call("resolve_recipe", goal="g")
    assert isinstance(res, ToolOk)
    assert res.data["decision"] == "create"
