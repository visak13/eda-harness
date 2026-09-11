"""#37 (Astra, 2026-09-10; ruling m-dea825c3d8): (a) thread_limit=0 returns NO thread rows (rows[-0:]
was the whole thread) and the REST/tool schemas bound it to 0..200; (b) the fresh-criteria cap is
proven on a folded story in tests/test_s22_rules.py."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from edp8.board import Board
from edp8.bundles import TicketReadArgs
from edp8.schemas import MessageKind, Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store


@pytest.fixture
def board() -> Board:
    return Board(Store(":memory:"))


@pytest.fixture
def rig(board: Board) -> dict:
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Epic")
    for i in range(5):
        board.message_send(owner, ticket_id=epic.id, to=None, kind=MessageKind.note, text=f"m{i}")
    return {"owner": owner, "epic": epic}


def test_thread_limit_zero_returns_no_rows(board, rig):
    view = board.ticket_view(rig["epic"].id, include=["thread"], thread_limit=0)
    assert view["thread"] == [] and view["thread_total"] == 5 and view["thread_seq"] > 0
    assert len(board.ticket_view(rig["epic"].id, include=["thread"], thread_limit=2)["thread"]) == 2


def test_rest_thread_limit_is_bounded(board, rig):
    client = TestClient(create_app(board, admin_token="t"))
    h = {"X-Participant": "owner"}
    eid = rig["epic"].id
    r = client.get(f"/v1/tickets/{eid}", params={"include": "thread", "thread_limit": 0}, headers=h)
    assert r.status_code == 200 and r.json()["value"]["thread"] == []
    assert client.get(f"/v1/tickets/{eid}", params={"thread_limit": 201}, headers=h).status_code == 422
    assert client.get(f"/v1/tickets/{eid}", params={"thread_limit": -1}, headers=h).status_code == 422


def test_tool_schema_bounds_thread_limit():
    assert TicketReadArgs(ticket_id="t", thread_limit=0).thread_limit == 0
    with pytest.raises(ValidationError):
        TicketReadArgs(ticket_id="t", thread_limit=201)
    with pytest.raises(ValidationError):
        TicketReadArgs(ticket_id="t", thread_limit=-1)
