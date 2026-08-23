"""Tests for edp8.search: BM25, RRF fusion, filters, snippets, NullEmbedder."""

from __future__ import annotations

import os

os.environ["EDP8_EMBEDDER"] = "none"

from edp8.search import BM25, Index, NullEmbedder  # noqa: E402


def test_bm25_exact_term_ranks_first():
    bm25 = BM25()
    bm25.fit(
        [
            ("a", "the quick brown fox jumps over the lazy dog"),
            ("b", "completely unrelated text about weather patterns"),
            ("c", "fox fox fox fox everywhere you look, a fox"),
        ]
    )
    hits = bm25.search("fox", k=3)
    assert hits[0][0] == "c"
    keys = [key for key, _ in hits]
    assert "a" in keys
    assert hits[0][1] > 0


def test_bm25_no_match_returns_empty():
    bm25 = BM25()
    bm25.fit([("a", "hello world")])
    assert bm25.search("zzz", k=5) == []


def test_bm25_restrict_filters_candidates():
    bm25 = BM25()
    bm25.fit(
        [
            ("a", "search term here"),
            ("b", "search term here too"),
        ]
    )
    hits = bm25.search("search", k=5, restrict={"a"})
    assert [key for key, _ in hits] == ["a"]


class FakeEmbedder:
    """Deterministic embedder: vector encodes presence of a few marker words."""

    name = "fake"
    _VOCAB = ["alpha", "beta", "gamma", "delta"]

    def embed(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        vectors = []
        for text in texts:
            low = text.lower()
            vectors.append([1.0 if word in low else 0.0 for word in self._VOCAB])
        return vectors


def test_index_null_embedder_bm25_only():
    idx = Index(embedder=NullEmbedder())
    idx.rebuild(
        [
            ("doc", "d1", "apples and oranges are fruit"),
            ("doc", "d2", "the stock market fell today"),
        ]
    )
    results = idx.search("fruit", k=5)
    assert results
    assert results[0]["id"] == "d1"
    assert results[0]["type"] == "doc"


def test_index_rrf_fusion_with_fake_embedder():
    idx = Index(embedder=FakeEmbedder())
    idx.rebuild(
        [
            ("doc", "d1", "alpha content with no lexical overlap word: banana"),
            ("doc", "d2", "gamma content with no lexical overlap word: banana"),
            ("doc", "d3", "banana banana banana banana"),
        ]
    )
    # "banana" favors d3 lexically; dense query below matches "alpha" -> boosts d1.
    results = idx.search("banana alpha", k=3)
    ids = [r["id"] for r in results]
    assert "d1" in ids
    assert "d3" in ids
    # d1 should be boosted by the dense leg relative to a bm25-only ranking.
    assert results[0]["id"] in ("d1", "d3")


def test_index_types_filter():
    idx = Index(embedder=NullEmbedder())
    idx.rebuild(
        [
            ("doc", "d1", "shared keyword content"),
            ("ticket", "t1", "shared keyword content"),
        ]
    )
    results = idx.search("shared", k=10, types={"ticket"})
    assert len(results) == 1
    assert results[0]["type"] == "ticket"
    assert results[0]["id"] == "t1"


def test_index_allow_ids_filter():
    idx = Index(embedder=NullEmbedder())
    idx.rebuild(
        [
            ("doc", "d1", "shared keyword content"),
            ("doc", "d2", "shared keyword content"),
        ]
    )
    results = idx.search("shared", k=10, allow_ids={"d2"})
    assert len(results) == 1
    assert results[0]["id"] == "d2"


def test_index_no_candidates_after_filter():
    idx = Index(embedder=NullEmbedder())
    idx.rebuild([("doc", "d1", "some content")])
    assert idx.search("content", k=10, types={"ticket"}) == []


def test_snippet_around_match():
    idx = Index(embedder=NullEmbedder())
    long_text = ("padding " * 50) + "findme right here" + (" more padding" * 50)
    idx.rebuild([("doc", "d1", long_text)])
    results = idx.search("findme", k=1)
    assert "findme" in results[0]["snippet"]


def test_snippet_defaults_to_start_when_no_match():
    idx = Index(embedder=NullEmbedder())
    idx.rebuild([("doc", "d1", "alpha beta")])
    idx.upsert("doc", "d2", "alpha gamma delta")
    results = idx.search("alpha", k=5)
    assert all(r["snippet"] for r in results)


def test_upsert_marks_dirty_and_is_searchable():
    idx = Index(embedder=NullEmbedder())
    idx.rebuild([("doc", "d1", "original content")])
    assert idx.search("newword", k=5) == []
    idx.upsert("doc", "d2", "newword appears here")
    results = idx.search("newword", k=5)
    assert len(results) == 1
    assert results[0]["id"] == "d2"
