"""Heronry Desktop: the board in a native window plus a tray / menu-bar icon (design-e963c656f5 §4.9, S8).

`heronry gui`, and the bundle's app with no argument, land here. The desktop is a CLIENT of the one launcher:
every tray and window-menu action calls the same `edp8.cli` command the terminal runs (start, stop, restart,
status, update), so there is one code path (strategyhl-5af811e7bd §4). The GUI process owns no service:
closing the window hides it, Quit leaves the services running unless "Stop services on quit" is set.

* **First run** (no config.toml yet): `heronry init` with the harnesses found on this machine (claude and/or
  codex, else claude), then the window opens /ui/setup with a one-time sign-in code (S6's wizard picks the
  harnesses for real). Later runs open /ui/join with a fresh one-time code, so the window is signed in.
  The wizard's "Your tools" step is the prerequisites step: each Install click runs the one installer step,
  `heronry prereqs install --only <tool> --yes` (t-08612be1b0), so nothing is installed without a click.
* **Splash:** the S7 splash with a status line while the services come up.
* **Threads:** `webview.start()` owns the main thread (Cocoa rule); the tray runs `run_detached()` on macOS and
  Linux (it shares the GUI loop) and its own thread on Windows. Never multiprocessing (a bundle's
  `sys.executable` is the app itself).
* **WebView2** (Windows) is checked first; when missing the user is offered Microsoft's bootstrapper, and the
  board opens in the browser if they decline.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import logging
import os
import sys
import threading
import time
from importlib import resources
from pathlib import Path
from typing import Any, Callable

from . import settings

WEBVIEW2_CLIENT = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_BOOTSTRAPPER = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
PREFS_FILE = "desktop.json"


# ------------------------------------------------------------------------------------------ the one code path

def run_cli(verb: str, *args: str) -> tuple[int, str]:
    """Run a `heronry` command in-process, exactly as the terminal would, and return (exit code, output)."""
    from . import cli
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            rc = int(cli._COMMANDS[verb](list(args)) or 0)
        except SystemExit as e:  # argument errors exit; the GUI shows them instead
            rc = e.code if isinstance(e.code, int) else 1
            if not isinstance(e.code, int) and e.code:
                print(e.code)
        except Exception as e:  # noqa: BLE001 — shown to the user, never a crash of the GUI
            rc = 1
            print(f"{verb} failed: {e}")
    return rc, buf.getvalue().strip()


def status_text() -> str:
    from . import launcher
    lines = []
    for r in launcher.status_rows():
        if r["service"] == "bridge" and r.get("state") != "up":
            continue
        where = f"  {r['url']}" if r.get("url") else ""
        lines.append(f"{r['service']:<11}{r.get('state') or '-':<6}{where}")
    return "\n".join(lines)


def services_up() -> bool:
    from . import launcher
    return all(launcher.healthy(s) for s in ("board", "mcp", "pool", "broker"))


# ------------------------------------------------------------------------------------------ first run / URLs

def initialized() -> bool:
    return settings.config_file().is_file() and settings.admin_token_file().is_file()


def first_run_init() -> tuple[int, str]:
    """No config yet: `heronry init` with the harnesses this machine has (the /ui/setup wizard changes them)."""
    from .setup import detect_harnesses
    found = detect_harnesses()
    picked = [h for h in ("claude", "codex") if found.get(h)] or ["claude"]
    return run_cli("init", "--harness", ",".join(picked), "--yes")


def board_url() -> str:
    from . import launcher
    return str(launcher.url("board")).rstrip("/")


def entry_url() -> str:
    """Where the window lands: the setup wizard until it is finished, else the board, signed in once through a
    one-time code (never a token in the address bar)."""
    from .admin import setup_api
    base = board_url()
    try:
        code = setup_api.issue_setup_code()
    except Exception:  # noqa: BLE001 — no code: the board's own sign-in page
        return f"{base}/ui/"
    if not setup_api.state().get("done"):
        return f"{base}/ui/setup?code={code}"
    return f"{base}/ui/join?code={code}"


# ------------------------------------------------------------------------------------------ preferences

def prefs_path() -> Path:
    return settings.config_dir() / PREFS_FILE


def load_prefs() -> dict[str, Any]:
    try:
        data = json.loads(prefs_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_prefs(prefs: dict[str, Any]) -> None:
    p = prefs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(prefs, indent=1), encoding="utf-8")


# ------------------------------------------------------------------------------------------ assets

def _asset(name: str) -> Path:
    """Package data in a wheel or bundle; in a source checkout (dev mode) the S7 files under the home."""
    packaged = Path(str(resources.files("edp8").joinpath("desktop_assets", name)))
    if packaged.is_file():
        return packaged
    from .brand import ASSET_DIR
    from .materialise import checkout_root
    # a source checkout (read-only brand art, never state)
    roots = [r for r in (settings.home(), checkout_root()) if r is not None]
    for root in roots:
        for rel in (name, f"icons/{name}"):
            if (root / ASSET_DIR / rel).is_file():
                return root / ASSET_DIR / rel
    raise FileNotFoundError(f"desktop asset {name} is missing from this build")


def asset_bytes(name: str) -> bytes:
    return _asset(name).read_bytes()


def asset_path(name: str) -> str:
    return str(_asset(name))


def splash_html(product: str) -> str:
    img = base64.b64encode(asset_bytes("heronry-splash.png")).decode("ascii")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{product}</title><style>
html,body{{margin:0;height:100%;background:#211B18;color:#F5EBDD;font:15px system-ui,sans-serif}}
body{{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px}}
img{{max-width:80vw;max-height:70vh;border-radius:12px}}#s{{color:#C1AEA1;min-height:1.4em}}
</style></head><body><img alt="{product}" src="data:image/png;base64,{img}"><div id="s" role="status">Starting…</div>
<script>window.setStatus=function(t){{document.getElementById('s').textContent=t}}</script></body></html>"""


