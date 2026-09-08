"""Pure view derivations over Board+Participant (design §4.1 "Backend views").

Extracted from ui.py so BOTH the legacy HTML renderer (ui.py) and the JSON API
(api_views.py) compute a view exactly once. Every function is pure over a Board and
(where identity matters) a Participant; it returns JSON-friendly data (enums as their
`.value`, datetimes as isoformat) — never HTML, except `render_markdown`/`doc_page`
which return sanitised document HTML the two renderers share.

Strategy Phase 2 (characterise-then-extract): tests/test_views.py pins the legacy HTML
BEFORE this module existed; ui.py now sources its derivations here with identical output.
"""

from __future__ import annotations

from typing import Any

import markdown as _markdown
import nh3

from .avatar_preferences import avatar_preferences_path, load_avatar_preferences
from .avatars import avatar_id_for
from .board import Board, BoardError
from .schemas import (
    EventKind,
    MessageKind,
    Participant,
    Role,
    TicketKind,
    TicketStatus,
    Verdict,
)

_TERMINAL = (TicketStatus.done, TicketStatus.partial, TicketStatus.dropped)

# ------------------------------------------------------------------ markdown / sanitiser

# nh3 (Rust/ammonia) allowlist sanitiser (design §18.1, S21) — replaces the old regex strip.
# The renderer is an ALLOWLIST: only these tags/attributes survive and only these URL schemes
# on links; everything else (scripts, inline handlers, iframes, SVG/MathML, javascript:/data:
# hrefs, encoded handlers, malformed HTML) is dropped, whatever shape the input takes.
_ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "br", "hr", "blockquote", "pre", "code",
    "strong", "em", "b", "i", "del", "ins", "sub", "sup", "a", "img", "ul", "ol", "li",
    "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "span", "div",
}
_ALLOWED_ATTRS = {"a": {"href", "title"}, "img": {"src", "alt", "title"},
                  "td": {"align"}, "th": {"align"}, "code": {"class"}}
_URL_SCHEMES = {"http", "https", "mailto"}


def render_markdown(body: str) -> str:
    """Render doc markdown to HTML (fenced code + tables), then sanitise with an nh3 allowlist
    (design §18.1): only safe tags/attributes survive, links only http/https/mailto. Docs are
    fleet-authored, but the browser gets no excuses — a poisoned doc cannot ship a script,
    handler, iframe, SVG/MathML payload or javascript:/data: link to a reader."""
    rendered = _markdown.markdown(body or "", extensions=["fenced_code", "tables", "sane_lists"])
    return nh3.clean(rendered, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS,
                     url_schemes=_URL_SCHEMES, link_rel="noopener noreferrer")


# ------------------------------------------------------------------ small derivations


def seat_state(board: Board, pid: str | None) -> str | None:
    """Latest session state for a participant (alive|parked|dead|stalled); None = never had
    a shell. The single source ui.py and the API both read (was ui.py's local _seat_state)."""
    if not pid:
        return None
    return board.seat_state(pid)


def search_ticket_ids(board: Board, q: str, *, types: set[str] | None = None,
                      limit: int = 500) -> list[str]:
    """Ticket ids matching a full-text query, best-first — the one place ui.py's filters and
    the API reach FTS (was three inline board.store.fts_search calls in ui.py)."""
    return [h["id"] for h in board.store.fts_search(q, types=types or {"ticket"}, limit=limit)]


def unresolved_mentions(board: Board, text: str) -> list[str]:
    """@handles in text that match no participant — the message posts, but nobody is woken
    for these. De-duped, order preserved (parity with ui.py's _MENTION_RX check)."""
    from .board import _MENTION_RX

    bad = [h for h in _MENTION_RX.findall(text or "") if not _participant_by_handle(board, h)]
    return list(dict.fromkeys(bad))


def _participant_by_handle(board: Board, handle: str) -> Participant | None:
    try:
        return board.participant(f"@{handle}")
    except BoardError:
        return None


