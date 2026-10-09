"""e0cec S3 (owner R3, dec-49f1f6a911, design-b6a55eed13 §4.A): an ask to the owner clears structurally, never by
model judgement, and each settle stores who and why (an `ask_resolved` event). Asks never block the asking seat."""
import pytest

from edp8.board import Board, BoardError
from edp8.schemas import EventKind, MessageKind, Role, SessionState, StatusValue, TicketKind, TicketStatus, WorkType
from edp8.store import Store


@pytest.fixture
def rig():
    b = Board(Store())
    owner = b.participant_create("human", Role.owner, "owner", id_="owner")
    arch = b.participant_create("agent", Role.architect, "architect.e", id_="architect.e")
    eng = b.participant_create("agent", Role.engineer, "engineer.e", id_="engineer.e")
    qa = b.participant_create("agent", Role.qa, "qa.e", id_="qa.e")
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Asks")
    for i, p in enumerate((arch, eng, qa)):
        b.session_upsert(id_=f"s-{i}", participant_id=p.id, ticket_id=epic.id, pool_id="pool", state=SessionState.alive)
    return b, owner, arch, eng, qa, epic


def open_ids(b, who):
    return [a["id"] for a in b.inbox(who)]


def settle(b, ask):
    return b.ask_resolution(ask.id)


def ask(b, eng, epic, to="owner", text="Which theme?"):
    return b.message_send(eng, ticket_id=epic.id, to=to, kind=MessageKind.question, text=text)


def test_a_reply_to_from_another_seat_resolves(rig):
    b, owner, arch, eng, qa, epic = rig
    q = ask(b, eng, epic)
    assert open_ids(b, owner) == [q.id]
    r = b.message_send(arch, ticket_id=epic.id, to=eng.id, kind=MessageKind.note, text="use dark", reply_to=q.id)
    assert open_ids(b, owner) == []
    assert settle(b, q) == {"resolved_by": arch.id, "reason": "reply", "via": r.id, "at": settle(b, q)["at"]}


def test_a_message_quote_from_another_seat_resolves(rig):
    b, owner, arch, eng, qa, epic = rig
    q = ask(b, eng, epic)
    quote = {"source": "message", "id": q.id, "text": "Which theme?"}
    from edp8.quotes import quotes_in
    r = b.message_send(arch, ticket_id=epic.id, to=eng.id, kind=MessageKind.note, text="dark, see the quote",
                       quotes=quotes_in(b, arch, [quote]))
    assert open_ids(b, owner) == []
    assert settle(b, q)["reason"] == "reply" and settle(b, q)["via"] == r.id


def test_the_askers_own_follow_up_does_not_resolve(rig):
    b, owner, arch, eng, qa, epic = rig
    q = ask(b, eng, epic)
    b.message_send(eng, ticket_id=epic.id, to=None, kind=MessageKind.note, text="more detail", reply_to=q.id)
    assert open_ids(b, owner) == [q.id]


def test_a_counter_question_naming_the_ask_does_not_resolve(rig):
    b, owner, arch, eng, qa, epic = rig
    q = ask(b, eng, epic)
    b.message_send(qa, ticket_id=epic.id, to=eng.id, kind=MessageKind.question, text="which?", reply_to=q.id)
    assert open_ids(b, owner) == [q.id]


def test_resolves_settles_the_named_asks(rig):
    b, owner, arch, eng, qa, epic = rig
    q1, q2, q3 = ask(b, eng, epic, text="one"), ask(b, eng, epic, text="two"), ask(b, eng, epic, text="three")
    r = b.message_send(arch, ticket_id=epic.id, to=None, kind=MessageKind.note, text="decided both",
                       resolves=[q1.id, q2.id, q1.id])
    assert open_ids(b, owner) == [q3.id]
    assert r.resolves == [q1.id, q2.id]
    assert settle(b, q1)["resolved_by"] == arch.id and settle(b, q1)["reason"] == "resolves"
    assert settle(b, q2)["via"] == r.id


