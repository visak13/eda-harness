"""Tests for edp8.store: put/get/query, filters incl. IN lists, quoted `to`
column on message, doc versions, events_since, seq monotonicity.
"""

from __future__ import annotations

import pytest

from edp8.schemas import (
    Doc,
    DocType,
    Event,
    EventKind,
    Message,
    MessageKind,
    Participant,
    Role,
    Ticket,
    TicketKind,
    TicketStatus,
    WorkType,
)
from edp8.store import Store, new_id


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def make_participant(role=Role.owner, handle="own1", id_=None):
    return Participant(id=id_ or new_id("p"), type="human", role=role, handle=handle)


def make_ticket(kind=TicketKind.epic, status=TicketStatus.drafted, id_=None, **kw):
    return Ticket(
        id=id_ or new_id("t"),
        kind=kind,
        work_type=WorkType.feature,
        title="a title",
        status=status,
        **kw,
    )


def test_put_get_roundtrip(store):
    p = make_participant()
    store.put("participant", p)
    got = store.get("participant", p.id)
    assert got == p


def test_get_missing_returns_none(store):
    assert store.get("participant", "nope") is None


def test_put_update_existing_row(store):
    t = make_ticket(status=TicketStatus.drafted)
    store.put("ticket", t)
    t.status = TicketStatus.designed
    store.put("ticket", t)
    got = store.get("ticket", t.id)
    assert got.status == TicketStatus.designed
    # still one row
    rows = store.query("ticket", {})
    assert sum(1 for x in rows if x.id == t.id) == 1


def test_put_wrong_type_raises(store):
    p = make_participant()
    with pytest.raises(TypeError):
        store.put("ticket", p)


def test_query_filters_by_indexed_column(store):
    t1 = make_ticket(kind=TicketKind.epic)
    t2 = make_ticket(kind=TicketKind.story, parent_id=t1.id)
    store.put("ticket", t1)
    store.put("ticket", t2)
    hits = store.query("ticket", {"kind": TicketKind.story})
    assert [h.id for h in hits] == [t2.id]


def test_query_unindexed_column_raises_keyerror(store):
    with pytest.raises(KeyError):
        store.query("ticket", {"title": "x"})


def test_query_in_list_filter(store):
    t1 = make_ticket(kind=TicketKind.story)
    t2 = make_ticket(kind=TicketKind.task, parent_id=t1.id)
    t3 = make_ticket(kind=TicketKind.epic)
    for t in (t1, t2, t3):
        store.put("ticket", t)
    hits = store.query("ticket", {"kind": [TicketKind.story, TicketKind.task]})
    ids = {h.id for h in hits}
    assert ids == {t1.id, t2.id}


def test_query_none_values_are_ignored(store):
    t1 = make_ticket()
    store.put("ticket", t1)
    hits = store.query("ticket", {"kind": None, "status": None})
    assert [h.id for h in hits] == [t1.id]


def test_query_message_to_quoted_column(store):
    """`to` is a SQL keyword-ish column name; must be quoted in DDL/DML."""
    m1 = Message(id=new_id("m"), ticket_id="t-1", to="p-1", kind=MessageKind.note, text="hi")
    m2 = Message(id=new_id("m"), ticket_id="t-1", to="p-2", kind=MessageKind.note, text="bye")
    store.put("message", m1)
    store.put("message", m2)
    hits = store.query("message", {"to": "p-1"})
    assert [h.id for h in hits] == [m1.id]


def test_query_message_to_none_thread_note(store):
    m1 = Message(id=new_id("m"), ticket_id="t-1", to=None, kind=MessageKind.status, text="update")
    store.put("message", m1)
    hits = store.query("message", {"ticket_id": "t-1"})
    assert [h.id for h in hits] == [m1.id]
    assert hits[0].to is None


def test_query_order_and_limit(store):
    for i in range(5):
        store.put("ticket", make_ticket())
    hits = store.query("ticket", {}, limit=2)
    assert len(hits) == 2


def test_delete(store):
    t = make_ticket()
    store.put("ticket", t)
    assert store.delete("ticket", t.id) is True
    assert store.get("ticket", t.id) is None
    assert store.delete("ticket", t.id) is False


def test_doc_versions_and_get_by_version(store):
    d = Doc(id=new_id("d"), doc_type=DocType.design, title="v1", body_md="body v1",
            owner_role=Role.architect, scope="epic-1")
    store.put("doc", d)
    d.title = "v2"
    d.body_md = "body v2"
    d.version = 2
    store.put("doc", d)
    assert store.doc_versions(d.id) == [1, 2]
    v1 = store.doc_version(d.id, 1)
    assert v1.title == "v1"
    assert v1.body_md == "body v1"
    v2 = store.doc_version(d.id, 2)
    assert v2.title == "v2"
    # current doc row reflects latest
    current = store.get("doc", d.id)
    assert current.version == 2
    assert current.title == "v2"


def test_doc_version_missing_returns_none(store):
    d = Doc(id=new_id("d"), doc_type=DocType.note, title="t", body_md="b",
            owner_role=Role.owner, scope="global")
    store.put("doc", d)
    assert store.doc_version(d.id, 99) is None


def test_events_since_and_ordering(store):
    for i in range(3):
        ev = Event(id=new_id("ev"), subject_id="s", kind=EventKind.status_changed, data={"i": i})
        store.put("event", ev)
    all_evs = store.events_since(0)
    assert [e.data["i"] for _, e in all_evs] == [0, 1, 2]
    later = store.events_since(all_evs[0][0])
    assert [e.data["i"] for _, e in later] == [1, 2]


def test_events_since_limit(store):
    for i in range(5):
        store.put("event", Event(id=new_id("ev"), subject_id="s", kind=EventKind.status_changed))
    hits = store.events_since(0, limit=2)
    assert len(hits) == 2


def test_seq_monotonic_across_types(store):
    """seq is a single global counter shared by every object type."""
    p = make_participant()
    t = make_ticket()
    store.put("participant", p)
    store.put("ticket", t)
    seq_p = store.seq_of("participant", p.id)
    seq_t = store.seq_of("ticket", t.id)
    assert seq_t == seq_p + 1
    assert store.max_seq() == seq_t


def test_seq_of_missing_is_none(store):
    assert store.seq_of("ticket", "nope") is None


def test_put_does_not_bump_seq_on_update(store):
    t = make_ticket()
    store.put("ticket", t)
    seq1 = store.seq_of("ticket", t.id)
    t.status = TicketStatus.designed
    store.put("ticket", t)
    seq2 = store.seq_of("ticket", t.id)
    assert seq1 == seq2


def test_all_text_units_includes_doc_ticket_message(store):
    d = Doc(id=new_id("d"), doc_type=DocType.note, title="Doc Title", body_md="doc body",
            owner_role=Role.owner, scope="global")
    t = make_ticket()
    m = Message(id=new_id("m"), ticket_id=t.id, to=None, kind=MessageKind.note, text="msg text")
    store.put("doc", d)
    store.put("ticket", t)
    store.put("message", m)
    units = store.all_text_units()
    kinds = {u[0] for u in units}
    assert kinds == {"doc", "ticket", "message"}
    doc_unit = next(u for u in units if u[0] == "doc")
    assert "Doc Title" in doc_unit[2] and "doc body" in doc_unit[2]
