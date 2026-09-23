"""S14-C1 offline replay: exam4 + tests/exam_regressions.json at 8 KB vs 16 KB (and lessons 1,500 vs 3,000 B),
one process, one index, on a sqlite-backup snapshot of .data/edp8.db (the live board is never touched).

    .venv/Scripts/python.exe scripts/exam_offline_replay.py <out_dir> [--v8 <v8 dir>] [--lesson-bytes 1500]

Deterministic: every question is embedded once and cached in <out_dir>/qvec.json (the host's 1.5 GB mid-embed
RAM guard otherwise drops the dense leg per question and the numbers wander run to run), and one request clock
(ref_now) serves every lookup. Writes run_<exam>_<cap>_<lessons>/ (packs + manifest via edp8.exam.run_packs),
replay_result.json, and epic_audit.json (per epic: bytes == len(json.dumps(records)), every live binding shown).
Delete <out_dir>/snap.db to re-snapshot the live DB.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from edp8 import exam, knowledge, search
from edp8.board import Board
from edp8.search import Index, VectorCache, make_embedder
from edp8.store import Store

CONFIGS = ((8000, 1500), (16000, 1500), (16000, 3000))  # (MAX_BYTES, LESSON_MAX_BYTES)
AUDIT_QUESTION = "what are the rules and decisions in force"
REPLAY_RAM_FLOOR_GB = 0.6  # replay-only; the model is loaded once and each query is embedded once


def _snapshot(v8: Path, out: Path) -> tuple[Path, Path]:
    snap, vec = out / "snap.db", out / "snap.db.vec"
    if not snap.exists():
        for src, dst in ((v8 / ".data/edp8.db", snap), (v8 / ".data/edp8.db.vec", vec)):
            s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
            d = sqlite3.connect(dst)
            s.backup(d)
            d.close()
            s.close()
    return snap, vec


def _cached_query_embedder(out: Path, questions: list[str]):
    search.RAM_FLOOR_GB = REPLAY_RAM_FLOOR_GB
    emb = make_embedder(ram_floor=REPLAY_RAM_FLOOR_GB)
    qfile = out / "qvec.json"
    qcache = json.loads(qfile.read_text(encoding="utf-8")) if qfile.exists() else {}
    missing = [q for q in dict.fromkeys(questions) if q not in qcache]
    if missing:
        for q, v in zip(missing, emb.embed(missing, is_query=True)):
            qcache[q] = [float(x) for x in v]
        qfile.write_text(json.dumps(qcache), encoding="utf-8")
    raw = emb.embed

    def embed(texts: list[str], is_query: bool = False) -> list[list[float]]:
        if is_query:
            return [qcache[t] for t in texts]  # KeyError = an unexpected query: fail loudly
        return raw(texts, is_query=is_query)

    emb.embed = embed
    return emb


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("out", type=Path)
    p.add_argument("--v8", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--lesson-bytes", type=int, default=knowledge.LESSON_MAX_BYTES)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    exams = {"exam4": a.v8 / ".data/exams/r4b/exam4.json", "regr": a.v8 / "tests/exam_regressions.json"}
    loaded = {k: exam.load_exam(path) for k, path in exams.items()}

    snap, vec = _snapshot(a.v8, a.out)
    store = Store(str(snap))
    questions = [q["question"] for qs in loaded.values() for q in qs] + [AUDIT_QUESTION]
    index = Index(embedder=_cached_query_embedder(a.out, questions), cache=VectorCache(str(vec)))
    board = Board(store, index)
    index.rebuild(store.all_text_units())
    if index._warm_thread is not None:
        index._warm_thread.join()
    print("index", index.status(), flush=True)
    actor = store.query("participant", limit=1)[0]
    clock = datetime.now(timezone.utc)  # one request clock for every lookup (O2)

    def lookup(scope: str, question: str) -> dict:
        return {"ok": True, "value": board.lookup(actor, scope=scope, question=question, ref_now=clock)}

    res = {}
    for cap, lesson_bytes in CONFIGS:
        knowledge.MAX_BYTES, knowledge.LESSON_MAX_BYTES = cap, lesson_bytes
        for name, qs in loaded.items():
            key = f"{name}_{cap}_{lesson_bytes}"
            res[key] = exam.run_packs(qs, a.out / f"run_{key}", lookup=lookup, rev=f"offline-{cap}-{lesson_bytes}")
            print(key, res[key]["summary"], flush=True)
    (a.out / "replay_result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")

    knowledge.MAX_BYTES, knowledge.LESSON_MAX_BYTES = 16000, a.lesson_bytes
    audit = []
    for e in sorted({q["epic"] for q in loaded["exam4"]}):
        out = board.lookup(actor, scope=e, question=AUDIT_QUESTION, ref_now=clock)
        rc = out["receipt"]
        ids = [r["id"] for r in out["records"]]
        live_binding = {d.id for d in store.query("decision", {"status": "live"}, limit=100000)
                        if getattr(d, "binding", False) and knowledge._epic_id_of(store, d.scope or "") == e}
        shown = {r["id"] for r in out["records"] if r.get("binding")}
        audit.append({"epic": e, "bytes": rc["bytes"], "payload": len(json.dumps(out["records"]).encode("utf-8")),
                      "dups": len(ids) - len(set(ids)), "binding_live": len(live_binding),
                      "binding_missing": sorted(live_binding - shown), "always_bytes": rc["always_bytes"],
                      "mandatory_overflow": rc["mandatory_overflow"], "seed_kind": rc["seed_kind"]})
        print("epic", audit[-1], flush=True)
    (a.out / "epic_audit.json").write_text(json.dumps(audit, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
