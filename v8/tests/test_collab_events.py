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
def client(board, ui_prefix):
    return TestClient(create_app(board, admin_token="t"))


@pytest.fixture
def published(monkeypatch):
    sent: list[tuple] = []
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: sent.append(a) or True)
    return sent


@pytest.fixture
def rig(client):
    for pid, role, typ in [("owner", "owner", "human"), ("ravi", "qa", "human"),
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
    assert ev["data"]["from_type"] == "human" and ev["data"]["from_role"] == "qa"
    ctx = client.get("/v1/context", headers={"X-Participant": "arch"}).json()["value"]
    ask = next(a for a in ctx["asks_for_me"] if a["text"] == "human here")
    assert ask["from_type"] == "human" and ask["from_role"] == "qa"


def test_message_to_closed_agent_seat_notifies_owner(client, rig, published):
    # a base-role stub ("arch", no ticket) is NOT a seat: no fyi (2026-09-05 flood: 37/45 owner fyis
    # named a stub); a real per-ticket seat with a dead shell pages THIS epic's human owner
    r = client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "question", "to": "arch",
                                          "text": "anyone home?"}, headers={"X-Participant": "ravi"})
    assert r.json()["ok"]
    assert not [x for x in published if "CLOSED seat" in str(x[3])], published
    seat = f"architect.{rig['epic']}"
    client.post("/v1/participants", json={"type": "agent", "role": "architect", "handle": seat, "id": seat},
                headers=ADMIN)
    client.put("/v1/sessions/s-dead", json={"participant_id": seat, "ticket_id": rig["epic"], "pool_id": "local",
                                            "state": "dead", "reason": "closed by self: done"}, headers=ADMIN)
    published.clear()
    r = client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "question", "to": "architect",
                                          "text": "anyone home?"}, headers={"X-Participant": "ravi"})
    assert r.json()["ok"] and r.json()["value"]["to"] == seat  # role resolved to the epic's seat
    fyis = [x for x in published if x[1] == "owner" and f"CLOSED seat {seat}" in str(x[3])]
    assert fyis, published
    assert "spawn(participant_id=" in fyis[0][3]["text"]
    # a HUMAN recipient never triggers the closed-seat path
    published.clear()
    client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "question", "to": "ravi",
                                      "text": "hi"}, headers={"X-Participant": "owner"})
    assert not any("CLOSED seat" in str(x[3]) for x in published)


def test_epic_page_comment_form_posts_as_identity(client, rig, ui_prefix):
    page = client.get(f"{ui_prefix}/epic/{rig['epic']}", params={"as": "ravi"}).text
    assert "Comment on this epic as @ravi" in page
    r = client.post(f"{ui_prefix}/ticket/{rig['epic']}/say", data={"as_": "ravi", "text": "from the browser"},
                    follow_redirects=False)
    assert r.status_code == 303 and f"{ui_prefix}/epic/{rig['epic']}" in r.headers["location"]
    msgs = client.get("/v1/messages", params={"ticket_id": rig["epic"]},
                      headers={"X-Participant": "owner"}).json()["value"]
    assert any(m["created_by"] == "ravi" and m["text"] == "from the browser" for m in msgs)


def test_doc_page_approve_and_comment(client, rig, ui_prefix):
    # a knowledge ticket's criterion is checked by the owner (§24.1 derivation): the strategy-doc
    # sign-off is the one HITL point, so this is where the owner's doc-approve UI shows.
    kt = client.post("/v1/tickets", json={"kind": "story", "work_type": "knowledge", "title": "hl-craft",
                                          "parent_id": rig["epic"]}, headers={"X-Participant": "arch"}).json()["value"]["id"]
    c = client.post("/v1/criteria", json={"ticket_id": kt, "text": "strategy signed", "check": "look"},
                    headers={"X-Participant": "arch"}).json()["value"]
    assert c["checked_by"] == "owner"
    d = client.post("/v1/docs", json={"doc_type": "strategy_hl", "title": "s", "body_md": "b",
                                      "scope": rig["epic"]}, headers={"X-Participant": "craft"}).json()["value"]
    client.patch(f"/v1/criteria/{c['id']}", json={"evidence_ref": d["id"]}, headers={"X-Participant": "craft"})
    page = client.get(f"{ui_prefix}/doc/{d['id']}", params={"as": "owner"}).text
    assert "Approve" in page and "Needs work" in page and "← Epic" in page and "to-top" in page
    r = client.post(f"{ui_prefix}/me/verdict", data={"as_": "owner", "criterion_id": c["id"], "ticket_id": kt,
                                            "verdict": "pass", "evidence_version": 1,
                                            "back": f"{ui_prefix}/doc/{d['id']}?as=owner"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"{ui_prefix}/doc/{d['id']}")
    r2 = client.post(f"{ui_prefix}/doc/{d['id']}/comment", data={"as_": "ravi", "text": "solid @arch"},
                     follow_redirects=False)
    assert r2.status_code == 303
    msgs = client.get("/v1/messages", params={"ticket_id": rig["epic"]},
                      headers={"X-Participant": "owner"}).json()["value"]
    assert any(m["created_by"] == "ravi" and m["text"].startswith(f"[doc {d['id']} v1]") for m in msgs)


def test_thread_newest_first_default_with_toggle(client, rig, ui_prefix):
    for i in range(3):
        client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "note", "text": f"m{i}"},
                    headers={"X-Participant": "owner"})
    convo = client.get(f"{ui_prefix}/epic/{rig['epic']}", params={"as": "owner"}).text.split("class='conversation'")[1]
    assert convo.index(">m2<") < convo.index(">m0<")  # newest first
    assert "order=oldest" in client.get(f"{ui_prefix}/epic/{rig['epic']}", params={"as": "owner"}).text
    convo_old = client.get(f"{ui_prefix}/epic/{rig['epic']}",
                           params={"as": "owner", "order": "oldest"}).text.split("class='conversation'")[1]
    assert convo_old.index(">m0<") < convo_old.index(">m2<")
