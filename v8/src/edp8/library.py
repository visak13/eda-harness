"""The Library's knowledge side (S-LIBRARY, design-34bf11cc07 §4.3): the strategy/domain docs and
lessons the Library tab lists, and the one-shot "Import from skills.sh".

Import is a single bounded server-side fetch, never something a seat runs at boot: a skills.sh
page URL (`https://skills.sh/<owner>/<repo>/<skill>`) resolves to the skill's raw SKILL.md on
GitHub (the page names the repo; the file sits at `skills/<skill>/SKILL.md`, `<skill>/SKILL.md` or
the repo root), a GitHub blob URL resolves to its raw form, and a raw SKILL.md URL is taken as is.
Only those three hosts are fetched (no open proxy). The doc keeps `source_url` so a repeat import
of the same URL writes the next version of that doc instead of a duplicate.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .board import Board, BoardError
from .schemas import KNOWLEDGE_DOC_TYPES, DocStatus, DocType, Participant, Relation, TicketKind, normalize_tags

MAX_BYTES = 256 * 1024
TIMEOUT_S = 10.0
ALLOWED_HOSTS = ("skills.sh", "www.skills.sh", "github.com", "raw.githubusercontent.com")
_RAW = "https://raw.githubusercontent.com"
_SEG = re.compile(r"^[A-Za-z0-9_.\-]+$")


# ----------------------------------------------------------------------------- knowledge view
def knowledge_view(board: Board) -> dict[str, Any]:
    """Every strategy/domain doc (all statuses, newest first) with its tags, provenance and the
    epics it is linked to (uses_strategy/uses_domain, with link ids so the tab can unlink), plus
    every lesson. `{ok, value}` envelope is the caller's."""
    docs = [d for t in KNOWLEDGE_DOC_TYPES for d in board.store.query("doc", {"doc_type": t}, limit=2000)]
    docs.sort(key=lambda d: d.created_at, reverse=True)
    links = [lk for rel in (Relation.uses_strategy, Relation.uses_domain)
             for lk in board.store.query("link", {"relation": rel}, limit=100_000)]
    by_doc: dict[str, list[dict[str, Any]]] = {}
    tickets: dict[str, Any] = {}
    for lk in links:
        t = tickets.get(lk.from_id) or board.store.get("ticket", lk.from_id)
        if t is None:
            continue
        tickets[lk.from_id] = t
        by_doc.setdefault(lk.to_id, []).append({"link_id": lk.id, "ticket_id": t.id, "kind": t.kind.value,
                                                 "title": t.title, "relation": lk.relation.value})
    rows = []
    for d in docs:
        rows.append({**board._doc_summary(d, 240), "created_by": d.created_by,
                     "created_at": d.created_at.isoformat(), "source": d.source, "source_url": d.source_url,
                     "resolution": d.resolution, "linked": by_doc.get(d.id, [])})
    lessons = [{"id": le.id, "domain": le.domain, "topic": le.topic, "text": le.text, "status": le.status.value,
                "created_by": le.created_by, "created_at": le.created_at.isoformat()}
               for le in board.store.query("lesson", {}, limit=2000, newest_first=True)]
    epics = [{"id": t.id, "title": t.title, "status": t.status.value}
             for t in board.store.query("ticket", {"kind": TicketKind.epic.value}, limit=2000, newest_first=True)]
    tags = sorted({t for r in rows for t in r["tags"]})
    return {"docs": rows, "lessons": lessons, "tags": tags, "epics": epics}


# ----------------------------------------------------------------------------- skills.sh import
def normalize_source(url: str) -> str:
    """The re-import key: scheme+host+path, no query/fragment/trailing slash, host lower-cased."""
    u = urlsplit(url.strip())
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path.rstrip("/"), "", ""))


