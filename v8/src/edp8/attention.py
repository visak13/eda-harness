"""S20 attention trail (design-e963c656f5 §4.18, owner ruling m-8d061abf32): the ONE derivation of what waits on a
person, each item with its full location path, so every surface (rail counts, Epics list, the epic's openers, the
Work drawer's ticket rows, the Waiting-on-you popover, notifications, the Decisions read) renders the same list and
none computes its own rule.

Items and the rule each reuses (never re-implemented here):
- ask: `board.inbox` — questions/steers to anyone; status/finding/deviation to a human (answered = gone).
- gate: `views._owner_gates` — open gates this viewer may answer (S16: never one the board would refuse).
- signoff: `views.pending_signoffs` — owner-checked pending criteria with evidence.
- fix: S19 fix proposals still `proposed`, for an admin (`admin.auth.is_admin`).
- access_request: t-882e4d2eeb requests still `pending`, for an admin (shape agreed in m-5a9866b623).

Location vocabulary. The epic page has no tab bar; its "tabs" are the WorkHeader openers: `actions` (the Actions
menu; section `decisions` = its answer-decision item), `design` (the design doc drawer), `files` (Files & evidence),
`work` (the Work drawer; section `tickets`, then the ticket row). `thread` is the page's own conversation (no
opener). `tab`/`section` are the hop on the SCOPE page (epic, quick task, topic, admin); `at` is where the item sits
on the page that holds it (the ticket page for a child ticket's item, else the scope page itself).
A dot clears only when its item leaves this list (answered, decided, dismissed); opening it never clears it.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
from typing import Any
from urllib.parse import quote, urlencode

from . import views
from .board import _TERMINAL, Board, is_quick, is_topic
from .schemas import Gate, Participant, TicketKind

KINDS = ("ask", "gate", "signoff", "fix", "access_request")

#: design_signoff lives behind the Design opener, a demo behind Files & evidence; every other gate is a decision
_GATE_AT = {Gate.design_signoff.value: ("design", "signoff"), Gate.demo.value: ("files", "evidence")}
_GATE_NOUN = {Gate.design_signoff.value: "design sign-off", Gate.demo.value: "demo review",
              Gate.scope.value: "scope decision", Gate.budget.value: "budget decision",
              Gate.acceptance.value: "acceptance", Gate.adversarial.value: "adversarial review",
              Gate.poc.value: "proof-of-concept review"}
_PLURAL = {"status": "statuses", "access request": "access requests", "fix to approve": "fixes to approve"}


def _page(t: Any) -> str:
    """The SPA route of a ticket's own page."""
    if is_topic(t):
        return f"/ui/library/topics/{quote(t.id, safe='')}"
    return f"/ui/{'epic' if t.kind == TicketKind.epic else 'ticket'}/{quote(t.id, safe='')}"


def _scope(board: Board, t: Any) -> tuple[Any, dict[str, Any]]:
    root = board.epic_of(t)
    kind = "topic" if is_topic(root) else "quick" if is_quick(root) else "epic"
    return root, {"type": kind, "id": root.id, "title": root.title}


def _place(board: Board, t: Any, at: tuple[str, str], item: dict[str, Any], *, kind: str, since: str,
           label: str, noun: str, query: dict[str, str] | None = None, anchor: str | None = None,
           src: Any = None) -> dict[str, Any]:
    """One item: the hop on its scope page, where it sits on its own page, and the deep link that lands there."""
    root, scope = _scope(board, t)
    child = t.id != root.id
    tab, section = ("work", "tickets") if child and scope["type"] != "topic" else at
    url = _page(t) + (f"?{urlencode(query)}" if query else "") + (f"#{anchor}" if anchor else "")
    return {"kind": kind, "id": item["id"], "since": since, "label": label, "noun": noun, "scope": scope,
            "tab": tab, "section": section,
            "ticket": {"id": t.id, "title": t.title} if child else None,
            "at": {"tab": at[0], "section": at[1]}, "item": item, "url": url, "_src": src}


def _asks(board: Board, viewer: Participant) -> list[dict[str, Any]]:
    out = []
    for m in board.inbox(viewer):
        t = board.store.get("ticket", m["ticket_id"])
        if t is None:
            continue
        role = m.get("from_role") or "a seat"
        kind = m["kind"]
        out.append(_place(board, t, ("thread", "asks"), {"type": "message", "id": m["id"]}, kind="ask",
                          since=m["created_at"], label=f"{kind} from {role}", noun=kind, anchor=m["id"], src=m))
    return out


def _gates(board: Board, viewer: Participant) -> list[dict[str, Any]]:
    out = []
    for tid, ev in views._owner_gates(board, viewer):
        t = board.ticket(tid)
        gate = ev.data.get("gate") or ""
        noun = _GATE_NOUN.get(gate, f"{gate} decision")
        out.append(_place(board, t, _GATE_AT.get(gate, ("actions", "decisions")),
                          {"type": "gate", "id": ev.id, "gate": gate}, kind="gate",
                          since=ev.created_at.isoformat(), label=noun, noun=noun, query={"request": ev.id},
                          src=(tid, ev)))
    return out


