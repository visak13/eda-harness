"""The owner's feed carries what its card acts on: gates, addressed messages,
dying shells, and phase-boundary status changes — and not the design-time noise."""

import pytest

from edp8.board import Board
from edp8.schemas import Event, EventKind, Role
from edp8.store import Store


@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def owner(board):
    return board.participant_create("human", Role.owner, "owner", id_="owner")


def ev(kind, data):
    return Event(id="ev-x", subject_id="t-x", kind=kind, data=data)


def test_owner_sees_shell_death_and_stall(board, owner):
    assert board.relevant(ev(EventKind.shell_dead, {"participant": "architect.e1"}), owner)
    assert board.relevant(ev(EventKind.shell_stalled, {"participant": "engineer.s1"}), owner)


def test_owner_sees_phase_boundaries_not_design_noise(board, owner):
    assert board.relevant(ev(EventKind.status_changed, {"from": "signed_off", "to": "ready"}), owner)
    assert board.relevant(ev(EventKind.status_changed, {"from": "in_progress", "to": "in_review"}), owner)
    assert board.relevant(ev(EventKind.status_changed, {"from": "in_review", "to": "done"}), owner)
    assert not board.relevant(ev(EventKind.status_changed, {"from": "drafted", "to": "designed"}), owner)
    assert not board.relevant(ev(EventKind.status_changed, {"from": "designed", "to": "signed_off"}), owner)


def test_owner_still_skips_assignment_noise(board, owner):
    assert not board.relevant(ev(EventKind.assigned, {"assignee": "engineer.s1"}), owner)
    assert not board.relevant(ev(EventKind.ticket_created, {"kind": "task"}), owner)
