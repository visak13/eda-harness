"""Context-diet Phase 2 — step-level cross-cutting concerns flow down.

The Action layer has carried `concerns` since SPECIALIZATION-LAYERED-RULESETS;
the step layer could not, so a concern the neuron knew at map time died
between recipe -> step -> plan on the planner's loose interpretation. Phase 2
adds RecipeStep.concerns + acceptance_sketch, and a flow-down gate at
record_plan (submission) with a pool_spawn_worker backstop (the incremental
create_plan/add_action path never passes record_plan).

READ-BACK DISCIPLINE: a past incident silently dropped acceptance fields on
action create (ok + version + no advisory while storing empty) — so every
field here is asserted through the full round trip: tool write -> store
reload -> read_object -> digest row -> tiering passthrough.
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
    return res


async def _recipe_with_step(env, concerns=None, sketch=None):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    kw = {}
    if concerns:
        kw["concerns"] = concerns
    if sketch:
        kw["acceptance_sketch"] = sketch
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner", **kw))["step_id"]
    return rid, sid


# ── read-back: the fields survive the whole round trip ─────────────────────

async def test_step_concerns_round_trip(env):
    rid, sid = await _recipe_with_step(
        env, concerns=["security", "a11y"],
        sketch=["API rejects bad input with 4xx"])
    # store reload
    s = next(x for x in env.ctx.recipes.load(rid).steps if x.step_id == sid)
    assert s.concerns == ["security", "a11y"]
    assert s.acceptance_sketch == ["API rejects bad input with 4xx"]
    # read_object('step')
    from edp_claude import objects
    view = await objects.read_object(env.ctx, "step", recipe_id=rid,
                                     step_id=sid)
    assert view["concerns"] == ["security", "a11y"]
    assert view["acceptance_sketch"] == ["API rejects bad input with 4xx"]
    # digest row carries them (a planner orients WITHOUT a full read)
    dig = _ok(await env.call("get_recipe_digest", recipe_id=rid))
    row = next(x for x in dig["open_steps"] if x["step_id"] == sid)
    assert row["concerns"] == ["security", "a11y"]
    assert row["acceptance_sketch"] == ["API rejects bad input with 4xx"]


async def test_legacy_step_serializes_without_new_keys(env):
    rid, sid = await _recipe_with_step(env)          # no concerns, no sketch
    s = next(x for x in env.ctx.recipes.load(rid).steps if x.step_id == sid)
    dumped = s.model_dump()
    assert "concerns" not in dumped, "emission gate broken (byte-compat)"
    assert "acceptance_sketch" not in dumped
    dig = _ok(await env.call("get_recipe_digest", recipe_id=rid))
    row = next(x for x in dig["open_steps"] if x["step_id"] == sid)
    assert "concerns" not in row and "acceptance_sketch" not in row


# ── flow-down gate at dispatch (the incremental-path backstop) ─────────────

async def _drafted_plan(env, rid, sid, action_concerns=None):
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    kw = {"concerns": action_concerns} if action_concerns else {}
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="work", **kw))
    return pid


async def test_dispatch_refused_when_step_concern_uncovered(env):
    rid, sid = await _recipe_with_step(env, concerns=["security"])
    pid = await _drafted_plan(env, rid, sid)         # no action carries it
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    _refused(res, "step concern 'security'", "assemble_ruleset")
    # the pre-stamp rollback held: the action is not stranded in_progress
    a = next(x for x in env.ctx.plans.load(pid).actions
             if x.action_id == "a1")
    assert a.status != "in_progress"


async def test_dispatch_passes_when_concern_covered(env):
    rid, sid = await _recipe_with_step(env, concerns=["security"])
    pid = await _drafted_plan(env, rid, sid, action_concerns=["Security"])
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    # spawn may still fail at the fake pool — but never on the flow-down gate
    if isinstance(res, ToolError):
        assert "step concern" not in res.message, res.message


async def test_dispatch_refused_when_sketch_unmapped(env):
    rid, sid = await _recipe_with_step(
        env, sketch=["exports a valid CSV", "handles empty input"])
    pid = await _drafted_plan(env, rid, sid)
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    _refused(res, "exports a valid CSV", "sketch_covered_by")
    # planner maps the lines explicitly -> gate passes
    p = env.ctx.plans.load(pid)
    p.sketch_covered_by = {"exports a valid CSV": ["a1"],
                           "handles empty input": ["a1"]}
    env.ctx.plans.save(p)
    res2 = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    if isinstance(res2, ToolError):
        assert "sketch" not in res2.message, res2.message


async def test_sketch_mapping_to_unknown_action_refused(env):
    rid, sid = await _recipe_with_step(env, sketch=["works end to end"])
    pid = await _drafted_plan(env, rid, sid)
    p = env.ctx.plans.load(pid)
    p.sketch_covered_by = {"works end to end": ["a99"]}
    env.ctx.plans.save(p)
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    _refused(res, "unknown", "a99")


# ── flow-down gate at record_plan (submission path) ────────────────────────

async def test_record_plan_refused_on_uncovered_concern(env):
    rid, sid = await _recipe_with_step(env, concerns=["perf"])
    plan = dict(
        plan_id=f"{rid}-{sid}", recipe_id=rid, recipe_step_id=sid,
        domain="api", shape="x", goal="g", state="drafted",
        actions=[{"action_id": "a1", "description": "d", "status": "pending",
                  "depends_on": [], "executor_mode": "subagent",
                  "acceptance": {"kind": "manual_review"}}],
        context={})
    _refused(await env.call("record_plan", plan=plan),
             "step concern 'perf'")
    plan["actions"][0]["concerns"] = ["perf"]
    _ok(await env.call("record_plan", plan=plan))


async def test_legacy_step_gates_nothing(env):
    rid, sid = await _recipe_with_step(env)          # legacy: no obligations
    pid = await _drafted_plan(env, rid, sid)
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    if isinstance(res, ToolError):
        assert "cross-cutting" not in res.message, res.message
