"""Per-epic work helpers that outlived the asks ledger (s-aa76c83998 removed the ledger; see edp8.requirements).

- story_digest / epic_digests: status, open criteria and the last event, recomputed from the board.
- check_serves (E6): a task names the requirement or finding ids it serves.
- touched_decisions (E4): the binding decisions a criterion's text reaches.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from . import advice
from .schemas import (
    Criterion,
    Participant,
    Ticket,
    TicketKind,
    TicketStatus,
    Verdict,
)

if TYPE_CHECKING:
    from .board import Board


def _err(code: str, message: str, hint: str = ""):
    from .board import BoardError
    return BoardError(code, message, hint)


# ------------------------------------------------------------------ per-story digest (derived, never hand-written)
def story_digest(board: "Board", story: Ticket) -> dict[str, Any]:
    """status, open criteria and the last event with its id: recomputed from the board, nothing stored."""
    kids = board.children(story.id)
    ids = [story.id, *[k.id for k in kids]]
    open_c = [c.id for c in board.criteria(story.id) if c.verdict != Verdict.passed]
    for k in kids:
        open_c += [c.id for c in board.criteria(k.id) if c.verdict != Verdict.passed]
    last: tuple[int, Any] | None = None
    for tid in ids:
        for seq, ev in board.store.query_seq("event", {"subject_id": tid}, limit=1, newest_first=True):
            if last is None or seq > last[0]:
                last = (seq, ev)
    d: dict[str, Any] = {"story": story.id, "status": story.status.value, "open_criteria": open_c}
    if kids:
        d["tasks"] = {"open": sum(1 for k in kids if k.status not in (TicketStatus.done, TicketStatus.dropped)),
                      "done": sum(1 for k in kids if k.status == TicketStatus.done)}
    if last is not None:
        d["last"] = {"event": last[1].id, "kind": last[1].kind.value, "at": last[1].created_at.isoformat()}
    return d


def epic_digests(board: "Board", epic_id: str, only: set[str] | None = None) -> list[dict[str, Any]]:
    out = []
    for k in board.children(epic_id):
        if k.kind == TicketKind.story and (only is None or k.id in only):
            out.append(story_digest(board, k))
    return out


# ------------------------------------------------------------------ E6: a task names what it serves
def check_serves(board: "Board", kind: TicketKind, parent_id: str | None, serves: list[str] | None) -> list[str]:
    """E6: a `kind=task` under an epic names the requirement ids or finding ids it serves; each must belong to that
    epic's tree. Every other ticket kind carries none."""
    ids = list(dict.fromkeys(x.strip() for x in (serves or []) if x and x.strip()))
    if kind != TicketKind.task:
        if ids:
            advice.advise("serves ignored: only a task names what it serves (a story's work comes from its criteria)")
        return []
    epic_id = board._epic_id_of(parent_id) if parent_id else None
    if not ids:
        advice.advise("a task should name the requirement or finding ids it serves: ticket_create(kind=task, "
                      "serves=[requirement id | finding message id]); requirements(epic) lists the requirement ids. "
                      "Nothing behind it? it is a line in the story's fix list, not a task; created without")
        return []
    for i in ids:
        r = board.store.get("requirement", i)
        if r is not None:
            ok = r.epic_id == epic_id  # type: ignore[union-attr]
        else:
            m = board.store.get("message", i)
            ok = m is not None and m.kind.value == "finding" and board._epic_id_of(m.ticket_id) == epic_id  # type: ignore[union-attr]
        if not ok:
            raise _err("schema", f"{i!r} is not a requirement or a finding of {epic_id}",
                       "serves takes requirement ids from requirements(epic) or the id of a finding message on this epic")
    return ids


# ------------------------------------------------------------------ E4: the decisions a criterion touches
DECISION_CLIP = 240
_STOP = frozenset("that with this from have must will should when then than into only also each every never always".split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", (text or "").lower()) if w not in _STOP}


def touched_decisions(board: "Board", actor: Participant, c: Criterion) -> list[dict[str, str]]:
    """E4: `lookup(scope=epic, question=<criterion text>)`, kept to the binding decisions the text reaches. Never raises:
    a retrieval failure is an empty list, not a failed criterion_create."""
    try:
        epic = board.epic_of(board.ticket(c.ticket_id))
        res = board.lookup(actor, scope=epic.id, question=c.text)
        out = []
        for r in res.get("records", []):
            if (r.get("type") == "decision" and r.get("binding") and r.get("provenance") == "seed"
                    and _words(c.text) & _words(r.get("text") or "")):  # a match that shares a real word with the text
                out.append({"id": r["id"], "text": (r.get("text") or "")[:DECISION_CLIP]})
        return out[:5]
    except Exception:  # noqa: BLE001
        return []
