"""S11 (s-9277bcebc9) desktop-shell probe: the real WebView2 window, driven by real mouse events (CDP
Input.dispatchMouseEvent), against a throwaway local page. It touches no board, no fleet and no services: a private
http.server on a spare loopback port, a private WebView2 storage folder, and a tray icon that is removed on exit.

Run it with the INSTALLED app's Python (it ships pywebview, pythonnet and pystray) and the worktree's edp8 on the path:

    heronry.exe -c "import sys; sys.path.insert(0, r'<repo>\\v8\\src'); import runpy; runpy.run_path(r'<repo>\\v8\\scripts\\probe_desktop_shell.py', run_name='__main__')" -- --out <dir> [--select off] [--toast-shot <png>] [--assets <desktop_assets dir>] [--boot-order]

`--select off` reproduces the OLD window (pywebview's default text_select=False, desktop.py before S11) to show the
cause; the default builds the window through edp8.desktop.make_window (the fix). `--boot-order` attaches the navigation
guard the way Desktop.boot() does: first thing in the `webview.start(func)` thread, before any page has loaded (pywebview
starts func before the native window exists), then checks that a foreign window.open and a top-level data: page are
stopped. Prints one JSON object.
"""

from __future__ import annotations

import http.server
import json
import socketserver
import sys
import threading
import time
from pathlib import Path

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>S11 probe</title></head>
<body style="font:28px system-ui;margin:40px">
<p id="msg">Select this sentence to quote it from the desktop window.</p>
<p><a id="ext" href="https://example.com/ext-blank" target="_blank">external, new window</a></p>
<p><a id="ext2" href="https://example.com/ext-plain">external, same window</a></p>
<p><a id="inapp" href="/second.html" target="_blank">in-app, new window</a></p>
<script>
window.__sel = '';
document.addEventListener('mouseup', function () { setTimeout(function () { window.__sel = String(getSelection()); }, 0); });
</script></body></html>"""


class Quiet(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = (PAGE if self.path in ("/", "/index.html") else "<!doctype html><title>second</title><p id=s>second page</p>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def cdp(window, method: str, params: dict, timeout_s: float = 10.0) -> str:
    """One DevTools-protocol call on the window's own WebView2 (on its UI thread)."""
    from threading import Semaphore

    from System import Action, Func, Object  # type: ignore[import-not-found]
    from System.Threading.Tasks import Task  # type: ignore[import-not-found]
    control = window.native.webview
    done, box = Semaphore(0), []

    def finished(task):
        box.append(str(task.Exception) if task.IsFaulted else task.Result)
        done.release()
    control.Invoke(Func[Object](lambda: control.CoreWebView2.CallDevToolsProtocolMethodAsync(
        method, json.dumps(params)).ContinueWith(Action[Task](finished))))
    if not done.acquire(timeout=timeout_s):
        raise RuntimeError(f"{method}: no answer in {timeout_s}s")
    return box[0]


def mouse(window, kind: str, x: float, y: float, **extra) -> None:
    cdp(window, "Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": extra.pop("button", "none"), **extra})


def drag(window, x1: float, y1: float, x2: float) -> None:
    mouse(window, "mouseMoved", x1, y1)
    mouse(window, "mousePressed", x1, y1, button="left", clickCount=1, buttons=1)
    for step in range(1, 9):
        mouse(window, "mouseMoved", x1 + (x2 - x1) * step / 8, y1, button="left", buttons=1)
    mouse(window, "mouseReleased", x2, y1, button="left", clickCount=1)


def click(window, x: float, y: float) -> None:
    mouse(window, "mouseMoved", x, y)
    mouse(window, "mousePressed", x, y, button="left", clickCount=1, buttons=1)
    mouse(window, "mouseReleased", x, y, button="left", clickCount=1)


def rect(window, sel: str) -> tuple[float, float, float, float]:
    r = window.evaluate_js(f"(function(){{var r=document.querySelector('{sel}').getBoundingClientRect();return [r.left,r.top,r.width,r.height]}})()")
    return tuple(float(v) for v in r)


def wait_for(fn, timeout_s: float = 10.0, every: float = 0.2):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(every)
    return None


