"""Freshness replay (S13 slice 5).

Demonstrates, on a COPY of kg.db (never the shared board or shared git tree),
that an INCREMENTAL update — one owner decision that replaces an older one, and
one new commit touching a module — makes walk() return the new decision and
never the replaced one, and flags the touched node stale, with NO rebuild.

Run: python poc/kg/freshness.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

import db
import walk
from ingest import add_edge, upsert_node, upsert_source

SRC = Path("C:/Projects/Learning/eda-base3/v8/.data/kg-poc/kg.db")
REPLAY = Path("C:/Projects/Learning/eda-base3/v8/.data/kg-poc/kg-replay.db")

SLACK_TICKET = "ticket:s-7f663c6322"
SLACK_MODULE = "module:src/edp8/slack_bridge.py"
OLD = "decision:replay-old-webhook"
NEW = "decision:replay-new-webhook"


def _is_stale(conn, nid):
    r = conn.execute("SELECT * FROM node WHERE id=?", (nid,)).fetchone()
    head = {x["path"]: x["head_at"] for x in conn.execute("SELECT path, head_at FROM module_head")}
    return walk._stale(conn, r, head)


def _status(conn, nid):
    r = conn.execute("SELECT status FROM node WHERE id=?", (nid,)).fetchone()
    return r["status"] if r else "absent"


def _in_walk(conn, start, nid):
    _, _, sel = walk.walk(start, conn=conn)
    return nid in sel


def seed_old_decision(conn):
    """Pre-state: an OLD live owner decision that any https host is allowed."""
    src = upsert_source(conn, "message", "replay-old", "owner: any https webhook host is accepted")
    upsert_node(conn, OLD, "decision", "The webhook may point to any https host.",
                source_id=src, created_at="2026-09-19T00:00:00Z")
    add_edge(conn, OLD, SLACK_TICKET, "decides", "2026-09-19T00:00:00Z")
    conn.commit()


def apply_new_events(conn):
    """Incremental: (1) a new owner decision replacing the old one; (2) a new
    commit touching src/edp8/slack_bridge.py. Only the changed rows are written."""
    # (1) replacing owner decision
    src = upsert_source(conn, "message", "replay-new",
                        "owner ruling: webhook host must be hooks.slack.com or operator-listed")
    upsert_node(conn, NEW, "decision",
                "The webhook host must be hooks.slack.com or an operator-listed host.",
                source_id=src, created_at="2026-09-21T20:00:00Z")
    add_edge(conn, NEW, SLACK_TICKET, "decides", "2026-09-21T20:00:00Z")
    conn.execute("UPDATE node SET status='replaced' WHERE id=?", (OLD,))
    add_edge(conn, NEW, OLD, "replaces", "2026-09-21T20:00:00Z")
    # (2) a new commit touching the slack module: advance its head past the
    #     module node's last_verified_at (no rebuild, no re-ingest of history)
    conn.execute(
        "INSERT INTO module_head(path, head_at) VALUES ('src/edp8/slack_bridge.py', ?) "
        "ON CONFLICT(path) DO UPDATE SET head_at=excluded.head_at",
        ("2026-09-21T23:59:00Z",),
    )
    conn.commit()


def main():
    if not SRC.exists():
        raise SystemExit("build kg.db first (python poc/kg/ingest.py)")
    shutil.copy(SRC, REPLAY)
    conn = db.connect(REPLAY)
    seed_old_decision(conn)

    print("== BEFORE new events ==")
    before = {
        "old status": _status(conn, OLD),
        "old in walk(slack ticket)": _in_walk(conn, "s-7f663c6322", OLD),
        "new present": _status(conn, NEW),
        "slack module stale": _is_stale(conn, SLACK_MODULE),
    }
    for k, v in before.items():
        print(f"   {k}: {v}")

    apply_new_events(conn)

    print("== AFTER incremental update (no rebuild) ==")
    after = {
        "old status": _status(conn, OLD),
        "old in walk(slack ticket)": _in_walk(conn, "s-7f663c6322", OLD),
        "new status": _status(conn, NEW),
        "new in walk(slack ticket)": _in_walk(conn, "s-7f663c6322", NEW),
        "slack module stale": _is_stale(conn, SLACK_MODULE),
    }
    for k, v in after.items():
        print(f"   {k}: {v}")

    ok = (after["old status"] == "replaced"
          and after["old in walk(slack ticket)"] is False
          and after["new status"] == "live"
          and after["new in walk(slack ticket)"] is True
          and before["slack module stale"] is False
          and after["slack module stale"] is True)
    print("\nFRESHNESS REPLAY:", "PASS" if ok else "FAIL")
    conn.close()
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
