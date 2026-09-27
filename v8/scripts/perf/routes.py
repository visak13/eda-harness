"""S22: per-route p50/p95 for the routes the SPA calls on its main pages, against a PRIVATE board.

    python scripts/perf/routes.py <dir> --epic epic-… --ticket s-… [--n 15] [--out routes.json]

The route set is what web/scripts/perf-trace.mjs recorded the SPA calling on Epics, the epic view, a ticket,
Admin, Design and Code (plus /v1/inbox and /v1/seats). Each route is requested --n times, round-robin across
routes so no route runs only warm; client-side wall ms, with gzip accepted (as a browser does).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from private_board import headers  # noqa: E402


def route_set(epic: str, ticket: str) -> list[tuple[str, str, str, dict | None]]:
    """(page, method, path, json body) — the SPA's calls per page (perf-trace.mjs, 2026-09-27)."""
    shell = [("GET", "/v1/health", None), ("GET", "/v1/whoami", None), ("GET", "/v1/describe/message", None),
             ("GET", "/v1/me/attention", None), ("GET", "/v1/avatars/owner.svg", None)]
    pages = {
        "epics": [("GET", "/v1/epics/summary", None)],
        "epic": [("GET", f"/v1/epics/{epic}/page", None), ("GET", f"/v1/epics/summary?id={epic}", None),
                 ("GET", f"/v1/tickets/{epic}", None), ("GET", f"/v1/tickets/{epic}/contextual", None),
                 ("GET", "/v1/me/people", None), ("GET", "/v1/workflows/standard%401", None),
                 ("POST", "/v1/messages/resolve", {"ticket_id": epic, "kind": "note", "text": "hello"})],
        "ticket": [("GET", f"/v1/tickets/{ticket}/page", None), ("GET", f"/v1/tickets/{ticket}", None),
                   ("GET", f"/v1/tickets/{ticket}/contextual", None)],
        "admin": [("GET", "/v1/admin/capacity", None), ("GET", "/v1/admin/updates", None),
                  ("GET", "/v1/admin/services", None)],
        "design": [("GET", "/v1/workflows/templates", None), ("GET", "/v1/models", None), ("GET", "/v1/workflows", None)],
        "code": [("GET", "/v1/code", None)],
        "other": [("GET", "/v1/inbox", None), ("GET", "/v1/seats", None)],
    }
    out = [("shell", m, p, b) for m, p, b in shell]
    for page, rs in pages.items():
        out += [(page, m, p, b) for m, p, b in rs]
    return out


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--epic", required=True)
    ap.add_argument("--ticket", required=True)
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--out")
    a = ap.parse_args()
    d = Path(a.dir).resolve()
    base = json.loads((d / "board.json").read_text(encoding="utf-8"))["base"]
    routes = route_set(a.epic, a.ticket)
    ms: dict[str, list[float]] = {}
    size: dict[str, tuple[int, int]] = {}
    with httpx.Client(base_url=base, headers={**headers(d), "Accept-Encoding": "gzip"}, timeout=60) as c:
        for m, p, b in [(m, p, b) for _, m, p, b in routes]:  # warm once
            c.request(m, p, json=b)
        for _ in range(a.n):
            for page, m, p, b in routes:
                t = time.perf_counter()
                r = c.request(m, p, json=b)
                ms.setdefault(f"{m} {p}", []).append((time.perf_counter() - t) * 1000)
                wire = int(r.headers.get("content-length") or len(r.content))
                size[f"{m} {p}"] = (wire, len(r.content))
                if r.status_code >= 400:
                    print(f"{r.status_code} {m} {p}: {r.text[:120]}", file=sys.stderr)
    rows = []
    for page, m, p, _ in routes:
        k = f"{m} {p}"
        xs = ms[k]
        rows.append({"page": page, "route": k.replace(a.epic, "{epic}").replace(a.ticket, "{ticket}"),
                     "p50_ms": round(statistics.median(xs), 1), "p95_ms": round(pct(xs, 0.95), 1),
                     "wire_kb": round(size[k][0] / 1024, 1), "body_kb": round(size[k][1] / 1024, 1)})
    for r in rows:
        print(f"{r['page']:7} {r['route']:52} p50 {r['p50_ms']:7.1f}  p95 {r['p95_ms']:7.1f}  "
              f"wire {r['wire_kb']:6.1f} KB  body {r['body_kb']:6.1f} KB")
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
