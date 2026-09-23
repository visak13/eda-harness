"""t-cf353a4051: "architect" on an epic resolves to the epic's LIVE resident architect.

A resident spawned under another epic id keeps its own handle (architect.epic-<other>), so the
convention architect.<epic> can name a dead seat while the live resident is the epic's assignee.
Board.resident_architect prefers the assignee when it is an architect with a live/parked/stalled
session, else falls back to architect.<epic>; resolve_recipient, the architect listener, the
status recipients, the board view (spawn/close/epic page) all go through it.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8 import broker_adapter, delivery, rsi
from edp8.board import Board
from edp8.schemas import EventKind, MessageKind, Reason, Role, SessionState, StatusValue, TicketKind, WorkType
from edp8.store import Store


@pytest.fixture(autouse=True)
def _no_broker(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)


@pytest.fixture
def rig():
    b = Board(Store(":memory:"))
    owner = b.participant_create("human", Role.owner, "owner", id_="owner")
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    dead = b.participant_create("agent", Role.architect, f"architect.{epic.id}", id_=f"architect.{epic.id}")
    b.session_upsert(id_="sess-dead", participant_id=dead.id, ticket_id=epic.id, pool_id="p1",
                     state=SessionState.dead)
    live = b.participant_create("agent", Role.architect, "architect.epic-other", id_="architect.epic-other")
    story = b.ticket_create(dead, kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    eng = b.participant_create("agent", Role.engineer, f"engineer.{story.id}", id_=f"engineer.{story.id}")
    b.ticket_update(owner, story.id, assignee=eng.id)
    return {"b": b, "owner": owner, "epic": epic, "story": story, "dead": dead, "live": live, "eng": eng}


def _make_resident(r, state=SessionState.alive):
    b = r["b"]
    b.ticket_update(r["owner"], r["epic"].id, assignee=r["live"].id)
    b.session_upsert(id_="sess-live", participant_id=r["live"].id, ticket_id=r["epic"].id, pool_id="p1", state=state)


def _last_msg_event(b, subject):
    return b.store.query("event", {"subject_id": subject, "kind": EventKind.message_sent})[-1]


@pytest.mark.parametrize("state", [SessionState.alive, SessionState.parked, SessionState.stalled])
def test_note_to_architect_lands_in_the_live_assignee_feed(rig, state):
    _make_resident(rig, state)
    b = rig["b"]
    assert b.resident_architect(b.ticket(rig["epic"].id)) == rig["live"].id
    m = b.message_send(rig["owner"], ticket_id=rig["epic"].id, to="architect", kind=MessageKind.note, text="design comment")
    m = m[0] if isinstance(m, tuple) else m
    assert m.to == rig["live"].id
    plan = dict(delivery.delivery_plan(b, _last_msg_event(b, rig["epic"].id)))
    assert Reason.addressed in plan[rig["live"].id]
    assert rig["dead"].id not in plan


def test_no_assignee_falls_back_to_the_convention(rig):
    b = rig["b"]
    assert b.resident_architect(rig["epic"]) == rig["dead"].id
    m = b.message_send(rig["owner"], ticket_id=rig["epic"].id, to="architect", kind=MessageKind.note, text="x")
    m = m[0] if isinstance(m, tuple) else m
    assert m.to == rig["dead"].id


def test_dead_or_non_architect_assignee_falls_back(rig):
    b = rig["b"]
    b.ticket_update(rig["owner"], rig["epic"].id, assignee=rig["live"].id)  # no session: never spawned
    assert b.resident_architect(b.ticket(rig["epic"].id)) == rig["dead"].id
    b.session_upsert(id_="sess-live", participant_id=rig["live"].id, ticket_id=rig["epic"].id, pool_id="p1",
                     state=SessionState.dead)
    assert b.resident_architect(b.ticket(rig["epic"].id)) == rig["dead"].id
    b.ticket_update(rig["owner"], rig["epic"].id, assignee=rig["eng"].id)  # alive but not an architect
    b.session_upsert(id_="sess-eng", participant_id=rig["eng"].id, ticket_id=rig["story"].id, pool_id="p1",
                     state=SessionState.alive)
    assert b.resident_architect(b.ticket(rig["epic"].id)) == rig["dead"].id


def test_architect_listener_pages_the_resident_not_the_dead_seat(rig):
    _make_resident(rig)
    b = rig["b"]
    b.message_send(rig["eng"], ticket_id=rig["story"].id, to=None, kind=MessageKind.question, text="stuck?")
    plan = dict(delivery.delivery_plan(b, _last_msg_event(b, rig["story"].id)))
    assert Reason.architect_listener in plan[rig["live"].id]
    # the dead convention seat authored the story, so it may still hear it as that ticket's seat —
    # never as the epic's architect
    assert Reason.architect_listener not in plan.get(rig["dead"].id, [])


def test_status_recipients_and_board_view_name_the_resident(rig):
    _make_resident(rig)
    b = rig["b"]
    _, told = b.record_status(rig["eng"], status=StatusValue.done, note="shipped", ticket_id=rig["story"].id)
    assert rig["live"].id in told and rig["dead"].id not in told
    assert b.board(rig["epic"].id)["architect"] == {"id": rig["live"].id, "state": "alive"}


def test_rsi_manifest_finding_is_back_to_the_role_alias():
    """The S18 manifest no longer needs a seat id: 'architect' now reaches the live resident."""
    to = json.loads(rsi.MANIFEST.read_text(encoding="utf-8"))["finding"]["to"]
    assert to == "architect"
