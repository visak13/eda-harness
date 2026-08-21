"""QoL R1+R3 (2026-08-21) — batch authoring verbs (record_outcome /
add_action), the low-level-strategy dispatch advisory, and the curiosity
consult carrying the verbatim goal."""

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


def _mk(tmp_path, rid="r-qolr"):
    ctx = make_context(tmp_path)
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="build me a real thing",
        user_goal_distilled="g", domain="software_engineering",
        state="comprehending",
        comprehension={"curiosity_cleared": True, "user_signoff": True,
                       "branches": [], "expected_outcomes": []},
        steps=[], created_at=_now(), updated_at=_now(),
    ))
    return ctx, {t.name: t for t in build_registry(ctx)}


async def test_record_outcome_batch(tmp_path):
    ctx, t = _mk(tmp_path)
    ok = await t["record_outcome"].run({
        "recipe_id": "r-qolr",
        "outcomes": [
            {"description": "d1", "verification": "v1"},
            {"description": "d2", "verification": "v2",
             "deliverable": "runnable_app", "user_path": "run it cold"},
        ]})
    assert isinstance(ok, ToolOk), ok
    d = _d(ok)
    assert d["outcome_ids"] == ["o1", "o2"]
    r = ctx.recipes.load("r-qolr")
    assert [o.id for o in r.comprehension.expected_outcomes] == ["o1", "o2"]
    assert r.comprehension.expected_outcomes[1].deliverable == "runnable_app"
    assert r.comprehension.expected_outcomes[1].user_path == "run it cold"


async def test_record_outcome_needs_single_or_batch(tmp_path):
    ctx, t = _mk(tmp_path)
    res = await t["record_outcome"].run({"recipe_id": "r-qolr"})
    assert isinstance(res, ToolError)
    assert "outcomes=" in res.message


async def _to_plan(t):
    await t["record_outcome"].run({
        "recipe_id": "r-qolr", "description": "d", "verification": "v"})
    await t["add_step"].run({
        "recipe_id": "r-qolr", "description": "s",
        "execution": "spawn_planner", "serves": ["o1"],
        "estimate": {"hours": 1}})
    await t["create_plan"].run({
        "recipe_id": "r-qolr", "step_id": "s1", "shape": "x", "goal": "g"})


async def test_add_action_batch_appends_all(tmp_path):
    ctx, t = _mk(tmp_path)
    await _to_plan(t)
    ok = await t["add_action"].run({
        "plan_id": "r-qolr-s1",
        "actions": [
            {"action_id": "a1", "description": "first", "serves": ["o1"]},
            {"action_id": "a2", "description": "second",
             "depends_on": ["a1"], "serves": ["o1"]},
        ]})
    assert isinstance(ok, ToolOk), ok
    p = ctx.plans.load("r-qolr-s1")
    assert [a.action_id for a in p.actions] == ["a1", "a2"]
    assert p.actions[1].depends_on == ["a1"]


async def test_add_action_batch_is_atomic_on_refusal(tmp_path):
    ctx, t = _mk(tmp_path)
    await _to_plan(t)
    res = await t["add_action"].run({
        "plan_id": "r-qolr-s1",
        "actions": [
            {"action_id": "a1", "description": "fine", "serves": ["o1"]},
            {"action_id": "a1", "description": "dup id refuses"},
        ]})
    assert isinstance(res, ToolError)
    # NOTHING landed — the first item must not survive the second's refusal
    assert ctx.plans.load("r-qolr-s1").actions == []


async def test_add_action_needs_single_or_batch(tmp_path):
    ctx, t = _mk(tmp_path)
    await _to_plan(t)
    res = await t["add_action"].run({"plan_id": "r-qolr-s1"})
    assert isinstance(res, ToolError)
    assert "actions=" in res.message


async def test_spawn_advises_missing_low_level_strategy(tmp_path):
    from edp_claude.tools._tools import PoolSpawnWorker, _SpawnWorkerIn
    ctx, t = _mk(tmp_path)
    await t["record_outcome"].run({
        "recipe_id": "r-qolr", "description": "d", "verification": "v"})
    for n in (1, 2, 3):
        await t["add_step"].run({
            "recipe_id": "r-qolr", "description": f"s{n}",
            "execution": "spawn_planner", "serves": ["o1"],
            "estimate": {"hours": 1}})
    await t["create_plan"].run({
        "recipe_id": "r-qolr", "step_id": "s1", "shape": "x", "goal": "g"})
    await t["add_action"].run({
        "plan_id": "r-qolr-s1", "action_id": "a1", "description": "build",
        "serves": ["o1"]})
    res = await PoolSpawnWorker(ctx)._run(
        _SpawnWorkerIn(plan_id="r-qolr-s1", action_id="a1"))
    assert res.ok, res
    kinds = [a["kind"] for a in (_d(res).get("advisories") or [])]
    assert "no_low_level_strategy" in kinds
    # review legs are exempt — judgment needs no build spec
    await t["add_action"].run({
        "plan_id": "r-qolr-s1", "action_id": "r1",
        "description": "review it", "leg_kind": "review"})
    res2 = await PoolSpawnWorker(ctx)._run(
        _SpawnWorkerIn(plan_id="r-qolr-s1", action_id="r1",
                       role="reviewer"))
    kinds2 = [a["kind"] for a in (_d(res2).get("advisories") or [])] \
        if res2.ok else []
    assert "no_low_level_strategy" not in kinds2


