"""Adversary round 2 (2026-09-10) backend defects #3, #5, #7 — Board + Store(':memory:') direct."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from edp8 import views
from edp8.board import Board
from edp8.schemas import Message, MessageKind, Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store, new_id

HDR = {"X-Participant": "owner"}


@pytest.fixture
def board() -> Board:
    return Board(Store(":memory:"))


@pytest.fixture
def rig(board: Board) -> dict:
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    bob = board.participant_create("human", Role.owner, "bob", id_="human-b")
    alice = board.participant_create("agent", Role.architect, "alice", id_="alice")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Epic")
    story = board.ticket_create(alice, kind=TicketKind.story, work_type=WorkType.feature, title="S",
                                parent_id=epic.id)
    return {"owner": owner, "bob": bob, "alice": alice, "epic": epic, "story": story}


def _post_many(board: Board, rig: dict, n: int, ticket_id: str | None = None) -> list[Message]:
    tid = ticket_id or rig["story"].id
    return [board.message_send(rig["alice"], ticket_id=tid, to=None, kind=MessageKind.note, text=str(i))
            for i in range(n)]


# --------------------------------------------------------------------------- #3 handle-addressed rows
def test_bare_handle_recipient_is_stored_as_canonical_id(board: Board, rig: dict) -> None:
    m = board.message_send(rig["alice"], ticket_id=rig["story"].id, to="bob", kind=MessageKind.note, text="hi")
    assert m.to == "human-b"
    rows = views.replies_for(board, rig["bob"])
    assert [r["id"] for r in rows] == [m.id]


def test_replies_for_includes_historic_handle_addressed_rows(board: Board, rig: dict) -> None:
    old = Message(id=new_id("m"), ticket_id=rig["story"].id, to="bob", kind=MessageKind.note,
                  text="legacy row addressed by handle", created_by="alice")
    board.store.put("message", old)
    ids = {r["id"] for r in views.replies_for(board, rig["bob"])}
    assert old.id in ids


# --------------------------------------------------------------------------- #5 windows keep the newest
def test_thread_window_keeps_newest_in_order(board: Board, rig: dict) -> None:
    _post_many(board, rig, 101)
    texts = [m.text for m in board.thread(rig["story"].id, limit=50)]
    assert texts == [str(i) for i in range(51, 101)]


def test_thread_include_appends_out_of_window_message_in_place(board: Board, rig: dict) -> None:
    msgs = _post_many(board, rig, 101)
    oldest = msgs[0]
    texts = [m.text for m in board.thread(rig["story"].id, limit=50, include=oldest.id)]
    assert texts == ["0"] + [str(i) for i in range(51, 101)]
    # an in-window include changes nothing
    assert len(board.thread(rig["story"].id, limit=50, include=msgs[-1].id)) == 50
    # a message from another ticket is never smuggled in
    other = board.message_send(rig["alice"], ticket_id=rig["epic"].id, to=None, kind=MessageKind.note, text="x")
    assert other.id not in {m.id for m in board.thread(rig["story"].id, limit=50, include=other.id)}


def test_ticket_and_epic_page_include_deep_linked_message(board: Board, rig: dict) -> None:
    msgs = _post_many(board, rig, 120)
    oldest = msgs[0]
    page = views.ticket_page(board, rig["story"].id)
    assert len(page["thread"]) == 100 and oldest.id not in {m["id"] for m in page["thread"]}
    assert page["thread"][-1]["text"] == "119"
    page = views.ticket_page(board, rig["story"].id, include=oldest.id)
    assert page["thread"][0]["id"] == oldest.id and len(page["thread"]) == 101
    # the REST wiring: ?include=m-... on both page endpoints
    client = TestClient(create_app(board, admin_token="t"))
    r = client.get(f"/v1/tickets/{rig['story'].id}/page", params={"include": oldest.id}, headers=HDR).json()
    assert r["ok"] and oldest.id in {m["id"] for m in r["value"]["thread"]}
    e_msgs = _post_many(board, rig, 101, ticket_id=rig["epic"].id)
    r = client.get(f"/v1/epics/{rig['epic'].id}/page", params={"include": e_msgs[0].id}, headers=HDR).json()
    assert r["ok"] and r["value"]["thread"][0]["id"] == e_msgs[0].id
    assert r["value"]["thread"][-1]["text"] == "100"


def test_conversations_last_is_the_true_last(board: Board, rig: dict) -> None:
    _post_many(board, rig, 101)
    rows = views.conversations_for(board, rig["alice"])
    row = next((r for r in rows if r["ticket_id"] == rig["story"].id), None)
    assert row is not None, rows
    assert row["last"]["text"] == "100"


def test_replies_for_returns_the_newest_of_many(board: Board, rig: dict) -> None:
    for i in range(600):
        board.message_send(rig["alice"], ticket_id=rig["story"].id, to="bob", kind=MessageKind.note, text=str(i))
    rows = views.replies_for(board, rig["bob"], limit=30)
    assert [r["text"] for r in rows][:3] == ["599", "598", "597"]


# --------------------------------------------------------------------------- #7 wake preview mentions
def test_resolve_preview_lists_mentioned_recipients(board: Board, rig: dict) -> None:
    text = "@alice please coordinate with @bob"
    r = board.resolve(rig["owner"], ticket_id=rig["story"].id, to=None, kind=MessageKind.note, text=text)
    assert {"alice", "human-b"} <= {w["recipient"] for w in r["wakes"]}, r
    # the preview mirrors the mentions a real send emits (same exclude set as message_send)
    m = board.message_send(rig["owner"], ticket_id=rig["story"].id, to=None, kind=MessageKind.note, text=text)
    evs = [e for e in board.store.query("event", {"subject_id": rig["story"].id}) if e.data.get("message") == m.id]
    assert set(evs[-1].data["mentions"]) == {"alice", "human-b"}
    # the addressee is excluded from mentions in both, exactly like message_send
    r2 = board.resolve(rig["owner"], ticket_id=rig["story"].id, to="bob", kind=MessageKind.note, text=text)
    assert "human-b" in {w["recipient"] for w in r2["wakes"]}


def test_resolve_endpoint_accepts_text(board: Board, rig: dict) -> None:
    client = TestClient(create_app(board, admin_token="t"))
    r = client.post("/v1/messages/resolve",
                    json={"ticket_id": rig["story"].id, "to": None, "kind": "note",
                          "text": "@alice please coordinate with @bob"}, headers=HDR).json()
    assert r["ok"], r
    assert {"alice", "human-b"} <= {w["recipient"] for w in r["value"]["wakes"]}
    # without text the preview is unchanged (backwards compatible)
    r0 = client.post("/v1/messages/resolve", json={"ticket_id": rig["story"].id, "to": None, "kind": "note"},
                     headers=HDR).json()
    assert r0["ok"] and r0["value"]["wakes"] == []
