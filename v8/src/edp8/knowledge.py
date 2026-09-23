"""edp8 lookup — deterministic retrieval over decision/claim/lesson records + kglinks.

A port of poc/kg/walk.py onto the board's own Store (design-d2c4f39fc6 §4.2): binding
decisions in scope are always included (never cut), the rest is a scored, 2-hop, capped
remainder. Epic isolation is enforced on every candidate — a lookup scoped to one epic
never returns another epic's decisions/claims; lessons are the sole cross-epic exception,
matched by domain/topic.

Pure functions over a Store; no board/emit/index side effects. board.lookup() wires the
optional semantic index and git heads in.
"""

from __future__ import annotations

import json as _json
import math
import os
import re
from datetime import datetime
from typing import Any, Callable

from .schemas import now

RECORD_TYPES = ("decision", "claim", "lesson")
EPIC_TYPES = ("decision", "claim")  # the epic-isolated types; lessons are filed nowhere
MAX_RECORDS = 40
MAX_BYTES = 8000
ALWAYS_MAX_BYTES = 2000  # R2-5: the "Always applies" (binding, text-only) section's byte reserve
MAX_HOPS = 2
SEED_TOP = 8  # R2-6/D4: each leg (FTS, dense) casts at least its top-8 vote, then RRF-fused
SEED_TOP_CAP = 24  # E1 (steer m-a006bfe2a5): per-leg seed count caps here when scaled by epic size
SEED_SCALE_DIV = 6  # E1: per-leg = max(SEED_TOP, ceil(live_records / SEED_SCALE_DIV)), cap SEED_TOP_CAP


