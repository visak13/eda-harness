"""The pain log as a board record (e0cec S6, design-b6a55eed13 §4.C): ONE store, the board's database.

A pain is a `pain` row (schemas.Pain). The two jsonl files that scripts/pain.py and earlier boards wrote —
the repo's `v8/.pain/pain-points.jsonl` and the installed `<data>/.pain/pain-points.jsonl` — are IMPORTED
(deduped by id, a resolution line carried over) the first time a board reads them and again when a file is
touched; after that the board is the writer, and `pain(action=...)` reads and writes it.

Statuses: open · fixed (fixed_commit) · ticket (ticket_ref: the ticket that owns the fix) · duplicate
(dup_of) · invalid. A legacy `superseded` resolution imports as `duplicate` of the pain that replaced it.

Who resolves: the owner, the doctor and an admin, any status. An epic's architect may resolve `fixed` only,
and only when the note (or `commit`) cites a commit reachable from `main` — the row records who and which
commit. Every other seat files and reads.
"""

from __future__ import annotations

import os
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import materialise, settings
from .pain_git import commit_on_main, commit_on_remote
from .records import pain_file
from .schemas import Pain, PainStatus

STATUSES = tuple(s.value for s in PainStatus)
RESOLVE_STATUSES = (PainStatus.fixed.value, PainStatus.ticket.value, PainStatus.duplicate.value,
                    PainStatus.invalid.value)
SEVERITIES = ("low", "medium", "high")
REQUIRED = ("severity", "area", "symptom", "expected", "evidence")
_SHA = re.compile(r"\b([0-9a-f]{7,40})\b")
_PAIN_ID = re.compile(r"^p-[0-9a-f]{6,}$")
_lock = threading.RLock()
_synced: dict[str, tuple[float, ...]] = {}  # (board store token, import sources) -> their mtimes at the last import


def store_token(store: Any) -> str:
    """A per-store id that outlives no store (id() is reused after a garbage collect)."""
    tok = getattr(store, "_pain_token", None)
    if tok is None:
        tok = store._pain_token = uuid.uuid4().hex
    return tok


class PainError(ValueError):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code, self.hint = code, hint


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _when(ts: str) -> datetime:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


# ----------------------------------------------------------------------------- the jsonl import
def repo_file() -> Path | None:
    """The repo store beside the dev checkout: <v8>/.pain/pain-points.jsonl (EDP8_REPO_PAIN_FILE overrides it);
    None on an installed board, which has no checkout."""
    env = settings.env_raw("EDP8_REPO_PAIN_FILE")
    if env:
        return Path(env)
    root = materialise.checkout_root()
    return root / ".pain" / "pain-points.jsonl" if root else None


def import_sources() -> list[tuple[str, Path]]:
    """(label, path) of the files to import, in precedence order, deduped by resolved path. EDP8_PAIN_IMPORT
    (an os.pathsep list) replaces the lot; with EDP8_PAIN_FILE set only that file is read (a test or a
    private board); otherwise the settings' file (the installed store) and the repo store."""
    explicit = settings.env_raw("EDP8_PAIN_IMPORT")
    if explicit:
        cands = [(Path(p).parent.parent.name or "file", Path(p)) for p in explicit.split(os.pathsep) if p]
    elif settings.env_raw("EDP8_PAIN_FILE"):
        cands = [("file", Path(pain_file()))]
    else:
        repo = repo_file()
        cands = [("installed", Path(pain_file()))] + ([("repo", repo)] if repo else [])
    seen: set[str] = set()
    out = []
    for label, p in cands:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key not in seen:
            seen.add(key)
            out.append((label, p))
    return out


def _read_lines(p: Path) -> list[dict[str, Any]]:
    import json
    out: list[dict[str, Any]] = []
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError:
        return out
    for raw in text.splitlines():
        raw = raw.strip().lstrip("﻿")
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _legacy_id(d: dict[str, Any]) -> str:
    return "p-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{d.get('ts')}|{d.get('symptom')}").hex[:8]


