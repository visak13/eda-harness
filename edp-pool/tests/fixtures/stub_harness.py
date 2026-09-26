"""A stand-in harness for PTY and pool tests (S2 s-b7ec13d748): behaves like a seat shell on every OS.

Protocol (one line per command, the PTY's Enter submits it):

* on start: ``GRANDCHILD:<pid>`` (a sleeping child, so a tree kill has a descendant to reach), then the
  ready marker ``❯`` that the pool waits for;
* ``resize?``: ``SIZE:<cols>x<rows>`` from the terminal it sits in (also printed on SIGWINCH on POSIX);
* ``exit <n>``: ``BYE``, then exit with code n;
* ``--version`` on the command line: one version line and exit 0 (the pool's version probe);
* anything else: ``ECHO:<line>``.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time


def _say(text: str) -> None:
    sys.stdout.write(text + "\r\n")
    sys.stdout.flush()


def _size() -> str:
    try:
        sz = os.get_terminal_size(sys.stdout.fileno())
    except OSError:
        sz = shutil.get_terminal_size()
    return f"SIZE:{sz.columns}x{sz.lines}"


def main() -> int:
    if "--version" in sys.argv[1:]:
        print("0.0.0 (edp stub harness)")  # the pool's pre-spawn version probe
        return 0
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if hasattr(signal, "SIGWINCH"):
        signal.signal(signal.SIGWINCH, lambda *_: _say(_size()))
    _say(f"GRANDCHILD:{child.pid}")
    _say("❯ ready")
    while True:
        try:
            line = input().strip()
        except EOFError:
            return 0
        if not line:
            continue
        if line == "resize?":
            _say(_size())
        elif line.startswith("exit"):
            parts = line.split()
            code = int(parts[1]) if len(parts) > 1 else 0
            _say("BYE")
            time.sleep(0.5)  # ConPTY drops output a process writes just before it exits
            child.kill()
            return code
        else:
            _say(f"ECHO:{line}")


if __name__ == "__main__":
    raise SystemExit(main())
