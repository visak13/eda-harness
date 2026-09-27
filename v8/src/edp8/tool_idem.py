"""S23 standard 2: idempotent creates (every create tool; T3 F2 widened it past the first three).

A retried create returns the FIRST result instead of a second object:
- with `idempotency_key`: the key travels to the board as the Idempotency-Key header (edp8.idempotency), which
  keeps the first reply 24 h in its DB, so the window survives an MCP-proxy restart. The same key and the
  same args replay it; the same key with DIFFERENT args is a `conflict` (the key names one intent);
- without a key: an identical create by the same seat within 10 minutes replays (T1 audit: 3/3 paired
  same-input creates made duplicates). This window lives in the tool-serving process and resets when it
  restarts; pass a key for a retry that must hold across one. Pass a fresh key to create a deliberate twin.
A replay carries `replay: true` in its value and says so in the hint. Only successes are kept.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Callable

AUTO_TTL_S = 600
_MAX = 5000
_lock = threading.Lock()
_cache: dict[tuple[str, str, str], tuple[float, str, dict[str, Any]]] = {}  # slot -> (expires, digest, reply)


def _digest(args: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()


def _sweep(now: float) -> None:
    if len(_cache) < _MAX:
        return
    for k in [k for k, v in _cache.items() if v[0] < now]:
        _cache.pop(k, None)


def once(tool: str, seat: str | None, args: dict[str, Any], key: str | None,
         create: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run `create` once per (seat, tool, key-or-same-args) window; replay or refuse otherwise."""
    if key:  # the board keeps it (edp8.idempotency): replay and conflict come back from there
        from .client import idempotency_key
        with idempotency_key(key):
            return create()
    digest = _digest(args)
    slot = (seat or "?", tool, f"auto:{digest}")
    now = time.time()
    with _lock:
        hit = _cache.get(slot)
        if hit and hit[0] < now:
            _cache.pop(slot, None)
            hit = None
    if hit:
        first = hit[2]
        value = first.get("value")
        replay = {**first, "value": {**value, "replay": True} if isinstance(value, dict) else value}
        replay["hint"] = "replay: same id, nothing new; a new idempotency_key makes a twin"
        return replay
    out = create()
    if out.get("ok"):
        with _lock:
            _sweep(now)
            _cache[slot] = (now + AUTO_TTL_S, digest, out)
    return out


def reset() -> None:
    """Tests: forget every remembered create."""
    with _lock:
        _cache.clear()
