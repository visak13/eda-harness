"""t-852e7add63 item 7: the one-off v34 cleanup report (owner m-8aa6439a77).

The v34 rule (Board.inbox: a plain status, a note or a finding never waits on a human; a later human message to the
asker clears an ask) resolves the pre-v34 stale items by itself, so no row is written. This script measures that
on a COPY of a board database (the live file is never opened for writing): per human and per scope, how many ask
items counted before v34 and how many count now, and which ids are still waiting (the owner can Dismiss them).

    .venv/Scripts/python.exe scripts/attention_v34_cleanup.py --db .data/edp8.db [--scope epic-…] [--json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from edp8.board import Board
from edp8.schemas import MessageKind, Participant
from edp8.store import Store

_PRE_V34_HUMAN_KINDS = [MessageKind.question, MessageKind.steer, MessageKind.status, MessageKind.finding,
                        MessageKind.deviation]


def _pre_v34_resolved(board: Board, m: Any) -> bool:
    """Board.ask_resolved as it stood before v34: dead agent author, a kind=answer reply, or the addressee's reply."""
    author = board.store.get("participant", m.created_by)
    if author is not None and author.type == "agent" and board.seat_state(m.created_by) == "dead":
        return True
    return any(r.kind == MessageKind.answer or board._is_addressee(r.created_by, m.to)
               for r in board.store.query("message", {"reply_to": m.id}, limit=200))


def pre_v34_ids(board: Board, p: Participant) -> list[str]:
    """The ask ids the pre-v34 inbox showed a human (direct address only; the role-address path is unchanged)."""
    rows = board.store.query("message", {"to": p.id, "kind": _PRE_V34_HUMAN_KINDS}, limit=100, newest_first=True)
    out = []
    for m in reversed(rows):
        if _pre_v34_resolved(board, m):
            continue
        tk = board.store.get("ticket", m.ticket_id)
        if tk is None or str(tk.status) == "dropped" or str(board.epic_of(tk).status) in ("done", "partial", "dropped"):
            continue
        out.append(m.id)
    return out


def report(board: Board, scope: str | None = None) -> dict[str, Any]:
    """Before/after counts per human (and per scope), plus the ids still waiting after v34."""
    rows = []
    for p in board.store.query("participant", {}, limit=100_000):
        if p.type != "human" or getattr(p, "retired", False):
            continue
        before = pre_v34_ids(board, p)
        after = [a["id"] for a in board.inbox(p)]
        if scope:
            before = [i for i in before if board._epic_id_of(board.store.get("message", i).ticket_id) == scope]
            after = [i for i in after if board._epic_id_of(board.store.get("message", i).ticket_id) == scope]
        if not before and not after:
            continue
        kinds_before = Counter(str(board.store.get("message", i).kind) for i in before)
        rows.append({"human": p.id, "before": len(before), "after": len(after),
                     "before_by_kind": dict(kinds_before), "resolved": sorted(set(before) - set(after)),
                     "still_waiting": after})
    return {"scope": scope, "humans": rows}


def _copy(db: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="attn-v34-")) / "copy.db"
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return tmp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--scope", help="an epic id: count only its asks")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    out = report(Board(Store(_copy(a.db))), a.scope)
    if a.json:
        print(json.dumps(out, indent=1))
        return 0
    print(f"| human | before (pre-v34) | after (v34) | before by kind | still waiting |{' scope ' + a.scope if a.scope else ''}")
    print("|---|---|---|---|---|")
    for r in out["humans"]:
        kinds = ", ".join(f"{n} {k}" for k, n in sorted(r["before_by_kind"].items(), key=lambda kv: -kv[1]))
        print(f"| {r['human']} | {r['before']} | {r['after']} | {kinds} | {' '.join(r['still_waiting']) or '-'} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