def _participant(board: Board, pid: str | None) -> Participant | None:
    try:
        return board.store.get("participant", pid) if pid else None  # type: ignore[return-value]
    except Exception:
        return None


# ------------------------------------------------------------------ avatars (mtime-cached prefs)

_prefs_cache: dict[str, Any] = {"key": None, "value": {}}


def _prefs() -> dict[str, str]:
    """Avatar preferences, reloaded when ui-avatars.json's mtime changes (design §4.1 fixes the
    per-process cache at ui.py:145 — a saved avatar now shows without a board restart)."""
    path = avatar_preferences_path()
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        key = (str(path), None)
    if _prefs_cache["key"] != key:
        _prefs_cache["key"] = key
        _prefs_cache["value"] = load_avatar_preferences(path)
    return _prefs_cache["value"]


def avatar_for(board: Board, pid: str | None) -> dict[str, Any]:
    """Avatar identity for a participant, prefs mtime-cached: for a human the chosen (or
    hash-derived) avatar_id; for an agent its role/model; system for the unknown. The SVG
    itself is rendered by avatars.py from this identity (HTML side) or the svg endpoint (API)."""
    p = _participant(board, pid)
    if p is None:
        return {"kind": "system", "avatar_id": "system", "role": None, "model": None}
    if p.type == "human":
        return {"kind": "human", "avatar_id": avatar_id_for(p, _prefs()),
                "role": p.role.value, "model": None}
    return {"kind": "role", "avatar_id": None, "role": p.role.value, "model": p.model}


# ------------------------------------------------------------------ sign-off / verdict


def pending_signoffs(board: Board, viewer: Participant) -> list[tuple[Any, Any, Any]]:
    """(criterion, ticket, evidence_doc|None) for every owner-checked pending criterion with
    evidence, inside the viewer's owner scope. Empty for a non-owner. The doc awaiting the
    human's sign-off (design §14) — was ui.py's inline _V.pending scan."""
    if viewer.role != Role.owner:
        return []
    out: list[tuple[Any, Any, Any]] = []
    for c in board.store.query("criterion", {"verdict": Verdict.pending}, limit=300):
        if c.checked_by != "owner" or not c.evidence_ref:
            continue
        tk = board.store.get("ticket", c.ticket_id)
        if tk is None or tk.status in _TERMINAL:
            continue
        if not board._owner_scope(viewer, tk.id):
            continue
        out.append((c, tk, board.store.get("doc", c.evidence_ref)))
    return out


def signoff_criterion_for_doc(board: Board, viewer: Participant, doc: Any) -> Any | None:
    """The pending owner-checked criterion holding THIS doc as evidence (any version), for the
    doc reader's Approve/Needs-work card (design §14). None for a non-owner or when none apply."""
    if viewer.type != "human" or viewer.role != Role.owner:
        return None
    for c in board.store.query("criterion", {"verdict": Verdict.pending}, limit=300):
        if c.checked_by != "owner" or c.evidence_ref != doc.id:
            continue
        tk = board.store.get("ticket", c.ticket_id)
        if tk is None or tk.status in _TERMINAL:
            continue
        if not board._owner_scope(viewer, tk.id):  # §14 finding 1: owner A's card stays off owner B's reader
            continue
        return c
    return None


def record_verdict(board: Board, actor: Participant, *, criterion_id: str, verdict: str,
                   note: str = "", ticket_id: str | None = None,
                   evidence_version: int | None = None, stale_ok: bool = False) -> dict[str, Any]:
    """One-click ruling shared by /ui/me/verdict and POST /v1/me/verdict (design §14): record
    the verdict (with the doc version it names) and, when a note is given, post a
    '[sign-off pass|fail] note' message to the ticket's assignee and deliver it. Returns the
    criterion and the message id (or None)."""
    from . import delivery

    v = Verdict(verdict)
    c = board.criterion_update(actor, criterion_id.strip(), verdict=v,
                               evidence_version=evidence_version, stale_ok=stale_ok)
    msg_id = None
    if note.strip() and ticket_id and ticket_id.strip():
        tk = board.store.get("ticket", ticket_id.strip())
        m = board.message_send(actor, ticket_id=ticket_id.strip(), to=getattr(tk, "assignee", None),
                               kind=MessageKind.answer if v == Verdict.passed else MessageKind.finding,
                               text=f"[sign-off {v.value}] {note.strip()}")
        delivery.after_message(board, actor.id, m)
        msg_id = m.id
    return {"criterion": c.model_dump(mode="json"), "message": msg_id}


