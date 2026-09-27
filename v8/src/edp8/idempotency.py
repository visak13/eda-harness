"""T3 F2 (report-6971109e05): board-side idempotency keys for every create.

A POST carrying `Idempotency-Key` runs once per (caller, path, key) for 24 h:
- the same key with the same body replays the FIRST reply (`value.replay: true`), whether the retry comes from
  the same MCP proxy or one restarted since — the key lives in the board DB (`idem` table), not a process;
- the same key with a different body is a 409 `conflict` (a key names one intent);
- only successes are kept, so a refused create can be retried with its key.
The caller is the X-Participant + X-Token pair (hashed): one seat's key never replays another seat's reply.
Concurrent duplicates are serialised per slot, so a retry racing its original waits and then replays.

The tool layer (tool_idem) forwards a tool's `idempotency_key` as this header. The no-key "identical create
within 10 minutes" window stays in the tool-serving process (tool_idem) and resets when it restarts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from .store import Store

TTL_S = 24 * 3600
HEADER = b"idempotency-key"
REPLAY_HINT = "replay: same id, nothing new; a new idempotency_key makes a twin"


def _sha(*parts: bytes) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p)
        h.update(b"\0")
    return h.hexdigest()


def _json(status: int, content: dict[str, Any]) -> tuple[int, bytes]:
    return status, json.dumps(content).encode()


def replay_body(body: bytes) -> bytes:
    try:
        env = json.loads(body)
    except ValueError:
        return body
    if isinstance(env, dict):
        if isinstance(env.get("value"), dict):
            env["value"] = {**env["value"], "replay": True}
        env["hint"] = REPLAY_HINT
    return json.dumps(env).encode()


class IdempotencyMiddleware:
    """Pure ASGI (no BaseHTTPMiddleware): reads the body once, replays or records the reply."""

    def __init__(self, app: Any, store: Store):
        self.app = app
        self.store = store
        self._locks: dict[str, asyncio.Lock] = {}

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        key = headers.get(HEADER)
        if not key:
            return await self.app(scope, receive, send)
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        who = _sha(headers.get(b"x-participant", b""), headers.get(b"x-token", b""))
        slot = _sha(who.encode(), scope["path"].encode(), key)
        digest = _sha(body)
        lock = self._locks.setdefault(slot, asyncio.Lock())
        try:
            async with lock:
                hit = self.store.idem_get(slot, time.time())
                if hit is None:
                    status, headers_out, out = await self._run_and_keep(scope, body, slot, digest)
                else:
                    first_digest, status, first = hit
                    if first_digest != digest:
                        status, out = _json(409, {
                            "ok": False,
                            "error": {"code": "conflict", "field": "idempotency_key",
                                      "message": f"idempotency_key {key.decode(errors='replace')!r} was used "
                                                 "for different args"},
                            "hint": "a key names ONE create: reuse it only to retry the same args; pass a new "
                                    "key for new work"})
                    else:
                        out = replay_body(first)
                    headers_out = [(b"content-type", b"application/json")]
        finally:
            if not lock.locked() and not getattr(lock, "_waiters", None):
                self._locks.pop(slot, None)
        headers_out = [(k, v) for k, v in headers_out if k.lower() != b"content-length"]
        await send({"type": "http.response.start", "status": status,
                    "headers": [*headers_out, (b"content-length", str(len(out)).encode())]})
        await send({"type": "http.response.body", "body": out})

    async def _run_and_keep(self, scope: dict, body: bytes, slot: str, digest: str) -> tuple[int, list, bytes]:
        """Run the route with the body already read; keep a success BEFORE replying, so a caller that gave
        up waiting (the timeout a retry follows) still finds its first reply here."""
        sent = False

        async def replay_receive() -> dict:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        start: dict = {}
        chunks: list[bytes] = []

        async def capture(msg: dict) -> None:
            if msg["type"] == "http.response.start":
                start.update(msg)
            elif msg["type"] == "http.response.body":
                chunks.append(msg.get("body", b""))

        await self.app(scope, replay_receive, capture)
        status = start.get("status", 500)
        out = b"".join(chunks)
        if status == 200:
            try:
                good = json.loads(out).get("ok") is True
            except (ValueError, AttributeError):
                good = False
            if good:
                now = time.time()
                self.store.idem_put(slot, digest, status, out, now + TTL_S, now)
        return status, list(start.get("headers") or []), out
