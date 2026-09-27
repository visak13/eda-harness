"""S22: sample processes' memory (read-only psutil) every --every seconds for --minutes.

    python scripts/perf/mem_sample.py --pid 123 --pid 456 --minutes 15 --every 30 --out mem.jsonl

Writes {t, pid, rss_mb, private_mb, threads} lines and prints first/last/max and growth per pid. A pid
whose process ends is reported and dropped; nothing is ever signalled.
"""
from __future__ import annotations

import argparse
import json
import time

import psutil


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, action="append", required=True)
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--every", type=float, default=30)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    procs = {p: psutil.Process(p) for p in a.pid}
    seen: dict[int, list[dict]] = {p: [] for p in a.pid}
    end = time.monotonic() + a.minutes * 60
    with open(a.out, "w", encoding="utf-8") as out:
        while procs:
            for pid, p in list(procs.items()):
                try:
                    m = p.memory_info()
                    row = {"t": round(time.time(), 1), "pid": pid, "rss_mb": round(m.rss / 2**20, 1),
                           "private_mb": round(getattr(m, "private", m.rss) / 2**20, 1), "threads": p.num_threads()}
                except psutil.NoSuchProcess:
                    print(f"pid {pid} ended")
                    del procs[pid]
                    continue
                seen[pid].append(row)
                out.write(json.dumps(row) + "\n")
                out.flush()
            if time.monotonic() >= end:
                break
            time.sleep(a.every)
    for pid, rows in seen.items():
        if rows:
            print(json.dumps({"pid": pid, "samples": len(rows), "first_rss": rows[0]["rss_mb"],
                              "last_rss": rows[-1]["rss_mb"], "max_rss": max(r["rss_mb"] for r in rows),
                              "first_private": rows[0]["private_mb"], "last_private": rows[-1]["private_mb"],
                              "growth_rss_mb": round(rows[-1]["rss_mb"] - rows[0]["rss_mb"], 1),
                              "minutes": round((rows[-1]["t"] - rows[0]["t"]) / 60, 1)}))


if __name__ == "__main__":
    main()
