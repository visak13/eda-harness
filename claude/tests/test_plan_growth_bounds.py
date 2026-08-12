"""Plan-growth bounds (2026-08-01) — planners and neurons pay for the map.

Measured abuse: plan …39fd30-s11 reached 44 actions, zero batched, with
2-4KB essay descriptions — every unbatched action is a spawned shell
(~10k cold start + ~6k brief) and nothing surfaced that cost at authoring.

Three mechanisms: a description write cap (add_action AND add_step, the
_CONTEXT_TEXT_MAX pattern — tool path only, legacy essays still load), a
soft cost meter riding every append past EDP_PLAN_ACTION_SOFT, and a hard
ceiling past which new actions are accepted BATCHED ONLY.
"""
from edp_contracts import ToolError, ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _refused(res, *needles):
    assert isinstance(res, ToolError), res
    assert res.code == "tool_precondition", res
    for n in needles:
        assert n in res.message, (n, res.message)


async def _plan(env):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner", estimate={"hours": 1}))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    return rid, pid


async def test_action_description_write_cap(env):
    _, pid = await _plan(env)
    essay = "READ THIS FIRST — THIS IS A RE-DISPATCH. " * 60   # ~2.5KB
    _refused(await env.call("add_action", plan_id=pid, action_id="a1",
                            description=essay),
             "write cap", "grounding brief")
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="build the export module"))


async def test_step_description_write_cap(env):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    _refused(await env.call("add_step", recipe_id=rid,
                            description="x" * 2000,
                            execution="spawn_planner", estimate={"hours": 1}),
             "write cap")


async def test_soft_meter_rides_appends(env, monkeypatch):
    monkeypatch.setenv("EDP_PLAN_ACTION_SOFT", "3")
    monkeypatch.setenv("EDP_PLAN_ACTION_CEILING", "50")
    _, pid = await _plan(env)
    for i in range(1, 4):
        d = _ok(await env.call("add_action", plan_id=pid,
                               action_id=f"a{i}", description="w"))
        assert not any(a.get("kind") == "plan_growth_cost"
                       for a in (d.get("advisories") or []))
    d = _ok(await env.call("add_action", plan_id=pid, action_id="a4",
                           description="w"))
    costs = [a for a in (d.get("advisories") or [])
             if a.get("kind") == "plan_growth_cost"]
    assert costs and "COST METER" in costs[0]["detail"]
    assert "batch_group" in costs[0]["detail"]


async def test_ceiling_accepts_batched_only(env, monkeypatch):
    monkeypatch.setenv("EDP_PLAN_ACTION_SOFT", "2")
    monkeypatch.setenv("EDP_PLAN_ACTION_CEILING", "4")
    _, pid = await _plan(env)
    for i in range(1, 5):
        _ok(await env.call("add_action", plan_id=pid, action_id=f"a{i}",
                           description="w"))
    # unbatched append past the ceiling: refused with the remedies named
    _refused(await env.call("add_action", plan_id=pid, action_id="a5",
                            description="w"),
             "BATCHED ONLY", "batch_group", "COST METER")
    # a batched append still lands (one shell per group — the remedy itself)
    _ok(await env.call("add_action", plan_id=pid, action_id="a5",
                       description="w", batch_group="tail"))


async def test_step_count_meter(env, monkeypatch):
    monkeypatch.setenv("EDP_RECIPE_STEP_SOFT", "2")
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    _ok(await env.call("add_step", recipe_id=rid, description="one",
                       execution="spawn_planner", estimate={"hours": 1}))
    _ok(await env.call("add_step", recipe_id=rid, description="two",
                       execution="spawn_planner", estimate={"hours": 1}))
    d = _ok(await env.call("add_step", recipe_id=rid, description="three",
                           execution="spawn_planner", estimate={"hours": 1}))
    assert any("map_growth_cost" in a for a in (d.get("advisories") or [])), d
