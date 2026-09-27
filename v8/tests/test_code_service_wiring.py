"""S21 (s-0cfebd3862): every channel reaches the one code service (edp8.code_service).

`heronry start|stop|restart code` and its opt-in place in `all`, the supervisor's control route (the Admin console
and the Code tab's Start go through it), the Admin → Services row, and the desktop tray. The service itself is
faked here; tests/test_code_service_py.py runs it for real with a stub code-server.
"""

from __future__ import annotations

import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edp8 import cli, code_service, desktop, launcher, supervisor
from edp8.admin import services as admin_services
from edp8.schemas import Participant


@pytest.fixture
def fake_code(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(code_service, "start", lambda **k: calls.append("start") or
                        {"service": "code", "state": "started", "pid": 11, "url": "http://127.0.0.1:1/"})
    monkeypatch.setattr(code_service, "stop", lambda **k: calls.append("stop") or
                        {"service": "code", "state": "stopped", "killed": 3, "survivors": []})
    monkeypatch.setattr(code_service, "restart", lambda **k: calls.append("restart") or
                        {"service": "code", "state": "restarted", "pid": 12, "url": "http://127.0.0.1:1/"})
    return calls


# ------------------------------------------------------------------------------------------ CLI

def test_all_leaves_code_out_unless_autostart(monkeypatch):
    monkeypatch.delenv("EDP_CODE_AUTOSTART", raising=False)
    monkeypatch.setattr(code_service, "autostart", lambda: False)
    assert cli._targets([]) == list(launcher.ORDER)
    assert cli._targets(["code"]) == ["code"]
    monkeypatch.setattr(code_service, "autostart", lambda: True)
    assert cli._targets(["all"]) == [*launcher.ORDER, "code"]


def test_start_stop_restart_code_by_name_touch_only_the_code_service(monkeypatch, fake_code, capsys):
    monkeypatch.setattr(launcher, "start", lambda svc, **k: pytest.fail(f"launcher.start({svc})"))
    monkeypatch.setattr(launcher, "stop", lambda svc, **k: pytest.fail(f"launcher.stop({svc})"))
    monkeypatch.setattr(launcher, "ensure_supervisor", lambda **k: pytest.fail("supervisor started"))
    monkeypatch.setattr(launcher, "stop_supervisor", lambda: pytest.fail("supervisor stopped"))
    assert cli.start(["code"]) == 0
    assert cli.stop(["code"]) == 0
    assert cli.restart(["code"]) == 0
    assert fake_code == ["start", "stop", "restart"]
    out = capsys.readouterr().out
    assert "code       started" in out and "code       stopped" in out and "code       restarted" in out


def test_start_code_without_code_server_fails_with_the_install_hint(monkeypatch, capsys):
    monkeypatch.setattr(code_service, "start", lambda **k: {"service": "code", "state": "not_installed",
                                                            "install_hint": "brew install code-server"})
    assert cli.start(["code"]) == 1
    assert "not installed  brew install code-server" in capsys.readouterr().err


def test_a_refusal_is_one_plain_line(monkeypatch, capsys):
    def refuse(**k):
        raise code_service.CodeError("port 9410 is held by pid 7, not this Heronry's code server; leaving it alone")
    monkeypatch.setattr(code_service, "start", refuse)
    assert cli.start(["code"]) == 1
    assert "code       FAILED  port 9410 is held by pid 7" in capsys.readouterr().err


def test_status_lists_code_but_does_not_nag_about_it_while_opt_in(monkeypatch, capsys):
    rows = [{"service": "board", "state": "up"},
            {"service": "code", "state": "down", "autostart": False, "reason": "not running"}]
    monkeypatch.setattr(launcher, "status_rows", lambda: rows)
    assert cli.status([]) == 0
    got = capsys.readouterr()
    assert "code" in got.out and "down:" not in got.err
    rows[1]["autostart"] = True
    cli.status([])
    assert "down: code" in capsys.readouterr().err


def test_launcher_status_rows_end_with_the_code_row(monkeypatch):
    monkeypatch.setattr(launcher.run_state, "snapshot", lambda: [])
    monkeypatch.setattr(launcher, "supervisor_running", lambda: False)
    monkeypatch.setattr(code_service, "status", lambda: {
        "service": "code", "state": "not_installed", "pid": None, "port": 9410, "url": "http://127.0.0.1:9410/",
        "installed": False, "install_hint": "npm install -g code-server", "autostart": False,
        "reason": "code-server is not installed", "version": None})
    row = launcher.status_rows()[-1]
    assert row["service"] == "code" and row["state"] == "not_installed"
    assert row["install_hint"] == "npm install -g code-server" and row["reason"] == "code-server is not installed"


# ------------------------------------------------------------------------------------------ supervisor

def test_the_control_route_runs_the_code_service_and_records_it(fake_code):
    emitted = []
    sup = types.SimpleNamespace(paused=set(), failed=set(), lock=None, stop_event=None, resume=lambda s: None)
    dispatch = supervisor.make_dispatch(sup, lambda svc, reason, who=None: emitted.append((svc, reason, who)))
    for verb in ("start", "stop", "restart"):
        code, out = dispatch(f"/services/code/{verb}", {"by": "alice"})
        assert code == 200 and out["ok"] is True
    assert fake_code == ["start", "stop", "restart"]
    assert emitted == [("code", f"{v} via the control port by alice", "alice") for v in ("start", "stop", "restart")]


def test_the_control_route_answers_not_installed_and_refusals_with_409(monkeypatch):
    sup = types.SimpleNamespace(paused=set(), failed=set(), lock=None, stop_event=None, resume=lambda s: None)
    dispatch = supervisor.make_dispatch(sup, lambda *a, **k: None)
    monkeypatch.setattr(code_service, "start", lambda **k: {"service": "code", "state": "not_installed",
                                                            "reason": "code-server is not installed: x",
                                                            "install_hint": "x"})
    code, out = dispatch("/services/code/start", {})
    assert code == 409 and out["state"] == "not_installed" and out["install_hint"] == "x"

    def refuse(**k):
        raise code_service.CodeError("leaving it alone")
    monkeypatch.setattr(code_service, "start", refuse)
    assert dispatch("/services/code/start", {}) == (409, {"ok": False, "error": "leaving it alone"})


# ------------------------------------------------------------------------------------------ Admin → Services

def _admin_app(monkeypatch, seen: list):
    monkeypatch.setattr(admin_services.control, "endpoint", lambda: ("127.0.0.1", 1, "s"))
    monkeypatch.setattr(admin_services.control, "request",
                        lambda path, body=None, **k: seen.append((path, body)) or (200, {"ok": True, "state": "started"}))
    admin = Participant(id="alice", created_by="t", type="human", role="owner", handle="alice", admin=True)
    app = FastAPI()
    app.include_router(admin_services.router(None, lambda: admin))
    return TestClient(app)


def test_admin_code_server_row_has_controls_through_the_supervisor(monkeypatch):
    seen: list = []
    client = _admin_app(monkeypatch, seen)
    for verb in ("start", "stop", "restart"):
        r = client.post(f"/v1/admin/services/code-server/{verb}", json={})
        assert r.status_code == 200, r.text
    assert [p for p, _ in seen] == ["/services/code/start", "/services/code/stop", "/services/code/restart"]
    assert seen[0][1]["by"] == "alice"


def test_admin_row_says_how_to_install_when_code_server_is_missing():
    row = admin_services._code_server_row({"service": "code", "state": "not_installed", "pid": None, "port": 9410,
                                           "install_hint": "brew install code-server", "autostart": False})
    assert row["service"] == "code-server" and row["managed"] is True and row["health"] == "not installed"
    assert "brew install code-server" in row["note"]
    up = admin_services._code_server_row({"service": "code", "state": "up", "pid": 5, "port": 9410, "autostart": True})
    assert up["health"] == "up" and not up.get("note")


# ------------------------------------------------------------------------------------------ tray

def test_tray_offers_start_stop_code_by_state_and_opens_the_code_tab(monkeypatch):
    calls = []
    monkeypatch.setattr(desktop, "run_cli", lambda verb, *a: calls.append((verb, *a)) or (0, "ok"))
    monkeypatch.setattr(desktop, "board_url", lambda: "http://127.0.0.1:19400")
    state = {"s": "down"}
    monkeypatch.setattr(code_service, "status", lambda: {"state": state["s"]})
    app = desktop.Desktop("Heronry Desktop")
    app.window = types.SimpleNamespace(calls=[], create_confirmation_dialog=lambda *a: True,
                                       load_url=lambda u: app.window.calls.append(("load_url", u)),
                                       show=lambda: None, restore=lambda: None)
    assert app.enabled("Start code server") and not app.enabled("Stop code server")
    dict(app.actions())["Start code server"]()
    state["s"] = "up"
    assert app.enabled("Stop code server") and not app.enabled("Start code server")
    dict(app.actions())["Stop code server"]()
    dict(app.actions())["Open Code tab"]()
    assert calls == [("start", "code"), ("stop", "code")]
    assert app.window.calls == [("load_url", "http://127.0.0.1:19400/ui/code")]


def test_tray_menu_items_carry_the_enabled_state(monkeypatch):
    made = {}

    class MenuItem:
        def __init__(self, text, action, **kw):
            self.text, self.action, self.kw = text, action, kw

    class Menu:
        SEPARATOR = MenuItem("-", None)

        def __init__(self, *items):
            self.items = items

    class Icon:
        def __init__(self, name, image, title, menu):
            made.update(menu=menu)

    monkeypatch.setitem(sys.modules, "pystray", types.SimpleNamespace(MenuItem=MenuItem, Menu=Menu, Icon=Icon))
    monkeypatch.setattr(code_service, "status", lambda: {"state": "up"})
    desktop.Desktop("H").make_tray()
    items = {i.text: i for i in made["menu"].items}
    for want in ("Start code server", "Stop code server", "Open Code tab"):
        assert want in items
    assert items["Stop code server"].kw["enabled"](None) is True
    assert items["Start code server"].kw["enabled"](None) is False
    assert items["Open Code tab"].kw["enabled"](None) is True
