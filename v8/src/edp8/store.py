"""edp8 store — sqlite persistence for the ten objects.

One table per object type, JSON body + indexed columns that queries need. Doc
versions are kept in `doc_versions`. Writes are serialized by sqlite; the store
is process-local and the service is the single writer.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from collections.abc import Callable, Iterator
import re
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .schemas import OBJECT_TYPES, Doc, Event, Obj

# S18 T2: sha256 of the source this process executed, taken as the module loads (edp8.rsi reads it)
SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

_INDEXED: dict[str, list[str]] = {
    "participant": ["role", "handle"],
    "ticket": ["kind", "work_type", "parent_id", "status", "assignee", "created_by", "epic_id"],
    "criterion": ["ticket_id", "verdict", "checked_by"],
    "doc": ["doc_type", "scope", "owner_role"],
    "link": ["from_id", "to_id", "relation"],
    "message": ["ticket_id", "to", "kind", "reply_to", "created_by"],
    "event": ["subject_id", "kind"],
    "artifact": ["form"],
    "session": ["participant_id", "ticket_id", "pool_id", "state"],
    "decision": ["scope", "status", "source"],
    "claim": ["scope", "status", "basis"],
    "lesson": ["domain", "topic", "status"],
    "kglink": ["from_id", "to_id", "kind"],
    # RSI phase 1 (report-9a85d0418e §7): written only by edp8.rsi
    "policy": ["status", "parent"],
    "rsi_run": ["verdict", "trigger", "started_at"],
    "rsi_state": [],
}


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _dump(m: BaseModel) -> str:
    return m.model_dump_json()


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._lock = threading.RLock()
        self._transaction_depth = 0
        self._after_commit: list[Callable[[], None]] = []
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL") if self.path != ":memory:" else None
        self._init()

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[None]:
        """Nest writes in one atomic unit; publish notifications only after durable commit.
        `immediate=True` takes SQLite's write lock (BEGIN IMMEDIATE) before the body runs, so a
        read-check-write body is serialised against other connections too, not only this Store."""
        with self._lock:
            outer = self._transaction_depth == 0
            self._transaction_depth += 1
            try:
                if outer and immediate and not self._conn.in_transaction:
                    self._conn.execute("BEGIN IMMEDIATE")
                yield
                if outer:
                    self._conn.commit()
            except BaseException:
                if outer:
                    self._conn.rollback()
                    self._after_commit.clear()
                raise
            finally:
                self._transaction_depth -= 1
            callbacks = []
            if outer:
                callbacks, self._after_commit = self._after_commit, []
        # Board callbacks take the Board lock. Never invert Board -> Store ordering.
        for callback in callbacks:
            callback()

    def after_commit(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if self._transaction_depth:
                self._after_commit.append(callback)
                return
        callback()

    # ------------------------------------------------------------------ schema
    def _init(self) -> None:
        with self._lock, self._conn:
            for t, cols in _INDEXED.items():
                extra = "".join(f', "{c}" TEXT' for c in cols)
                self._conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {t} (id TEXT PRIMARY KEY, seq INTEGER, "
                    f"created_at TEXT, body TEXT NOT NULL{extra})"
                )
                # columns added since the table was created (2026-09-06: created_by/epic_id/
                # checked_by) — MUST land before any index on them: SQLite silently accepts
                # CREATE INDEX ON t("missing") as an index on a string constant, and the later
                # ALTER ADD COLUMN then corrupts the file ("database disk image is malformed")
                self._migrate_columns(t, cols)
                for c in cols:
                    self._conn.execute(f'CREATE INDEX IF NOT EXISTS ix_{t}_{c} ON {t}("{c}")')
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS doc_versions (doc_id TEXT, version INTEGER, body TEXT, "
                "PRIMARY KEY(doc_id, version))"
            )
            self._conn.execute("CREATE TABLE IF NOT EXISTS seq (name TEXT PRIMARY KEY, n INTEGER)")
            # RSI §7: at most one incumbent policy, enforced by the DB (not only by edp8.rsi)
            self._conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_policy_incumbent ON policy("status") '
                               "WHERE status='incumbent'")
            self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(type UNINDEXED, id UNINDEXED, text)")
            if self._conn.execute("SELECT count(*) FROM fts").fetchone()[0] == 0:
                self._fts_rebuild_locked()
            self.migrated_reviewer = self._migrate_reviewer_locked()

    # S-ROLES (s-a0c67e6aa7, owner m-bba708e10e): "reviewer" is no longer a role — qa checks stories.
    # (table, indexed column, JSON path) rows still naming it; migrated to qa at every open (idempotent).
    _REVIEWER_ROWS = (("participant", "role", "$.role"), ("criterion", "checked_by", "$.checked_by"),
                      ("doc", "owner_role", "$.owner_role"))

    def _migrate_reviewer_locked(self) -> dict[str, int]:
        """Rewrite every stored reviewer participant / reviewer-checked criterion / reviewer-owned doc
        to qa, body and index column together, so an old board loads under the reviewer-less Role
        enum. Returns the count per table (all 0 on a migrated board); the service logs it."""
        counts: dict[str, int] = {}
        for t, col, path in self._REVIEWER_ROWS:
            cur = self._conn.execute(
                f"UPDATE {t} SET \"{col}\"='qa', body=json_set(body, '{path}', 'qa') WHERE \"{col}\"='reviewer'")
            counts[t] = cur.rowcount
        cur = self._conn.execute(
            "UPDATE doc_versions SET body=json_set(body, '$.owner_role', 'qa') "
            "WHERE json_extract(body, '$.owner_role')='reviewer'")
        counts["doc_versions"] = cur.rowcount
        return counts

    def _migrate_columns(self, t: str, cols: list[str]) -> None:
        """A new indexed column on an existing table: ALTER + backfill from the JSON body,
        so old boards keep working unchanged."""
        have = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({t})")}
        for c in cols:
            if c in have:
                continue
            self._conn.execute(f'ALTER TABLE {t} ADD COLUMN "{c}" TEXT')
            self._conn.execute(f"UPDATE {t} SET \"{c}\"=json_extract(body, '$.{c}')")

    # ------------------------------------------------------------------ full text (FTS5)
    @staticmethod
    def _fts_text(type_: str, d: dict[str, Any]) -> str | None:
        if type_ == "ticket":
            # ruling #32: an epic's verbatim `words` stay searchable now that its title is short
            return "\n".join([d.get("title") or "", d.get("words") or "", d.get("description") or "",
                              " ".join(d.get("tags") or [])])
        if type_ == "doc":
            return f"{d.get('title') or ''}\n{d.get('body_md') or ''}"
        if type_ == "message":
            return d.get("text") or ""
        if type_ == "criterion":
            return d.get("text") or ""
        if type_ == "decision":
            if d.get("status") == "withdrawn":
                return ""  # withdrawn: keep the row + links, drop it from search (design §3 status)
            return f"{d.get('text') or ''}\n{d.get('detail') or ''}"
        if type_ == "claim":
            if d.get("status") == "withdrawn":
                return ""  # withdrawn: keep the row + links, drop it from search (mirrors decision)
            return d.get("text") or ""
        if type_ == "lesson":
            return "\n".join([d.get("text") or "", d.get("topic") or "", d.get("domain") or ""])
        return None

    def _fts_put_locked(self, type_: str, id_: str, text: str) -> None:
        self._conn.execute("DELETE FROM fts WHERE type=? AND id=?", (type_, id_))
        self._conn.execute("INSERT INTO fts(type, id, text) VALUES (?,?,?)", (type_, id_, text))

    def _fts_rebuild_locked(self) -> None:
        self._conn.execute("DELETE FROM fts")
        for t in ("ticket", "doc", "message", "criterion", "decision", "claim", "lesson"):
            for r in self._conn.execute(f"SELECT id, body FROM {t}"):
                text = self._fts_text(t, json.loads(r["body"]))
                if text:
                    self._conn.execute("INSERT INTO fts(type, id, text) VALUES (?,?,?)", (t, r["id"], text))

    @staticmethod
    def fts_query(q: str) -> str:
        """Plain words → a safe FTS5 query: every token quoted, OR-joined (ranking by bm25 sorts
        the fuller matches first); punctuation never reaches the FTS parser."""
        toks = [t for t in re.findall(r"[\w\-]+", q or "") if t]
        return " OR ".join(f'"{t}"' for t in toks)

    def fts_search(self, q: str, *, types: set[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Exact-word hits: [{type, id, snippet, rank}] best first."""
        match = self.fts_query(q)
        if not match:
            return []
        sql = "SELECT type, id, snippet(fts, 2, '[', ']', '…', 12) AS snip, bm25(fts) AS r FROM fts WHERE fts MATCH ?"
        args: list[Any] = [match]
        if types:
            sql += f" AND type IN ({','.join('?' for _ in types)})"
            args += sorted(types)
        sql += " ORDER BY r LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [{"type": r["type"], "id": r["id"], "snippet": r["snip"], "rank": i + 1} for i, r in enumerate(rows)]

    def _next_seq(self) -> int:
        row = self._conn.execute("SELECT n FROM seq WHERE name='global'").fetchone()
        n = (row["n"] if row else 0) + 1
        self._conn.execute("INSERT OR REPLACE INTO seq(name,n) VALUES('global',?)", (n,))
        return n

    # ------------------------------------------------------------------ generic CRUD
    def put(self, type_: str, obj: Obj) -> Obj:
        model = OBJECT_TYPES[type_]
        if not isinstance(obj, model):
            raise TypeError(f"{type_} expects {model.__name__}")
        cols = _INDEXED[type_]
        data = obj.model_dump(mode="json")
        with self.transaction():
            exists = self._conn.execute(f"SELECT 1 FROM {type_} WHERE id=?", (obj.id,)).fetchone()
            vals = [data.get(c) for c in cols]
            if exists:
                sets = ", ".join(f'"{c}"=?' for c in cols)
                self._conn.execute(
                    f"UPDATE {type_} SET body=?{', ' + sets if sets else ''} WHERE id=?",
                    [_dump(obj), *vals, obj.id],
                )
            else:
                seq = self._next_seq()
                names = ", ".join(["id", "seq", "created_at", "body", *(f'"{c}"' for c in cols)])
                qs = ", ".join("?" for _ in range(4 + len(cols)))
                self._conn.execute(
                    f"INSERT INTO {type_} ({names}) VALUES ({qs})",
                    [obj.id, seq, data["created_at"], _dump(obj), *vals],
                )
            if type_ == "doc":
                assert isinstance(obj, Doc)
                self._conn.execute(
                    "INSERT OR REPLACE INTO doc_versions(doc_id,version,body) VALUES(?,?,?)",
                    (obj.id, obj.version, _dump(obj)),
                )
            text = self._fts_text(type_, data)
            if text is not None:
                self._fts_put_locked(type_, obj.id, text)
        return obj

    def query_seq(self, type_: str, filters: dict[str, Any] | None = None, *, since_seq: int | None = None,
                  limit: int = 500, newest_first: bool = False, before_seq: int | None = None) -> list[tuple[int, Obj]]:
        """Like query(), with each row's global seq — so a caller can ask 'what is new since'.
        `newest_first=True` selects the LAST `limit` rows (ORDER BY seq DESC) — rows come back
        newest first; reverse for chronological display."""
        filters = {k: v for k, v in (filters or {}).items() if v is not None}
        cols = _INDEXED[type_]
        where, args = [], []
        for k, v in filters.items():
            if k not in cols:
                raise KeyError(f"{type_} cannot filter on {k!r}; indexed: {cols}")
            if isinstance(v, (list, tuple, set)):
                where.append(f'"{k}" IN ({",".join("?" for _ in v)})')
                args.extend(list(v))
            else:
                where.append(f'"{k}"=?')
                args.append(v)
        if since_seq is not None:
            where.append("seq>?")
            args.append(since_seq)
        if before_seq is not None:
            where.append("seq<?")
            args.append(before_seq)
        sql = f"SELECT seq, body FROM {type_}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY seq DESC LIMIT ?" if newest_first else " ORDER BY seq LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        model = OBJECT_TYPES[type_]
        return [(r["seq"], model.model_validate_json(r["body"])) for r in rows]

    def query_body_like(self, type_: str, needle: str, limit: int = 100000) -> list[tuple[int, Obj]]:
        """(seq, row) of `type_` whose JSON body contains `needle` literally, oldest first: a cheap
        prefilter for a field no column indexes (C18 doc comments); the caller filters exactly."""
        esc = needle.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        with self._lock:
            rows = self._conn.execute(f"SELECT seq, body FROM {type_} WHERE body LIKE ? ESCAPE '!' "
                                      "ORDER BY seq LIMIT ?", (f"%{esc}%", limit)).fetchall()
        model = OBJECT_TYPES[type_]
        return [(r["seq"], model.model_validate_json(r["body"])) for r in rows]

    def thread_count(self, ticket_id: str) -> int:
        """Full direct-source total without fetching/deserializing message bodies."""
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM message WHERE ticket_id=?", (ticket_id,)).fetchone()[0]

    def get(self, type_: str, id_: str) -> Obj | None:
        with self._lock:
            row = self._conn.execute(f"SELECT body FROM {type_} WHERE id=?", (id_,)).fetchone()
        return OBJECT_TYPES[type_].model_validate_json(row["body"]) if row else None

    def query(
        self,
        type_: str,
        filters: dict[str, Any] | None = None,
        *,
        since_seq: int | None = None,
        limit: int = 500,
        order: str = "seq",
        newest_first: bool = False,
    ) -> list[Obj]:
        """Rows of `type_` matching `filters` (a list/tuple/set value is an IN), oldest first.
        `limit` keeps the FIRST `limit` rows in `order`; `newest_first=True` flips the order to
        `seq DESC` so the LAST `limit` rows are kept (returned newest first — the caller reverses
        for chronological display). Adversary round 2 #5: a history window must keep the newest."""
        filters = {k: v for k, v in (filters or {}).items() if v is not None}
        cols = _INDEXED[type_]
        where, args = [], []
        for k, v in filters.items():
            if k not in cols:
                raise KeyError(f"{type_} cannot filter on {k!r}; indexed: {cols}")
            if isinstance(v, (list, tuple, set)):
                where.append(f'"{k}" IN ({",".join("?" for _ in v)})')
                args.extend(list(v))
            else:
                where.append(f'"{k}"=?')
                args.append(v)
        if since_seq is not None:
            where.append("seq>?")
            args.append(since_seq)
        sql = f"SELECT body FROM {type_}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY seq DESC LIMIT ?" if newest_first else f" ORDER BY {order} LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        model = OBJECT_TYPES[type_]
        return [model.model_validate_json(r["body"]) for r in rows]

    def delete(self, type_: str, id_: str) -> bool:
        with self.transaction():
            cur = self._conn.execute(f"DELETE FROM {type_} WHERE id=?", (id_,))
        return cur.rowcount > 0

    def seq_of(self, type_: str, id_: str) -> int | None:
        with self._lock:
            row = self._conn.execute(f"SELECT seq FROM {type_} WHERE id=?", (id_,)).fetchone()
        return row["seq"] if row else None

    def max_seq(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT n FROM seq WHERE name='global'").fetchone()
        return row["n"] if row else 0

    # ------------------------------------------------------------------ docs
    def doc_version(self, doc_id: str, version: int) -> Doc | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT body FROM doc_versions WHERE doc_id=? AND version=?", (doc_id, version)
            ).fetchone()
        return Doc.model_validate_json(row["body"]) if row else None

    def doc_versions(self, doc_id: str) -> list[int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT version FROM doc_versions WHERE doc_id=? ORDER BY version", (doc_id,)
            ).fetchall()
        return [r["version"] for r in rows]

    # ------------------------------------------------------------------ events
    def events_since(self, seq: int, limit: int = 200) -> list[tuple[int, Event]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, body FROM event WHERE seq>? ORDER BY seq LIMIT ?", (seq, limit)
            ).fetchall()
        return [(r["seq"], Event.model_validate_json(r["body"])) for r in rows]

    def events_before(self, seq: int | None, limit: int = 200) -> list[tuple[int, Event]]:
        """Events before seq (None = the newest), newest first — the tail reader's page."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, body FROM event WHERE (? IS NULL OR seq<?) ORDER BY seq DESC LIMIT ?",
                (seq, seq, limit),
            ).fetchall()
        return [(r["seq"], Event.model_validate_json(r["body"])) for r in rows]

    def all_text_units(self) -> list[tuple[str, str, str]]:
        """(type, id, text) for search indexing: docs (title+body), tickets (title), messages (text)."""
        out: list[tuple[str, str, str]] = []
        with self._lock:
            for r in self._conn.execute("SELECT id, body FROM doc"):
                d = json.loads(r["body"])
                out.append(("doc", r["id"], f"{d['title']}\n{d['body_md']}"))
            for r in self._conn.execute("SELECT id, body FROM ticket"):
                d = json.loads(r["body"])
                out.append(("ticket", r["id"], self._fts_text("ticket", d) or d["title"]))
            for r in self._conn.execute("SELECT id, body FROM message"):
                d = json.loads(r["body"])
                out.append(("message", r["id"], d["text"]))
            for r in self._conn.execute("SELECT id, body FROM criterion"):
                d = json.loads(r["body"])
                out.append(("criterion", r["id"], d["text"]))
            for t in ("decision", "claim", "lesson"):
                for r in self._conn.execute(f"SELECT id, body FROM {t}"):
                    text = self._fts_text(t, json.loads(r["body"]))
                    if text:
                        out.append((t, r["id"], text))
        return out

    def close(self) -> None:
        self._conn.close()


def iso(dt: datetime) -> str:
    return dt.isoformat()
