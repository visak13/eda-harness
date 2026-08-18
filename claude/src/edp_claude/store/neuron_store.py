"""Neuron DB — the unified specialization registry (vision 2026-05-22).

SQLite-backed. Decision #1: domain experts, comprehension checkers, AND
orchestration all live in ONE registry. Discovery is by description-
embedding cosine (`search`); the embedding is an INDEX artifact stored
as a BLOB column, never part of the public NeuronRecord. Mirrors the old
ADR-024/025 registry, evolved for branchable shells (base_session_id).

No LLM here — pure storage + cosine. Embeddings come from an EmbedPort
the caller owns (StubEmbed offline, ollama in prod).
"""

import math
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path

from ..schemas import NeuronRecord

_DDL = """
CREATE TABLE IF NOT EXISTS neurons (
    neuron_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    category        TEXT NOT NULL,
    status          TEXT NOT NULL,
    base_session_id TEXT,
    spec_id         TEXT,
    editable        INTEGER NOT NULL DEFAULT 1,
    use_count       INTEGER NOT NULL DEFAULT 0,
    flag_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    trained_at      TEXT,
    last_used_at    TEXT,
    embedding       BLOB
);
"""

# Validated lifecycle transitions (decision #3 gate). archived is terminal.
TRANSITIONS: dict[str, set[str]] = {
    "trained": {"pending_review", "archived"},
    "pending_review": {"stable", "trained", "archived"},  # changes → trained
    "stable": {"underused", "pending_review", "archived"},  # re-validate
    "underused": {"stable", "pending_review", "archived"},
    "archived": set(),
}

