"""Tool-doc overhaul (2026-08-21) — the missing update paths that forced
re-authoring: plan-level patch, action serves/leg_kind/deliverable, step
serves/estimate/acceptance_sketch/concerns/deliverable."""

from datetime import datetime, timezone

import pytest

from edp_claude.objects import ObjectError, update_object
from edp_claude.schemas import Recipe
from edp_claude.server import make_context
from edp_claude.tools import build_registry

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _bare_seat(monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)


def _now():
    return datetime.now(timezone.utc)


async def _mk(tmp_path, rid="r-crud"):
    ctx = make_context(tmp_path)
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="crud goal",
        user_goal_distilled="g", domain="software_engineering",
        state="comprehending",
        comprehension={"curiosity_cleared": True, "user_signoff": True,
                       "branches": [], "expected_outcomes": []},
        steps=[], created_at=_now(), updated_at=_now(),
    ))
    t = {x.name: x for x in build_registry(ctx)}
    await t["record_outcome"].run({
        "recipe_id": rid, "outcomes": [
            {"description": "d1", "verification": "v1"},
            {"description": "d2", "verification": "v2"}]})
    await t["add_step"].run({
        "recipe_id": rid, "description": "s",
        "execution": "spawn_planner", "serves": ["o1"],
        "estimate": {"hours": 1}})
    await t["create_plan"].run({
        "recipe_id": rid, "step_id": "s1", "shape": "x", "goal": "g"})
    await t["add_action"].run({
        "plan_id": f"{rid}-s1", "action_id": "a1", "description": "d",
        "serves": ["o1"]})
    return ctx, t


async def test_plan_level_fields_patchable(tmp_path):
    ctx, t = await _mk(tmp_path)
    out = await update_object(
        ctx, "plan", {"plan_id": "r-crud-s1"},
        {"review_policy": {"triggers": ["novel decision"],
                           "justify": {"r1": "novel decision: new seam"}},
         "shape": "walking-skeleton"})
    assert out.get("ok"), out
    p = ctx.plans.load("r-crud-s1")
    assert p.shape == "walking-skeleton"
    assert p.review_policy["justify"]["r1"].startswith("novel")


async def test_plan_patch_refuses_unknown_and_bad_policy(tmp_path):
    ctx, t = await _mk(tmp_path)
    with pytest.raises(ObjectError, match="allows"):
        await update_object(ctx, "plan", {"plan_id": "r-crud-s1"},
                            {"actions": []})
    with pytest.raises(ObjectError, match="mapping"):
        await update_object(ctx, "plan", {"plan_id": "r-crud-s1"},
                            {"review_policy": "always review"})


async def test_action_serves_leg_kind_deliverable_patchable(tmp_path):
    ctx, t = await _mk(tmp_path)
    out = await update_object(
        ctx, "action", {"plan_id": "r-crud-s1", "action_id": "a1"},
        {"serves": ["o2"], "leg_kind": "review",
         "deliverable": "runnable_app"})
    assert out.get("ok"), out
    a = ctx.plans.load("r-crud-s1").actions[0]
    assert a.serves == ["o2"]
    assert a.leg_kind == "review"
    assert a.deliverable == "runnable_app"


async def test_action_serves_patch_validates_outcome_ids(tmp_path):
    ctx, t = await _mk(tmp_path)
    with pytest.raises(ObjectError, match="unknown outcome"):
        await update_object(
            ctx, "action", {"plan_id": "r-crud-s1", "action_id": "a1"},
            {"serves": ["o9"]})


async def test_step_new_fields_patchable(tmp_path):
    ctx, t = await _mk(tmp_path)
    out = await update_object(
        ctx, "step", {"recipe_id": "r-crud", "step_id": "s1"},
        {"serves": ["o1", "o2"], "estimate": {"hours": 3},
         "acceptance_sketch": ["it runs"], "concerns": ["security"],
         "deliverable": "runnable_app"})
    assert out.get("ok"), out
    s = ctx.recipes.load("r-crud").steps[0]
    assert s.serves == ["o1", "o2"]
    assert s.estimate == {"hours": 3}
    assert s.acceptance_sketch == ["it runs"]
    assert s.concerns == ["security"]
    assert s.deliverable == "runnable_app"


async def test_step_estimate_patch_validates_shape(tmp_path):
    ctx, t = await _mk(tmp_path)
    with pytest.raises(ObjectError, match="estimate"):
        await update_object(
            ctx, "step", {"recipe_id": "r-crud", "step_id": "s1"},
            {"estimate": "3 hours"})