def _from_line(d: dict[str, Any], label: str) -> Pain | None:
    if not d.get("symptom"):
        return None
    pid = str(d.get("id") or _legacy_id(d))
    sev = str(d.get("severity") or "low")
    dup = str(d.get("dup_of") or "")
    return Pain(id=pid, created_at=_when(str(d.get("ts") or "")), created_by=str(d.get("handle") or ""),
                severity=sev if sev in SEVERITIES else "low", area=str(d.get("area") or ""),
                symptom=str(d["symptom"]), expected=str(d.get("expected") or ""),
                evidence=str(d.get("evidence") or ""), workaround=str(d.get("workaround") or ""),
                cost=str(d.get("cost") or ""), role=str(d.get("role") or ""), handle=str(d.get("handle") or ""),
                ts=str(d.get("ts") or ""), dup_of=dup, supersedes=str(d.get("supersedes") or ""),
                status=PainStatus.duplicate if dup else PainStatus.open, source=f"import:{label}")


def _apply_line_resolution(p: Pain, r: dict[str, Any]) -> None:
    """Carry a jsonl resolution line onto `p` (the legacy status words map onto the board's five)."""
    st = str(r.get("status") or "open")
    by = str(r.get("fixed_by") or "")
    if st == "fixed":
        p.status, p.fixed_commit = PainStatus.fixed, by
    elif st == "invalid":
        p.status = PainStatus.invalid
    elif st == "superseded":
        p.status = PainStatus.duplicate
        p.dup_of = p.dup_of or (by if _PAIN_ID.match(by) else "")
    else:
        return
    p.resolved_by, p.resolved_at = "import", str(r.get("ts") or "")
    p.resolution_note = str(r.get("note") or "")[:1000]


def import_files(board: Any, sources: list[tuple[str, Path]] | None = None) -> dict[str, int]:
    """Import the jsonl stores into the board, once per record id: a record that is already a row is left
    alone, except an import-sourced row still open that a file has since resolved (scripts/pain.py).
    Returns {"added", "resolved", "seen"}; the board's own rows are never overwritten."""
    store = board.store
    recs: dict[str, Pain] = {}
    ress: dict[str, dict[str, Any]] = {}
    seen = 0
    for label, path in (sources if sources is not None else import_sources()):
        for d in _read_lines(path):
            if d.get("resolves"):
                rid = str(d.get("id"))
                if rid not in ress or str(d.get("ts") or "") >= str(ress[rid].get("ts") or ""):
                    ress[rid] = d
                continue
            p = _from_line(d, label)
            if p is None:
                continue
            seen += 1
            recs[p.id] = recs.get(p.id) or p  # the first store to name an id wins; the same id twice is one pain
    added = resolved = 0
    with _lock:
        for p in sorted(recs.values(), key=lambda x: x.ts):
            row = store.get("pain", p.id)
            if row is None:
                if p.id in ress:
                    _apply_line_resolution(p, ress[p.id])
                store.put("pain", p)
                added += 1
            elif row.status == PainStatus.open and str(row.source).startswith("import:") and p.id in ress:  # type: ignore[attr-defined]
                _apply_line_resolution(row, ress[p.id])  # type: ignore[arg-type]
                store.put("pain", row)
                resolved += 1
    return {"added": added, "resolved": resolved, "seen": seen}


def sync(board: Any, *, force: bool = False) -> dict[str, int] | None:
    """Import the jsonl stores when any of them moved since this board last read them (mtime-gated, so a
    read on every context() is a few stat calls), then route the S14 inventory's dispositions."""
    srcs = import_sources()
    stamp: list[float] = []
    for _, p in srcs:
        try:
            stamp.append(p.stat().st_mtime)
        except OSError:
            stamp.append(0.0)
    key = f"{store_token(board.store)}|{'|'.join(str(p) for _, p in srcs)}"
    if not force and _synced.get(key) == tuple(stamp):
        return None
    _synced[key] = tuple(stamp)
    out = import_files(board, srcs)
    from .pain_dispositions import apply as apply_dispositions
    out["routed"] = apply_dispositions(board)
    return out