# ------------------------------------------------------------------ people / conversations


def _roster(board: Board, viewer: Participant) -> list[dict[str, Any]]:
    """Ordered participants a viewer can reach: humans first (by handle), then LIVE/parked agent
    seats; empty-chair base-role stubs and closed seats are omitted (tagging them wakes nobody).
    Each entry is self-describing so the recipient picker, @autocomplete and who-can-I-reach all
    read one list (design §13, ui.py parity)."""
    out: list[dict[str, Any]] = []
    for c in sorted(board.store.query("participant", {}), key=lambda c: (c.type != "human", c.handle or "")):
        if not c.handle or c.handle.startswith(("__", "wt-")):
            continue
        if c.type == "human":
            out.append({"id": c.id, "handle": c.handle, "type": "human", "role": c.role.value,
                        "seat_ticket": None, "seat_state": None, "label": "person", "self": c.id == viewer.id})
            continue
        state = seat_state(board, c.id)
        if state not in ("alive", "parked"):
            continue
        tid = c.id.split(".", 1)[1] if "." in c.id else None
        out.append({"id": c.id, "handle": c.handle, "type": "agent", "role": c.role.value,
                    "seat_ticket": tid, "seat_state": state, "label": f"{c.role.value} seat", "self": False})
    return out


def people_for(board: Board, viewer: Participant) -> list[dict[str, Any]]:
    """The reachable roster minus the viewer (the recipient picker / @autocomplete source).
    who-can-I-reach in the HTML includes the viewer's own row; the JSON list is recipients."""
    return [p for p in _roster(board, viewer) if not p["self"]]


def conversations_for(board: Board, viewer: Participant) -> list[dict[str, Any]]:
    """One row per ticket that involves the viewer — unanswered asks first (unread), then the
    viewer's open tickets by recent traffic. Each row carries the last message (design §18.2)."""
    ctx_asks = board.inbox(viewer)
    ask_tids: list[str] = []
    for m in ctx_asks:
        if m["ticket_id"] not in ask_tids:
            ask_tids.append(m["ticket_id"])
    convo_ids = list(ask_tids)
    for t in board.my_tickets(viewer):
        if t.status not in _TERMINAL and t.id not in convo_ids:
            convo_ids.append(t.id)
    rows: list[dict[str, Any]] = []
    for tid in convo_ids[:14]:
        tk = board.store.get("ticket", tid)
        if tk is None:
            continue
        last = board.thread(tid, limit=1)
        lm = last[-1] if last else None
        rows.append({"ticket_id": tid, "title": tk.title, "epic_id": tk.epic_id,
                     "unread": tid in ask_tids,
                     "last": ({"by": lm.created_by, "text": lm.text[:120],
                               "at": lm.created_at.isoformat()} if lm else None)})
    return rows


def summary_for(board: Board, viewer: Participant) -> dict[str, Any]:
    """Identity + the counts the shell chrome shows: waiting-on-you, open gates, conversations,
    plus the avatar id and the board's newest seq (design §4.1)."""
    asks = board.inbox(viewer)
    gates = [g for _t, g in _owner_gates(board, viewer)]
    return {"participant": viewer.model_dump(mode="json"),
            "avatar_id": avatar_for(board, viewer.id)["avatar_id"],
            "counts": {"waiting_on_you": len(asks), "open_gates": len(gates),
                       "conversations": len(conversations_for(board, viewer))},
            "last_seq": board.store.max_seq()}


