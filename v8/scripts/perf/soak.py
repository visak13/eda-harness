"""S22: drive a PRIVATE board like open SPA tabs under feed traffic, for a memory-growth window.

    python scripts/perf/soak.py <dir> --minutes 15 --every 2 --epic epic-… --ticket s-…

Every `--every` seconds: one note on the ticket (a feed event), then the refetches a tab on the epic view
makes for it (epic page, its summary row, attention) plus the Epics list. <dir> is private_board.py's.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from private_board import headers  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--every", type=float, default=2)
    ap.add_argument("--epic", required=True)
    ap.add_argument("--ticket", required=True)
    a = ap.parse_args()
    d = Path(a.dir).resolve()
    base = json.loads((d / "board.json").read_text(encoding="utf-8"))["base"]
    h = headers(d)
    end = time.monotonic() + a.minutes * 60
    n = errors = 0
    with httpx.Client(base_url=base, headers=h, timeout=30) as c:
        while time.monotonic() < end:
            t0 = time.monotonic()
            try:
                c.post("/v1/messages", json={"kind": "note", "ticket_id": a.ticket, "text": f"soak {n}"}).raise_for_status()
                for path, params in ((f"/v1/epics/{a.epic}/page", None), ("/v1/epics/summary", {"id": a.epic}),
                                     ("/v1/me/attention", None), ("/v1/epics/summary", None)):
                    c.get(path, params=params).raise_for_status()
            except httpx.HTTPError:
                errors += 1
            n += 1
            time.sleep(max(0.0, a.every - (time.monotonic() - t0)))
    print(json.dumps({"events": n, "errors": errors, "minutes": a.minutes}))


if __name__ == "__main__":
    main()