# ----------------------------------------------------------------------------- reads
def _short(text: str, n: int = 160) -> str:
    return text if len(text) <= n else text[:n].rstrip() + "…"


def _row(p: Pain) -> dict[str, Any]:
    out: dict[str, Any] = {"id": p.id, "ts": p.ts or p.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "severity": p.severity, "area": p.area, "role": p.role, "symptom": _short(p.symptom),
                           "status": p.status.value}
    for k in ("fixed_commit", "ticket_ref", "dup_of", "supersedes"):
        if getattr(p, k):
            out[k] = getattr(p, k)
    # the public repo's page for the commit (brand.REPO_URL), only once the remote has it: an unpushed sha is a 404
    if re.fullmatch(r"[0-9a-f]{7,40}", p.fixed_commit) and commit_on_remote(p.fixed_commit):
        from .brand import REPO_URL
        out["commit_url"] = f"{REPO_URL}/commit/{p.fixed_commit}"
    return out


def _all(store: Any) -> list[Pain]:
    return store.query("pain", {}, limit=-1)  # type: ignore[return-value]


def query(store: Any, *, status: str | None = "open", area: str | None = None, q: str | None = None,
          ) -> list[dict[str, Any]]:
    """Compact rows, newest first. status=None or 'all' = every status; q = words in symptom/expected/area."""
    if status not in (None, "all") and status not in STATUSES:
        raise PainError("schema", f"status must be one of {('all', *STATUSES)}", "")
    words = [w.lower() for w in (q or "").split() if w]
    out = []
    for p in sorted(_all(store), key=lambda x: (x.ts or x.created_at.isoformat(), x.id), reverse=True):
        if status not in (None, "all") and p.status.value != status:
            continue
        if area and p.area.lower() != area.lower():
            continue
        hay = f"{p.symptom} {p.expected} {p.area}".lower()
        if words and not all(w in hay for w in words):
            continue
        out.append(_row(p))
    return out


def get(store: Any, pain_id: str) -> Pain:
    p = store.get("pain", pain_id)
    if p is None:
        raise PainError("not_found", f"no pain record {pain_id!r}", "pain(action='query') lists them")
    return p  # type: ignore[return-value]


def read(store: Any, pain_id: str) -> dict[str, Any]:
    p = get(store, pain_id)
    dups = [d.id for d in _all(store) if d.dup_of == pain_id]
    res = None
    if p.status != PainStatus.open:
        res = {"status": p.status.value, "by": p.resolved_by, "at": p.resolved_at, "note": p.resolution_note,
               "fixed_commit": p.fixed_commit, "ticket_ref": p.ticket_ref, "dup_of": p.dup_of}
    return {**p.model_dump(mode="json", exclude={"created_at"}), "resolution": res, "duplicates": dups}


# ----------------------------------------------------------------------------- writes
def file(store: Any, record: dict[str, Any], *, role: str, handle: str) -> dict[str, Any]:
    """File one record (the board stamps role/handle/ts/id). dup_of/supersedes must name a pain; a record
    with dup_of is filed as a duplicate; supersedes closes the record it replaces as its duplicate."""
    missing = [k for k in REQUIRED if not record.get(k)]
    if missing:
        raise PainError("schema", f"pain file: missing {missing}", f"required: {', '.join(REQUIRED)}")
    if record["severity"] not in SEVERITIES:
        raise PainError("schema", f"severity must be one of {SEVERITIES}", "")
    with _lock:
        for k in ("dup_of", "supersedes"):
            if record.get(k):
                get(store, str(record[k]))
        p = Pain(id=f"p-{uuid.uuid4().hex[:8]}", created_by=handle, role=role, handle=handle, ts=_now(),
                 severity=record["severity"], area=str(record["area"]), symptom=str(record["symptom"]),
                 expected=str(record["expected"]), evidence=str(record["evidence"]),
                 workaround=str(record.get("workaround") or ""), cost=str(record.get("cost") or ""),
                 dup_of=str(record.get("dup_of") or ""), supersedes=str(record.get("supersedes") or ""),
                 status=PainStatus.duplicate if record.get("dup_of") else PainStatus.open, source="board")
        store.put("pain", p)
        if p.supersedes:
            old = get(store, p.supersedes)
            old.status, old.dup_of = PainStatus.duplicate, p.id
            old.resolved_by, old.resolved_at, old.resolution_note = handle, _now(), f"superseded by {p.id}"
            store.put("pain", old)
    return _row(p) | {"id": p.id, "expected": p.expected, "evidence": p.evidence, "handle": handle}


