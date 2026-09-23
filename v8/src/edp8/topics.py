"""Library topics (S-SME-SURFACE, s-698224fca8; owner m-de07c37d0c point 2 + m-bdfb407429).

A topic is its own record in the Library — a parentless ticket of kind `topic`, never under an epic —
with a title, one tag list (its sme sets it, the owner edits it, last write wins, the page shows who),
the Library docs it maintains, a thread, named human experts and ONE resident sme seat (`sme.<topic>`).
The seat is woken by every message on the thread (Board._general_reasons), files only proposed docs
(Board.doc_create/_doc_update_locked) and stays until the owner closes the topic (close_check).

Research is board-side and bounded: `research()` fetches a skills.sh search, a skills.sh skill page, a
GitHub file or a page on the topic's seed-URL host — nothing else — and leaves a `topic_fetched`
receipt; `propose()` files a proposed doc only for a URL this topic fetched and stamps its source URL
and fetched-at from that receipt, never from the seat's word.
"""

from __future__ import annotations

import html as _html
import ipaddress
import json
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx

from .board import _TERMINAL, Board, BoardError, is_topic
from .library import MAX_BYTES, TIMEOUT_S, normalize_source
from .schemas import (
    KNOWLEDGE_DOC_TYPES,
    DocStatus,
    DocType,
    EventKind,
    Link,
    MessageKind,
    Participant,
    Relation,
    Role,
    Ticket,
    TicketKind,
    TicketStatus,
    WorkType,
    normalize_tags,
)
from .store import new_id

SEAT_ROLE = Role.sme.value
_HANDLE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{1,39}$")
# adversary 09-23 #2: tokens.json's top level holds the humans AND the `agents` map — an expert named
# "agents" would replace every minted seat secret with a string; the key is reserved
_RESERVED_HANDLES = frozenset({"agents", "owner"})
EXPERT_KINDS = (MessageKind.note, MessageKind.question, MessageKind.answer)


def seat_id(topic_id: str) -> str:
    return f"{SEAT_ROLE}.{topic_id}"


def topic(board: Board, topic_id: str) -> Ticket:
    t = board.ticket(topic_id)
    if not is_topic(t):
        raise BoardError("not_found", f"{topic_id} is not a Library topic", "GET /v1/topics lists them")
    return t


def _private_host(host: str) -> bool:
    """Loopback, link-local, private and unspecified IP literals, and localhost names (an IP-literal check:
    a public name that resolves privately is not caught here)."""
    h = host.strip("[]").lower()
    if not h or h == "localhost" or h.endswith(".localhost") or h.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified or ip.is_reserved
            or ip.is_multicast)


def _owner_only(actor: Participant, what: str) -> None:
    if actor.role != Role.owner:
        raise BoardError("forbidden", f"only the owner {what}", "sign in as the owner")


def _open(t: Ticket) -> None:
    if t.status in _TERMINAL:
        raise BoardError("transition", f"topic {t.id} is closed", "the owner opens a new topic")


# ----------------------------------------------------------------------------- lifecycle
def create(board: Board, actor: Participant, *, title: str, tags: list[str] | None = None,
           seed_url: str | None = None, description: str = "") -> dict[str, Any]:
    """The owner opens a topic: the record, its seed URL (a receipt event, no schema change), its tags
    as set by the owner, and its resident sme seat queued for spawn (the pool-watch tick drains it)."""
    _owner_only(actor, "opens a Library topic")
    seed = (seed_url or "").strip() or None
    if seed:
        u = urlsplit(seed)
        if u.scheme != "https" or not u.netloc:
            raise BoardError("invalid", f"seed URL {seed!r} is not an https URL", "give an https:// page")
        if _private_host(u.hostname or ""):  # adversary 09-23 #9: the seed host joins the research allowlist
            raise BoardError("invalid", f"seed URL host {u.hostname!r} is a local or private address",
                             "the seed is a public https site")
    t = board.ticket_create(actor, kind=TicketKind.topic, work_type=WorkType.knowledge, title=title.strip(),
                            description=description or "", tags=normalize_tags(tags))
    if seed:
        board._emit(t.id, EventKind.ticket_updated, {"changed": ["seed_url"], "seed_url": seed, "by": actor.id})
    if t.tags:
        board._emit(t.id, EventKind.ticket_updated, {"changed": ["tags"], "tags": t.tags, "by": actor.id})
    ensure_seat(board, t.id)
    return {"topic": board.ticket(t.id), "seat": seat_view(board, t.id)}


