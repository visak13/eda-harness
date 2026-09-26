"""POSIX PTY: a client of the per-seat ``edp_pool.pty.host`` sidecar (1/2 §3).

The pool never forks and never holds a PTY master. It starts the host in its own session
(``start_new_session=True``), hands it the harness spec on stdin (so the seat's env, token included, is
never on an argv), then talks to it over the host's AF_UNIX socket. :meth:`HostedPty.attach` reconnects
to a live host after a pool restart.
"""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import PtyClosed

_SUN_PATH_MAX = 100  # sockaddr_un.sun_path is 104 bytes on macOS, 108 on Linux; keep a margin


def sock_path(run_dir: str | Path | None, name: str | None) -> str:
    """Where the host for seat `name` listens. Short by construction (a hash of the name), and moved to
    /tmp when the run dir would push the path past the AF_UNIX limit (long macOS temp dirs)."""
    stem = "pty-" + hashlib.sha1((name or str(time.time_ns())).encode("utf-8")).hexdigest()[:12]
    if run_dir is None:
        from edp_contracts import settings
        run_dir = settings.run_dir()
    d = Path(run_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{stem}.sock"
    if len(str(p)) > _SUN_PATH_MAX:
        p = Path("/tmp") / f"edp-{stem}.sock"
    return str(p)


class HostedPty:
    pid: int

    def __init__(self) -> None:
        self._sock_path = ""
        self._stream: socket.socket | None = None
        self._buf = b""
        self._pending = ""
        self._exit: int | None = None
        self._eof = False
        self._host: subprocess.Popen | None = None
        self._host_pid: int | None = None

    # ------------------------------------------------------------------ lifecycle
    @classmethod
    def spawn(cls, argv: list[str], cwd: str | None, env: dict[str, str], rows: int, cols: int, *,
              run_dir: str | Path | None = None, name: str | None = None, timeout: float = 15.0) -> HostedPty:
        path = sock_path(run_dir, name)
        log_path = Path(path).with_suffix(".host.log")
        spec = {"argv": argv, "cwd": cwd, "env": env, "rows": rows, "cols": cols}
        with open(log_path, "ab") as log:
            host = subprocess.Popen([sys.executable, "-m", "edp_pool.pty.host", "--sock", path],
                                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log,
                                    start_new_session=True, close_fds=True)
        assert host.stdin is not None
        host.stdin.write(json.dumps(spec).encode("utf-8"))
        host.stdin.close()
        try:
            return cls.attach(path, timeout=timeout, _host=host)
        except Exception:
            if host.poll() is None:
                from edp_contracts.proc import kill_popen
                kill_popen(host, grace=1.0)
            raise

    @classmethod
    def attach(cls, path: str, *, timeout: float = 15.0, _host: subprocess.Popen | None = None) -> HostedPty:
        """Connect to a running host (fresh spawn, or a seat that outlived the previous pool)."""
        self = cls()
        self._sock_path, self._host = path, _host
        deadline = time.monotonic() + timeout
        st: dict | None = None
        last: Exception | None = None
        while time.monotonic() < deadline:
            if _host is not None and _host.poll() is not None:
                raise RuntimeError(f"pty host exited early (rc={_host.returncode}); see {Path(path).with_suffix('.host.log')}")
            try:
                st = self._request({"op": "status"})
                break
            except OSError as e:
                last = e
                time.sleep(0.05)
        if st is None:
            raise TimeoutError(f"pty host at {path} did not answer within {timeout}s: {last!r}")
        self.pid = int(st["pid"])
        self._host_pid = int(st["host_pid"])
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect(path)
        s.sendall(b'{"op": "attach"}\n')
        s.settimeout(0.1)
        self._stream = s
        return self

    # ------------------------------------------------------------------ control requests
    def _request(self, req: dict) -> dict:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(5.0)
            s.connect(self._sock_path)
            s.sendall((json.dumps(req) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    raise ConnectionError("pty host closed the connection")
                buf += chunk
        return json.loads(buf.split(b"\n", 1)[0])

    # ------------------------------------------------------------------ Pty protocol
    def read(self, n: int = 4096) -> str:
        if not self._pending and not self._eof:
            self._fill()
        if self._pending:
            out, self._pending = self._pending[:n], self._pending[n:]
            return out
        if self._eof:
            raise PtyClosed(f"pty host stream ended (exit {self._exit})")
        return ""

    def _fill(self) -> None:
        assert self._stream is not None
        try:
            chunk = self._stream.recv(65536)
        except TimeoutError:
            return
        except OSError:
            chunk = b""
        if not chunk:
            self._eof = True
            return
        self._buf += chunk
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            msg = json.loads(line)
            if "out" in msg:
                self._pending += msg["out"]
            if "exit" in msg:
                self._exit = msg["exit"]
                self._eof = True

    def write(self, text: str) -> int:
        r = self._request({"op": "write", "data": text})
        if not r.get("ok"):
            raise OSError(r.get("error"))
        return int(r.get("n") or 0)

    def resize(self, rows: int, cols: int) -> None:
        r = self._request({"op": "resize", "rows": rows, "cols": cols})
        if not r.get("ok"):
            raise OSError(r.get("error"))

    def alive(self) -> bool:
        if self._exit is not None:
            return False
        if self._host is not None:
            self._host.poll()  # reap the host once it exits, so it never lingers as a zombie
        try:
            return bool(self._request({"op": "status"}).get("alive"))
        except (OSError, ValueError):
            return False

    def exit_code(self) -> int | None:
        if self._exit is not None:
            return self._exit
        try:
            st = self._request({"op": "status"})
        except (OSError, ValueError):
            return None
        return None if st.get("alive") else st.get("exit")

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            finally:
                self._stream = None
        if self._host is not None:
            self._host.poll()

    def host_pid(self) -> int | None:
        return self._host_pid
