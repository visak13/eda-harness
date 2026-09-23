"""Implicit read and record (S-IMPLICIT, design-34bf11cc07 §4.5): the claim/decision/lesson records
a seat gets without asking and the board writes without being asked.

Read — `recall(store, ticket_id)`: the ticket's recall section, built from knowledge.wired_lookup with
no semantic index (FTS + the knowledge graph only), capped to RECALL_MAX one-line items. context() and
assemble_ruleset append it; a seat never calls anything for it.

Record — the board writes records itself, deterministically, on events (Board calls these hooks):
  criterion verdict with a note  → claim     (basis ruled for an owner judgment, measured otherwise)
  deviation accepted             → decision  (an answer replying to a deviation, first word accept/…)
  gate answered                  → decision
  pain filed                     → lesson    (the off-board pain file, ingested mtime-gated)
Every auto-record is created_by=AUTHOR ("board"), deduped by normalised text in its scope, and capped
per epic (AUTO_CAP); withdraw_decision / withdraw_claim is the undo. No model call, no child process, no
network anywhere in this module: a hook is plain reads and writes on the Store.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from . import knowledge
from .schemas import (Check, ClaimBasis, ClaimStatus, DecisionStatus, LessonStatus, MessageKind,
                      Participant, Role, Verdict)

_log = logging.getLogger("edp8.records")

AUTHOR = "board"  # created_by of every auto-record: how the cap counts them and a reader tells them apart
RECALL_MAX = 8  # recall items per ticket
RECALL_TEXT = 160  # chars per recall line
DECISION_TEXT = 240  # Decision.text max_length
DECISION_DETAIL = 1000  # Decision.detail max_length
ACCEPT = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?(?:accept(?:ed|s)?|approved?|agreed?|go|yes)\b", re.I)
ACCEPTERS = (Role.architect, Role.owner, Role.sme)  # who accepts a deviation
PAIN_FILE_DEFAULT = Path(__file__).resolve().parents[2] / ".pain" / "pain-points.jsonl"


def auto_cap() -> int:
    """Auto-records allowed per epic (EDP8_AUTO_RECORD_CAP, default 60)."""
    try:
        return max(0, int(os.environ.get("EDP8_AUTO_RECORD_CAP", "60")))
    except ValueError:
        return 60


def board_actor() -> Participant:
    """The participant auto-records are written as. Its role never reaches a binding gate: every
    auto-decision is non-binding and replaces nothing."""
    return Participant(id=AUTHOR, type="agent", role=Role.architect, handle=AUTHOR)


def norm(text: str) -> str:
    """Dedup key: lower-case, whitespace collapsed, trailing punctuation dropped."""
    return re.sub(r"\s+", " ", (text or "").strip().lower()).rstrip(" .;:")


def one_line(text: str, width: int) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip())
    return s if len(s) <= width else s[: width - 1].rstrip() + "…"


# ----------------------------------------------------------------------------- read
def recall(store: Any, ticket_id: str, *, question: str | None = None) -> dict[str, Any]:
    """The ticket's recall section: `{items: [{id, type, text}], receipt}`. Three knowledge.wired_lookup
    passes with index=None (FTS + graph, no embedder, no model): from the ticket node (its own claims and
    decisions), for the ticket's title (the epic's matching records + cross-epic lessons), and from the
    epic node (the epic-wide rulings). Merged in that order, deduped, capped to RECALL_MAX one-liners."""
    t = store.get("ticket", ticket_id)
    if t is None:
        return {"items": [], "receipt": {"returned": 0, "why": f"no ticket {ticket_id}"}}
    q = question or t.title
    epic = knowledge._epic_id_of(store, ticket_id)
    passes = [knowledge.wired_lookup(store, None, ticket_id, id=ticket_id),
              knowledge.wired_lookup(store, None, ticket_id, question=q)]
    if epic and epic != ticket_id:
        passes.append(knowledge.wired_lookup(store, None, ticket_id, id=epic))
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for got in passes:
        for r in got.get("records", []):
            if r.get("section") == "excerpt" or r.get("type") not in ("decision", "claim", "lesson"):
                continue
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            items.append({"id": r["id"], "type": r["type"], "text": one_line(r.get("text", ""), RECALL_TEXT)})
    cut = max(0, len(items) - RECALL_MAX) + sum(sum((g.get("receipt", {}).get("cut_by_type") or {}).values())
                                                for g in passes)
    items = items[:RECALL_MAX]
    return {"items": items,
            "receipt": {"question": one_line(q, 80), "returned": len(items), "cut": cut, "cap": RECALL_MAX,
                        "more": "lookup(scope=<ticket>, question=…) for the full pack" if cut else ""}}


# ----------------------------------------------------------------------------- record: shared guards
def _epic(store: Any, scope: str) -> str:
    return knowledge._epic_id_of(store, scope) or scope


def _auto_count(store: Any, epic: str) -> int:
    n = 0
    for typ in ("decision", "claim"):
        for r in store.query(typ, {}, limit=-1):  # created_by is not an indexed column
            if r.created_by == AUTHOR and _epic(store, r.scope) == epic:
                n += 1
    return n


def _duplicate(store: Any, typ: str, epic: str, text: str) -> str | None:
    """The id of a live record of this type in this epic with the same normalised text, else None."""
    key = norm(text)
    dead = {DecisionStatus.withdrawn, DecisionStatus.replaced, ClaimStatus.withdrawn}
    for r in store.query(typ, {}, limit=-1):
        if getattr(r, "status", None) in dead:
            continue
        if norm(r.text) == key and _epic(store, r.scope) == epic:
            return r.id
    return None


def _admit(store: Any, typ: str, scope: str, text: str) -> tuple[bool, str]:
    epic = _epic(store, scope)
    dup = _duplicate(store, typ, epic, text)
    if dup:
        return False, f"duplicate of {dup}"
    cap = auto_cap()
    if _auto_count(store, epic) >= cap:
        return False, f"epic {epic} is at the auto-record cap ({cap})"
    return True, ""


# ----------------------------------------------------------------------------- record: the four paths
def claim_from_verdict(board: Any, actor: Participant, criterion: Any, note: str) -> Any | None:
    """criterion verdict with a note → claim. basis=ruled when the owner rules a judgment check
    (look|verdict), measured otherwise (qa, or a command/path check the checker ran)."""
    note = (note or "").strip()
    if not note or criterion.verdict == Verdict.pending:
        return None
    verdict = criterion.verdict.value if hasattr(criterion.verdict, "value") else str(criterion.verdict)
    text = f"{criterion.id} {verdict}: {one_line(note, 400)}"
    ok, why = _admit(board.store, "claim", criterion.ticket_id, text)
    if not ok:
        _log.info("auto-claim skipped for %s: %s", criterion.id, why)
        return None
    owner_judgment = actor.role == Role.owner and criterion.check in (Check.look, Check.verdict)
    basis = ClaimBasis.ruled if owner_judgment else ClaimBasis.measured
    evidence = [x for x in (criterion.evidence_ref, criterion.id) if x]
    status = ClaimStatus.confirmed if criterion.verdict == Verdict.passed else ClaimStatus.open
    return board.record_claim(board_actor(), scope=criterion.ticket_id, text=text, basis=basis,
                              evidence=evidence, status=status)


def decision_from_deviation(board: Any, actor: Participant, answer: Any) -> Any | None:
    """An `answer` replying to a `deviation`, sent by the architect/owner/sme and opening with an
    acceptance word, → decision scoped to the deviation's ticket, sourced from the answer."""
    if answer.kind != MessageKind.answer or not answer.reply_to or actor.role not in ACCEPTERS:
        return None
    if not ACCEPT.match(answer.text or ""):
        return None
    dev = board.store.get("message", answer.reply_to)
    if dev is None or dev.kind != MessageKind.deviation:
        return None
    text = one_line(f"Deviation accepted: {dev.text}", DECISION_TEXT)
    ok, why = _admit(board.store, "decision", dev.ticket_id, text)
    if not ok:
        _log.info("auto-decision (deviation %s) skipped: %s", dev.id, why)
        return None
    detail = one_line(f"{actor.id} accepted {dev.id}: {answer.text}", DECISION_DETAIL)
    return board.record_decision(board_actor(), scope=dev.ticket_id, text=text, detail=detail,
                                 binding=False, source=answer.id)