def candidate_urls(url: str) -> list[str]:
    """The raw SKILL.md URLs to try for `url`, in order. Refuses non-https and foreign hosts."""
    u = urlsplit(url.strip())
    host = u.netloc.lower()
    if u.scheme != "https" or host not in ALLOWED_HOSTS:
        raise BoardError("invalid", f"cannot import from {url!r}",
                         "give a https://skills.sh/<owner>/<repo>/<skill> page or a raw SKILL.md URL on GitHub")
    parts = [p for p in u.path.split("/") if p]
    if host.endswith("skills.sh"):
        if len(parts) != 3 or not all(_SEG.match(p) for p in parts):
            raise BoardError("invalid", f"{url!r} is not a skill page",
                             "a skills.sh skill page looks like https://skills.sh/<owner>/<repo>/<skill>")
        o, r, sk = parts
        return [f"{_RAW}/{o}/{r}/HEAD/skills/{sk}/SKILL.md", f"{_RAW}/{o}/{r}/HEAD/{sk}/SKILL.md",
                f"{_RAW}/{o}/{r}/HEAD/SKILL.md"]
    if host == "github.com":
        if len(parts) < 5 or parts[2] != "blob" or not parts[-1].lower().endswith(".md"):
            raise BoardError("invalid", f"{url!r} is not a GitHub file URL",
                             "use https://github.com/<owner>/<repo>/blob/<ref>/<path>/SKILL.md")
        return [f"{_RAW}/{parts[0]}/{parts[1]}/{'/'.join(parts[3:])}"]
    if not parts or not parts[-1].lower().endswith(".md"):
        raise BoardError("invalid", f"{url!r} is not a markdown file", "give the raw SKILL.md URL")
    return [urlunsplit(("https", host, u.path, "", ""))]


def http_get(url: str) -> tuple[int, bytes]:
    """One bounded GET: no redirects (a redirect could leave the allowed hosts), TIMEOUT_S total,
    at most MAX_BYTES read. Returns (status, body); a body over the cap raises."""
    deadline = time.monotonic() + TIMEOUT_S
    with httpx.Client(timeout=TIMEOUT_S, follow_redirects=False) as c, c.stream("GET", url) as r:
        if r.status_code != 200:
            return r.status_code, b""
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise BoardError("invalid", f"{url} is larger than {MAX_BYTES // 1024} KB", "import a smaller skill")
            if time.monotonic() > deadline:  # a slow drip under the read timeout still stops at TIMEOUT_S
                raise httpx.ReadTimeout(f"{url} took longer than {TIMEOUT_S:.0f} s")
        return 200, bytes(buf)


# tests replace this (a stubbed fetch); production is http_get
FETCH = http_get


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """A SKILL.md's YAML frontmatter, hand-parsed for the keys we use (no YAML dependency):
    scalar `key: value`, inline lists `[a, b]`, block lists (`- a`) and keys nested one level
    (e.g. `metadata:` → `tags:`) flattened. Returns (fields, body without the frontmatter)."""
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    if not m:
        return {}, text
    fields: dict[str, Any] = {}
    last: str | None = None
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", raw)
        if item and last is not None:
            cur = fields.get(last)
            fields[last] = [*(cur if isinstance(cur, list) else []), _scalar(item.group(1))]
            continue
        kv = re.match(r"^\s*([A-Za-z0-9_\-]+)\s*:\s*(.*)$", raw)
        if not kv:
            continue
        key, val = kv.group(1).lower(), kv.group(2).strip()
        last = key
        if val.startswith("[") and val.endswith("]"):
            fields[key] = [_scalar(x) for x in val[1:-1].split(",") if x.strip()]
        elif val:
            fields.setdefault(key, _scalar(val))  # a top-level key wins over a nested one of the same name
        else:
            fields.setdefault(key, [])
    return fields, text[m.end():]


def _scalar(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1]
    return v


def _tags_of(fields: dict[str, Any]) -> list[str]:
    raw = fields.get("tags") or fields.get("keywords") or []
    if isinstance(raw, str):
        raw = [x for x in re.split(r"[,\s]+", raw) if x]
    return normalize_tags(raw)


