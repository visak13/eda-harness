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


@pytest.fixture(autouse=True)
def no_guard_wait(monkeypatch):
    monkeypatch.setattr(desktop.Desktop, "guard_wait_s", 0.0, raising=False)


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
    for want in ("Open board", "Status", "Start services", "Stop services", "Restart services", "Install update"):
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


def test_a_join_landing_goes_on_to_the_board_once_signed_in(monkeypatch, cli_calls):
    monkeypatch.setattr(desktop, "initialized", lambda: True)
    monkeypatch.setattr(desktop, "services_up", lambda: True)
    monkeypatch.setattr(desktop, "board_url", lambda: "http://127.0.0.1:5555")
    monkeypatch.setattr(desktop, "entry_url", lambda: "http://127.0.0.1:5555/ui/join?code=X")
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    answers = iter([0, 0, 1])
    app.window.evaluate_js = lambda js: next(answers) if "sessionStorage" in js else None
    monkeypatch.setattr("time.sleep", lambda s: None)
    app.boot()
    loads = [c[1] for c in app.window.calls if c[0] == "load_url"]
    assert loads == ["http://127.0.0.1:5555/ui/join?code=X", "http://127.0.0.1:5555/ui/"]


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
    monkeypatch.setattr(updater, "update_staged", lambda: False)
    applied = []
    monkeypatch.setattr(updater, "apply", lambda opts: applied.append(opts) or 0)
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    app.window.answer = False
    app.update()
    assert applied == []
    app.window.answer = True
    app.update()
    assert applied == [{"relaunch-app": True}] and cli_calls == []  # the same entry `heronry update` calls, in-process


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
    for want in ("Open board", "Status", "Start services", "Stop services", "Restart services", "Install update",
                 "Stop services on quit", "Quit"):
        assert want in texts
    assert made["title"] == "Heronry Desktop" and made["image"].size == (64, 64)
    assert [i for i in made["menu"].items if i.text == "Open board"][0].kw.get("default") is True


def test_no_window_menu_on_windows_because_the_tray_carries_every_item(monkeypatch):
    """Owner look, S8 step 6: the WinForms menu strip read as a duplicate title bar."""
    monkeypatch.setattr(sys, "platform", "win32")
    assert desktop.Desktop("Heronry Desktop").menu() == []


def test_no_webview2_check_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert desktop.webview2_version() is None
    assert desktop.ensure_webview2("H") is True


def test_bundle_install_update_applies_then_closes_for_the_runner(monkeypatch, cli_calls):
    from edp8 import launcher, updater
    monkeypatch.setattr(updater, "check", lambda **kw: {"current": "0.9.0", "latest": "0.9.1", "newer": True, "url": "u"})
    staged = {"v": False}
    monkeypatch.setattr(updater, "update_staged", lambda: staged["v"])
    monkeypatch.setattr(updater, "apply", lambda opts: staged.update(v=True) or 0)
    monkeypatch.setattr(launcher, "bundled", lambda: True)
    exits = []
    monkeypatch.setattr(desktop.threading, "Timer", lambda t, fn, args: types.SimpleNamespace(start=lambda: exits.append(args)))
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    app.tray = types.SimpleNamespace(stop=lambda: app.window.calls.append(("tray.stop",)))
    app.update()
    assert cli_calls == [] and app.quitting and ("destroy",) in app.window.calls and exits == [[0]]
    assert "reopens" in [c for c in app.window.calls if c[0] == "create_confirmation_dialog"][0][2]


def test_a_refused_or_failed_apply_is_shown_and_the_app_stays_open(monkeypatch, cli_calls):
    from edp8 import launcher, updater
    monkeypatch.setattr(updater, "check", lambda **kw: {"current": "0.9.0", "latest": "0.9.1", "newer": True, "url": "u"})
    monkeypatch.setattr(updater, "update_staged", lambda: False)
    monkeypatch.setattr(launcher, "bundled", lambda: True)

    def refuse(opts):
        raise updater.UpdateError("Windows Installer is busy")
    monkeypatch.setattr(updater, "apply", refuse)
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    app.update()
    assert not app.quitting and "Update refused: Windows Installer is busy" in app.window.calls[-1][2]


