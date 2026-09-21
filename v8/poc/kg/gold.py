"""Gold-question harness for the KG PoC (S13).

Holds the 12 architect gold questions (note-0151676530), each mapped to the
node(s) that actually carry its answer -- used ONLY to measure recall, NEVER
shown to the answering seat. Provides:
  - seed comparison: FTS5/BM25 vs a zero-dependency TF-IDF cosine baseline
    (no neural embedder is available on this host; see findings)
  - walk recall: per question, did walk() return a needed node? names misses
  - a `uses`-eviction check (did the popularity factor push a needed node out)
  - pack writer: the walk output handed to the fresh answering seat

Run: python poc/kg/gold.py            # recall + seed comparison
     python poc/kg/gold.py pack out.md  # write the answering pack
"""
from __future__ import annotations

import math
import re
import sys
from collections import Counter

import db
import walk

# Each question: q text (shown to the seat), seed (walk start, may be shaped
# from the question per the architect's steer), need = answer-bearing node ids
# (marking aid only, never shown). Multiple need ids = any one suffices.
QUESTIONS = [
    {"id": 1, "q": "What visual reference must the board UI match, and is it binding or background?",
     "seed": "visual reference renders board UI match binding",
     "need": ["ref:revision3-clean", "decision:m-9454a938d8"]},
    {"id": 2, "q": "Which model do building seats run on, and which model does QA run on?",
     "seed": "which model building seats run on and which model QA runs on",
     "need": ["decision:m-cd794bb07c", "decision:m-6f88809fb9"]},
    {"id": 3, "q": "How many QA seats may this epic have?",
     "seed": "how many QA seats one consolidated qa seat epic",
     "need": ["design_part:note-55e4059e2e", "decision:m-e72e114ecc", "decision:m-db2c34eca0"]},
    {"id": 4, "q": "May an agent seat restart the shared board, proxy or pool, and under what condition?",
     "seed": "may an agent restart shared board proxy pool owner authorisation",
     "need": ["check:c-b64e3e2dba", "decision:m-4066aaddd1"]},
    {"id": 5, "q": "Which hosts may a Slack webhook point to, and when is that enforced?",
     "seed": "which hosts slack webhook allow-list hooks.slack.com enforced save send",
     "need": ["decision:m-0c01b6dd0a", "decision:m-cc4b2c2917"]},
    {"id": 6, "q": "Where do notifications live in the UI, and what sits directly above Find in the rail?",
     "seed": "notifications account menu Usage directly above Find rail",
     "need": ["check:c-1165c735b6"]},
    {"id": 7, "q": "What remains before the epic can be accepted?",
     "seed": "what remains before epic accepted only a few checks left owner-present",
     "need": ["decision:m-29ccb0c637"]},
    {"id": 8, "q": "What is the default size budget of context(), and how do you get the full output?",
     "seed": "default size budget of context bytes verbose full output",
     "need": ["check:c-95dee00a73", "decision:m-29551ca78e"]},
    {"id": 9, "q": "Why did a resumed seat get 401 on every tool call, and what fixed it?",
     "seed": "resumed seat 401 every tool call token dropped resume fixed",
     "need": ["lesson:m-be1f9350f3", "decision:m-81a3d39a03"]},
    {"id": 10, "q": "Which code handles conversation paging, and what does the page indicator read?",
     "seed": "web/src/components/useThreadHistory.tsx",
     "need": ["module:web/src/components/useThreadHistory.tsx", "ticket:s-5c93e5e31e"]},
    {"id": 11, "q": "What happens when a user saves an invalid or off-list Slack webhook?",
     "seed": "invalid off-list slack webhook rejected 422 field error stored untouched",
     "need": ["decision:m-9a5ff76772"]},
    {"id": 12, "q": "Is a framework role cut allowed right now?",
     "seed": "framework role cut allowed held until owner answers three yes no",
     "need": ["decision:m-6f88809fb9"]},
]


# ---- zero-dependency TF-IDF cosine baseline (stand-in for a dense method) ----

_TOK = re.compile(r"[A-Za-z0-9_]+")


def _toks(s):
    return [t.lower() for t in _TOK.findall(s or "")]


