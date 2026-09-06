"""Scoped delivery (2026-09-06): a bare role resolves to the seat on THIS epic, feeds never
cross epics, agent-created epics page no shared 'owner', and spawn never steals a live assignee."""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter, pool_adapter
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.schemas import EventKind
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}


@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def client(board):
    return TestClient(create_app(board, admin_token="t"))


@pytest.fixture
def published(monkeypatch):
    sent: list[tuple] = []
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: sent.append(a) or True)
    return sent


def _reg(client, pid, role, typ="agent"):
    r = client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid}, headers=ADMIN)
    assert r.json()["ok"], r.text


def _session(client, sid, pid, ticket, state):
    client.put(f"/v1/sessions/{sid}", json={"participant_id": pid, "ticket_id": ticket, "pool_id": "local",
                                            "state": state}, headers=ADMIN)


@pytest.fixture
def two_epics(client):
    _reg(client, "owner", "owner", "human")
    _reg(client, "bot", "coordinator")  # an agent that creates its own epic
    a = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "A"},
                    headers={"X-Participant": "owner"}).json()["value"]["id"]
    b = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "B (agent-made)"},
                    headers={"X-Participant": "bot"}).json()["value"]["id"]
    for e in (a, b):
        _reg(client, f"architect.{e}", "architect")
        _session(client, f"sid-{e}", f"architect.{e}", e, "alive")
        client.patch(f"/v1/tickets/{e}", json={"assignee": f"architect.{e}"}, headers={"X-Participant": "owner"})
    return {"a": a, "b": b}


def test_role_address_resolves_to_this_epics_seat_only(client, board, two_epics, published):
    a, b = two_epics["a"], two_epics["b"]
    r = client.post("/v1/messages", json={"ticket_id": a, "kind": "question", "to": "architect", "text": "q?"},
                    headers={"X-Participant": "owner"}).json()
    assert r["ok"] and r["value"]["to"] == f"architect.{a}"
    assert f"resolved to seat architect.{a}" in r["hint"]
    assert published[-1][1] == f"architect.{a}"  # the broker inbox that was woken
    arch_a, arch_b = board.participant(f"architect.{a}"), board.participant(f"architect.{b}")
    ev = [e for _, e in board.store.events_since(0) if e.kind == EventKind.message_sent][-1]
    assert board.relevant(ev, arch_a) and not board.relevant(ev, arch_b)
    assert [m["id"] for m in board.inbox(arch_a)] == [r["value"]["id"]]
    assert board.inbox(arch_b) == []


def test_role_with_no_seat_stays_a_note_and_wakes_nobody(client, two_epics, published):
    a = two_epics["a"]
    r = client.post("/v1/messages", json={"ticket_id": a, "kind": "note", "to": "sme", "text": "learning"},
                    headers={"X-Participant": "owner"}).json()
    assert r["ok"] and r["value"]["to"] == "sme" and "no sme seat" in r["hint"]
    assert not published


def test_agent_created_epic_pages_no_owner(client, board, two_epics, published):
    b = two_epics["b"]
    owner = board.participant("owner")
    assert board.epic_owner(b) is None
    g = client.post(f"/v1/gates/{b}/design_signoff/open", json={"note": "n"},
                    headers={"X-Participant": f"architect.{b}"}).json()
    assert g["ok"] and "no human owner" in g["hint"]
    assert not [x for x in published if x[1] == "owner"]
    for _, e in board.store.events_since(0):
        if e.subject_id == b:
            assert not board.relevant(e, owner), e
    # a message to a CLOSED seat on the agent epic goes to its live architect, not to 'owner'
    _reg(client, f"engineer.{b}", "engineer")
    _session(client, "sid-eng-b", f"engineer.{b}", b, "dead")
    published.clear()
    client.post("/v1/messages", json={"ticket_id": b, "kind": "question", "to": f"engineer.{b}", "text": "?"},
                headers={"X-Participant": "bot"})
    fyi = [x for x in published if x[2] == "fyi"]
    assert fyi and fyi[0][1] == f"architect.{b}"
    assert not [x for x in published if x[1] == "owner"]


def test_creating_a_ticket_does_not_subscribe_for_life(client, board, two_epics):
    a = two_epics["a"]
    _reg(client, "arch-x", "architect")
    t = client.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "t", "parent_id": a},
                    headers={"X-Participant": "arch-x"}).json()["value"]["id"]
    client.post("/v1/messages", json={"ticket_id": t, "kind": "note", "text": "n"}, headers={"X-Participant": "owner"})
    ev = [e for _, e in board.store.events_since(0) if e.kind == EventKind.message_sent][-1]
    assert not board.relevant(ev, board.participant("arch-x"))  # creator, not worker
    assert board.relevant(ev, board.participant(f"architect.{a}"))  # assigned up the chain


@pytest.fixture
def spawn_rig(client, two_epics, monkeypatch):
    a = two_epics["a"]
    _reg(client, "arch-c", "architect")
    s = client.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "S", "parent_id": a},
                    headers={"X-Participant": "arch-c"}).json()["value"]["id"]
    _reg(client, f"engineer.{s}", "engineer")
    client.patch(f"/v1/tickets/{s}", json={"assignee": f"engineer.{s}"}, headers={"X-Participant": "owner"})
    _session(client, "sid-eng", f"engineer.{s}", s, "alive")
    set_client(BoardClient(participant="owner", admin_token="t", client=client))
    spawned = []
    monkeypatch.setattr(pool_adapter, "spawn", lambda role, participant_id, **kw: spawned.append((role, participant_id)) or
                        {"ok": True, "value": {"session_id": "new"}, "hint": ""})
    return {"a": a, "s": s, "spawned": spawned}


def _spawn(**kw):
    return ALL_TOOLS["spawn"].handler(ALL_TOOLS["spawn"].args_model(**kw))


def test_spawn_refuses_second_architect_while_resident_is_up(client, spawn_rig):
    out = _spawn(role="architect", ticket_id=spawn_rig["s"])
    assert out["ok"] is False and out["error"]["code"] == "conflict"
    assert f"architect.{spawn_rig['a']}" in out["error"]["message"] and "to='architect'" in out["hint"]
    assert spawn_rig["spawned"] == []


def test_spawn_never_steals_a_live_assignee(client, spawn_rig):
    s = spawn_rig["s"]
    _session(client, f"sid-{spawn_rig['a']}", f"architect.{spawn_rig['a']}", spawn_rig["a"], "dead")  # resident gone
    out = _spawn(role="architect", ticket_id=s)
    assert out["ok"] and out["value"]["assignee_kept"] == f"engineer.{s}"
    tk = client.get(f"/v1/tickets/{s}", headers={"X-Participant": "owner"}).json()["value"]
    assert tk["assignee"] == f"engineer.{s}"
    # explicit takeover is allowed
    out = _spawn(role="architect", ticket_id=s, assign=True)
    assert out["ok"] and "assignee_kept" not in out["value"]
    tk = client.get(f"/v1/tickets/{s}", headers={"X-Participant": "owner"}).json()["value"]
    assert tk["assignee"] == f"architect.{s}"
