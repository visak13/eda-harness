"""edp8 store — sqlite persistence for the ten objects.

One table per object type, JSON body + indexed columns that queries need. Doc
versions are kept in `doc_versions`. Writes are serialized by sqlite; the store
is process-local and the service is the single writer.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .schemas import OBJECT_TYPES, Doc, Event, Obj

_INDEXED: dict[str, list[str]] = {
    "participant": ["role", "handle"],
    "ticket": ["kind", "work_type", "parent_id", "status", "assignee"],
    "criterion": ["ticket_id", "verdict"],
    "doc": ["doc_type", "scope", "owner_role"],
    "link": ["from_id", "to_id", "relation"],
    "message": ["ticket_id", "to", "kind", "reply_to"],
    "event": ["subject_id", "kind"],
    "artifact": ["form"],
    "session": ["participant_id", "ticket_id", "pool_id", "state"],
}


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _dump(m: BaseModel) -> str:
    return m.model_dump_json()


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL") if self.path != ":memory:" else None
        self._init()

    # ------------------------------------------------------------------ schema
    def _init(self) -> None:
        with self._lock, self._conn:
            for t, cols in _INDEXED.items():
                extra = "".join(f', "{c}" TEXT' for c in cols)
                self._conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {t} (id TEXT PRIMARY KEY, seq INTEGER, "
                    f"created_at TEXT, body TEXT NOT NULL{extra})"
                )
                for c in cols:
                    self._conn.execute(f'CREATE INDEX IF NOT EXISTS ix_{t}_{c} ON {t}("{c}")')
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS doc_versions (doc_id TEXT, version INTEGER, body TEXT, "
                "PRIMARY KEY(doc_id, version))"
            )
            self._conn.execute("CREATE TABLE IF NOT EXISTS seq (name TEXT PRIMARY KEY, n INTEGER)")

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
        with self._lock, self._conn:
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
        return obj

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
    ) -> list[Obj]:
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
        sql += f" ORDER BY {order} LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        model = OBJECT_TYPES[type_]
        return [model.model_validate_json(r["body"]) for r in rows]

    def delete(self, type_: str, id_: str) -> bool:
        with self._lock, self._conn:
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

    def all_text_units(self) -> list[tuple[str, str, str]]:
        """(type, id, text) for search indexing: docs (title+body), tickets (title), messages (text)."""
        out: list[tuple[str, str, str]] = []
        with self._lock:
            for r in self._conn.execute("SELECT id, body FROM doc"):
                d = json.loads(r["body"])
                out.append(("doc", r["id"], f"{d['title']}\n{d['body_md']}"))
            for r in self._conn.execute("SELECT id, body FROM ticket"):
                d = json.loads(r["body"])
                out.append(("ticket", r["id"], d["title"]))
            for r in self._conn.execute("SELECT id, body FROM message"):
                d = json.loads(r["body"])
                out.append(("message", r["id"], d["text"]))
        return out

    def close(self) -> None:
        self._conn.close()


def iso(dt: datetime) -> str:
    return dt.isoformat()
