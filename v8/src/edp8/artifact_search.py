"""One artifact search for every `$` picker (epic-0cec8d1c31 S16, owner m-45367b2531 and m-ec3b411172).

The web composer and the VS Code extension both call `GET /v1/artifacts/search`; neither builds rows itself.
A row is a finalised artifact the CALLER may read (`guest_scope.visible`: a guest sees its member epics' closure,
every other role sees all), named by its title and the epic it is linked to. Rows of the epic the caller is
looking at come first (`group: scope`), every other readable artifact after (`group: board`), each group newest
first within the same match rank. Staged uploads are invisible (design §18.1)."""

from __future__ import annotations

import re
from typing import Any

from . import guest_scope

DEFAULT_LIMIT = 40
MAX_LIMIT = 200


def title_of(a: Any) -> str:
    """What a reader calls the artifact: its upload filename, else the first line of its note, else its uri."""
    name = (getattr(a, "filename", "") or "").strip()
    if name:
        return name
    note = (getattr(a, "note", "") or "").strip().splitlines()
    if note and note[0].strip():
        return note[0].strip()[:200]
    uri = (getattr(a, "uri", "") or "").strip()
    return uri.rsplit("/", 1)[-1][:200] if uri and not uri.startswith("/v1/artifacts/") else a.id


WINDOW = 400  # rows read per group before ranking: the work is bounded by this, never by the board's size
_CHUNK = 300  # ids per IN (...) query


def _chunks(ids: list[str]) -> list[list[str]]:
    return [ids[i:i + _CHUNK] for i in range(0, len(ids), _CHUNK)]


def _epic_and_ticket(board: Any, oid: str) -> tuple[str | None, str | None]:
    """(real epic id, ticket id) for the other end of a link: a ticket names its epic; a doc its scope's. Only
    a ticket whose root is an epic counts: a quick task or a topic is its own root and is not labelled an epic."""
    t = board.store.get("ticket", oid)
    if t is None:
        d = board.store.get("doc", oid)
        t = board.store.get("ticket", d.scope) if d is not None and str(d.scope).split("-")[0] in ("epic", "s", "t") else None
    if t is None:
        return None, None
    root = t if not t.parent_id else board.epic_of(t)
    return (root.id if str(getattr(root.kind, "value", root.kind)) == "epic" else None), t.id


def _epic_links(board: Any, scope: Any, ids: list[str]) -> dict[str, tuple[str | None, str]]:
    """artifact id -> (epic id or None, ticket id) from its links, oldest first; a link to a real epic's tree
    outranks one to a parentless ticket (a quick task, a topic). A guest follows only the links it may
    read (both ends in its scope), so an artifact also produced on a foreign epic names only the guest's own."""
    out: dict[str, tuple[str | None, str]] = {}
    wanted = set(ids)
    links = []
    for chunk in _chunks(ids):
        links += board.store.query("link", {"to_id": chunk}, limit=100_000) + board.store.query(
            "link", {"from_id": chunk}, limit=100_000)
    for lk in sorted(links, key=lambda x: x.created_at):
        if not guest_scope.visible(scope, "link", lk):
            continue
        art, other = (lk.to_id, lk.from_id) if lk.to_id in wanted else (lk.from_id, lk.to_id)
        if art in out and out[art][0]:
            continue
        epic, ticket = _epic_and_ticket(board, other)
        if ticket and (epic or art not in out):
            out[art] = (epic, ticket)
    return out


def _linked_to_epic(board: Any, epic_id: str) -> list[str]:
    """Artifact ids linked to the epic's tickets and their docs (the asked epic's own, for the scope group)."""
    tickets = [t.id for t in board.store.query("ticket", {"epic_id": epic_id}, limit=100_000)] + [epic_id]
    ends = set(tickets) | {d.id for c in _chunks(tickets) for d in board.store.query("doc", {"scope": c}, limit=100_000)}
    found: dict[str, str] = {}
    for c in _chunks(sorted(ends)):
        for lk in board.store.query("link", {"from_id": c}, limit=100_000) + board.store.query("link", {"to_id": c}, limit=100_000):
            for oid in (lk.from_id, lk.to_id):
                if oid.startswith("art-"):
                    found[oid] = lk.created_at.isoformat()
    return sorted(found, key=found.get, reverse=True)[:WINDOW]  # newest link first


def _rank(q: str, row: dict[str, Any]) -> int:
    """0 id prefix, 1 title prefix, 2 title word start, 3 substring of title/uri/epic title, -1 no match."""
    if not q:
        return 3
    ident, title = row["id"].lower(), row["title"].lower()
    if ident.startswith(q):
        return 0
    if title.startswith(q):
        return 1
    if re.search(r"(^|[^a-z0-9])" + re.escape(q), title):
        return 2
    hay = " ".join((title, ident, (row.get("uri") or "").lower(), (row.get("epic_title") or "").lower()))
    return 3 if q in hay else -1


def _candidates(board: Any, scope: Any, q: str, epic_id: str | None) -> list[Any]:
    """The finalised artifacts worth ranking, never more than a few WINDOWs and never the whole board:
    a guest's are its scope's; anyone else's are the asked epic's, the newest, and (for a q) the body matches
    plus those of epics whose title matches. Staged uploads are invisible (design §18.1)."""
    seen: dict[str, Any] = {}

    def take(arts: list[Any]) -> None:
        for a in arts:
            if a is not None and not getattr(a, "staged", False) and a.id not in seen and guest_scope.visible(scope, "artifact", a):
                seen[a.id] = a

    if scope is not None:  # a guest: only what its scope already holds
        take([board.store.get("artifact", i) for i in sorted(scope.artifacts)])
        return list(seen.values())
    if epic_id:
        take([board.store.get("artifact", i) for i in _linked_to_epic(board, epic_id)])
    if q:
        take([a for _, a in board.store.query_body_like("artifact", q, WINDOW, newest_first=True)])
        epics = [e for e in board.store.query("ticket", {"kind": "epic"}, limit=100_000) if q in (e.title or "").lower()]
        for e in sorted(epics, key=lambda e: e.created_at, reverse=True)[:10]:
            take([board.store.get("artifact", i) for i in _linked_to_epic(board, e.id)])
    else:
        take(board.store.query("artifact", {}, limit=WINDOW, newest_first=True))
    return list(seen.values())


def search(board: Any, actor: Any, *, q: str = "", epic_id: str | None = None, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    q = (q or "").strip().lower()
    scope = guest_scope.scope_for(board, actor)
    arts = _candidates(board, scope, q, epic_id)
    where = _epic_links(board, scope, [a.id for a in arts]) if arts else {}
    epic_titles: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for a in arts:
        epic, ticket = where.get(a.id, (None, None))
        if epic and epic not in epic_titles:
            e = board.store.get("ticket", epic)
            epic_titles[epic] = e.title if e is not None else epic
        rows.append({"id": a.id, "form": str(getattr(a.form, "value", a.form)), "title": title_of(a), "uri": a.uri,
                     "content_type": a.content_type, "epic_id": epic, "epic_title": epic_titles.get(epic) if epic else None,
                     "ticket_id": ticket, "created_at": a.created_at.isoformat(),
                     "group": "scope" if epic_id and epic == epic_id else "board"})
    ranked = [(r, _rank(q, r)) for r in rows]
    ranked = [(r, s) for r, s in ranked if s >= 0]
    ranked.sort(key=lambda rs: rs[0]["created_at"], reverse=True)  # newest first inside a group and rank (stable sort)
    ranked.sort(key=lambda rs: (rs[0]["group"] != "scope", rs[1]))
    return [r for r, _ in ranked[:limit]]
