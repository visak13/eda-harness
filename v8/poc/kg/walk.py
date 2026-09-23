"""walk(start): deterministic retrieval over kg.db.

start is a node id, a ticket id, a module path, or free text (FTS5/BM25 seed).
Returns a MANDATORY set (must_follow targets + LIVE decisions on the start's own
path start->design_part->problem) that is ALWAYS included, outside the cut, plus
a scored remainder filled up to a hard cap (40 nodes, 8 KB total). Replaced nodes
are kept in the store but never returned. The receipt names what was cut by type.

Run: python poc/kg/walk.py "<start>"
"""
from __future__ import annotations

import math
import re
import sys

import db

MAX_NODES = 40
MAX_BYTES = 8192
MAX_HOPS = 2
DETAIL_LIMIT = 8  # detail=True: surface source excerpts on the top-N fact nodes only

# edge-type weights: how much a hop across this relation carries relevance.
# came_from/replaces are never traversed (source rows aren't nodes; replaced
# nodes are excluded).
REL_WEIGHT = {
    "must_follow": 1.0,
    "decides": 0.9,
    "verifies": 0.85,
    "part_of": 0.8,
    "implements": 0.8,
    "proves": 0.7,
    "learned_from": 0.65,
    "touches": 0.6,
}
UP_RELS = ("part_of", "implements")  # start -> design_part -> problem


def _fts_seed(conn, text, k=5):
    q = " OR ".join(re.findall(r"[A-Za-z0-9_]+", text)) or text
    try:
        rows = conn.execute(
            "SELECT n.id FROM node_fts f JOIN node n ON n.rowid=f.rowid "
            "WHERE node_fts MATCH ? AND n.status='live' "
            "ORDER BY bm25(node_fts), n.id LIMIT ?", (q, k)).fetchall()  # id tie-break
    except Exception:
        rows = []
    return [r["id"] for r in rows]


def resolve_seeds(conn, start):
    def exists(nid):
        return conn.execute("SELECT 1 FROM node WHERE id=?", (nid,)).fetchone() is not None
    for cand in (start, f"ticket:{start}", f"module:{start}", f"problem:{start}"):
        if exists(cand):
            return [cand], ("id" if cand == start else cand.split(":", 1)[0])
    return _fts_seed(conn, start), "fts"


def _neighbors(conn, nid):
    """Undirected node<->node edges, excluding came_from (sources) and any edge
    that lands on a replaced node. Yields (other_id, rel)."""
    out = []
    for r in conn.execute(
        "SELECT e.to_id AS o, e.rel AS rel, n.status AS st FROM edge e "
        "JOIN node n ON n.id=e.to_id WHERE e.from_id=? AND e.rel!='came_from'", (nid,)):
        if r["st"] != "replaced":
            out.append((r["o"], r["rel"]))
    for r in conn.execute(
        "SELECT e.from_id AS o, e.rel AS rel, n.status AS st FROM edge e "
        "JOIN node n ON n.id=e.from_id WHERE e.to_id=? AND e.rel NOT IN ('came_from','replaces')", (nid,)):
        if r["st"] != "replaced":
            out.append((r["o"], r["rel"]))
    return out


def _path_to_problem(conn, seed):
    """Follow part_of/implements up from seed; collect design_part + problem."""
    path, frontier, seen = [], [seed], {seed}
    for _ in range(4):
        nxt = []
        for nid in frontier:
            for r in conn.execute(
                "SELECT to_id, rel FROM edge WHERE from_id=? AND rel IN ('part_of','implements')", (nid,)):
                o = r["to_id"]
                if o not in seen:
                    seen.add(o); path.append(o); nxt.append(o)
        frontier = nxt
        if not frontier:
            break
    return path


