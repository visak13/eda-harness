"""Pure-unit tests for the two views.py derivations a checker calls out by name in
criterion c-2b582c033d: waiting_reason's ORDERED decision, its 0/0 → 'None defined' and
seat-presence-as-a-separate-field rules, and avatar_for's mtime-triggered prefs reload.

These drive views.py directly over a Board (no HTTP), so a change to the ordering or the
cache logic fails here rather than surfacing as a mystery in the page.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8 import views
from edp8.avatar_preferences import avatar_preferences_path, save_avatar_preference
from edp8.board import Board
from edp8.schemas import (
    Check,
    Gate,
    MessageKind,
    Relation,
    Role,
    SessionState,
    StatusValue,
    TicketKind,
    TicketStatus,
    WorkType,
)
from edp8.store import Store


@pytest.fixture
def board():
    b = Board(Store(":memory:"))
    b.participant_create("human", Role.owner, "owner", id_="owner")
    b.participant_create("agent", Role.architect, "arch", id_="arch")
    b.participant_create("agent", Role.engineer, "eng", id_="eng")
    return b


def _epic(b):
    owner = b.participant("owner")
    return b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E").id


def _story(b, epic, **kw):
    arch = b.participant("arch")
    return b.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.bug, title="s",
                           parent_id=epic, **kw).id


def _force_status(b, sid, status):
    """Set a ticket's status directly (bypassing transition guards) — these tests exercise the
    waiting_reason derivation, not the transition machine."""
    t = b.ticket(sid)
    t.status = status
    b.store.put("ticket", t)


# --------------------------------------------------------------------------- waiting_reason order


def test_open_gate_wins_over_everything(board):
    epic = _epic(board)
    # a story that ALSO has a pending owner question and an explicit blocker: the gate still wins
    blocker = _story(board, epic)
    sid = _story(board, epic)
    board.link_create(board.participant("arch"), from_id=blocker, to_id=sid, relation=Relation.blocks)
    board.message_send(board.participant("eng"), ticket_id=sid, to="owner",
                       kind=MessageKind.question, text="?")
    board.gate_open(sid, Gate.scope, by="eng", note="need scope")
    r = views.waiting_reason(board, board.ticket(sid))
    assert r["reason"] == "open gate: scope"


def test_pending_owner_request_beats_blocks(board):
    epic = _epic(board)
    blocker = _story(board, epic)
    sid = _story(board, epic)
    board.link_create(board.participant("arch"), from_id=blocker, to_id=sid, relation=Relation.blocks)
    board.message_send(board.participant("eng"), ticket_id=sid, to="owner",
                       kind=MessageKind.question, text="?")
    assert views.waiting_reason(board, board.ticket(sid))["reason"] == "waiting on the owner to answer"


def test_blocks_beats_blocked_status(board):
    epic = _epic(board)
    blocker = _story(board, epic)
    sid = _story(board, epic)
    board.link_create(board.participant("arch"), from_id=blocker, to_id=sid, relation=Relation.blocks)
    _force_status(board, sid, TicketStatus.blocked)
    assert views.waiting_reason(board, board.ticket(sid))["reason"] == f"blocked by {blocker}"


def test_blocked_status_beats_latest_status(board):
    epic = _epic(board)
    sid = _story(board, epic)
    board.record_status(board.participant("eng"), status=StatusValue.handed_off, ticket_id=sid)
    _force_status(board, sid, TicketStatus.blocked)
    assert views.waiting_reason(board, board.ticket(sid))["reason"] == "blocked"


def test_latest_status_when_nothing_else(board):
    epic = _epic(board)
    sid = _story(board, epic)
    board.record_status(board.participant("eng"), status=StatusValue.reviewed, ticket_id=sid)
    assert views.waiting_reason(board, board.ticket(sid))["reason"] == "reviewed"


def test_zero_criteria_is_none_defined(board):
    epic = _epic(board)
    sid = _story(board, epic)  # no gate, no owner ask, no blocks, no status, no criteria
    assert views.waiting_reason(board, board.ticket(sid))["reason"] == "None defined"


def test_criteria_tally_when_no_blocker(board):
    epic = _epic(board)
    sid = _story(board, epic)
    board.criterion_create(board.participant("arch"), ticket_id=sid, text="c1", check=Check.command)
    assert views.waiting_reason(board, board.ticket(sid))["reason"] == "0/1 criteria passed"


def test_presence_is_separate_from_reason(board):
    epic = _epic(board)
    board.participant_create("agent", Role.engineer, "engineer.seat", id_="engineer.seat")
    sid = _story(board, epic, assignee="engineer.seat")
    board.record_status(board.participant("eng"), status=StatusValue.reviewed, ticket_id=sid)
    board.session_upsert(id_="sx", participant_id="engineer.seat", ticket_id=sid,
                         pool_id="local", state=SessionState.alive)
    r = views.waiting_reason(board, board.ticket(sid))
    assert r["reason"] == "reviewed"        # presence never leaks into the reason
    assert r["presence"] == "alive"          # returned as its own field
    assert r["latest_status"] == "reviewed"


# --------------------------------------------------------------------------- avatar_for mtime reload


def test_avatar_for_reloads_on_prefs_mtime_change(board, monkeypatch, tmp_path):
    monkeypatch.setenv("EDP8_HOME", str(tmp_path))
    views._prefs_cache["key"] = None  # order-independent: forget any earlier test's file
    first = views.avatar_for(board, "owner")["avatar_id"]  # hash-derived default
    target = "human-01" if first != "human-01" else "human-02"
    save_avatar_preference("owner", target)  # writes ui-avatars.json under the tmp EDP8_HOME
    # force a distinct mtime so the reload is driven by the mtime change, not coincidence
    future = time.time() + 10
    os.utime(avatar_preferences_path(), (future, future))
    assert views.avatar_for(board, "owner")["avatar_id"] == target
