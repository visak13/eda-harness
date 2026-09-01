"""The human co-working plane: @mentions, ownership routing, tokens, /ui/me."""

from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter
from edp8.board import Board
from edp8.schemas import Role
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
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "tokens.json"))
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


@pytest.fixture
def rig(client):
    for pid, role, typ in [("aksou", "owner", "human"), ("x", "owner", "human"),
                           ("arch", "architect", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "mine"},
                       headers={"X-Participant": "aksou"}).json()["value"]["id"]
    return {"epic": epic}


# ----------------------------------------------------------------------- mentions

def test_mention_fans_out_to_broker_and_feed(client, rig, published):
    r = client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "note",
                                          "text": "planning this — need @x and @arch to weigh in"},
                    headers={"X-Participant": "aksou"}).json()
    assert r["ok"], r
    targets = [t for _f, t, _k, _b in published]
    assert targets == ["x", "arch"]  # thread note, but both mentions woken
    # the mention reaches x's FEED too (any role)
    feed = client.get("/v1/events", params={"since": 0}, headers={"X-Participant": "x"}).json()["value"]
    assert any(e["kind"] == "message_sent" and "x" in e["data"].get("mentions", []) for e in feed)


def test_unknown_handle_is_prose_not_error(client, rig, published):
    r = client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "note",
                                          "text": "email me @ home or ping @nobody-here"},
                    headers={"X-Participant": "aksou"}).json()
    assert r["ok"], r
    assert published == []


# ----------------------------------------------------------------------- ownership routing

def test_gate_routes_to_epic_owning_human(client, rig, published):
    assert client.patch(f"/v1/tickets/{rig['epic']}", json={"assignee": "arch"},
                        headers={"X-Participant": "aksou"}).json()["ok"]
    r = client.post(f"/v1/gates/{rig['epic']}/design_signoff/open", json={"note": "ready"},
                    headers={"X-Participant": "arch"}).json()
    assert r["ok"], r
    assert published[-1][:3] == ("arch", "aksou", "question")  # NOT the generic 'owner'


def test_other_owner_does_not_see_my_epic_events(client, rig):
    client.post(f"/v1/gates/{rig['epic']}/design_signoff/open", json={"note": "n"},
                headers={"X-Participant": "aksou"})
    mine = client.get("/v1/events", params={"since": 0}, headers={"X-Participant": "aksou"}).json()["value"]
    theirs = client.get("/v1/events", params={"since": 0}, headers={"X-Participant": "x"}).json()["value"]
    assert any(e["kind"] == "gate_opened" for e in mine)
    assert not any(e["kind"] == "gate_opened" for e in theirs)


# ----------------------------------------------------------------------- tokens

def test_token_required_only_when_configured(client, rig, tmp_path):
    ok_before = client.get("/v1/whoami", headers={"X-Participant": "x"}).json()
    assert ok_before["ok"]  # no tokens.json yet -> trusted mode
    (tmp_path / "tokens.json").write_text(json.dumps({"x": "s3cret"}), encoding="utf-8")
    denied = client.get("/v1/whoami", headers={"X-Participant": "x"})
    assert denied.status_code == 401
    allowed = client.get("/v1/whoami", headers={"X-Participant": "x", "X-Token": "s3cret"}).json()
    assert allowed["ok"]
    # agents and un-listed humans are untouched
    assert client.get("/v1/whoami", headers={"X-Participant": "arch"}).json()["ok"]
    assert client.get("/v1/whoami", headers={"X-Participant": "aksou"}).json()["ok"]


def test_asks_on_closed_projects_disappear(client, rig):
    client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "question", "to": "aksou",
                                      "text": "still relevant?"}, headers={"X-Participant": "arch"})
    ctx = client.get("/v1/context", headers={"X-Participant": "aksou"}).json()["value"]
    assert any(a["text"] == "still relevant?" for a in ctx["asks_for_me"])
    assert client.patch(f"/v1/tickets/{rig['epic']}", json={"status": "dropped"},
                        headers={"X-Participant": "aksou"}).json()["ok"]
    ctx = client.get("/v1/context", headers={"X-Participant": "aksou"}).json()["value"]
    assert not any(a["text"] == "still relevant?" for a in ctx["asks_for_me"])


# ----------------------------------------------------------------------- /ui/me

def test_ui_me_renders_and_replies(client, rig, published):
    client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "question", "to": "x",
                                      "text": "your call on the auth boundary?"},
                headers={"X-Participant": "aksou"})
    page = client.get("/ui/me", params={"as": "x"})
    assert page.status_code == 200 and "auth boundary" in page.text
    r = client.post("/ui/me/message", data={"as_": "x", "ticket_id": rig["epic"], "to": "aksou",
                                            "kind": "answer", "text": "option B, keep it server-side"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert published[-1][:3] == ("x", "aksou", "answer")
    thread = client.get("/v1/messages", params={"ticket_id": rig["epic"]},
                        headers={"X-Participant": "aksou"}).json()["value"]
    assert any("option B" in m["text"] for m in thread)


def test_ui_me_gate_answer(client, rig, published):
    client.post(f"/v1/gates/{rig['epic']}/design_signoff/open", json={"note": "n"},
                headers={"X-Participant": "arch"})
    page = client.get("/ui/me", params={"as": "aksou"})
    assert "design_signoff" in page.text
    r = client.post("/ui/me/gate", data={"as_": "aksou", "ticket_id": rig["epic"],
                                         "gate": "design_signoff", "answer": "signed"},
                    follow_redirects=False)
    assert r.status_code == 303
    gates = client.get(f"/v1/gates/{rig['epic']}", headers={"X-Participant": "aksou"}).json()["value"]
    assert gates == []