def import_skill(board: Board, actor: Participant, url: str, *, scope: str = "global",
                 tags: list[str] | None = None) -> dict[str, Any]:
    """Fetch one skill and file it as a strategy_hl doc (title, body, frontmatter tags, source_url).
    Same URL again → the next version of that doc. Authoring rights are DOC_AUTHORS[strategy_hl]."""
    key = normalize_source(url)
    tried: list[str] = []
    text: str | None = None
    fetched: str | None = None
    for cand in candidate_urls(url):
        tried.append(cand)
        try:
            status, body = FETCH(cand)
        except httpx.HTTPError as e:
            raise BoardError("invalid", f"fetching {cand} failed: {type(e).__name__}", "retry, or give the raw SKILL.md URL") from e
        if status == 200 and body:
            text, fetched = body.decode("utf-8", errors="replace"), cand
            break
    if text is None:
        raise BoardError("not_found", f"no SKILL.md found for {url}", f"tried: {', '.join(tried)}")
    fields, body_md = parse_frontmatter(text)
    parts = [p for p in urlsplit(key).path.split("/") if p]
    name = str(fields.get("name") or (parts[-2] if parts and parts[-1].lower() == "skill.md" and len(parts) > 1
                                       else parts[-1] if parts else "skill"))
    desc = str(fields.get("description") or "").strip()
    head = [f"> Imported from {url.strip()} (skills.sh source; fetched {fetched})."]
    if desc:
        head.append(f"> {desc}")
    doc_body = "\n".join(head) + "\n\n" + body_md.lstrip()
    all_tags = normalize_tags([*_tags_of(fields), "skills-sh", *(tags or [])])
    title = f"skill: {name}"
    # lookup and write under the board's lock: two imports of one URL cannot both see "no doc yet"
    with board._lock:
        existing = [d for d in board.store.query("doc", {"doc_type": DocType.strategy_hl}, limit=-1)
                    if d.source_url == key and d.status != DocStatus.retired]
        if existing:
            d = board.doc_update(actor, existing[0].id, body_md=doc_body, title=title,
                                 tags=normalize_tags([*existing[0].tags, *all_tags]))
            return {"doc": d, "created": False, "fetched": fetched}
        d = board.doc_create(actor, doc_type=DocType.strategy_hl, title=title, body_md=doc_body, scope=scope,
                             tags=all_tags, source_url=key)
        return {"doc": d, "created": True, "fetched": fetched}


# ----------------------------------------------------------------------------- auto-link (S-IMPLICIT)
def plain_tags(tags: list[str] | None) -> set[str]:
    """The tags that can match a Library doc: words only — `model:<role>=…`, `seat-model:…` and other
    key:value / key=value tags configure seats, and `quick` marks the ticket kind, so none of them link."""
    return {t for t in normalize_tags(tags) if ":" not in t and "=" not in t and t != "quick"}


def autolink(board: Board, ticket_id: str, *, trigger: str) -> list[dict[str, Any]]:
    """Link every ACTIVE strategy/domain doc whose tags intersect the ticket's (and its epic's) plain tags
    — uses_domain for a domain doc, uses_strategy otherwise — and post one board note on the ticket naming
    each doc and its link id so the architect or owner can unlink it (link_delete). Already-linked docs are
    skipped. Returns [{doc, title, tags, link}] of the new links; no note when nothing was linked."""
    from . import records  # local: records is the board-authored identity

    t = board.ticket(ticket_id)
    want = plain_tags([*(board.epic_of(t).tags or []), *(t.tags or [])])
    if not want:
        return []
    have = {lk.to_id for rel in (Relation.uses_strategy, Relation.uses_domain)
            for lk in board.store.query("link", {"from_id": t.id, "relation": rel}, limit=-1)}
    out: list[dict[str, Any]] = []
    for dtype in KNOWLEDGE_DOC_TYPES:
        for d in board.store.query("doc", {"doc_type": dtype}, limit=-1):
            if d.status != DocStatus.active or d.id in have:
                continue
            hit = sorted(want & set(d.tags or []))
            if not hit:
                continue
            rel = Relation.uses_domain if dtype == DocType.domain.value else Relation.uses_strategy
            lk = board.link_create(records.board_actor(), from_id=t.id, to_id=d.id, relation=rel)
            out.append({"doc": d.id, "title": d.title, "tags": hit, "link": lk.id, "relation": rel.value})
            have.add(d.id)
    if out:
        lines = "; ".join(f"{o['doc']} \"{o['title']}\" (tags {', '.join(o['tags'])}; {o['relation']} {o['link']})"
                          for o in out)
        board._pairing_note(t.id, f"Library auto-link at {trigger}: linked {len(out)} doc(s) by tag — {lines}. "
                                  "Unlink one with link_delete(<link id>).")
    return out
