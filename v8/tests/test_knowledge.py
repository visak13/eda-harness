"""Tests for the S14 knowledge layer (design-d2c4f39fc6 §2-4): decision/claim/lesson/kglink
store roundtrips, record_decision's one-transaction replaces flip, and lookup's caps,
determinism and epic isolation."""

from __future__ import annotations

import pytest

from edp8.board import Board, BoardError
from edp8.knowledge import MAX_BYTES, MAX_RECORDS
from edp8.schemas import (
    Claim,
    ClaimBasis,
    Decision,
    DecisionStatus,
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
    import json
    epic = make_epic(board, rig)
    for i in range(80):
        board.record_decision(rig["owner"], scope=epic.id,
                              text=f"rule {i} about webhooks and hosts and allow lists and echoes number {i}",
                              detail="a long detail sentence " * 20)
    out = board.lookup(rig["engineer"], scope=epic.id, question="webhooks hosts allow")
    payload = len(json.dumps(out["records"], ensure_ascii=False).encode("utf-8"))
    assert payload <= MAX_BYTES, payload
    assert out["receipt"]["cut_by_type"], "expected some records cut"
    assert out["receipt"]["cut_ids"], "receipt must name what was cut"


def test_negative_lesson_counter_rejected():
    import pytest as _pytest
    with _pytest.raises(Exception):
        Lesson(id=new_id("les"), domain="d", topic="t", text="x", helped=-1)
