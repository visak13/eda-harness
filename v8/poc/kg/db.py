"""SQLite schema for the knowledge-graph PoC (S13).

One file, three real tables plus an FTS5 mirror over node.text and a small
ingest-state table so re-runs are incremental. Node text is ONE sentence;
everything longer lives in source.excerpt.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("KG_DB", "C:/Projects/Learning/eda-base3/v8/.data/kg-poc/kg.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS node (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL,      -- problem|decision|design_part|check|ticket|evidence|lesson|module
    text          TEXT NOT NULL,      -- ONE sentence
    status        TEXT NOT NULL DEFAULT 'live',  -- live|replaced
    module        TEXT,               -- code path for module nodes / owning module for others
    source_id     TEXT,               -- -> source.id
    created_at    TEXT,               -- board/commit timestamp of the underlying object
    last_verified_at TEXT,            -- when this node was last confirmed current
    uses          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS edge (
    from_id    TEXT NOT NULL,
    to_id      TEXT NOT NULL,
    rel        TEXT NOT NULL,         -- part_of|decides|must_follow|verifies|proves|implements|touches|learned_from|replaces|came_from
    created_at TEXT,
    PRIMARY KEY (from_id, to_id, rel)
);

CREATE TABLE IF NOT EXISTS source (
    id      TEXT PRIMARY KEY,         -- kind:ref, e.g. message:m-xxx
    kind    TEXT NOT NULL,            -- message|ticket|criterion|doc|link|commit|artifact
    ref     TEXT NOT NULL,            -- the board/git id
    excerpt TEXT                      -- fuller text, kept but never loaded by default
);

-- incremental cursors: one row per stream (messages seq, git head, doc versions...)
CREATE TABLE IF NOT EXISTS ingest_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- live code state: latest commit time per module path (refreshed every ingest).
-- Staleness = module_head.head_at > node.last_verified_at, so a new commit
-- flags the touched nodes stale without bumping their verification time.
CREATE TABLE IF NOT EXISTS module_head (
    path    TEXT PRIMARY KEY,
    head_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edge_from ON edge(from_id, rel);
CREATE INDEX IF NOT EXISTS idx_edge_to   ON edge(to_id, rel);
CREATE INDEX IF NOT EXISTS idx_node_type ON node(type);
CREATE INDEX IF NOT EXISTS idx_node_module ON node(module);

-- keyword search leg: BM25 over node.text (no new dependency)
CREATE VIRTUAL TABLE IF NOT EXISTS node_fts USING fts5(
    text, id UNINDEXED, content='node', content_rowid='rowid'
);
"""

# keep the FTS mirror in step with node via triggers so ingest never has to
FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS node_ai AFTER INSERT ON node BEGIN
    INSERT INTO node_fts(rowid, text, id) VALUES (new.rowid, new.text, new.id);
END;
CREATE TRIGGER IF NOT EXISTS node_ad AFTER DELETE ON node BEGIN
    INSERT INTO node_fts(node_fts, rowid, text, id) VALUES ('delete', old.rowid, old.text, old.id);
END;
CREATE TRIGGER IF NOT EXISTS node_au AFTER UPDATE ON node BEGIN
    INSERT INTO node_fts(node_fts, rowid, text, id) VALUES ('delete', old.rowid, old.text, old.id);
    INSERT INTO node_fts(rowid, text, id) VALUES (new.rowid, new.text, new.id);
END;
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.executescript(FTS_TRIGGERS)
    conn.commit()
    return conn


def get_state(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM ingest_state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO ingest_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


if __name__ == "__main__":
    c = connect()
    print("schema ready at", DB_PATH)
    for t in ("node", "edge", "source"):
        n = c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n}")