def test_the_install_update_item_is_off_while_an_update_runs(monkeypatch):
    from edp8 import updater
    app = desktop.Desktop("H")
    monkeypatch.setattr(updater, "update_staged", lambda: False)
    monkeypatch.setattr(updater, "install_scope_busy", lambda: False)
    assert app.enabled("Install update") is True
    monkeypatch.setattr(updater, "update_staged", lambda: True)
    assert app.enabled("Install update") is False
    monkeypatch.setattr(updater, "update_staged", lambda: False)
    monkeypatch.setattr(updater, "install_scope_busy", lambda: True)
    assert app.enabled("Install update") is False


def test_an_unread_update_outcome_is_shown_once_at_start(monkeypatch, tmp_path):
    from edp8 import updater
    shown = []
    res = {"state": "rolled_back", "from": "0.9.0", "reason": "the new version did not answer its health check",
           "finished_at": "t1", "_seen": False}
    marked = []
    monkeypatch.setattr(updater, "last_result", lambda: dict(res))
    monkeypatch.setattr(updater, "mark_result_seen", marked.append)
    app = desktop.Desktop("H")
    app._notify = lambda title, msg: shown.append(msg)
    app.announce_update_result()
    assert shown == ["Rolled back to 0.9.0: the new version did not answer its health check"] and len(marked) == 1
    res["_seen"] = True
    app.announce_update_result()
    assert len(shown) == 1


def test_gui_capture_options_stay_inside_the_apps_own_folders(tmp_path):
    from edp8 import settings
    assert desktop.parse_args([]) == {"capture": None, "settle": 6.0}
    default = desktop.parse_args(["--capture", "--settle", "2"])
    assert default == {"capture": (settings.data_dir() / "captures").resolve(), "settle": 2.0}
    inside = settings.data_dir() / "shots"
    assert desktop.parse_args(["--capture", str(inside)])["capture"] == inside.resolve()
    with pytest.raises(SystemExit, match="outside Heronry's own folders"):
        desktop.parse_args(["--capture", str(tmp_path.parent / "elsewhere")])
    with pytest.raises(SystemExit):
        desktop.parse_args(["--grab"])


def test_capture_run_shoots_its_own_page_then_quits(monkeypatch, tmp_path, cli_calls):
    monkeypatch.setattr(desktop, "initialized", lambda: True)
    monkeypatch.setattr(desktop, "services_up", lambda: True)
    monkeypatch.setattr(desktop, "entry_url", lambda: "http://127.0.0.1:5555/ui/setup?code=X")
    monkeypatch.setattr(desktop, "capture_png", lambda window: b"\x89PNG-fake")
    monkeypatch.setattr("time.sleep", lambda s: None)
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    app.capture_dir, app.settle_s = tmp_path, 0
    app.boot()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["01-splash.png", "02-window.png"]
    assert ("load_url", "http://127.0.0.1:5555/ui/setup?code=X") in app.window.calls
    assert app.quitting and ("destroy",) in app.window.calls
    assert cli_calls == []  # Quit leaves the services running (the option is off)


def test_capture_run_writes_messages_instead_of_a_dialog_and_still_quits(monkeypatch, tmp_path, cli_calls):
    monkeypatch.setattr(desktop, "initialized", lambda: True)
    monkeypatch.setattr(desktop, "services_up", lambda: True)
    monkeypatch.setattr(desktop, "entry_url", lambda: "u")

    def boom(window):
        raise RuntimeError("no webview")
    monkeypatch.setattr(desktop, "capture_png", boom)
    monkeypatch.setattr("time.sleep", lambda s: None)
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    app.capture_dir = tmp_path
    app.boot()
    assert "capture failed: no webview" in (tmp_path / "messages.txt").read_text(encoding="utf-8")
    assert not [c for c in app.window.calls if c[0] == "create_confirmation_dialog"]
    assert ("destroy",) in app.window.calls


