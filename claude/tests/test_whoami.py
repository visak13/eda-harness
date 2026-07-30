"""whoami() — the canonical broker inbox address (2026-06-01).

The bug: a PLANNER's inbox is its plan_id (`<recipe_id>-<step_id>`, dash)
but its EDP_HANDLE is `<recipe_id>:<step_id>` (colon). The dash form was
computed only inside the broker tools (_self_and_parent_addresses), never
handed to the agent — so a hand-built `rx.broker(me)` bound to EDP_HANDLE
listened on a DEAD inbox and emitted nothing. whoami() exposes the same
canonical address the tools use, so the agent never string-munges.
"""

from pathlib import Path

from edp_contracts import ToolOk

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def test_whoami_planner_inbox_is_dash_plan_id(env, monkeypatch):
    # planner EDP_HANDLE is the COLON form; its inbox is the DASH plan_id.
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "recipe-abc-97ea19:s2")
    out = _ok(await env.call("whoami"))
    assert out["role"] == "planner"
    assert out["self_address"] == "recipe-abc-97ea19-s2"   # DASH, not colon
    assert out["self_address"] != "recipe-abc-97ea19:s2"   # NOT the handle
    assert out["parent_address"] == "recipe-abc-97ea19"    # the recipe


async def test_whoami_worker_inbox_equals_its_handle(env, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "recipe-abc-97ea19-s2:a1")
    out = _ok(await env.call("whoami"))
    assert out["role"] == "worker"
    # a worker's inbox IS its handle (the remap only affects planners)
    assert out["self_address"] == "recipe-abc-97ea19-s2:a1"
    assert out["parent_address"] == "recipe-abc-97ea19-s2"  # its plan


async def test_whoami_no_handle_is_null(env, monkeypatch):
    # the neuron has no EDP_HANDLE — its inbox is its recipe_id, not whoami.
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.setenv("EDP_ROLE", "neuron")
    out = _ok(await env.call("whoami"))
    assert out["self_address"] is None


def test_briefs_bind_inbox_via_whoami_not_raw_handle():
    # the planner brief must NOT tell the agent to subscribe on its colon
    # EDP_HANDLE; it must route `me` through whoami().self_address.
    planner = (_CMD / "agentic-plan.md").read_text(encoding="utf-8").lower()
    assert "whoami" in planner and "self_address" in planner
    assert "dead inbox" in planner            # the trap is named
    # the buggy instruction (subscribe on your colon handle) is gone
    assert "rx.broker(me)` on your handle" not in planner
    worker = (_CMD / "worker.md").read_text(encoding="utf-8").lower()
    assert "whoami" in worker
