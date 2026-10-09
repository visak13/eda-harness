"""s-aa76c83998 — Mark as requirement (design-63db8a7d42 item H, owner idea m-45541e67b1; replaces the asks ledger).

A person (owner or guest) presses "Mark as requirement" on a quote card: the board records the quoted span of the
message (message id + character range) as a `Requirement` on the epic and sends no message. The epic's architect is
woken once per new requirement. It stays open until the architect links it to a criterion or to a design section
(doc id + version + heading); an epic cannot finish while one is open. Functions take the Board; Board methods delegate
here so board.py stays the one place rules are enforced.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import guest_scope, secret_screen
from .quotes import heading_at
from .schemas import (
    AskState,
    EventKind,
    Participant,
    Requirement,
    RequirementState,
    DocType,
    Role,
    TicketKind,
    TicketStatus,
)
from .store import new_id

if TYPE_CHECKING:
    from .board import Board

TEXT_CLIP = 700


def _err(code: str, message: str, hint: str = ""):
    from .board import BoardError
    return BoardError(code, message, hint)


def get(board: "Board", req_id: str) -> Requirement:
    r = board.store.get("requirement", req_id)
    if r is None:
        raise _err("not_found", f"requirement {req_id!r} does not exist", "requirements(epic_id=<epic>) lists them")
    return r  # type: ignore[return-value]


def epic_requirements(board: "Board", epic_id: str, *, state: str | None = None) -> list[Requirement]:
    where: dict[str, Any] = {"epic_id": epic_id}
    if state:
        where["state"] = state
    rows = board.store.query("requirement", where, limit=100000)
    return sorted(rows, key=lambda r: r.created_at)  # type: ignore[arg-type,return-value]


def open_ids(board: "Board", epic_id: str) -> list[str]:
    return [r.id for r in epic_requirements(board, epic_id, state=RequirementState.open.value)]


def blocked_reason(board: "Board", epic_id: str) -> str | None:
    """Why the epic cannot finish: its open requirements, named. None when there are none."""
    ids = open_ids(board, epic_id)
    if not ids:
        return None
    return f"{len(ids)} open requirement{'s' if len(ids) != 1 else ''} ({', '.join(ids[:4])}{'…' if len(ids) > 4 else ''})"


def row(board: "Board", r: Requirement) -> dict[str, Any]:
    text = r.text if len(r.text) <= TEXT_CLIP else f"{r.text[:TEXT_CLIP]}…"
    out: dict[str, Any] = {"id": r.id, "state": r.state.value, "epic": r.epic_id, "ticket": r.ticket_id,
                           "source": r.source, "char_start": r.char_start, "char_end": r.char_end, "text": text,
                           "by": r.created_by, "marked_by": r.marked_by or [r.created_by], "at": r.created_at.isoformat()}
    if r.criterion:
        out["criterion"] = r.criterion
    if r.doc_id:
        out["doc"] = {"id": r.doc_id, "version": r.doc_version, "heading": r.heading}
    if r.linked_by:
        out["linked_by"] = r.linked_by
    return out


# ------------------------------------------------------------------ mark (owner or guest)
def mark(board: "Board", actor: Participant, *, message_id: str, char_start: int | None = None,
         char_end: int | None = None, text: str | None = None) -> Requirement:
    """Record a span of a message as an open requirement of its epic. Sends no message. Idempotent: the same span of the
    same message is one requirement. A quote without a character range passes its `text`: the span is that text's
    first occurrence in the message (the whole message when it does not occur). Owner and guest only (an agent states
    a requirement in a message, not here)."""
    with board._lock, board.store.transaction():
        if actor.type != "human":
            raise _err("scope", f"{actor.role} may not mark a requirement", "the owner or a guest marks one")
        m = board.store.get("message", message_id)
        if guest_scope.is_guest(actor):
            scope = guest_scope.scope_for(board, actor)
            if m is None or scope is None or not scope.has(message_id):
                raise guest_scope.not_found("message", message_id)
            # a guest reads a message only when the read-side secret screen lets the WHOLE text through; slicing a
            # withheld source into smaller spans must not get around it (review F1)
            if secret_screen.withhold(m.text or "") != (m.text or ""):  # type: ignore[union-attr]
                raise guest_scope.not_found("message", message_id)
        if m is None:
            raise _err("not_found", f"message {message_id!r} does not exist")
        t = board.ticket(m.ticket_id) if board.store.get("ticket", m.ticket_id) is not None else None  # type: ignore[union-attr]
        if t is None:
            raise _err("scope", "a requirement is marked on a message of an epic's thread",
                       "a document thread has no epic")
        epic = board.epic_of(t)
        if epic.kind != TicketKind.epic:
            raise _err("scope", f"{t.id} is not on an epic's tree", "a quick task or a topic has no requirements")
        body = m.text or ""  # type: ignore[union-attr]
        if char_start is None and char_end is None:
            at = body.find(text) if text and text.strip() else -1
            cs, ce = (at, at + len(text)) if at >= 0 else (0, len(body))
        else:
            cs, ce = char_start, char_end
        text = body
        if cs is None or ce is None or not (0 <= cs < ce <= len(text)):
            raise _err("schema", f"char_start/char_end must satisfy 0 <= start < end <= {len(text)}",
                       "pass the quoted span's range, or neither for the whole message")
        if not text[cs:ce].strip():
            raise _err("schema", "the marked span is blank")
        for r in board.store.query("requirement", {"source": message_id}, limit=1000):
            if r.char_start == cs and r.char_end == ce:  # type: ignore[union-attr]
                if actor.id not in (r.marked_by or [r.created_by]):  # type: ignore[union-attr]
                    r.marked_by = [*(r.marked_by or [r.created_by]), actor.id]  # type: ignore[union-attr]
                    board.store.put("requirement", r)  # one requirement, every marker sees it (review F3)
                    guest_scope.invalidate()  # no event was emitted, so a guest's cached scope would still miss it
                return r  # type: ignore[return-value]
        r = Requirement(id=new_id("req"), epic_id=epic.id, ticket_id=t.id, source=message_id, char_start=cs,
                        char_end=ce, text=text[cs:ce], created_by=actor.id, marked_by=[actor.id])
        board.store.put("requirement", r)
        board._emit(r.id, EventKind.requirement_marked, {"epic": epic.id, "ticket": t.id, "source": message_id,
                                                         "by": actor.id})
        _reopen(board, epic, r)
    return r


def _reopen(board: "Board", epic: Any, r: Requirement) -> None:
    """design-63db8a7d42 item C: a new requirement reopens a finished epic (review F4). No workflow declares an edge out
    of `done` (partial → in_progress is the only declared reopen), so the board makes the move itself, the way it
    reopens an in_review epic when a story is sent back: status_changed by `board` with the trigger, and one hint to the
    architect. A dropped epic stays dropped."""
    if epic.status not in (TicketStatus.done, TicketStatus.partial):
        return
    was = epic.status
    epic.status = TicketStatus.in_progress
    board.store.put("ticket", epic)
    board._emit(epic.id, EventKind.status_changed, {"from": was.value, "to": TicketStatus.in_progress.value,
                                                    "by": "board", "trigger": f"requirement {r.id} marked"})
    board.hint_architect(epic.id, "requirement_reopened",
                         f"{r.id} was marked on {epic.id} after it was {was.value}; the epic is in_progress again. "
                         f"Link {r.id} to a criterion or a design section, or finish the epic again.", requirement=r.id)


# ------------------------------------------------------------------ link (architect, or the epic's owner)
def link(board: "Board", actor: Participant, req_id: str, *, criterion: str | None = None, doc: str | None = None,
         version: int | None = None, heading: str | None = None) -> Requirement:
    """Close a requirement: link it to a criterion of the epic, or to a design section (doc id + version + heading)
    of a doc scoped to the epic. Exactly one of the two. Linking an already-linked requirement re-points it."""
    with board._lock, board.store.transaction():
        r = get(board, req_id)
        if actor.role == Role.owner:
            oid = board.epic_owner(r.epic_id)
            if oid is not None and oid != actor.id:
                raise _err("scope", f"{r.epic_id} belongs to another owner")
        elif actor.role == Role.architect and actor.type == "agent":
            if r.epic_id not in board.my_epics(actor):
                raise _err("scope", f"{actor.id!r} does not work in {r.epic_id}", "link on your own epic's requirements")
        else:
            raise _err("scope", f"{actor.role} may not link a requirement", "the epic's architect links it")
        if bool(criterion) == bool(doc):
            raise _err("validation", "link one way: criterion=<criterion id>, or doc=<id> + version + heading",
                       "already in the design? link the section that says it; changed the design? doc_edit it, "
                       "then link the new version")
        if criterion:
            c = board.store.get("criterion", criterion)
            if c is None:
                raise _err("not_found", f"criterion {criterion!r} does not exist")
            if board.epic_of(board.ticket(c.ticket_id)).id != r.epic_id:  # type: ignore[union-attr]
                raise _err("scope", f"criterion {criterion} is not under {r.epic_id}")
            r.criterion, r.doc_id, r.doc_version, r.heading = criterion, None, None, None
        else:
            d = board.store.get("doc", str(doc))
            if d is None:
                raise _err("not_found", f"doc {doc!r} does not exist")
            if version is None or not (heading or "").strip():
                raise _err("validation", "a design link needs doc + version + heading",
                           "name the section: link(doc=<id>, version=<n>, heading='<heading text>')")
            dv = board.store.doc_version(str(doc), int(version))
            if dv is None:
                raise _err("not_found", f"doc {doc} has no version {version}")
            if d.doc_type != DocType.design:  # type: ignore[union-attr]
                raise _err("validation", f"doc {doc} is a {d.doc_type.value}, not a design",  # type: ignore[union-attr]
                           "a requirement links to a criterion or to a section of a design doc; "
                           "put the commitment in the design (doc_edit) and link that section")
            if getattr(d, "scope", None) not in (r.epic_id, *[x.id for x in board._descendants(r.epic_id)]):
                raise _err("scope", f"doc {doc} is not scoped to {r.epic_id} or its tickets")
            lines = (dv.body_md or "").replace("\r\n", "\n").split("\n")
            want = " ".join((heading or "").split()).lstrip("#").strip().lower()
            heads = {" ".join((heading_at(lines, i) or "").split()).lower() for i in range(1, len(lines) + 1)}
            heads.discard("")
            if want not in heads:
                raise _err("validation", f"{doc} v{version} has no heading {heading!r}",
                           f"headings: {'; '.join(sorted(heads))[:300]}")
            r.criterion, r.doc_id, r.doc_version, r.heading = None, str(doc), int(version), str(heading).strip()
        r.state, r.linked_by = RequirementState.linked, actor.id
        board.store.put("requirement", r)
        board._emit(r.id, EventKind.requirement_linked,
                    {"epic": r.epic_id, "criterion": r.criterion, "doc": r.doc_id, "version": r.doc_version,
                     "heading": r.heading, "by": actor.id})
    return r


# ------------------------------------------------------------------ migration of the retired asks ledger
def archive_asks(board: "Board") -> dict[str, int]:
    """Idempotent, run once at board start: every `ask` row not yet archived becomes `archived` (read-only history,
    never deleted, never converted to a requirement) and emits one ask_archived event. Criteria that covered an ask are
    left as they are. Returns counts."""
    n = {"archived": 0, "already": 0}
    with board._lock, board.store.transaction():
        for a in board.store.query("ask", {}, limit=1_000_000):
            if a.state == AskState.archived:  # type: ignore[union-attr]
                n["already"] += 1
                continue
            old = a.state.value  # type: ignore[union-attr]
            a.state = AskState.archived  # type: ignore[union-attr]
            board.store.put("ask", a)
            board._emit(a.id, EventKind.ask_archived, {"epic": a.epic_id, "from": old})  # type: ignore[union-attr]
            n["archived"] += 1
    return n
