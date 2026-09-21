"""Tests for the S14 knowledge layer (design-d2c4f39fc6 §2-4): decision/claim/lesson/kglink
store roundtrips, record_decision's one-transaction replaces flip, and lookup's caps,
determinism and epic isolation."""

from __future__ import annotations

import pytest

from edp8 import knowledge
from edp8.board import Board, BoardError
from edp8.knowledge import ALWAYS_MAX_BYTES, EXCERPT_CHARS, MAX_BYTES, MAX_RECORDS
from edp8.schemas import (
    Claim,
    ClaimBasis,
    Decision,
    DecisionStatus,
    DocType,
    KgLink,
    Lesson,
    LinkKind,
    Role,
    TicketKind,
    WorkType,
)
from edp8.store import Store, new_id


@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def rig(board):
    return {
        "owner": board.participant_create("human", Role.owner, "own1"),
        "architect": board.participant_create("agent", Role.architect, "arch1"),
        "engineer": board.participant_create("agent", Role.engineer, "eng1"),
    }


def make_epic(board, rig, title="Epic one"):
    return board.ticket_create(rig["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title=title)


# --------------------------------------------------------------------------- store roundtrips
def test_record_types_roundtrip():
    s = Store(":memory:")
    d = Decision(id=new_id("dec"), scope="epic-x", text="use sqlite", detail="a graph db adds a server")
    c = Claim(id=new_id("clm"), scope="epic-x", text="fastembed helps", basis=ClaimBasis.assumption)
    le = Lesson(id=new_id("les"), domain="operations", topic="restart", text="never taskkill by image")
    lk = KgLink(id=new_id("kl"), from_id=d.id, to_id="m-1", kind=LinkKind.came_from)
    for t, o in (("decision", d), ("claim", c), ("lesson", le), ("kglink", lk)):
        s.put(t, o)
        assert s.get(t, o.id) == o
    # indexed-column filters work
    assert s.query("decision", {"status": "live"})[0].id == d.id
    assert s.query("lesson", {"domain": "operations"})[0].id == le.id
    assert s.query("kglink", {"kind": "came_from"})[0].id == lk.id
    s.close()


def test_decision_fts_searchable():
    s = Store(":memory:")
    d = Decision(id=new_id("dec"), scope="epic-x", text="builders run on opus", detail="high tier for costly work")
    s.put("decision", d)
    hits = s.fts_search("opus", types={"decision"})
    assert [h["id"] for h in hits] == [d.id]
    s.close()


def test_decision_indexes_detail_not_text_alone():
    # R2-2: FTS (and the embed input, which is _fts_text) index text PLUS detail, so a question
    # answered only by the WHY/TRIGGER/EFFECT lines still seeds. Words + the trigger source id that
    # appear ONLY in detail must be searchable.
    s = Store(":memory:")
    d = Decision(id=new_id("dec"), scope="epic-x", text="adopt session resume",
                 detail="WHY: seats lose context on respawn. TRIGGER: owner ruling m-6ffe756cf7. "
                        "EFFECT: the pool fork-resumes done rows.")
    s.put("decision", d)
    assert d.id in [h["id"] for h in s.fts_search("respawn", types={"decision"})]
    assert d.id in [h["id"] for h in s.fts_search("m-6ffe756cf7", types={"decision"})]
    assert "respawn" in s._fts_text("decision", d.model_dump(mode="json"))  # the embed input carries detail
    s.close()


# --------------------------------------------------------------------------- record_decision
def test_record_decision_replaces_flips_in_one_transaction(board, rig):
    epic = make_epic(board, rig)
    old = board.record_decision(rig["owner"], scope=epic.id, text="any https host is accepted")
    new = board.record_decision(rig["owner"], scope=epic.id, text="allow-list hosts only",
                                replaces=[old.id])
    assert board.store.get("decision", old.id).status == DecisionStatus.replaced
    assert board.store.get("decision", new.id).status == DecisionStatus.live
    # a replaces kglink was written
    links = board.store.query("kglink", {"from_id": new.id, "kind": "replaces"})
    assert [lk.to_id for lk in links] == [old.id]


def test_record_decision_unknown_replaces_rolls_back(board, rig):
    epic = make_epic(board, rig)
    with pytest.raises(BoardError):
        board.record_decision(rig["owner"], scope=epic.id, text="x", replaces=["dec-nope"])
    # nothing persisted (atomic rollback)
    assert board.store.query("decision") == []


def test_record_decision_text_cap_rejected(board, rig):
    epic = make_epic(board, rig)
    with pytest.raises(Exception):
        board.record_decision(rig["owner"], scope=epic.id, text="x" * 241)


def test_record_claim_source_link(board, rig):
    epic = make_epic(board, rig)
    c = board.record_claim(rig["engineer"], scope=epic.id, text="ram is the bottleneck",
                           basis=ClaimBasis.measured, evidence=["c-1"], source="m-9")
    assert board.store.query("kglink", {"from_id": c.id, "kind": "came_from"})[0].to_id == "m-9"
    assert board.store.query("kglink", {"from_id": c.id, "kind": "proves"})[0].to_id == "c-1"


# --------------------------------------------------------------------------- lookup
def test_lookup_binding_always_included_and_confirmed(board, rig):
    epic = make_epic(board, rig)
    b = board.record_decision(rig["owner"], scope=epic.id, text="UI must match revision3 renders",
                              binding=True)
    out = board.lookup(rig["engineer"], scope=epic.id, question="anything unrelated")
    ids = [r["id"] for r in out["records"]]
    assert b.id in ids
    rec = next(r for r in out["records"] if r["id"] == b.id)
    assert rec["binding"] and rec["confirmed"]
    assert out["receipt"]["binding"] == 1


def test_lookup_claim_confirmed_label(board, rig):
    epic = make_epic(board, rig)
    board.record_claim(rig["engineer"], scope=epic.id, text="measured fact", basis=ClaimBasis.measured,
                       evidence=["c-1"])
    board.record_claim(rig["engineer"], scope=epic.id, text="bare guess", basis=ClaimBasis.assumption)
    out = board.lookup(rig["engineer"], scope=epic.id, question="fact guess measured")
    by_text = {r["text"]: r for r in out["records"]}
    assert by_text["measured fact"]["confirmed"] is True
    assert by_text["bare guess"]["confirmed"] is False


def test_lookup_isolation_between_epics(board, rig):
    epic_a = make_epic(board, rig, "Epic A")
    epic_b = make_epic(board, rig, "Epic B")
    da = board.record_decision(rig["owner"], scope=epic_a.id, text="epic A only rule about webhooks")
    db = board.record_decision(rig["owner"], scope=epic_b.id, text="epic B only rule about webhooks")
    out_a = board.lookup(rig["engineer"], scope=epic_a.id, question="webhooks rule")
    ids_a = [r["id"] for r in out_a["records"]]
    assert da.id in ids_a
    assert db.id not in ids_a


def test_lookup_lessons_cross_epic(board, rig):
    epic_a = make_epic(board, rig, "Epic A")
    epic_b = make_epic(board, rig, "Epic B")
    les = Lesson(id=new_id("les"), domain="operations", topic="webhooks",
                 text="allow-list webhook hosts", created_by=rig["architect"].id)
    board.store.put("lesson", les)
    # a lookup in epic B still finds the lesson by its words, though it is filed nowhere
    out_b = board.lookup(rig["engineer"], scope=epic_b.id, question="webhook hosts allow-list")
    assert les.id in [r["id"] for r in out_b["records"]]


def test_lookup_replaced_never_returned(board, rig):
    epic = make_epic(board, rig)
    old = board.record_decision(rig["owner"], scope=epic.id, text="old webhook rule")
    board.record_decision(rig["owner"], scope=epic.id, text="new webhook rule", replaces=[old.id])
    out = board.lookup(rig["engineer"], scope=epic.id, question="webhook rule")
    assert old.id not in [r["id"] for r in out["records"]]


def test_lookup_is_deterministic(board, rig):
    epic = make_epic(board, rig)
    for i in range(10):
        board.record_decision(rig["owner"], scope=epic.id, text=f"rule number {i} about webhooks")
    a = board.lookup(rig["engineer"], scope=epic.id, question="webhooks rule")
    b = board.lookup(rig["engineer"], scope=epic.id, question="webhooks rule")
    assert [r["id"] for r in a["records"]] == [r["id"] for r in b["records"]]


def test_lookup_caps_records_and_bytes(board, rig):
    epic = make_epic(board, rig)
    binder = board.record_decision(rig["owner"], scope=epic.id, text="binding rule kept", binding=True)
    for i in range(60):
        board.record_decision(rig["owner"], scope=epic.id,
                              text=f"rule {i} " + "webhooks host allow echo " * 6)
    out = board.lookup(rig["engineer"], scope=epic.id, question="webhooks host allow")
    assert len(out["records"]) <= MAX_RECORDS
    assert out["receipt"]["bytes"] <= MAX_BYTES
    # the binding decision is never cut
    assert binder.id in [r["id"] for r in out["records"]]


# --------------------------------------------------------------------------- consult-driven fixes
def test_unresolved_scope_isolates_to_nothing(board, rig):
    # P1: a garbage/unknown scope must NOT fall back to unrestricted (which leaked every epic).
    epic = make_epic(board, rig)
    board.record_decision(rig["owner"], scope=epic.id, text="binding thing", binding=True)
    out = board.lookup(rig["engineer"], scope="typo-not-an-epic", question="thing")
    assert out["records"] == []
    assert out["receipt"]["epic"] is None


def test_lessons_still_found_under_unresolved_scope(board, rig):
    # lessons are cross-epic; an unresolved scope still finds them (they are filed nowhere).
    les = Lesson(id=new_id("les"), domain="ops", topic="x", text="a reusable ops lesson about caches",
                 created_by=rig["architect"].id)
    board.store.put("lesson", les)
    out = board.lookup(rig["engineer"], scope="typo", question="ops cache lesson")
    assert les.id in [r["id"] for r in out["records"]]


def test_must_follow_edge_forces_non_binding_decision(board, rig):
    # P1 §4.2 step 1: a must_follow edge protects a non-binding decision from cuts + always includes it.
    epic = make_epic(board, rig)
    anchor = board.record_decision(rig["owner"], scope=epic.id, text="anchor binding", binding=True)
    target = board.record_decision(rig["owner"], scope=epic.id, text="not flagged binding but must-follow")
    board.store.put("kglink", KgLink(id=new_id("kl"), from_id=anchor.id, to_id=target.id,
                                     kind=LinkKind.must_follow, created_by=rig["owner"].id))
    out = board.lookup(rig["engineer"], scope=epic.id, question="something totally unrelated")
    assert target.id in [r["id"] for r in out["records"]]


def test_lookup_by_ticket_id_finds_its_decisions(board, rig):
    # P1: record_decision writes a `decides` edge to its scope, so lookup(id=ticket) connects.
    epic = make_epic(board, rig)
    story = board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title="a story", parent_id=epic.id)
    d = board.record_decision(rig["engineer"], scope=story.id, text="a decision made on the story")
    out = board.lookup(rig["engineer"], scope=story.id, id=story.id)
    assert d.id in [r["id"] for r in out["records"]]


def test_records_payload_within_byte_budget(board, rig):
    # P2: the cap is measured against the serialized records payload, not just a render.
    # (R2-5: a record only ranks if the question reaches it — the epic hub no longer bridges
    # every decision — so link the 80 into the ranked neighbourhood to exercise the Section-B cut.)
    import json
    epic = make_epic(board, rig)
    anchor = board.record_decision(rig["owner"], scope=epic.id, text="anchor about webhooks hosts allow")
    for i in range(80):
        d = board.record_decision(rig["owner"], scope=epic.id,
                                  text=f"rule {i} about webhooks and hosts and allow lists and echoes number {i}",
                                  detail="a long detail sentence " * 20)
        board.store.put("kglink", KgLink(id=new_id("kl"), from_id=anchor.id, to_id=d.id,
                                         kind=LinkKind.implements, created_by=rig["owner"].id))
    out = board.lookup(rig["engineer"], scope=epic.id, question="webhooks hosts allow")
    payload = len(json.dumps(out["records"], ensure_ascii=False).encode("utf-8"))
    assert payload <= MAX_BYTES, payload
    assert out["receipt"]["cut_by_type"], "expected some records cut"
    assert out["receipt"]["cut_ids"], "receipt must name what was cut"


def test_negative_lesson_counter_rejected():
    import pytest as _pytest
    with _pytest.raises(Exception):
        Lesson(id=new_id("les"), domain="d", topic="t", text="x", helped=-1)


# --------------------------------------------------------------------------- R2-6 seeding recall
def test_lookup_receipt_reports_seeding_backend(board, rig):
    epic = make_epic(board, rig)
    board.record_decision(rig["owner"], scope=epic.id, text="a rule about caches")
    out = board.lookup(rig["engineer"], scope=epic.id, question="caches")
    assert out["receipt"]["seed_top"] == 8
    assert out["receipt"]["embeddings"]["embedder"] == "none"  # no semantic index in the unit fixture


def test_embedder_ram_guard_falls_back_to_fts(monkeypatch):
    from edp8 import search
    monkeypatch.delenv("EDP8_EMBEDDER", raising=False)  # reach the auto→fastembed guard branch
    monkeypatch.setattr(search, "_free_ram_gb", lambda: 0.5)
    emb = search.make_embedder(ram_floor=1.5)  # must NOT load the model when RAM is tight
    assert emb.name == "none"
    assert "low_ram" in (emb.fallback_reason or "")


class _StubModel:
    def __init__(self):
        self.calls = []

    def embed(self, docs, batch_size=256, **_):
        self.calls.append((list(docs), batch_size))
        return [[1.0, 0.0] for _ in docs]


def _stub_fastembed(search):
    emb = search.FastEmbedEmbedder.__new__(search.FastEmbedEmbedder)  # skip the model load
    emb._model = _StubModel()
    return emb


def test_fastembed_calls_are_bounded(monkeypatch):
    """Host-crash regression (2026-09-21): never hand the model a big batch or an unbounded text."""
    from edp8 import search
    monkeypatch.setattr(search, "_free_ram_gb", lambda: 8.0)
    emb = _stub_fastembed(search)
    vecs = emb.embed(["x" * 50_000] * 20)
    assert len(vecs) == 20
    for docs, batch_size in emb._model.calls:
        assert len(docs) <= search.EMBED_BATCH and batch_size == search.EMBED_BATCH
        assert all(len(d) <= search.EMBED_MAX_CHARS + len("search_document: ") for d in docs)


def test_fastembed_aborts_mid_embed_when_ram_tightens(monkeypatch):
    from edp8 import search
    free = iter([8.0, 0.5])
    monkeypatch.setattr(search, "_free_ram_gb", lambda: next(free))
    emb = _stub_fastembed(search)
    idx = search.Index(embedder=emb)
    idx.rebuild([("doc", str(i), "cache rule") for i in range(search.EMBED_BATCH * 2)])
    assert len(emb._model.calls) == 1  # stopped before the second batch
    assert idx._dense_matrix is None and "low_ram mid-embed" in emb.fallback_reason
    assert idx.search("cache")  # FTS still answers


def test_bulk_reindex_warms_in_background_then_embeds_only_deltas(monkeypatch):
    from edp8 import search
    monkeypatch.setattr(search, "_free_ram_gb", lambda: 8.0)
    emb = _stub_fastembed(search)
    idx = search.Index(embedder=emb)
    n = search.BULK_THRESHOLD * 3
    idx.rebuild([("doc", str(i), f"cache rule {i}") for i in range(n)])  # returns without embedding inline
    idx._warm_thread.join(timeout=10)
    st = idx.status()
    assert st["warming"] is False and st["embeddings_active"] is True
    assert len(idx._dense_keys) == n
    emb._model.calls.clear()
    idx.upsert("doc", "new", "one new message")
    idx.search("message")
    embedded = [d for docs, _ in emb._model.calls for d in docs if d.startswith("search_document")]
    assert embedded == ["search_document: one new message"]  # not the whole corpus again
    assert len(idx._dense_keys) == n + 1


def test_vector_cache_roundtrip(tmp_path):
    from edp8.search import VectorCache, _text_hash
    vc = VectorCache(str(tmp_path / "vec.db"))
    vc.put_many([(_text_hash("alpha"), [0.1, 0.2, 0.3]), (_text_hash("beta"), [0.4, 0.5, 0.6])])
    assert vc.count() == 2
    got = vc.get_many([_text_hash("alpha"), _text_hash("missing")])
    assert _text_hash("missing") not in got
    assert got[_text_hash("alpha")] == pytest.approx([0.1, 0.2, 0.3], abs=1e-6)
    vc.close()
    # a fresh handle onto the same file still sees the rows (persistence)
    assert VectorCache(str(tmp_path / "vec.db")).count() == 2


def test_persisted_vectors_survive_restart_without_reembedding(monkeypatch, tmp_path):
    # Follow-up to ffb0476: a board restart must NOT re-embed the whole corpus. With a disk cache,
    # the second Index hydrates every vector by text hash and embeds no documents at all.
    from edp8 import search
    monkeypatch.setattr(search, "_free_ram_gb", lambda: 8.0)
    cache_path = str(tmp_path / "vec.db")
    units = [("doc", str(i), f"cache rule {i}") for i in range(search.BULK_THRESHOLD * 3)]

    first = search.Index(embedder=_stub_fastembed(search), cache=search.VectorCache(cache_path))
    first.rebuild(units)
    first._warm_thread.join(timeout=10)
    assert first.status()["embeddings_active"] is True
    assert search.VectorCache(cache_path).count() == len(units)  # every unit persisted

    emb2 = _stub_fastembed(search)
    second = search.Index(embedder=emb2, cache=search.VectorCache(cache_path))
    second.rebuild(units)  # same corpus, warm restart
    if second._warm_thread is not None:
        second._warm_thread.join(timeout=10)
    doc_embeds = [d for docs, _ in emb2._model.calls for d in docs if d.startswith("search_document")]
    assert doc_embeds == []  # nothing re-embedded — all served from the disk cache
    assert len(second._dense_keys) == len(units)  # dense matrix is fully populated from cache
    assert second.search("cache rule 1")  # and search works


def test_edited_unit_reembeds_and_persists(monkeypatch, tmp_path):
    from edp8 import search
    monkeypatch.setattr(search, "_free_ram_gb", lambda: 8.0)
    cache_path = str(tmp_path / "vec.db")
    emb = _stub_fastembed(search)
    idx = search.Index(embedder=emb, cache=search.VectorCache(cache_path))
    idx.rebuild([("doc", "1", "original text")])
    idx.search("original")  # inline embed of the single unit
    idx.upsert("doc", "1", "edited text")  # new content hash -> a re-embed
    idx.search("edited")
    embedded = [d for docs, _ in emb._model.calls for d in docs if d.startswith("search_document")]
    assert "search_document: edited text" in embedded
    assert search.VectorCache(cache_path).count() == 2  # both the original and the edited vector


def test_reembed_embeds_missing_units_inline(monkeypatch):
    from edp8 import search
    monkeypatch.setattr(search, "_free_ram_gb", lambda: 8.0)
    emb = _stub_fastembed(search)
    idx = search.Index(embedder=emb)
    idx.upsert("decision", "1", "a rule")   # marks dirty, no embed yet
    idx.upsert("decision", "2", "another rule")
    st = idx.reembed()
    assert st["missing"] == 0 and st["embedded_now"] == 2
    assert idx.embedded_ids("decision") == {"1", "2"}


def test_reembed_bulk_warms_in_background(monkeypatch):
    from edp8 import search
    monkeypatch.setattr(search, "_free_ram_gb", lambda: 8.0)
    emb = _stub_fastembed(search)
    idx = search.Index(embedder=emb)
    for i in range(search.BULK_THRESHOLD * 2):
        idx.upsert("decision", str(i), f"rule {i}")
    st = idx.reembed()
    assert st["warming"] is True
    idx._warm_thread.join(timeout=10)
    assert len(idx.embedded_ids("decision")) == search.BULK_THRESHOLD * 2


def test_reembed_none_embedder_is_noop():
    from edp8.search import Index, NullEmbedder
    idx = Index(embedder=NullEmbedder(fallback_reason="EDP8_EMBEDDER=none"))
    idx.upsert("decision", "1", "x")
    st = idx.reembed()
    assert st["embedder"] == "none" and st["warming"] is False


def test_embed_counts_per_epic(monkeypatch, rig):
    from edp8 import search
    from edp8.board import Board
    from edp8.store import Store
    monkeypatch.setattr(search, "_free_ram_gb", lambda: 8.0)
    b = Board(Store(":memory:"), search.Index(embedder=_stub_fastembed(search)))
    owner = b.participant_create("human", Role.owner, "o2")
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    d1 = b.record_decision(owner, scope=epic.id, text="rule one about hosts")
    d2 = b.record_decision(owner, scope=epic.id, text="rule two about hosts")
    gone = b.record_decision(owner, scope=epic.id, text="mistaken rule")
    b.withdraw_decision(owner, decision_id=gone.id, reason="oops")
    b.reembed()
    counts = b.embed_counts(epic.id)
    assert counts["epic"] == epic.id
    assert counts["decision"]["live"] == 2  # the withdrawn one is not live
    assert counts["decision"]["embedded"] == 2 and counts["decision"]["unembedded"] == 0
    assert {d1.id, d2.id} == b.index.embedded_ids("decision") & {d1.id, d2.id}


class _FakeTE:
    def __init__(self, model_name, **kwargs):
        self.model_name = model_name
        self.kwargs = kwargs


class _FakeTENoKwargs:
    def __init__(self, model_name, **kwargs):
        if kwargs:
            raise TypeError("this build does not accept session kwargs")
        self.model_name = model_name


def _inject_fake_fastembed(monkeypatch, cls):
    # Inject a fake `fastembed` module so FastEmbedEmbedder's `from fastembed import TextEmbedding`
    # binds the fake — this never loads the real model or onnxruntime (hard rule: no model in tests).
    import sys
    import types
    fake = types.ModuleType("fastembed")
    fake.TextEmbedding = cls
    monkeypatch.setitem(sys.modules, "fastembed", fake)


def test_fastembed_passes_arena_off_and_thread_cap(monkeypatch):
    # Board resident-cost fix (m-e5133ef308): the ONNX memory arena is turned OFF and threads capped.
    from edp8 import search
    _inject_fake_fastembed(monkeypatch, _FakeTE)
    emb = search.FastEmbedEmbedder()
    assert emb._model.kwargs["enable_cpu_mem_arena"] is False
    assert emb._model.kwargs["threads"] == search.EMBED_THREADS
    assert emb._model.model_name == search.EMBED_MODEL


def test_fastembed_falls_back_when_kwargs_unsupported(monkeypatch):
    from edp8 import search
    _inject_fake_fastembed(monkeypatch, _FakeTENoKwargs)
    emb = search.FastEmbedEmbedder()  # must not raise — plain construction fallback
    assert emb._model.model_name == search.EMBED_MODEL


def test_status_reports_embed_config_for_fastembed(monkeypatch):
    from edp8 import search
    idx = search.Index(embedder=_stub_fastembed(search))
    st = idx.status()
    assert st["embedder"] == "fastembed"
    assert st["arena"] == search.EMBED_ARENA and st["threads"] == search.EMBED_THREADS
    assert st["model"] == search.EMBED_MODEL


def test_embedder_forced_none_has_reason(monkeypatch):
    from edp8 import search
    monkeypatch.setenv("EDP8_EMBEDDER", "none")
    emb = search.make_embedder()
    assert emb.name == "none" and emb.fallback_reason == "EDP8_EMBEDDER=none"


def test_index_status_shape_without_model():
    from edp8.search import Index, NullEmbedder
    idx = Index(embedder=NullEmbedder(fallback_reason="EDP8_EMBEDDER=none"))
    st = idx.status()
    assert st["embedder"] == "none" and st["embeddings_active"] is False
    assert st["reason"] == "EDP8_EMBEDDER=none"


# --------------------------------------------------------------------------- R2-7 source fallback
def test_source_fallback_quotes_epic_docs_when_sparse(board, rig):
    epic = make_epic(board, rig)
    board.doc_create(rig["architect"], doc_type=DocType.note, scope=epic.id, title="ux notes",
                     body_md="Relocation-only roles are hidden behind a toggle in the filter rail.")
    out = board.lookup(rig["engineer"], scope=epic.id, question="relocation only roles hidden toggle")
    assert out["receipt"]["source_excerpts"] >= 1
    assert out["receipt"]["strong_records"] < 3  # the fallback only fires when curated recall is thin
    exc = [r for r in out["records"] if r.get("section") == "excerpt"]
    assert exc and exc[0]["type"] == "doc"
    assert exc[0]["author"] and exc[0]["date"] and len(exc[0]["text"]) <= EXCERPT_CHARS
    assert "Unconfirmed source excerpts" in out["body"]


def test_source_fallback_suppressed_when_enough_strong_records(board, rig):
    epic = make_epic(board, rig)
    board.doc_create(rig["architect"], doc_type=DocType.note, scope=epic.id, title="notes",
                     body_md="webhooks allow-list hosts and cadence")
    for i in range(3):
        board.record_decision(rig["owner"], scope=epic.id, text=f"webhooks allow-list rule {i} for hosts")
    out = board.lookup(rig["engineer"], scope=epic.id, question="webhooks allow-list hosts")
    assert out["receipt"]["strong_records"] >= 3
    assert out["receipt"]["source_excerpts"] == 0
    assert "Unconfirmed source excerpts" not in out["body"]


def test_source_excerpts_are_epic_scoped(board, rig):
    epic_a = make_epic(board, rig, "A")
    epic_b = make_epic(board, rig, "B")
    board.doc_create(rig["architect"], doc_type=DocType.note, scope=epic_b.id, title="b notes",
                     body_md="the escrow slots settle at close in epic B only")
    out = board.lookup(rig["engineer"], scope=epic_a.id, question="escrow slots settle close")
    assert out["receipt"]["source_excerpts"] == 0  # never leaks epic B's sources into epic A


# --------------------------------------------------------------------------- C4 ranked noise floor
def test_ranked_floor_drops_below_threshold_record(board, rig):
    epic = make_epic(board, rig)
    hit = board.record_decision(rig["owner"], scope=epic.id,
                                text="webhooks allowlist hosts rule is the strong direct match")
    # weak: never seeded by the question; reached only via a 0.3 `touches` edge from the hit,
    # so its score is 0.3x the top and it sits below the 0.35 floor.
    weak = board.record_decision(rig["owner"], scope=epic.id,
                                 text="standup cadence timing note unrelated to the query")
    board.store.put("kglink", KgLink(id=new_id("kl"), from_id=hit.id, to_id=weak.id,
                                     kind=LinkKind.touches, created_by=rig["owner"].id))
    out = board.lookup(rig["engineer"], scope=epic.id, question="webhooks allowlist hosts")
    ids = [r["id"] for r in out["records"]]
    assert hit.id in ids
    assert weak.id not in ids
    assert out["receipt"]["floor_dropped"] >= 1
    assert weak.id in out["receipt"]["floor_dropped_ids"]


def test_ranked_floor_rescues_part_of_linked_record(board, rig):
    epic = make_epic(board, rig)
    hit = board.record_decision(rig["owner"], scope=epic.id,
                                text="webhooks allowlist hosts rule is the strong direct match")
    weak = board.record_decision(rig["owner"], scope=epic.id,
                                 text="a minor sub-point that only makes sense beside the hit")
    # part_of both pulls `weak` into the neighbourhood (0.3) AND rescues it from the floor,
    # because it links to a kept (strong) record.
    board.store.put("kglink", KgLink(id=new_id("kl"), from_id=weak.id, to_id=hit.id,
                                     kind=LinkKind.part_of, created_by=rig["owner"].id))
    out = board.lookup(rig["engineer"], scope=epic.id, question="webhooks allowlist hosts")
    ids = [r["id"] for r in out["records"]]
    assert hit.id in ids
    assert weak.id in ids  # rescued by part_of despite being below the raw floor
    assert weak.id not in out["receipt"]["floor_dropped_ids"]


def test_ranked_floor_disabled_keeps_weak_record(board, rig, monkeypatch):
    monkeypatch.setattr(knowledge, "RANKED_FLOOR_FRAC", 0.0)
    epic = make_epic(board, rig)
    hit = board.record_decision(rig["owner"], scope=epic.id,
                                text="webhooks allowlist hosts rule is the strong direct match")
    weak = board.record_decision(rig["owner"], scope=epic.id,
                                 text="standup cadence timing note unrelated to the query")
    board.store.put("kglink", KgLink(id=new_id("kl"), from_id=hit.id, to_id=weak.id,
                                     kind=LinkKind.touches, created_by=rig["owner"].id))
    out = board.lookup(rig["engineer"], scope=epic.id, question="webhooks allowlist hosts")
    ids = [r["id"] for r in out["records"]]
    assert weak.id in ids  # floor off (A/B baseline) => nothing dropped
    assert out["receipt"]["floor_dropped"] == 0


# --------------------------------------------------------------------------- R2-6 seed_kind honesty
def test_seed_kind_reports_dense_when_embeddings_active(board, rig):
    epic = make_epic(board, rig)
    board.record_decision(rig["owner"], scope=epic.id, text="webhooks allowlist hosts rule")
    out = knowledge.lookup(board.store, epic.id, question="webhooks allowlist hosts",
                           semantic=lambda q: [], embed_status={"embeddings_active": True})
    assert out["receipt"]["seed_kind"] == "fts+dense"


def test_seed_kind_reports_fts_when_embeddings_inactive(board, rig):
    epic = make_epic(board, rig)
    board.record_decision(rig["owner"], scope=epic.id, text="webhooks allowlist hosts rule")
    # embedder present but not active (e.g. RAM fallback) => the receipt must not claim dense
    out = knowledge.lookup(board.store, epic.id, question="webhooks allowlist hosts",
                           semantic=lambda q: [], embed_status={"embeddings_active": False, "reason": "low RAM"})
    assert out["receipt"]["seed_kind"] == "fts"
    out2 = knowledge.lookup(board.store, epic.id, question="webhooks allowlist hosts",
                            semantic=None, embed_status=None)
    assert out2["receipt"]["seed_kind"] == "fts"


# --------------------------------------------------------------------------- withdraw (ruling m-7baa527b65)
def test_withdraw_decision_hides_it_but_keeps_row_and_links(board, rig):
    epic = make_epic(board, rig)
    d = board.record_decision(rig["owner"], scope=epic.id, text="a mistaken rule about webhooks")
    # present before withdrawal
    assert d.id in [r["id"] for r in board.lookup(rig["engineer"], scope=epic.id, question="webhooks rule")["records"]]
    assert board.store.fts_search("webhooks", types={"decision"})

    w = board.withdraw_decision(rig["owner"], decision_id=d.id, reason="duplicate from resume-script bug")
    assert w.status == DecisionStatus.withdrawn
    assert w.withdrawn_reason == "duplicate from resume-script bug"
    # the row and its `decides` kglink are kept
    assert board.store.get("decision", d.id) is not None
    assert board.store.query("kglink", {"from_id": d.id, "kind": "decides"})
    # lookup never returns it, and search drops it
    assert d.id not in [r["id"] for r in board.lookup(rig["engineer"], scope=epic.id, question="webhooks rule")["records"]]
    assert d.id not in [h["id"] for h in board.store.fts_search("webhooks", types={"decision"})]


def test_withdraw_binding_decision_not_force_included(board, rig):
    # a withdrawn binding decision must not sneak back via the always-include set
    epic = make_epic(board, rig)
    b = board.record_decision(rig["owner"], scope=epic.id, text="binding but retracted", binding=True)
    board.withdraw_decision(rig["owner"], decision_id=b.id, reason="entered in error")
    out = board.lookup(rig["engineer"], scope=epic.id, question="anything")
    assert b.id not in [r["id"] for r in out["records"]]
    assert out["receipt"]["binding"] == 0


def test_withdraw_unknown_decision_raises(board, rig):
    with pytest.raises(BoardError):
        board.withdraw_decision(rig["owner"], decision_id="dec-nope", reason="x")


# --------------------------------------------------------------------------- R2-1 history inline
def test_lookup_renders_replaced_chain_inline(board, rig):
    epic = make_epic(board, rig)
    a = board.record_decision(rig["owner"], scope=epic.id, text="first: use OAuth via Google login")
    b = board.record_decision(rig["owner"], scope=epic.id, text="second: use OAuth via GitHub login",
                              replaces=[a.id])
    c = board.record_decision(rig["owner"], scope=epic.id, text="third: use email magic links for login",
                              replaces=[b.id])
    out = board.lookup(rig["engineer"], scope=epic.id, question="login OAuth email magic")
    ids = [r["id"] for r in out["records"]]
    assert c.id in ids
    assert a.id not in ids and b.id not in ids  # replaced records never rank on their own
    rec_c = next(r for r in out["records"] if r["id"] == c.id)
    assert [h["id"] for h in rec_c["history"]] == [b.id, a.id]  # whole chain, newest-first
    assert "earlier: first: use OAuth via Google login (replaced " in out["body"]


# --------------------------------------------------------------------------- R2-5 two-section budget
def test_always_section_is_text_only_and_capped_and_trims_by_score(board, rig):
    epic = make_epic(board, rig)
    for i in range(40):
        board.record_decision(rig["owner"], scope=epic.id,
                              text=f"binding rule {i:02d} every seat must follow this host allow policy line",
                              detail="WHY: a long reason that must never appear in the always section " * 3,
                              binding=True)
    out = board.lookup(rig["engineer"], scope=epic.id, question="totally unrelated question")
    r = out["receipt"]
    assert r["always_bytes"] <= ALWAYS_MAX_BYTES
    assert r["binding_trimmed"], "binding text over the 2000-byte reserve must be trimmed by score"
    assert r["mandatory_overflow"] is True
    always = [x for x in out["records"] if x.get("section") == "always"]
    assert always and all("detail" not in x for x in always)  # text only, never detail
    assert "Always applies" in out["body"]


def test_binding_detail_only_when_it_also_ranks(board, rig):
    epic = make_epic(board, rig)
    ranked = board.record_decision(rig["owner"], scope=epic.id,
                                   text="binding webhook allowlist rule for hosts",
                                   detail="WHY: security; only allow-listed hosts", binding=True)
    other = board.record_decision(rig["owner"], scope=epic.id,
                                  text="binding standup cadence rule", detail="WHY: ops rhythm", binding=True)
    out = board.lookup(rig["engineer"], scope=epic.id, question="webhook allowlist hosts")
    always = {x["id"] for x in out["records"] if x.get("section") == "always"}
    assert ranked.id in always and other.id in always  # both must-follow, text-only up top
    ranked_sec = {x["id"]: x for x in out["records"] if x.get("section") == "ranked"}
    assert ranked.id in ranked_sec and ranked_sec[ranked.id]["detail"]  # detail only where it ranks
    assert other.id not in ranked_sec  # unrelated binding does not bridge in via the epic hub
    assert "Always applies" in out["body"] and "For your question" in out["body"]
