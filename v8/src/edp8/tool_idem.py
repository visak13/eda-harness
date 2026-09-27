"""S23 standard 2: idempotent creates (doc_create, artifact_create, ticket_create).

A retried create returns the FIRST result instead of a second object:
- with `idempotency_key`: the same key and the same args replay the first result for 24 h; the same
  key with DIFFERENT args is a `conflict` (the key names one intent);
- without a key: an identical create by the same seat within 10 minutes replays (T1 audit: 3/3 paired
  same-input creates made duplicates). Pass a fresh key to create a deliberate twin inside the window.
A replay carries `replay: true` in its value and says so in the hint. Only successes are
kept; the cache lives in the tool-serving process (the shared MCP proxy for the fleet).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Callable

KEYED_TTL_S = 24 * 3600
AUTO_TTL_S = 600
_MAX = 5000
_lock = threading.Lock()
_cache: dict[tuple[str, str, str], tuple[float, str, dict[str, Any]]] = {}


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
    digest = _digest(args)
    slot = (seat or "?", tool, f"key:{key}" if key else f"auto:{digest}")
    now = time.time()
    with _lock:
        hit = _cache.get(slot)
        if hit and hit[0] < now:
            _cache.pop(slot, None)
            hit = None
    if hit:
        if hit[1] != digest:
            return {"ok": False, "error": {"code": "conflict", "field": "idempotency_key",
                                           "message": f"{tool}: idempotency_key {key!r} was used for different args"},
                    "hint": "a key names ONE create: reuse it only to retry the same args; pass a new key for new work"}
        first = hit[2]
        value = first.get("value")
        replay = {**first, "value": {**value, "replay": True} if isinstance(value, dict) else value}
        replay["hint"] = "replay: same id, nothing new; a new idempotency_key makes a twin"
        return replay
    out = create()
    if out.get("ok"):
        with _lock:
            _sweep(now)
            _cache[slot] = (now + (KEYED_TTL_S if key else AUTO_TTL_S), digest, out)
    return out


def reset() -> None:
    """Tests: forget every remembered create."""
    with _lock:
        _cache.clear()