# ------------------------------------------------------------------------------------------ WebView2

def webview2_version() -> str | None:
    """The installed Evergreen WebView2 runtime version (machine or user install), else None."""
    if sys.platform != "win32":
        return None
    import winreg
    keys = [(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT}"),
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT}"),
            (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT}")]
    for root, key in keys:
        try:
            with winreg.OpenKey(root, key) as k:
                v, _ = winreg.QueryValueEx(k, "pv")
                if v and v != "0.0.0.0":
                    return str(v)
        except OSError:
            continue
    return None


def _ask(title: str, text: str) -> bool:
    """A native yes/no box before any GUI toolkit is up (Windows only)."""
    import ctypes
    return ctypes.windll.user32.MessageBoxW(None, text, title, 0x4 | 0x20) == 6  # MB_YESNO|MB_ICONQUESTION -> IDYES


def ensure_webview2(product: str) -> bool:
    """True when the window can open. Missing runtime: offer Microsoft's bootstrapper (~2 MB, per-user)."""
    if sys.platform != "win32" or webview2_version():
        return True
    if not _ask(product, f"{product} shows the board in a Microsoft Edge WebView2 window, which is not installed.\n\n"
                         "Download and install the WebView2 Runtime from Microsoft now?\n"
                         "(No: the board opens in your browser instead.)"):
        return False
    import subprocess
    import tempfile

    import httpx
    target = Path(tempfile.gettempdir()) / "MicrosoftEdgeWebview2Setup.exe"
    try:
        with httpx.stream("GET", WEBVIEW2_BOOTSTRAPPER, follow_redirects=True, timeout=60) as r:
            r.raise_for_status()
            with target.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        subprocess.run([str(target), "/silent", "/install"], timeout=600, check=False)
    except Exception:  # noqa: BLE001 — fall back to the browser
        return False
    return webview2_version() is not None


# ------------------------------------------------------------------------------------------ toasts and the page bridge

NOTIFY_TITLE_MAX = 80
NOTIFY_BODY_MAX = 240
NOTIFY_BURST = (5, 10.0)  # at most 5 toasts per 10 s from the page; a runaway page cannot flood the desktop
TOAST_LINGER_S = 10.0


def board_origin() -> str:
    """scheme://host:port of the board this window shows (what the navigation guard treats as 'in the app')."""
    from urllib.parse import urlsplit
    u = urlsplit(board_url())
    return f"{u.scheme}://{u.netloc}"