def tray_menu_dump(monkeypatch, *, bundled: bool = False, stop_on_quit: bool = False) -> list[tuple[str, str]]:
    """S21 c-b73a4537db without a window capture (a capture tripped the antivirus in S8): build the real tray
    menu against a fake pystray, click every item on the calling thread (each from the same fresh prefs), and
    record what each one runs."""
    class MenuItem:
        def __init__(self, text, action, **kw):
            self.text, self.action, self.kw = text, action, kw

    class Menu:
        SEPARATOR = MenuItem("-", None)

        def __init__(self, *items):
            self.items = items

    made = {}
    monkeypatch.setitem(sys.modules, "pystray", types.SimpleNamespace(
        MenuItem=MenuItem, Menu=Menu, Icon=lambda name, image, title, menu: made.update(menu=menu) or types.SimpleNamespace(stop=lambda: None)))
    monkeypatch.setattr(desktop.threading, "Thread", lambda target, daemon: types.SimpleNamespace(start=target))
    calls: list[str] = []
    monkeypatch.setattr(desktop, "run_cli", lambda verb, *a: calls.append("heronry " + " ".join((verb, *a))) or (0, "ok"))
    monkeypatch.setattr(desktop, "status_text", lambda: calls.append("launcher.status_rows() (heronry status's rows)") or "")
    monkeypatch.setattr(desktop, "board_url", lambda: "http://127.0.0.1:9400")
    from edp8 import launcher, updater
    monkeypatch.setattr(updater, "check", lambda **kw: {"newer": True, "latest": "9.9.9", "current": "0.9.0",
                                                         "url": "https://github.com/<repo>/releases/tag/v9.9.9"})
    monkeypatch.setattr(launcher, "bundled", lambda: bundled)
    monkeypatch.setattr(updater, "update_staged", lambda: False)
    monkeypatch.setattr(updater, "apply", lambda opts: calls.append(f"updater.apply({opts})") or 0)
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda u: calls.append(f"webbrowser.open({u})"))
    app = desktop.Desktop("Heronry Desktop")
    app.window = FakeWindow()
    app.window.load_url = lambda u: calls.append(f"window.load_url({u})")
    app.window.show = lambda: calls.append("window.show()")
    monkeypatch.setattr(desktop, "save_prefs", lambda p: calls.append(f"save_prefs(stop_services_on_quit={p['stop_services_on_quit']})"))
    app.make_tray()
    rows: list[tuple[str, str]] = []
    for it in made["menu"].items:
        if it.action is None:
            rows.append(("----", ""))
            continue
        calls.clear()
        app.prefs, app.quitting = {"stop_services_on_quit": stop_on_quit}, False
        it.action(None, it)
        rows.append((it.text, "; ".join(calls) or "(no command)"))
    return rows


def test_tray_menu_model_dump(monkeypatch, capsys):
    """Prints the tray menu model for the S21 report (`pytest -s -k tray_menu_model_dump`): every item and the
    command it calls. Start/stop/restart are `heronry` CLI verbs, the terminal's own code path."""
    rows = tray_menu_dump(monkeypatch)
    bundled = dict(tray_menu_dump(monkeypatch, bundled=True))
    stopping = dict(tray_menu_dump(monkeypatch, stop_on_quit=True))
    got = dict(rows)
    assert got["Start services"] == "heronry start --no-browser"
    assert got["Stop services"] == "heronry stop"
    assert got["Restart services"] == "heronry restart"
    assert got["Start code server"] == "heronry start code" and got["Stop code server"] == "heronry stop code"
    assert got["Install update"] == "updater.apply({'relaunch-app': True})" == bundled["Install update"]
    assert got["Open board"] == "window.show()"
    assert got["Quit"] == "(no command)"  # services stay up unless "Stop services on quit" is set
    assert stopping["Quit"] == "heronry stop"
    with capsys.disabled():
        print("\n== tray menu model (edp8.desktop.Desktop.make_tray), item -> what a click runs")
        for text, run in rows:
            print(f"  {text:<24} {run}")
        print(f"  {'Install update':<24} {bundled['Install update']}   <- bundled (installed) app")
        print(f"  {'Quit':<24} {stopping['Quit']}   <- with 'Stop services on quit' set")


# ------------------------------------------------------------------------------------------ S11 (s-9277bcebc9)

class FakeTray:
    HAS_NOTIFICATION = True

    def __init__(self, fail=False):
        self.toasts: list[tuple[str, str]] = []
        self.cleared = 0
        self.fail = fail

    def notify(self, message, title=None):
        if self.fail:
            raise OSError("shell refused")
        self.toasts.append((title, message))

    def remove_notification(self):
        self.cleared += 1