def _seed_per_leg(live_count: int) -> int:
    """E1: on a large epic the fixed 8+8 seed net missed live records that existed but never seeded.
    Scale each leg with the scope's live-record count — max(8, ceil(live/6)), capped at 24 per leg —
    so recall grows with the corpus while the BFS stays bounded (union cap = 2x per-leg)."""
    scaled = -(-max(0, live_count) // SEED_SCALE_DIV)  # ceil division
    return min(SEED_TOP_CAP, max(SEED_TOP, scaled))
# D2: seeds carry a rank-decayed weight in [SEED_W_LO, SEED_W_HI] so ranked scores discriminate by
# retrieval relevance instead of collapsing to a constant; both stay above the 0.6 one-hop weight.
SEED_W_HI = 1.0
SEED_W_LO = 0.7
# R2-7 source fallback: when the question reaches too few strong records, quote the epic's raw
# messages/doc paragraphs so a not-yet-curated answer is still visible (marked unconfirmed).
RELEVANCE_FLOOR = 0.5   # graph weight (1.0 = a direct seed, 0.6 = one strong hop) that counts as strong
MIN_RELEVANT = 3        # below this many strong records, add the source-excerpt tier
MAX_EXCERPTS = 4
EXCERPT_CHARS = 400
# C4 (steer m-cb8198669e): the reader kept seeing the same few unrelated decisions under every
# question. In "For your question", drop any ranked record whose fused score is below this fraction
# of the top hit's score — unless it is linked by replaces or part_of to a kept record (so chains and
# a claim's own ticket group are not orphaned). Fewer, relevant records beat a full budget of noise.
RANKED_FLOOR_FRAC = float(os.environ.get("EDP8_RANKED_FLOOR", "0.35"))  # 0 disables (for A/B measuring)
RESCUE_KINDS = {"replaces", "part_of"}

# link weight: how much a hop across this kind carries relevance (design §4.2 step 5).
LINK_WEIGHT = {
    "must_follow": 1.0,
    "decides": 0.9,
    "verifies": 0.7,
    "implements": 0.6,
    "learned_from": 0.6,
}
DEFAULT_WEIGHT = 0.3
# never traversed: came_from points at sources; replaces points at superseded records.
SKIP_KINDS = {"came_from", "replaces"}
# Item 3 (steer m-3f96079aa8): claims were under-used — they only surfaced when they seeded on their
# own words, because the source message they share with a decision is a came_from edge (never walked).
# A matched decision now pulls the claims recorded from the SAME source (or citing it as evidence),
# and a matched claim pulls its decision, at this hop weight (same as `implements`).
CO_SOURCE_WEIGHT = 0.6
# per-type score multiplier: an unconfirmed claim (an assumption, or no evidence) ranks below a live
# decision of equal match; a lesson is filed nowhere, so it ranks a notch below an epic-local record.
TYPE_WEIGHT = {"decision": 1.0, "claim": 1.0, "claim_unconfirmed": 0.8, "lesson": 0.9}
# Lessons tail: lessons render in their own section, "Lessons from elsewhere", never in the ranked
# section — at most MAX_LESSONS within LESSON_MAX_BYTES, reserved inside the 8,000-byte cap.
MAX_LESSONS = 3
LESSON_MAX_BYTES = 1500
# E5 (finding m-205a352fec): the board ranks the dense leg WITHIN the scope (live_scope_ids as allow_ids)
# and fetches this many in-scope hits, enough to fill the largest adaptive leg.
DENSE_FETCH = 2 * SEED_TOP_CAP


def live_scope_ids(store: Any, target_epic: str | None) -> set[str]:
    """E5: ids of the live records a dense search may return for this scope — the epic's live
    decisions/claims plus every live lesson (cross-epic). The board passes this as allow_ids so the dense
    leg ranks WITHIN the epic instead of taking a global top-k and filtering it afterwards."""
    ids: set[str] = set()
    for rtype in EPIC_TYPES:
        if target_epic is None:
            break
        for r in store.query(rtype, limit=100000):
            if not _dropped(r, rtype) and _epic_id_of(store, getattr(r, "scope", "") or "") == target_epic:
                ids.add(r.id)
    for les in store.query("lesson", limit=100000):
        if not _dropped(les, "lesson"):
            ids.add(les.id)
    return ids


def _tokens(q: str) -> str:
    return " OR ".join(f'"{t}"' for t in re.findall(r"[\w\-]+", q or ""))


def _epic_id_of(store: Any, scope_id: str, _seen: set[str] | None = None) -> str | None:
    """The epic a scope (epic|ticket id) belongs to, following parent_id. None if not a ticket."""
    _seen = _seen or set()
    t = store.get("ticket", scope_id)
    if t is None:
        return None
    if getattr(t, "epic_id", None):
        return t.epic_id
    # walk up defensively (older rows may lack epic_id)
    while t is not None and t.parent_id and t.id not in _seen:
        _seen.add(t.id)
        t = store.get("ticket", t.parent_id)
    return t.id if t is not None else None


def _record_epic(store: Any, rec: Any, rec_type: str) -> str | None:
    """The epic a decision/claim belongs to. Lessons have no epic (cross-epic by design)."""
    if rec_type == "lesson":
        return None
    return _epic_id_of(store, getattr(rec, "scope", "") or "")


def _confirmed(rec: Any, rec_type: str) -> bool:
    if rec_type == "claim":
        return bool(rec.evidence) and rec.basis in ("measured", "ruled") and rec.status != "refuted"
    if rec_type == "decision":
        return rec.status == "live"
    if rec_type == "lesson":
        return rec.status == "live"
    return True


def _dropped(rec: Any, rec_type: str) -> bool:
    """Replaced/withdrawn decisions, refuted claims, retired lessons never surface."""
    st = getattr(rec, "status", "live")
    if rec_type == "decision":
        return st in ("replaced", "withdrawn")
    if rec_type == "claim":
        return st in ("refuted", "withdrawn")
    if rec_type == "lesson":
        return st == "retired"
    return False


def _freshness(created_at: datetime, ref: datetime) -> float:
    age_days = max(0.0, (ref - created_at).total_seconds() / 86400.0)
    return 1.0 / (1.0 + age_days / 30.0)


def _effective_date(rec: Any) -> datetime:
    """When the ruling/claim was MADE. For a backfilled record created_at is only the evening it was
    written, so freshness and the rendered date use decided_at (the source msg/doc date) when set,
    falling back to created_at (steer m-34d0beb1e8)."""
    return getattr(rec, "decided_at", None) or rec.created_at


def _usefulness(rec: Any, rec_type: str) -> float:
    if rec_type != "lesson":
        return 1.0
    helped, harmed = max(0, rec.helped or 0), max(0, rec.harmed or 0)  # never let a stray negative blow up log
    return 1.0 + math.log(1 + helped) - math.log(1 + harmed)


def _find_record(store: Any, node_id: str) -> tuple[str, Any] | None:
    for t in RECORD_TYPES:
        o = store.get(t, node_id)
        if o is not None:
            return t, o
    return None


def _adjacency(store: Any) -> dict[str, list[tuple[str, str]]]:
    """Undirected node->list[(other, kind)] over kglinks, skipping came_from/replaces edges."""
    adj: dict[str, list[tuple[str, str]]] = {}
    for lk in store.query("kglink", limit=100000):
        if lk.kind in SKIP_KINDS:
            continue
        adj.setdefault(lk.from_id, []).append((lk.to_id, lk.kind))
        adj.setdefault(lk.to_id, []).append((lk.from_id, lk.kind))
    return adj


def _as_date(dt: Any) -> str:
    """The date portion of a created_at (datetime or ISO string), for the 'replaced <date>' tag."""
    if isinstance(dt, datetime):
        return dt.date().isoformat()
    return str(dt)[:10]


def _excerpt(text: str, question: str | None, width: int = EXCERPT_CHARS) -> str:
    """A ≤width-char window around the earliest question token, else the head of the text."""
    text = " ".join((text or "").split())
    if len(text) <= width:
        return text
    lo = text.lower()
    best = -1
    for term in re.findall(r"[\w\-]+", (question or "").lower()):
        idx = lo.find(term)
        if idx != -1 and (best == -1 or idx < best):
            best = idx
    start = 0 if best == -1 else max(0, best - width // 3)
    return text[start:start + width]


def _source_excerpts(store: Any, target_epic: str | None, question: str | None,
                     source_search: Callable[[str], list[dict[str, Any]]] | None) -> list[dict[str, str]]:
    """R2-7: quote up to MAX_EXCERPTS of the epic's OWN messages/doc paragraphs (FTS ∪ embeddings,
    scope-limited, newest-first) when the curated records did not answer the question. These are
    unconfirmed source material, never treated as decisions."""
    if not question or target_epic is None:
        return []
    hits: list[dict[str, Any]] = []
    if source_search is not None:
        try:
            hits = source_search(question)
        except Exception:
            hits = []
    if not hits:
        try:
            hits = store.fts_search(question, types={"message", "doc"}, limit=30)
        except Exception:
            hits = []
    cand: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for h in hits:
        t, i = h.get("type"), h.get("id")
        if t not in ("message", "doc") or not i or i in seen:
            continue
        seen.add(i)
        obj = store.get(t, i)
        if obj is None:
            continue
        ep = _epic_id_of(store, (getattr(obj, "ticket_id", "") if t == "message"
                                 else getattr(obj, "scope", "")) or "")
        if ep == target_epic:
            cand.append((t, obj))
    cand.sort(key=lambda to: to[1].created_at, reverse=True)  # newest-first
    out: list[dict[str, str]] = []
    for t, obj in cand[:MAX_EXCERPTS]:
        body = obj.text if t == "message" else f"{getattr(obj, 'title', '')} {getattr(obj, 'body_md', '')}"
        out.append({"id": obj.id, "type": t, "author": obj.created_by or "",
                    "date": _as_date(obj.created_at), "text": _excerpt(body, question)})
    return out


def _history_chain(store: Any, rec: Any, _seen: set[str] | None = None) -> list[dict[str, str]]:
    """The replaces chain under a live decision (design R2-1): every decision it superseded,
    directly or transitively, newest-first, each tagged with the date it was replaced (the
    created_at of the record that replaced it). Replaced records never rank on their own — they
    live only here, inline, so 'what was first proposed and why it changed' is answerable."""
    _seen = _seen or set()
    out: list[dict[str, str]] = []
    for lk in store.query("kglink", {"from_id": rec.id, "kind": "replaces"}, limit=100):
        old = store.get("decision", lk.to_id)
        if old is None or old.id in _seen:
            continue
        _seen.add(old.id)
        out.append({"id": old.id, "text": old.text, "date": _as_date(rec.created_at),
                    **({"source": old.source} if getattr(old, "source", None) else {})})
        out.extend(_history_chain(store, old, _seen))
    return out


def _leg_ranked(store: Any, hits: Any, target_epic: str | None, limit: int,
                types: tuple[str, ...] = EPIC_TYPES) -> list[str]:
    """One retrieval leg's hits → in-scope record ids of `types` in rank order, de-duped, capped at `limit`."""
    out: list[str] = []
    seen: set[str] = set()
    for h in hits or []:
        nid = h["id"] if isinstance(h, dict) else h
        if nid in seen:
            continue
        found = _find_record(store, nid)
        if not found:
            continue
        rtype, rec = found
        if rtype not in types:
            continue  # item 3: lessons seed on their own leg, never taking an epic record's slot
        if _dropped(rec, rtype):
            continue  # a replaced/withdrawn/refuted record must not take a seed slot
        if _in_scope(store, rec, rtype, target_epic):
            out.append(nid)
            seen.add(nid)
        if len(out) >= limit:
            break
    return out


def _seed(store: Any, *, question: str | None, node_id: str | None, path: str | None,
          target_epic: str | None,
          semantic: Callable[[str], list[dict[str, Any]]] | None,
          per_leg: int = SEED_TOP,
          ) -> tuple[list[str], dict[str, float], str]:
    """Seed nodes, their retrieval weights, and the seed kind. Explicit id/path win; else the FTS and
    DENSE legs each cast their own top-`per_leg` vote (D4: not top-N of one fused search, so a weak leg
    cannot crowd out the other; E1: `per_leg` scales with epic size), fused via RRF. Seeds carry a
    rank-decayed weight in [SEED_W_LO, 1.0] so the ranked scores discriminate (D2)."""
    if node_id:
        rec = _find_record(store, node_id)
        if rec:
            # an explicit record id seeds only if it is in scope (never bridge to a foreign epic)
            if _in_scope(store, rec[1], rec[0], target_epic):
                return [node_id], {node_id: 1.0}, "id"
            return [], {}, "id_out_of_scope"
        if store.get("ticket", node_id) or store.get("doc", node_id):
            return [node_id], {node_id: 1.0}, "id"
    if path:
        # a path seeds through kglink endpoints that name it (touches edges), else FTS on the string.
        hits = [lk.from_id for lk in store.query("kglink", {"to_id": path}, limit=50)][:per_leg]
        if hits:
            return hits, {h: 1.0 for h in hits}, "path"
        question = question or path
    if not question:
        return [], {}, "none"
    # Each leg over-fetches past SEED_TOP so in-scope hits are not crowded out by foreign matches
    # before scope filtering (design §4.2: seeds are limited to the agent's epic).
    try:
        fts_leg = _leg_ranked(store, store.fts_search(question, types=set(RECORD_TYPES), limit=200),
                              target_epic, per_leg)
    except Exception:
        fts_leg = []
    dense_leg: list[str] = []
    if semantic is not None:
        try:
            dense_leg = _leg_ranked(store, semantic(question), target_epic, per_leg)
        except Exception:
            dense_leg = []
    # RRF over the two legs' rank lists; each leg gets an equal, independent vote.
    rrf_k = 60
    fused: dict[str, float] = {}
    for leg in (fts_leg, dense_leg):
        for rank, nid in enumerate(leg, start=1):
            fused[nid] = fused.get(nid, 0.0) + 1.0 / (rrf_k + rank)
    order = sorted(fused, key=lambda nid: (-fused[nid], nid))[:2 * per_leg]  # E1: union cap scales too
    n = len(order)
    weights: dict[str, float] = {}
    for i, nid in enumerate(order):
        weights[nid] = SEED_W_HI if n <= 1 else SEED_W_HI - (SEED_W_HI - SEED_W_LO) * (i / (n - 1))
    kind = "fts+dense" if dense_leg else "fts"
    return order, weights, kind


def _lesson_seeds(store: Any, question: str | None,
                  semantic: Callable[[str], list[dict[str, Any]]] | None) -> list[str]:
    """Item 3: lessons get their OWN seed leg (lesson-only FTS + the dense hits that are lessons, RRF),
    so a cross-epic lesson is found even when the epic's decisions fill every main seed slot."""
    if not question:
        return []
    legs: list[list[str]] = []
    try:
        legs.append(_leg_ranked(store, store.fts_search(question, types={"lesson"}, limit=50), None,
                                2 * MAX_LESSONS, types=("lesson",)))
    except Exception:
        pass
    if semantic is not None:
        try:
            legs.append(_leg_ranked(store, semantic(question), None, 2 * MAX_LESSONS, types=("lesson",)))
        except Exception:
            pass
    fused: dict[str, float] = {}
    for leg in legs:
        for rank, nid in enumerate(leg, start=1):
            fused[nid] = fused.get(nid, 0.0) + 1.0 / (60 + rank)
    return sorted(fused, key=lambda nid: (-fused[nid], nid))[:2 * MAX_LESSONS]


def _in_scope(store: Any, rec: Any, rec_type: str, target_epic: str | None) -> bool:
    if rec_type == "lesson":
        return True  # cross-epic by design
    if target_epic is None:
        return False  # an unresolved scope isolates decisions/claims to NOTHING, never everything
    return _record_epic(store, rec, rec_type) == target_epic


def _always_include(store: Any, target_epic: str | None) -> set[str]:
    """The never-cut set (design §4.2 step 1): live binding decisions in scope, PLUS any live
    decision that is an endpoint of a must_follow edge in scope (a must-follow item, even if the
    decision itself is not flagged binding)."""
    if target_epic is None:
        return set()  # nothing is mandatory outside a resolved scope
    ids: set[str] = set()
    for d in store.query("decision", {"status": "live"}, limit=100000):
        if d.binding and _epic_id_of(store, d.scope or "") == target_epic:
            ids.add(d.id)
    for lk in store.query("kglink", {"kind": "must_follow"}, limit=100000):
        for nid in (lk.from_id, lk.to_id):
            found = _find_record(store, nid)
            if found and found[0] == "decision" and not _dropped(found[1], "decision") \
                    and _in_scope(store, found[1], "decision", target_epic):
                ids.add(nid)
    return ids


def _render_line(rtype: str, rec: Any, *, confirmed: bool, fresh: bool, binding: bool,
                 text_only: bool = False) -> str:
    tags = [rtype.upper()]
    if binding:
        tags.append("binding")
    if not confirmed:
        tags.append("unconfirmed")
    if not fresh:
        tags.append("STALE")
    head = " ".join(tags)
    when = ""
    if rtype in ("decision", "claim"):  # show WHEN it was decided (source date), not when backfilled
        when = f" (decided {_effective_date(rec).date().isoformat()})"
    if rtype == "claim":
        head += f" {rec.basis}"  # measured | ruled | assumption — how the claim is known
    elif rtype == "lesson":
        head += f" [{rec.domain}/{rec.topic}]"
    line = f"- {head}: {rec.text}{when}  <{rec.id}>"
    detail = getattr(rec, "detail", "") or ""
    if detail and not text_only:  # R2-5: the Always-applies section renders text only
        line += f"\n    why: {detail}"
    evidence = getattr(rec, "evidence", None) or []
    if rtype in ("claim", "lesson") and evidence and not text_only:
        line += f"\n    evidence: {', '.join(evidence[:8])}"
    return line


def _co_source_links(store: Any, target_epic: str | None) -> dict[str, set[str]]:
    """Item 3: live decision<->claim pairs in the epic that share a source id, or where the claim cites
    the decision (or its source) as evidence. Undirected, record ids only."""
    if target_epic is None:
        return {}
    by_source: dict[str, set[str]] = {}
    claims: list[Any] = []
    dec_ids: set[str] = set()
    for rtype in ("decision", "claim"):
        for r in store.query(rtype, limit=100000):
            if _dropped(r, rtype) or _epic_id_of(store, getattr(r, "scope", "") or "") != target_epic:
                continue
            if rtype == "claim":
                claims.append(r)
            else:
                dec_ids.add(r.id)
            if getattr(r, "source", None):
                by_source.setdefault(r.source, set()).add(r.id)
    out: dict[str, set[str]] = {}

    def _pair(a: str, b: str) -> None:
        if a != b:
            out.setdefault(a, set()).add(b)
            out.setdefault(b, set()).add(a)

    for ids in by_source.values():
        decs = [i for i in ids if i in dec_ids]
        for c in (i for i in ids if i not in dec_ids):
            for d in decs:
                _pair(c, d)
    for c in claims:
        for ev in c.evidence or []:
            if ev in dec_ids:
                _pair(c.id, ev)
            for d in by_source.get(ev, ()):
                if d in dec_ids:
                    _pair(c.id, d)
    return out


def _type_weight(rec: Any, rtype: str) -> float:
    if rtype == "claim" and not _confirmed(rec, rtype):
        return TYPE_WEIGHT["claim_unconfirmed"]
    return TYPE_WEIGHT.get(rtype, 1.0)


def _live_record_count(store: Any, target_epic: str | None) -> int:
    """E1: count of non-dropped decision+claim records in the epic — the size the seed net scales to."""
    if target_epic is None:
        return 0
    n = 0
    for rtype in ("decision", "claim"):
        for r in store.query(rtype, limit=100000):
            if not _dropped(r, rtype) and _epic_id_of(store, getattr(r, "scope", "") or "") == target_epic:
                n += 1
    return n


_DEC_ID = re.compile(r"\bdec-[0-9a-f]{10}\b")


def binding_orphans(store: Any) -> list[dict[str, Any]]:
    """Audit (m-0cccdead3e): every replaced or withdrawn BINDING decision must have a live binding
    successor, found forward along replaces links or named (dec-…) in its withdraw reason. Returns the
    ones that do not, with the live successors they do have, so a re-curation that demoted a
    must-follow rule is caught instead of silently dropping it from "Always applies"."""
    decs = {d.id: d for d in store.query("decision", limit=100000)}
    replaced_by: dict[str, list[str]] = {}
    for d in decs.values():
        for rid in getattr(d, "replaces", None) or []:
            replaced_by.setdefault(rid, []).append(d.id)

    def _status(d: Any) -> str:
        return getattr(getattr(d, "status", ""), "value", getattr(d, "status", ""))

    out = []
    for d in decs.values():
        if not getattr(d, "binding", False) or _status(d) not in ("replaced", "withdrawn"):
            continue
        frontier = list(replaced_by.get(d.id, [])) + _DEC_ID.findall(getattr(d, "withdrawn_reason", "") or "")
        seen: set[str] = {d.id}
        live: list[str] = []
        while frontier:
            sid = frontier.pop()
            if sid in seen or sid not in decs:
                continue
            seen.add(sid)
            s = decs[sid]
            if _status(s) == "live":
                live.append(sid)
            else:  # a successor that was itself replaced/withdrawn: keep walking forward
                frontier += replaced_by.get(sid, []) + _DEC_ID.findall(getattr(s, "withdrawn_reason", "") or "")
        if not any(getattr(decs[s], "binding", False) for s in live):
            out.append({"id": d.id, "status": _status(d), "scope": getattr(d, "scope", None),
                        "text": d.text, "live_successors": sorted(live)})
    return sorted(out, key=lambda o: o["id"])


def lookup(store: Any, scope: str, *, question: str | None = None, id: str | None = None,
           path: str | None = None, semantic: Callable[[str], list[dict[str, Any]]] | None = None,
           stale_paths: Callable[[Any, str], bool] | None = None,
           ref_now: datetime | None = None,
           embed_status: dict[str, Any] | None = None,
           source_search: Callable[[str], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """Deterministic retrieval (design §4.2). Returns {records, body, receipt}.

    scope: epic|ticket id — the isolation boundary. question|id|path: the starting point.
    semantic(question)->hits, stale_paths(rec,type)->bool are injected by board.lookup.
    """
    ref = ref_now or now()
    target_epic = _epic_id_of(store, scope)
    live_count = _live_record_count(store, target_epic)  # E1: seed net scales with epic size
    per_leg = _seed_per_leg(live_count)
    seeds, seed_weights, seed_kind = _seed(store, question=question, node_id=id, path=path,
                                           target_epic=target_epic, semantic=semantic, per_leg=per_leg)
    # R2-6: _seed labels "fts+dense" when the dense leg actually returned seeds; also say so when the
    # dense matrix was active but returned nothing here (embeddings were consulted), so the receipt
    # honestly shows which backend served — a RAM/absent-model fallback stays "fts" with the reason.
    if seed_kind == "fts" and embed_status and embed_status.get("embeddings_active"):
        seed_kind = "fts+dense"

    # 2-hop scored BFS over kglinks; best weight per node (design §4.2 step 3/5). A ticket/epic/
    # message/doc HUB reached mid-traversal does not re-broadcast to its siblings (R2-5/defect-2):
    # otherwise every decision is 2 hops from every other via the shared epic `decides` hub, and
    # "ranks for the question" means nothing. A ticket SEED still reaches its own decisions.
    adj = _adjacency(store)
    seed_set = set(seeds)
    # D2: seeds start at their retrieval-rank weight (not a flat 1.0), so the ranked scores reflect how
    # well each seed matched the question; BFS neighbours still decay from there by link weight.
    best: dict[str, float] = {s: seed_weights.get(s, SEED_W_HI) for s in seeds}
    frontier: dict[str, float] = dict(best)
    for _hop in range(MAX_HOPS):
        nxt: dict[str, float] = {}
        for nid, w in frontier.items():
            if nid not in seed_set and _find_record(store, nid) is None:
                continue  # a non-record hub only bridges when it is the explicit starting point
            for other, kind in adj.get(nid, ()):
                ow = w * LINK_WEIGHT.get(kind, DEFAULT_WEIGHT)
                if ow > best.get(other, 0.0):
                    best[other] = ow
                    nxt[other] = ow
        frontier = nxt
    # Item 3: one co-source hop from each seed — a matched decision brings the claims recorded from
    # its source message (the measured fact behind the ruling), and a matched claim its decision.
    co_source = _co_source_links(store, target_epic) if seeds else {}
    co_source_hits: set[str] = set()
    for s in seeds:
        for other in co_source.get(s, ()):
            ow = best.get(s, SEED_W_HI) * CO_SOURCE_WEIGHT
            if ow > best.get(other, 0.0):
                best[other] = ow
                co_source_hits.add(other)

    always_ids = _always_include(store, target_epic)

    def _mk(nid: str, rtype: str, rec: Any, weight: float) -> tuple[float, dict[str, Any]]:
        confirmed = _confirmed(rec, rtype)
        fresh = not (stale_paths(rec, rtype) if stale_paths else False)
        history = _history_chain(store, rec) if rtype == "decision" else []
        score = (weight * _freshness(_effective_date(rec), ref) * _usefulness(rec, rtype)
                 * _type_weight(rec, rtype))
        entry = {"id": rec.id, "type": rtype, "text": rec.text,
                 "detail": getattr(rec, "detail", "") or "",
                 "status": getattr(rec, "status", "live"),
                 "confirmed": confirmed, "fresh": fresh, "binding": nid in always_ids,
                 "score": round(score, 6)}
        if getattr(rec, "source", None):
            entry["source"] = rec.source  # the message/doc it came from, so a reader can cite it
        if history:
            entry["history"] = history
        return score, entry

    # ranked = records the QUESTION reached (seeds + 2-hop). A binding record shows its detail only
    # when it also ranks here (R2-5). always = binding/must-follow set, rendered text-only up front.
    ranked: list[tuple[float, str, str, Any, dict[str, Any]]] = []
    for nid in best:
        found = _find_record(store, nid)
        if not found:
            continue
        rtype, rec = found
        if _dropped(rec, rtype) or not _in_scope(store, rec, rtype, target_epic):
            continue
        sc, entry = _mk(nid, rtype, rec, best.get(nid, DEFAULT_WEIGHT))
        entry["provenance"] = "seed" if nid in seed_set else "walk"  # E2: seed = a lexical/dense match
        ranked.append((sc, nid, rtype, rec, entry))
    # E2 (steer m-a006bfe2a5): a walk-only record (reached by graph links, with NO lexical or dense
    # match to the question) must never outrank a seed (matched) record — a high-degree hub was winning
    # on graph weight alone. Tier seeds above walks, each tier ordered by score.
    ranked.sort(key=lambda x: (x[1] not in seed_set, -x[0], x[1]))
    # Item 3: lessons leave the ranked section for their own tail (below), so a cross-epic lesson
    # neither takes an epic record's slot nor is lost under the byte cap.
    lesson_cands = [t for t in ranked if t[2] == "lesson"]
    ranked = [t for t in ranked if t[2] != "lesson"]
    have_lessons = {t[1] for t in lesson_cands}
    lesson_seed_ids = _lesson_seeds(store, question, semantic) if not id else []
    for i, lid in enumerate(lesson_seed_ids):
        les = store.get("lesson", lid)
        if les is None or lid in have_lessons or _dropped(les, "lesson"):
            continue
        w = SEED_W_HI - (SEED_W_HI - SEED_W_LO) * (i / max(1, len(lesson_seed_ids) - 1))
        sc, entry = _mk(lid, "lesson", les, w)
        entry["provenance"] = "seed"
        lesson_cands.append((sc, lid, "lesson", les, entry))
    lesson_cands.sort(key=lambda x: (x[4].get("provenance") != "seed", -x[0], x[1]))

    # C4 noise floor: keep only ranked records at >= RANKED_FLOOR_FRAC of the top score, plus any
    # weak record linked by replaces/part_of to a kept (strong) one — so a live decision's chain and
    # a claim tied to a kept record's ticket are not dropped. Below-floor records are noise, not budget.
    floor_dropped: list[str] = []
    ranked_allowed_ids: set[str] = {rec.id for _, _, _, rec, _ in ranked}
    if ranked and RANKED_FLOOR_FRAC > 0:
        top_score = ranked[0][0]
        floor = RANKED_FLOOR_FRAC * top_score if top_score > 0 else 0.0
        if floor > 0:
            strong_ids = {rec.id for sc, _, _, rec, _ in ranked if sc >= floor}
            rescue_pairs: set[tuple[str, str]] = set()
            for lk in store.query("kglink", limit=100000):
                if lk.kind in RESCUE_KINDS:
                    rescue_pairs.add((lk.from_id, lk.to_id))
                    rescue_pairs.add((lk.to_id, lk.from_id))
            allowed: set[str] = set(strong_ids)
            for sc, _, _, rec, _ in ranked:
                if rec.id in allowed:
                    continue
                if any((rec.id, s) in rescue_pairs for s in strong_ids):
                    allowed.add(rec.id)
                else:
                    floor_dropped.append(rec.id)
            ranked_allowed_ids = allowed

    binding_cands: list[tuple[float, str, Any, dict[str, Any]]] = []
    for nid in always_ids:
        found = _find_record(store, nid)
        if not found:
            continue
        rtype, rec = found
        if _dropped(rec, rtype) or not _in_scope(store, rec, rtype, target_epic):
            continue
        w = best.get(nid, LINK_WEIGHT["must_follow"])
        sc, entry = _mk(nid, rtype, rec, w)
        binding_cands.append((sc, nid, rec, entry))
    binding_cands.sort(key=lambda x: (-x[0], x[1]))

    records: list[dict[str, Any]] = []
    counts = {"confirmed": 0, "unconfirmed": 0, "fresh": 0, "stale": 0}

    def _count(entry: dict[str, Any]) -> None:
        counts["confirmed" if entry["confirmed"] else "unconfirmed"] += 1
        counts["fresh" if entry["fresh"] else "stale"] += 1

    # --- Section A "Always applies": binding, TEXT ONLY, at most ALWAYS_MAX_BYTES of the budget.
    # Mandatory overflow trims the lowest-score binding text and says so in the receipt (R2-5).
    always_lines: list[str] = []
    always_bytes = 0
    binding_trimmed: list[str] = []
    for sc, nid, rec, _full in binding_cands:
        stub = {"id": rec.id, "type": "decision", "text": rec.text, "binding": True,
                "section": "always", "confirmed": _full["confirmed"], "fresh": _full["fresh"],
                "score": _full["score"]}
        bsize = len(_json.dumps(stub, ensure_ascii=False).encode("utf-8"))
        if always_bytes + bsize > ALWAYS_MAX_BYTES:
            binding_trimmed.append(rec.id)
            continue
        records.append(stub)
        always_lines.append(_render_line("decision", rec, confirmed=_full["confirmed"],
                                          fresh=_full["fresh"], binding=True, text_only=True))
        always_bytes += bsize
        _count(stub)

    # --- Section D "Lessons from elsewhere" (item 3), sized FIRST so its reserve is kept inside the cap:
    # lessons the question matched (seeded or walked), then lessons filed under a domain of a kept
    # decision ("found across epics by domain/topic"), at most MAX_LESSONS / LESSON_MAX_BYTES.
    kept_domains: set[str] = set()
    for _sc, _nid, rtype, rec, _e in ranked:
        if rtype == "decision" and rec.id in ranked_allowed_ids:
            kept_domains.update(getattr(rec, "domains", None) or [])
    if kept_domains:
        have = {t[1] for t in lesson_cands}
        extra = []
        for les in store.query("lesson", {"status": "live"}, limit=100000):
            if les.id in have or les.domain not in kept_domains:
                continue
            sc, entry = _mk(les.id, "lesson", les, DEFAULT_WEIGHT)
            entry["provenance"] = "domain"
            extra.append((sc, les.id, "lesson", les, entry))
        extra.sort(key=lambda x: (-x[0], x[1]))
        lesson_cands = lesson_cands + extra
    lesson_lines: list[str] = []
    lesson_bytes = 0
    lesson_entries: list[dict[str, Any]] = []
    for _sc, _nid, _rt, rec, entry in lesson_cands:
        if len(lesson_lines) >= MAX_LESSONS:
            break
        entry = {**entry, "section": "lesson", "evidence": list(rec.evidence or [])[:8],
                 "domain": rec.domain, "topic": rec.topic}
        bsize = len(_json.dumps(entry, ensure_ascii=False).encode("utf-8"))
        if lesson_bytes + bsize > LESSON_MAX_BYTES or always_bytes + lesson_bytes + bsize > MAX_BYTES:
            continue
        lesson_entries.append(entry)
        lesson_lines.append(_render_line("lesson", rec, confirmed=entry["confirmed"], fresh=entry["fresh"],
                                         binding=False))
        lesson_bytes += bsize

    # --- Section B "For your question": ranked records, full detail + inline history, up to MAX_BYTES total.
    ranked_lines: list[str] = []
    used_bytes = always_bytes + lesson_bytes
    cut_by_type: dict[str, int] = {}
    cut_ids: dict[str, list[str]] = {}
    for sc, nid, rtype, rec, entry in ranked:
        if rec.id not in ranked_allowed_ids:
            continue  # C4: below the noise floor and not rescued by a replaces/part_of link
        entry = {**entry, "section": "ranked"}
        bsize = len(_json.dumps(entry, ensure_ascii=False).encode("utf-8"))
        if used_bytes + bsize > MAX_BYTES:  # E1: the ranked section runs to the byte cap, not a count
            cut_by_type[rtype] = cut_by_type.get(rtype, 0) + 1
            cut_ids.setdefault(rtype, []).append(rec.id)
            continue
        records.append(entry)
        line = _render_line(rtype, rec, confirmed=entry["confirmed"], fresh=entry["fresh"],
                            binding=entry["binding"])
        for h in entry.get("history", []):  # R2-1: the superseded chain, inline, newest-first
            line += f"\n    earlier: {h['text']} (replaced {h['date']})"
        ranked_lines.append(line)
        used_bytes += bsize
        _count(entry)

    for entry in lesson_entries:  # Section D records follow the ranked ones in `records`
        records.append(entry)
        _count(entry)

    # --- Section C "Unconfirmed source excerpts" (R2-7): only when the question reached too few
    # strong records, quote the epic's own messages/doc paragraphs so a not-yet-curated answer is
    # still visible. Counts inside the 8,000-byte budget.
    excerpt_lines: list[str] = []
    strong = sum(1 for tup in ranked if best.get(tup[1], 0.0) >= RELEVANCE_FLOOR)
    if strong < MIN_RELEVANT:
        for ex in _source_excerpts(store, target_epic, question, source_search):
            e = {**ex, "section": "excerpt", "confirmed": False, "binding": False}
            bsize = len(_json.dumps(e, ensure_ascii=False).encode("utf-8"))
            if used_bytes + bsize > MAX_BYTES:
                break
            records.append(e)
            excerpt_lines.append(f"- SOURCE {ex['type']} <{ex['id']}> {ex['author']} {ex['date']}: {ex['text']}")
            used_bytes += bsize

    body_parts = []
    if always_lines:
        body_parts.append("Always applies\n" + "\n".join(always_lines))
    body_parts.append("For your question\n" + ("\n".join(ranked_lines) if ranked_lines else "(nothing scored)"))
    if lesson_lines:
        body_parts.append("Lessons from elsewhere\n" + "\n".join(lesson_lines))
    if excerpt_lines:
        body_parts.append("Unconfirmed source excerpts\n" + "\n".join(excerpt_lines))
    body = "\n\n".join(body_parts)

    receipt = {
        "scope": scope, "epic": target_epic, "seed_kind": seed_kind, "seeds": seeds,
        "returned": len(records), "ranked_returned": len(ranked_lines),
        "source_excerpts": len(excerpt_lines), "strong_records": strong,
        "always_applies": len(always_lines), "always_bytes": always_bytes,
        "binding": sum(1 for r in records if r.get("binding")),
        "binding_trimmed": binding_trimmed, "always_cap": ALWAYS_MAX_BYTES,
        "bytes": used_bytes, "cut_by_type": cut_by_type,
        "cut_ids": {t: ids[:20] for t, ids in cut_ids.items()},
        "fetch": "read a cut record by id via record read / lookup(id=<id>)" if cut_ids else "",
        "cap": {"records": MAX_RECORDS, "bytes": MAX_BYTES},
        # mandatory overflow = the binding must-follow set could not fit its byte reserve (R2-5)
        "mandatory_overflow": bool(binding_trimmed),
        # R2-6: which seeding backend served this lookup (embeddings vs FTS-only + why)
        "embeddings": embed_status or {"embedder": "none", "reason": "no semantic index wired"},
        # E1: the adaptive per-leg seed count and the epic size it scaled to; E2: seed vs walk provenance
        "seed_top": per_leg, "seed_top_base": SEED_TOP, "seed_union_cap": 2 * per_leg,
        "live_records": live_count,
        "ranked_seed": sum(1 for r in records if r.get("provenance") == "seed"),
        "ranked_walk": sum(1 for r in records if r.get("provenance") == "walk"),
        # C4 noise floor: how many ranked records were dropped for scoring below the floor, and the floor
        "floor_dropped": len(floor_dropped), "floor_dropped_ids": floor_dropped[:20],
        # item 3: the lessons tail and how many ranked records arrived by a co-source hop
        "lessons": len(lesson_lines), "lesson_bytes": lesson_bytes,
        "co_source_pulled": sum(1 for r in records if r.get("section") == "ranked"
                                and r["id"] not in seed_set and r["id"] in co_source_hits),
        "ranked_floor_frac": RANKED_FLOOR_FRAC,
        **counts,
    }
    return {"records": records, "body": body, "receipt": receipt}