def navigation_decision(url: str, origin: str, *, splash: bool = False) -> str:
    """The window's navigation policy (design §4.G): `allow` stays in the window (the board, about:blank, and the
    shell's own splash `data:` page while `splash` is true, i.e. before the board URL first loads), `external` goes to
    the system browser, `block` is dropped (file:, javascript:, blob:, any later data: page, app-private schemes: a
    top-level page in this window gets the bridge). A same-origin target=_blank opens in the window; a foreign site never."""
    from urllib.parse import urlsplit
    try:
        u = urlsplit(url.strip())
    except ValueError:
        return "block"
    scheme = u.scheme.lower()
    if url.strip().lower() == "about:blank":
        return "allow"
    if scheme == "data":
        return "allow" if splash else "block"
    if scheme in ("http", "https"):
        return "allow" if f"{scheme}://{u.netloc}".lower() == origin.lower() else "external"
    return "block"


def open_in_browser(url: str) -> bool:
    """Hand an http(s) URL to the system browser; anything else is refused."""
    import webbrowser
    if navigation_decision(url, "") != "external":  # empty origin: every http(s) URL is foreign, other schemes blocked
        return False
    return bool(webbrowser.open(url))


class Bridge:
    """`window.pywebview.api`: the whole of what the board page may ask of the shell. Public methods only (pywebview
    walks every public attribute), so the app handle is private; the window never leaves the board's own origin
    (navigation guard), so only the board's page can call these."""

    def __init__(self, app: "Desktop") -> None:
        self._app = app
        self._sent: list[float] = []

    def ping(self) -> dict[str, Any]:
        """Lets the page confirm it runs inside the desktop shell (and which one)."""
        return {"shell": "heronry-desktop", "platform": sys.platform, "toast": self._app.can_toast()}

    def notify(self, title: str = "", body: str = "") -> dict[str, Any]:
        """A native desktop toast for a board attention event (the SPA calls it for the same mention-triggered
        requests the browser shows). Text is capped and bursts are dropped, never queued."""
        now = time.monotonic()
        count, per = NOTIFY_BURST
        self._sent = [t for t in self._sent if now - t < per]
        if len(self._sent) >= count:
            return {"ok": False, "reason": "rate-limited"}
        title = str(title or "").strip()[:NOTIFY_TITLE_MAX] or self._app.product
        body = str(body or "").strip()[:NOTIFY_BODY_MAX]
        if not self._app.toast(title, body):
            return {"ok": False, "reason": "no-tray"}
        self._sent.append(now)
        return {"ok": True}

    def open_external(self, url: str) -> bool:
        """Open an http(s) link in the system browser (the page uses it for external anchors)."""
        return open_in_browser(str(url))


def raise_toast(title: str, message: str, *, wait_s: float = 6.0) -> tuple[bool, str]:
    """A native toast from a one-off tray icon (for `heronry notify-test`, which has no desktop app to borrow).
    (raised, what happened)."""
    try:
        import pystray
        from PIL import Image
    except ImportError as e:
        return False, f"the tray library is not installed ({e}); the desktop extra provides it"
    icon = pystray.Icon("heronry-notify-test", Image.open(io.BytesIO(asset_bytes("heronry-64.png"))), title)
    if not getattr(icon, "HAS_NOTIFICATION", False):
        return False, "this platform's tray cannot raise notifications"
    ready = threading.Event()

    def setup(i: Any) -> None:
        i.visible = True
        ready.set()
    icon.run_detached(setup)
    try:
        if not ready.wait(10.0):
            return False, "the tray icon did not come up within 10 s"
        time.sleep(1.0)  # let the shell register the new icon before it is asked for a toast
        icon.notify(message, title)
        time.sleep(wait_s)
        with contextlib.suppress(Exception):
            icon.remove_notification()
        return True, f"toast raised: {title}: {message}"
    except Exception as e:  # noqa: BLE001 — shown to the user
        return False, f"the toast could not be raised: {e}"
    finally:
        with contextlib.suppress(Exception):
            icon.stop()


