"""Visible-console launcher — `monitor` spawn mode.

Opens a real Windows console window (CREATE_NEW_CONSOLE) so the operator
WATCHES claude's native, correctly-rendered TUI. The agent runs
autonomously (`--dangerously-skip-permissions` via build_argv) with the
role activator passed as the initial-prompt arg — claude submits it when
its session is ready (this is claude's own prompt handling, not a
PTY-keystroke race). No drain log: the window IS the output (use headless
mode for a forensic per-session log).

Restored 2026-05-31: the operator wants VISIBLE shells. The headless
PtyLaunch route removed the windows — and a headless autonomous shell
then hangs on its first permission prompt with no window/human to approve
it. Visible + skip-permissions + the PreToolUse guard hook is the right
mix: watchable, autonomous, and still protected from stack-nuking kills.
"""

import subprocess

from .proctree import kill_process_tree


class ConsoleLaunch:
    def __init__(self, argv: list[str], env: dict, cwd: str | None):
        self.argv = argv
        self.env = env
        self.cwd = cwd
        self._proc: subprocess.Popen | None = None

    def spawn(self) -> None:
        self._proc = subprocess.Popen(
            self.argv,
            cwd=self.cwd,
            env=self.env,
            # A real, visible, separate console window — claude's TUI
            # renders natively there.
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> int | None:
        """OS pid (the Popen child) — for the pool's liveness fingerprint
        so a still-running shell is re-established as 'alive' after a pool
        restart, not stranded 'unknown'."""
        return self._proc.pid if self._proc is not None else None

    def terminate(self) -> None:
        # Close the WHOLE subtree this shell opened (MCP servers + rx
        # drivers), not just the root pid — otherwise its python children
        # orphan and accumulate on every close/reap. Kill descendants first
        # (snapshot before the root dies), then the root via its own handle
        # (keeps Popen.poll() state consistent).
        if self._proc is None or self._proc.poll() is not None:
            return
        try:
            kill_process_tree(self._proc.pid)
        except Exception:
            pass
        try:
            self._proc.terminate()
        except Exception:
            pass