async def test_small_recipe_skips_strategy_advisory(tmp_path):
    from edp_claude.tools._tools import PoolSpawnWorker, _SpawnWorkerIn
    ctx, t = _mk(tmp_path)
    await _to_plan(t)          # 1-step recipe
    await t["add_action"].run({
        "plan_id": "r-qolr-s1", "action_id": "a1", "description": "build",
        "serves": ["o1"]})
    res = await PoolSpawnWorker(ctx)._run(
        _SpawnWorkerIn(plan_id="r-qolr-s1", action_id="a1"))
    assert res.ok, res
    kinds = [a["kind"] for a in (_d(res).get("advisories") or [])]
    assert "no_low_level_strategy" not in kinds


async def test_dispatch_hold_blocks_worker_spawn(tmp_path):
    # Sol review #3: the hold used to stop waves + planner spawns but not
    # a live planner's worker spawns — porous where the work happens.
    from edp_claude.objects import update_object
    from edp_claude.tools._tools import PoolSpawnWorker, _SpawnWorkerIn
    ctx, t = _mk(tmp_path)
    await _to_plan(t)
    await t["add_action"].run({
        "plan_id": "r-qolr-s1", "action_id": "a1", "description": "build",
        "serves": ["o1"]})
    out = await update_object(ctx, "recipe", {"recipe_id": "r-qolr"},
                              {"dispatch_hold": "wait for my go"})
    assert out.get("ok"), out
    res = await PoolSpawnWorker(ctx)._run(
        _SpawnWorkerIn(plan_id="r-qolr-s1", action_id="a1"))
    assert not res.ok
    assert "OPERATOR HOLD" in res.message
    # pre-stamp rolled back — no phantom in_progress
    assert ctx.plans.load("r-qolr-s1").actions[0].status == "pending"
    out = await update_object(ctx, "recipe", {"recipe_id": "r-qolr"},
                              {"dispatch_hold": None})
    assert out.get("ok"), out
    res = await PoolSpawnWorker(ctx)._run(
        _SpawnWorkerIn(plan_id="r-qolr-s1", action_id="a1"))
    assert res.ok, res


def test_producer_verify_stands_down_for_runnable_app():
    # Sol review #6: the walking-skeleton guide demands STARTING a
    # runnable_app; the guard must not refuse the start command.
    from edp_claude.tools._tools import _reject_producer_verify
    verify = {"check": "command", "cmd": "npm start"}
    assert _reject_producer_verify(verify, deliverable="runnable_app") \
        is None
    assert _reject_producer_verify(verify, deliverable=None) is not None


async def test_outcome_form_patchable_and_advised(tmp_path):
    # Sol review #1: a formless outcome draws a loud authoring advisory,
    # and deliverable/user_path are patchable after the fact.
    from edp_claude.objects import update_object
    ctx, t = _mk(tmp_path)
    res = await t["record_outcome"].run({
        "recipe_id": "r-qolr", "description": "d", "verification": "v"})
    assert "ADVISORY" in _d(res)["note"]
    out = await update_object(
        ctx, "outcome", {"recipe_id": "r-qolr", "outcome_id": "o1"},
        {"deliverable": "runnable_app", "user_path": "run it cold"})
    assert out.get("ok"), out
    o = ctx.recipes.load("r-qolr").comprehension.expected_outcomes[0]
    assert o.deliverable == "runnable_app" and o.user_path == "run it cold"


def test_render_depth_cap_never_emits_json():
    from edp_claude.tools.render_text import render_payload
    deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}
    text = render_payload(deep)
    assert "{" not in text and "depth cap" in text


async def test_curiosity_consult_carries_verbatim_goal(tmp_path):
    ctx, t = _mk(tmp_path)
    res = await t["consult_curiosity"].run({
        "decision": "how to build", "context": "my framing",
        "handle": "r-qolr"})
    assert isinstance(res, ToolOk), res
    cid = _d(res)["curiosity_id"]
    [consult] = [m for m in ctx.broker.inboxes.get(cid, [])
                 if m.kind == "consult"]
    assert consult.body["user_goal_verbatim"] == "build me a real thing"
    assert consult.body["caller_framing"] == "my framing"