def notify_test_main(argv: list[str]) -> int:
    """`heronry notify-test [--title T] [--message M] [--wait S]`: raise one native desktop toast and say whether it
    was raised (exit 0) or why not (exit 1)."""
    from .brand import DESKTOP_APP_NAME
    title, message, wait_s = DESKTOP_APP_NAME, "Test notification from `heronry notify-test`.", 6.0
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--title", "--message", "--wait") and i + 1 < len(argv):
            if a == "--wait":
                try:
                    wait_s = float(argv[i + 1])
                except ValueError:
                    raise SystemExit(f"heronry notify-test: --wait needs a number of seconds, not {argv[i + 1]!r}") from None
                if not 0 <= wait_s <= 600:
                    raise SystemExit(f"heronry notify-test: --wait must be between 0 and 600 seconds, not {argv[i + 1]!r}")
            elif a == "--title":
                title = argv[i + 1]
            else:
                message = argv[i + 1]
            i += 2
        else:
            raise SystemExit(f"heronry notify-test: unknown option {a!r} (usage: heronry notify-test [--title T] [--message M] [--wait S])")
    ok, text = raise_toast(title[:NOTIFY_TITLE_MAX], message[:NOTIFY_BODY_MAX], wait_s=wait_s)
    print(text, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


# ------------------------------------------------------------------------------------------ the app

class Desktop:
    """Window + tray state and the actions both of them offer (one set, so the tray is never the only way in)."""

    def __init__(self, product: str, *, notify: Callable[[str, str], bool | None] | None = None) -> None:
        self.product = product
        self.window: Any = None
        self.tray: Any = None
        self.quitting = False
        self.prefs = load_prefs()
        self._notify = notify
        self.capture_dir: Path | None = None  # `heronry gui --capture <dir>`: the app shoots its own page, then quits
        self.settle_s = 6.0
        self.guard_wait_s = 20.0
        self._code_state: tuple[float, bool] = (0.0, False)  # (checked at, up): the tray asks on every open
        self.guard_attached = False
        self._guard_hooked = False
        self.guard_error = ""
        self.splash_open = True  # the shell's own data: page is the only one allowed, until the board URL first loads
        self.settings: Any = None  # pywebview's settings dict (set by make_window); the guard flips the link rule

    # ---- toasts ---------------------------------------------------------------------------------
    def can_toast(self) -> bool:
        return self.tray is not None and bool(getattr(self.tray, "HAS_NOTIFICATION", False))

    def toast(self, title: str, message: str) -> bool:
        """A native toast through the tray icon (Windows: the balloon the shell shows as a toast). False when there
        is no tray to raise it from; the caller falls back to a dialog."""
        if not self.can_toast():
            return False
        try:
            self.tray.notify(message[:250], title[:60])  # the Windows balloon cuts at 255 / 63 characters
        except Exception:  # noqa: BLE001 — a tray that cannot notify is a fallback, never a crash
            return False
        timer = threading.Timer(TOAST_LINGER_S, self._clear_toast)
        timer.daemon = True
        timer.start()
        return True

    def _clear_toast(self) -> None:
        with contextlib.suppress(Exception):
            self.tray.remove_notification()

    def use_toasts(self) -> None:
        """Wire the notify hook: action results and update outcomes become toasts instead of modal dialogs."""
        self._notify = self.toast

    # ---- actions (tray menu, window menu) ------------------------------------------------------
    def show(self, message: str, title: str | None = None) -> None:
        title = title or self.product
        if self.capture_dir is not None:  # unattended capture run: the message is evidence (and a toast when wired)
            with open(self.capture_dir / "messages.txt", "a", encoding="utf-8") as f:
                f.write(f"== {title}\n{message}\n")
            print(f"{title}: {message}")
        if self._notify and self._notify(title, message) is not False:
            return
        if self.capture_dir is None and self.window is not None:
            self.window.create_confirmation_dialog(title, message)

    def open_board(self) -> None:
        if self.window is None:
            import webbrowser
            webbrowser.open(entry_url())
            return
        self.window.show()
        self.window.restore()

    def _verb(self, verb: str, *args: str) -> int:
        rc, out = run_cli(verb, *args)
        self.show(out or f"{verb}: done", f"{self.product}: {verb}")
        return rc

    def start(self) -> None:
        self._verb("start", "--no-browser")

    def stop(self) -> None:
        self._verb("stop")

    def restart(self) -> None:
        self._verb("restart")

    def status(self) -> None:
        self.show(status_text(), f"{self.product}: status")

    # ---- the optional code server (S21): `heronry start|stop code`, the same command the terminal runs
    def code_up(self, max_age_s: float = 5.0) -> bool:
        """Whether this home's code server is up (cached briefly: the tray re-asks every time its menu opens)."""
        at, up = self._code_state
        if time.monotonic() - at > max_age_s:
            from . import code_service
            try:
                up = code_service.status()["state"] == "up"
            except Exception:  # noqa: BLE001 — unknown: offer Start; the command says what is wrong
                up = False
            self._code_state = (time.monotonic(), up)
        return up

    def start_code(self) -> None:
        self._verb("start", "code")
        self._code_state = (0.0, False)

    def stop_code(self) -> None:
        self._verb("stop", "code")
        self._code_state = (0.0, False)

    def open_code(self) -> None:
        """The board's Code tab (it embeds the code server, or says how to start it)."""
        target = f"{board_url()}/ui/code"
        if self.window is None:
            import webbrowser
            webbrowser.open(target)
            return
        self.window.load_url(target)
        self.window.show()
        self.window.restore()

    def update(self) -> None:
        """Install update: check GitHub Releases; on a newer release ask, then `updater.apply` in this process, the
        one entry `heronry update` calls too (S10). The bundle closes for its installer and comes back by itself."""
        from . import updater
        title = f"{self.product}: update"
        if updater.update_staged():
            self.show("An update is already installing; its outcome is shown here when it finishes.", title)
            return
        try:
            got = updater.check(force=True, timeout=10.0)
        except Exception as e:  # noqa: BLE001
            got, why = None, str(e)
        else:
            why = "could not reach GitHub (or no release yet)"
        if got is None:
            self.show(why, title)
            return
        if not got.get("newer"):
            self.show(f"{self.product} {got['current']} is up to date.", title)
            return
        ask = (f"{self.product} {got['latest']} is available (you have {got['current']}).\n\n"
               "Install it now? Working seats pause and resume, the services restart and this window closes and "
               "reopens. Your board data and settings stay. If the update fails it goes back to the version you have.")
        if self.window is not None and not self.window.create_confirmation_dialog(title, ask):
            return
        self.install_update()

    def install_update(self) -> None:
        from . import launcher, updater
        title = f"{self.product}: update"
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                updater.apply({"relaunch-app": True})
        except updater.UpdateError as e:
            self.show(f"Update refused: {e}", title)
            return
        except Exception as e:  # noqa: BLE001 — shown, never a crash of the GUI
            self.show(f"The update could not start: {e}", title)
            return
        if not updater.update_staged():
            self.show(buf.getvalue().strip() or "Nothing to install.", title)
            return
        if launcher.bundled():
            self._close_for_update()
        else:
            self.show("Installing in the background; the outcome is shown here when it finishes.", title)

    def _close_for_update(self) -> None:
        """The runner waits for this process to exit before it installs over the app; it stops the services itself."""
        self.quitting = True
        if self.tray is not None:
            with contextlib.suppress(Exception):
                self.tray.stop()
        if self.window is not None:
            with contextlib.suppress(Exception):
                self.window.destroy()
        threading.Timer(5.0, os._exit, [0]).start()  # a lingering tray thread must not hold the install

    def announce_update_result(self) -> None:
        """An outcome the runner wrote that this tray has not shown: Updated to X / Rolled back: why / Failed: why."""
        from . import updater
        res = updater.last_result()
        if res and res.get("finished_at") and not res.get("_seen"):
            updater.mark_result_seen(res)
            self.show(updater.result_text(res), f"{self.product}: update")

    def toggle_stop_on_quit(self) -> None:
        self.prefs["stop_services_on_quit"] = not self.stop_on_quit
        save_prefs(self.prefs)

    @property
    def stop_on_quit(self) -> bool:
        return bool(self.prefs.get("stop_services_on_quit"))

    def quit(self) -> None:
        self.quitting = True
        if self.stop_on_quit:
            rc, out = run_cli("stop")
            if rc != 0:
                self.show(f"Some services were left running:\n{out}", f"{self.product}: quit")
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:  # noqa: BLE001
                pass
        if self.window is not None:
            self.window.destroy()

    def actions(self) -> list[tuple[str, Callable[[], None]]]:
        return [("Open board", self.open_board), ("Status", self.status), ("Start services", self.start),
                ("Stop services", self.stop), ("Restart services", self.restart), ("Install update", self.update),
                ("Start code server", self.start_code), ("Stop code server", self.stop_code),
                ("Open Code tab", self.open_code)]

    def enabled(self, label: str) -> bool:
        """Start/Stop code server are offered by state (S21); every other action always is."""
        if label == "Start code server":
            return not self.code_up()
        if label == "Stop code server":
            return self.code_up()
        if label == "Install update":  # one update at a time: Windows Installer or a staged runner is mid-way
            from . import updater
            try:
                return not (updater.update_staged() or updater.install_scope_busy())
            except Exception:  # noqa: BLE001 — unknown: offer it; apply refuses with the reason
                return True
        return True

    # ---- window --------------------------------------------------------------------------------
    def on_closing(self) -> bool:
        """Closing the window hides it (the tray and services stay); Quit really closes."""
        if self.quitting or self.tray is None:
            return True
        self.window.hide()
        return False

    def attach_navigation_guard(self) -> bool:
        """Hook WebView2's NavigationStarting: a top-level navigation off the board's origin is cancelled and handed
        to the system browser (`navigation_decision`). Windows/WebView2 only; elsewhere pywebview's own rules apply.
        `webview.start(func)` runs `func` before the native window exists, so this can fail early; `ensure_navigation_
        guard` retries. Until it succeeds pywebview's own rule (every new window goes to the browser) stays on."""
        if sys.platform != "win32" or self.window is None:
            return False
        if self.guard_attached:
            return True
        try:
            from System import Action  # type: ignore[import-not-found]
            control = self.window.native.webview  # None until the form exists: AttributeError, retried
            if not control.IsHandleCreated:
                self.guard_error = "the window handle does not exist yet"
                return False
            done, outcome = threading.Event(), []

            def hook() -> None:  # on the UI thread, the only one that may touch CoreWebView2
                try:
                    core = control.CoreWebView2
                    if core is None:
                        outcome.append("CoreWebView2 is not ready yet")
                    elif self._guard_hooked:
                        outcome.append("")
                    else:
                        core.NavigationStarting += self._on_navigation_starting
                        self._guard_hooked = True
                        outcome.append("")
                except Exception as e:  # noqa: BLE001
                    outcome.append(f"{type(e).__name__}: {e}")
                finally:
                    done.set()
            control.BeginInvoke(Action(hook))  # never Invoke: a busy UI thread must not block the boot thread
            if not done.wait(3.0):
                self.guard_error = "the window's UI thread did not answer"
                return False
            if outcome[0]:
                self.guard_error = outcome[0]
                return False
        except Exception as e:  # noqa: BLE001 — no guard is a degraded window, never a crash
            self.guard_error = f"{type(e).__name__}: {e}"
            return False
        self.guard_attached = True
        self.guard_error = ""
        if self.settings is not None:
            self.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False  # the guard decides from here on
        return True

    def ensure_navigation_guard(self, wait_s: float | None = None) -> bool:
        """Attach the guard as soon as the native window and its WebView2 core exist (polling up to `wait_s`), and keep
        retrying on every page load after that. Logs the failure; the window then keeps pywebview's browser-only rule."""
        wait_s = self.guard_wait_s if wait_s is None else wait_s
        deadline = time.monotonic() + wait_s
        while not self.attach_navigation_guard():
            if sys.platform != "win32" or time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        if self.guard_attached:
            return True
        if sys.platform == "win32":
            logging.getLogger("edp8.desktop").warning("navigation guard not attached (%s); external links keep going to "
                                                      "the browser through pywebview's own rule", self.guard_error)
            events = getattr(self.window, "events", None)
            if events is not None and hasattr(events, "loaded"):
                with contextlib.suppress(Exception):
                    events.loaded += self.attach_navigation_guard
        return False

    def _on_navigation_starting(self, _sender: Any, args: Any) -> None:
        uri = str(args.Uri)
        decision = navigation_decision(uri, board_origin(), splash=self.splash_open)
        if decision == "allow":
            return
        args.Cancel = True
        if decision == "external":
            open_in_browser(uri)

    def boot(self) -> None:
        """Runs beside the GUI loop: bring the services up (showing progress on the splash), then the board."""
        self.ensure_navigation_guard()
        if self.capture_dir is None:
            self._boot()
            with contextlib.suppress(Exception):
                self.announce_update_result()
            return
        import time
        try:
            time.sleep(1.5)  # the splash's first paint
            self.capture("01-splash.png")
            self._boot()
            time.sleep(self.settle_s)
            self.capture("02-window.png")
        except Exception as e:  # noqa: BLE001 — a capture run always ends
            self.show(f"capture failed: {e}", f"{self.product}: capture")
        finally:
            self.quit()

    def capture(self, name: str) -> Path:
        """Write the window's own page as a PNG (the web content only; never the screen or another window)."""
        assert self.capture_dir is not None
        out = self.capture_dir / name
        out.write_bytes(capture_png(self.window))
        page = ""
        with contextlib.suppress(Exception):
            page = self.window.get_current_url() or ""
        print(f"captured {out}  {page.split('?')[0]}")
        return out

    def _boot(self) -> None:
        def say(text: str) -> None:
            if self.window is not None:
                self.window.evaluate_js(f"window.setStatus && window.setStatus({json.dumps(text)})")
        if not initialized():
            say("First run: setting up…")
            rc, out = first_run_init()
            if rc != 0:
                say("Setup failed — see the message")
                self.show(out, f"{self.product}: setup")
                return
        from . import launcher
        while True:  # an update owns the services: show its step, start nothing, go on once it has its result
            blocked = launcher.update_block()
            if not blocked:
                break
            say(blocked.split("; wait")[0] + "…")
            time.sleep(2.0)
        if not services_up():
            say("Starting the board, pool, broker and MCP…")
            rc, out = run_cli("start", "--no-browser")
            if rc != 0:
                say("A service did not start — see the message")
                self.show(out, f"{self.product}: start")
                if not services_up():
                    return
        say("Opening the board…")
        url = entry_url()
        self.splash_open = False  # from here a data: page is not the shell's splash any more
        self.window.load_url(url)
        if "/ui/join?" in url:
            self._on_to_board()

    def _on_to_board(self, wait_s: float = 20.0) -> None:
        """/ui/join redeems the one-time code into this window's session (sessionStorage), then says so; the
        desktop goes on to the board itself once the session holds a token."""
        import time
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            try:
                if self.window.evaluate_js("sessionStorage.getItem('edp8.token') ? 1 : 0") == 1:
                    self.window.load_url(f"{board_url()}/ui/")
                    return
            except Exception:  # noqa: BLE001 — the page is still loading
                pass
            time.sleep(0.5)

    def menu(self) -> list[Any]:
        """The window's menu. None on Windows: the tray carries every item, and a WinForms menu strip under the
        title bar reads as a second title bar (owner look, S8 step 6)."""
        if sys.platform == "win32":
            return []
        from webview.menu import Menu, MenuAction, MenuSeparator
        items: list[Any] = [MenuAction(label, fn) for label, fn in self.actions()]
        items += [MenuSeparator(), MenuAction("Stop services on quit (toggle)", self.toggle_stop_on_quit),
                  MenuAction("Quit", self.quit)]
        return [Menu(self.product, items)]

    # ---- tray ----------------------------------------------------------------------------------
    def make_tray(self) -> Any:
        import pystray
        from PIL import Image

        def item(label: str, fn: Callable[[], None], **kw: Any) -> Any:
            return pystray.MenuItem(label, lambda _icon, _item: threading.Thread(target=fn, daemon=True).start(), **kw)
        entries = [item(label, fn, default=(label == "Open board"), enabled=lambda _i, lb=label: self.enabled(lb))
                   for label, fn in self.actions()]
        entries += [pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Stop services on quit", lambda _i, _t: self.toggle_stop_on_quit(),
                                     checked=lambda _t: self.stop_on_quit),
                    pystray.MenuItem("Quit", lambda _i, _t: self.quit())]
        image = Image.open(io.BytesIO(asset_bytes("heronry-64.png")))
        self.tray = pystray.Icon("heronry", image, self.product, pystray.Menu(*entries))
        return self.tray