def _mandatory(conn, seeds):
    """The binding constraints for the START: must_follow targets, the LIVE
    decisions on the start node ITSELF, and the light path skeleton
    (start -> design_part -> problem) as context.

    Deliberately NOT every live decision on the shared problem node: in this
    epic hundreds of owner rulings were posted on the epic thread, so returning
    all of them unconditionally would blow the budget. Epic-wide decisions stay
    retrievable through the scored, capped remainder (finding, not a bug)."""
    skeleton = set()
    for s in seeds:
        skeleton.add(s)
        skeleton.update(_path_to_problem(conn, s))  # design_part + problem
    ids = set(skeleton)
    # must_follow targets reachable from the seeds and their path
    for nid in skeleton:
        for r in conn.execute("SELECT to_id FROM edge WHERE from_id=? AND rel='must_follow'", (nid,)):
            ids.add(r["to_id"])
    # LIVE decisions that decide a SEED node itself (its own thread), not the
    # transitively-shared problem. A problem seed is skipped: its decisions are
    # epic-wide history, retrieved through the scored pool, never mandatory.
    for s in seeds:
        if s.startswith("problem:"):
            continue
        for r in conn.execute(
            "SELECT e.from_id AS d, n.status AS st FROM edge e JOIN node n ON n.id=e.from_id "
            "WHERE e.to_id=? AND e.rel='decides'", (s,)):
            if r["st"] == "live":
                ids.add(r["d"])
    return ids


def _stale(conn, node_row, head_cache):
    lv = node_row["last_verified_at"] or ""
    paths = []
    if node_row["type"] == "module" and node_row["module"]:
        paths.append(node_row["module"])
    for r in conn.execute(
        "SELECT n.module AS m FROM edge e JOIN node n ON n.id IN (e.from_id,e.to_id) "
        "WHERE (e.from_id=? OR e.to_id=?) AND e.rel IN ('touches','implements') "
        "AND n.type='module'", (node_row["id"], node_row["id"])):
        if r["m"]:
            paths.append(r["m"])
    for p in paths:
        head = head_cache.get(p)
        if head and head > lv:
            return True
    return False


def _score(conn, nid, weight, span, now, uses_on=True):
    r = conn.execute("SELECT created_at, uses FROM node WHERE id=?", (nid,)).fetchone()
    created = r["created_at"] or ""
    recency = 0.5
    if span and created:
        try:
            frac = (span[2].fromisoformat(created.replace("Z", "+00:00")) - span[0]).total_seconds() / span[1]
            recency = 0.5 + 0.5 * max(0.0, min(1.0, frac))
        except Exception:
            recency = 0.5
    uses_factor = (1.0 + math.log1p(r["uses"] or 0)) if uses_on else 1.0
    return weight * recency * uses_factor


def _span(conn):
    from datetime import datetime, timezone
    rows = conn.execute("SELECT min(created_at) a, max(created_at) b FROM node WHERE created_at IS NOT NULL").fetchone()
    try:
        a = datetime.fromisoformat(rows["a"].replace("Z", "+00:00"))
        b = datetime.fromisoformat(rows["b"].replace("Z", "+00:00"))
        secs = max(1.0, (b - a).total_seconds())
        return (a, secs, datetime), b
    except Exception:
        return None, None


DETAIL_TYPES = ("decision", "check", "lesson")


def _render_line(r, stale):
    tag = r["type"].upper()
    flag = " [STALE]" if stale else ""
    return f"- {tag}{flag}: {r['text']}  <{r['id']}>"


def _detail(conn, r):
    """The one-line node text is the INDEX; enumerated answers live in the source
    excerpt. walk surfaces it for its top fact-bearing nodes (finding: a
    one-sentence cap alone loses lists like 'what remains: 1... 2...')."""
    if r["type"] not in DETAIL_TYPES or not r["source_id"]:
        return ""
    s = conn.execute("SELECT excerpt FROM source WHERE id=?", (r["source_id"],)).fetchone()
    if not s or not s["excerpt"]:
        return ""
    ex = " ".join(s["excerpt"].split())
    # window the excerpt on the ruling content (where node.text starts in the
    # source), not the first 340 chars — otherwise a message's preamble is all
    # the reader ever sees (this was the real Q7 information-loss bug).
    probe = r["text"][:40]
    idx = ex.find(probe)
    if idx > 0:
        ex = ex[idx:]
    elif idx == 0:
        ex = ex[len(r["text"]):].strip() or ex
    return "    detail: " + ex[:340] if ex else ""