def decision_from_gate(board: Any, actor: Participant, ticket_id: str, gate: str, answer: str,
                       source: str | None) -> Any | None:
    """gate answered → decision on the gated ticket, sourced from the board's answer message."""
    g = gate.value if hasattr(gate, "value") else str(gate)
    text = one_line(f"{g} gate on {ticket_id} answered by {actor.id}: {answer}", DECISION_TEXT)
    ok, why = _admit(board.store, "decision", ticket_id, text)
    if not ok:
        _log.info("auto-decision (gate %s on %s) skipped: %s", g, ticket_id, why)
        return None
    return board.record_decision(board_actor(), scope=ticket_id, text=text,
                                 detail=one_line(answer, DECISION_DETAIL), binding=False, source=source)


def pain_file() -> Path:
    return Path(os.environ.get("EDP8_PAIN_FILE") or PAIN_FILE_DEFAULT)


def read_pains(path: Path) -> list[dict[str, Any]]:
    """Open, first-hand pain records (latest resolution per id wins; dup_of records fold into theirs)."""
    records: list[dict[str, Any]] = []
    resolved: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
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
            resolved[str(d.get("id"))] = str(d.get("status") or "")
        elif d.get("id") and d.get("symptom") and not d.get("dup_of"):
            records.append(d)
    return [d for d in records if resolved.get(d["id"], "open") == "open"]


