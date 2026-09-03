"""Human-collaboration events: who/what verdicts, sender identity, closed-seat fyi,
doc approve + epic comments from the UI, thread ordering."""

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


@pytest.fixture
def rig(client):
    for pid, role, typ in [("owner", "owner", "human"), ("ravi", "reviewer", "human"),
                           ("arch", "architect", "agent"), ("craft", "sme", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "w"},
                       headers={"X-Participant": "owner"}).json()["value"]["id"]
    return {"epic": epic}


def _events(client, subject):
    return client.get("/v1/events", params={"subject_id": subject},
                      headers={"X-Participant": "owner"}).json()["value"]


def test_verdict_is_a_first_class_event_with_who(client, rig):
    c = client.post("/v1/criteria", json={"ticket_id": rig["epic"], "text": "t", "check": "look",
                                          "checked_by": "owner"}, headers={"X-Participant": "arch"}).json()["value"]
    d = client.post("/v1/docs", json={"doc_type": "strategy_hl", "title": "s", "body_md": "b",
                                      "scope": rig["epic"]}, headers={"X-Participant": "craft"}).json()["value"]
    client.patch(f"/v1/criteria/{c['id']}", json={"evidence_ref": d["id"]}, headers={"X-Participant": "craft"})
    client.patch(f"/v1/criteria/{c['id']}", json={"verdict": "pass"}, headers={"X-Participant": "owner"})
    ev = [e for e in _events(client, rig["epic"]) if e["kind"] == "criterion_checked"][-1]
    assert ev["data"]["by"] == "owner" and ev["data"]["by_type"] == "human"
    assert ev["data"]["verdict"] == "pass" and ev["data"]["evidence"] == d["id"]


def test_message_events_and_asks_carry_sender_identity(client, rig):
    client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "question", "to": "arch",
                                      "text": "human here"}, headers={"X-Participant": "ravi"})
    ev = [e for e in _events(client, rig["epic"]) if e["kind"] == "message_sent"][-1]
    assert ev["data"]["from_type"] == "human" and ev["data"]["from_role"] == "reviewer"
    ctx = client.get("/v1/context", headers={"X-Participant": "arch"}).json()["value"]
    ask = next(a for a in ctx["asks_for_me"] if a["text"] == "human here")
    assert ask["from_type"] == "human" and ask["from_role"] == "reviewer"


def test_message_to_closed_agent_seat_notifies_owner(client, rig, published):
    r = client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "question", "to": "arch",
                                          "text": "anyone home?"}, headers={"X-Participant": "ravi"})
    assert r.json()["ok"]
    fyis = [x for x in published if x[1] == "owner" and "CLOSED seat arch" in str(x[3])]
    assert fyis, published
    # a HUMAN recipient never triggers the closed-seat path
    published.clear()
    client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "question", "to": "ravi",
                                      "text": "hi"}, headers={"X-Participant": "owner"})
    assert not any("CLOSED seat" in str(x[3]) for x in published)


def test_epic_page_comment_form_posts_as_identity(client, rig):
    page = client.get(f"/ui/epic/{rig['epic']}", params={"as": "ravi"}).text
    assert "Comment on this epic as @ravi" in page
    r = client.post(f"/ui/ticket/{rig['epic']}/say", data={"as_": "ravi", "text": "from the browser"},
                    follow_redirects=False)
    assert r.status_code == 303 and f"/ui/epic/{rig['epic']}" in r.headers["location"]
    msgs = client.get("/v1/messages", params={"ticket_id": rig["epic"]},
                      headers={"X-Participant": "owner"}).json()["value"]
    assert any(m["created_by"] == "ravi" and m["text"] == "from the browser" for m in msgs)


def test_doc_page_approve_and_comment(client, rig):
    c = client.post("/v1/criteria", json={"ticket_id": rig["epic"], "text": "strategy signed", "check": "look",
                                          "checked_by": "owner"}, headers={"X-Participant": "arch"}).json()["value"]
    d = client.post("/v1/docs", json={"doc_type": "strategy_hl", "title": "s", "body_md": "b",
                                      "scope": rig["epic"]}, headers={"X-Participant": "craft"}).json()["value"]
    client.patch(f"/v1/criteria/{c['id']}", json={"evidence_ref": d["id"]}, headers={"X-Participant": "craft"})
    page = client.get(f"/ui/doc/{d['id']}", params={"as": "owner"}).text
    assert "Approve" in page and "Needs work" in page and "← Epic" in page and "to-top" in page
    r = client.post("/ui/me/verdict", data={"as_": "owner", "criterion_id": c["id"], "ticket_id": rig["epic"],
                                            "verdict": "pass", "back": f"/ui/doc/{d['id']}?as=owner"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/ui/doc/{d['id']}")
    r2 = client.post(f"/ui/doc/{d['id']}/comment", data={"as_": "ravi", "text": "solid @arch"},
                     follow_redirects=False)
    assert r2.status_code == 303
    msgs = client.get("/v1/messages", params={"ticket_id": rig["epic"]},
                      headers={"X-Participant": "owner"}).json()["value"]
    assert any(m["created_by"] == "ravi" and m["text"].startswith(f"[doc {d['id']} v1]") for m in msgs)


def test_thread_newest_first_default_with_toggle(client, rig):
    for i in range(3):
        client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "note", "text": f"m{i}"},
                    headers={"X-Participant": "owner"})
    convo = client.get(f"/ui/epic/{rig['epic']}", params={"as": "owner"}).text.split("class='conversation'")[1]
    assert convo.index(">m2<") < convo.index(">m0<")  # newest first
    assert "order=oldest" in client.get(f"/ui/epic/{rig['epic']}", params={"as": "owner"}).text
    convo_old = client.get(f"/ui/epic/{rig['epic']}", params={"as": "owner", "order": "oldest"}).text.split("class='conversation'")[1]
    assert convo_old.index(">m0<") < convo_old.index(">m2<")
