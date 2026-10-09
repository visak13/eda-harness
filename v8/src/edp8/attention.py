"""S20 attention trail (design-e963c656f5 §4.18, owner ruling m-8d061abf32): the ONE derivation of the unanswered
messages addressed to a person, each with its full location path, so every surface (the Epics list's dots, the epic's
openers, the Work drawer's ticket rows, notifications) renders the same list and none computes its own rule.
s-aa76c83998 (design-63db8a7d42 item H): the gate, sign-off, fix and access-request kinds are gone. A gate, a fix
proposal and an access request now reach the owner as a chat message, so they are asks like any other; there is no
Needs-you view and no decisions read.

Items and the rule each reuses (never re-implemented here):
- ask: `board.inbox` — questions/steers to the viewer; status/finding/deviation to a human (answered = gone).
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
from .board import Board, is_help, is_quick, is_topic
from .schemas import Participant, TicketKind

KINDS = ("ask",)

_PLURAL = {"status": "statuses", "access request": "access requests", "fix to approve": "fixes to approve"}


def _page(t: Any) -> str:
    """The SPA route of a ticket's own page."""
    if is_topic(t):
        return f"/ui/library/topics/{quote(t.id, safe='')}"
    return f"/ui/{'epic' if t.kind == TicketKind.epic else 'ticket'}/{quote(t.id, safe='')}"


def _scope(board: Board, t: Any) -> tuple[Any, dict[str, Any]]:
    root = board.epic_of(t)
    # a help thread is a topic the Library never lists: its trail starts at the rail's Ask for help instead
    kind = "help" if is_help(root) else "topic" if is_topic(root) else "quick" if is_quick(root) else "epic"
    return root, {"type": kind, "id": root.id, "title": root.title}


def _place(board: Board, t: Any, at: tuple[str, str], item: dict[str, Any], *, kind: str, since: str,
           label: str, noun: str, query: dict[str, str] | None = None, anchor: str | None = None,
           src: Any = None, ask: str | None = None, why: str = "") -> dict[str, Any]:
    """One item: the hop on its scope page, where it sits on its own page, and the deep link that lands there.
    `ask` (t-77c3a55b75, owner m-0e6940fe2c): a sign-off's or gate's plain-words question, so every surface says
    what the viewer decides. `why` (e0cec S3): the one line saying why only this person can act on it."""
    root, scope = _scope(board, t)
    child = t.id != root.id
    tab, section = ("work", "tickets") if child and scope["type"] in ("epic", "quick") else at
    url = _page(t) + (f"?{urlencode(query)}" if query else "") + (f"#{anchor}" if anchor else "")
    return {"kind": kind, "id": item["id"], "since": since, "label": label, "noun": noun, "scope": scope,
            "tab": tab, "section": section,
            "ticket": {"id": t.id, "title": t.title} if child else None,
            "at": {"tab": at[0], "section": at[1]}, "item": item, "url": url, "_src": src, "why": why,
            **({"ask": ask} if ask else {})}


ASK_WHY = "work does not wait on it: the seat carries on with its recommendation until you answer"


def _asks(board: Board, viewer: Participant) -> list[dict[str, Any]]:
    out = []
    for m in board.inbox(viewer):
        t = board.store.get("ticket", m["ticket_id"])
        if t is None:
            continue
        role = m.get("from_role") or "a seat"
        kind = m["kind"]
        why = views._why_in_inbox(board, viewer, m)
        out.append(_place(board, t, ("thread", "asks"), {"type": "message", "id": m["id"]}, kind="ask",
                          since=m["created_at"], label=f"{kind} from {role}", noun=kind, anchor=m["id"], src=m,
                          why=f"{why[:1].upper()}{why[1:]}; {ASK_WHY}" if viewer.type == "human" else why))
    return out


_SOURCES = (_asks,)


def items(board: Board, viewer: Participant) -> list[dict[str, Any]]:
    """Every item waiting on `viewer`, oldest first. THE rule every attention surface reads. Each row keeps its
    source record under `_src` for in-process readers (the Decisions read); `public()` strips it."""
    out: list[dict[str, Any]] = []
    from .admin import access
    access.reconcile_expired(board)  # a lapsed access request settles its owner notice here, whoever reads next (F5)
    for source in _SOURCES:
        out.extend(source(board, viewer))
    from . import guest_scope
    scope = guest_scope.scope_for(board, viewer)
    if scope is not None:  # e0cec S5: a guest's rows (and so every count/rollup) are its closure only
        out = [r for r in out if scope.has((r.get("ticket") or {}).get("id") or (r.get("scope") or {}).get("id"))]
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
                       "topics": by_type["topic"], "help": by_type["help"], "admin": by_type["admin"]}}


def attention(board: Board, viewer: Participant) -> dict[str, Any]:
    """GET /v1/me/attention: the items plus their rollup, one read under one lock."""
    with board._lock, board.store._lock:
        rows = items(board, viewer)
        return {"participant": viewer.id, "items": [public(r) for r in rows], **rollup(rows)}
