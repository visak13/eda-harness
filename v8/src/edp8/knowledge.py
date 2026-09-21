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
import re
from datetime import datetime
from typing import Any, Callable

from .schemas import now

RECORD_TYPES = ("decision", "claim", "lesson")
MAX_RECORDS = 40
MAX_BYTES = 8000
MAX_HOPS = 2
SEED_TOP = 5

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
        return st == "refuted"
    if rec_type == "lesson":
        return st == "retired"
    return False


def _freshness(created_at: datetime, ref: datetime) -> float:
    age_days = max(0.0, (ref - created_at).total_seconds() / 86400.0)
    return 1.0 / (1.0 + age_days / 30.0)


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


def _seed(store: Any, *, question: str | None, node_id: str | None, path: str | None,
          target_epic: str | None, semantic: Callable[[str], list[dict[str, Any]]] | None) -> tuple[list[str], str]:
    """Seed nodes and the seed kind. Explicit id/path win; else FTS ∪ semantic, top SEED_TOP."""
    if node_id:
        rec = _find_record(store, node_id)
        if rec:
            # an explicit record id seeds only if it is in scope (never bridge to a foreign epic)
            if _in_scope(store, rec[1], rec[0], target_epic):
                return [node_id], "id"
            return [], "id_out_of_scope"
        if store.get("ticket", node_id) or store.get("doc", node_id):
            return [node_id], "id"
    if path:
        # a path seeds through kglink endpoints that name it (touches edges), else FTS on the string.
        hits = [lk.from_id for lk in store.query("kglink", {"to_id": path}, limit=50)]
        if hits:
            return hits[:SEED_TOP], "path"
        question = question or path
    if not question:
        return [], "none"
    fused: dict[str, float] = {}
    rrf_k = 60
    # over-fetch well past SEED_TOP so in-scope hits are never crowded out by foreign matches
    # before the scope filter runs below (design §4.2: seeds are limited to the agent's epic).
    try:
        for rank, h in enumerate(store.fts_search(question, types=set(RECORD_TYPES), limit=200), start=1):
            fused[h["id"]] = fused.get(h["id"], 0.0) + 1.0 / (rrf_k + rank)
    except Exception:
        pass
    if semantic is not None:
        try:
            for rank, h in enumerate(semantic(question), start=1):
                if h.get("type") in RECORD_TYPES:
                    fused[h["id"]] = fused.get(h["id"], 0.0) + 1.0 / (rrf_k + rank)
        except Exception:
            pass
    ranked = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))
    seeds: list[str] = []
    for nid, _ in ranked:
        found = _find_record(store, nid)
        if not found:
            continue
        rtype, rec = found
        if _in_scope(store, rec, rtype, target_epic):
            seeds.append(nid)
        if len(seeds) >= SEED_TOP:
            break
    return seeds, "fts"


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


def _render_line(rtype: str, rec: Any, *, confirmed: bool, fresh: bool, binding: bool) -> str:
    tags = [rtype.upper()]
    if binding:
        tags.append("binding")
    if not confirmed:
        tags.append("unconfirmed")
    if not fresh:
        tags.append("STALE")
    head = " ".join(tags)
    line = f"- {head}: {rec.text}  <{rec.id}>"
    detail = getattr(rec, "detail", "") or ""
    if detail:
        line += f"\n    why: {detail}"
    return line