def walk(start, uses_on=True, record=False, detail=False, conn=None):
    """Pure deterministic read by default. record=True bumps the `uses` counter
    of the returned nodes (popularity feedback) — off during determinism tests.
    detail=True surfaces the source excerpt for top fact-bearing nodes."""
    close = False
    if conn is None:
        conn, close = db.connect(), True
    seeds, seed_kind = resolve_seeds(conn, start)
    span, _ = _span(conn)
    head_cache = {r["path"]: r["head_at"] for r in conn.execute("SELECT path, head_at FROM module_head")}

    mandatory = _mandatory(conn, seeds) if seeds else set()

    # scored BFS remainder (<= 2 hops), excluding replaced + mandatory
    best = {}  # id -> weight
    frontier = {s: 1.0 for s in seeds}
    for s in seeds:
        best[s] = 1.0
    for _hop in range(MAX_HOPS):
        nxt = {}
        for nid, w in frontier.items():
            for o, rel in _neighbors(conn, nid):
                ow = w * REL_WEIGHT.get(rel, 0.4)
                if ow > best.get(o, 0.0):
                    best[o] = ow
                    nxt[o] = ow
        frontier = nxt

    scored = []
    for nid, w in best.items():
        if nid in mandatory:
            continue
        scored.append((_score(conn, nid, w, span, None, uses_on), nid))
    scored.sort(key=lambda x: (-x[0], x[1]))

    # assemble: mandatory first (never cut), then scored until caps.
    # sorted() so the set's hash-seed iteration order can't make walk
    # non-deterministic across processes.
    selected, cut_by_type = [], {}
    mandatory_set = set(mandatory)
    order = sorted(mandatory) + [nid for _, nid in scored]
    used_bytes, count, detailed, mandatory_bytes = 0, 0, 0, 0
    lines = []
    for nid in _dedupe(order):
        r = conn.execute("SELECT * FROM node WHERE id=?", (nid,)).fetchone()
        if r is None or r["status"] == "replaced":
            continue
        stale = _stale(conn, r, head_cache)
        line = _render_line(r, stale)
        block = line
        if detail and detailed < DETAIL_LIMIT:
            d = _detail(conn, r)
            if d:
                block = line + "\n" + d
                detailed += 1
        bsize = len(block.encode("utf-8")) + 1  # real UTF-8 bytes, not chars
        forced = nid in mandatory_set
        if not forced and (count >= MAX_NODES or used_bytes + bsize > MAX_BYTES):
            cut_by_type[r["type"]] = cut_by_type.get(r["type"], 0) + 1
            continue
        selected.append(nid); lines.append(block)
        if record:
            conn.execute("UPDATE node SET uses = uses + 1 WHERE id=?", (nid,))
        used_bytes += bsize
        if forced:
            mandatory_bytes += bsize
        count += 1
    if record:
        conn.commit()

    receipt = {
        "start": start, "seed_kind": seed_kind, "seeds": seeds,
        "returned": count, "mandatory": len(mandatory_set & set(selected)),
        "bytes": used_bytes, "cut_by_type": cut_by_type,
        "cap": {"nodes": MAX_NODES, "bytes": MAX_BYTES},
        # mandatory constraints are exempt from the cut, so they can push the
        # total past the cap; the receipt says so rather than hide it.
        "mandatory_overflow": used_bytes > MAX_BYTES or count > MAX_NODES,
        "mandatory_bytes": mandatory_bytes,
    }
    body = "\n".join(lines)
    if close:
        conn.close()
    return body, receipt, selected


def _dedupe(seq):
    seen = set()
    for x in seq:
        if x not in seen:
            seen.add(x); yield x


if __name__ == "__main__":
    # Node text carries arrows and dashes; a cp1252 console (Windows default) raised UnicodeEncodeError (qa).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    start = sys.argv[1] if len(sys.argv) > 1 else "epic-44a0576511"
    body, receipt, _ = walk(start)
    print("== receipt ==")
    for k, v in receipt.items():
        print(f"  {k}: {v}")
    print("== walk output ==")
    print(body)
