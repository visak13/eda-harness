"""POSIX PTY host sidecar: ``python -m edp_pool.pty.host --sock <path>`` (spec JSON on stdin).

One per seat (strategyll-2d9045f5a0 §3). It forks the harness into a new PTY while it is still
single-threaded, owns the master for the seat's whole life, and serves a local AF_UNIX socket (mode 0600)
with newline-delimited JSON:

* ``{"op": "attach"}``: this connection becomes an output stream. It first gets the recent output
  (a 64 KB replay), then ``{"out": "<text>"}`` per read, then ``{"exit": <code>}`` when the child ends.
* ``{"op": "write", "data": "<text>"}``, ``{"op": "resize", "rows": r, "cols": c}``,
  ``{"op": "status"}``: one JSON reply each.

The master is read even when no client is attached (a full PTY buffer would block the seat), so a pool
restart loses nothing but the output between the old pool's death and the new attach, beyond the replay.
The host exits when the child's PTY reaches EOF. It never kills: stops are ``kill_tree`` on the child.
"""
from __future__ import annotations

import argparse
import json
import os
import selectors
import socket
import sys
from collections import deque

_REPLAY_CHARS = 64 * 1024


def _send(conn: socket.socket, msg: dict) -> bool:
    try:
        conn.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="edp_pool.pty.host")
    ap.add_argument("--sock", required=True)
    a = ap.parse_args(argv)
    spec = json.loads(sys.stdin.read())
    sys.stdin.close()

    import ptyprocess  # only edp_pool.pty imports ptyprocess

    # Fork FIRST, while this process has exactly one thread (1/2 §3 reason 2).
    child = ptyprocess.PtyProcessUnicode.spawn(
        spec["argv"], cwd=spec.get("cwd"), env=spec.get("env"),
        dimensions=(int(spec.get("rows", 50)), int(spec.get("cols", 200))), echo=False)

    path = a.sock
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        srv.bind(path)
    finally:
        os.umask(old)
    os.chmod(path, 0o600)
    srv.listen(16)

    sel = selectors.DefaultSelector()
    sel.register(srv, selectors.EVENT_READ, "srv")
    sel.register(child.fd, selectors.EVENT_READ, "pty")
    bufs: dict[socket.socket, bytes] = {}
    streams: set[socket.socket] = set()
    replay: deque[str] = deque()
    replay_len = 0
    exit_code: int | None = None

    def drop(conn: socket.socket) -> None:
        streams.discard(conn)
        bufs.pop(conn, None)
        try:
            sel.unregister(conn)
        except (KeyError, ValueError):
            pass
        conn.close()

    def status() -> dict:
        alive = exit_code is None and child.isalive()
        return {"ok": True, "pid": child.pid, "host_pid": os.getpid(), "alive": alive,
                "exit": None if alive else _code(child)}

    def handle(conn: socket.socket, req: dict) -> None:
        op = req.get("op")
        if op == "attach":
            streams.add(conn)
            if replay:
                _send(conn, {"out": "".join(replay)})
            return
        try:
            if op == "write":
                n = child.write(str(req.get("data", "")))
                _send(conn, {"ok": True, "n": n})
            elif op == "resize":
                child.setwinsize(int(req["rows"]), int(req["cols"]))
                _send(conn, {"ok": True})
            elif op == "status":
                _send(conn, status())
            else:
                _send(conn, {"ok": False, "error": f"unknown op {op!r}"})
        except (OSError, ValueError, KeyError) as e:
            _send(conn, {"ok": False, "error": repr(e)})

    try:
        while True:
            for key, _ in sel.select(timeout=1.0):
                if key.data == "srv":
                    conn, _addr = srv.accept()
                    conn.settimeout(5.0)
                    bufs[conn] = b""
                    sel.register(conn, selectors.EVENT_READ, "conn")
                elif key.data == "pty":
                    try:
                        text = child.read(4096)
                    except EOFError:
                        sel.unregister(child.fd)
                        child.wait()
                        exit_code = _code(child)
                        continue
                    replay.append(text)
                    replay_len += len(text)
                    while replay_len > _REPLAY_CHARS and len(replay) > 1:
                        replay_len -= len(replay.popleft())
                    for s in list(streams):
                        if not _send(s, {"out": text}):
                            drop(s)
                else:
                    conn = key.fileobj  # type: ignore[assignment]
                    try:
                        data = conn.recv(65536)
                    except OSError:
                        data = b""
                    if not data:
                        drop(conn)
                        continue
                    bufs[conn] = bufs.get(conn, b"") + data
                    while b"\n" in bufs.get(conn, b""):
                        line, rest = bufs[conn].split(b"\n", 1)
                        bufs[conn] = rest
                        try:
                            handle(conn, json.loads(line))
                        except json.JSONDecodeError:
                            _send(conn, {"ok": False, "error": "bad json"})
            if exit_code is not None:
                for s in list(streams):
                    _send(s, {"exit": exit_code})
                return 0
    finally:
        for c in list(bufs):
            drop(c)
        srv.close()
        try:
            os.unlink(path)
        except OSError:
            pass


def _code(child) -> int | None:
    if child.signalstatus is not None:
        return -int(child.signalstatus)
    return child.exitstatus


if __name__ == "__main__":
    raise SystemExit(main())
