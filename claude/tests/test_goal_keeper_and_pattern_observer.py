"""Team-architecture Phase 6 (2026-05-21) — /goal-keeper +
/pattern-observer externality shells.

Both follow the same consult-spawn-reply pattern as /critic from
Phase 5. These tests pin the substrate (consult message lands BEFORE
spawn; spawn role is correct; unique inbox per call) and the brief
discipline (each shell does observation/reporting, not deciding).
"""

from pathlib import Path

from edp_contracts import ToolError, ToolOk

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"


def _body(name: str) -> str:
    return (_CMD / f"{name}.md").read_text(encoding="utf-8").lower()


async def test_consult_goal_keeper_round_trip(env):
    res = await env.call(
        "consult_goal_keeper", recipe_id="recipe-x",
        query="check drift on the dispatch step")
    assert isinstance(res, ToolOk)
    gk_id = res.data["gk_id"]
    assert gk_id.startswith("recipe-x-goalkeeper-")

    spawns = [s for s in env.ctx.pool.spawns
              if s["role"] == "goal_keeper"]
    assert len(spawns) == 1
    assert spawns[0]["handle"] == gk_id

    # Consult message in goal-keeper's inbox, ready for Step 0:
    msgs = await env.ctx.broker.poll(gk_id)
    assert len(msgs) == 1
    consult = msgs[0]
    assert consult.kind == "consult"
    assert consult.body["scope"] == "recipe"
    assert consult.body["handle"] == "recipe-x"


async def test_consult_pattern_observer_round_trip(env):
    res = await env.call(
        "consult_pattern_observer",
        query="any recurring failures?",
        scope_handle="recipe-x")
    assert isinstance(res, ToolOk)
    po_id = res.data["po_id"]
    assert po_id.startswith("patterns-observer-")

    spawns = [s for s in env.ctx.pool.spawns
              if s["role"] == "pattern_observer"]
    assert len(spawns) == 1

    msgs = await env.ctx.broker.poll(po_id)
    assert len(msgs) == 1
    assert msgs[0].body["scope"] == "cross-plan"
    assert msgs[0].body["handle"] == "recipe-x"


async def test_pattern_observer_scan_all_from_spawned_caller(env, monkeypatch):
    # scope_handle empty = scan ALL worklogs. The reply still needs a
    # route: a spawned caller has its own handle (me), so no scope_handle
    # is needed for routing. (The neuron's main shell instead passes
    # scope_handle=recipe_id — see test_consult_pattern_observer_round_trip.)
    monkeypatch.setenv("EDP_HANDLE", "plan-x:a1")
    monkeypatch.setenv("EDP_ROLE", "planner")
    res = await env.call("consult_pattern_observer", query="cross-plan scan")
    assert isinstance(res, ToolOk)
    msgs = await env.ctx.broker.poll(res.data["po_id"])
    assert msgs[0].body["handle"] == ""        # empty scope = scan all
    # reply routes to the caller's own poll-handle (planner = plan_id)
    assert msgs[0].body["caller"] == "plan-x-a1"


async def test_pattern_observer_requires_route_from_main_shell(env):
    # no me, no scope_handle → can't route the report → precondition.
    res = await env.call("consult_pattern_observer", query="scan")
    assert isinstance(res, ToolError)
    assert "scope_handle" in res.message.lower()


def test_goal_keeper_brief_carries_externality_discipline():
    b = _body("goal-keeper")
    # The right framing:
    assert "drift" in b
    assert "strategic" in b and "tactical" in b
    assert "user_goal_verbatim" in b  # strategic source of truth
    assert "do not decide" in b or "you do not decide" in b
    # Step 0 = check_inbox:
    assert "check_inbox" in b
    # Reply via the substrate (not addressing):
    assert "reply" in b
    # Anti-patterns enforced:
    assert "deciding what to do" in b or "you don't pivot" in b


def test_pattern_observer_brief_carries_externality_discipline():
    b = _body("pattern-observer")
    # The right framing:
    assert "pattern" in b
    assert "memory across runs" in b or "across runs" in b
    assert "you do not fix" in b
    # Step 0 = check_inbox:
    assert "check_inbox" in b
    # Reply via the substrate:
    assert "reply" in b
    # Anti-patterns enforced:
    assert "≥2 instances" in b or "≥ 2 instances" in b or "2 instances" in b
    assert "vague" in b
