"""edp8.codex_seat monitor mode = the native codex TUI (owner ruling m-0e7b8fdd7f, steer m-f4177acf97).

The runner and the TUI are two clients of one app-server on an authenticated loopback websocket:
  * WsClient speaks RFC 6455 text frames, sends the capability token as a bearer, fails on a 401
  * the listener's token lives in an owner-only file (path on argv, value never) and in env for the TUI
  * the app-server and the model's shell never receive the ws token
  * the TUI argv names the token's env VAR, never its value, and joins the seat's own thread
  * run_tui starts the TUI only after the thread has a landed input, and the seat ends with the TUI
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from edp8.codex_seat import rpc as rpc_mod
from edp8.codex_seat import run as run_mod
from edp8.codex_seat import seat as seat_mod
from edp8.codex_seat.rpc import WS_TOKEN_ENV, AppServer, redactor
from edp8.codex_seat.ws import WsClient

V8 = Path(__file__).resolve().parents[1]
FAKE = Path(__file__).resolve().parent / "codex_seat" / "fake_app_server.py"
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class FakeWsServer:
    """One-connection loopback websocket server: bearer check, then echoes every text message back."""

    def __init__(self, token: str):
        self.token = token
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._conn, args=(c,), daemon=True).start()

    def _conn(self, c):
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += c.recv(4096)
        head = buf.split(b"\r\n\r\n")[0].decode()
        hdr = {k.strip().lower(): v.strip() for k, v in (ln.split(":", 1) for ln in head.split("\r\n")[1:] if ":" in ln)}
        if hdr.get("authorization") != f"Bearer {self.token}":
            c.sendall(b"HTTP/1.1 401 Unauthorized\r\ncontent-length: 0\r\n\r\n")
            c.close()
            return
        acc = base64.b64encode(hashlib.sha1((hdr["sec-websocket-key"] + GUID).encode()).digest()).decode()
        c.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Accept: {acc}\r\n\r\n".encode())
        rest = b""

        def exact(n):
            nonlocal rest
            while len(rest) < n:
                d = c.recv(65536)
                if not d:
                    raise ConnectionError
                rest += d
            out, rest = rest[:n], rest[n:]
            return out
        try:
            while True:
                b1, b2 = exact(2)
                n = b2 & 0x7F
                if n == 126:
                    n = struct.unpack(">H", exact(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", exact(8))[0]
                mask = exact(4)
                data = bytes(x ^ mask[i % 4] for i, x in enumerate(exact(n)))
                if b1 & 0x0F == 0x8:
                    return
                n = len(data)
                head = bytes([0x81, n]) if n < 126 else (bytes([0x81, 126]) + struct.pack(">H", n) if n < 65536
                                                         else bytes([0x81, 127]) + struct.pack(">Q", n))
                c.sendall(head + data)  # server frames are unmasked
        except (ConnectionError, OSError):
            return

    def close(self):
        self.sock.close()


def test_ws_client_refuses_a_listener_that_rejects_its_token():
    srv = FakeWsServer("right")
    try:
        with pytest.raises(ConnectionRefusedError, match="401"):
            WsClient("127.0.0.1", srv.port, "wrong")
        with pytest.raises(ConnectionRefusedError):
            WsClient("127.0.0.1", srv.port, None)
    finally:
        srv.close()


@pytest.mark.parametrize("size", [5, 300, 70_000])
def test_ws_client_round_trips_text_of_every_frame_length(size):
    srv = FakeWsServer("tok")
    try:
        c = WsClient("127.0.0.1", srv.port, "tok")
        msg = json.dumps({"jsonrpc": "2.0", "method": "x", "params": {"t": "é" + "a" * size}})
        c.send_text(msg)
        assert c.recv_text() == msg
        c.close()
    finally:
        srv.close()


def test_ws_listen_args_keep_the_token_off_argv_and_in_an_owner_only_file(tmp_path):
    a = AppServer(["codex", "app-server"], cwd=str(tmp_path), env={"EDP8_TOKEN": "seat-secret-123"},
                  log_path=tmp_path / "m.jsonl", ws=True)
    args = a._ws_listen_args()
    try:
        assert args[:2] == ["--listen", a.ws_url] and a.ws_url.startswith("ws://127.0.0.1:")
        assert args[2:5] == ["--ws-auth", "capability-token", "--ws-token-file"]
        tok_file = Path(args[5])
        assert tok_file.is_absolute() and tok_file.read_text(encoding="utf-8") == a.ws_token
        assert not any(a.ws_token in x for x in args)
        assert a.env[WS_TOKEN_ENV] == a.ws_token
        assert a.ws_token not in redactor(a.env)(f"x {a.ws_token} y")  # persisted logs never hold it
        if os.name == "nt":
            acl = subprocess.run(["icacls", str(tok_file.parent)], capture_output=True, text=True).stdout
            grants = [ln for ln in acl.splitlines()[:-2] if ":" in ln.split(str(tok_file.parent))[-1]]
            assert len(grants) == 1 and os.environ["USERNAME"].lower() in grants[0].lower(), acl
    finally:
        a._cleanup_token()
    assert not tok_file.exists()


def test_app_server_child_never_holds_the_ws_token(tmp_path, monkeypatch):
    seen = {}

    class Stop(Exception):
        pass

    real = subprocess.Popen

    def fake_popen(argv, **kw):
        if "app-server" not in argv:
            return real(argv, **kw)  # icacls (private_dir)
        seen["argv"], seen["env"] = argv, kw["env"]
        raise Stop
    monkeypatch.setattr(rpc_mod.subprocess, "Popen", fake_popen)
    a = AppServer(["codex", "app-server"], cwd=str(tmp_path), env={"PATH": os.environ.get("PATH", "")},
                  log_path=tmp_path / "m.jsonl", ws=True)
    with pytest.raises(Stop):
        a.start()
    try:
        assert WS_TOKEN_ENV not in seen["env"] and a.env.get(WS_TOKEN_ENV)
        assert not any(a.ws_token in x for x in seen["argv"])
        assert "--ws-token-file" in seen["argv"]
    finally:
        a._cleanup_token()


def test_tui_argv_joins_the_seat_thread_with_the_token_by_env_name(tmp_path):
    s = seat_mod.CodexSeat(cwd=V8, role="reviewer", handle="reviewer.tui", log_dir=tmp_path, codex_bin=str(FAKE),
                           board=False, env={"EDP_PARITY_DESCRIPTIONS": str(V8 / "guides" / "harness-parity" / "descriptions.ours.json")},
                           discover=lambda _c: ([], None), ws=True)
    s.server = SimpleNamespace(ws_url="ws://127.0.0.1:5555", env={WS_TOKEN_ENV: "the-token-value"})
    s.thread_id = "thr-1"
    argv = s.tui_argv()
    assert argv[-10:] == ["resume", "thr-1", "--remote", "ws://127.0.0.1:5555", "--remote-auth-token-env",
                          WS_TOKEN_ENV, "-c", "check_for_update_on_startup=false", "-C", s.cwd]
    assert "the-token-value" not in " ".join(argv)
    assert s.tui_env()[WS_TOKEN_ENV] == "the-token-value"
    s.tools.shutdown()


def test_tui_argv_always_turns_the_startup_update_check_off(tmp_path):
    """Invariant (architect m-052faf9812): the TUI never opens on codex's "Update now" modal, whose Enter
    runs `npm install -g @openai/codex` on the shared host (drill tui1, 2026-09-23). Upgrades are an owner
    action between stories, never from inside a seat."""
    s = seat_mod.CodexSeat(cwd=V8, role="engineer", handle="engineer.tui", log_dir=tmp_path, codex_bin=str(FAKE),
                           board=False, env={"EDP_PARITY_DESCRIPTIONS": str(V8 / "guides" / "harness-parity" / "descriptions.ours.json")},
                           discover=lambda _c: ([], None), ws=True)
    s.server = SimpleNamespace(ws_url="ws://127.0.0.1:5555", env={})
    s.thread_id = "thr-2"
    argv = s.tui_argv()
    pairs = list(zip(argv, argv[1:]))
    assert ("-c", "check_for_update_on_startup=false") in pairs
    assert not any(a == "-c" and b.startswith("check_for_update_on_startup=") and b != "check_for_update_on_startup=false"
                   for a, b in pairs)
    s.tools.shutdown()


class _FakeSeat:
    def __init__(self, argv, seen_after=2):
        self.cwd = str(V8)
        self._argv = argv
        self._polls = 0
        self._seen_after = seen_after
        self.stopped = False
        self.server = SimpleNamespace(exit_code=None)
        self.tools = SimpleNamespace(shutdown=lambda: None)
        self.delivery = SimpleNamespace(seen_any=self._seen)

    def _seen(self):
        self._polls += 1
        return self._polls > self._seen_after

    def alive(self):
        return not self.stopped

    def tui_argv(self):
        assert self._polls > self._seen_after, "TUI started before the thread had a landed input"
        return self._argv

    def tui_env(self):
        return dict(os.environ)

    def stop(self):
        self.stopped = True


def test_run_tui_waits_for_the_first_input_and_the_seat_ends_with_the_tui():
    seat = _FakeSeat([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert run_mod.run_tui(seat, "reviewer.x") == 3
    assert seat.stopped


def test_run_tui_stops_the_tui_when_the_thread_is_gone():
    seat = _FakeSeat([sys.executable, "-c", "import time; time.sleep(60)"], seen_after=0)
    t = threading.Timer(1.0, seat.stop)
    t.start()
    t0 = __import__("time").time()
    run_mod.run_tui(seat, "reviewer.x")  # returns only once the TUI is gone
    assert seat.stopped and __import__("time").time() - t0 < 30
