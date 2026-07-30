"""2026-05-25 — MCP-tool logging + planner pacing + close-checks.

Every claude MCP tool call logs tool_start (with input) → tool_done to
disk, so a HANG shows as a start with no done. Plus the brief changes:
planner paces + self-restores its heartbeat; planner/worker do a final
check before pool_close_self.
"""

from pathlib import Path

from edp_contracts import ToolOk

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"


class _FakeLog:
    def __init__(self):
        self.calls = []

    def info(self, kind, detail, **f):
        self.calls.append(("info", kind, f))

    def warning(self, kind, detail, **f):
        self.calls.append(("warning", kind, f))

    def error(self, kind, detail, **f):
        self.calls.append(("error", kind, f))

    def debug(self, *a, **k):
        pass


async def test_every_tool_call_logs_start_and_done(env, monkeypatch):
    import edp_claude.tools.base as base
    fake = _FakeLog()
    monkeypatch.setattr(base, "_log", fake)
    # a successful tool call
    res = await env.call("resolve_recipe", goal="build a thing")
    assert isinstance(res, ToolOk)
    kinds = [(k, f.get("tool")) for _, k, f in fake.calls]
    assert ("tool_start", "resolve_recipe") in kinds
    assert ("tool_done", "resolve_recipe") in kinds
    # the input is captured in tool_start (so a hang shows what stalled)
    start = next(f for lvl, k, f in fake.calls if k == "tool_start")
    assert "build a thing" in start["args"]
    done = next(f for lvl, k, f in fake.calls if k == "tool_done")
    assert "dur_ms" in done


async def test_failing_tool_still_logs_done_with_outcome(env, monkeypatch):
    import edp_claude.tools.base as base
    fake = _FakeLog()
    monkeypatch.setattr(base, "_log", fake)
    # precondition error (no recipe) → still a tool_done with ok=False
    await env.call("next_action", handle="nope", handle_type="recipe")
    done = [f for lvl, k, f in fake.calls if k == "tool_done"
            and f.get("tool") == "next_action"]
    assert done and done[-1]["ok"] is False


def test_planner_brief_paces_and_self_restores_heartbeat():
    # 2026-05-31 planner phasing: the wait/heartbeat protocol lives in the
    # drive phase guide (loaded once the plan exists), not the brief.
    b = (Path(__file__).resolve().parents[1] / "docs" / "guides"
         / "planner-phase-drive.md").read_text(encoding="utf-8").lower()
    # self-restoring: verify/re-arm every wait, not once
    assert "cronlist" in b
    assert "every wait" in b and "never assume it survived" in b
    # adaptive cadence (pace like the neuron, not every minute)
    assert "pace the cadence" in b or "don't blindly fire every minute" in b
    # judge slow-vs-hung via inspect_worker, never force-fail alive
    assert "inspect_worker" in b and "never force-fail" in b


def test_planner_and_worker_final_check_before_close():
    # 2026-05-31 planner phasing: the close/finalize discipline lives in
    # the drive phase guide (the `done` branch), not the dispatcher brief.
    planner = (Path(__file__).resolve().parents[1] / "docs" / "guides"
               / "planner-phase-drive.md").read_text(encoding="utf-8").lower()
    assert "final check before you close" in planner
    assert "do not close" in planner
    worker = (_CMD / "worker.md").read_text(encoding="utf-8").lower()
    assert "final check before you close" in worker
    assert "check_inbox" in worker and "do not close" in worker
