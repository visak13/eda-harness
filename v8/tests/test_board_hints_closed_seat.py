"""Board hints (design-63db8a7d42 D): a message to a closed seat revives nothing; the epic's architect gets one hint
naming the seat and the message, and its feed listener prints it. Private board, stub pool."""
from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

from fastapi.testclient import TestClient

from edp8 import broker_adapter
from edp8.board import Board
from edp8.schemas import EventKind, TicketStatus
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}


class StubPool:
    def __init__(self):
        self.resumed: list[str] = []
        self.spawned: list[str] = []

    def resume(self, pid, *a, **kw):
        self.resumed.append(pid)
        return {"ok": True, "value": {"resumed": True}}

    def spawn(self, role, pid, **kw):
        self.spawned.append(pid)
        return {"ok": True}

    def reachable(self, timeout=2.0):
        return True


def _rig(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: True)
    pool = StubPool()
    board = Board(Store(":memory:"), pool=pool, free_mb=lambda: 4096)
    client = TestClient(create_app(board, admin_token="t"))
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "w"},
                       headers={"X-Participant": "owner"}).json()["value"]["id"]
    story = client.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "s", "parent_id": epic},
                        headers={"X-Participant": "arch"}).json()["value"]["id"]
    seats = {"architect": f"architect.{epic}", "engineer": f"engineer.{story}"}
    for role, seat in seats.items():
        assert client.post("/v1/participants", json={"type": "agent", "role": role, "handle": seat, "id": seat},
                           headers=ADMIN).json()["ok"]
    return board, client, epic, story, seats, pool


def _session(client, sid, seat, ticket, state, reason=""):
    assert client.put(f"/v1/sessions/{sid}", json={"participant_id": seat, "ticket_id": ticket, "pool_id": "local",
                                                   "state": state, "reason": reason}, headers=ADMIN).json()["ok"]


def test_a_message_to_a_self_closed_seat_revives_nothing_and_hints_the_architect_once(monkeypatch):
    from edp8 import delivery
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    _session(client, "s-arch", seats["architect"], epic, "alive")
    _session(client, "s-eng", seats["engineer"], story, "dead", "closed by self: handed_off")
    t = board.store.get("ticket", story)
    t.status = TicketStatus.in_review
    board.store.put("ticket", t)
    r = client.post("/v1/messages", json={"ticket_id": story, "kind": "steer", "to": seats["engineer"],
                                          "text": "rework: tighten criterion 2"},
                    headers={"X-Participant": seats["architect"]}).json()
    assert r["ok"], r
    assert pool.resumed == [] and pool.spawned == []
    assert "revive started" not in r["hint"]
    # a human (the owner) writing to the closed seat: same hint, still no revive
    r2 = client.post("/v1/messages", json={"ticket_id": story, "kind": "question", "to": seats["engineer"],
                                           "text": "status?"}, headers={"X-Participant": "owner"}).json()
    assert r2["ok"], r2
    assert pool.resumed == []
    hints = [e for e in board.store.query("event", {"subject_id": story, "kind": EventKind.board_hint}, limit=50)
             if e.data.get("hint") == "closed_seat_message"]
    assert len(hints) == 2
    assert hints[0].data["seat"] == seats["engineer"] and hints[0].data["message"] == r["value"]["id"]
    assert seats["engineer"] in hints[0].data["text"] and r["value"]["id"] in hints[0].data["text"]
    arch = board.store.get("participant", seats["architect"])
    assert [x.value for x in board._architect_listener_reasons(hints[1], arch)] == ["architect_listener"]
    assert delivery.after_message(board, "owner", board.store.get("message", r2["value"]["id"]))  # receipt, not a revive


def test_a_live_seat_is_not_hinted(monkeypatch):
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    _session(client, "s-arch", seats["architect"], epic, "alive")
    _session(client, "s-eng", seats["engineer"], story, "alive")
    r = client.post("/v1/messages", json={"ticket_id": story, "kind": "steer", "to": seats["engineer"], "text": "go"},
                    headers={"X-Participant": seats["architect"]}).json()
    assert r["ok"], r
    assert not board.store.query("event", {"subject_id": story, "kind": EventKind.board_hint}, limit=10)


# ---- Astra report-8bcc65d4bc: F1 / F2 / F3 ----------------------------------------------------------------------