def _commits(commit: str, note: str) -> list[str]:
    cands = [commit.strip()] if commit.strip() else []
    cands += [m for m in _SHA.findall(note or "") if re.search(r"\d", m)]
    return list(dict.fromkeys(cands))


def resolve(store: Any, pain_id: str, status: str, *, who: str, role: str, admin: bool = False,
            has_epic: bool = False, commit: str = "", ticket_id: str = "", dup_of: str = "", note: str = "",
            ) -> dict[str, Any]:
    """Resolve one pain. The owner/doctor/admin set any status; an epic's architect sets `fixed` with a
    commit reachable from main. `fixed` needs a commit (arg or a sha in the note; the owner, doctor and admin may omit it), `ticket` an existing
    ticket, `duplicate` an existing other pain."""
    if status not in RESOLVE_STATUSES:
        raise PainError("schema", f"status must be one of {RESOLVE_STATUSES}", "")
    full = admin or role in ("owner", "doctor")
    if not full:
        if role != "architect" or not has_epic:
            raise PainError("forbidden", f"role {role!r} may not resolve pain records",
                            "the owner, the doctor, an admin or an epic's architect resolves; "
                            "file a fix note on your ticket instead")
        if status != PainStatus.fixed.value:
            raise PainError("forbidden", "an architect resolves a pain as fixed only",
                            "ticket, duplicate and invalid are the owner's or the doctor's call")
    with _lock:
        p = get(store, pain_id)
        used = ""
        if status == PainStatus.fixed.value:
            cands = _commits(commit, note)
            if not cands and not full:
                raise PainError("schema", "a fixed pain names the commit that fixed it",
                                "resolve(status=fixed, commit=<sha>) or cite the sha in the note")
            used = cands[0] if cands else ""  # the owner/doctor/admin may close one with no sha to cite
            if not full:
                used, why = "", ""
                for c in cands:
                    ok, why = commit_on_main(c)
                    if ok:
                        used = c
                        break
                if not used:
                    raise PainError("precondition", f"no cited commit is reachable from main ({why})",
                                    "merge the fix first, then cite its sha; the board records who and which commit")
        if status == PainStatus.ticket.value:
            if not ticket_id or store.get("ticket", ticket_id) is None:
                raise PainError("not_found", f"ticket {ticket_id!r} does not exist",
                                "resolve(status=ticket, ticket_id=<the ticket that owns the fix>)")
        if status == PainStatus.duplicate.value:
            if not dup_of or dup_of == pain_id:
                raise PainError("schema", "a duplicate names the other pain it repeats",
                                "resolve(status=duplicate, dup_of=<pain id>)")
            get(store, dup_of)
        p.status = PainStatus(status)
        p.fixed_commit = used if status == PainStatus.fixed.value else p.fixed_commit
        p.ticket_ref = ticket_id if status == PainStatus.ticket.value else p.ticket_ref
        p.dup_of = dup_of if status == PainStatus.duplicate.value else p.dup_of
        p.resolved_by, p.resolved_at, p.resolution_note = who, _now(), (note or "")[:1000]
        store.put("pain", p)
    return _row(p) | {"resolved_by": who, "resolved_at": p.resolved_at, "note": p.resolution_note}


def open_pains(store: Any) -> list[Pain]:
    """The first-hand open pains, oldest first (what lessons_from_pains turns into lessons)."""
    return sorted((p for p in _all(store) if p.status == PainStatus.open and not p.dup_of),
                  key=lambda x: (x.ts or x.created_at.isoformat(), x.id))
