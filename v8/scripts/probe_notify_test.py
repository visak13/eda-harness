"""S11 evidence: `heronry notify-test` run through the real CLI entry point inside the installed app's Python; the log
records the exit code and the line it printed. No screen is captured (the visual of the same pystray toast is in
probe_desktop_shell.py --toast-shot).

    heronry.exe -c "import sys, runpy; sys.path.insert(0, r'<repo>\\v8\\src'); sys.argv=['probe','--out',r'<dir>','--assets',r'<app>\\app_packages\\edp8\\desktop_assets']; runpy.run_path(r'<repo>\\v8\\scripts\\probe_notify_test.py', run_name='__main__')"
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    out = Path(argv[argv.index("--out") + 1])
    assets = Path(argv[argv.index("--assets") + 1])
    out.mkdir(parents=True, exist_ok=True)
    from edp8 import cli, desktop
    desktop._asset = lambda name: assets / name
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["notify-test", "--message", "Raised by `heronry notify-test` from the command line.", "--wait", "7"])
    text = buf.getvalue().strip()
    print(f"exit {rc}: {text}")
    (out / "notify-test.log").write_text(f"exit {rc}\n{text}\n", encoding="utf-8")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
