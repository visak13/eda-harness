"""RC2 item 6 (t-e338298d88): after `heronry update` or a board restart, the output names the one action an open
Claude Code session may need (/mcp Reconnect for edp8). Measured on Claude Code 2.1.283: the client re-connects by
itself only when the MCP server is back within seconds; an update's stop/install/start outlasts its retries."""
from edp8 import cli, launcher, updater


def test_update_result_names_the_reconnect_action():
    for res in ({"state": "ok", "to": "0.10.0", "resumed": ["s-1"]},
                {"state": "incomplete", "to": "0.10.0", "reason": "1 seat did not resume"}):
        text = updater.result_text(res)
        assert "/mcp" in text and "Reconnect" in text and "edp8" in text


def test_failed_update_does_not_ask_for_a_reconnect():
    assert "/mcp" not in updater.result_text({"state": "failed", "reason": "health check timed out"})


def test_board_restart_prints_the_reconnect_action(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_legacy_supervisor", lambda: False)
    monkeypatch.setattr(cli, "_via_control", lambda path, body: {"service": "board", "state": "restarted"})
    monkeypatch.setattr(launcher, "enabled", lambda svc: True)
    assert cli.restart(["board"]) == 0
    out = capsys.readouterr().out
    assert "/mcp" in out and "Reconnect" in out


def test_pool_restart_alone_does_not(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_legacy_supervisor", lambda: False)
    monkeypatch.setattr(cli, "_pool_guard", lambda verb, force: True)
    monkeypatch.setattr(cli, "_via_control", lambda path, body: {"service": "pool", "state": "restarted"})
    monkeypatch.setattr(launcher, "enabled", lambda svc: True)
    assert cli.restart(["pool"]) == 0
    assert "/mcp" not in capsys.readouterr().out
