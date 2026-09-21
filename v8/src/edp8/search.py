"""edp8 search — BM25 lexical index + optional dense embeddings, fused via RRF.

Structure-first: `types`/`allow_ids` filter the candidate set before either leg
ranks it. One writer / many readers guarded by a single RLock.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import sqlite3
import threading
from collections import Counter
from typing import Iterable, Protocol

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]+")

RAM_FLOOR_GB = 1.5  # R2-6: below this free RAM at load, skip the embedding model, fall back to FTS
# Bound every ONNX call. fastembed's defaults (batch 256, padded to the longest text, nomic's 8192
# token window) make attention memory batch x heads x seq^2: a full-corpus reindex reached ~58 GB
# of commit and took the host down (2026-09-21). Small batch x capped length keeps a call ~100 MB.
EMBED_BATCH = 8
EMBED_MAX_TOKENS = 512
EMBED_MAX_CHARS = 2000  # char backstop in case the tokenizer cap cannot be applied
BULK_THRESHOLD = 32  # more un-embedded units than this -> embed in a background thread, FTS meanwhile
# Board resident cost (2026-09-21 owner order m-6fba97db17 / steer m-e5133ef308): onnxruntime's CPU
# memory arena pre-allocates and RETAINS a pool sized to the peak allocation, so the board's RSS
# stayed at ~2.2 GB long after a bounded warm. Turn the arena off (RSS then tracks live use, which
# after batch-8/512-token calls is small) and cap ORT threads (each op thread keeps its own arena).
# Vectors are byte-identical either way, so seed recall is unchanged.
EMBED_THREADS = int(os.environ.get("EDP8_EMBED_THREADS", "1"))
EMBED_ARENA = os.environ.get("EDP8_EMBED_ARENA", "0") == "1"  # default OFF
EMBED_MODEL = os.environ.get("EDP8_EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5")  # smaller model is a drop-in


def _free_ram_gb() -> float | None:
    """Available system RAM in GB, or None if it cannot be measured (guard then stays off)."""
    try:
        import psutil

        return psutil.virtual_memory().available / (1024**3)
    except Exception:
        return None


def _rss_mb() -> float | None:
    """This process's resident set size in MB, or None if it cannot be measured."""
    try:
        import psutil

        return psutil.Process().memory_info().rss / (1024**2)
    except Exception:
        return None


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop tokens shorter than 2 chars."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 2]


def _text_hash(text: str) -> str:
    """Content key for a vector: the sha256 of the exact text handed to the embedder. Identical
    text (across ids) shares one vector; an edit re-hashes and re-embeds."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class VectorCache:
    """Disk-persisted {text-hash -> vector}, so a board restart reuses embeddings instead of
    re-embedding the whole corpus (the ~520 s startup warm that followed ffb0476). One tiny SQLite
    file beside the board DB; keyed on content, not on (type,id), so a moved/duplicated unit is a
    cache hit. All access is under the Index lock, so a single shared connection is safe."""

    _SQLITE_VARS = 500  # keep IN(...) lists well under SQLite's 999-variable limit

    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS vec (hash TEXT PRIMARY KEY, dim INTEGER NOT NULL, vec BLOB NOT NULL)"
        )
        self._conn.commit()

    def get_many(self, hashes: Iterable[str]) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        hs = list(dict.fromkeys(hashes))  # de-dup, preserve order
        cur = self._conn.cursor()
        for i in range(0, len(hs), self._SQLITE_VARS):
            chunk = hs[i : i + self._SQLITE_VARS]
            q = f"SELECT hash, vec FROM vec WHERE hash IN ({','.join('?' * len(chunk))})"
            for h, blob in cur.execute(q, chunk):
                out[h] = np.frombuffer(blob, dtype=np.float32).tolist()
        return out

    def put_many(self, items: Iterable[tuple[str, list[float]]]) -> int:
        rows = [
            (h, len(v), np.asarray(v, dtype=np.float32).tobytes())
            for h, v in items
        ]
        if not rows:
            return 0
        self._conn.executemany("INSERT OR REPLACE INTO vec(hash, dim, vec) VALUES(?, ?, ?)", rows)
        self._conn.commit()
        return len(rows)

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM vec").fetchone()[0]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


class BM25:
    """Okapi BM25 over a fixed corpus of (key, text) documents."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._postings: dict[str, dict[str, int]] = {}
        self._df: dict[str, int] = {}
        self._doc_len: dict[str, int] = {}
        self._n = 0
        self._avgdl = 0.0

    def fit(self, docs: list[tuple[str, str]]) -> None:
        self._postings = {}
        self._df = {}
        self._doc_len = {}
        total_len = 0
        for key, text in docs:
            tokens = _tokenize(text)
            self._doc_len[key] = len(tokens)
            total_len += len(tokens)
            for term, tf in Counter(tokens).items():
                self._postings.setdefault(term, {})[key] = tf
                self._df[term] = self._df.get(term, 0) + 1
        self._n = len(docs)
        self._avgdl = total_len / self._n if self._n else 0.0

    def search(
        self, query: str, k: int = 10, restrict: set[str] | None = None
    ) -> list[tuple[str, float]]:
        if self._n == 0:
            return []
        avgdl = self._avgdl or 1.0
        scores: dict[str, float] = {}
        for term in _tokenize(query):
            postings = self._postings.get(term)
            if not postings:
                continue
            df = self._df[term]
            idf = math.log((self._n - df + 0.5) / (df + 0.5) + 1)
            for key, tf in postings.items():
                if restrict is not None and key not in restrict:
                    continue
                dl = self._doc_len[key]
                denom = tf + self.k1 * (1 - self.b + self.b * dl / avgdl)
                scores[key] = scores.get(key, 0.0) + idf * (tf * (self.k1 + 1)) / denom
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[:k]