def capture_png(window: Any, timeout_s: float = 20.0) -> bytes:
    """The window's web content as PNG bytes, taken by the webview itself: WebView2's CapturePreviewAsync on
    Windows (pywebview's native form holds the control). No screen grab, no other process's window."""
    if sys.platform != "win32":
        raise RuntimeError("--capture is implemented for Windows (WebView2) only")
    from threading import Semaphore

    from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat  # type: ignore[import-not-found]
    from System import Action, Func, Object  # type: ignore[import-not-found]
    from System.IO import MemoryStream  # type: ignore[import-not-found]
    from System.Threading.Tasks import Task  # type: ignore[import-not-found]
    control = window.native.webview
    stream = MemoryStream()
    done = Semaphore(0)
    failed: list[str] = []

    def finished(task: Any) -> None:
        if task.IsFaulted:
            failed.append(str(task.Exception))
        done.release()

    control.Invoke(Func[Object](lambda: control.CoreWebView2.CapturePreviewAsync(
        CoreWebView2CapturePreviewImageFormat.Png, stream).ContinueWith(Action[Task](finished))))
    if not done.acquire(timeout=timeout_s):
        raise RuntimeError(f"the webview did not return a capture within {timeout_s:.0f}s")
    if failed:
        raise RuntimeError(failed[0])
    return bytes(stream.ToArray())


