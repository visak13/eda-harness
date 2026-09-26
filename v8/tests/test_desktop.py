"""S8 (s-6dcf78f803): Heronry Desktop (edp8.desktop) without a real window.

pywebview/pystray are faked: what is pinned here is the behaviour the design fixes (§4.9, strategyhl-5af811e7bd §4):
every window/tray action is the CLI's own command (one code path), closing hides, Quit leaves the services unless
"Stop services on quit" is set, the first run inits and lands on /ui/setup, the splash shows while services come up.
The hands-on look (real WebView2 window, real tray) is the MSI walkthrough on this host."""

from __future__ import annotations

import sys
import types

import pytest

from edp8 import desktop


class FakeWindow:
    def __init__(self):
        self.calls: list[tuple] = []
        self.answer = True

    def __getattr__(self, name):
        def rec(*a):
            self.calls.append((name, *a))
            return self.answer if name == "create_confirmation_dialog" else None
        return rec


@pytest.fixture
def cli_calls(monkeypatch):
    calls: list[tuple] = []

    def fake(verb, *args):
        calls.append((verb, *args))
        return 0, f"{verb} ok"
    monkeypatch.setattr(desktop, "run_cli", fake)
    return calls


def test_run_cli_runs_the_terminal_command_in_process_and_captures_it(monkeypatch):
    from edp8 import cli
    monkeypatch.setitem(cli._COMMANDS, "status", lambda argv: print("rows", argv) or 0)
    assert desktop.run_cli("status", "--json") == (0, "rows ['--json']")


def test_run_cli_turns_exits_and_errors_into_a_message(monkeypatch):
    from edp8 import cli

    def boom(argv):
        raise RuntimeError("port taken")
    monkeypatch.setitem(cli._COMMANDS, "start", boom)
    monkeypatch.setitem(cli._COMMANDS, "stop", lambda argv: (_ for _ in ()).throw(SystemExit("unknown service 'x'")))
    assert desktop.run_cli("start") == (1, "start failed: port taken")
    assert desktop.run_cli("stop", "x") == (1, "unknown service 'x'")


@pytest.mark.parametrize("label,verb", [("Start services", ("start", "--no-browser")), ("Stop services", ("stop",)),
                                        ("Restart services", ("restart",))])
def test_tray_and_menu_actions_are_the_cli_commands(cli_calls, label, verb):
    app = desktop.Desktop("Heronry Desktop")
    app.window = FakeWindow()
    dict(app.actions())[label]()
    assert cli_calls == [verb]
    assert app.window.calls[-1][0] == "create_confirmation_dialog"  # the command's output is shown


def test_every_required_action_is_offered():
    labels = [label for label, _ in desktop.Desktop("H").actions()]
    for want in ("Open board", "Status", "Start services", "Stop services", "Restart services", "Check for update"):
        assert want in labels


def test_closing_the_window_hides_it_while_the_tray_lives():
    app = desktop.Desktop("H")
    app.window, app.tray = FakeWindow(), object()
    assert app.on_closing() is False
    assert ("hide",) in app.window.calls
    app.quitting = True
    assert app.on_closing() is True


def test_quit_leaves_services_running_by_default(cli_calls):
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    app.quit()
    assert cli_calls == []
    assert ("destroy",) in app.window.calls


def test_quit_stops_services_when_the_option_is_set_and_it_persists(cli_calls):
    app = desktop.Desktop("H")
    app.toggle_stop_on_quit()
    assert desktop.load_prefs() == {"stop_services_on_quit": True}
    again = desktop.Desktop("H")  # a new launch reads the saved choice
    again.window = FakeWindow()
    assert again.stop_on_quit
    again.quit()
    assert cli_calls == [("stop",)]


def test_first_run_inits_with_the_detected_harnesses(monkeypatch, cli_calls):
    import edp8.setup as setup_mod
    monkeypatch.setattr(setup_mod, "detect_harnesses", lambda: {"claude": None, "codex": "/bin/codex", "pi": None})
    desktop.first_run_init()
    assert cli_calls == [("init", "--harness", "codex", "--yes")]
    cli_calls.clear()
    monkeypatch.setattr(setup_mod, "detect_harnesses", lambda: {"claude": None, "codex": None, "pi": None})
    desktop.first_run_init()
    assert cli_calls == [("init", "--harness", "claude", "--yes")]