def test_f1_a_historical_seat_revive_started_event_still_decodes_in_every_read(monkeypatch):
    from edp8.schemas import Event
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    old = Event(id="ev-old-revive", subject_id=story, kind="seat_revive_started",
                data={"seat": seats["engineer"], "by": "owner", "message": "m-old"})
    board.store.put("event", old)
    owner = board.store.get("participant", "owner")
    assert board.store.get("event", "ev-old-revive").kind == "seat_revive_started"
    assert any(e.id == "ev-old-revive" for _, e in board.store.events_since(0))
    list(board.replay(owner, 0))
    list(board.replay_tail(owner, 20))
    assert EventKind.seat_revive_started.value == "seat_revive_started"


def test_f2_the_architects_own_message_to_a_closed_seat_reaches_its_own_listener(monkeypatch):
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    _session(client, "s-arch", seats["architect"], epic, "alive")
    _session(client, "s-eng", seats["engineer"], story, "dead", "closed by self: handed_off")
    r = client.post("/v1/messages", json={"ticket_id": story, "kind": "steer", "to": seats["engineer"], "text": "go"},
                    headers={"X-Participant": seats["architect"]}).json()
    assert r["ok"], r
    [hint] = [e for e in board.store.query("event", {"subject_id": story, "kind": EventKind.board_hint}, limit=10)]
    arch = board.store.get("participant", seats["architect"])
    assert hint.data["sender"] == seats["architect"]
    assert board.relevant(hint, arch) and [x.value for x in board._architect_listener_reasons(hint, arch)] == [
        "architect_listener"]


def test_f3_retired_gate_kinds_are_not_open_on_the_ticket_page_or_the_api(monkeypatch):
    from edp8 import views
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    for kind in ("poc", "demo", "adversarial", "budget"):
        board._emit(story, EventKind.gate_opened, {"gate": kind, "by": "arch", "note": "legacy"})
    live = board._emit(story, EventKind.gate_opened, {"gate": "scope", "by": "arch", "note": "split?"})
    assert [e.id for e in board.open_gates(story)] == [live.id]
    page = views.ticket_page(board, story)
    gates = page.get("open_gates") if isinstance(page, dict) else getattr(page, "open_gates", [])
    kinds = {(g.get("gate") if isinstance(g, dict) else getattr(g, "gate", None)) for g in gates}
    assert kinds <= {"scope"}, kinds


def test_a_message_folded_into_a_close_hint_on_another_ticket_is_not_hinted_again(monkeypatch):
    # adversary report-b9c60aeff1 F3: a close that leaves messages on two tickets anchors its one hint on the seat's own
    # ticket; the send path must still find it there and not hint the epic's message a second time
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    _session(client, "s-arch", seats["architect"], epic, "alive")
    _session(client, "s-eng", seats["engineer"], story, "alive")
    sent = []
    for ticket in (story, epic):
        r = client.post("/v1/messages", json={"ticket_id": ticket, "kind": "question", "to": seats["engineer"],
                                              "text": "status?"}, headers={"X-Participant": "owner"}).json()
        assert r["ok"], r
        sent.append(r["value"]["id"])
    _session(client, "s-eng", seats["engineer"], story, "dead", "process exited without close_self")
    hints = [e for e in board.store.query("event", {"kind": EventKind.board_hint}, limit=100)
             if e.data.get("hint") == "closed_seat_message"]
    assert len(hints) == 1 and hints[0].subject_id == story and hints[0].data["messages"] == sent
    epic_msg = board.store.get("message", sent[1])
    assert board.hint_closed_seat_message(epic_msg, seats["engineer"]) is False


def test_a_spawns_first_steer_to_the_seat_it_is_starting_is_not_hinted(monkeypatch):
    # live 16:14Z: spawn(steer=...) posts its steer just before the seat launches, and the board hinted the architect
    # that its own steer "awaits CLOSED seat". The seat is starting, not closed. Any other send still hints.
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    _session(client, "s-arch", seats["architect"], epic, "alive")
    _session(client, "s-eng", seats["engineer"], story, "dead", "closed by self: handed_off")

    def send(key=None):
        h = {"X-Participant": seats["architect"], **({"Idempotency-Key": key} if key else {})}
        r = client.post("/v1/messages", json={"ticket_id": story, "kind": "steer", "to": seats["engineer"],
                                              "text": "rework"}, headers=h).json()
        assert r["ok"], r
        return r

    r = send("spawn-steer-abc123")
    assert "seat is closed" not in r["hint"]
    hints = [e for e in board.store.query("event", {"kind": EventKind.board_hint}, limit=50)
             if e.data.get("hint") == "closed_seat_message"]
    assert hints == []
    send()
    hints = [e for e in board.store.query("event", {"kind": EventKind.board_hint}, limit=50)
             if e.data.get("hint") == "closed_seat_message"]
    assert len(hints) == 1
