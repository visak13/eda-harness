"""t-86f4ae3569: `heronry status` names why every service that is not up is down."""

from __future__ import annotations

import subprocess
import sys

from edp8 import launcher, run_state, settings


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_every_down_row_has_a_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path / "run"))
    for var, name in (("EDP8_PORT", "board"), ("EDP_BROKER_PORT", "broker"), ("EDP_POOL_PORT", "pool"),
                      ("EDP8_MCP_PORT", "mcp")):
        monkeypatch.setenv(var, "1")  # nothing listens on port 1
    rows = launcher.status_rows()
    down = [r for r in rows if r["state"] != "up"]
    assert {r["service"] for r in down} >= {"board", "broker", "pool", "mcp", "supervisor"}
    assert all(r.get("reason") for r in down), down


def test_a_record_whose_pid_is_gone_says_exited_with_the_log(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path / "run"))
    (tmp_path / "run").mkdir()
    pid = _dead_pid()
    run_state.write("broker", pid=pid, port=1, git_rev="t")
    run_state.update("broker", last_restart_reason="listener gone")
    why = launcher.down_reason("broker")
    assert f"recorded pid {pid} is gone" in why and str(settings.logs_dir() / "broker.log") in why, why
    assert "last restart: listener gone" in why, why


def test_no_record_says_not_running(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path / "run"))
    assert launcher.down_reason("pool").startswith("not running: no run record")


def test_a_bridge_without_a_slack_map_says_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("EDP8_SLACK_MAP", str(tmp_path / "no-such-map.json"))
    assert "no Slack map" in launcher.down_reason("bridge")