def capture_dir(path: str | None) -> Path:
    """Where `--capture` writes: `<data dir>/captures` by default; only ever inside the app's own dirs, so the
    installed app never writes into an arbitrary folder."""
    own = [settings.data_dir(), settings.run_dir(), settings.logs_dir()]
    target = Path(path).expanduser().resolve() if path else (settings.data_dir() / "captures").resolve()
    if not any(target == d.resolve() or target.is_relative_to(d.resolve()) for d in own):
        raise SystemExit(f"heronry gui --capture: {target} is outside Heronry's own folders; use a folder under "
                         f"{settings.data_dir()} (the default is {settings.data_dir() / 'captures'})")
    return target


def parse_args(argv: list[str]) -> dict[str, Any]:
    """`heronry gui [--capture [<dir>]] [--settle <seconds>]`."""
    opts: dict[str, Any] = {"capture": None, "settle": 6.0}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--capture":
            given = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else None
            opts["capture"] = capture_dir(given)
            i += 2 if given is not None else 1
        elif a == "--settle" and i + 1 < len(argv):
            opts["settle"] = float(argv[i + 1])
            i += 2
        else:
            raise SystemExit(f"heronry gui: unknown option {a!r} (usage: heronry gui [--capture [<dir>]] [--settle <s>])")
    return opts


