"""pain.py — the pain-point file with a lifecycle (stdlib only; 2026-09-06).

Pain points stay OUTSIDE the board (owner ruling): they are fixed from a shell outside the
framework. This script gives the append-only file structure instead of a new plane:

  python scripts/pain.py list [--all] [--area tools] [--json]   open records (default) as a table
  python scripts/pain.py file  '<json-object>'                  append one record (assigns an id)
  python scripts/pain.py resolve <id> --status fixed|invalid|superseded [--by <sha>] [--note ...]
  python scripts/pain.py show <id>                              the record and its resolution trail

File: v8/.pain/pain-points.jsonl — one JSON object per line, append-only, BOM-tolerant.
  record:     {"id","ts","role","handle","severity","area","symptom","expected","evidence",
               "workaround","cost", "supersedes"?, "dup_of"?}
  resolution: {"id","resolves":true,"status","fixed_by","ts","note"}   (latest line per id wins)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FILE = Path(os.environ.get("EDP8_PAIN_FILE", HERE / ".pain" / "pain-points.jsonl"))
STATUSES = ("open", "fixed", "invalid", "superseded")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load() -> tuple[list[dict], dict[str, dict]]:
    """(records in file order, latest resolution per id). Lines without an id get one derived
    from their ts+symptom so old records are addressable without rewriting the file."""
    records: list[dict] = []
    resolutions: dict[str, dict] = {}
    if not FILE.is_file():
        return records, resolutions
    for raw in FILE.read_text(encoding="utf-8-sig").splitlines():
        raw = raw.strip().lstrip("﻿")
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if d.get("resolves"):
            resolutions[d["id"]] = d
            continue
        if not d.get("id"):
            d["id"] = "p-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{d.get('ts')}|{d.get('symptom')}").hex[:8]
            d["_legacy"] = True
        records.append(d)
    return records, resolutions


def _status(rec: dict, res: dict[str, dict]) -> str:
    return res.get(rec["id"], {}).get("status", "open")


def _append(obj: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    with FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def cmd_list(a: argparse.Namespace) -> int:
    recs, res = _load()
    rows = [r for r in recs if (a.all or _status(r, res) == "open") and (not a.area or r.get("area") == a.area)]
    if a.json:
        print(json.dumps([{**r, "status": _status(r, res)} for r in rows], indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("no open pain points" if not a.all else "no pain points")
        return 0
    for r in rows:
        st = _status(r, res)
        by = res.get(r["id"], {}).get("fixed_by") or ""
        print(f"{r['id']}  {st:<10} {r.get('severity','?'):<6} {r.get('area','?'):<7} {r.get('ts','')[:10]}  "
              f"{r.get('role','?'):<9} {(r.get('symptom') or '')[:90]}" + (f"  [{by}]" if by else ""))
    print(f"\n{len(rows)} shown ({sum(1 for r in recs if _status(r, res) == 'open')} open of {len(recs)})")
    return 0


def cmd_file(a: argparse.Namespace) -> int:
    try:
        d = json.loads(a.record)
    except ValueError as e:
        print(f"not JSON: {e}", file=sys.stderr)
        return 2
    missing = [k for k in ("role", "severity", "area", "symptom", "expected", "evidence") if not d.get(k)]
    if missing:
        print(f"missing fields: {missing}", file=sys.stderr)
        return 2
    d.setdefault("ts", _now())
    d["id"] = d.get("id") or f"p-{uuid.uuid4().hex[:8]}"
    _append(d)
    if d.get("supersedes"):
        _append({"id": d["supersedes"], "resolves": True, "status": "superseded", "fixed_by": d["id"],
                 "ts": _now(), "note": f"superseded by {d['id']}"})
    print(f"pain point filed: {d['id']} {d['area']} — {d['symptom'][:80]}")
    return 0


def cmd_resolve(a: argparse.Namespace) -> int:
    recs, _ = _load()
    if not any(r["id"] == a.id for r in recs):
        print(f"no record {a.id}", file=sys.stderr)
        return 2
    _append({"id": a.id, "resolves": True, "status": a.status, "fixed_by": a.by or "", "ts": _now(),
             "note": a.note or ""})
    print(f"{a.id} -> {a.status}" + (f" ({a.by})" if a.by else ""))
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    recs, res = _load()
    for r in recs:
        if r["id"] == a.id:
            print(json.dumps({**r, "status": _status(r, res), "resolution": res.get(r["id"])}, indent=2,
                             ensure_ascii=False))
            return 0
    print(f"no record {a.id}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list"); s.add_argument("--all", action="store_true"); s.add_argument("--area")
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("file"); s.add_argument("record"); s.set_defaults(fn=cmd_file)
    s = sub.add_parser("resolve"); s.add_argument("id"); s.add_argument("--status", choices=STATUSES[1:], required=True)
    s.add_argument("--by"); s.add_argument("--note"); s.set_defaults(fn=cmd_resolve)
    s = sub.add_parser("show"); s.add_argument("id"); s.set_defaults(fn=cmd_show)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
