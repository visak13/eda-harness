"""Request timing (S22 performance pass): one JSON line per HTTP request — the route TEMPLATE (never the
raw path, so ids and query strings stay out of the log), method, status, milliseconds and response bytes.

Off by default (EDP8_TIMING). When on, the board appends to `<logs>/timing.jsonl`; `summarise()` turns
that file into per-route p50/p95, which is what scripts/perf/routes.py reports. A streamed response (the
SSE feed) is logged when it ends, so its line measures the connection, not a request.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import settings


def enabled() -> bool:
    return bool(settings.get("EDP8_TIMING"))


def log_path() -> Path:
    return settings.logs_dir() / "timing.jsonl"


class TimingMiddleware:
    """Pure ASGI (no BaseHTTPMiddleware: that buffers streamed bodies and would break the feed)."""

    def __init__(self, app: ASGIApp, path: Path | None = None) -> None:
        self.app = app
        self.path = path or log_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._f: Any = None  # opened once: an open() per request cost ~20 ms on this host (AV scan) on the loop

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        status = 0
        size = 0

        async def send_wrapped(message: Message) -> None:
            nonlocal status, size
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                size += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapped)
        finally:
            route = scope.get("route")
            template = getattr(route, "path", None) or _static_family(scope.get("path") or "")
            row = {"t": round(time.time(), 3), "method": scope.get("method"), "route": template,
                   "status": status, "ms": round((time.perf_counter() - t0) * 1000, 2), "bytes": size}
            line = json.dumps(row) + "\n"
            with self._lock:
                if self._f is None:
                    self._f = open(self.path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — lives with the app
                self._f.write(line)


def _static_family(path: str) -> str:
    """A path no route template matched (static files, the SPA catch-all): its first two segments only."""
    parts = [p for p in path.split("/") if p][:2]
    return "/" + "/".join(parts) + ("/*" if parts else "")


def _pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return 0.0
    k = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return s[k]


def summarise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per (method, route): count, p50, p95, max ms and median bytes; slowest p95 first."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["method"], r["route"]), []).append(r)
    out = []
    for (method, route), rs in groups.items():
        ms = [r["ms"] for r in rs]
        out.append({"method": method, "route": route, "n": len(rs), "p50_ms": _pct(ms, 0.5),
                    "p95_ms": _pct(ms, 0.95), "max_ms": max(ms),
                    "bytes_p50": _pct([float(r["bytes"]) for r in rs], 0.5)})
    return sorted(out, key=lambda r: -r["p95_ms"])


def read(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or log_path()
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
