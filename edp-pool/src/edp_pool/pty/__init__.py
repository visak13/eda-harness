"""One PTY abstraction for every OS (strategyll-2d9045f5a0, S2 s-b7ec13d748).

Only this package imports ``winpty`` or ``ptyprocess``; everything else uses :func:`spawn_pty` and the
:class:`Pty` protocol.

* Windows: pywinpty (ConPTY) in the pool's own process, as the fleet has always run. ConPTY delivers no
  SIGHUP, so seats outlive a pool that is killed without a tree kill.
* POSIX: a per-seat sidecar, ``python -m edp_pool.pty.host``, owns the PTY master. The pool never forks
  (it is a threaded HTTP server, and on macOS ``pty.fork`` is unsafe next to urllib), and the last close
  of a master hangs up the seat, so a master held by the pool would kill every seat when the pool exits.

``Pty`` exposes no kill: every stop is ``edp_contracts.proc.kill_tree`` on the ProcId recorded at spawn.
"""
from __future__ import annotations

import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

__all__ = ["Pty", "PtyClosed", "harness_env", "inject", "single_line", "spawn_pty"]


class PtyClosed(Exception):
    """The PTY reached EOF: the child exited and its output is drained."""


class Pty(Protocol):
    pid: int              # the harness child itself (the seat's identity), never a host/launcher

    def read(self, n: int = 4096) -> str: ...          # '' when nothing is ready; PtyClosed at EOF
    def write(self, text: str) -> int: ...
    def resize(self, rows: int, cols: int) -> None: ...
    def alive(self) -> bool: ...
    def exit_code(self) -> int | None: ...             # -signum for a signal death
    def close(self) -> None: ...                       # releases handles only; never kills
    def host_pid(self) -> int | None: ...              # the POSIX sidecar's pid (None on Windows)


def spawn_pty(argv: Sequence[str], *, cwd: str | None, env: Mapping[str, str], rows: int = 50, cols: int = 200,
              run_dir: str | Path | None = None, name: str | None = None) -> Pty:
    """Start `argv` at its final size in a new PTY. `run_dir`/`name` place the POSIX host's control socket
    (default: the settings run dir, named after the seat); Windows ignores them."""
    if sys.platform == "win32":
        from ._win import WinPty
        return WinPty.spawn(list(argv), cwd, dict(env), rows, cols)
    from ._posix import HostedPty
    return HostedPty.spawn(list(argv), cwd, dict(env), rows, cols, run_dir=run_dir, name=name)


def harness_env(env: Mapping[str, str], rows: int, cols: int) -> dict[str, str]:
    """The terminal environment every harness gets on both OSes (1/2 §4). Pre-set values win."""
    out = dict(env)
    out.setdefault("TERM", "xterm-256color")
    out.setdefault("COLORTERM", "truecolor")
    out["COLUMNS"] = str(cols)
    out["LINES"] = str(rows)
    if sys.platform != "win32" and not (out.get("LC_ALL") or out.get("LANG")):
        # C.UTF-8 exists on macOS only in recent releases; en_US.UTF-8 is always there
        out["LANG"] = "en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8"
    return out


def single_line(text: str) -> str:
    """The wake contract: one line, so a stray newline never submits half a wake."""
    return " ".join(text.splitlines())


def inject(pty: Pty, text: str, submit_delay_ms: float) -> None:
    """Type one line into the seat and press Enter after `submit_delay_ms` (claude's paste detection
    needs the pause). The same route on both OSes; monitor-mode consoles on Windows use console_input."""
    pty.write(single_line(text))
    time.sleep(max(0.0, submit_delay_ms) / 1000.0)
    pty.write("\r")