class Embedder(Protocol):
    """Text -> dense vector; `is_query` picks the query/document prefix."""

    name: str

    def embed(self, texts: list[str], is_query: bool = False) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """Local ONNX embeddings via fastembed (nomic-embed-text-v1.5)."""

    name = "fastembed"
    fallback_reason: str | None = None

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        before = _rss_mb()
        # arena off + capped threads keep the board's idle RSS low (see EMBED_* notes). Fall back to a
        # plain construction if a fastembed build does not accept these kwargs, so the board never
        # fails to start over a memory tweak.
        try:
            self._model = TextEmbedding(model_name=EMBED_MODEL, threads=EMBED_THREADS,
                                        enable_cpu_mem_arena=EMBED_ARENA)
        except TypeError:
            self._model = TextEmbedding(model_name=EMBED_MODEL)
        self.model_name = EMBED_MODEL
        after = _rss_mb()
        # R2-6: report the model's resident footprint so a memory-tight host is legible
        self.resident_mb: float | None = round(after - before, 1) if (before and after) else after
        try:  # cap the sequence length at the tokenizer; EMBED_MAX_CHARS is the backstop
            self._model.model.tokenizer.enable_truncation(max_length=EMBED_MAX_TOKENS)
        except Exception:
            pass

    def embed(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        prefix = "search_query: " if is_query else "search_document: "
        docs = [prefix + t[:EMBED_MAX_CHARS] for t in texts]
        out: list[list[float]] = []
        for i in range(0, len(docs), EMBED_BATCH):
            # the load-time guard is not enough: re-check between batches so a tightening host
            # aborts the dense leg (callers fall back to FTS) instead of running into the pagefile
            free = _free_ram_gb()
            if free is not None and free < RAM_FLOOR_GB:
                self.fallback_reason = f"low_ram mid-embed: {free:.2f}GB free < {RAM_FLOOR_GB}GB floor"
                raise MemoryError(self.fallback_reason)
            chunk = docs[i : i + EMBED_BATCH]
            out.extend(list(v) for v in self._model.embed(chunk, batch_size=EMBED_BATCH))
        return out


class OllamaEmbedder:
    """Embeddings from a local Ollama server (nomic-embed-text)."""

    name = "ollama"

    def __init__(self, base: str | None = None) -> None:
        import httpx

        self._base = base or os.environ.get("EDP8_OLLAMA_URL", "http://127.0.0.1:11434")
        httpx.get(f"{self._base}/api/tags", timeout=1.0).raise_for_status()

    def embed(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        import httpx

        prefix = "search_query: " if is_query else "search_document: "
        out = []
        with httpx.Client(timeout=10.0) as client:
            for text in texts:
                r = client.post(
                    f"{self._base}/api/embeddings",
                    json={"model": "nomic-embed-text", "prompt": prefix + text},
                )
                r.raise_for_status()
                out.append(r.json()["embedding"])
        return out


class NullEmbedder:
    """No dense leg: signals callers to fall back to BM25-only search."""

    name = "none"

    def __init__(self, fallback_reason: str | None = None) -> None:
        self.fallback_reason = fallback_reason

    def embed(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        return []


def _load_fastembed(ram_floor: float) -> Embedder:
    """Load fastembed unless free RAM is below the floor (R2-6): a tight host stays on FTS
    rather than pay a multi-hundred-MB model load and risk an OOM on this shared machine."""
    free = _free_ram_gb()
    if free is not None and free < ram_floor:
        return NullEmbedder(fallback_reason=f"low_ram: {free:.2f}GB free < {ram_floor}GB floor")
    return FastEmbedEmbedder()


def make_embedder(ram_floor: float = RAM_FLOOR_GB) -> Embedder:
    """Pick an embedder: EDP8_EMBEDDER forces a choice, else fastembed->ollama->none. fastembed
    is skipped (FTS fallback) when free RAM is under `ram_floor` at load time."""
    forced = os.environ.get("EDP8_EMBEDDER")
    if forced == "fastembed":
        try:
            return _load_fastembed(ram_floor)
        except Exception as e:
            return NullEmbedder(fallback_reason=f"fastembed load failed: {e}")
    if forced == "ollama":
        try:
            return OllamaEmbedder()
        except Exception as e:
            return NullEmbedder(fallback_reason=f"ollama unavailable: {e}")
    if forced == "none":
        return NullEmbedder(fallback_reason="EDP8_EMBEDDER=none")
    try:
        return _load_fastembed(ram_floor)
    except Exception:
        pass
    try:
        return OllamaEmbedder()
    except Exception:
        pass
    return NullEmbedder(fallback_reason="no embedder available")


def _snippet(text: str, query: str, width: int = 200) -> str:
    """First `width` chars around the earliest matching query token, else the start."""
    lower = text.lower()
    best = -1
    for term in _tokenize(query):
        idx = lower.find(term)
        if idx != -1 and (best == -1 or idx < best):
            best = idx
    if best == -1:
        return text[:width]
    start = max(0, best - width // 2)
    return text[start : start + width]


def _key(type_: str, id_: str) -> str:
    return f"{type_}:{id_}"


class Index:
    """BM25 + optional dense vectors over edp8 text units, fused via RRF."""

    def __init__(self, embedder: Embedder | None = None, rrf_k: int = 60,
                 cache: VectorCache | None = None):
        self._embedder = embedder if embedder is not None else make_embedder()
        self._rrf_k = rrf_k
        self._cache = cache  # disk-persisted text-hash -> vec; None disables persistence
        self._lock = threading.RLock()
        self._bm25 = BM25()
        self._units: dict[str, tuple[str, str, str]] = {}
        self._dense_keys: list[str] = []
        self._dense_matrix: np.ndarray | None = None
        self._vecs: dict[str, tuple[str, list[float]]] = {}  # key -> (text it was embedded from, vec)
        self._warming = False
        self._warm_thread: threading.Thread | None = None
        self._dirty = True

    def rebuild(self, units: list[tuple[str, str, str]]) -> None:
        with self._lock:
            self._units = {_key(t, i): (t, i, txt) for t, i, txt in units}
            self._dirty = True
            self._reindex()

    def upsert(self, type_: str, id_: str, text: str) -> None:
        with self._lock:
            self._units[_key(type_, id_)] = (type_, id_, text)
            self._dirty = True

    def status(self) -> dict:
        """R2-6: which seeding backend is live, why (if it fell back), and the model's footprint."""
        emb = self._embedder
        on = emb.name != "none" and self._dense_matrix is not None
        cached = None
        if self._cache is not None:
            try:
                cached = self._cache.count()
            except Exception:
                cached = None
        st = {"embedder": emb.name, "embeddings_active": on, "warming": self._warming,
              "reason": getattr(emb, "fallback_reason", None),
              "model_mb": getattr(emb, "resident_mb", None),
              "cached_vectors": cached,
              "free_ram_gb": round(g, 2) if (g := _free_ram_gb()) is not None else None}
        if emb.name == "fastembed":  # so the receipt shows the resident-cost config in effect
            st.update({"model": getattr(emb, "model_name", EMBED_MODEL),
                       "arena": EMBED_ARENA, "threads": EMBED_THREADS})
        return st

    def _missing(self) -> list[tuple[str, str]]:
        """Units whose current text has no cached vector (new or edited)."""
        return [(key, txt) for key, (_, _, txt) in self._units.items()
                if self._vecs.get(key, (None, None))[0] != txt]

    def _hydrate_from_cache(self) -> None:
        """Fill the in-memory vector map from the disk cache (lock held): for every unit whose text
        is not already embedded, reuse a persisted vector matched by content hash. After this the
        startup warm only embeds units that were never seen before, so a restart is near-instant."""
        if self._cache is None:
            return
        want: dict[str, list[tuple[str, str]]] = {}
        for key, (_, _, txt) in self._units.items():
            if self._vecs.get(key, (None, None))[0] != txt:
                want.setdefault(_text_hash(txt), []).append((key, txt))
        if not want:
            return
        try:
            got = self._cache.get_many(want.keys())
        except Exception:
            return
        for h, pairs in want.items():
            vec = got.get(h)
            if vec is not None:
                for key, txt in pairs:
                    self._vecs[key] = (txt, vec)

    def _persist(self, pairs: list[tuple[str, str]], vecs: list[list[float]]) -> None:
        """Write freshly computed vectors to the disk cache, keyed by text hash (lock held)."""
        if self._cache is None or not vecs:
            return
        try:
            self._cache.put_many((_text_hash(txt), vec) for (_, txt), vec in zip(pairs, vecs))
        except Exception:
            pass  # persistence is best-effort; the in-memory map still serves this run

    def _build_matrix(self) -> None:
        """Dense matrix from the vector cache (lock held); units not embedded yet are FTS-only."""
        for key in [k for k in self._vecs if k not in self._units]:
            del self._vecs[key]
        keys = [key for key, (_, _, txt) in self._units.items()
                if self._vecs.get(key, (None, None))[0] == txt]
        self._dense_matrix = None
        self._dense_keys = []
        if keys:
            arr = np.array([self._vecs[k][1] for k in keys], dtype=float)
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self._dense_matrix = arr / norms
            self._dense_keys = keys

    def _warm(self) -> None:
        """Background bulk embed: chunks run OUTSIDE the lock so search stays live on FTS."""
        try:
            while True:
                with self._lock:
                    chunk = self._missing()[:BULK_THRESHOLD]
                if not chunk:
                    break
                vecs = self._embedder.embed([txt for _, txt in chunk], is_query=False)
                if len(vecs) != len(chunk):
                    break
                with self._lock:
                    for (key, txt), vec in zip(chunk, vecs):
                        self._vecs[key] = (txt, vec)
                    self._persist(chunk, vecs)
        except Exception:
            pass  # e.g. the mid-embed RAM guard: keep what is cached, stay FTS for the rest
        finally:
            with self._lock:
                self._warming = False
                self._build_matrix()

    def _reindex(self) -> None:
        docs = [(key, txt) for key, (_, _, txt) in self._units.items()]
        self._bm25.fit(docs)
        self._dirty = False
        if self._embedder.name == "none":
            self._dense_matrix, self._dense_keys = None, []
            return
        self._hydrate_from_cache()  # reuse persisted vectors before deciding what to embed
        if self._warming:
            return  # the warm thread picks up whatever is missing and rebuilds the matrix
        missing = self._missing()
        if len(missing) > BULK_THRESHOLD:
            # a bulk embed (startup: the whole corpus) must not block the caller or hold the lock
            self._warming = True
            self._warm_thread = threading.Thread(target=self._warm, name="edp8-embed-warm", daemon=True)
            self._warm_thread.start()
            return
        if missing:  # small delta (a new message): embed just that, inline
            try:
                vecs = self._embedder.embed([txt for _, txt in missing], is_query=False)
            except Exception:
                vecs = []
            if len(vecs) == len(missing):
                for (key, txt), vec in zip(missing, vecs):
                    self._vecs[key] = (txt, vec)
                self._persist(missing, vecs)
        self._build_matrix()

    def reembed(self) -> dict:
        """R2 item-3: embed every unit that lacks a current vector, via the SAME bounded path as a
        normal reindex (batch 8, 512-token cap, RAM re-check between batches). Safe to trigger anytime
        with no board restart — a bulk backlog warms in the background thread, a small delta embeds
        inline. Returns counts so the caller can report how many are still unembedded (e.g. after the
        RAM guard aborted a warm). This is the only sanctioned re-embed entry point (hard rule 4)."""
        with self._lock:
            if self._embedder.name == "none":
                return {"embedder": "none", "missing": len(self._missing()), "warming": False,
                        "reason": getattr(self._embedder, "fallback_reason", None)}
            self._hydrate_from_cache()
            missing = self._missing()
            if not missing:
                self._build_matrix()
                return {"embedder": self._embedder.name, "missing": 0, "warming": self._warming,
                        "embedded_now": 0}
            if self._warming:
                return {"embedder": self._embedder.name, "missing": len(missing), "warming": True}
            if len(missing) > BULK_THRESHOLD:
                self._warming = True
                self._warm_thread = threading.Thread(target=self._warm, name="edp8-embed-warm", daemon=True)
                self._warm_thread.start()
                return {"embedder": self._embedder.name, "missing": len(missing), "warming": True}
            try:
                vecs = self._embedder.embed([txt for _, txt in missing], is_query=False)
            except Exception as e:  # e.g. the mid-embed RAM guard: keep what is cached, report it
                self._build_matrix()
                return {"embedder": self._embedder.name, "missing": len(self._missing()),
                        "warming": False, "error": str(e)}
            if len(vecs) == len(missing):
                for (key, txt), vec in zip(missing, vecs):
                    self._vecs[key] = (txt, vec)
                self._persist(missing, vecs)
            self._build_matrix()
            return {"embedder": self._embedder.name, "missing": len(self._missing()),
                    "warming": False, "embedded_now": len(missing)}

    def embedded_ids(self, type_: str) -> set[str]:
        """The ids of `type_` that currently have a live vector in the dense matrix (R2 item-3
        embedded/unembedded accounting)."""
        with self._lock:
            keys = set(self._dense_keys)
            return {self._units[k][1] for k in keys if k in self._units and self._units[k][0] == type_}

    def search(
        self,
        query: str,
        k: int = 10,
        types: set[str] | None = None,
        allow_ids: set[str] | None = None,
    ) -> list[dict]:
        with self._lock:
            if self._dirty:
                self._reindex()
            candidates = set(self._units.keys())
            if types is not None:
                candidates = {k for k in candidates if self._units[k][0] in types}
            if allow_ids is not None:
                candidates = {k for k in candidates if self._units[k][1] in allow_ids}
            if not candidates:
                return []

            bm25_hits = self._bm25.search(query, k=len(candidates), restrict=candidates)
            bm25_rank = {key: rank for rank, (key, _) in enumerate(bm25_hits, start=1)}

            dense_rank: dict[str, int] = {}
            if self._dense_matrix is not None:
                try:
                    qvecs = self._embedder.embed([query], is_query=True)
                except Exception:
                    qvecs = []
                if qvecs:
                    qv = np.array(qvecs[0], dtype=float)
                    qn = np.linalg.norm(qv)
                    if qn > 0:
                        qv = qv / qn
                    sims = self._dense_matrix @ qv
                    scored = [
                        (key, float(sims[idx]))
                        for idx, key in enumerate(self._dense_keys)
                        if key in candidates
                    ]
                    scored.sort(key=lambda kv: kv[1], reverse=True)
                    dense_rank = {
                        key: rank for rank, (key, _) in enumerate(scored, start=1)
                    }

            fused: dict[str, float] = {}
            for key, rank in bm25_rank.items():
                fused[key] = fused.get(key, 0.0) + 1.0 / (self._rrf_k + rank)
            for key, rank in dense_rank.items():
                fused[key] = fused.get(key, 0.0) + 1.0 / (self._rrf_k + rank)

            ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
            results = []
            for key, score in ranked:
                t, i, text = self._units[key]
                snippet = _snippet(text, query)
                results.append({"type": t, "id": i, "score": score, "snippet": snippet})
            return results