def _owner_gates(board: Board, viewer: Participant) -> list[tuple[str, Any]]:
    """(ticket_id, gate_event) open gates the owner viewer can answer, across their owned epics'
    subtrees. Empty for a non-owner (design §4.1 owner scoping)."""
    if viewer.role != Role.owner:
        return []
    out: list[tuple[str, Any]] = []
    for t in board.store.query("ticket", {"kind": TicketKind.epic}, limit=200):
        if t.status in _TERMINAL or not board._owner_scope(viewer, t.id):
            continue
        for sub in (t, *board._descendants(t.id)):
            for ev in board.open_gates(sub.id):
                out.append((sub.id, ev))
    return out


def decisions_for(board: Board, viewer: Participant) -> dict[str, Any]:
    """The Decisions home (design §4.1): sign-offs the viewer must rule, questions in their
    inbox, and open gates. A non-owner gets empty signoffs and gates."""
    signoffs = []
    for c, tk, doc in pending_signoffs(board, viewer):
        epic = board.epic_of(tk)
        signoffs.append({
            "criterion": {"id": c.id, "text": c.text, "check": c.check.value,
                          "checked_by": c.checked_by, "verdict": c.verdict.value,
                          "evidence_ref": c.evidence_ref,
                          "evidence_version": getattr(c, "evidence_version", None)},
            "ticket": {"id": tk.id, "title": tk.title, "epic_id": epic.id,
                       "epic_title": epic.title, "assignee": tk.assignee},
            "doc": ({"id": doc.id, "title": doc.title, "doc_type": doc.doc_type.value,
                     "version": doc.version} if doc else None),
            "excerpt": (getattr(doc, "body_md", "") or "")[:300].strip()})
    questions = []
    for m in board.inbox(viewer):
        asker = _participant(board, m["created_by"])
        questions.append({**m, "asker": {
            "type": getattr(asker, "type", "agent") if asker else "agent",
            "role": getattr(getattr(asker, "role", None), "value", "unknown") if asker else "unknown",
            "seat_state": seat_state(board, m["created_by"]),
            "note": _asker_note(board, m["created_by"])}})
    gates = []
    for tid, ev in _owner_gates(board, viewer):
        gates.append({"ticket_id": tid, "gate": ev.data.get("gate"), "by": ev.data.get("by"),
                      "note": ev.data.get("note"), "opened_at": ev.created_at.isoformat(),
                      "epic": board.epic_of(board.ticket(tid)).id})
    return {"signoffs": signoffs, "questions": questions, "gates": gates,
            "counts": {"signoffs": len(signoffs), "questions": len(questions), "gates": len(gates)}}


def _asker_note(board: Board, pid: str) -> str:
    asker = _participant(board, pid)
    if asker and asker.type == "human":
        return "A person will see your answer on their page."
    state = seat_state(board, pid)
    if state in ("alive", "parked"):
        return f"Its shell is {state}; your answer wakes it."
    return "Its shell has closed; your answer stays with the project for the next shell."


def resolved_for(board: Board, viewer: Participant, limit: int = 30) -> list[dict[str, Any]]:
    """The viewer's recent rulings — criterion verdicts, gate answers and answers they posted —
    newest first, so a decision made is visible after it leaves the inbox (design §4.1)."""
    out: list[dict[str, Any]] = []
    for _s, e in board.replay(viewer, 0):
        d = e.data
        if e.kind == EventKind.criterion_checked and d.get("by") == viewer.id:
            out.append({"at": e.created_at.isoformat(), "kind": "verdict", "ticket_id": e.subject_id,
                        "criterion": d.get("criterion"), "verdict": d.get("verdict")})
        elif e.kind == EventKind.gate_answered and d.get("by") == viewer.id:
            out.append({"at": e.created_at.isoformat(), "kind": "gate", "ticket_id": e.subject_id,
                        "gate": d.get("gate"), "answer": d.get("answer")})
    out.sort(key=lambda r: r["at"], reverse=True)
    return out[:limit]