def ensure_seat(board: Board, topic_id: str) -> str | None:
    """Keep the resident seat: `sme.<topic>` is the assignee, and a seat that is not alive/parked is queued
    for spawn (RAM floor, token mint and seat choice are the pairing queue's). None once closed."""
    t = topic(board, topic_id)
    if t.status in _TERMINAL:
        return None
    pid = seat_id(t.id)
    with board._lock:
        if board.store.get("participant", pid) is None:
            try:
                board.participant_create("agent", Role.sme, pid, id_=pid)
            except BoardError:
                pass
        if t.assignee != pid:
            t.assignee = pid
            board.store.put("ticket", t)
            board._emit(t.id, EventKind.assigned, {"assignee": pid, "by": "board"})
        board._enqueue_pairing(pid, SEAT_ROLE, t.id)
    return pid


def close(board: Board, actor: Participant, topic_id: str) -> Ticket:
    """The owner closes the topic: status done (board-authored — topics have no delivery walk), the seat
    released through the pool, the thread read-only. Docs and proposals stay in the Library."""
    _owner_only(actor, "closes a Library topic")
    with board._lock:  # adversary 09-23 #4: a tag write that read the open ticket must not put it back open
        t = topic(board, topic_id)
        _open(t)
        old = t.status
        t.status = TicketStatus.done
        board.store.put("ticket", t)
        board._emit(t.id, EventKind.status_changed, {"from": old.value, "to": "done", "by": actor.id,
                                                     "note": "topic closed by the owner"})
        board._pending_pairings.pop(seat_id(t.id), None)
    try:
        board._pool_adapter().close(seat_id(t.id), f"topic {t.id} closed by the owner")
    except Exception:  # noqa: BLE001 — a pool hiccup never keeps a topic open; the owner can reap the seat
        pass
    return t


def set_tags(board: Board, actor: Participant, topic_id: str, tags: list[str]) -> Ticket:
    """One tag list, written by the owner or the topic's sme; last write wins (ticket_updated names who)."""
    t = topic(board, topic_id)
    if actor.role != Role.owner and actor.id != t.assignee:
        raise BoardError("forbidden", "the owner or the topic's sme sets its tags")
    with board._lock:  # adversary 09-23 #4: serialised with close(), so a tag write never re-opens a closed topic
        return board.ticket_update(actor, t.id, tags=normalize_tags(tags))


# ----------------------------------------------------------------------------- experts
def experts(board: Board, topic_id: str) -> list[Participant]:
    out = []
    for lk in board.store.query("link", {"from_id": topic_id, "relation": Relation.has_expert.value}, limit=-1):
        p = board.store.get("participant", lk.to_id)
        if p is not None:
            out.append(p)
    return out  # type: ignore[return-value]


def expert_topic(board: Board, p: Participant) -> str | None:
    """The one topic an expert participant belongs to (None once removed)."""
    rows = board.store.query("link", {"to_id": p.id, "relation": Relation.has_expert.value}, limit=1)
    return rows[0].from_id if rows else None  # type: ignore[union-attr]


