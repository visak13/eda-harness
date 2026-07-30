"""Item 3B (delivery channel) — the plan path pushes the recipe's settled
context onto the planner's instruction.

Before Item 3B: the plan branch of next_action set NO instr.context, so a
planner got recipe decisions only if it chose to read them — the silent
hand-copy that let the s26 embedder-drift class of leak through.

s17 RP-B (2026-06-07) UPDATE — the plan path still carries the recipe context,
but decisions are now an `active_decisions` POINTER (count + id+title index +
on-demand load instruction), NOT a full-text re-dump. So the planner still
learns the decisions EXIST (and can recognise / fetch them), without the
~39.5K-char-per-tick context pollution. This test asserts the pointer reaches
the plan path and indexes the load-bearing decision by id+title.
"""
from datetime import datetime, timezone

from edp_contracts import ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def test_item3b_plan_path_carries_recipe_decisions(env):
    from edp_claude.schemas import Recipe, Plan
    rid = "recipe-i3b"
    sid = "s1"
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [],
                       "expected_outcomes": [{"id": "o1", "description": "d",
                                              "verification": "v"}]},
        steps=[{"step_id": sid, "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))
    # a settled, load-bearing decision recorded at the recipe level
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="MiniLM is the settled embedder; never nomic"))
    # the step's plan, mid-flight
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=f"{rid}-{sid}", recipe_id=rid, recipe_step_id=sid,
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "d",
                  "status": "in_progress", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "manual_review"}}],
        context={})))
    # next_action on the PLAN handle now carries the decisions POINTER
    d = _ok(await env.call("next_action", handle=f"{rid}-{sid}",
                           handle_type="plan"))
    ad = d["context"]["active_decisions"]
    # the pointer indexes the decision by id+title; full text is NOT re-dumped
    assert ad["count"] == 1, ad
    titles = [e["title"] for e in ad["index"]]
    assert any("never nomic" in t for t in titles), titles
    # the un-missable count rides in the recap (self-detection trigger)
    assert "decisions=1" in d["context"]["recap"], d["context"]["recap"]
    # and the heavy full-text dump is gone from the push
    assert "decisions" not in d["context"]["prior"], d["context"]["prior"]