def test_resolves_refuses_a_foreign_or_non_ask_id_and_stores_nothing(rig):
    b, owner, arch, eng, qa, epic = rig
    story = b.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    elsewhere = b.message_send(eng, ticket_id=story.id, to="owner", kind=MessageKind.question, text="there")
    note = b.message_send(eng, ticket_id=epic.id, to=None, kind=MessageKind.note, text="just a note")
    before = len(b.thread(epic.id))
    for bad in (elsewhere.id, note.id, "m-nope"):
        with pytest.raises(BoardError) as e:
            b.message_send(arch, ticket_id=epic.id, to=None, kind=MessageKind.note, text="x", resolves=[bad])
        assert bad in str(e.value)
    assert len(b.thread(epic.id)) == before
    assert b.ask_resolution(elsewhere.id) is None


def test_resolves_on_an_already_settled_ask_is_accepted(rig):
    b, owner, arch, eng, qa, epic = rig
    q = ask(b, eng, epic)
    b.message_send(arch, ticket_id=epic.id, to=None, kind=MessageKind.note, text="a", resolves=[q.id])
    first = settle(b, q)
    b.message_send(qa, ticket_id=epic.id, to=None, kind=MessageKind.note, text="b", resolves=[q.id])
    assert settle(b, q) == first  # the first settle stands


def test_the_owner_writing_on_the_ticket_settles_an_ask_to_them(rig):
    b, owner, arch, eng, qa, epic = rig
    q = ask(b, eng, epic)
    other = ask(b, eng, epic, to=arch.id, text="to the architect")  # not addressed to the owner
    r = b.message_send(owner, ticket_id=epic.id, to=None, kind=MessageKind.note, text="carry on, I trust you")
    assert open_ids(b, owner) == []
    assert settle(b, q)["resolved_by"] == owner.id and settle(b, q)["reason"] == "owner_message"
    assert settle(b, q)["via"] == r.id
    assert b.ask_resolution(other.id) is None


def test_an_owner_message_on_another_ticket_does_not_settle(rig):
    b, owner, arch, eng, qa, epic = rig
    story = b.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    q = ask(b, eng, epic)
    b.message_send(owner, ticket_id=story.id, to=None, kind=MessageKind.note, text="elsewhere")
    assert open_ids(b, owner) == [q.id]


def test_the_ticket_moving_past_the_asked_phase_settles_it(rig):
    b, owner, arch, eng, qa, epic = rig
    story = b.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    q = b.message_send(eng, ticket_id=story.id, to="owner", kind=MessageKind.question, text="q")
    assert q.ask_phase == story.status.value
    b.store.put("ticket", b.ticket(story.id).model_copy(update={"status": TicketStatus.in_progress}))
    b._emit(story.id, EventKind.status_changed, {"from": story.status.value, "to": "in_progress", "by": "board"})
    assert open_ids(b, owner) == []
    assert settle(b, q)["reason"] == "phase_past" and settle(b, q)["resolved_by"] == "board"


def test_moving_to_the_same_or_an_earlier_phase_does_not_settle(rig):
    b, owner, arch, eng, qa, epic = rig
    story = b.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    b.store.put("ticket", b.ticket(story.id).model_copy(update={"status": TicketStatus.in_progress}))
    q = b.message_send(eng, ticket_id=story.id, to="owner", kind=MessageKind.question, text="q")
    assert q.ask_phase == "in_progress"
    b._emit(story.id, EventKind.status_changed, {"from": "in_progress", "to": "blocked", "by": "x"})
    b._emit(story.id, EventKind.status_changed, {"from": "blocked", "to": "in_progress", "by": "x"})
    b._emit(story.id, EventKind.status_changed, {"from": "in_review", "to": "ready", "by": "x"})
    assert open_ids(b, owner) == [q.id]
    b._emit(story.id, EventKind.status_changed, {"from": "in_progress", "to": "in_review", "by": "x"})
    assert open_ids(b, owner) == []