def add_expert(board: Board, actor: Participant, topic_id: str, *, handle: str, name: str = "",
               mint: Any) -> tuple[Participant, str]:
    """The owner links a named human expert: participant type human, role expert, its own token minted
    by `mint(handle)` exactly like the owner's (tokens.json). Returns (expert, token) — the token is
    handed back this once and never listed again."""
    _owner_only(actor, "adds an expert to a topic")
    t = topic(board, topic_id)
    _open(t)
    h = handle.strip().lstrip("@").lower()
    if not _HANDLE.match(h):
        raise BoardError("invalid", f"{handle!r} is not a handle",
                         "2–40 of a-z 0-9 . _ -, starting with a letter or digit")
    if h in _RESERVED_HANDLES:
        raise BoardError("invalid", f"{handle!r} is a reserved name", "pick the person's own handle")
    with board._lock:
        p = board.participant_create("human", Role.expert, h, id_=h)
        token = mint(h)
        if not token:
            board.store.delete("participant", p.id)
            raise BoardError("invalid", "an expert needs its own token, and this board has no tokens.json",
                             "run the board in token mode (tokens.json with the owner's token) to add experts")
        board.store.put("link", Link(id=new_id("lk"), from_id=t.id, to_id=p.id, relation=Relation.has_expert,
                                     created_by=actor.id))
    board._pairing_note(t.id, f"{actor.id} added expert @{h}" + (f" ({name.strip()})" if name.strip() else "")
                        + " to this topic.")
    return p, token


def remove_expert(board: Board, actor: Participant, topic_id: str, expert_id: str, *, revoke: Any) -> None:
    _owner_only(actor, "removes an expert")
    t = topic(board, topic_id)
    rows = board.store.query("link", {"from_id": t.id, "to_id": expert_id,
                                      "relation": Relation.has_expert.value}, limit=-1)
    if not rows:
        raise BoardError("not_found", f"{expert_id} is not an expert on {t.id}")
    for lk in rows:
        board.store.delete("link", lk.id)
    revoke(expert_id)
    board._pairing_note(t.id, f"{actor.id} removed expert @{expert_id}; their token no longer works.")


# ----------------------------------------------------------------------------- read
def _last_update(board: Board, topic_id: str, field: str) -> dict[str, Any] | None:
    rows = board.store.query("event", {"subject_id": topic_id, "kind": EventKind.ticket_updated.value},
                             limit=-1, newest_first=True)  # adversary 09-23 #10: the seed outlives 200 tag writes
    for ev in rows:
        if field in (ev.data.get("changed") or []):
            return {**ev.data, "at": ev.created_at.isoformat()}
    return None


def seed_url(board: Board, topic_id: str) -> str | None:
    u = _last_update(board, topic_id, "seed_url")
    return u.get("seed_url") if u else None


def docs(board: Board, topic_id: str) -> list[Any]:
    """The docs this topic maintains: the knowledge docs it links, and every proposal filed from it."""
    ids: list[str] = [lk.to_id for rel in (Relation.uses_strategy, Relation.uses_domain)
                      for lk in board.store.query("link", {"from_id": topic_id, "relation": rel.value}, limit=-1)]
    for dtype in KNOWLEDGE_DOC_TYPES:
        for d in board.store.query("doc", {"doc_type": dtype}, limit=-1):
            if (d.source or {}).get("ticket") == topic_id and d.id not in ids:
                ids.append(d.id)
    out = [board.store.get("doc", i) for i in ids]
    return [d for d in out if d is not None]


def doc_for(board: Board, topic_id: str, doc_id: str) -> Any:
    if doc_id not in {d.id for d in docs(board, topic_id)}:
        raise BoardError("not_found", f"{doc_id} is not one of {topic_id}'s docs")
    return board.doc(doc_id)


def seat_view(board: Board, topic_id: str) -> dict[str, Any]:
    """The seat's latest session state (alive|parked|dead|stalled, mirrored from the pool); before the pool
    reports a session: queued (pairing pending), spawned (the pool took it) or not spawned."""
    pid = seat_id(topic_id)
    state = board.seat_state(pid)
    if state is None:
        state = ("queued" if pid in board._pending_pairings
                 else "spawned" if board.store.get("participant", pid) is not None else "not spawned")
    return {"participant": pid, "state": state}