class TfIdf:
    def __init__(self, conn):
        self.ids, self.docs = [], []
        for r in conn.execute("SELECT id, text FROM node WHERE status='live'"):
            self.ids.append(r["id"]); self.docs.append(_toks(r["text"]))
        n = len(self.docs)
        df = Counter()
        for d in self.docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + n / (1 + c)) for t, c in df.items()}
        self.vecs = [self._vec(d) for d in self.docs]

    def _vec(self, toks):
        tf = Counter(toks)
        v = {t: (c / len(toks)) * self.idf.get(t, 0.0) for t, c in tf.items()} if toks else {}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def seed(self, query, k=5):
        q = self._vec(_toks(query))
        scored = []
        for nid, v in zip(self.ids, self.vecs):
            keys = q.keys() & v.keys()
            if keys:
                scored.append((sum(q[t] * v[t] for t in keys), nid))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [nid for _, nid in scored[:k]]


def fts_seed(conn, query, k=5):
    from walk import _fts_seed
    return _fts_seed(conn, query, k)


def seed_comparison(conn):
    tfidf = TfIdf(conn)
    print("\n== SEED COMPARISON: FTS5/BM25 vs TF-IDF cosine (no neural embedder available) ==")
    print(f"{'Q':>2}  {'FTS5 hit':>8}  {'TFIDF hit':>9}  seed")
    fh = th = 0
    for item in QUESTIONS:
        need = set(item["need"])
        fs = fts_seed(conn, item["seed"], 5)
        ts = tfidf.seed(item["seed"], 5)
        f_ok = bool(need & set(fs)); t_ok = bool(need & set(ts))
        fh += f_ok; th += t_ok
        print(f"{item['id']:>2}  {('HIT' if f_ok else 'miss'):>8}  {('HIT' if t_ok else 'miss'):>9}  {item['seed'][:46]}")
    print(f"seed recall@5 -- FTS5: {fh}/12   TF-IDF: {th}/12")
    return fh, th


def walk_recall(conn):
    print("\n== WALK RECALL (did walk() return a needed node?) ==")
    hits, misses = 0, []
    evicted = []
    for item in QUESTIONS:
        need = set(item["need"])
        _, r_on, sel_on = walk.walk(item["seed"], uses_on=True, detail=True, conn=conn)
        got = need & set(sel_on)
        if got:
            hits += 1
            status = "HIT " + next(iter(got))
        else:
            misses.append(item["id"])
            status = "MISS  need=" + ",".join(sorted(need))
        # uses-eviction: with uses off, does a previously-missed need node appear?
        _, _, sel_off = walk.walk(item["seed"], uses_on=False, detail=True, conn=conn)
        if not got and (need & set(sel_off)):
            evicted.append(item["id"])
        print(f"  Q{item['id']:>2}: {status}")
    print(f"walk recall: {hits}/12; misses: {misses or 'none'}")
    print(f"'uses' pushed a needed node out of the cut on: {evicted or 'no question'}")
    return hits, misses, evicted


def write_pack(conn, path):
    """One deduped read for the answering seat: the union of the 12 per-question
    walks, each node printed once (that is what a real seat would hold), then the
    12 questions. Answer-node ids are NOT in here beyond the walk's own output."""
    seen, know = set(), []
    per_q_bytes = 0
    for item in QUESTIONS:
        body, r, sel = walk.walk(item["seed"], uses_on=True, detail=True, conn=conn)
        per_q_bytes += r["bytes"]
        block = []
        cur_id = None
        for line in body.splitlines():
            if line.startswith("- "):
                if cur_id and cur_id not in seen:
                    seen.add(cur_id); know.append("\n".join(block))
                m = re.search(r"<([^>]+)>\s*$", line)
                cur_id = m.group(1) if m else line
                block = [line]
            else:
                block.append(line)
        if cur_id and cur_id not in seen:
            seen.add(cur_id); know.append("\n".join(block))
    parts = ["# Knowledge pack (walk output only) — answer the questions from THIS alone.\n",
             "## Facts\n" + "\n".join(know),
             "\n## Questions\n" + "\n".join(f"{it['id']}. {it['q']}" for it in QUESTIONS)]
    text = "\n".join(parts)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    nbytes = len(text.encode("utf-8"))
    print(f"pack: {path}  unique_nodes={len(know)}  pack_bytes={nbytes}  "
          f"(sum of 12 raw walks={per_q_bytes})")
    return nbytes


if __name__ == "__main__":
    conn = db.connect()
    if len(sys.argv) > 2 and sys.argv[1] == "pack":
        write_pack(conn, sys.argv[2])
    else:
        seed_comparison(conn)
        walk_recall(conn)