# ------------------------------------------------------------------ waiting_reason


def waiting_reason(board: Board, t: Any) -> dict[str, Any]:
    """Why a ticket is not moving, as a single ordered decision (design §4.2): open gate →
    pending owner request → explicit blocks link → blocked status → latest recorded status.
    0/0 criteria yields 'None defined'. Seat PRESENCE is returned as its own field, never
    folded into the reason (silence is never rendered as a status)."""
    crits = board.criteria(t.id)
    latest = None
    evs = board.store.query("event", {"subject_id": t.id, "kind": EventKind.status_recorded})
    if evs:
        latest = max(evs, key=lambda e: e.created_at).data.get("status")
    presence = seat_state(board, t.assignee) if t.assignee else None

    gates = board.open_gates(t.id)
    if gates:
        reason = f"open gate: {gates[0].data.get('gate')}"
    elif _pending_owner_request(board, t):
        reason = "waiting on the owner to answer"
    elif (blocked := [b.id for b in board.blockers(t.id) if b.status != TicketStatus.done]):
        reason = f"blocked by {', '.join(blocked)}"
    elif t.status == TicketStatus.blocked:
        reason = "blocked"
    elif latest:
        reason = latest
    elif not crits:
        reason = "None defined"
    else:
        passed = sum(c.verdict == Verdict.passed for c in crits)
        reason = f"{passed}/{len(crits)} criteria passed"
    return {"reason": reason, "presence": presence, "latest_status": latest}


def _pending_owner_request(board: Board, t: Any) -> bool:
    owner = board.epic_owner(t.id)
    if not owner:
        return False
    for m in board.store.query("message", {"ticket_id": t.id, "to": owner,
                                           "kind": MessageKind.question}, limit=50):
        if not board.store.query("message", {"reply_to": m.id, "kind": MessageKind.answer}, limit=1):
            return True
    return False


# ------------------------------------------------------------------ epics / tickets / epic


def _crit_counts(board: Board, ticket_id: str) -> dict[str, int]:
    crits = board.criteria(ticket_id)
    passed = sum(c.verdict == Verdict.passed for c in crits)
    failed = sum(c.verdict == Verdict.failed for c in crits)
    return {"passed": passed, "failed": failed, "pending": len(crits) - passed - failed,
            "total": len(crits)}


def epics_summary(board: Board, viewer: Participant | None = None, *, status: str | None = None,
                  q: str | None = None) -> list[dict[str, Any]]:
    """One row per epic for the Projects list (design §4.1): criteria tally, open gates,
    waiting_reason, assigned seats and latest status. Honours the same status/q filters the
    legacy /ui page uses."""
    rows = board.store.query("ticket", {"kind": TicketKind.epic}, limit=5000)
    if status == "open":
        rows = [t for t in rows if t.status not in _TERMINAL]
    elif status:
        rows = [t for t in rows if t.status.value == status]
    if q:
        hit = set(search_ticket_ids(board, q))
        rows = [t for t in rows if t.id in hit]
    out = []
    for t in rows:
        seats = sorted({k.assignee for k in board._descendants(t.id) if k.assignee}
                       | ({t.assignee} if t.assignee else set()))
        out.append({"id": t.id, "title": t.title, "status": t.status.value,
                    "created_at": t.created_at.isoformat(), "criteria": _crit_counts(board, t.id),
                    "open_gates": sum(len(board.open_gates(s.id)) for s in (t, *board._descendants(t.id))),
                    "waiting_reason": waiting_reason(board, t), "assigned_seats": seats,
                    "latest_status": waiting_reason(board, t)["latest_status"]})
    return out