def test_toast_goes_through_the_tray_and_is_capped_to_the_balloon_limits():
    app = desktop.Desktop("Heronry Desktop")
    app.tray = FakeTray()
    assert app.toast("T" * 100, "m" * 400) is True
    (title, message), = app.tray.toasts
    assert len(title) == 60 and len(message) == 250


def test_toast_is_false_without_a_tray_or_when_the_shell_refuses():
    app = desktop.Desktop("H")
    assert app.toast("t", "m") is False and app.can_toast() is False
    app.tray = FakeTray(fail=True)
    assert app.toast("t", "m") is False


def test_wiring_the_notify_hook_turns_action_results_into_toasts_not_dialogs(cli_calls):
    app = desktop.Desktop("Heronry Desktop")
    app.window, app.tray = FakeWindow(), FakeTray()
    app.use_toasts()
    dict(app.actions())["Start services"]()
    assert app.tray.toasts == [("Heronry Desktop: start", "start ok")]
    assert not [c for c in app.window.calls if c[0] == "create_confirmation_dialog"]


def test_a_toast_that_cannot_be_raised_falls_back_to_the_dialog(cli_calls):
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    app.use_toasts()  # no tray: toast() is False
    app.show("hello")
    assert app.window.calls[-1][0] == "create_confirmation_dialog"


def test_the_bridge_notify_raises_a_capped_toast_and_drops_a_burst():
    app = desktop.Desktop("Heronry Desktop")
    app.tray = FakeTray()
    bridge = desktop.Bridge(app)
    assert bridge.notify("Question for you", "x" * 500) == {"ok": True}
    assert app.tray.toasts[0][0] == "Question for you" and len(app.tray.toasts[0][1]) == 240
    assert bridge.notify("", "no title")["ok"] and app.tray.toasts[-1][0] == "Heronry Desktop"
    for _ in range(3):
        assert bridge.notify("t", "b")["ok"]
    assert bridge.notify("t", "one too many") == {"ok": False, "reason": "rate-limited"}
    assert len(app.tray.toasts) == 5


def test_the_bridge_says_so_when_there_is_no_tray():
    assert desktop.Bridge(desktop.Desktop("H")).notify("t", "b") == {"ok": False, "reason": "no-tray"}


def test_the_bridge_exposes_only_its_public_methods_and_hides_the_app():
    public = {n for n in dir(desktop.Bridge(desktop.Desktop("H"))) if not n.startswith("_")}
    assert public == {"ping", "notify", "open_external"}
    assert desktop.Bridge(desktop.Desktop("H")).ping()["shell"] == "heronry-desktop"


def test_bridge_open_external_opens_http_links_only(monkeypatch):
    import webbrowser
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u) or True)
    bridge = desktop.Bridge(desktop.Desktop("H"))
    assert bridge.open_external("https://example.com/a?b=1") is True
    assert bridge.open_external("file:///C:/Windows/System32/calc.exe") is False
    assert bridge.open_external("javascript:alert(1)") is False
    assert opened == ["https://example.com/a?b=1"]


@pytest.mark.parametrize("url,want", [
    ("http://127.0.0.1:9400/ui/ticket/t-1", "allow"),            # the board: stays in the window
    ("http://127.0.0.1:9400/ui/records/t-1?as=owner", "allow"),   # a same-origin 'Open in tab' opens in the window
    ("about:blank", "allow"),
    ("data:text/html,<b>x</b>", "block"), ("blob:http://127.0.0.1:9400/abc", "block"),  # a top-level page here gets the bridge
    ("about:srcdoc", "block"),
    ("https://github.com/org/repo", "external"),                  # a foreign site goes to the system browser
    ("http://127.0.0.1:9402/mcp", "external"),                    # same host, another port = another origin
    ("https://127.0.0.1:9400/ui/", "external"),                   # same host and port, other scheme
    ("file:///C:/Users/x/secret.txt", "block"), ("javascript:alert(1)", "block"), ("ms-settings:privacy", "block"),
])
def test_navigation_policy(url, want):
    assert desktop.navigation_decision(url, "http://127.0.0.1:9400") == want