def test_an_ask_made_while_blocked_clears_when_the_block_lifts(rig):
    b, owner, arch, eng, qa, epic = rig
    story = b.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    b.store.put("ticket", b.ticket(story.id).model_copy(update={"status": TicketStatus.blocked}))
    q = b.message_send(eng, ticket_id=story.id, to="owner", kind=MessageKind.question, text="unblock me")
    assert q.ask_phase == "blocked"
    b._emit(story.id, EventKind.status_changed, {"from": "blocked", "to": "in_progress", "by": "x"})
    assert settle(b, q)["reason"] == "phase_past"


def test_an_unrelated_seat_note_does_not_resolve(rig):
    b, owner, arch, eng, qa, epic = rig
    q = ask(b, eng, epic)
    b.message_send(qa, ticket_id=epic.id, to=None, kind=MessageKind.note, text="unrelated thoughts")
    b.message_send(arch, ticket_id=epic.id, to=eng.id, kind=MessageKind.answer, text="answers nothing in particular")
    b.message_send(qa, ticket_id=epic.id, to="owner", kind=MessageKind.status, text="fyi")
    assert open_ids(b, owner) == [q.id]
    assert b.ask_resolution(q.id) is None


def test_asks_to_the_owner_never_block_the_asking_seat(rig):
    b, owner, arch, eng, qa, epic = rig
    q = ask(b, eng, epic)
    again = b.message_send(eng, ticket_id=epic.id, to=None, kind=MessageKind.note, text="working on my recommendation")
    assert again.id and open_ids(b, owner) == [q.id]
    assert open_ids(b, eng) == []  # the asker has nothing waiting on it, and may record its outcome
    assert b.record_status(eng, status=StatusValue.handed_off, ticket_id=epic.id)[0].id


# ------------------------------------------------------------------ the REST and MCP edges

OWN = {"X-Participant": "owner"}
ENG = {"X-Participant": "engineer.e"}
ARCH = {"X-Participant": "architect.e"}


@pytest.fixture
def rest(monkeypatch):
    from fastapi.testclient import TestClient

    from edp8 import broker_adapter
    from edp8.service import create_app
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    board = Board(Store(":memory:"))
    client = TestClient(create_app(board, admin_token="t"))
    for pid, role, typ in [("owner", "owner", "human"), ("architect.e", "architect", "agent"),
                           ("engineer.e", "engineer", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers={"X-Admin": "t"}).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E"},
                       headers=OWN).json()["value"]["id"]
    return client, epic


def send(client, headers, epic, **body):
    return client.post("/v1/messages", json={"ticket_id": epic, "kind": "note", "text": "t", **body}, headers=headers).json()


def test_the_ask_receipt_names_resolves_and_tells_the_seat_to_carry_on(rest):
    client, epic = rest
    to_owner = send(client, ENG, epic, kind="question", to="owner", text="theme?")
    assert to_owner["ok"]
    assert "never blocks you" in to_owner["hint"] and "resolves=[id]" in to_owner["hint"]
    to_seat = send(client, ENG, epic, kind="question", to="architect.e", text="design?")
    assert "resolves=[ask id]" in to_seat["hint"]
    assert "resolves=" not in send(client, ENG, epic, kind="note", text="plain")["hint"]


def test_resolves_over_rest_settles_and_a_bad_id_is_a_400(rest):
    client, epic = rest
    q = send(client, ENG, epic, kind="question", to="owner", text="theme?")["value"]["id"]
    bad = client.post("/v1/messages", json={"ticket_id": epic, "kind": "note", "text": "x", "resolves": ["m-nope"]},
                      headers=ARCH)
    assert bad.status_code == 400 and "m-nope" in bad.text
    ok = send(client, ARCH, epic, resolves=[q])
    assert ok["ok"] and ok["value"]["resolves"] == [q]
    assert client.get("/v1/me/attention", headers=OWN).json()["value"]["items"] == []


def test_resolves_is_an_mcp_arg_that_reaches_the_client():
    from edp8.bundles import MessageSendArgs
    assert "resolves" in MessageSendArgs.model_fields
    assert MessageSendArgs(ticket_id="t", kind="note", text="x", resolves=["m-1"]).resolves == ["m-1"]
