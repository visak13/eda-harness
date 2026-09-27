"""Context-pack exam replay (t-d606b5d93f, dec-7581ebda87): render seats' boot `context()` packs from a
sqlite-backup copy of the fleet DB, in-process, and report whether each key message id is in the pack.

    .venv/Scripts/python.exe scripts/ctx_pack_replay.py <out_dir> --budget 16000 [--label after]
        [--as-of-seq 23765] [--seat architect.epic-7f3d64e6de=m-e633397a42 ...]

The live board is never touched: the DB is copied with the SQLite backup API into <out_dir>/snap.db
(reused if present; delete it to re-snapshot) and opened with edp8.board.Board. `bundles._context`
bounds each snapshot exactly as the MCP tool does. Writes <out_dir>/<label>/<seat>.json and prints
one row per seat: bytes, key id in pack, and where (for_you / thread / asks_for_me).
--as-of-seq rewinds the thread to the exam's moment: a second copy drops every message and event row after
that seq (the exam packs' cursor seq is 23765, 2026-09-27 08:21:39Z). Ticket and criterion rows stay current.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

DEFAULT_SEATS = ("architect.epic-7f3d64e6de=m-e633397a42", "qa.epic-7f3d64e6de=m-078c3f13c3")


def _snapshot(v8: Path, out: Path, as_of: int | None) -> Path:
    snap = out / "snap.db"
    if not snap.exists():
        s = sqlite3.connect(f"file:{v8 / '.data/edp8.db'}?mode=ro", uri=True)
        d = sqlite3.connect(snap)
        s.backup(d)
        d.close()
        s.close()
    if as_of is None:
        return snap
    rewound = out / f"snap_asof_{as_of}.db"
    if not rewound.exists():
        s, d = sqlite3.connect(snap), sqlite3.connect(rewound)
        s.backup(d)
        s.close()
        d.execute("DELETE FROM message WHERE seq > ?", (as_of,))
        d.execute("DELETE FROM event WHERE seq > ?", (as_of,))
        d.commit()
        d.close()
    return rewound


def _where(pack: dict, mid: str) -> list[str]:
    hits = []
    if any(a.get("id") == mid for a in pack.get("asks_for_me") or []):
        hits.append("asks_for_me")
    for tv in pack.get("tickets") or []:
        tid = (tv.get("ticket") or {}).get("id")
        for key in ("for_you", "thread"):
            if any(isinstance(m, dict) and m.get("id") == mid for m in tv.get(key) or []):
                hits.append(f"{tid}.{key}")
    return hits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--budget", type=int, default=16000)
    ap.add_argument("--label", default="run")
    ap.add_argument("--as-of-seq", type=int, default=None)
    ap.add_argument("--seat", action="append", help="participant_id=key_message_id")
    ap.add_argument("--v8", default=str(Path(__file__).resolve().parents[1]))
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    os.environ["EDP8_CONTEXT_BUDGET_B"] = str(a.budget)

    from edp8 import bundles
    from edp8.board import Board
    from edp8.store import Store

    board = Board(Store(str(_snapshot(Path(a.v8), out, a.as_of_seq))))
    rows = []
    for spec in a.seat or DEFAULT_SEATS:
        pid, mid = spec.split("=", 1)
        p = board.store.get("participant", pid)
        full = board.context(p)
        bundles.get_client = lambda full=full: type("C", (), {"context": lambda self, ticket_id=None:
                                                              {"ok": True, "value": full}})()
        pack = bundles._context(bundles.ContextArgs())["value"]
        (out / a.label).mkdir(exist_ok=True)
        text = json.dumps(pack, indent=1, ensure_ascii=True, default=str)
        (out / a.label / f"{pid}.json").write_text(text, encoding="utf-8")
        where = _where(pack, mid)
        rows.append({"seat": pid, "key": mid, "budget": a.budget, "bytes": bundles._bytes(pack),
                     "in_pack": bool(where), "where": where})
    print(json.dumps(rows, indent=1))
    (out / f"{a.label}.result.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
