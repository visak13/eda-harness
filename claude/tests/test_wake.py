"""wake (cron-heartbeat) — tool + port unit coverage.

WALK-1 already proves WAIT-enrichment end-to-end over the FSM. Here we
pin the close-on-done tool contract and the StubPool.release semantics,
plus the env-driven heartbeat interval (zero LLM discretion).
"""

from edp_contracts import ToolError, ToolOk

from edp_claude.stubs.stub_pool import StubPool
from edp_claude.tools._tools import _heartbeat_secs


async def test_pool_close_self_precondition_when_not_spawned(env, monkeypatch):
    # The neuron / a hand-run shell has no spawn id — closing is a no-op
    # error, never a silent success (it must NOT reap the user's shell).
    monkeypatch.delenv("EDP_SPAWN_SESSION_ID", raising=False)
    res = await env.call("pool_close_self")
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"
    assert "edp_spawn_session_id" in res.message.lower()


async def test_pool_close_self_releases_spawn_session(env, monkeypatch):
    monkeypatch.setenv("EDP_SPAWN_SESSION_ID", "worker:xyz")
    res = await env.call("pool_close_self")
    assert isinstance(res, ToolOk)
    assert res.data["released"] == "worker:xyz"


async def test_stub_pool_release_drops_matching_session():
    p = StubPool()
    p.spawns = [
        {"role": "worker", "handle": "p:a1", "session_id": "worker:keep"},
        {"role": "worker", "handle": "p:a2", "session_id": "worker:drop"},
    ]
    res = await p.release("worker:drop")
    assert isinstance(res, ToolOk)
    assert res.data["released"] == "worker:drop"
    assert [s["session_id"] for s in p.spawns] == ["worker:keep"]


_PLAN = {
    "plan_id": "p-wake", "recipe_id": "r", "recipe_step_id": "s1",
    "domain": "software_engineering", "shape": "modular-build",
    "goal": "g", "state": "drafted",
    "actions": [{"action_id": "a1", "description": "d",
                 "status": "pending", "depends_on": [],
                 "executor_mode": "subagent",
                 "acceptance": {"kind": "tests_pass"}}],
    "context": {}, "version": 1,
    # Skip the plan-level audit gate for this focused wake test.
    "ocak_audit": {"scope": "plan",
                   "findings": {"O": "n/a", "C": "ok",
                                "A": "ok", "K": "low"},
                   "verdict": "overridden_by_user",
                   "gaps": [], "notes": "wake test",
                   "at": "2026-05-20T00:00:00+00:00"},
}


async def test_dispatch_persists_in_progress_then_tool_forces_wait(env):
    # Post-HITL sweep A end-to-end through the TOOL: dispatch must
    # persist in_progress (widened save-guard) so the NEXT next_action
    # returns a tool-FORCED wait carrying the heartbeat — not a
    # re-dispatch the planner has to override by inference.
    assert isinstance(await env.call("record_plan", plan=_PLAN), ToolOk)

    d1 = (await env.call("next_action", handle="p-wake",
                         handle_type="plan")).data
    assert d1["kind"] == "dispatch_action"
    # persisted, not just mutated in memory:
    assert env.ctx.plans.load("p-wake").actions[0].status == "in_progress"

    d2 = (await env.call("next_action", handle="p-wake",
                         handle_type="plan")).data
    assert d2["kind"] == "wait"
    assert d2["args"]["handle"] == "p-wake"
    assert d2["args"]["handle_type"] == "plan"
    # 1800 = the 30-min backstop default (raised from 60s 2026-07-25): the
    # cron is a lost-push backstop, not the stall detector.
    assert d2["args"]["heartbeat_secs"] == 1800  # enrichment now reachable


def test_heartbeat_secs_env_override(monkeypatch):
    monkeypatch.delenv("EDP_HEARTBEAT_SECS", raising=False)
    assert _heartbeat_secs() == 1800
    monkeypatch.setenv("EDP_HEARTBEAT_SECS", "45")
    assert _heartbeat_secs() == 45
    monkeypatch.setenv("EDP_HEARTBEAT_SECS", "not-an-int")
    assert _heartbeat_secs() == 1800  # malformed → safe default
