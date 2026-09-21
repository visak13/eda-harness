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
ALWAYS_MAX_BYTES = 2000  # R2-5: the "Always applies" (binding, text-only) section's byte reserve
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


def _as_date(dt: Any) -> str:
    """The date portion of a created_at (datetime or ISO string), for the 'replaced <date>' tag."""
    if isinstance(dt, datetime):
        return dt.date().isoformat()
    return str(dt)[:10]


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
        out.append({"id": old.id, "text": old.text, "date": _as_date(rec.created_at)})
        out.extend(_history_chain(store, old, _seen))
    return out


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
    line = f"- {head}: {rec.text}  <{rec.id}>"
    detail = getattr(rec, "detail", "") or ""
    if detail and not text_only:  # R2-5: the Always-applies section renders text only
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

    # 2-hop scored BFS over kglinks; best weight per node (design §4.2 step 3/5). A ticket/epic/
    # message/doc HUB reached mid-traversal does not re-broadcast to its siblings (R2-5/defect-2):
    # otherwise every decision is 2 hops from every other via the shared epic `decides` hub, and
    # "ranks for the question" means nothing. A ticket SEED still reaches its own decisions.
    adj = _adjacency(store)
    seed_set = set(seeds)
    best: dict[str, float] = {s: 1.0 for s in seeds}
    frontier: dict[str, float] = {s: 1.0 for s in seeds}
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

    always_ids = _always_include(store, target_epic)

    def _mk(nid: str, rtype: str, rec: Any, weight: float) -> tuple[float, dict[str, Any]]:
        confirmed = _confirmed(rec, rtype)
        fresh = not (stale_paths(rec, rtype) if stale_paths else False)
        history = _history_chain(store, rec) if rtype == "decision" else []
        score = weight * _freshness(rec.created_at, ref) * _usefulness(rec, rtype)
        entry = {"id": rec.id, "type": rtype, "text": rec.text,
                 "detail": getattr(rec, "detail", "") or "",
                 "status": getattr(rec, "status", "live"),
                 "confirmed": confirmed, "fresh": fresh, "binding": nid in always_ids,
                 "score": round(score, 6)}
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
        ranked.append((sc, nid, rtype, rec, entry))
    ranked.sort(key=lambda x: (-x[0], x[1]))

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

    # --- Section B "For your question": ranked records, full detail + inline history, up to MAX_BYTES total.
    ranked_lines: list[str] = []
    used_bytes = always_bytes
    cut_by_type: dict[str, int] = {}
    cut_ids: dict[str, list[str]] = {}
    for sc, nid, rtype, rec, entry in ranked:
        entry = {**entry, "section": "ranked"}
        bsize = len(_json.dumps(entry, ensure_ascii=False).encode("utf-8"))
        if len(records) >= MAX_RECORDS or used_bytes + bsize > MAX_BYTES:
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

    body_parts = []
    if always_lines:
        body_parts.append("Always applies\n" + "\n".join(always_lines))
    body_parts.append("For your question\n" + ("\n".join(ranked_lines) if ranked_lines else "(nothing scored)"))
    body = "\n\n".join(body_parts)

    receipt = {
        "scope": scope, "epic": target_epic, "seed_kind": seed_kind, "seeds": seeds,
        "returned": len(records), "ranked_returned": len(ranked_lines),
        "always_applies": len(always_lines), "always_bytes": always_bytes,
        "binding": sum(1 for r in records if r.get("binding")),
        "binding_trimmed": binding_trimmed, "always_cap": ALWAYS_MAX_BYTES,
        "bytes": used_bytes, "cut_by_type": cut_by_type,
        "cut_ids": {t: ids[:20] for t, ids in cut_ids.items()},
        "fetch": "read a cut record by id via record read / lookup(id=<id>)" if cut_ids else "",
        "cap": {"records": MAX_RECORDS, "bytes": MAX_BYTES},
        # mandatory overflow = the binding must-follow set could not fit its byte reserve (R2-5)
        "mandatory_overflow": bool(binding_trimmed),
        **counts,
    }
    return {"records": records, "body": body, "receipt": receipt}