def test_entry_url_is_the_setup_wizard_until_it_is_done(monkeypatch):
    from edp8.admin import setup_api
    monkeypatch.setattr(desktop, "board_url", lambda: "http://127.0.0.1:5555")
    monkeypatch.setattr(setup_api, "issue_setup_code", lambda: "C0DE")
    monkeypatch.setattr(setup_api, "state", lambda: {"done": False})
    assert desktop.entry_url() == "http://127.0.0.1:5555/ui/setup?code=C0DE"
    monkeypatch.setattr(setup_api, "state", lambda: {"done": True})
    assert desktop.entry_url() == "http://127.0.0.1:5555/ui/join?code=C0DE"


def test_boot_inits_starts_then_opens_the_board_with_splash_status(monkeypatch, cli_calls):
    state = {"init": False, "up": False}
    monkeypatch.setattr(desktop, "initialized", lambda: state["init"])
    monkeypatch.setattr(desktop, "first_run_init", lambda: (cli_calls.append(("init",)), state.update(init=True), (0, ""))[-1])
    monkeypatch.setattr(desktop, "services_up", lambda: state["up"])
    monkeypatch.setattr(desktop, "entry_url", lambda: "http://127.0.0.1:5555/ui/setup?code=X")
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    app.boot()
    assert cli_calls == [("init",), ("start", "--no-browser")]
    js = [c[1] for c in app.window.calls if c[0] == "evaluate_js"]
    assert any("First run" in j for j in js) and any("Starting" in j for j in js)
    assert app.window.calls[-1] == ("load_url", "http://127.0.0.1:5555/ui/setup?code=X")


def test_boot_does_not_start_services_that_are_already_up(monkeypatch, cli_calls):
    monkeypatch.setattr(desktop, "initialized", lambda: True)
    monkeypatch.setattr(desktop, "services_up", lambda: True)
    monkeypatch.setattr(desktop, "entry_url", lambda: "u")
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    app.boot()
    assert cli_calls == []
    assert app.window.calls[-1] == ("load_url", "u")


def test_splash_is_the_s7_art_inline():
    html = desktop.splash_html("Heronry Desktop")
    assert "data:image/png;base64,iVBOR" in html and "setStatus" in html


def test_update_asks_before_applying(monkeypatch, cli_calls):
    from edp8 import updater
    monkeypatch.setattr(updater, "check", lambda **kw: {"current": "0.9.0", "latest": "0.9.1", "newer": True, "url": "u"})
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    app.window.answer = False
    app.update()
    assert cli_calls == []
    app.window.answer = True
    app.update()
    assert cli_calls == [("update",)]


def test_update_says_up_to_date(monkeypatch, cli_calls):
    from edp8 import updater
    monkeypatch.setattr(updater, "check", lambda **kw: {"current": "0.9.1", "latest": "0.9.1", "newer": False, "url": "u"})
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    app.update()
    assert cli_calls == []
    assert "up to date" in app.window.calls[-1][2]


def test_tray_menu_has_every_action_plus_the_quit_option(monkeypatch):
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
            made.update(name=name, title=title, menu=menu, image=image)

    monkeypatch.setitem(sys.modules, "pystray", types.SimpleNamespace(MenuItem=MenuItem, Menu=Menu, Icon=Icon))
    app = desktop.Desktop("Heronry Desktop")
    app.make_tray()
    texts = [i.text for i in made["menu"].items]
    for want in ("Open board", "Status", "Start services", "Stop services", "Restart services", "Check for update",
                 "Stop services on quit", "Quit"):
        assert want in texts
    assert made["title"] == "Heronry Desktop" and made["image"].size == (64, 64)
    assert [i for i in made["menu"].items if i.text == "Open board"][0].kw.get("default") is True


def test_no_webview2_check_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert desktop.webview2_version() is None
    assert desktop.ensure_webview2("H") is True