def fetches(board: Board, topic_id: str, n: int = 10) -> list[dict[str, Any]]:
    rows = board.store.query("event", {"subject_id": topic_id, "kind": EventKind.topic_fetched.value},
                             limit=n, newest_first=True)
    return [dict(ev.data) for ev in rows]


def row(board: Board, t: Ticket) -> dict[str, Any]:
    return {"id": t.id, "title": t.title, "tags": t.tags, "status": "closed" if t.status in _TERMINAL else "open",
            "created_at": t.created_at.isoformat(), "created_by": t.created_by, "seat": seat_view(board, t.id),
            "docs": len(docs(board, t.id)), "experts": len(experts(board, t.id)),
            "messages": board.store.thread_count(t.id)}


def list_view(board: Board) -> list[dict[str, Any]]:
    ts = board.store.query("ticket", {"kind": TicketKind.topic.value}, limit=-1, newest_first=True)
    return [row(board, t) for t in ts]  # type: ignore[arg-type]


def page(board: Board, topic_id: str, *, thread_limit: int = 200) -> dict[str, Any]:
    """Everything the topic page shows: the record, who set its tags, its docs, thread, experts and seat.
    Expert tokens are never part of it."""
    t = topic(board, topic_id)
    tags_by = _last_update(board, t.id, "tags")
    people: dict[str, dict[str, Any]] = {}

    def who(pid: str) -> dict[str, Any]:
        if pid not in people:
            p = board.store.get("participant", pid)
            people[pid] = {"id": pid, "role": p.role.value if p else ("board" if pid == "board" else None),
                           "type": p.type if p else "agent"}
        return people[pid]

    thread = [{"id": m.id, "created_at": m.created_at.isoformat(), "created_by": m.created_by, "to": m.to,
               "kind": m.kind.value, "text": m.text, "reply_to": m.reply_to, "from": who(m.created_by)}
              for m in board.thread(t.id, limit=thread_limit)]
    return {
        "topic": {**row(board, t), "description": t.description},
        "seed_url": seed_url(board, t.id),
        "tags_set_by": {"by": tags_by.get("by"), "at": tags_by.get("at")} if tags_by else None,
        "docs": [{**board._doc_summary(d, 240), "source_url": d.source_url, "proposes": d.proposes,
                  "resolution": d.resolution, "created_by": d.created_by, "created_at": d.created_at.isoformat()}
                 for d in docs(board, t.id)],
        "thread": thread,
        "experts": [{"id": p.id, "handle": p.handle, "created_at": p.created_at.isoformat()}
                    for p in experts(board, t.id)],
        "seat": seat_view(board, t.id),
        "fetches": fetches(board, t.id),
    }


def post(board: Board, actor: Participant, topic_id: str, *, text: str, kind: MessageKind = MessageKind.note,
         to: str | None = None, reply_to: str | None = None) -> Any:
    """Owner or expert posts on the topic thread (the sme uses message_send like any seat)."""
    t = topic(board, topic_id)
    _open(t)
    if actor.role == Role.expert and kind not in EXPERT_KINDS:
        raise BoardError("forbidden", f"an expert posts {', '.join(k.value for k in EXPERT_KINDS)}")
    if not text.strip():
        raise BoardError("invalid", "the message is empty")
    return board.message_send(actor, ticket_id=t.id, to=to or None, kind=kind, text=text, reply_to=reply_to)


# ----------------------------------------------------------------------------- research (the sme's own browsing)
SKILLS_HOSTS = ("skills.sh", "www.skills.sh")
BASE_HOSTS = (*SKILLS_HOSTS, "github.com", "raw.githubusercontent.com")
SEARCH_URL = "https://www.skills.sh/api/search?q="
TEXT_CAP = 12_000  # characters of page text handed back to the seat; the receipt keeps the byte count
MAX_REDIRECTS = 3