def make_window(app: Desktop, webview: Any) -> Any:
    """The one window. `text_select=True` is the quoting fix: pywebview's default (False) injects `user-select:none`
    on the body, so no text could be selected and the SPA's select-to-quote never saw a range. The page bridge
    (`Bridge`) carries toasts and external links; the navigation guard replaces pywebview's send-every-new-window-
    to-the-browser rule (a same-origin 'Open in tab' stays in the window, a foreign site goes to the browser)."""
    from .brand import DESKTOP_APP_NAME
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # pywebview's own rule until the guard is attached
    app.settings = webview.settings
    app.use_toasts()
    return webview.create_window(DESKTOP_APP_NAME, html=splash_html(DESKTOP_APP_NAME), width=1280, height=820,
                                 min_size=(720, 480), background_color="#211B18", menu=app.menu(),
                                 js_api=Bridge(app), text_select=True)


def main(argv: list[str] | None = None) -> int:
    from .brand import DESKTOP_APP_NAME
    opts = parse_args(list(argv or []))
    app = Desktop(DESKTOP_APP_NAME)
    if opts["capture"] is not None:
        app.capture_dir = opts["capture"]
        app.capture_dir.mkdir(parents=True, exist_ok=True)
        app.settle_s = opts["settle"]
    if not ensure_webview2(DESKTOP_APP_NAME):
        # no window possible: the services still come up and the board opens in the browser
        if not initialized():
            first_run_init()
        run_cli("start", "--no-browser")
        app.open_board()
        return 0
    import webview
    app.window = make_window(app, webview)
    app.window.events.closing += app.on_closing
    tray = app.make_tray()
    if sys.platform == "win32":
        threading.Thread(target=tray.run, name="tray", daemon=True).start()
    else:
        tray.run_detached()  # shares the GUI loop (Cocoa / GTK)
    storage = settings.data_dir() / "desktop-webview"
    storage.mkdir(parents=True, exist_ok=True)
    # WinForms (Windows) takes only an .ico; GTK/Cocoa take a png
    icon = asset_path("heronry.ico" if sys.platform == "win32" else "heronry-256.png")
    webview.start(app.boot, private_mode=False, storage_path=str(storage), icon=icon)
    return 0
