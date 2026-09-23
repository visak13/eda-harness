"""A minimal RFC 6455 text-frame client for a loopback `codex app-server --listen ws://127.0.0.1:<port>`.

Monitor mode (owner ruling m-0e7b8fdd7f) runs the native codex TUI as the seat's console; the TUI and
the runner are two clients of ONE app-server, so the app-server listens on a loopback websocket instead
of stdio. Measured on 0.156.0 (s-10a2b1f9ec spike, 2026-09-23): `--ws-auth capability-token
--ws-token-file <abs path>` works on loopback — no/wrong bearer → 401, the right one → 101.
Stdlib only (the seat venv has no websocket package); one JSON-RPC message per text message.
"""

from __future__ import annotations

import base64
import os
import socket
import struct
import threading


class WsClosed(ConnectionError):
    pass


class WsClient:
    def __init__(self, host: str, port: int, token: str | None = None, timeout: float = 10.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        auth = f"Authorization: Bearer {token}\r\n" if token else ""
        self.sock.sendall((f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n{auth}\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WsClosed("closed during the upgrade")
            buf += chunk
        head, self._buf = buf.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101 " not in f"{status} ":
            self.sock.close()
            raise ConnectionRefusedError(f"websocket upgrade refused: {status}")
        self.sock.settimeout(None)
        self._wlock = threading.Lock()

    # ------------------------------------------------------------------ send
    def _frame(self, op: int, data: bytes) -> bytes:
        n = len(data)
        if n < 126:
            head = bytes([0x80 | op, 0x80 | n])
        elif n < 65536:
            head = bytes([0x80 | op, 0x80 | 126]) + struct.pack(">H", n)
        else:
            head = bytes([0x80 | op, 0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        # XOR in one go: int.from_bytes over the payload is far faster than a per-byte generator
        m = (mask * (n // 4 + 1))[:n]
        body = (int.from_bytes(data, "big") ^ int.from_bytes(m, "big")).to_bytes(n, "big") if n else b""
        return head + mask + body

    def send_text(self, text: str) -> None:
        frame = self._frame(0x1, text.encode("utf-8"))
        with self._wlock:
            self.sock.sendall(frame)

    # ------------------------------------------------------------------ receive
    def _exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WsClosed("socket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv_text(self) -> str | None:
        """The next complete text message; None once the server closes (or the socket drops)."""
        parts: list[bytes] = []
        try:
            while True:
                b1, b2 = self._exact(2)
                op, n = b1 & 0x0F, b2 & 0x7F
                if n == 126:
                    n = struct.unpack(">H", self._exact(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", self._exact(8))[0]
                mask = self._exact(4) if b2 & 0x80 else b""
                payload = self._exact(n)
                if mask:
                    payload = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
                if op == 0x8:  # close
                    return None
                if op == 0x9:  # ping → pong
                    with self._wlock:
                        self.sock.sendall(self._frame(0xA, payload))
                    continue
                if op == 0xA:
                    continue
                parts.append(payload)
                if b1 & 0x80:
                    return b"".join(parts).decode("utf-8", "replace")
        except (OSError, WsClosed):
            return None

    def close(self) -> None:
        try:
            with self._wlock:
                self.sock.sendall(self._frame(0x8, b""))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