def lookup(store: Any, scope: str, *, question: str | None = None, id: str | None = None,
           path: str | None = None, semantic: Callable[[str], list[dict[str, Any]]] | None = None,
           stale_paths: Callable[[Any, str], bool] | None = None,
           ref_now: datetime | None = None) -> dict[str, Any]:
    """Deterministic retrieval (design §4.2). Returns {records, body, receipt}.

    scope: epic|ticket id — the isolation boundary. question|id|path: the starting point.
    semantic(question)->hits, stale_paths(rec,type)->bool are injected by board.lookup.
    """
    ref = ref_now or now()
    target_epic = _epic_id_of(store, scope)
    seeds, seed_kind = _seed(store, question=question, node_id=id, path=path,
                             target_epic=target_epic, semantic=semantic)

    # 2-hop scored BFS over kglinks; best weight per node (design §4.2 step 3/5).
    adj = _adjacency(store)
    best: dict[str, float] = {s: 1.0 for s in seeds}
    frontier: dict[str, float] = {s: 1.0 for s in seeds}
    for _hop in range(MAX_HOPS):
        nxt: dict[str, float] = {}
        for nid, w in frontier.items():
            for other, kind in adj.get(nid, ()):  # noqa: E501
                ow = w * LINK_WEIGHT.get(kind, DEFAULT_WEIGHT)
                if ow > best.get(other, 0.0):
                    best[other] = ow
                    nxt[other] = ow
        frontier = nxt

    always_ids = _always_include(store, target_epic)

    # collect candidate records: seeds/neighbours that are decision/claim/lesson, in scope, not dropped.
    scored: list[tuple[float, str, str, Any]] = []
    seen: set[str] = set()
    for nid in list(best) + list(always_ids):
        if nid in seen:
            continue
        seen.add(nid)
        found = _find_record(store, nid)
        if not found:
            continue
        rtype, rec = found
        if _dropped(rec, rtype) or not _in_scope(store, rec, rtype, target_epic):
            continue
        weight = best.get(nid, LINK_WEIGHT["must_follow"] if nid in always_ids else DEFAULT_WEIGHT)
        score = weight * _freshness(rec.created_at, ref) * _usefulness(rec, rtype)
        scored.append((score, nid, rtype, rec))

    # always-include first (never cut), then by score desc, id tie-break (deterministic).
    scored.sort(key=lambda x: (x[1] not in always_ids, -x[0], x[1]))

    records: list[dict[str, Any]] = []
    lines: list[str] = []
    used_bytes, cut_by_type, cut_ids = 0, {}, {}
    counts = {"confirmed": 0, "unconfirmed": 0, "fresh": 0, "stale": 0}
    for score, nid, rtype, rec in scored:
        binding = nid in always_ids
        confirmed = _confirmed(rec, rtype)
        fresh = not (stale_paths(rec, rtype) if stale_paths else False)
        entry = {"id": rec.id, "type": rtype, "text": rec.text,
                 "detail": getattr(rec, "detail", "") or "",
                 "status": getattr(rec, "status", "live"),
                 "confirmed": confirmed, "fresh": fresh, "binding": binding,
                 "score": round(score, 6)}
        # budget against the ACTUAL returned payload (the serialized record), not just a render,
        # so the ≤8,000-byte cap is a real reading budget (design §4.2 step 7).
        bsize = len(_json.dumps(entry, ensure_ascii=False).encode("utf-8"))
        if not binding and (len(records) >= MAX_RECORDS or used_bytes + bsize > MAX_BYTES):
            cut_by_type[rtype] = cut_by_type.get(rtype, 0) + 1
            cut_ids.setdefault(rtype, []).append(rec.id)
            continue
        records.append(entry)
        lines.append(_render_line(rtype, rec, confirmed=confirmed, fresh=fresh, binding=binding))
        used_bytes += bsize
        counts["confirmed" if confirmed else "unconfirmed"] += 1
        counts["fresh" if fresh else "stale"] += 1

    receipt = {
        "scope": scope, "epic": target_epic, "seed_kind": seed_kind, "seeds": seeds,
        "returned": len(records), "binding": sum(1 for r in records if r["binding"]),
        "bytes": used_bytes, "cut_by_type": cut_by_type,
        # step 8: name what was cut so the reader can fetch it (ids capped so the receipt stays small)
        "cut_ids": {t: ids[:20] for t, ids in cut_ids.items()},
        "fetch": "read a cut record by id via record read / lookup(id=<id>)" if cut_ids else "",
        "cap": {"records": MAX_RECORDS, "bytes": MAX_BYTES},
        "mandatory_overflow": used_bytes > MAX_BYTES or len(records) > MAX_RECORDS,
        **counts,
    }
    return {"records": records, "body": "\n".join(lines), "receipt": receipt}