def tickets_table(board: Board, *, epic: str | None = None, status: str | None = None,
                  kind: str | None = None, work_type: str | None = None, assignee: str | None = None,
                  tag: str | None = None, q: str | None = None) -> dict[str, Any]:
    """The cross-epic tickets table with the seven legacy filters, criteria counts and
    blocked-by, matching /ui/tickets ordering and default open-only behaviour (design §4.1)."""
    rows = board.store.query("ticket", {"epic_id": epic or None, "status": status or None,
                                        "kind": kind or None, "work_type": work_type or None}, limit=5000)
    if assignee:
        rows = [t for t in rows if (t.assignee or "").find(assignee) >= 0]
    if tag:
        rows = [t for t in rows if tag in (t.tags or [])]
    if q:
        order = {i: n for n, i in enumerate(search_ticket_ids(board, q))}
        rows = sorted([t for t in rows if t.id in order], key=lambda t: order[t.id])
    else:
        rows = sorted(rows, key=lambda t: t.created_at, reverse=True)
    if not (status or q or epic):
        rows = [t for t in rows if t.status not in _TERMINAL]
    out = []
    for t in rows[:500]:
        out.append({"id": t.id, "epic_id": t.epic_id if t.epic_id and t.epic_id != t.id else None,
                    "title": t.title, "kind": t.kind.value, "work_type": t.work_type.value,
                    "status": t.status.value, "assignee": t.assignee, "tags": t.tags or [],
                    "criteria": _crit_counts(board, t.id),
                    "blocked_by": [b.id for b in board.blockers(t.id) if b.status != TicketStatus.done]})
    return {"rows": out, "count": len(rows)}


def epic_page(board: Board, epic_id: str) -> dict[str, Any]:
    """One epic's board view (design §4.1): the kanban tree, counts, thread, linked docs and
    open gates — the data behind /ui/epic and /v1/epics/{id}/page."""
    bd = board.board(epic_id)
    thread = [_msg(m) for m in board.thread(epic_id, limit=100)]
    docs = [board._doc_summary(d) for d in board.store.query("doc", {"scope": epic_id}, limit=100)]
    return {"board": bd, "words": bd.get("words"), "counts": bd.get("counts"),
            "thread": thread, "docs": docs, "open_gates": bd.get("open_gates", [])}


def ticket_page(board: Board, ticket_id: str) -> dict[str, Any]:
    """One ticket's page data (design §4.1): the record, its criteria, linked docs with the
    relation, the thread, and the resolved assignee — behind /ui/ticket and /v1/tickets/{id}/page."""
    t = board.ticket(ticket_id)
    crits = board.criteria(ticket_id)
    rel_by_doc = {lk.to_id: lk.relation.value for lk in board.links(from_id=ticket_id)}
    docs = [{**board._doc_summary(d), "relation": rel_by_doc.get(d.id)}
            for d in board.linked_docs(ticket_id)]
    assignee = _participant(board, t.assignee)
    return {"ticket": t.model_dump(mode="json"), "epic_id": board.epic_of(t).id,
            "criteria": [{"id": c.id, "text": c.text, "check": c.check.value,
                          "checked_by": c.checked_by, "verdict": c.verdict.value,
                          "evidence_ref": c.evidence_ref,
                          "evidence_version": getattr(c, "evidence_version", None)} for c in crits],
            "docs": docs, "thread": [_msg(m) for m in board.thread(ticket_id, limit=100)],
            "assignee": {"id": t.assignee, "handle": getattr(assignee, "handle", None),
                         "role": getattr(getattr(assignee, "role", None), "value", None)},
            "waiting_reason": waiting_reason(board, t)}


def _msg(m: Any) -> dict[str, Any]:
    return {"id": m.id, "by": m.created_by, "to": m.to, "kind": m.kind.value, "text": m.text,
            "at": m.created_at.isoformat(), "reply_to": m.reply_to}


# ------------------------------------------------------------------ doc / activity / library


