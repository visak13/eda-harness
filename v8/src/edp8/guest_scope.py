"""Guest sharing (epic-0cec8d1c31 S5, design-b6a55eed13 §4.B; S1 spike report-f1bc7d34da).

ONE place answers what a `guest` may do:

- `POLICY` / `treatment(method, path)`: every REST operation's guest treatment. The shared `actor` dependency
  calls `guard_route()` for a guest, so an operation that is `refused` OR not in the table answers 403: a route
  added later is refused for guests until someone classifies it (fail closed). `scoped` and `allowed` are exact
  (method, path template) entries; only refusals may be patterns.
- `scope_for(board, actor)` + `visible(scope, kind, obj)`: what a guest may READ. A non-guest gets None
  (unscoped: no other role changes). A guest gets an `EpicScope`, its member epics (`Ticket.members` on the
  epic, edited by the owner in the People panel) and their ONE-HOP closure (owner R2, "anything linked to the
  epic is part of it"; architect m-6aec8c2abb): every ticket in those trees, their messages, the design_ref
  docs, docs scoped to one of those tickets, and every doc or artifact one link away from one of them, plus
  artifacts attached to their messages. A linked global doc is readable; its OTHER links are not.
- A refused read answers 404 with the same body as a missing id (`not_found`), so a guest gets no
  existence oracle.

The closure is materialised once per (guest, store seq): every board write bumps the store's global seq, so
the cache can never serve a scope older than the data it answers for.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

from fastapi import HTTPException

GUEST_ROLE = "guest"
EXT_PREFIX = "ext:"
MESSAGE_KINDS = frozenset({"question", "note"})  # what a guest may post (design §4.B)


@dataclass(frozen=True)
class EpicScope:
    """What a guest may read: ids by object kind (materialised once per guest and store seq)."""
    participant_id: str
    epics: frozenset[str]
    tickets: frozenset[str] = field(default_factory=frozenset)
    docs: frozenset[str] = field(default_factory=frozenset)
    artifacts: frozenset[str] = field(default_factory=frozenset)
    messages: frozenset[str] = field(default_factory=frozenset)
    people: frozenset[str] = field(default_factory=frozenset)  # participants a guest may see
    requirements: frozenset[str] = field(default_factory=frozenset)  # the guest's own marks on member epics

    def has(self, oid: str | None) -> bool:
        return bool(oid) and (oid in self.tickets or oid in self.docs or oid in self.artifacts
                              or oid in self.messages or oid in self.requirements)


# ------------------------------------------------------------------------------------------- identity

def is_guest(actor: Any) -> bool:
    return actor is not None and str(getattr(actor, "role", "")) == GUEST_ROLE


def display_handle(p: Any) -> str:
    """How a participant is named to seats and in the UI: a guest is always `ext:<handle>` (design §4.B)."""
    h = str(getattr(p, "handle", "") or "").lstrip("@")
    return EXT_PREFIX + h if is_guest(p) else h


# ------------------------------------------------------------------------------------------- the policy

#: exact (METHOD, path template) → why. Readable/writable only inside the guest's scope, through this module.
SCOPED: dict[tuple[str, str], str] = {
    ("GET", "/v1/me/notifications"): "own notifications, rows outside the scope dropped",
    ("GET", "/v1/me/attention"): "own attention, rows outside the scope dropped",
    ("GET", "/v1/me/people"): "people on member epics + the owner",
    ("GET", "/v1/me/conversations"): "own conversations, threads outside the scope dropped",
    ("GET", "/v1/me/replies"): "own replies, rows outside the scope dropped",
    ("GET", "/v1/me/summary"): "counts over the scoped attention",
    ("GET", "/v1/seats"): "seats on member-epic tickets only",
    ("GET", "/v1/epics/summary"): "member epics only",
    ("GET", "/v1/epics/{epic_id}/page"): "require(epic) + sections filtered",
    ("GET", "/v1/epics/{epic_id}/members"): "require(epic): who the epic is shared with",
    ("GET", "/v1/tickets/table"): "member-epic tickets only",
    ("GET", "/v1/tickets/{ticket_id}/page"): "require(ticket) + sections filtered",
    ("GET", "/v1/tickets/{ticket_id}/thread"): "require(ticket)",
    ("GET", "/v1/tickets/{ticket_id}/transitions"): "require(ticket)",
    ("GET", "/v1/docs/{doc_id}/html"): "require(doc)",
    ("GET", "/v1/context"): "member epics' tickets; recall dropped",
    ("GET", "/v1/context_delta"): "visible events only",
    ("GET", "/v1/inbox"): "asks on visible tickets only",
    ("GET", "/v1/participants"): "people on member epics + the owner",
    ("GET", "/v1/participants/{id_}"): "require(person in scope)",
    ("GET", "/v1/tickets"): "filter_visible",
    ("GET", "/v1/tickets/{id_}"): "require(ticket) + sections filtered",
    ("GET", "/v1/criteria"): "filter_visible",
    ("GET", "/v1/docs"): "filter_visible",
    ("GET", "/v1/docs/{id_}"): "require(doc)",
    ("GET", "/v1/docs/{id_}/diff"): "require(doc)",
    ("GET", "/v1/links"): "both ends visible",
    ("GET", "/v1/epics/{epic_id}/requirements"): "require(epic); the guest's own requirements only, no story digests",
    ("POST", "/v1/requirements"): "Mark as requirement: the message must be in scope (404 otherwise); sends no message",
    ("POST", "/v1/artifacts/upload-authorize"): "upload: staged, invisible until finalised in scope",
    ("POST", "/v1/artifacts/upload"): "upload: staged, invisible until finalised in scope",
    ("POST", "/v1/artifacts/finalize"): "finalise onto a ticket in scope; secret screen",
    ("GET", "/v1/artifacts/search"): "visible artifacts only (filter_visible); a foreign epic_id is a 404",
    ("GET", "/v1/artifacts/{id_}/content"): "require(artifact)",
    ("GET", "/v1/artifacts/{id_}"): "require(artifact)",
    ("POST", "/v1/messages"): "ticket in scope; kind in {question, note}; secret screen",
    ("GET", "/v1/messages"): "ticket in scope (require) or filter_visible",
    ("GET", "/v1/lookup"): "scope must be a visible ticket/epic",
    ("GET", "/v1/messages/{id_}"): "require(message)",
    ("GET", "/v1/tickets/{id_}/contextual"): "require(ticket)",
    ("GET", "/v1/docs/{id_}/sources"): "require(doc)",
    ("GET", "/v1/docs/{id_}/comments"): "require(doc)",
    ("GET", "/v1/docs/{id_}/context"): "require(doc)",
    ("POST", "/v1/docs/comments"): "doc in scope (a comment is a message on its thread)",
    ("GET", "/v1/gates/{ticket_id}"): "require(ticket)",
    ("GET", "/v1/board/{epic_id}"): "require(epic)",
    ("GET", "/v1/events"): "visible events only (iter_replay keep)",
    ("GET", "/v1/find"): "visible hits only, pushed into retrieval",
    ("GET", "/v1/feed"): "visible events only; scope recomputed on change, resync on revoke",
    ("GET", "/ui/poll"): "visible events only",
}

#: exact (METHOD, path template) → why. No epic data (own row, liveness, static contracts, SPA shell).
ALLOWED: dict[tuple[str, str], str] = {
    ("POST", "/v1/me/attention/dismiss"): "own attention row only",
    ("GET", "/v1/me/avatar"): "own row",
    ("PUT", "/v1/me/avatar"): "own row",
    ("GET", "/v1/avatars/catalog"): "static catalog",
    ("GET", "/v1/avatars/{pid}.svg"): "avatar image (no epic data)",
    ("GET", "/v1/me/settings"): "own row",
    ("PUT", "/v1/me/settings"): "own row",
    ("POST", "/v1/join"): "public invite redeem",
    ("POST", "/v1/signout"): "sign out",
    ("GET", "/v1/access-requests/available"): "public access-request flow (own guards)",
    ("POST", "/v1/access-requests"): "public access-request flow (own guards)",
    ("POST", "/v1/access-requests/claim"): "public access-request flow (own guards)",
    ("GET", "/v1/whoami"): "own identity",
    ("POST", "/v1/docs/reads/reset"): "own already-read ledger only (subscribe/resume_self clear it); returns no doc data",
    ("GET", "/v1/describe/{type_}"): "object schemas (static)",
    ("GET", "/v1/listening"): "static contract",
    ("GET", "/healthz"): "liveness",
    ("GET", "/v1/health"): "liveness",
    ("GET", "/openapi.json"): "route shapes only",
    ("GET", "/docs"): "route shapes only",
    ("GET", "/docs/oauth2-redirect"): "route shapes only",
    ("GET", "/redoc"): "route shapes only",
    ("GET", "/ui"): "SPA shell (data comes from /v1)",
    ("GET", "/ui/{path:path}"): "SPA shell (data comes from /v1)",
    ("GET", "/"): "SPA shell redirect",
}

#: (regex on "METHOD /path", why). Refusals only: a pattern can never let a new route through.
REFUSED: list[tuple[str, str]] = [
    (r"^\w+ /v1/admin(/|$)", "admin surface"),
    (r"^\w+ /v1/sessions", "spawn/reap/resume/close: seat authority"),
    (r"^POST /v1/quick-tasks$", "creates owner work"),
    (r"^POST /v1/requirements/", "requirement_link: the epic's architect closes a requirement"),
    (r"^\w+ /v1/workflows", "workflow definitions are owner configuration"),
    (r"^\w+ /v1/(models|harness|pool/capabilities)", "models / harness / pool: owner configuration"),
    (r"^\w+ /v1/code(/|$)", "Code tab and chat (owner ruling R6)"),
    (r"^\w+ /v1/(doctor|fixes|help)(/|$)", "Help seat diagnostics and fixes"),
    (r"^\w+ /v1/pains", "framework pain log (host evidence)"),
    (r"^GET /v1/services/status$", "host services"),
    (r"^GET /v1/harvest/cost$", "fleet cost"),
    (r"^GET /v1/me/usage$", "fleet usage/cost"),
    (r"^POST /v1/me/settings/slack/test$", "outward Slack ping"),
    (r"^\w+ /v1/(topics|expert-session)", "Library topics are not epics"),
    (r"^\w+ /v1/index/", "index search and maintenance (board-wide)"),
    (r"^GET /v1/(recall|knowledge|library|activity|decisions)$", "operator aggregates the guest UI never calls"),
    (r"^GET /v1/close_check$", "seat close check"),
    (r"^POST /v1/service_event$", "service plane"),
    (r"^POST /v1/status$", "seat status record"),
    (r"^POST /v1/participants$", "registry write"),
    (r"^\w+ /ui-legacy", "legacy renderer (not ported to the scope)"),
    (r"^\w+ /ui/(me|activity|tickets|epic|ticket|doc)(/|$)", "legacy renderer at /ui"),
    (r"^POST /v1/gates", "gate open/answer"),
    (r"^POST /v1/me/verdict$", "criterion verdict"),
    (r"^(POST|PATCH|PUT|DELETE) /v1/criteria", "criteria create / verdict"),
    (r"^(POST|PATCH|PUT|DELETE) /v1/tickets", "ticket create / status transition / edit"),
    (r"^(POST|PATCH|PUT|DELETE) /v1/epics", "epic edits incl. membership (owner)"),
    (r"^(POST|PATCH|PUT|DELETE) /v1/docs", "doc create/edit/approve/import"),
    (r"^POST /v1/library", "doc import"),
    (r"^(POST|DELETE) /v1/links", "link writes would widen the closure"),
    (r"^(POST|PATCH|DELETE) /v1/(decisions|claims|lessons|records)", "records / decisions"),
    (r"^POST /v1/messages/", "message side-actions (resolve …) are seat/owner work"),
    (r"^POST /v1/artifacts$", "url artifacts are seat work; a guest uploads files"),
]
_REFUSED = [(re.compile(rx), why) for rx, why in REFUSED]

#: MCP tool → treatment. A tool is a BoardClient REST call made as the caller, so the REST gate is what
#: enforces it; this table must name every tool in bundles.ALL_TOOLS (tests/test_e0cec_s5_guest.py).
TOOLS_ALLOWED = frozenset({"describe", "describe_objects", "get_guide", "subscribe", "whoami"})
TOOLS_LOCAL = frozenset({"get_guide"})  # calls no board route: framework guide text from the package
TOOLS_SCOPED = frozenset({
    "artifact_read", "artifact_upload", "requirements", "board", "context", "context_delta", "criterion_query", "doc_query",
    "doc_read", "events_query", "find", "gates", "inbox", "link_query", "lookup", "message_query", "message_read",
    "message_send", "ticket_query", "ticket_read"})


def treatment(method: str, path: str) -> tuple[str, str]:
    """(scoped|allowed|refused|unclassified, why) for one operation; HEAD is GET."""
    m = "GET" if method.upper() == "HEAD" else method.upper()
    if (m, path) in SCOPED:
        return "scoped", SCOPED[(m, path)]
    if (m, path) in ALLOWED:
        return "allowed", ALLOWED[(m, path)]
    key = f"{m} {path}"
    for rx, why in _REFUSED:
        if rx.search(key):
            return "refused", why
    return "unclassified", "not in guest_scope.POLICY: refused until classified"


def tool_treatment(name: str) -> str:
    return "allowed" if name in TOOLS_ALLOWED else "scoped" if name in TOOLS_SCOPED else "refused"


#: query parameters that name the object a scoped read is about: a foreign id there is a 404 like a path id
ID_PARAMS = ("ticket_id", "epic_id", "epic", "scope", "subject_id", "id", "doc_id", "parent_id", "around", "source", "request", "reply_to")


def guard_route(actor: Any, request: Any, board: Any = None) -> None:
    """The fail-closed gate, called by the shared actor dependency: a guest reaches only scoped/allowed ops.

    For a scoped op it also (1) answers 404 when a path parameter or an id-naming query parameter is a board
    id outside the scope, so every single-object read is `require`d without a per-route call, and (2) puts the
    scope on `request.state.guest_scope`, which the response redactor (service middleware) reads."""
    if not is_guest(actor) or request is None:
        return
    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    treat, why = treatment(request.method, path)
    if treat not in ("scoped", "allowed"):
        raise HTTPException(403, f"a guest may not use {request.method} {path} ({why})")
    if treat != "scoped" or board is None:
        return
    scope = scope_for(board, actor)
    request.state.guest_scope = scope
    named = [(k, v) for k, v in (request.path_params or {}).items()]
    named += [(k, request.query_params.get(k)) for k in ID_PARAMS if request.query_params.get(k)]
    for k, v in named:
        v = str(v)
        if k == "id_" and path.startswith("/v1/participants/"):
            if v not in scope.people and v.lstrip("@") not in _handles(board, scope):
                raise not_found("participant", v)
            continue
        _require_id(board, scope, v)


def _require_id(board: Any, scope: EpicScope, v: str) -> None:
    """404 when `v` is a board id (by its prefix shape) outside the scope."""
    m = _ID_RX.match(v)
    if m and not (scope.has(v) or (m.group(1) == "c" and _crit_visible(board, scope, v))
                  or (m.group(1) == "ev" and _ev_visible(board, scope, v))):
        raise not_found(_KIND_BY_PREFIX.get(m.group(1), "object"), v)


#: a stored reply's fields that name what the request touched (its own `id` is checked when it is readable kind)
REPLY_REF_FIELDS = ("ticket_id", "doc_id", "design_ref", "reply_to", "parent_id", "epic_id", "scope", "from_id",
                    "to_id", "artifact_id", "subject_id")


def require_replay(board: Any, actor: Any, body: Any, reply: Any) -> None:
    """S13 F3 residual (architect m-10b64902e7): a guest's cached reply replays only while the guest can still
    reach every object id the request body names (walked in full) and every reference the first reply carries.
    Any refusal refuses the replay with the same 404 a fresh request gets."""
    scope = scope_for(board, actor)
    if scope is None:
        return
    def walk(x: Any) -> None:
        if isinstance(x, str):
            _require_id(board, scope, x)
        elif isinstance(x, dict):
            for y in x.values():
                walk(y)
        elif isinstance(x, list):
            for y in x:
                walk(y)
    walk(body)
    if isinstance(reply, dict):
        walk([reply.get(k) for k in REPLY_REF_FIELDS])
        own = reply.get("id")
        m = _ID_RX.match(own) if isinstance(own, str) else None
        if m and _KIND_BY_PREFIX.get(m.group(1), "doc") in ("ticket", "doc", "artifact", "message"):
            _require_id(board, scope, own)


_KIND_BY_PREFIX = {"m": "message", "art": "artifact", "c": "criterion", "lk": "link", "ev": "event",
                   "dec": "decision", "epic": "ticket", "s": "ticket", "t": "ticket", "q": "ticket"}


def _handles(board: Any, scope: EpicScope) -> set[str]:
    out = set()
    for pid in scope.people:
        p = board.store.get("participant", pid)
        if p is not None:
            out.add(str(p.handle).lstrip("@"))
    return out


def _crit_visible(board: Any, scope: EpicScope, cid: str) -> bool:
    c = board.store.get("criterion", cid)
    return c is not None and c.ticket_id in scope.tickets


def _ev_visible(board: Any, scope: EpicScope, eid: str) -> bool:
    e = board.store.get("event", eid)
    return e is not None and event_visible(scope, e)


# ------------------------------------------------------------------------------------------- membership

def members(epic: Any) -> list[str]:
    return list(getattr(epic, "members", None) or [])


def member_epics(board: Any, participant_id: str) -> frozenset[str]:
    return frozenset(t.id for t in board.store.query("ticket", {"kind": "epic"}, limit=100_000)
                     if participant_id in members(t))


def epic_has_guests(board: Any, epic_id: str | None) -> bool:
    """Whether an epic shares its tree with at least one guest (the secret screen's trigger)."""
    if not epic_id:
        return False
    epic = board.store.get("ticket", epic_id)
    for pid in members(epic):
        p = board.store.get("participant", pid)
        if p is not None and is_guest(p) and not getattr(p, "retired", False):
            return True
    return False


# ------------------------------------------------------------------------------------------- the scope

_CACHE: dict[tuple[int, str], tuple[int, EpicScope]] = {}
_CACHE_LOCK = threading.Lock()


def scope_for(board: Any, actor: Any) -> EpicScope | None:
    """THE scoping function: None for every role but guest; for a guest, its member epics' closure."""
    if not is_guest(actor):
        return None
    seq = (board.store.max_seq(), getattr(board.store, "deletes", 0))  # a link delete narrows the closure
    key = (id(board), actor.id)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == seq:
            return hit[1]
    scope = _compute(board, actor.id)
    with _CACHE_LOCK:
        if len(_CACHE) > 256:
            _CACHE.clear()
        _CACHE[key] = (seq, scope)
    return scope


def invalidate() -> None:
    """Drop every cached scope: a write that changes who may see an object but emits no event (a second marker on a requirement)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _compute(board: Any, pid: str) -> EpicScope:
    epics = member_epics(board, pid)
    people = {pid}
    people |= {p.id for p in board.store.query("participant", {"role": "owner"}, limit=1000)}
    if not epics:
        return EpicScope(pid, epics, people=frozenset(people))
    rows = board.store.query("ticket", {"epic_id": list(epics)}, limit=1_000_000)
    tickets = {t.id for t in rows} | set(epics)
    docs = {t.design_ref for t in rows if t.design_ref}
    tl = list(tickets)
    docs |= {d.id for d in board.store.query("doc", {"scope": tl}, limit=1_000_000)}
    artifacts: set[str] = set()
    links = board.store.query("link", {"from_id": tl}, limit=1_000_000) + board.store.query(
        "link", {"to_id": tl}, limit=1_000_000)
    others = {lk.to_id if lk.from_id in tickets else lk.from_id for lk in links} - tickets
    for oid in others:  # one hop: the doc or artifact at the other end (never its own links)
        if board.store.get("doc", oid) is not None:
            docs.add(oid)
        elif board.store.get("artifact", oid) is not None:
            artifacts.add(oid)
    messages = set()
    for m in board.store.query("message", {"ticket_id": tl + list(docs)}, limit=1_000_000):
        messages.add(m.id)
        artifacts.update(m.artifacts or [])
        people.add(m.created_by)
    for t in rows:
        if t.assignee:
            people.add(t.assignee)
        people.add(t.created_by)
    for e in epics:
        epic = board.store.get("ticket", e)
        people.update(members(epic))
    reqs = {r.id for r in board.store.query("requirement", {"epic_id": list(epics)}, limit=1_000_000)
            if pid in (r.marked_by or [r.created_by])}
    return EpicScope(pid, epics, frozenset(tickets), frozenset(docs), frozenset(artifacts), frozenset(messages),
                     frozenset(p for p in people if p), frozenset(reqs))


def visible(scope: EpicScope | None, kind: str, obj_or_id: Any) -> bool:
    """Whether `scope` may read this object. `kind` is the board object type; `obj_or_id` an object or id."""
    if scope is None:
        return True
    oid = obj_or_id if isinstance(obj_or_id, str) else (
        obj_or_id.get("id") if isinstance(obj_or_id, dict) else getattr(obj_or_id, "id", None))
    get = (lambda k: obj_or_id.get(k)) if isinstance(obj_or_id, dict) else (lambda k: getattr(obj_or_id, k, None))
    if kind == "ticket":
        return oid in scope.tickets
    if kind == "doc":
        return oid in scope.docs
    if kind == "artifact":
        return oid in scope.artifacts
    if kind == "message":
        return oid in scope.messages or (not isinstance(obj_or_id, str) and get("ticket_id") in scope.tickets)
    if kind in ("criterion", "gate", "session"):
        return get("ticket_id") in scope.tickets
    if kind == "link":
        return scope.has(get("from_id")) and scope.has(get("to_id"))
    if kind == "participant":
        return oid in scope.people
    if kind == "decision":
        return get("scope") in scope.tickets
    if kind == "event":
        return event_visible(scope, obj_or_id)
    if kind == "hit":  # a find() hit, already located (type, id, ticket_id, epic_id)
        t = get("type") or ""
        if t == "criterion":
            return get("ticket_id") in scope.tickets
        return visible(scope, t, get("id") or "")
    if kind == "any":
        return scope.has(oid)
    return False  # lessons, pains, sessions … are never a guest's


def event_visible(scope: EpicScope, ev: Any) -> bool:
    """An event is visible when its subject is, or (for message/link events) the ticket it names is."""
    sid = ev.get("subject_id") if isinstance(ev, dict) else getattr(ev, "subject_id", None)
    data = (ev.get("data") if isinstance(ev, dict) else getattr(ev, "data", None)) or {}
    if "from_id" in data and "to_id" in data:  # a link event: both ends visible, whatever its subject
        return scope.has(data.get("from_id")) and scope.has(data.get("to_id"))
    if data.get("ticket_id") and data["ticket_id"] not in scope.tickets:  # about a foreign ticket
        return False
    return scope.has(sid) or data.get("ticket_id") in scope.tickets


#: events that can widen or narrow a guest's closure (an open SSE stream recomputes on these)
SCOPE_EVENTS = frozenset({"ticket_created", "ticket_updated", "message_sent", "doc_updated", "assigned",
                          "link_created", "link_deleted"})


# ------------------------------------------------------------------------------------------- enforcement

def not_found(kind: str, oid: str) -> Exception:
    """THE refusal for a read outside the scope: the same BoardError (code, text, 404) that `Board._get`
    raises for a missing id, so a guest cannot tell "missing" from "not a member" (architect m-6aec8c2abb)."""
    from .board import BoardError
    return BoardError("not_found", f"{kind} {oid!r} does not exist")


def require(board: Any, actor: Any, kind: str, obj_or_id: Any) -> None:
    """Refuse a single-object read outside the guest's scope with 404 (no existence oracle)."""
    scope = scope_for(board, actor)
    if not visible(scope, kind, obj_or_id):
        oid = obj_or_id if isinstance(obj_or_id, str) else getattr(obj_or_id, "id", "?")
        raise not_found(kind, str(oid))


def require_any(board: Any, actor: Any, oid: str, kind: str = "object") -> None:
    """require() for an id of unknown kind (ticket, doc, artifact or message)."""
    scope = scope_for(board, actor)
    if scope is not None and not scope.has(oid):
        raise not_found(kind, oid)


def filter_visible(scope: EpicScope | None, kind: str, rows: Iterable[Any]) -> list[Any]:
    rows = list(rows)
    return rows if scope is None else [r for r in rows if visible(scope, kind, r)]


def keep_event(board: Any, actor: Any):
    """A `keep(event)` predicate for a one-shot replay, or None for an unscoped actor."""
    scope = scope_for(board, actor)
    return None if scope is None else (lambda e: event_visible(scope, e))


class StreamScope:
    """A guest's scope for one open stream (SSE feed, watch queue). The closure is recomputed on the events
    that can change it (SCOPE_EVENTS), so a ticket, link or message created after the stream opened shows up,
    and `revoked` turns true once the guest lost a member epic: the stream must end with a resync."""

    def __init__(self, board: Any, actor: Any) -> None:
        self.board, self.actor = board, actor
        self.scope = scope_for(board, actor)
        self.revoked = False
        self._lock = threading.Lock()

    def keep(self, ev: Any) -> bool:
        # scope_for is cached on (max_seq, deletes), so recomputing on every event is cheap, and an event-less
        # change (a link delete) narrows an open stream too, not only the SCOPE_EVENTS kinds
        with self._lock:
            before = self.scope.epics if self.scope else frozenset()
            self.scope = scope_for(self.board, self.actor)
            after = self.scope.epics if self.scope else frozenset()
            if before - after:
                self.revoked = True
                return False
            scope = self.scope
        return scope is None or event_visible(scope, ev)


def stream_scope(board: Any, actor: Any) -> StreamScope | None:
    return StreamScope(board, actor) if is_guest(actor) else None


def keep_hit(board: Any, actor: Any):
    scope = scope_for(board, actor)
    return None if scope is None else (lambda h: visible(scope, "hit", h))


def redact_ids(scope: EpicScope | None, value: Any) -> Any:
    """Drop, from a view built for an allowed subject, every row that names an object outside the scope.

    The ticket/epic pages and ticket_view carry sections (chain, links, blockers, docs, children, thread,
    recall …) that can name objects in other epics, e.g. a cross-epic `blocks` link or a global doc's other
    links. Every board id is `<prefix>-<10 hex>`; a dict row whose `id` is such an id outside the scope, and a
    bare id string outside it, is removed. Records that are never a guest's (decisions, claims, lessons …)
    are removed wherever they appear.
    """
    if scope is None:
        return value
    if isinstance(value, list):
        return [redact_ids(scope, v) for v in value if not _foreign(scope, v)]
    if isinstance(value, dict):
        # e0cec S5 (review #4/#5): a dict-valued ref (in_reply_to, parent …) or a bare id value (a one-hop
        # doc's `scope`) outside the closure is blanked, not only list items.
        return {k: (None if _foreign(scope, v) and isinstance(v, (str, dict)) else redact_ids(scope, v))
                for k, v in value.items()}
    return value


_ID_RX = re.compile(r"^([a-z]+)-[0-9a-f]{10}$")
_NEVER = frozenset({"dec", "clm", "les", "kl", "fix", "acc", "rsi", "topic", "policy"})


def _foreign(scope: EpicScope, row: Any) -> bool:
    if isinstance(row, str):
        m = _ID_RX.match(row)
        return bool(m) and (m.group(1) in _NEVER or not (scope.has(row) or row in scope.people))
    if not isinstance(row, dict):
        return False
    if {"handle", "type", "role"} <= row.keys() and isinstance(row.get("id"), str):  # a participant row
        return row["id"] not in scope.people
    if "from_id" in row and "to_id" in row:
        return not (scope.has(row["from_id"]) and scope.has(row["to_id"]))
    oid = row.get("id")
    m = _ID_RX.match(oid) if isinstance(oid, str) else None
    if m:
        prefix = m.group(1)
        if prefix in _NEVER:
            return True
        if prefix == "c":
            return row.get("ticket_id") not in scope.tickets
        if prefix == "ev":
            return not event_visible(scope, row)
        if not scope.has(oid):
            return True
    tid = row.get("ticket_id")
    return isinstance(tid, str) and bool(_ID_RX.match(tid)) and tid not in scope.tickets and not scope.has(tid)
