"""Field-report fixes: ack-before-finish, steers in context, close reasons,
criterion text edits, extends validation, ruleset graceful skips."""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter, bundles
from edp8.board import Board, BoardError
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.schemas import Role, SessionState
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
def rig(client):
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"),
                           ("eng", "engineer", "agent"), ("craft", "sme", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "w"},
                       headers={"X-Participant": "owner"}).json()["value"]["id"]
    return {"epic": epic}


def test_steer_surfaces_in_context(client, rig):
    r = client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "steer", "to": "eng",
                                          "text": "verify s-X criteria only"}, headers={"X-Participant": "owner"})
    assert r.json()["ok"]
    ctx = client.get("/v1/context", headers={"X-Participant": "eng"}).json()["value"]
    assert any("verify s-X" in a["text"] for a in ctx["asks_for_me"])


def test_seat_participant_sees_its_ticket_unassigned(client, rig):
    client.post("/v1/participants", json={"type": "agent", "role": "reviewer",
                                          "handle": f"reviewer.{rig['epic']}", "id": f"reviewer.{rig['epic']}"},
                headers=ADMIN)
    who = client.get("/v1/whoami", headers={"X-Participant": f"reviewer.{rig['epic']}"}).json()["value"]
    assert rig["epic"] in who["tickets"]  # named for the ticket -> surfaced even unassigned


def test_finish_refuses_with_pending_asks(client, rig, monkeypatch):
    set_client(BoardClient(participant="eng", admin_token="t", client=client))
    monkeypatch.setenv("EDP8_PARTICIPANT", "eng")
    client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "question", "to": "eng",
                                      "text": "blocking q"}, headers={"X-Participant": "owner"})
    out = ALL_TOOLS["finish"].handler(ALL_TOOLS["finish"].args_model())
    assert out["ok"] is False and out["error"]["code"] == "precondition"
    assert "blocking q" in out["error"]["message"]


def test_close_reason_reaches_feed_and_broker(client, rig, monkeypatch):
    sent = []
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: sent.append(a) or True)
    body = {"participant_id": "arch", "ticket_id": rig["epic"], "pool_id": "local",
            "state": "alive"}
    client.put("/v1/sessions/s-9", json=body, headers=ADMIN)
    client.put("/v1/sessions/s-9", json={**body, "state": "dead",
                                         "reason": "finish: job recorded (closed after idle)"}, headers=ADMIN)
    evs = client.get("/v1/events", params={"subject_id": rig["epic"]},
                     headers={"X-Participant": "owner"}).json()["value"]
    dead = [e for e in evs if e["kind"] == "shell_dead"]
    assert dead and dead[-1]["data"]["clean"] is True
    assert "finish" in dead[-1]["data"]["reason"]
    assert sent[-1][2] == "fyi"  # clean close is not a crash notice


def test_criterion_text_edit_and_unknown_kwarg(client, rig):
    c = client.post("/v1/criteria", json={"ticket_id": rig["epic"], "text": "old", "check": "verdict",
                                          "checked_by": "qa"}, headers={"X-Participant": "arch"}).json()["value"]
    r = client.patch(f"/v1/criteria/{c['id']}", json={"text": "new wording"},
                     headers={"X-Participant": "arch"}).json()
    assert r["ok"] and r["value"]["text"] == "new wording"
    bad = client.patch(f"/v1/criteria/{c['id']}", json={"wording": "nope"}, headers={"X-Participant": "arch"})
    assert bad.status_code == 422  # unknown kwarg is an ERROR, not a silent drop


def test_extends_must_link_docs(client, rig):
    d = client.post("/v1/docs", json={"doc_type": "strategy_hl", "title": "t", "body_md": "b",
                                      "scope": rig["epic"]}, headers={"X-Participant": "craft"}).json()["value"]
    bad = client.post("/v1/links", json={"from_id": d["id"], "to_id": rig["epic"], "relation": "extends"},
                      headers={"X-Participant": "arch"}).json()
    assert bad["ok"] is False and "DOCS only" in bad["error"]["message"]


def test_ruleset_skips_dangling_layer(client, rig, board):
    set_client(BoardClient(participant="arch", admin_token="t", client=client))
    d = client.post("/v1/docs", json={"doc_type": "strategy_hl", "title": "t", "body_md": "- rule one",
                                      "scope": rig["epic"]}, headers={"X-Participant": "craft"}).json()["value"]
    client.post("/v1/links", json={"from_id": rig["epic"], "to_id": d["id"], "relation": "uses_strategy"},
                headers={"X-Participant": "arch"})
    # forge a legacy dangling extends (doc -> ticket) directly in the store, bypassing the new guard
    from edp8.schemas import Link, Relation
    board.store.put("link", Link(id="lk-bad", from_id=d["id"], to_id=rig["epic"], relation=Relation.extends,
                                 created_by="arch"))
    out = ALL_TOOLS["assemble_ruleset"].handler(
        ALL_TOOLS["assemble_ruleset"].args_model(ticket_id=rig["epic"]))
    assert out["ok"], out
    assert out["value"]["skipped_layers"] == [rig["epic"]]
    assert any("rule one" in x["text"] for x in out["value"]["constructive"])
