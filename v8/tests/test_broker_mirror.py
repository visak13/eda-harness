"""Addressed board traffic is mirrored into edp-broker inboxes (the wake plane)."""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter
from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}


@pytest.fixture
def published(monkeypatch):
    sent: list[tuple[str, str, str, dict]] = []
    monkeypatch.setattr(broker_adapter, "publish",
                        lambda from_, to, kind, body: sent.append((from_, to, kind, body)) or True)
    return sent


@pytest.fixture
def client():
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


@pytest.fixture
def rig(client):
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent")]:
        r = client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                        headers=ADMIN)
        assert r.json()["ok"], r.text
    r = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "w"},
                    headers={"X-Participant": "owner"})
    return r.json()["value"]["id"]


def test_addressed_message_is_mirrored(client, rig, published):
    r = client.post("/v1/messages", json={"ticket_id": rig, "to": "arch", "kind": "question", "text": "hi"},
                    headers={"X-Participant": "owner"})
    assert r.json()["ok"], r.text
    assert published == [("owner", "arch", "question", {"ticket_id": rig, "text": "hi",
                                                        "board_msg_id": published[0][3]["board_msg_id"]})]


def test_unaddressed_note_is_not_mirrored(client, rig, published):
    r = client.post("/v1/messages", json={"ticket_id": rig, "kind": "note", "text": "fyi"},
                    headers={"X-Participant": "owner"})
    assert r.json()["ok"], r.text
    assert published == []


def test_role_named_participant_is_mirrored_but_pure_role_broadcast_is_not(client, rig, published):
    # "architect" the PARTICIPANT (default registry row) has an inbox to wake
    r = client.post("/v1/participants", json={"type": "agent", "role": "architect", "handle": "architect",
                                              "id": "architect"}, headers=ADMIN)
    assert r.json()["ok"], r.text
    r = client.post("/v1/messages", json={"ticket_id": rig, "to": "architect", "kind": "question", "text": "q"},
                    headers={"X-Participant": "owner"})
    assert r.json()["ok"], r.text
    assert published[-1][:3] == ("owner", "architect", "question")
    # "sme" is only a role here (no such participant): a broadcast, nothing to wake
    n = len(published)
    r = client.post("/v1/messages", json={"ticket_id": rig, "to": "sme", "kind": "note", "text": "x"},
                    headers={"X-Participant": "owner"})
    assert r.json()["ok"], r.text
    assert len(published) == n


def test_gate_open_wakes_owner_and_answer_wakes_assignee(client, rig, published):
    r = client.patch(f"/v1/tickets/{rig}", json={"assignee": "arch"}, headers={"X-Participant": "owner"})
    assert r.json()["ok"], r.text
    r = client.post(f"/v1/gates/{rig}/design_signoff/open", json={"note": "please"},
                    headers={"X-Participant": "arch"})
    assert r.json()["ok"], r.text
    assert ("arch", "owner", "question") == published[-1][:3]
    r = client.post(f"/v1/gates/{rig}/design_signoff/answer", json={"answer": "signed"},
                    headers={"X-Participant": "owner"})
    assert r.json()["ok"], r.text
    assert ("owner", "arch", "answer") == published[-1][:3]
    assert published[-1][3]["gate"] == "design_signoff"


def test_dead_session_transition_drops_crashed_notice_for_owner(client, rig, published):
    body = {"participant_id": "architect.x", "ticket_id": rig, "pool_id": "local", "state": "alive"}
    assert client.put("/v1/sessions/s-1", json=body, headers=ADMIN).json()["ok"]
    assert published == []  # alive is not news
    assert client.put("/v1/sessions/s-1", json={**body, "state": "dead"}, headers=ADMIN).json()["ok"]
    assert published[-1][:3] == ("pool", "owner", "crashed")
    assert published[-1][3]["participant"] == "architect.x"
    # same state again is not a transition — no duplicate notice
    n = len(published)
    assert client.put("/v1/sessions/s-1", json={**body, "state": "dead"}, headers=ADMIN).json()["ok"]
    assert len(published) == n


def test_broker_down_never_fails_the_write(client, rig, monkeypatch):
    monkeypatch.setenv("EDP_BROKER_URL", "http://127.0.0.1:1")  # nothing listens
    r = client.post("/v1/messages", json={"ticket_id": rig, "to": "arch", "kind": "steer", "text": "x"},
                    headers={"X-Participant": "owner"})
    assert r.json()["ok"], r.text
