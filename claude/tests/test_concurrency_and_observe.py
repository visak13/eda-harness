"""2026-05-25 — concurrency + external observation + vector consult.

Covers: consult_specialist resolves by VECTOR similarity over the neuron
DB (works for trained specialists, no guide file needed); pool_reap as
the deliberate stuck-worker escape; inspect_worker / read_worklog let
the neuron judge slow-vs-hung from outside.
"""

from edp_contracts import ToolError, ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


# ── consult_specialist via vector similarity ──────────────────────────────
async def test_consult_specialist_resolves_trained_by_vector(env):
    # a trained domain specialist (no guide file) — consult by QUERY must
    # find it via vector search and return its RECIPE.
    c = _ok(await env.call("create_specialization", name="Java Expert",
                           subject="Java Spring Boot REST",
                           description="java spring boot rest api services"))
    nid = c["neuron_id"]
    _ok(await env.call("add_spec_entry", spec_id=c["spec_id"], kind="step",
                       text="model the aggregate first"))
    out = _ok(await env.call(
        "consult_specialist",
        query="how to build a spring boot rest api in java"))
    assert out["specialist_id"] == nid          # found by similarity
    assert out["source"] == "recipe"            # trained → recipe, no guide
    assert out["mode"] in ("vector", "text-fallback")
    assert "aggregate" in out["knowledge"]      # the recipe content


async def test_consult_specialist_empty_registry_is_precondition(env):
    res = await env.call("consult_specialist", query="anything")
    assert isinstance(res, ToolError)


# ── pool_reap (deliberate escape) ─────────────────────────────────────────
async def test_pool_reap_releases_a_stuck_worker(env):
    # spawn a worker (holds the lock), then reap it by handle
    _ok(await env.call("pool_spawn_worker", plan_id="p1", action_id="a1"))
    # W7: liveness returns {state, last_output_ts}; assert on state.
    assert (await env.ctx.pool.liveness("p1:a1"))["state"] == "alive"
    _ok(await env.call("pool_reap", handle="p1:a1"))
    # after reap the worker is gone (lock freed for re-dispatch)
    assert (await env.ctx.pool.liveness("p1:a1"))["state"] in ("dead", "unknown")


# ── inspect_worker / read_worklog (external observation) ──────────────────
async def test_inspect_worker_reports_liveness_and_activity(env):
    from edp_claude.schemas import Plan
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id="p2", recipe_id="r", recipe_step_id="s1", domain="x",
        shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "d",
                  "status": "in_progress", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "manual_review"}}],
    )))
    env.ctx.plans.append_worklog("p2", {"kind": "progress",
                                        "detail": "scaffolding"})
    _ok(await env.call("pool_spawn_worker", plan_id="p2", action_id="a1"))
    out = _ok(await env.call("inspect_worker", plan_id="p2", action_id="a1"))
    assert out["handle"] == "p2:a1"
    assert out["liveness"] == "alive"
    assert out["action_status"] == "in_progress"
    assert out["last_activity"]                       # has a timestamp
    assert any(e.get("kind") == "progress" for e in out["recent"])
    # alive → the note must say DON'T force-fail
    assert "do not force-fail" in out["note"].lower() \
        or "wait" in out["note"].lower()


async def test_read_worklog_tail(env):
    for i in range(5):
        env.ctx.plans.append_worklog("p3", {"kind": "progress", "i": i})
    out = _ok(await env.call("read_worklog", plan_id="p3", tail=3))
    assert len(out["entries"]) == 3
    assert out["entries"][-1]["i"] == 4
