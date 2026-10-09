"""Final bounded R1-R4 verification at 5036b903; private boards and stubbed effects only."""
from datetime import timedelta

import pytest

from test_board_hints_closed_seat import _rig, _session
from edp8 import pool_adapter
from edp8.schemas import EventKind, now


def rig(monkeypatch):
    b, c, epic, story, seats, _ = _rig(monkeypatch)
    _session(c, "arch", seats["architect"], epic, "alive")
    _session(c, "eng", seats["engineer"], story, "alive")
    return b, c, epic, story, seats


def instruction(c, story, eng):
    r = c.post("/v1/messages", headers={"X-Participant": "owner"},
               json={"ticket_id": story, "kind": "steer", "to": eng, "text": "Do the requested work."})
    assert r.json()["ok"]
    return r.json()["value"]["id"]


def lost(b, story):
    return [e.data["message"] for e in b.store.query("event", {"subject_id": story, "kind": EventKind.board_hint})
            if e.data.get("hint") == "closed_seat_message"]


@pytest.mark.parametrize("role", ["owner", "architect"])
def test_r1_actor_is_server_written_and_mixed_claims_are_refused(monkeypatch, role):
    b, c, epic, story, seats = rig(monkeypatch)
    calls = []
    monkeypatch.setattr(pool_adapter, "close", lambda pid, reason: calls.append(reason) or {"ok": True})
    headers = {"X-Participant": "owner" if role == "owner" else seats["architect"]}
    base = {"participant_id": seats["engineer"], "ticket_id": story}
    for reason in ("closed by owner; closed by architect", "closed by owner: closed by architect", "CLOSED BY SELF"):
        r = c.post("/v1/sessions/close", headers=headers, json={**base, "reason": reason})
        assert r.status_code >= 400 and not r.json()["ok"]
    assert calls == []
    assert c.post("/v1/sessions/close", headers=headers, json=base).json()["ok"]
    assert c.post("/v1/sessions/close", headers=headers, json={**base, "reason": "finished"}).json()["ok"]
    assert calls == [f"closed by {role}", f"closed by {role}: finished"]


@pytest.mark.parametrize("field", ["reply_to", "resolves"])
def test_r2_status_never_acknowledges_instruction(monkeypatch, field):
    b, c, epic, story, seats = rig(monkeypatch)
    mid = instruction(c, story, seats["engineer"])
    value = mid if field == "reply_to" else [mid]
    r = c.post("/v1/messages", headers={"X-Participant": seats["engineer"]},
               json={"ticket_id": story, "kind": "status", "text": "Booting, not handled.", field: value})
    assert r.json()["ok"]
    _session(c, "eng", seats["engineer"], story, "dead", "closed by owner")
    assert lost(b, story) == [mid]


def test_r3_legacy_running_session_backfills_and_hints_old_instruction(monkeypatch):
    b, c, epic, story, seats = rig(monkeypatch)
    row = b.store.get("session", "eng")
    row.started_seq = None
    b.store.put("session", row)
    mid = instruction(c, story, seats["engineer"])
    message = b.store.get("message", mid)
    message.created_at = now() - timedelta(minutes=4)
    b.store.put("message", message)
    _session(c, "eng", seats["engineer"], story, "alive")
    assert b.store.get("session", "eng").started_seq == b.store.seq_of("session", "eng")
    _session(c, "eng", seats["engineer"], story, "dead", "closed by owner")
    assert lost(b, story) == [mid]


def test_r4_two_incidents_each_have_one_plain_chat_and_one_recovery(monkeypatch):
    b, c, epic, story, seats = rig(monkeypatch)
    _session(c, "arch", seats["architect"], epic, "dead", "crashed")

    def chats():
        return b.store.query("message", {"created_by": "board", "to": "owner", "ticket_id": story})

    for index in range(2):
        _session(c, "eng", seats["engineer"], story, "dead", "process exited")
        _session(c, "eng", seats["engineer"], story, "dead", "process exited")
        assert len(chats()) == 2 * index + 1
        assert chats()[-1].kind.value == "note" and "crashed" in chats()[-1].text
        event = b.store.query("event", {"subject_id": story, "kind": EventKind.shell_dead})[-1]
        assert not b.relevant(event, b.participant("owner"))
        _session(c, "eng", seats["engineer"], story, "alive")
        _session(c, "eng", seats["engineer"], story, "alive")
        assert len(chats()) == 2 * index + 2
        assert chats()[-1].kind.value == "note" and "is running again" in chats()[-1].text
    for m in chats():
        events = b.store.query("event", {"subject_id": story, "kind": EventKind.message_sent})
        event = next(e for e in events if e.data.get("message") == m.id)
        assert b.relevant(event, b.participant("owner"))
