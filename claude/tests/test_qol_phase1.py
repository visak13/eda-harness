"""QoL Phase 1 (2026-08-21) — tool-ergonomics regressions from the
baseline drill (docs/design/qol-baseline.md): param aliases, id echo,
loud unknown kwargs, explained empty waves, sketch_covers patching,
proposed-ban injection filter, and the digest's verbatim goal."""

from datetime import datetime, timezone

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.objects import update_object
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


def _mk(tmp_path, rid="r-qol1", signoff=True, sketch=None):
    ctx = make_context(tmp_path)
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="the REAL goal words",
        user_goal_distilled="distilled", domain="software_engineering",
        state="executing",
        comprehension={"curiosity_cleared": True, "user_signoff": signoff,
                       "branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner",
                "acceptance_sketch": sketch or ["bar A", "bar B"]}],
        created_at=_now(), updated_at=_now(),
    ))
    return ctx, {t.name: t for t in build_registry(ctx)}


# ── F16: writes echo the id they mint ──────────────────────────────────────
async def test_record_outcome_echoes_its_outcome_id(tmp_path):
    ctx, t = _mk(tmp_path)
    res = await t["record_outcome"].run({
        "recipe_id": "r-qol1", "description": "d", "verification": "v"})
    assert isinstance(res, ToolOk)
    assert _d(res)["outcome_id"] == "o1"


# ── F12: param aliases ─────────────────────────────────────────────────────
async def test_create_plan_accepts_recipe_step_id_alias(tmp_path):
    ctx, t = _mk(tmp_path)
    res = await t["create_plan"].run({
        "recipe_id": "r-qol1", "recipe_step_id": "s1",
        "shape": "x", "goal": "g"})
    assert isinstance(res, ToolOk), res
    assert _d(res)["plan_id"] == "r-qol1-s1"


async def test_grounding_brief_accepts_text_alias(tmp_path):
    ctx, t = _mk(tmp_path)
    await t["create_plan"].run({"recipe_id": "r-qol1", "step_id": "s1",
                                "shape": "x", "goal": "g"})
    res = await t["record_grounding_brief"].run({
        "plan_id": "r-qol1-s1", "text": "the brief"})
    assert isinstance(res, ToolOk), res


async def test_signoff_accepts_quote_alias(tmp_path):
    ctx, t = _mk(tmp_path, signoff=False)
    res = await t["record_comprehension_signoff"].run({
        "recipe_id": "r-qol1", "quote": "go ahead, proceed"})
    assert isinstance(res, ToolOk), res


async def test_branch_verdict_action_path_needs_no_recipe_id(tmp_path):
    ctx, t = _mk(tmp_path)
    await t["create_plan"].run({"recipe_id": "r-qol1", "step_id": "s1",
                                "shape": "x", "goal": "g"})
    await t["add_action"].run({
        "plan_id": "r-qol1-s1", "action_id": "a1", "description": "d"})
    res = await t["record_branch_verdict"].run({
        "plan_id": "r-qol1-s1", "action_id": "a1", "passed": True,
        "verdict": "re-ran the declared checks in a fresh shell; every "
                   "criterion holds against the compiled doc. PASS."})
    assert isinstance(res, ToolOk), res


async def test_branch_verdict_without_any_id_teaches_both_paths(tmp_path):
    ctx, t = _mk(tmp_path)
    res = await t["record_branch_verdict"].run({
        "branch_id": "b1", "verdict": "x" * 50})
    assert isinstance(res, ToolError)
    assert "plan_id" in res.message and "recipe_id" in res.message


# ── silent-kwarg drop is now a loud refusal ────────────────────────────────
async def test_add_action_unknown_kwarg_refused_loudly(tmp_path):
    ctx, t = _mk(tmp_path)
    await t["create_plan"].run({"recipe_id": "r-qol1", "step_id": "s1",
                                "shape": "x", "goal": "g"})
    res = await t["add_action"].run({
        "plan_id": "r-qol1-s1", "action_id": "a1", "description": "d",
        "review_trigger": "acceptance complexity"})
    assert isinstance(res, ToolError)
    assert "review_trigger" in res.message


# ── F21: an empty wave explains itself ─────────────────────────────────────
async def test_empty_recipe_wave_carries_reason_and_next_call(tmp_path):
    ctx, t = _mk(tmp_path)
    r = ctx.recipes.load("r-qol1")
    r.steps[0].status = "done"
    ctx.recipes.save(r)
    res = await t["next_action"].run({
        "handle": "r-qol1", "handle_type": "recipe", "all_ready": True})
    assert isinstance(res, ToolOk)
    assert _d(res)["count"] == 0
    assert "empty wave" in _d(res)["note"]
    assert "WITHOUT" in _d(res)["note"]


