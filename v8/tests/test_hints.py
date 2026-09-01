"""Self-describing outputs: hints name the expected next step (the stitch layer)."""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}


@pytest.fixture
def client():
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


@pytest.fixture
def rig(client):
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"),
                           ("eng", "engineer", "agent"), ("craft", "sme", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "w"},
                       headers={"X-Participant": "owner"}).json()["value"]["id"]
    story = client.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "s",
                                             "parent_id": epic}, headers={"X-Participant": "arch"}).json()["value"]["id"]
    return {"epic": epic, "story": story}


def test_task_create_hint_names_the_stitch(client, rig):
    r = client.post("/v1/tickets", json={"kind": "task", "work_type": "feature", "title": "t",
                                         "parent_id": rig["story"]}, headers={"X-Participant": "eng"}).json()
    assert r["ok"], r
    assert "low-level craft" in r["hint"]


def test_strategy_doc_hint_names_extends_and_ruleset(client, rig):
    r = client.post("/v1/docs", json={"doc_type": "strategy_hl", "title": "shape", "body_md": "b",
                                      "scope": rig["epic"]}, headers={"X-Participant": "craft"}).json()
    assert r["ok"], r
    assert "extends" in r["hint"] and "assemble_ruleset" in r["hint"]


def test_context_flags_strategy_links_and_hints_ruleset(client, rig):
    r = client.post("/v1/docs", json={"doc_type": "strategy_hl", "title": "shape", "body_md": "b",
                                      "scope": rig["epic"]}, headers={"X-Participant": "craft"}).json()
    doc = r["value"]["id"]
    assert client.post("/v1/links", json={"from_id": rig["epic"], "to_id": doc, "relation": "uses_strategy"},
                       headers={"X-Participant": "craft"}).json()["ok"]
    assert client.patch(f"/v1/tickets/{rig['story']}", json={"assignee": "eng"},
                        headers={"X-Participant": "arch"}).json()["ok"]
    ctx = client.get("/v1/context", headers={"X-Participant": "eng"}).json()
    assert ctx["ok"], ctx
    blocks = {b["ticket"]["id"]: b for b in ctx["value"]["tickets"]}
    assert blocks[rig["story"]]["strategy_links"] is True  # inherited from the epic
    assert "assemble_ruleset" in ctx["value"]["hint"]


def test_context_without_strategy_links_stays_quiet(client, rig):
    assert client.patch(f"/v1/tickets/{rig['story']}", json={"assignee": "eng"},
                        headers={"X-Participant": "arch"}).json()["ok"]
    ctx = client.get("/v1/context", headers={"X-Participant": "eng"}).json()
    blocks = {b["ticket"]["id"]: b for b in ctx["value"]["tickets"]}
    assert blocks[rig["story"]]["strategy_links"] is False
    assert "assemble_ruleset" not in ctx["value"]["hint"]
