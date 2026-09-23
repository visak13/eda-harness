"""t-899d295194 c-8f893cc2e8: an ask is unanswered only while its author's seat is live (or the author is
human / never had a shell) and nothing resolves it — a kind=answer reply, or ANY reply from the addressee.
The epic's Needs attention (contextual_work.unresolved_asks), the inbox and the owner-request flag read
the one rule (Board.ask_resolved)."""
import pytest

from edp8.board import Board
from edp8.contextual_work import contextual_work
from edp8.schemas import MessageKind, Role, SessionState, TicketKind, WorkType
from edp8.store import Store
from edp8.views import _pending_owner_request


@pytest.fixture
def rig():
    board = Board(Store())
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    arch = board.participant_create("agent", Role.architect, "architect.e", id_="architect.e")
    qa = board.participant_create("agent", Role.qa, "qa.e", id_="qa.e")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Asks")
    for i, p in enumerate((arch, qa)):
        board.session_upsert(id_=f"s-{i}", participant_id=p.id, ticket_id=epic.id, pool_id="pool", state=SessionState.alive)
    return board, owner, arch, qa, epic


def asks(board, epic):
    return [a["id"] for a in contextual_work(board, epic.id)["unresolved_asks"]]


def test_live_author_unanswered_counts(rig):
    b, owner, arch, _, epic = rig
    q = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.question, text="Which theme?")
    assert asks(b, epic) == [q.id]
    assert [m["id"] for m in b.inbox(owner)] == [q.id]
    assert _pending_owner_request(b, epic) is True


def test_closed_seat_asks_drop_out(rig):
    b, owner, arch, qa, epic = rig
    q1 = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.question, text="one")
    q2 = b.message_send(qa, ticket_id=epic.id, to="owner", kind=MessageKind.steer, text="two")
    assert set(asks(b, epic)) == {q1.id, q2.id}
    b.session_upsert(id_="s-1", participant_id=qa.id, ticket_id=epic.id, pool_id="pool", state=SessionState.dead)
    assert asks(b, epic) == [q1.id]  # qa's seat closed: nobody is left to read an answer
    assert [m["id"] for m in b.inbox(owner)] == [q1.id]


def test_addressee_note_or_mention_reply_resolves(rig):
    b, owner, arch, _, epic = rig
    q = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.question, text="Ship?")
    b.message_send(owner, ticket_id=epic.id, to=arch.id, kind=MessageKind.note, text="@architect.e yes, ship it", reply_to=q.id)
    assert asks(b, epic) == []
    assert b.inbox(owner) == []
    assert _pending_owner_request(b, epic) is False


def test_a_third_party_note_does_not_resolve_but_an_answer_does(rig):
    b, owner, arch, qa, epic = rig
    q = b.message_send(arch, ticket_id=epic.id, to="owner", kind=MessageKind.question, text="Ship?")
    b.message_send(qa, ticket_id=epic.id, to=None, kind=MessageKind.note, text="I think so", reply_to=q.id)
    assert asks(b, epic) == [q.id]  # only the addressee's reply (of any kind) closes it
    b.message_send(qa, ticket_id=epic.id, to=arch.id, kind=MessageKind.answer, text="answered", reply_to=q.id)
    assert asks(b, epic) == []


def test_human_author_and_never_shelled_agent_stay_open(rig):
    b, owner, _, _, epic = rig
    fresh = b.participant_create("agent", Role.engineer, "engineer.e", id_="engineer.e")  # no session yet
    q1 = b.message_send(owner, ticket_id=epic.id, to=fresh.id, kind=MessageKind.steer, text="start here")
    q2 = b.message_send(fresh, ticket_id=epic.id, to="owner", kind=MessageKind.question, text="which?")
    assert set(asks(b, epic)) == {q1.id, q2.id}