# ── pains #3/#5: sketch coverage is patchable post-authoring ───────────────
async def test_update_object_patches_sketch_covers(tmp_path):
    ctx, t = _mk(tmp_path)
    await t["create_plan"].run({"recipe_id": "r-qol1", "step_id": "s1",
                                "shape": "x", "goal": "g"})
    await t["add_action"].run({
        "plan_id": "r-qol1-s1", "action_id": "a1", "description": "d"})
    out = await update_object(ctx, "action",
                        {"plan_id": "r-qol1-s1", "action_id": "a1"},
                        {"sketch_covers": ["bar A"]})
    assert out.get("ok"), out
    assert ctx.plans.load("r-qol1-s1").sketch_covered_by == {
        "bar A": ["a1"]}


async def test_update_object_sketch_covers_refuses_unknown_line(tmp_path):
    from edp_claude.objects import ObjectError
    ctx, t = _mk(tmp_path)
    await t["create_plan"].run({"recipe_id": "r-qol1", "step_id": "s1",
                                "shape": "x", "goal": "g"})
    await t["add_action"].run({
        "plan_id": "r-qol1-s1", "action_id": "a1", "description": "d"})
    with pytest.raises(ObjectError, match="unknown sketch line"):
        await update_object(ctx, "action",
                      {"plan_id": "r-qol1-s1", "action_id": "a1"},
                      {"sketch_covers": ["not a declared bar"]})


# ── hop-11: proposed bans carry no teeth in briefs ─────────────────────────
async def test_proposed_ban_not_injected_and_labeled_in_brief(tmp_path):
    from edp_claude.schemas.recipe import RejectedOption
    from edp_claude.store.recipe_brief import render_recipe_brief
    ctx, t = _mk(tmp_path)
    r = ctx.recipes.load("r-qol1")
    r.context.rejected_options.append(RejectedOption(
        id="x1", text="never use frameworks", reason="user said tiny",
        status="proposed"))
    r.context.rejected_options.append(RejectedOption(
        id="x2", text="no cloud calls", reason="local only"))
    ctx.recipes.save(r)
    brief = render_recipe_brief(r)
    assert "PROPOSED" in brief and "no teeth yet" in brief
    # and the confirmation now leaves a durable trace
    res = await t["confirm_direction_constraints"].run({
        "recipe_id": "r-qol1", "ids": ["x1"], "action": "activate"})
    assert isinstance(res, ToolOk)
    ev = ctx.recipes.read_events_tail(
        "r-qol1", kinds=["constraints_confirmed"])
    assert len(ev) == 1
    row = ev[0] if isinstance(ev[0], dict) else ev[0].data
    assert row.get("activated") == ["x1"]


# ── F6: the digest serves the verbatim goal ────────────────────────────────
async def test_read_object_digest_carries_verbatim_goal(tmp_path):
    ctx, t = _mk(tmp_path)
    res = await t["read_object"].run({
        "type": "recipe", "ids": {"recipe_id": "r-qol1"},
        "detail": "digest"})
    assert isinstance(res, ToolOk)
    obj = res.data["object"] if isinstance(res.data, dict) else \
        res.data.model_dump()["object"]
    assert obj["user_goal_verbatim"] == "the REAL goal words"

# ── F3: every action read carries the 'you are here' position block ────────
async def test_action_read_carries_position_block(tmp_path):
    ctx, t = _mk(tmp_path)
    r = ctx.recipes.load("r-qol1")
    r.comprehension.expected_outcomes.append(
        __import__("edp_claude.schemas", fromlist=["Outcome"]).Outcome(
            id="o1", description="the working thing", verification="v"))
    r.steps[0].serves = ["o1"]
    ctx.recipes.save(r)
    await t["create_plan"].run({"recipe_id": "r-qol1", "step_id": "s1",
                                "shape": "x", "goal": "g"})
    await t["add_action"].run({
        "plan_id": "r-qol1-s1", "action_id": "a1", "description": "d"})
    res = await t["read_object"].run({
        "type": "action",
        "ids": {"plan_id": "r-qol1-s1", "action_id": "a1"}})
    obj = _d(res)["object"]
    pos = obj["position"]
    assert pos["user_goal_verbatim"] == "the REAL goal words"
    assert pos["step"].startswith("s1 — 1 of 1")
    assert pos["serves_outcomes"] == ["o1: the working thing"]


# ── F4: digest recent list drops empty recipe_saved noise ──────────────────
async def test_digest_recent_drops_empty_recipe_saved_rows(tmp_path):
    ctx, t = _mk(tmp_path)
    ctx.recipes.append_worklog("r-qol1", {"kind": "learning",
                                          "summary": "something real"})
    res = await t["get_recipe_digest"].run({"recipe_id": "r-qol1"})
    recent = _d(res)["recent_events"]["recent"]
    kinds = [x["kind"] for x in recent]
    assert "learning" in kinds
    assert "recipe_saved" not in kinds          # saved-noise suppressed
    assert _d(res)["recent_events"]["counts_by_kind"].get(
        "recipe_saved", 0) >= 1                 # but still counted