def doc_page(board: Board, doc_id: str, viewer: Participant | None = None, *,
             version: int | None = None) -> dict[str, Any]:
    """A document rendered for reading (design §4.1/§14): sanitised HTML, the version list, and
    the viewer's pending sign-off criterion when one references this doc."""
    d = board.doc(doc_id, version)
    signoff = signoff_criterion_for_doc(board, viewer, d) if viewer else None
    return {"id": d.id, "title": d.title, "doc_type": d.doc_type.value, "scope": d.scope,
            "owner_role": d.owner_role.value, "version": d.version,
            "versions": board.store.doc_versions(doc_id), "html": render_markdown(d.body_md),
            "signoff_criterion": ({"id": signoff.id, "text": signoff.text,
                                   "ticket_id": signoff.ticket_id} if signoff else None)}


def feed_line(e: Any) -> str:
    """One human-readable line for an event (design §4.1) — the single formatter ui.py's
    activity page and the API's activity feed share."""
    d = e.data
    if e.kind == "message_sent":
        return f"{d.get('from')} → {d.get('to') or 'thread'}: {d.get('text', '')}"
    if e.kind == "status_changed":
        return f"moved {d.get('from', '?')} → {d.get('to', d.get('note', '?'))}"
    if e.kind == "gate_opened":
        return f"needs your answer: {d.get('gate')} gate ({d.get('note') or 'no note'})"
    if e.kind == "gate_answered":
        return f"{d.get('gate')} gate answered by {d.get('by')}: {d.get('answer', '')}"
    if e.kind in ("shell_dead", "shell_stalled"):
        verb = "closed" if d.get("clean") else ("stalled" if str(e.kind).endswith("stalled") else "died")
        return f"{d.get('participant')}'s shell {verb} — {d.get('reason') or 'no reason recorded'}"
    if e.kind == "assigned":
        return f"assigned to {d.get('assignee')}"
    if e.kind == "criterion_checked":
        who = f"{d.get('by')} ({'human' if d.get('by_type') == 'human' else 'agent'})"
        return f"criterion {d.get('criterion')} verdict {d.get('verdict')} by {who}"
    return str({k: v for k, v in d.items() if k != "mentions"})[:200]


def activity_for(board: Board, viewer: Participant, limit: int = 120) -> list[dict[str, Any]]:
    """Everything relevant to the viewer, newest first, grouped by day (design §4.1) — the
    data behind /ui/activity and /v1/activity."""
    feed = board.replay(viewer, 0)[-limit:]
    by_day: dict[str, list[dict[str, Any]]] = {}
    for _s, e in reversed(feed):
        by_day.setdefault(e.created_at.strftime("%A %d %b"), []).append(
            {"line": feed_line(e), "subject_id": e.subject_id, "kind": e.kind.value,
             "at": e.created_at.isoformat()})
    return [{"day": day, "events": evs} for day, evs in by_day.items()]


def library_for(board: Board, epic_id: str | None = None) -> dict[str, Any]:
    """The knowledge library (design §4.1): docs, non-staged artifacts and links, optionally
    scoped to one epic. Staged upload artifacts never appear (S21). §14 finding 9: when an epic
    is named the scope covers artifacts and links too, not docs alone — an artifact belongs to the
    epic when a link joins it to an in-epic ticket/doc, and a link when either end is in scope."""
    doc_filter = {"scope": epic_id} if epic_id else {}
    docs = [board._doc_summary(d) for d in board.store.query("doc", doc_filter, limit=500)]
    arts = [a for a in board.store.query("artifact", {}, limit=500) if not getattr(a, "staged", False)]
    links = list(board.links())
    if epic_id:
        tk = board.store.get("ticket", epic_id)
        scope_ids = {tk.id, *(d.id for d in board._descendants(tk.id))} if tk is not None else set()
        scope_ids |= {d["id"] for d in docs}
        art_ids = {lk.to_id for lk in links if lk.from_id in scope_ids} \
            | {lk.from_id for lk in links if lk.to_id in scope_ids}
        arts = [a for a in arts if a.id in art_ids]
        reachable = scope_ids | art_ids
        links = [lk for lk in links if lk.from_id in reachable or lk.to_id in reachable]
    return {"docs": docs, "artifacts": [a.model_dump(mode="json") for a in arts],
            "links": [lk.model_dump(mode="json") for lk in links]}
