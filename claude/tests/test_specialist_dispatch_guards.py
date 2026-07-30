"""Specialist-dispatch guards (2026-06-01).

The live failure: a planner expressed specialist-intent as PROSE in an
action description ("call get_specialization(spec_id=...)") and left the
structured `specialization` field null — so the action dispatched as a
GENERIC worker that merely read the spec doc instead of forking the trained
SME (and, with spec_id null, bypassed the whole layered ruleset).

Guard A: add_action refuses a description carrying a dispatch-mechanism token.
Guard B: pool_spawn_worker refuses an action that DECLARES a specialization
         (it must branch_specialist).
"""

from edp_contracts import ToolError, ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _plan(env):
    rid = _ok(await env.call("start_recipe", goal="build an api",
                             domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="linear-build", goal="build it"))["plan_id"]
    return pid


# ── Guard A: no dispatch mechanism in the work description ────────────────

async def test_add_action_rejects_get_specialization_in_description(env):
    pid = await _plan(env)
    res = await env.call(
        "add_action", plan_id=pid, action_id="a1",
        description="Audit the HMI; call get_specialization(spec_id=spec-x) "
                    "and apply its standards.")
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"
    assert "specialization" in res.message and "field" in res.message


async def test_add_action_rejects_branch_specialist_prose(env):
    pid = await _plan(env)
    res = await env.call(
        "add_action", plan_id=pid, action_id="a1",
        description="branch_specialist for this and build the endpoint")
    assert isinstance(res, ToolError)


async def test_add_action_allows_clean_description_with_specialization_field(env):
    # the RIGHT way: clean description + the structured field set.
    pid = await _plan(env)
    _ok(await env.call(
        "add_action", plan_id=pid, action_id="a1",
        description="Implement POST /login with validation and tests",
        specialization="Java Spring Boot REST API"))
    plan = env.ctx.plans.load(pid)
    a = next(a for a in plan.actions if a.action_id == "a1")
    # MULTI-SPEC (2026-06-03): the singular descriptor folds into the
    # canonical list; there is no parallel scalar attribute anymore.
    assert a.effective_specializations() == ["Java Spring Boot REST API"]


# ── Guard B (inverted 2026-06-02): specialist dispatches FRESH, but must be
#    resolved (spec_id stamped) AND have a compiled doc to load. ──────────────

def _stamp_spec_id(env, pid, action_id, spec_id):
    # MULTI-SPEC: stamp the canonical plural field (N=1 = one-element list).
    p = env.ctx.plans.load(pid)
    next(a for a in p.actions if a.action_id == action_id).spec_ids = [spec_id]
    env.ctx.plans.save(p)


async def test_pool_spawn_worker_requires_resolved_spec_id(env):
    # specialization declared but NOT resolved to a spec_id → refuse (the
    # planner must neuron_search + stamp spec_id so the worker can load a doc)
    pid = await _plan(env)
    _ok(await env.call(
        "add_action", plan_id=pid, action_id="a1",
        description="Implement POST /login with validation",
        specialization="Java Spring Boot REST API"))
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    assert isinstance(res, ToolError) and res.code == "tool_precondition"
    # generalized Guard B (MULTI-SPEC): unresolved declaration → spec_ids empty
    assert "spec_ids is empty" in res.message and "neuron_search" in res.message


async def test_pool_spawn_worker_requires_compiled_doc(env):
    # spec_id stamped but the spec has NO compiled doc → refuse (no grounding)
    pid = await _plan(env)
    sid = _ok(await env.call("create_specialization", name="Spring",
                             subject="spring", description="spring"))["spec_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="Implement POST /login",
                       specialization="Java Spring Boot REST API"))
    _stamp_spec_id(env, pid, "a1", sid)
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    assert isinstance(res, ToolError) and res.code == "tool_precondition"
    assert "no compiled doc" in res.message.lower()


async def test_pool_spawn_worker_allows_resolved_specialist_with_doc(env):
    # spec_id stamped AND a compiled doc exists → Guard B does not block it.
    pid = await _plan(env)
    sid = _ok(await env.call("create_specialization", name="Spring",
                             subject="spring", description="spring"))["spec_id"]
    _ok(await env.call("write_specialist_doc", spec_id=sid,
                       content="# Spring\n## House style\n- ...\n"))
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="Implement POST /login",
                       specialization="Java Spring Boot REST API"))
    _stamp_spec_id(env, pid, "a1", sid)
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    msg = res.message if isinstance(res, ToolError) else ""
    assert "no compiled doc" not in msg.lower() and "no spec_id" not in msg


async def test_pool_spawn_worker_allows_generic_action(env):
    # an action with NO specialization is not blocked by Guard B.
    pid = await _plan(env)
    _ok(await env.call(
        "add_action", plan_id=pid, action_id="a1",
        description="Back up the data directory"))
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    msg = res.message if isinstance(res, ToolError) else ""
    assert "spec_id" not in msg