_pain_seen: dict[str, float] = {}  # pain file path → mtime already ingested (per board process)


def lessons_from_pains(board: Any, path: Path | None = None) -> list[Any]:
    """pain filed → lesson: one lesson per open pain (domain=area, topic=symptom head, evidence=[pain
    id]), skipped when a lesson already names that pain or carries the same text. Re-reads the file
    only when its mtime moved. Lessons are cross-epic, so the cap is global: auto_cap() pain lessons."""
    p = path or pain_file()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return []
    if _pain_seen.get(str(p)) == mtime:
        return []
    _pain_seen[str(p)] = mtime
    lessons = board.store.query("lesson", {}, limit=-1)
    known = {e for le in lessons for e in (le.evidence or [])}
    texts = {norm(le.text) for le in lessons if le.status == LessonStatus.live}
    auto = sum(1 for le in lessons if le.created_by == AUTHOR)
    out = []
    for d in read_pains(p):
        if d["id"] in known:
            continue
        text = one_line(d["symptom"], 400)
        if d.get("expected"):
            text = one_line(f"{text} — expected: {d['expected']}", 600)
        if norm(text) in texts:
            continue
        if auto >= auto_cap():
            _log.info("pain lessons at the cap (%d); %s not recorded", auto_cap(), d["id"])
            break
        le = board.record_lesson(board_actor(), domain=str(d.get("area") or "other"),
                                 topic=one_line(d["symptom"], 60), text=text, evidence=[d["id"]])
        out.append(le)
        texts.add(norm(text))
        auto += 1
    return out


def safely(fn: Any, *args: Any, **kw: Any) -> Any:
    """Run one hook; an auto-record never breaks the event that triggered it."""
    try:
        return fn(*args, **kw)
    except Exception:  # noqa: BLE001
        _log.exception("auto-record %s failed", getattr(fn, "__name__", fn))
        return None
