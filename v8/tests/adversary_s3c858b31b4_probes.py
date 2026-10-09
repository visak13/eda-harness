"""Bounded 5ea77f0d review: assertions reproduce defects, not desired contracts.

Private in-memory stores and a stub pool only. tests/conftest.py isolates fleet env.
Run: .venv/Scripts/python.exe -m pytest -q -s -p no:cacheprovider tests/adversary_s3c858b31b4_probes.py
"""
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from edp8 import broker_adapter, delivery, views
from edp8.board import Board
from edp8.schemas import Check, Criterion, EventKind, Role, SessionState, TicketKind, TicketStatus, WorkType
from edp8.service import create_app
from edp8.store import Store


class Pool:
    def __init__(self):
        self.spawned = []

    def spawn(self, role, participant_id, **kwargs):
        self.spawned.append((role, participant_id))
        return {"ok": True}


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *args, **kwargs: True)
    pool = Pool()
    b = Board(Store(":memory:"), pool=pool, free_mb=lambda: 4096)
    owner = b.participant_create("human", Role.owner, "owner", id_="owner")
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Review probe")
    story = b.ticket_create(owner, kind=TicketKind.story, work_type=WorkType.feature, title="Story", parent_id=epic.id)
    arch = b.participant_create("agent", Role.architect, f"architect.{epic.id}", id_=f"architect.{epic.id}")
    eng = b.participant_create("agent", Role.engineer, f"engineer.{story.id}", id_=f"engineer.{story.id}")
    return b, owner, epic, story, arch, eng, pool


def test_historical_revive_event_breaks_event_reads(rig):
    b, owner, epic, *_ = rig
    ev = b._emit(epic.id, EventKind.board_hint, {"seat": "engineer.old", "by": owner.id, "message": "m-old"})
    body = ev.model_dump(mode="json")
    body["kind"] = "seat_revive_started"
    with b.store._conn:
        b.store._conn.execute("UPDATE event SET kind=?, body=? WHERE id=?", (body["kind"], json.dumps(body), ev.id))
    for name, read in [("get", lambda: b.store.get("event", ev.id)),
                       ("events_since", lambda: b.store.events_since(0, limit=1000)),
                       ("events_before", lambda: b.store.events_before(None, limit=1000)),
                       ("feed replay", lambda: b.replay(owner, 0)),
                       ("activity tail", lambda: b.replay_tail(owner, 20))]:
        with pytest.raises(ValidationError, match="seat_revive_started"):
            read()
        print(f"F1 {name}: ValidationError on historical seat_revive_started")


def test_architect_sending_to_closed_seat_does_not_receive_hint(rig):
    b, owner, epic, story, arch, eng, _ = rig
    b.session_upsert(id_="eng-dead", participant_id=eng.id, ticket_id=story.id, pool_id="stub",
                     state=SessionState.dead, reason="closed by self: handed_off")
    m = b.message_send(arch, ticket_id=story.id, kind="steer", to=eng.id, text="Please repair the review finding")
    receipt = delivery.after_message(b, arch.id, m)
    hint = b.store.query("event", {"kind": EventKind.board_hint})[-1]
    assert "architect was told" in receipt[eng.id]
    assert b._architect_listener_reasons(hint, arch) == []
    assert not b.relevant(hint, arch)
    print("F2 architect-origin closed_seat_message: receipt claims told; listener/relevant both false")


def test_retired_gates_still_appear_on_ticket_api_and_cannot_be_answered(rig):
    b, owner, epic, story, arch, eng, _ = rig
    c = TestClient(create_app(b, admin_token="test"))
    for gate in ("poc", "demo", "adversarial", "budget"):
        b._emit(story.id, EventKind.gate_opened, {"gate": gate, "by": arch.id, "note": "Old open gate"})
    active = [e.data["gate"] for e in b.open_gates(story.id)]
    assert active == ["poc", "demo", "adversarial", "budget"]
    page = views.ticket_page(b, story.id)
    assert [g["gate"] for g in page["open_gates"]] == active
    for gate in active:
        r = c.post(f"/v1/gates/{story.id}/{gate}/answer", json={"answer": "retire"},
                   headers={"X-Participant": owner.id})
        assert r.status_code == 422, (r.status_code, r.text)
    print("F3 ticket_page.open_gates retains all four removed kinds; every answer returns HTTP 422")


def test_dead_qa_still_spawns_without_architect_decision(rig):
    b, owner, epic, story, arch, eng, pool = rig
    b.store.put("ticket", story.model_copy(update={"status": TicketStatus.in_review, "assignee": eng.id}))
    b.store.put("ticket", epic.model_copy(update={"status": TicketStatus.in_review}))
    b.store.put("criterion", Criterion(id="c-probe", ticket_id=story.id, text="Pending", check=Check.command,
                                       checked_by="qa", created_by=arch.id))
    pid = f"qa.{epic.id}"
    b.participant_create("agent", Role.qa, pid, id_=pid)
    b.session_upsert(id_="qa-old", participant_id=pid, ticket_id=epic.id, pool_id="stub", state=SessionState.alive)
    b.session_upsert(id_="qa-old", participant_id=pid, ticket_id=epic.id, pool_id="stub", state=SessionState.dead,
                     reason="crashed")
    assert pid in b._pending_pairings
    result = b.run_pending_pairings()
    assert pool.spawned == [("qa", pid)], (result, pool.spawned)
    print("F4 alive->dead qa: board queues and drain spawns qa without any architect action")

