"""Incremental ingest: board REST + git log -> kg.db.

Plain rules only, zero model calls. Re-running after new events adds or
replaces only what changed (idempotent upserts keyed on the source id, a
message-seq cursor, and a per-file git head). Run: python poc/kg/ingest.py
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from collections import defaultdict

import db
import board

EPIC = "epic-44a0576511"
REPO = "C:/Projects/Learning/eda-base3"
RENDER_NODE = "ref:revision3-clean"
RENDER_RE = re.compile(r"revision3-clean", re.I)

# owner messages that "rule on something": kind + author is the plain rule;
# a ruling verb is the lexical fallback that needs judgement (counted).
RULING_RE = re.compile(
    r"\b(use|uses|must|only|no longer|approv|authoris|authoriz|hold|held|"
    r"instead|final|decide|decision|rule[sd]?|require[sd]?|ban|forbid|allow|"
    r"keep|drop|cut|reject|do not|don't|never|always|shall|will run|runs on|"
    r"remain|remains|before .* accept|held until|answer)\b",
    re.I,
)
_SENT = re.compile(r"(?<=[.!?])\s+")


def one_sentence(text: str, maxlen: int = 300) -> str:
    text = " ".join((text or "").split())
    if not text:
        return "(empty)"
    first = _SENT.split(text)[0]
    return first[:maxlen]


def ruling_sentence(text: str, maxlen: int = 300) -> str:
    """Prefer the first sentence that actually states a ruling; else the first."""
    text = " ".join((text or "").split())
    for s in _SENT.split(text):
        if RULING_RE.search(s):
            return s[:maxlen]
    return one_sentence(text, maxlen)


# ---- upserts (return True only when a row's content actually changed) --------

def upsert_source(conn, kind, ref, excerpt):
    sid = f"{kind}:{ref}"
    conn.execute(
        "INSERT INTO source(id, kind, ref, excerpt) VALUES (?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET excerpt=excluded.excerpt",
        (sid, kind, ref, (excerpt or "")[:2000]),
    )
    return sid


def upsert_node(conn, nid, ntype, text, *, status="live", module=None,
                source_id=None, created_at=None, last_verified_at=None):
    row = conn.execute("SELECT type,text,status,module,source_id,created_at,last_verified_at "
                       "FROM node WHERE id=?", (nid,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO node(id,type,text,status,module,source_id,created_at,last_verified_at,uses)"
            " VALUES (?,?,?,?,?,?,?,?,0)",
            (nid, ntype, text, status, module, source_id, created_at, last_verified_at or created_at),
        )
        return True
    # update only mutable content fields; NEVER auto-bump last_verified_at, and
    # NEVER touch status here (the replaces pass owns live|replaced) — otherwise
    # a re-run would flip replaced nodes back and churn.
    changed = (row["text"] != text or row["module"] != module or row["type"] != ntype)
    if changed:
        conn.execute("UPDATE node SET type=?,text=?,module=?,source_id=? WHERE id=?",
                     (ntype, text, module, source_id, nid))
    return changed


def add_edge(conn, from_id, to_id, rel, created_at=None):
    cur = conn.execute(
        "INSERT OR IGNORE INTO edge(from_id,to_id,rel,created_at) VALUES (?,?,?,?)",
        (from_id, to_id, rel, created_at),
    )
    return cur.rowcount > 0


# ---- ingest stages -----------------------------------------------------------

def ingest_tickets(conn, stats):
    tickets = board.tickets(EPIC)
    label_map = {}  # "S10" -> ticket id
    for t in tickets:
        tid = t["id"]
        if t["kind"] == "epic":
            src = upsert_source(conn, "ticket", tid, t.get("words") or t.get("title"))
            if upsert_node(conn, f"problem:{tid}", "problem",
                           one_sentence(t.get("words") or t.get("title")),
                           source_id=src, created_at=t.get("created_at")):
                stats["node+"] += 1
            continue
        src = upsert_source(conn, "ticket", tid, t.get("title"))
        nid = f"ticket:{tid}"
        if upsert_node(conn, nid, "ticket", one_sentence(t.get("title")),
                       source_id=src, created_at=t.get("created_at")):
            stats["node+"] += 1
        stats["edge+"] += add_edge(conn, nid, f"problem:{EPIC}", "part_of", t.get("created_at"))
        stats["edge+"] += add_edge(conn, nid, src, "came_from", t.get("created_at"))
        m = re.match(r"(S\d+)\b", t.get("title", ""))
        if m:
            label_map[m.group(1).upper()] = tid
        # criteria for this ticket
        for c in board.criteria(tid):
            csrc = upsert_source(conn, "criterion", c["id"], c.get("text"))
            cnid = f"check:{c['id']}"
            if upsert_node(conn, cnid, "check", one_sentence(c.get("text"), 400),
                           source_id=csrc, created_at=c.get("created_at")):
                stats["node+"] += 1
            stats["edge+"] += add_edge(conn, cnid, nid, "verifies", c.get("created_at"))
            ev = c.get("evidence_ref")
            if ev:
                esrc = upsert_source(conn, "evidence", ev, f"evidence for {c['id']}")
                enid = f"evidence:{ev}"
                if upsert_node(conn, enid, "evidence", f"Evidence {ev} recorded against a criterion.",
                               source_id=esrc, created_at=c.get("created_at")):
                    stats["node+"] += 1
                stats["edge+"] += add_edge(conn, enid, cnid, "proves", c.get("created_at"))
    return tickets, label_map


def ingest_messages(conn, stats):
    since = int(db.get_state(conn, "msg_seq", "0"))
    msgs = board.messages(EPIC, since_seq=since)
    if not msgs:
        return 0
    by_reply = defaultdict(list)  # reply_to root -> [decision nodes] for replaces chains
    judgement = 0
    maxseq = since
    for m in sorted(msgs, key=lambda x: x.get("seq", 0)):
        maxseq = max(maxseq, m.get("seq", 0))
        author, kind, mid = m.get("created_by", ""), m.get("kind"), m["id"]
        tid = m.get("ticket_id") or EPIC
        target = f"ticket:{tid}" if tid != EPIC else f"problem:{EPIC}"
        text = m.get("text", "")

        is_owner = author == "owner"
        is_arch = author.startswith("architect")
        # decisions: owner (or architect state-setting) rulings
        if kind in ("answer", "steer", "note") and (is_owner or is_arch):
            structural = (kind == "answer" and m.get("reply_to"))
            lexical = bool(RULING_RE.search(text))
            if structural or lexical:
                if lexical and not structural:
                    judgement += 1
                src = upsert_source(conn, "message", mid, text)
                nid = f"decision:{mid}"
                if upsert_node(conn, nid, "decision", ruling_sentence(text),
                               source_id=src, created_at=m.get("created_at")):
                    stats["node+"] += 1
                stats["edge+"] += add_edge(conn, nid, target, "decides", m.get("created_at"))
                stats["edge+"] += add_edge(conn, nid, src, "came_from", m.get("created_at"))
                if m.get("reply_to"):
                    by_reply[m["reply_to"]].append((m.get("seq", 0), nid, m.get("created_at")))
        # lessons: findings and deviations, any author
        if kind in ("finding", "deviation"):
            src = upsert_source(conn, "message", mid, text)
            nid = f"lesson:{mid}"
            if upsert_node(conn, nid, "lesson", one_sentence(text, 400),
                           source_id=src, created_at=m.get("created_at")):
                stats["node+"] += 1
            stats["edge+"] += add_edge(conn, nid, target, "learned_from", m.get("created_at"))
            stats["edge+"] += add_edge(conn, nid, src, "came_from", m.get("created_at"))

    # replaces: within one reply_to thread, a later owner/architect decision
    # supersedes the earlier one; mark earlier replaced, edge new -> old.
    for root, items in by_reply.items():
        items.sort()
        for (s1, prev, _), (s2, cur, at2) in zip(items, items[1:]):
            conn.execute("UPDATE node SET status='replaced' WHERE id=?", (prev,))
            stats["edge+"] += add_edge(conn, cur, prev, "replaces", at2)
    db.set_state(conn, "msg_seq", str(maxseq))
    stats["judgement"] = stats.get("judgement", 0) + judgement
    stats["msgs_scanned"] = stats.get("msgs_scanned", 0) + len(msgs)
    return len(msgs)


def ingest_docs(conn, stats):
    for d in board.docs(EPIC):
        did = d["id"]
        if d.get("doc_type") not in ("design", "note"):
            continue
        full = board.doc(did)
        body = full.get("body_md", "")
        src = upsert_source(conn, "doc", did, d.get("title"))
        nid = f"design_part:{did}"
        if upsert_node(conn, nid, "design_part", one_sentence(d.get("title"), 200),
                       source_id=src, created_at=d.get("created_at")):
            stats["node+"] += 1
        stats["edge+"] += add_edge(conn, nid, f"problem:{EPIC}", "part_of", d.get("created_at"))
        stats["edge+"] += add_edge(conn, nid, src, "came_from", d.get("created_at"))
        if RENDER_RE.search(body) or RENDER_RE.search(d.get("title", "")):
            stats["edge+"] += add_edge(conn, nid, RENDER_NODE, "must_follow", d.get("created_at"))
    return None


def ingest_git(conn, stats, tickets, label_map):
    # alias set per ticket: its id and its S-label
    alias_to_ticket = {}
    for t in tickets:
        if t["kind"] != "epic":
            alias_to_ticket[t["id"]] = t["id"]
    alias_to_ticket.update(label_map)
    alias_to_ticket[EPIC] = EPIC
    aliases = sorted(alias_to_ticket, key=len, reverse=True)

    out = subprocess.run(
        ["git", "-C", REPO, "log", "--name-only",
         "--pretty=format:%x01%H%x1f%aI%x1f%s", "--", "v8"],
        capture_output=True, text=True, encoding="utf-8",
    ).stdout
    head_at = {}  # normalized path -> latest commit iso
    for block in out.split("\x01"):
        if not block.strip():
            continue
        header, *rest = block.split("\n")
        parts = header.split("\x1f")
        if len(parts) < 3:
            continue
        sha, cdate, subject = parts[0], parts[1], parts[2]
        files = [f for f in rest if f.strip()]
        # which epic tickets does this commit name?
        matched = {alias_to_ticket[a] for a in aliases if a in subject}
        if not matched:
            continue
        csrc = upsert_source(conn, "commit", sha[:12], subject)
        for f in files:
            path = f[3:] if f.startswith("v8/") else f  # story convention drops v8/
            if head_at.get(path, "") < cdate:
                head_at[path] = cdate
            mnid = f"module:{path}"
            # module.last_verified_at set once, at creation, to this commit date
            if upsert_node(conn, mnid, "module", path, module=path,
                           source_id=csrc, created_at=cdate, last_verified_at=cdate):
                stats["node+"] += 1
            stats["edge+"] += add_edge(conn, mnid, csrc, "came_from", cdate)
            for tid in matched:
                tnode = f"ticket:{tid}" if tid != EPIC else f"problem:{EPIC}"
                stats["edge+"] += add_edge(conn, mnid, tnode, "touches", cdate)
    # refresh live code state (this is what staleness compares against)
    for path, at in head_at.items():
        conn.execute(
            "INSERT INTO module_head(path,head_at) VALUES (?,?) "
            "ON CONFLICT(path) DO UPDATE SET head_at=excluded.head_at",
            (path, at),
        )
    stats["modules"] = len(head_at)
    return None


def ensure_render_node(conn, stats):
    if upsert_node(conn, RENDER_NODE, "design_part",
                   "The board UI must match the revision3-clean renders (binding, not background).",
                   created_at="2026-09-18T00:00:00Z"):
        stats["node+"] += 1


def run():
    t0 = time.time()
    conn = db.connect()
    stats = defaultdict(int)
    before_n = conn.execute("SELECT count(*) FROM node").fetchone()[0]
    before_e = conn.execute("SELECT count(*) FROM edge").fetchone()[0]

    ensure_render_node(conn, stats)
    tickets, label_map = ingest_tickets(conn, stats)
    ingest_messages(conn, stats)
    ingest_docs(conn, stats)
    ingest_git(conn, stats, tickets, label_map)
    conn.commit()

    after_n = conn.execute("SELECT count(*) FROM node").fetchone()[0]
    after_e = conn.execute("SELECT count(*) FROM edge").fetchone()[0]
    by_type = dict(conn.execute("SELECT type, count(*) FROM node GROUP BY type").fetchall())
    by_rel = dict(conn.execute("SELECT rel, count(*) FROM edge GROUP BY rel").fetchall())
    print(f"ingest done in {time.time()-t0:.1f}s")
    print(f"  nodes: {before_n} -> {after_n} (new content writes: {stats['node+']})")
    print(f"  edges: {before_e} -> {after_e} (new edges: {stats['edge+']})")
    print(f"  msgs scanned this run: {stats.get('msgs_scanned',0)}; "
          f"owner/arch decisions needing lexical judgement: {stats.get('judgement',0)}")
    print(f"  node types: {by_type}")
    print(f"  edge types: {by_rel}")
    print(f"  modules tracked: {stats.get('modules',0)}")
    conn.close()
    return after_n, after_e


if __name__ == "__main__":
    run()