def allowed_hosts(board: Board, topic_id: str) -> tuple[str, ...]:
    """skills.sh (search + skill pages), GitHub (a skill's SKILL.md) and the topic's seed-URL host."""
    seed = seed_url(board, topic_id)
    host = urlsplit(seed).netloc.lower() if seed else ""
    return (*BASE_HOSTS, host) if host and host not in BASE_HOSTS else BASE_HOSTS


def http_fetch(url: str) -> tuple[int, bytes, str | None]:
    """One bounded GET, no automatic redirects: (status, body, Location). Same caps as the owner's import
    (library.MAX_BYTES, library.TIMEOUT_S total)."""
    deadline = time.monotonic() + TIMEOUT_S
    with httpx.Client(timeout=TIMEOUT_S, follow_redirects=False,
                      headers={"User-Agent": "edp8-topic-research/1"}) as c, c.stream("GET", url) as r:
        if r.status_code != 200:
            return r.status_code, b"", r.headers.get("location")
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise BoardError("invalid", f"{url} is larger than {MAX_BYTES // 1024} KB", "fetch a smaller page")
            if time.monotonic() > deadline:
                raise httpx.ReadTimeout(f"{url} took longer than {TIMEOUT_S:.0f} s")
        return 200, bytes(buf), None


# tests replace this with a recorded page; production is http_fetch
FETCH = http_fetch


def _check_host(url: str, hosts: tuple[str, ...]) -> None:
    u = urlsplit(url)
    if u.scheme != "https" or u.netloc.lower() not in hosts:
        raise BoardError("forbidden", f"{url!r} is outside this topic's research hosts",
                         f"https on: {', '.join(hosts)} (the owner's seed URL sets the extra host)")


def fetch(url: str, hosts: tuple[str, ...]) -> tuple[str, int, bytes]:
    """GET `url`, following at most MAX_REDIRECTS redirects that stay inside `hosts`. Returns
    (final url, status, body)."""
    cur = url.strip()
    for _ in range(MAX_REDIRECTS + 1):
        _check_host(cur, hosts)
        try:
            status, body, loc = FETCH(cur)
        except httpx.HTTPError as e:
            raise BoardError("invalid", f"fetching {cur} failed: {type(e).__name__}", "retry later") from e
        if status in (301, 302, 303, 307, 308) and loc:
            cur = urljoin(cur, loc)
            continue
        return cur, status, body
    raise BoardError("invalid", f"{url} redirects more than {MAX_REDIRECTS} times")


_DROP = re.compile(r"<(script|style|noscript|svg|head)\b.*?</\1\s*>", re.S | re.I)
_BLOCK = re.compile(r"</?(p|div|li|ul|ol|h[1-6]|br|tr|pre|section|article|header|footer|table)\b[^>]*>", re.I)


