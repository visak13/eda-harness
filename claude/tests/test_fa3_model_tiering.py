"""s17 FA3 — per-action model tiering (MODEL-TIERING-BENCHMARK.md §5 +
S17-FINDINGS-V2-AUTONOMY-LENS.md FA3).

Locks the dispatch wiring: a planner stamps an OPTIONAL per-action `model`
tier (Sonnet 4.6 for a MEASURED-safe NARROW worker); the worker dispatch path
(pool_spawn_worker) threads it to the pool spawn. When NO tier is stamped the
spawn carries model=None → the host default tier (Opus): behaviour byte-
identical to pre-FA3. Other roles never carry an override.

Hard gates proven here:
  (1) default (no stamp) → spawn model=None  AND  the serialized action OMITS
      the new `model` key entirely (byte-shape-identical to the pre-FA3 schema,
      so a pre-restart extra='forbid' reader never trips on it);
  (2) a stamped tier reaches the spawn verbatim and round-trips on disk;
  (3) the planner can stamp/clear it via update_object('action').
"""
from edp_contracts import ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _plan_with_action(env):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner", estimate={"hours": 1}))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build",
                             goal="build the thing"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="do generic narrow work"))
    return pid


async def test_fa3_default_no_override_spawns_opus_default(env):
    # No tier stamped → the dispatch threads model=None (host default = Opus).
    pid = await _plan_with_action(env)
    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    spawn = next(s for s in env.ctx.pool.spawns
                 if s.get("handle") == f"{pid}:a1")
    assert spawn["model"] is None, spawn

    # byte-shape: the action with no override serializes WITHOUT a `model` key.
    p = env.ctx.plans.load(pid)
    a = next(a for a in p.actions if a.action_id == "a1")
    assert a.model is None
    assert "model" not in a.model_dump(), "default must omit the model key"


async def test_fa3_stamped_tier_reaches_spawn_and_roundtrips(env):
    # Planner stamps Sonnet on a narrow action via update_object.
    pid = await _plan_with_action(env)
    _ok(await env.call("update_object", type="action",
                       ids={"plan_id": pid, "action_id": "a1"},
                       patch={"model": "claude-sonnet-4-6"}))

    # persisted + round-trips on disk
    p = env.ctx.plans.load(pid)
    a = next(a for a in p.actions if a.action_id == "a1")
    assert a.model == "claude-sonnet-4-6"
    assert a.model_dump()["model"] == "claude-sonnet-4-6"

    # the dispatch threads the stamped tier to the pool spawn verbatim
    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    spawn = next(s for s in env.ctx.pool.spawns
                 if s.get("handle") == f"{pid}:a1")
    assert spawn["model"] == "claude-sonnet-4-6", spawn


async def test_fa3_tier_can_be_cleared_back_to_default(env):
    pid = await _plan_with_action(env)
    _ok(await env.call("update_object", type="action",
                       ids={"plan_id": pid, "action_id": "a1"},
                       patch={"model": "claude-sonnet-4-6"}))
    _ok(await env.call("update_object", type="action",
                       ids={"plan_id": pid, "action_id": "a1"},
                       patch={"model": None}))
    p = env.ctx.plans.load(pid)
    a = next(a for a in p.actions if a.action_id == "a1")
    assert a.model is None
    assert "model" not in a.model_dump()
