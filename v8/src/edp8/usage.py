"""Private subscription telemetry, never API spend or host-wide account discovery.

Only operator-configured participant bindings may read dedicated allowlisted receipts.
Provider collection is separate/default-off; opening the widget cannot start a process.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import threading
import time
from typing import Literal

from pydantic import BaseModel

Provider = Literal["claude", "codex"]
Status = Literal["available", "stale", "unavailable", "auth_required", "error"]
MAX_BYTES = 65536
REFRESH_SECONDS = 30
STALE_SECONDS = 300


class Window(BaseModel):
    key: str
    window_minutes: int | None
    used_percent: float | None = None
    resets_at: int | None = None
    observed_at: str | None = None
    status: Status = "unavailable"
    reason: str = "Window not reported"


class ProviderUsage(BaseModel):
    provider: Provider
    account_binding: str | None = None
    source: str
    received_at: str | None = None
    windows: list[Window]
    retry_after_seconds: int = REFRESH_SECONDS


def stamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.astimezone(timezone.utc) if date.tzinfo else None
    except (ValueError, OverflowError):
        return None


def empty(provider: Provider, status: Status = "unavailable", reason: str = "Account not linked") -> ProviderUsage:
    keys = [("five_hour", 300), ("seven_day", 10080)]
    if provider == "claude":
        keys.append(("fable", None))
    return ProviderUsage(provider=provider,
        source="Claude Code statusline" if provider == "claude" else "Codex App Server",
        windows=[Window(key=key, window_minutes=duration, status=status, reason=reason)
                 for key, duration in keys])


def normalize(provider: Provider, raw: dict, now: float) -> ProviderUsage:
    """Project known numeric fields only. Each receipt replaces, never merges, windows."""
    result = empty(provider, reason="Window not reported")
    result.account_binding = "Linked account"  # no name/email/hash/path/opaque binding exported
    received = stamp(raw.get("received_at"))
    result.received_at = received.isoformat() if received else None
    state = raw.get("status", "available")
    if state in ("auth_required", "error", "unavailable"):
        reason = {"auth_required": "Source authentication required", "error": "Source collection failed",
                  "unavailable": "Source not reporting"}[state]
        for window in result.windows:
            window.status, window.reason = state, reason
        return result
    if state != "available" or received is None or received.timestamp() > now + 60:
        for window in result.windows:
            window.status, window.reason = "error", "Invalid source receipt"
        return result

    # These documented interfaces supply NO provider observation timestamp. In particular,
    # never trust an invented observed_at field or treat a new receipt as a new observation.
    if provider == "claude":
        rates = raw.get("rate_limits")
        rates = rates if isinstance(rates, dict) else {}
        candidates = [(rates.get(w.key), "used_percentage", "resets_at") for w in result.windows]
    else:
        rates = raw.get("rateLimits")
        by_id = raw.get("rateLimitsByLimitId")
        if isinstance(by_id, dict) and "codex" in by_id:
            rates = by_id["codex"]
        rates = rates if isinstance(rates, dict) else {}
        candidates = []
        for w in result.windows:
            matches = [v for k, v in rates.items() if k in ("primary", "secondary")
                       and isinstance(v, dict) and type(v.get("windowDurationMins")) in (int, float)
                       and v.get("windowDurationMins") == w.window_minutes]
            candidates.append((matches[0] if len(matches) == 1 else None, "usedPercent", "resetsAt"))
    for window, (candidate, used_key, reset_key) in zip(result.windows, candidates):
        # Fable-specific usage has not been verified; never infer it from a model label.
        if window.key == "fable" or not isinstance(candidate, dict):
            continue
        used, reset = candidate.get(used_key), candidate.get(reset_key)
        if (type(used) not in (int, float) or not 0 <= used <= 100 or not math.isfinite(used)
                or type(reset) is not int or not 0 < reset <= 253402300799):
            window.reason = "Invalid or missing window values"
            continue
        if reset <= now:
            window.status, window.reason = "stale", "Reset elapsed; awaiting source update"
            continue  # expired values must not masquerade as the new period's utilization
        window.used_percent, window.resets_at = used, reset
        window.status = "stale"
        window.reason = ("Receipt older than five minutes; observation time unknown"
                         if now - received.timestamp() > STALE_SECONDS else
                         "Observation time unknown; may be stale")
    return result


def read_json(path: Path) -> dict:
    """Bounded local-file boundary. No raw errors or arbitrary payload reaches the API."""
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("receipt_too_large")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("not_object")
    return value


class UsageCache:
    def __init__(self, config: Path | None = None, clock=time.time):
        self.config = config
        self.clock = clock
        self._lock = threading.Lock()
        self._cache: OrderedDict = OrderedDict()

    def read(self, participant_id: str) -> dict:
        now = self.clock()
        # Re-read the small operator ACL every request: revocation doesn't wait for cache TTL.
        path = self.config or (Path(os.environ["EDP8_USAGE_CONFIG"]) if os.environ.get("EDP8_USAGE_CONFIG") else None)
        if path is None:
            return {"providers": [empty(p).model_dump() for p in ("claude", "codex")]}
        try:
            config = read_json(path)
            people = config.get("participants", {})
            if not isinstance(people, dict):
                raise ValueError("invalid_configuration")
            bindings = people.get(participant_id, {})
            if not isinstance(bindings, dict):
                raise ValueError("invalid_configuration")
        except (OSError, ValueError, TypeError, RecursionError):
            return {"providers": [empty(p, "error", "Usage configuration unavailable").model_dump()
                                  for p in ("claude", "codex")]}
        with self._lock:
            providers = [self._read_provider(participant_id, p, bindings.get(p), now)
                         for p in ("claude", "codex")]
        return {"providers": [p.model_dump() for p in providers]}

    def _read_provider(self, actor: str, provider: Provider, binding: object, now: float) -> ProviderUsage:
        key = (actor, provider)
        if binding is None:
            self._cache.pop(key, None)
            return empty(provider)
        if (not isinstance(binding, dict) or not isinstance(binding.get("binding_id"), str)
                or not binding["binding_id"] or not isinstance(binding.get("snapshot"), str)
                or not Path(binding["snapshot"]).is_absolute()):
            return empty(provider, "error", "Invalid account binding")
        signature = (binding["binding_id"], binding["snapshot"])
        old = self._cache.get(key)
        if old and old[0] == signature and now < old[1]:
            self._cache.move_to_end(key)
            result = normalize(provider, old[2], now) if old[2] else old[3].model_copy(deep=True)
            result.retry_after_seconds = max(1, math.ceil(old[1] - now))
            return result
        failures = old[4] if old and old[0] == signature else 0
        raw = None
        try:
            raw = read_json(Path(binding["snapshot"]))
            if raw.get("binding_id") != binding["binding_id"] or raw.get("provider") != provider:
                raw = None
                result = empty(provider, "auth_required", "Account binding does not match receipt")
            else:
                result = normalize(provider, raw, now)
        except FileNotFoundError:
            result = empty(provider, "unavailable", "Waiting for authorized source receipt")
        except (OSError, ValueError, TypeError, OverflowError, RecursionError):
            result = empty(provider, "error", "Source receipt unreadable")
        failed = all(w.status in ("error", "auth_required", "unavailable") for w in result.windows)
        failures = min(failures + 1, 5) if failed else 0
        delay = min(REFRESH_SECONDS * 2 ** max(0, failures - 1), 300)
        result.retry_after_seconds = delay
        self._cache[key] = (signature, now + delay, raw, result, failures)
        self._cache.move_to_end(key)
        while len(self._cache) > 256:
            self._cache.popitem(last=False)
        return result
