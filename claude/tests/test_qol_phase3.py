"""QoL Phase 3 (2026-08-21) — deliverable FORM travels the whole chain,
the producer-verify guard stands down for interactive/visual forms, and
start_recipe nudges the missing workspace."""

from datetime import datetime, timezone

import pytest
from edp_contracts import ToolError, ToolOk

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


def _d(res):
    d = res.data
    return d if isinstance(d, dict) else d.model_dump()


def _now():
    return datetime.now(timezone.utc)


def _mk(tmp_path, rid="r-qol3"):
    ctx = make_context(tmp_path)
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="build me a UI",
        user_goal_distilled="g", domain="software_engineering",
        state="comprehending",
        comprehension={"curiosity_cleared": True, "user_signoff": True,
                       "branches": [], "expected_outcomes": []},
        steps=[], created_at=_now(), updated_at=_now(),
    ))
    return ctx, {t.name: t for t in build_registry(ctx)}


async def test_deliverable_travels_outcome_step_action(tmp_path):
    ctx, t = _mk(tmp_path)
    ok = await t["record_outcome"].run({
        "recipe_id": "r-qol3", "description": "a usable page",
        "verification": "exercise it in a browser",
        "deliverable": "interactive_ui"})
    assert isinstance(ok, ToolOk)
    ok = await t["add_step"].run({
        "recipe_id": "r-qol3", "description": "build it",
        "execution": "spawn_planner", "serves": ["o1"],
        "estimate": {"hours": 1}, "deliverable": "interactive_ui"})
    assert isinstance(ok, ToolOk), ok
    ok = await t["create_plan"].run({
        "recipe_id": "r-qol3", "step_id": "s1", "shape": "x", "goal": "g"})
    assert isinstance(ok, ToolOk), ok
    ok = await t["add_action"].run({
        "plan_id": "r-qol3-s1", "action_id": "a1", "description": "d",
        "serves": ["o1"], "deliverable": "interactive_ui"})
    assert isinstance(ok, ToolOk), ok
    r = ctx.recipes.load("r-qol3")
    assert r.comprehension.expected_outcomes[0].deliverable == \
        "interactive_ui"
    assert r.steps[0].deliverable == "interactive_ui"
    assert ctx.plans.load("r-qol3-s1").actions[0].deliverable == \
        "interactive_ui"


async def test_deliverable_enum_refuses_junk(tmp_path):
    ctx, t = _mk(tmp_path)
    res = await t["record_outcome"].run({
        "recipe_id": "r-qol3", "description": "d", "verification": "v",
        "deliverable": "webpage"})
    assert isinstance(res, ToolError)
    assert "interactive_ui" in res.message      # the enum teaches values


async def test_producer_verify_stands_down_for_interactive(tmp_path):
    ctx, t = _mk(tmp_path)
    await t["record_outcome"].run({
        "recipe_id": "r-qol3", "description": "d", "verification": "v"})
    await t["add_step"].run({
        "recipe_id": "r-qol3", "description": "s",
        "execution": "spawn_planner", "serves": ["o1"],
        "estimate": {"hours": 1}})
    await t["create_plan"].run({
        "recipe_id": "r-qol3", "step_id": "s1", "shape": "x", "goal": "g"})
    verify = {"check": "command", "cmd": "npm run dev -- --smoke"}
    # without a declared form: producer command refused (the old guard)
    res = await t["add_action"].run({
        "plan_id": "r-qol3-s1", "action_id": "a1", "description": "d",
        "serves": ["o1"], "verify": verify})
    assert isinstance(res, ToolError)
    assert "producer command" in res.message
    # interactive_ui: exercising the artifact is the WHOLE point
    ok = await t["add_action"].run({
        "plan_id": "r-qol3-s1", "action_id": "a1", "description": "d",
        "serves": ["o1"], "verify": verify,
        "deliverable": "interactive_ui"})
    assert isinstance(ok, ToolOk), ok


async def test_acceptor_consult_carries_deliverable(tmp_path):
    ctx, t = _mk(tmp_path)
    await t["record_outcome"].run({
        "recipe_id": "r-qol3", "description": "a usable page",
        "verification": "v", "deliverable": "interactive_ui"})
    r = ctx.recipes.load("r-qol3")
    r.comprehension.expected_outcomes[0].met = True
    r.comprehension.expected_outcomes[0].met_evidence = "e"
    ctx.recipes.save(r)
    res = await t["dispatch_acceptance"].run({"recipe_id": "r-qol3"})
    assert isinstance(res, ToolOk), res
    acc = _d(res)["acceptor_id"]
    msgs = ctx.broker.inboxes.get(acc, [])
    [consult] = [m for m in msgs if m.kind == "consult"]
    assert consult.body["outcomes"][0]["deliverable"] == "interactive_ui"


async def test_start_recipe_nudges_missing_workspace(tmp_path):
    ctx = make_context(tmp_path)
    t = {x.name: x for x in build_registry(ctx)}
    res = await t["start_recipe"].run({
        "goal": "build a thing in my folder", "domain": "generic"})
    assert isinstance(res, ToolOk)
    assert "NO WORKSPACE" in _d(res)["note"]
    # with a valid workspace (abs + exists + .git): no nudge
    ws = tmp_path / "repo"
    (ws / ".git").mkdir(parents=True)
    res2 = await t["start_recipe"].run({
        "goal": "another goal entirely", "domain": "generic",
        "workspace": str(ws)})
    assert isinstance(res2, ToolOk), res2
    assert "NO WORKSPACE" not in _d(res2)["note"]


async def test_dispatch_hold_blocks_wave_and_spawn(tmp_path):
    from edp_claude.objects import update_object
    ctx, t = _mk(tmp_path)
    await t["record_outcome"].run({
        "recipe_id": "r-qol3", "description": "d", "verification": "v"})
    await t["add_step"].run({
        "recipe_id": "r-qol3", "description": "s",
        "execution": "spawn_planner", "serves": ["o1"],
        "estimate": {"hours": 1}})
    out = await update_object(
        ctx, "recipe", {"recipe_id": "r-qol3"},
        {"dispatch_hold": "train ALL specialists before any dispatch"})
    assert out.get("ok"), out
    # the wave honors it
    res = await t["next_action"].run({
        "handle": "r-qol3", "handle_type": "recipe", "all_ready": True})
    assert isinstance(res, ToolOk)
    assert _d(res)["count"] == 0
    assert "OPERATOR HOLD" in _d(res)["note"]
    # the spawn refuses it, naming the rule + the clearing move
    res = await t["pool_spawn_planner"].run({
        "recipe_id": "r-qol3", "step_id": "s1"})
    assert isinstance(res, ToolError)
    assert "OPERATOR HOLD" in res.message
    assert "train ALL specialists" in res.message
    # cleared -> spawn proceeds
    out = await update_object(ctx, "recipe", {"recipe_id": "r-qol3"},
                              {"dispatch_hold": None})
    assert out.get("ok"), out
    res = await t["pool_spawn_planner"].run({
        "recipe_id": "r-qol3", "step_id": "s1"})
    assert isinstance(res, ToolOk), res
