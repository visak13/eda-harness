"""F20 (2026-08-17) — G-SPEC: a recipe cannot close succeeded while a spec
it consults has no compiled doc, or its neuron sits in pending_review.

Root cause this closes: Guard B fires only at worker spawn (and only when
spec_ids are stamped); the TRAINING flow had no close gate at all, so a
recipe could close while its own specialist never compiled.
"""

from datetime import datetime, timezone

from edp_claude.schemas import Recipe, Specialization
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.tools._tools import CloseRecipe, _CloseRecipeIn


def _now():
    return datetime.now(timezone.utc)


def _setup(ctx):
    ctx.recipes.save(Recipe(
        recipe_id="recipe-f20", user_goal_verbatim="g",
        user_goal_distilled="g", domain="software_engineering",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "done", "depends_on": [], "execution": "inline"}],
        created_at=_now(), updated_at=_now(),
    ))
    ctx.plans.save(Plan(
        plan_id="recipe-f20-s1", recipe_id="recipe-f20",
        recipe_step_id="s1", domain="software_engineering",
        shape="parallel_multitool", goal="g", state="dispatching",
        actions=[Action(
            action_id="a1", description="d", status="done",
            executor_mode="inline", spec_ids=["spec-x"],
            acceptance=Acceptance(kind="manual_review", expected="x",
                                  actual="done"))]))
    ctx.specs.save(Specialization(
        spec_id="spec-x", neuron_id="x", name="X", subject="x",
        entries=[], created_at=_now(), updated_at=_now()))


async def test_close_refused_while_consulted_spec_has_no_doc(tmp_path):
    ctx = make_context(tmp_path)
    _setup(ctx)
    refused = await CloseRecipe(ctx)._run(_CloseRecipeIn(
        recipe_id="recipe-f20",
        final_outcome={"status": "succeeded", "summary": "s"}))
    assert not refused.ok
    assert "G-SPEC" in refused.message and "spec-x" in refused.message

    # compile the doc → the gate clears
    ctx.specs.write_doc("spec-x", "# X — compiled stack doc\nrules…")
    ok = await CloseRecipe(ctx)._run(_CloseRecipeIn(
        recipe_id="recipe-f20",
        final_outcome={"status": "succeeded", "summary": "s"}))
    assert ok.ok, ok


async def test_non_success_close_carries_no_spec_gate(tmp_path):
    ctx = make_context(tmp_path)
    _setup(ctx)
    ok = await CloseRecipe(ctx)._run(_CloseRecipeIn(
        recipe_id="recipe-f20",
        final_outcome={"status": "abandoned", "summary": "s"}))
    assert ok.ok, ok