def main(argv: list[str]) -> int:
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path.cwd()
    select_off = "--select" in argv and argv[argv.index("--select") + 1] == "off"
    boot_order = "--boot-order" in argv
    toast_shot = Path(argv[argv.index("--toast-shot") + 1]) if "--toast-shot" in argv else None
    out.mkdir(parents=True, exist_ok=True)
    import webbrowser

    import webview

    from edp8 import desktop

    server = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{port}"
    opened: list[str] = []
    webbrowser.open = lambda url, *a, **k: opened.append(url) or True  # recorded, never launched
    desktop.board_origin = lambda: origin
    if "--assets" in argv:  # a source checkout has no built desktop_assets; borrow the installed app's (read only)
        assets = Path(argv[argv.index("--assets") + 1])
        desktop._asset = lambda name: assets / name
    result: dict = {"mode": "old window (text_select default)" if select_off else "edp8.desktop.make_window" + (" + guard attached in boot order" if boot_order else ""), "origin": origin}

    app = desktop.Desktop("S11 probe")
    if select_off:
        window = webview.create_window("S11 probe", url=origin + "/", width=900, height=600)
    else:
        window = desktop.make_window(app, webview)
    app.window = window

    def step(msg: str) -> None:
        with (out / "progress.txt").open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}" + chr(10))

    def run() -> None:
        try:
            step("run() started")
            if boot_order:
                step("ensure_navigation_guard ...")
                result["external_rule_before"] = webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"]
                t0 = time.monotonic()
                result["guard_attached_at_boot"] = app.ensure_navigation_guard(20)
                result["guard_wait_s"] = round(time.monotonic() - t0, 2)
                result["guard_error"] = app.guard_error
                step("guard " + json.dumps(result))
                result["external_rule_after"] = webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"]
                app.splash_open = False  # what _boot does right before it loads the board
            window.events.loaded.wait(20)
            step("loaded")
            if not select_off:
                window.load_url(origin + "/")
                time.sleep(0.3)
                window.events.loaded.wait(20)
            wait_for(lambda: (window.get_current_url() or "").startswith(origin))
            time.sleep(0.8)
            result["bridge_notify_type"] = window.evaluate_js("typeof (window.pywebview && window.pywebview.api && window.pywebview.api.notify)")
            result["body_user_select"] = window.evaluate_js("getComputedStyle(document.body).userSelect")
            x, y, w, h = rect(window, "#msg")
            drag(window, x + 4, y + h / 2, x + w - 4)
            time.sleep(0.4)
            result["drag_selection"] = window.evaluate_js("window.__sel")
            result["drag_selection_len"] = len(result["drag_selection"] or "")
            if not select_off:
                if not boot_order:
                    app.attach_navigation_guard()
                time.sleep(0.5)
                for name in ("ext", "ext2"):
                    before = len(opened)
                    x, y, w, h = rect(window, "#" + name)
                    click(window, x + w / 2, y + h / 2)
                    time.sleep(1.2)
                    result[f"link_{name}"] = {"system_browser": opened[before:], "window_url_still_board": str(window.evaluate_js("location.href")).startswith(origin)}
                x, y, w, h = rect(window, "#inapp")
                click(window, x + w / 2, y + h / 2)
                result["link_inapp_loaded_in_window"] = bool(wait_for(lambda: str(window.evaluate_js("location.href")).endswith("/second.html")))
                result["link_inapp_system_browser"] = [u for u in opened if u.startswith(origin)]
                if boot_order:
                    before = len(opened)
                    step("window.open")
                    window.run_js("window.open('https://example.com/window-open')")
                    time.sleep(1.5)
                    result["window_open_foreign"] = {"system_browser": opened[before:], "window_url_still_board": str(window.evaluate_js("location.href")).startswith(origin)}
                    step("data nav")
                    window.run_js("location.href = 'data:text/html,<title>hostile</title><b>hostile</b>'")
                    time.sleep(1.5)
                    result["data_page_navigation"] = {"window_url_still_board": str(window.evaluate_js("location.href")).startswith(origin)}
                tray = app.make_tray()
                threading.Thread(target=tray.run, daemon=True).start()
                wait_for(lambda: getattr(tray, "visible", False), 8)
                time.sleep(0.8)
                window.load_url(origin + "/")
                wait_for(lambda: str(window.evaluate_js("location.href")).rstrip("/") == origin)
                time.sleep(0.8)
                window.evaluate_js("window.pywebview.api.notify('S11 probe', 'Toast raised from the page through the bridge.').then(function(r){window.__notify=JSON.stringify(r)})")
                result["bridge_notify_result"] = wait_for(lambda: window.evaluate_js("window.__notify"))
                if toast_shot is not None:
                    time.sleep(1.2)
                    result["toast_shot"] = region_shot(toast_shot)
                time.sleep(2.5)
                with_suppress(tray.stop)
        except Exception as e:  # noqa: BLE001 — recorded, the probe still ends
            result["error"] = f"{type(e).__name__}: {e}"
        finally:
            (out / f"probe-{'old' if select_off else 'boot-order' if boot_order else 'fixed'}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
            print(json.dumps(result, indent=1))
            window.destroy()

    storage = out / "webview-storage"
    storage.mkdir(exist_ok=True)
    webview.start(run, private_mode=False, storage_path=str(storage))
    server.shutdown()
    return 0 if "error" not in result else 1


def with_suppress(fn) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001
        pass


def region_shot(path: Path) -> str:
    """The bottom-right corner of the primary screen (where a toast appears), 640x240 px, nothing else."""
    import ctypes

    from System.Drawing import Bitmap, Graphics, Imaging, Point, Size  # type: ignore[import-not-found]
    w, h = 640, 240
    sw, sh = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
    bmp = Bitmap(w, h)
    g = Graphics.FromImage(bmp)
    g.CopyFromScreen(Point(sw - w, sh - h - 48), Point(0, 0), Size(w, h))
    g.Dispose()
    bmp.Save(str(path), Imaging.ImageFormat.Png)
    return str(path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
