"""The pain log as a board-served record (S23): query, file, read and resolve over the SAME append-only
file scripts/pain.py writes (records.pain_file(): <home>/.pain/pain-points.jsonl). The owner ruling that
pains stay outside the board's database holds — the file is still the store; the board only serves it,
so a seat files and dedupes pains through MCP instead of a shell script (T1 audit coverage gap 1).

Line shapes (unchanged from scripts/pain.py):
  record:     {"id","ts","role","handle","severity","area","symptom","expected","evidence","workaround",
               "cost", "supersedes"?, "dup_of"?}
  resolution: {"id","resolves":true,"status","fixed_by","ts","note"}   (latest line per id wins)
A record with dup_of and no resolution of its own takes its original's status; filing with supersedes
also appends a `superseded` resolution for the record it replaces.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .records import pain_file

STATUSES = ("open", "fixed", "invalid", "superseded")
SEVERITIES = ("low", "medium", "high")
REQUIRED = ("severity", "area", "symptom", "expected", "evidence")
_lock = threading.Lock()


class PainError(ValueError):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code, self.hint = code, hint


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _path(path: Path | None) -> Path:
    return Path(path) if path is not None else Path(pain_file())


def load(path: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """(records in file order, latest resolution per id); legacy id-less lines get a stable derived id."""
    p = _path(path)
    records: list[dict[str, Any]] = []
    res: dict[str, dict[str, Any]] = {}
    if not p.is_file():
        return records, res
    for raw in p.read_text(encoding="utf-8-sig").splitlines():
        raw = raw.strip().lstrip("﻿")
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if d.get("resolves"):
            res[str(d.get("id"))] = d
            continue
        if not d.get("id"):
            d["id"] = "p-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{d.get('ts')}|{d.get('symptom')}").hex[:8]
        records.append(d)
    return records, res


def status_of(rec: dict[str, Any], res: dict[str, dict[str, Any]]) -> str:
    own = res.get(rec["id"])
    if own:
        return str(own.get("status") or "open")
    orig = res.get(str(rec.get("dup_of") or ""))
    return str(orig.get("status") or "open") if orig else "open"


def _row(r: dict[str, Any], res: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = {k: r.get(k) for k in ("id", "ts", "severity", "area", "role", "symptom", "dup_of", "supersedes")
           if r.get(k)}
    if isinstance(out.get("symptom"), str) and len(out["symptom"]) > 160:
        out["symptom"] = out["symptom"][:160].rstrip() + "…"
    out["status"] = status_of(r, res)
    return out


def query(*, status: str | None = "open", area: str | None = None, q: str | None = None,
          path: Path | None = None) -> list[dict[str, Any]]:
    """Compact rows, newest first. status=None or 'all' = every status; q = words in symptom/expected."""
    recs, res = load(path)
    words = [w.lower() for w in (q or "").split() if w]
    out = []
    for r in reversed(recs):
        st = status_of(r, res)
        if status not in (None, "all") and st != status:
            continue
        if area and str(r.get("area") or "").lower() != area.lower():
            continue
        hay = f"{r.get('symptom') or ''} {r.get('expected') or ''} {r.get('area') or ''}".lower()
        if words and not all(w in hay for w in words):
            continue
        out.append(_row(r, res))
    return out


def read(pain_id: str, path: Path | None = None) -> dict[str, Any]:
    recs, res = load(path)
    for r in recs:
        if r["id"] == pain_id:
            dups = [d["id"] for d in recs if d.get("dup_of") == pain_id]
            return {**r, "status": status_of(r, res), "resolution": res.get(pain_id), "duplicates": dups}
    raise PainError("not_found", f"no pain record {pain_id!r}", "pain(action='query') lists them")


def _append(p: Path, obj: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def file(record: dict[str, Any], *, role: str, handle: str, path: Path | None = None) -> dict[str, Any]:
    """Append one record (the board stamps role/handle/ts/id). dup_of/supersedes must name a record."""
    missing = [k for k in REQUIRED if not record.get(k)]
    if missing:
        raise PainError("schema", f"pain file: missing {missing}", f"required: {', '.join(REQUIRED)}")
    if record["severity"] not in SEVERITIES:
        raise PainError("schema", f"severity must be one of {SEVERITIES}", "")
    p = _path(path)
    with _lock:
        recs, res = load(p)
        known = {r["id"] for r in recs}
        for k in ("dup_of", "supersedes"):
            if record.get(k) and record[k] not in known:
                raise PainError("not_found", f"{k} names no pain record {record[k]!r}", "pain(action='query')")
        rec = {k: record.get(k) for k in (*REQUIRED, "workaround", "cost", "dup_of", "supersedes")
               if record.get(k) not in (None, "")}
        rec.update(id=f"p-{uuid.uuid4().hex[:8]}", ts=_now(), role=role, handle=handle)
        _append(p, rec)
        if rec.get("supersedes"):
            _append(p, {"id": rec["supersedes"], "resolves": True, "status": "superseded",
                        "fixed_by": rec["id"], "ts": _now(), "note": f"superseded by {rec['id']}"})
    return rec


def resolve(pain_id: str, status: str, *, by: str = "", note: str = "", path: Path | None = None) -> dict[str, Any]:
    if status not in STATUSES[1:]:
        raise PainError("schema", f"status must be one of {STATUSES[1:]}", "")
    p = _path(path)
    with _lock:
        recs, _ = load(p)
        if not any(r["id"] == pain_id for r in recs):
            raise PainError("not_found", f"no pain record {pain_id!r}", "pain(action='query')")
        line = {"id": pain_id, "resolves": True, "status": status, "fixed_by": by, "ts": _now(), "note": note}
        _append(p, line)
    return line