_COLS = (
    "neuron_id", "name", "description", "category", "status",
    "base_session_id", "spec_id", "editable", "use_count", "flag_count",
    "created_at", "updated_at", "trained_at", "last_used_at",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pack(vec: list[float] | None) -> bytes | None:
    return struct.pack(f"{len(vec)}f", *vec) if vec else None


def _unpack(blob: bytes | None) -> list[float] | None:
    if not blob:
        return None
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class NeuronStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the async server may touch the conn
        # from a worker thread; access is serialized by the event loop.
        self._conn = sqlite3.connect(
            str(self.db_path), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_DDL)
        self._conn.commit()

    def _to_record(self, row: sqlite3.Row) -> NeuronRecord:
        d = {k: row[k] for k in _COLS}
        d["editable"] = bool(d["editable"])
        return NeuronRecord.model_validate(d)

    def exists(self, neuron_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM neurons WHERE neuron_id=?", (neuron_id,)
        ).fetchone() is not None

    def create(
        self, rec: NeuronRecord, embedding: list[float] | None = None
    ) -> NeuronRecord:
        self._conn.execute(
            "INSERT INTO neurons "
            "(neuron_id,name,description,category,status,base_session_id,"
            "spec_id,editable,use_count,flag_count,created_at,updated_at,"
            "trained_at,last_used_at,embedding) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rec.neuron_id, rec.name, rec.description, rec.category,
                rec.status, rec.base_session_id, rec.spec_id,
                int(rec.editable), rec.use_count, rec.flag_count,
                rec.created_at.isoformat(), rec.updated_at.isoformat(),
                rec.trained_at.isoformat() if rec.trained_at else None,
                rec.last_used_at.isoformat() if rec.last_used_at else None,
                _pack(embedding),
            ),
        )
        self._conn.commit()
        return rec

    def get(self, neuron_id: str) -> NeuronRecord | None:
        row = self._conn.execute(
            "SELECT * FROM neurons WHERE neuron_id=?", (neuron_id,)
        ).fetchone()
        return self._to_record(row) if row else None

    def list(
        self, status: str | None = None, category: str | None = None
    ) -> list[NeuronRecord]:
        q, cond, args = "SELECT * FROM neurons", [], []
        if status:
            cond.append("status=?")
            args.append(status)
        if category:
            cond.append("category=?")
            args.append(category)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        rows = self._conn.execute(q, args).fetchall()
        return [self._to_record(r) for r in rows]

    def _set(self, neuron_id: str, **fields) -> NeuronRecord | None:
        if not self.exists(neuron_id):
            return None
        fields["updated_at"] = _now().isoformat()
        cols = ", ".join(f"{k}=?" for k in fields)
        self._conn.execute(
            f"UPDATE neurons SET {cols} WHERE neuron_id=?",
            (*fields.values(), neuron_id),
        )
        self._conn.commit()
        return self.get(neuron_id)

    def set_status(self, neuron_id: str, status: str,
                   force: bool = False) -> NeuronRecord | None:
        """F34 R2 #13 (2026-08-18): the transition is CONDITIONAL in SQL.
        `archived` is terminal — a shell holding a stale pre-archive read
        used to write its old status back afterward and silently resurrect
        the neuron. The WHERE clause makes that a no-op (the fresh record
        is returned either way; callers see the archive held). `force=True`
        is the explicit un-archive escape."""
        if not self.exists(neuron_id):
            return None
        if force or status == "archived":
            return self._set(neuron_id, status=status)
        self._conn.execute(
            "UPDATE neurons SET status=?, updated_at=? "
            "WHERE neuron_id=? AND status != 'archived'",
            (status, _now().isoformat(), neuron_id),
        )
        self._conn.commit()
        return self.get(neuron_id)

    def set_base_session(
        self, neuron_id: str, session_id: str
    ) -> NeuronRecord | None:
        # promoting a fork to base = the flow-back step (decision #2)
        return self._set(
            neuron_id, base_session_id=session_id,
            trained_at=_now().isoformat(),
        )

    def set_spec(self, neuron_id: str, spec_id: str) -> NeuronRecord | None:
        return self._set(neuron_id, spec_id=spec_id)

    def touch(self, neuron_id: str) -> NeuronRecord | None:
        # F34 R2 #13: increment IN SQL — two concurrent read-then-write
        # touches both wrote count+1 and lost one use, skewing the decay
        # flag-rate against healthy specialists.
        if not self.exists(neuron_id):
            return None
        now = _now().isoformat()
        self._conn.execute(
            "UPDATE neurons SET use_count = use_count + 1, "
            "last_used_at=?, updated_at=? WHERE neuron_id=?",
            (now, now, neuron_id),
        )
        self._conn.commit()
        return self.get(neuron_id)

    def flag(self, neuron_id: str) -> NeuronRecord | None:
        if not self.exists(neuron_id):
            return None
        self._conn.execute(
            "UPDATE neurons SET flag_count = flag_count + 1, updated_at=? "
            "WHERE neuron_id=?",
            (_now().isoformat(), neuron_id),
        )
        self._conn.commit()
        return self.get(neuron_id)

    def search(
        self, query_vec: list[float], top_k: int = 5,
        include_archived: bool = False,
    ) -> list[tuple[NeuronRecord, float]]:
        rows = self._conn.execute("SELECT * FROM neurons").fetchall()
        scored: list[tuple[NeuronRecord, float]] = []
        for r in rows:
            if not include_archived and r["status"] == "archived":
                continue
            scored.append(
                (self._to_record(r), cosine(query_vec, _unpack(r["embedding"])))
            )
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k]

    def search_text(
        self, query: str, top_k: int = 5, include_archived: bool = False,
    ) -> list[tuple[NeuronRecord, float]]:
        """Fallback when no embedding is available (ollama down): token
        overlap (Jaccard) over name+description. Same degradation
        philosophy as resolve_recipe's Jaccard floor."""
        qt = set(query.lower().split())
        rows = self._conn.execute("SELECT * FROM neurons").fetchall()
        scored: list[tuple[NeuronRecord, float]] = []
        for r in rows:
            if not include_archived and r["status"] == "archived":
                continue
            dt = set((r["name"] + " " + r["description"]).lower().split())
            inter = len(qt & dt)
            union = len(qt | dt) or 1
            scored.append((self._to_record(r), inter / union))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k]
