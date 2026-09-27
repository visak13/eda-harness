"""Can lookup(scope=epic, question=...) answer the ctx-pack exam's Q1-Q3? Run on a private DB copy."""
import json, sqlite3, sys, os, tempfile
from pathlib import Path

V8 = Path(__file__).resolve().parents[4]
SP = Path(os.environ.get("LOOKUP_EXAM_OUT") or Path(tempfile.gettempdir()) / "lookup-exam")  # DB copy + results, never the repo
SP.mkdir(parents=True, exist_ok=True)
EX = V8 / "docs/evidence/ctx-pack-exam"
EPIC = "epic-7f3d64e6de"
USE_INDEX = "--index" in sys.argv

copy = SP / "edp8-copy.db"
if not copy.exists():
    src = sqlite3.connect(f"file:{V8/'.data/edp8.db'}?mode=ro", uri=True)
    dst = sqlite3.connect(copy)
    src.backup(dst); dst.close(); src.close()

sys.path.insert(0, str(V8 / "src"))
from edp8.store import Store
from edp8.board import Board

store = Store(str(copy))
index = None
if USE_INDEX:
    import time, shutil
    from edp8.search import Index, VectorCache, make_embedder
    vc = SP / "edp8-copy.db.vec"
    if not vc.exists():
        shutil.copy(V8 / ".data/edp8.db.vec", vc)
    index = Index(embedder=make_embedder(), cache=VectorCache(str(vc)))
    index.rebuild(store.all_text_units())
    t0 = time.monotonic()
    while index.status().get("warming") and time.monotonic() - t0 < 600:
        time.sleep(1)
    print("index", index.status(), file=sys.stderr)
board = Board(store, index)

exam = json.loads((EX / "exam.json").read_text(encoding="utf-8"))
key = {k["seat"]: k for k in json.loads((EX / "key.json").read_text(encoding="utf-8"))}


def key_ids(k, q):
    v = k.get(q)
    if not v:
        return []
    if isinstance(v, dict):
        return [v["id"]] if v.get("id") else []
    return [x["id"] for x in v if x.get("id")]


def variants(seat, tickets, q, text):
    tk = " ".join(tickets)
    if q == "Q1":
        extra = f"criteria not pass verdict pending on {tk}"
    elif q == "Q2":
        extra = f"latest message addressed to {seat}"
    else:
        extra = f"owner messages cited by {tk}"
    return {"verbatim": text, "seat_words": extra}


rows = []
for s in exam:
    seat, tickets = s["seat"], s["tickets"]
    actor = store.get("participant", seat)
    k = key[seat]
    for qq in s["questions"]:
        q = qq["qid"]
        want = key_ids(k, q)
        res = {"seat": seat, "qid": q, "want": want}
        for vname, question in variants(seat, tickets, q, qq["text"]).items():
            out = board.lookup(actor, scope=EPIC, question=question)
            blob = json.dumps(out)
            got = [w for w in want if w in blob]
            types = sorted({r.get("type") for r in out.get("records", [])})
            res[vname] = {"got": got, "n_records": len(out.get("records", [])), "types": types,
                          "excerpts": out.get("receipt", {}).get("source_excerpts")}
            f = board.find(question, k=10, epic_id=EPIC)
            fb = json.dumps(f)
            res[vname]["find_got"] = [w for w in want if w in fb]
        # id-seeded lookup from the seat's first ticket
        out = board.lookup(actor, scope=EPIC, id=tickets[0])
        blob = json.dumps(out)
        res["id_seed"] = {"got": [w for w in want if w in blob], "n_records": len(out.get("records", [])),
                          "types": sorted({r.get("type") for r in out.get("records", [])})}
        rows.append(res)
        print(seat, q, len(want), {v: len(res[v]["got"]) for v in ("verbatim", "seat_words", "id_seed")},
              {v: len(res[v]["find_got"]) for v in ("verbatim", "seat_words")}, file=sys.stderr)

name = "lookup-exam-index.json" if USE_INDEX else "lookup-exam-fts.json"
(SP / name).write_text(json.dumps(rows, indent=1), encoding="utf-8")
