"""e0cec S15 slice A (p-5592b872): preparation by a knowledge ticket never carries an epic past the owner's sign-off.

Private board: nothing here touches the fleet."""
from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.schemas import TicketStatus
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}


def _rig():
    board = Board(Store(":memory:"), free_mb=lambda: 4096)
    client = TestClient(create_app(board, admin_token="t"))
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"), ("sme1", "sme", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "w"},
                       headers={"X-Participant": "owner"}).json()["value"]["id"]
    return board, client, epic


def _set(board, tid, **kw):
    t = board.store.get("ticket", tid)
    for k, v in kw.items():
        setattr(t, k, v)
    board.store.put("ticket", t)


def _story(client, epic, work_type):
    return client.post("/v1/tickets", json={"kind": "story", "work_type": work_type, "title": work_type,
                                            "parent_id": epic}, headers={"X-Participant": "arch"}).json()["value"]["id"]


def test_a_knowledge_story_starting_before_sign_off_leaves_the_epic_designed():
    board, client, epic = _rig()
    _set(board, epic, status=TicketStatus.designed)
    kt = _story(client, epic, "knowledge")
    _set(board, kt, status=TicketStatus.in_progress, assignee="sme1")
    board._after_status(board.ticket(kt))
    assert board.ticket(epic).status == TicketStatus.designed


def test_a_feature_story_starting_still_carries_the_epic_to_in_progress():
    board, client, epic = _rig()
    _set(board, epic, status=TicketStatus.designed)
    st = _story(client, epic, "feature")
    _set(board, st, status=TicketStatus.in_progress, assignee="arch")
    board._after_status(board.ticket(st))
    assert board.ticket(epic).status == TicketStatus.in_progress
