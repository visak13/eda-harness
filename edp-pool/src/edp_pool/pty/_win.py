"""Windows PTY: pywinpty's ConPTY process, in the pool's own process (1/2 §2)."""
from __future__ import annotations

from . import PtyClosed


class WinPty:
    pid: int

    @classmethod
    def spawn(cls, argv: list[str], cwd: str | None, env: dict[str, str], rows: int, cols: int) -> WinPty:
        from winpty import PtyProcess  # only this package imports winpty

        self = cls()
        self._p = PtyProcess.spawn(argv, cwd=cwd, env=env, dimensions=(rows, cols))
        self.pid = self._p.pid
        return self

    def read(self, n: int = 4096) -> str:
        try:
            data = self._p.read(n)
        except EOFError as e:
            raise PtyClosed(str(e)) from e
        return data if isinstance(data, str) else data.decode("utf-8", errors="replace")

    def write(self, text: str) -> int:
        return self._p.write(text)

    def resize(self, rows: int, cols: int) -> None:
        self._p.setwinsize(rows, cols)

    def alive(self) -> bool:
        return bool(self._p.isalive())

    def exit_code(self) -> int | None:
        return None if self._p.isalive() else self._p.exitstatus

    def close(self) -> None:
        # pywinpty has no handle-only close: its close() terminates the child. Stopping is kill_tree's job
        # (edp_contracts.proc), which runs before this, so there is nothing left to release here.
        return None

    def host_pid(self) -> int | None:
        return None
