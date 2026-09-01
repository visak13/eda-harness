"""HITL sign-off on /ui/me: owner-checked criteria render their doc and take verdicts."""

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
                           ("craft", "sme", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "w"},
                       headers={"X-Participant": "owner"}).json()["value"]["id"]
    kt = client.post("/v1/tickets", json={"kind": "story", "work_type": "knowledge", "title": "hl-craft",
                                          "parent_id": epic, "assignee": "craft"},
                     headers={"X-Participant": "arch"}).json()["value"]["id"]
    c = client.post("/v1/criteria", json={"ticket_id": kt, "text": "strategy doc signed by the owner",
                                          "check": "look", "checked_by": "owner"},
                    headers={"X-Participant": "arch"}).json()["value"]["id"]
    d = client.post("/v1/docs", json={"doc_type": "strategy_hl", "title": "shape",
                                      "body_md": "# Walking skeleton\n- build the **thin** thread first",
                                      "scope": epic}, headers={"X-Participant": "craft"}).json()["value"]["id"]
    assert client.patch(f"/v1/criteria/{c}", json={"evidence_ref": d},
                        headers={"X-Participant": "craft"}).json()["ok"]
    return {"epic": epic, "kt": kt, "crit": c, "doc": d}


def test_signoff_renders_markdown_and_takes_verdict(client, rig):
    page = client.get("/ui/me", params={"as": "owner"}).text
    assert "Docs awaiting your sign-off" in page
    assert "<strong>thin</strong>" in page  # markdown RENDERED, not raw
    r = client.post("/ui/me/verdict", data={"as_": "owner", "criterion_id": rig["crit"],
                                            "ticket_id": rig["kt"], "verdict": "pass",
                                            "note": "good shape, proceed"}, follow_redirects=False)
    assert r.status_code == 303
    crit = client.get("/v1/criteria", params={"ticket_id": rig["kt"]},
                      headers={"X-Participant": "owner"}).json()["value"][0]
    assert crit["verdict"] == "pass"
    page2 = client.get("/ui/me", params={"as": "owner"}).text
    assert "Docs awaiting your sign-off" not in page2  # nothing pending anymore


def test_doc_page_renders_markdown(client, rig):
    page = client.get(f"/ui/doc/{rig['doc']}").text
    assert "<h1>Walking skeleton</h1>" in page and "<pre>#" not in page
