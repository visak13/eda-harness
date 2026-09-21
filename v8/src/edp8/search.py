"""edp8 search — BM25 lexical index + optional dense embeddings, fused via RRF.

Structure-first: `types`/`allow_ids` filter the candidate set before either leg
ranks it. One writer / many readers guarded by a single RLock.
"""

from __future__ import annotations

import math
import os
import re
import threading
from collections import Counter
from typing import Protocol

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]+")

RAM_FLOOR_GB = 1.5  # R2-6: below this free RAM at load, skip the embedding model, fall back to FTS


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
        self._model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1.5")
        after = _rss_mb()
        # R2-6: report the model's resident footprint so a memory-tight host is legible
        self.resident_mb: float | None = round(after - before, 1) if (before and after) else after

    def embed(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        prefix = "search_query: " if is_query else "search_document: "
        return [list(v) for v in self._model.embed([prefix + t for t in texts])]


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

    def __init__(self, embedder: Embedder | None = None, rrf_k: int = 60):
        self._embedder = embedder if embedder is not None else make_embedder()
        self._rrf_k = rrf_k
        self._lock = threading.RLock()
        self._bm25 = BM25()
        self._units: dict[str, tuple[str, str, str]] = {}
        self._dense_keys: list[str] = []
        self._dense_matrix: np.ndarray | None = None
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
        return {"embedder": emb.name, "embeddings_active": on,
                "reason": getattr(emb, "fallback_reason", None),
                "model_mb": getattr(emb, "resident_mb", None),
                "free_ram_gb": round(g, 2) if (g := _free_ram_gb()) is not None else None}

    def _reindex(self) -> None:
        docs = [(key, txt) for key, (_, _, txt) in self._units.items()]
        self._bm25.fit(docs)
        self._dense_matrix = None
        self._dense_keys = []
        if docs and self._embedder.name != "none":
            keys = [key for key, _ in docs]
            texts = [txt for _, txt in docs]
            try:
                vecs = self._embedder.embed(texts, is_query=False)
            except Exception:
                vecs = []
            if vecs:
                arr = np.array(vecs, dtype=float)
                norms = np.linalg.norm(arr, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                self._dense_matrix = arr / norms
                self._dense_keys = keys
        self._dirty = False

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