def _signoffs(board: Board, viewer: Participant) -> list[dict[str, Any]]:
    out = []
    for c, t, doc in views.pending_signoffs(board, viewer):
        design = doc is not None and getattr(doc.doc_type, "value", doc.doc_type) == "design"
        noun = "design sign-off" if design else "sign-off"
        out.append(_place(board, t, ("design", "signoff") if design else ("files", "evidence"),
                          {"type": "criterion", "id": c.id, "doc": getattr(doc, "id", None)}, kind="signoff",
                          since=c.created_at.isoformat(), label=noun, noun=noun,
                          query={"doc": doc.id} if doc is not None else None, anchor=c.id,
                          src=(c, t, doc)))
    return out


def _fixes(board: Board, viewer: Participant) -> list[dict[str, Any]]:
    from .admin.auth import is_admin
    if not is_admin(viewer):
        return []
    out = []
    for f in board.store.query("fix", {"status": "proposed"}, limit=500):
        t = board.store.get("ticket", f.topic_id)
        if t is None or board.epic_of(t).status in _TERMINAL:
            continue
        out.append(_place(board, t, ("fixes", "fixes"), {"type": "fix", "id": f.id}, kind="fix",
                          since=f.created_at.isoformat(), label="fix to approve", noun="fix to approve",
                          anchor=f.id, src=f))
    return out


def _access_requests(board: Board, viewer: Participant) -> list[dict[str, Any]]:
    from .admin.auth import is_admin
    if not is_admin(viewer):
        return []
    try:
        rows = board.store.query("access_request", {"status": "pending"}, limit=500)
    except KeyError:  # t-882e4d2eeb not landed on this build: no requests can exist
        return []
    return [{"kind": "access_request", "id": r.id, "since": r.created_at.isoformat(),
             "label": f"{r.name} asks for access as {r.role_wanted}", "noun": "access request",
             "scope": {"type": "admin", "id": "admin", "title": "Admin"},
             "tab": "teammates", "section": "requests", "ticket": None,
             "at": {"tab": "teammates", "section": "requests"},
             "item": {"type": "access_request", "id": r.id},
             "url": f"/ui/admin?tab=teammates#{quote(r.id, safe='')}", "_src": r} for r in rows]


_SOURCES = (_asks, _gates, _signoffs, _fixes, _access_requests)


def items(board: Board, viewer: Participant) -> list[dict[str, Any]]:
    """Every item waiting on `viewer`, oldest first. THE rule every attention surface reads. Each row keeps its
    source record under `_src` for in-process readers (the Decisions read); `public()` strips it."""
    out: list[dict[str, Any]] = []
    for source in _SOURCES:
        out.extend(source(board, viewer))
    out.sort(key=lambda i: i["since"])
    return out


def public(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k != "_src"}


def reason(rows: list[dict[str, Any]]) -> str:
    """"2 questions, 1 design sign-off": counts by noun, biggest first, ties in first-seen order."""
    counts = Counter(r["noun"] for r in rows)
    order = {n: i for i, n in enumerate(OrderedDict.fromkeys(r["noun"] for r in rows))}
    parts = [f"{n} {noun if n == 1 else _PLURAL.get(noun, noun + 's')}"
             for noun, n in sorted(counts.items(), key=lambda kv: (-kv[1], order[kv[0]]))]
    return ", ".join(parts)


def rollup(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-scope counts for the rail, the Epics list and the popover: one entry per epic/quick/topic/admin with its
    reason, per-hop counts (`tabs`, `sections` keyed `tab/section`, `tickets` keyed by ticket id), newest first."""
    scopes: dict[str, dict[str, Any]] = {}
    for r in rows:
        s = scopes.setdefault(r["scope"]["id"], {**r["scope"], "count": 0, "tabs": Counter(),
                                                 "sections": Counter(), "tickets": Counter(),
                                                 "latest": r["since"], "_rows": []})
        s["count"] += 1
        s["tabs"][r["tab"]] += 1
        s["sections"][f"{r['tab']}/{r['section']}"] += 1
        if r["ticket"]:
            s["tickets"][r["ticket"]["id"]] += 1
        s["latest"] = max(s["latest"], r["since"])
        s["_rows"].append(r)
    out = []
    for s in scopes.values():
        s["reason"] = reason(s.pop("_rows"))
        for k in ("tabs", "sections", "tickets"):
            s[k] = dict(s[k])
        out.append(s)
    out.sort(key=lambda s: s["latest"], reverse=True)
    by_type = Counter()
    for s in out:
        by_type[s["type"]] += s["count"]
    return {"scopes": out,
            "counts": {"total": len(rows), "epics": by_type["epic"] + by_type["quick"],
                       "topics": by_type["topic"], "admin": by_type["admin"]}}


def attention(board: Board, viewer: Participant) -> dict[str, Any]:
    """GET /v1/me/attention: the items plus their rollup, one read under one lock."""
    with board._lock, board.store._lock:
        rows = items(board, viewer)
        return {"participant": viewer.id, "items": [public(r) for r in rows], **rollup(rows)}
