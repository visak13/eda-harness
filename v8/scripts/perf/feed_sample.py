"""S22: sample a board's view feed (read-only) and report events/min, bytes per event and the kinds.

    python scripts/perf/feed_sample.py --minutes 10 --out feed.jsonl [--base http://127.0.0.1:9400]

Signs as this seat (EDP8_PARTICIPANT/EDP_HANDLE + EDP8_TOKEN from the env) and reads /v1/feed?watch=true —
the SPA's own view feed. Each data frame is written as {t, seq, kind, bytes}; the summary prints to stdout.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import time

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("EDP8_BOARD_URL", "http://127.0.0.1:9400"))
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    who = os.environ.get("EDP8_PARTICIPANT") or os.environ["EDP_HANDLE"]
    h = {"X-Participant": who, "X-Token": os.environ.get("EDP8_TOKEN", "")}
    end = time.monotonic() + a.minutes * 60
    rows: list[dict] = []
    with open(a.out, "w", encoding="utf-8") as out, httpx.Client(timeout=httpx.Timeout(10, read=60)) as c:
        while time.monotonic() < end:
            try:
                with c.stream("GET", f"{a.base}/v1/feed?since=-1&watch=true", headers=h) as r:
                    r.raise_for_status()
                    buf = ""
                    for chunk in r.iter_text():
                        buf += chunk
                        while "\n\n" in buf:
                            frame, buf = buf.split("\n\n", 1)
                            data = "\n".join(l[5:].lstrip() for l in frame.split("\n") if l.startswith("data:"))
                            if not data:
                                continue
                            ev = json.loads(data)
                            row = {"t": time.time(), "seq": ev.get("seq"), "kind": ev.get("kind"), "bytes": len(data)}
                            rows.append(row)
                            out.write(json.dumps(row) + "\n")
                            out.flush()
                        if time.monotonic() >= end:
                            break
            except (httpx.HTTPError, ValueError):
                time.sleep(2)
    mins = a.minutes
    kinds = collections.Counter(r["kind"] for r in rows)
    size = sum(r["bytes"] for r in rows)
    print(json.dumps({"minutes": mins, "events": len(rows), "per_min": round(len(rows) / mins, 1),
                      "bytes_total": size, "bytes_avg": round(size / max(len(rows), 1)),
                      "bytes_max": max((r["bytes"] for r in rows), default=0), "kinds": kinds.most_common()}, indent=1))


if __name__ == "__main__":
    main()