def html_text(raw: str) -> str:
    """A page's readable text: scripts/styles dropped, block tags as line breaks, entities decoded.
    Markdown or plain text comes back as is."""
    low = raw[:20_000].lower()
    if "<html" not in low and "<body" not in low:
        return raw.strip()
    s = _BLOCK.sub("\n", _DROP.sub(" ", raw))
    s = _html.unescape(re.sub(r"<[^>]+>", " ", s))
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in s.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _receipt(board: Board, actor: Participant, t: Ticket, *, requested: str, final: str, status: int,
             size: int, kind: str) -> dict[str, Any]:
    data = {"url": normalize_source(final), "requested": requested, "status": status, "bytes": size, "kind": kind,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"), "by": actor.id}
    board._emit(t.id, EventKind.topic_fetched, data)
    return data


def research(board: Board, actor: Participant, topic_id: str, *, query: str | None = None,
             url: str | None = None) -> dict[str, Any]:
    """The topic seat's browsing: `query` searches skills.sh; `url` reads one page (a skills.sh skill page,
    a GitHub SKILL.md, or a page on the seed host). Every fetch leaves a receipt on the topic."""
    t = topic(board, topic_id)
    _open(t)
    if actor.role != Role.owner and actor.id != t.assignee:
        raise BoardError("forbidden", "the topic's sme researches it")
    if bool(query) == bool(url):
        raise BoardError("invalid", "give exactly one of query or url")
    hosts = allowed_hosts(board, t.id)
    if query:
        req = SEARCH_URL + quote(query.strip())
        final, status, body = fetch(req, hosts)
        rec = _receipt(board, actor, t, requested=req, final=final, status=status, size=len(body), kind="search")
        skills: list[dict[str, Any]] = []
        if status == 200:
            try:
                skills = json.loads(body.decode("utf-8", errors="replace")).get("skills") or []
            except ValueError:
                skills = []
        rows = [{"name": s.get("name"), "id": s.get("id"), "installs": s.get("installs"),
                 "page": f"https://www.skills.sh/{s.get('id')}"} for s in skills[:10] if s.get("id")]
        return {"receipt": rec, "results": rows,
                "next": "topic_research(url=<a result's page>) to read one, then topic_propose from what it says"}
    final, status, body = fetch(url or "", hosts)
    rec = _receipt(board, actor, t, requested=(url or "").strip(), final=final, status=status, size=len(body),
                   kind="page")
    text = html_text(body.decode("utf-8", errors="replace")) if status == 200 else ""
    return {"receipt": rec, "text": text[:TEXT_CAP], "truncated": len(text) > TEXT_CAP,
            "next": "distil what applies to this topic, then topic_propose(source_url=<this url>)"}


def _receipt_for(board: Board, topic_id: str, source_url: str) -> dict[str, Any] | None:
    key = normalize_source(source_url)
    for ev in board.store.query("event", {"subject_id": topic_id, "kind": EventKind.topic_fetched.value},
                                limit=500, newest_first=True):
        d = ev.data
        if d.get("status") == 200 and key in (d.get("url"), normalize_source(d.get("requested") or "")):
            return dict(d)
    return None


def propose(board: Board, actor: Participant, topic_id: str, *, title: str, body_md: str, source_url: str,
            doc_type: DocType = DocType.strategy_hl, tags: list[str] | None = None,
            proposes: str | None = None) -> dict[str, Any]:
    """File what the seat learned as a PROPOSED Library doc (a new doc, or with `proposes` the next version
    of an active one) carrying its source URL and fetched-at in the header — from this topic's receipt, so
    only a page the topic actually fetched can be cited. The owner approves it in the Library."""
    t = topic(board, topic_id)
    _open(t)
    if actor.id != t.assignee:
        raise BoardError("forbidden", "the topic's sme files its proposals")
    if DocType(doc_type).value not in KNOWLEDGE_DOC_TYPES:
        raise BoardError("invalid", f"a topic proposes {', '.join(KNOWLEDGE_DOC_TYPES)} docs")
    rec = _receipt_for(board, t.id, source_url)
    if rec is None:
        raise BoardError("invalid", f"{source_url} was not fetched for {t.id}",
                         "topic_research(url=...) it first; a proposal cites a page this topic read")
    head = f"> Source: {rec['url']} · fetched-at {rec['fetched_at']} (topic {t.id}, research by {actor.id})"
    d = board.doc_create(actor, doc_type=DocType(doc_type), title=title.strip(),
                         body_md=f"{head}\n\n{body_md.lstrip()}", scope="global",
                         tags=normalize_tags([*t.tags, *(tags or [])]), status=DocStatus.proposed,
                         proposes=proposes, ticket_id=t.id, source_url=rec["url"])
    return {"doc": d, "receipt": rec}