def test_only_the_shells_own_splash_may_be_a_data_page_and_only_before_the_board_loads():
    splash = "data:text/html;charset=utf-8;base64,PGI+eDwvYj4="
    assert desktop.navigation_decision(splash, "http://127.0.0.1:9400", splash=True) == "allow"
    assert desktop.navigation_decision(splash, "http://127.0.0.1:9400", splash=False) == "block"
    assert desktop.navigation_decision("blob:http://127.0.0.1:9400/x", "http://127.0.0.1:9400", splash=True) == "block"


def test_boot_closes_the_splash_window_for_data_pages_before_the_board_url_loads(monkeypatch, cli_calls):
    monkeypatch.setattr(desktop, "initialized", lambda: True)
    monkeypatch.setattr(desktop, "services_up", lambda: True)
    monkeypatch.setattr(desktop, "entry_url", lambda: "http://127.0.0.1:5555/ui/")
    app = desktop.Desktop("H")
    app.window = FakeWindow()
    seen: list[bool] = []
    app.window.load_url = lambda u: seen.append(app.splash_open)
    assert app.splash_open is True
    app.boot()
    assert seen == [False] and app.splash_open is False


def test_navigation_guard_cancels_a_foreign_navigation_and_opens_the_browser(monkeypatch):
    import webbrowser
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u) or True)
    monkeypatch.setattr(desktop, "board_origin", lambda: "http://127.0.0.1:9400")
    app = desktop.Desktop("H")
    app.splash_open = False
    for uri, cancelled, browser in [("http://127.0.0.1:9400/ui/", False, []), ("https://example.org/x", True, ["https://example.org/x"]),
                                    ("file:///etc/passwd", True, []), ("data:text/html,<b>x</b>", True, []),
                                    ("blob:http://127.0.0.1:9400/x", True, [])]:
        opened.clear()
        args = types.SimpleNamespace(Uri=uri, Cancel=False)
        app._on_navigation_starting(None, args)
        assert (args.Cancel, opened) == (cancelled, browser)


def test_the_window_allows_text_selection_and_carries_the_bridge(monkeypatch):
    """The quoting cause: pywebview's text_select defaults to False, which injects `user-select:none`."""
    seen: dict = {}
    fake = types.SimpleNamespace(settings={"OPEN_EXTERNAL_LINKS_IN_BROWSER": True},
                                 create_window=lambda title, **kw: seen.update(kw) or "window")
    app = desktop.Desktop("H")
    monkeypatch.setattr(app, "menu", lambda: [])  # off Windows the real menu imports pywebview, which CI lacks
    assert desktop.make_window(app, fake) == "window"
    assert seen["text_select"] is True
    assert isinstance(seen["js_api"], desktop.Bridge)
    # pywebview's browser-only rule stays on until the navigation guard is confirmed attached
    assert fake.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True and app.settings is fake.settings
    assert app._notify == app.toast


def test_notify_test_raises_one_toast_from_a_one_off_tray_icon(monkeypatch, capsys):
    made: dict = {}

    class Icon:
        HAS_NOTIFICATION = True

        def __init__(self, name, image, title):
            made.update(name=name, title=title, calls=[])
            self.visible = False

        def run_detached(self, setup):
            setup(self)

        def notify(self, message, title=None):
            made["calls"].append(("notify", title, message))

        def remove_notification(self):
            made["calls"].append(("remove",))

        def stop(self):
            made["calls"].append(("stop",))

    monkeypatch.setitem(sys.modules, "pystray", types.SimpleNamespace(Icon=Icon))
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert desktop.notify_test_main(["--title", "Hello", "--message", "World", "--wait", "0"]) == 0
    assert made["calls"] == [("notify", "Hello", "World"), ("remove",), ("stop",)]
    assert "toast raised: Hello: World" in capsys.readouterr().out


def test_notify_test_reports_a_tray_that_cannot_notify(monkeypatch, capsys):
    class Icon:
        HAS_NOTIFICATION = False

        def __init__(self, *a):
            pass

        def stop(self):
            pass

    monkeypatch.setitem(sys.modules, "pystray", types.SimpleNamespace(Icon=Icon))
    assert desktop.notify_test_main([]) == 1
    assert "cannot raise notifications" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        desktop.notify_test_main(["--bogus"])


