"""Heronry Desktop: the board in a native window plus a tray / menu-bar icon (design-e963c656f5 §4.9, S8).

`heronry gui`, and the bundle's app with no argument, land here. The desktop is a CLIENT of the one launcher:
every tray and window-menu action calls the same `edp8.cli` command the terminal runs (start, stop, restart,
status, update), so there is one code path (strategyhl-5af811e7bd §4). The GUI process owns no service:
closing the window hides it, Quit leaves the services running unless "Stop services on quit" is set.

* **First run** (no config.toml yet): `heronry init` with the harnesses found on this machine (claude and/or
  codex, else claude), then the window opens /ui/setup with a one-time sign-in code (S6's wizard picks the
  harnesses for real). Later runs open /ui/join with a fresh one-time code, so the window is signed in.
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
import sys
import threading
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
    # a source checkout: the package lives at <v8>/src/edp8 (read-only brand art, never state)
    roots = [r for r in (settings.home(), Path(__file__).resolve().parent.parent.parent) if r is not None]
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


# ------------------------------------------------------------------------------------------ the app

class Desktop:
    """Window + tray state and the actions both of them offer (one set, so the tray is never the only way in)."""

    def __init__(self, product: str, *, notify: Callable[[str, str], None] | None = None) -> None:
        self.product = product
        self.window: Any = None
        self.tray: Any = None
        self.quitting = False
        self.prefs = load_prefs()
        self._notify = notify

    # ---- actions (tray menu, window menu) ------------------------------------------------------
    def show(self, message: str, title: str | None = None) -> None:
        title = title or self.product
        if self._notify:
            self._notify(title, message)
        elif self.window is not None:
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

    def update(self) -> None:
        """Check GitHub Releases; on a newer release ask, then `heronry update` (the §4.10 apply)."""
        from . import updater
        title = f"{self.product}: update"
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
               "Install it now? Seats are drained and the services stop while it installs, then start again.")
        if self.window is not None and not self.window.create_confirmation_dialog(title, ask):
            return
        self._verb("update")

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
                ("Stop services", self.stop), ("Restart services", self.restart), ("Check for update", self.update)]

    # ---- window --------------------------------------------------------------------------------
    def on_closing(self) -> bool:
        """Closing the window hides it (the tray and services stay); Quit really closes."""
        if self.quitting or self.tray is None:
            return True
        self.window.hide()
        return False

    def boot(self) -> None:
        """Runs beside the GUI loop: bring the services up (showing progress on the splash), then the board."""
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
        entries = [item(label, fn, default=(label == "Open board")) for label, fn in self.actions()]
        entries += [pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Stop services on quit", lambda _i, _t: self.toggle_stop_on_quit(),
                                     checked=lambda _t: self.stop_on_quit),
                    pystray.MenuItem("Quit", lambda _i, _t: self.quit())]
        image = Image.open(io.BytesIO(asset_bytes("heronry-64.png")))
        self.tray = pystray.Icon("heronry", image, self.product, pystray.Menu(*entries))
        return self.tray


def main(argv: list[str] | None = None) -> int:
    from .brand import DESKTOP_APP_NAME
    app = Desktop(DESKTOP_APP_NAME)
    if not ensure_webview2(DESKTOP_APP_NAME):
        # no window possible: the services still come up and the board opens in the browser
        if not initialized():
            first_run_init()
        run_cli("start", "--no-browser")
        app.open_board()
        return 0
    import webview
    app.window = webview.create_window(DESKTOP_APP_NAME, html=splash_html(DESKTOP_APP_NAME), width=1280, height=820,
                                       min_size=(720, 480), background_color="#211B18", menu=app.menu())
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
