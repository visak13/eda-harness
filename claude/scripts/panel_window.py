"""Floating control-panel window — the pool panel as an ALWAYS-ON-TOP
overlay (the Firefox picture-in-picture shape the operator asked for,
2026-07-12), so pause/play/approvals stay one click away over any app.

pywebview + the Windows WebView2 runtime (present on Win11 by default).
Run via `panel-window.bat` (which supplies pywebview through uv without
touching the project's locked deps).

Fallback if WebView2/pywebview misbehaves on this host: an Edge app window
(not always-on-top, but chromeless):
    msedge --app=http://127.0.0.1:9301/panel
"""

import argparse


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:9301/panel")
    ap.add_argument("--width", type=int, default=560)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    import webview   # deferred: the bat supplies it via `uv run --with`

    webview.create_window(
        "EDP control panel",
        args.url,
        width=args.width,
        height=args.height,
        on_top=True,          # the whole point: overlays every other app
        easy_drag=False,
    )
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
