"""S14 near-duplicate audit (c-901b65a57a): for each backfilled epic, the closest pair of LIVE decisions by
word-set Jaccard over their text. Read-only on the board DB; loads no model. Exit 1 if any pair >= the threshold.

    .venv/Scripts/python.exe scripts/decision_dedup_audit.py [--db .data/edp8.db] [--threshold 0.30] [--pairs]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys

EPICS = ["epic-44a0576511", "epic-1b289d63f9", "epic-733b165bd7", "epic-6a8a6020fd", "epic-9cec9f7b04",
         "epic-cf3d352b92"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=".data/edp8.db")
    ap.add_argument("--threshold", type=float, default=0.30)
    ap.add_argument("--pairs", action="store_true", help="print every pair at or above the threshold")
    a = ap.parse_args()
    db = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    epic_of_ticket = {i: e for i, e in db.execute("select id, epic_id from ticket")}
    by: dict[str, list[tuple[str, set[str], str]]] = {e: [] for e in EPICS}
    for i, scope, body in db.execute("select id, scope, body from decision where status='live'"):
        e = scope if (scope or "").startswith("epic-") else epic_of_ticket.get(scope)
        if e in by:
            t = json.loads(body).get("text", "")
            by[e].append((i, set(re.findall(r"[a-z0-9]+", t.lower())), t))
    print(f"| epic | live decisions | closest pair | Jaccard | pairs >= {a.threshold:.2f} |")
    print("|---|---|---|---|---|")
    over_all, shown = 0, []
    for e, rs in by.items():
        best, pair, over = 0.0, ("-", "-"), 0
        for x in range(len(rs)):
            for y in range(x + 1, len(rs)):
                u = rs[x][1] | rs[y][1]
                j = len(rs[x][1] & rs[y][1]) / len(u) if u else 0.0
                if j >= a.threshold:
                    over += 1
                    shown.append((e, j, rs[x], rs[y]))
                if j > best:
                    best, pair = j, (rs[x][0], rs[y][0])
        over_all += over
        print(f"| {e} | {len(rs)} | {pair[0]} / {pair[1]} | {best:.3f} | {over} |")
    if a.pairs:
        for e, j, r1, r2 in shown:
            print(f"\n{e} {j:.3f}\n  {r1[0]}: {r1[2]}\n  {r2[0]}: {r2[2]}")
    return 1 if over_all else 0


if __name__ == "__main__":
    sys.exit(main())