def test_the_notify_test_verb_is_in_the_cli():
    from edp8 import cli
    assert "notify-test" in cli._COMMANDS and "notify-test" in {c.name for c in cli.COMMANDS}
    assert "notify-test" in cli._UNGUARDED


class _Event:
    def __init__(self):
        self.handlers: list = []

    def __iadd__(self, h):
        self.handlers.append(h)
        return self


class _GuardedWindow:
    """pywebview 6.2.1 order: `webview.start(func)` runs boot before the native window and WebView2 core exist."""

    def __init__(self, ready_after: int | None):
        self.polls = 0
        self.ready_after = ready_after
        self.core = types.SimpleNamespace(NavigationStarting=_Event())
        self.events = types.SimpleNamespace(loaded=_Event())
        self.control = types.SimpleNamespace(CoreWebView2=None, IsHandleCreated=True, BeginInvoke=lambda action: action())
        self.calls: list = []

    @property
    def native(self):
        self.polls += 1
        if self.ready_after is None or self.polls <= self.ready_after:
            if self.polls <= 1:
                raise AttributeError("native")  # the form is not created yet
            self.control.CoreWebView2 = None  # created, but WebView2 still initialising
        else:
            self.control.CoreWebView2 = self.core
        return types.SimpleNamespace(webview=self.control)

    def load_url(self, url):
        self.calls.append(("load_url", url))

    def evaluate_js(self, js):
        self.calls.append(("evaluate_js", js))


@pytest.fixture
def win32_shell(monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "System", types.SimpleNamespace(Action=lambda f: f))
    monkeypatch.setattr(desktop.time, "sleep", lambda s: None)


def test_boot_attaches_the_navigation_guard_even_though_the_window_is_not_there_yet(monkeypatch, cli_calls, win32_shell):
    """The regression: boot() ran before create_window finished, so the guard saw no CoreWebView2 and gave up for good."""
    monkeypatch.setattr(desktop, "initialized", lambda: True)
    monkeypatch.setattr(desktop, "services_up", lambda: True)
    monkeypatch.setattr(desktop, "entry_url", lambda: "http://127.0.0.1:5555/ui/")
    settings = {"OPEN_EXTERNAL_LINKS_IN_BROWSER": True}
    app = desktop.Desktop("H")
    app.settings = settings
    app.guard_wait_s = 5.0
    app.window = _GuardedWindow(ready_after=3)
    app.boot()
    assert app.guard_attached is True
    assert app.window.core.NavigationStarting.handlers == [app._on_navigation_starting]
    assert settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is False  # only once the guard is on
    assert app.window.calls[-1] == ("load_url", "http://127.0.0.1:5555/ui/")  # the board loads after the guard


def test_a_guard_that_never_attaches_keeps_the_browser_only_rule_and_says_so(monkeypatch, cli_calls, win32_shell, caplog):
    monkeypatch.setattr(desktop, "initialized", lambda: True)
    monkeypatch.setattr(desktop, "services_up", lambda: True)
    monkeypatch.setattr(desktop, "entry_url", lambda: "http://127.0.0.1:5555/ui/")
    clock = iter(range(0, 1000))
    monkeypatch.setattr(desktop.time, "monotonic", lambda: next(clock))
    settings = {"OPEN_EXTERNAL_LINKS_IN_BROWSER": True}
    app = desktop.Desktop("H")
    app.settings = settings
    app.guard_wait_s = 3.0
    app.window = _GuardedWindow(ready_after=None)
    with caplog.at_level("WARNING", logger="edp8.desktop"):
        app.boot()
    assert app.guard_attached is False
    assert settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True
    assert "navigation guard not attached" in caplog.text
    # every later page load tries again
    assert app.attach_navigation_guard in app.window.events.loaded.handlers
    app.window.ready_after = 0
    app.window.polls = 5
    assert app.attach_navigation_guard() is True and settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is False


def test_notify_test_wait_must_be_a_number(capsys):
    for bad in ("soon", "-1", "9999"):
        with pytest.raises(SystemExit) as e:
            desktop.notify_test_main(["--wait", bad])
        assert "--wait" in str(e.value) and "Traceback" not in str(e.value)
