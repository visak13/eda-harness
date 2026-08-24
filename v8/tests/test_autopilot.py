"""Autopilot: the coordinator's routine moves as deterministic board-side code."""

import pytest

from edp8.autopilot import Autopilot
from edp8.board import Board
from edp8.schemas import Check, DocType, Role, TicketKind, TicketStatus, WorkType
from edp8.store import Store


@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def owner(board):
    return board.participant_create("human", Role.owner, "owner", id_="owner")


@pytest.fixture
def ap(board, monkeypatch):
    a = Autopilot(board)
    spawned, reaped = [], []
    import edp8.pool_adapter as pa
    def fake_spawn(role, pid, **k):
        spawned.append((role, pid))
        return {"ok": True, "value": {"session_id": f"s-{pid}"}}

    monkeypatch.setattr(pa, "spawn", fake_spawn)
    monkeypatch.setattr(pa, "reap", lambda h: (reaped.append(h) or {"ok": True, "value": {}}))
    a._test_spawned, a._test_reaped = spawned, reaped
    a._test_sessions = []
    monkeypatch.setattr(pa, "sessions", lambda: {"ok": True, "value": a._test_sessions})
    return a


def test_drafted_epic_gets_an_architect(board, owner, ap):
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="w")
    ap.tick()
    assert ("architect", f"architect.{epic.id}") in ap._test_spawned
    assert board.ticket(epic.id).assignee == f"architect.{epic.id}"
    # idempotent while the seat is occupied
    ap._test_sessions[:] = [{"handle": f"architect.{epic.id}", "state": "active"}]
    n = len(ap._test_spawned)
    ap.tick()
    assert len(ap._test_spawned) == n


def test_ready_story_gets_engineer_and_review_story_gets_reviewer(board, owner, ap):
    arch = board.participant_create("agent", Role.architect, "arch", id_="arch")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="w")
    s1 = board.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="s1", parent_id=epic.id)
    r1 = board.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.review, title="r1", parent_id=epic.id)
    d = board.doc_create(arch, doc_type=DocType.design, title="d", body_md="b", scope=epic.id)
    for t in (s1, r1):
        board.ticket_update(arch, t.id, design_ref=d.id)
        board.criterion_create(arch, ticket_id=t.id, text="x", check=Check.command,
                               checked_by="qa" if t.id == r1.id else "reviewer")
        board.ticket_update(arch, t.id, status=TicketStatus.designed)
        board.ticket_update(owner, t.id, status=TicketStatus.signed_off)
    ap.tick()
    assert ("engineer", f"engineer.{s1.id}") in ap._test_spawned
    assert all(p != f"reviewer.{r1.id}" for _r, p in ap._test_spawned), "review story blocked until s1 done"


def test_closed_epic_fleet_is_reaped_parked_too(board, owner, ap):
    arch = board.participant_create("agent", Role.architect, "arch2", id_="arch2")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.chore, title="w")
    board.criterion_create(arch, ticket_id=epic.id, text="x", check=Check.command, checked_by="qa")
    board.store.put("ticket", board.ticket(epic.id).model_copy(update={"status": TicketStatus.dropped}))
    ap._test_sessions[:] = [{"handle": f"architect.{epic.id}", "state": "parked"},
                            {"handle": f"engineer.{epic.id}", "state": "active"}]
    ap.tick()
    assert f"architect.{epic.id}" in ap._test_reaped
    assert f"engineer.{epic.id}" in ap._test_reaped


def test_dead_shell_on_live_ticket_respawns(board, owner, ap):
    arch = board.participant_create("agent", Role.architect, "arch3", id_="arch3")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="w")
    s1 = board.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="s1", parent_id=epic.id)
    ap._test_sessions[:] = [{"handle": f"architect.{epic.id}", "state": "active"},
                            {"handle": f"engineer.{s1.id}", "state": "dead"}]
    ap.tick()
    assert ("engineer", f"engineer.{s1.id}") in ap._test_spawned
