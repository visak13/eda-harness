"""Shape + scoping tests for the JSON API (src/edp8/api_views.py, design §4.1, was S3).

Every endpoint is a thin adapter over views.py, so these assert the ENVELOPE and the
owner-scoping/auth rules the adapter owns — not the derivations themselves (tests/test_views.py
pins those against the legacy HTML). The verdict write path, evidence_version and the
stale-verdict refusal ride board.criterion_update's new kwargs and are covered with the
schema/board hunks; this file is the read surface plus avatar read/write.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter
from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
OWN = {"X-Participant": "owner"}
RAVI = {"X-Participant": "ravi"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


@pytest.fixture
def rig(client):
    def post(path, body, headers):
        r = client.post(path, json=body, headers=headers).json()
        assert r["ok"], r
        return r["value"]

    for pid, role, typ in [("owner", "owner", "human"), ("ravi", "reviewer", "human"),
                           ("arch", "architect", "agent"), ("craft", "sme", "agent")]:
        post("/v1/participants", {"type": typ, "role": role, "handle": pid, "id": pid}, ADMIN)
    epic = post("/v1/tickets", {"kind": "epic", "work_type": "feature", "title": "Galaxy site"}, OWN)["id"]
    story = post("/v1/tickets", {"kind": "story", "work_type": "bug", "title": "fix the ship sheet",
                                 "parent_id": epic, "tags": ["assets"]}, {"X-Participant": "arch"})["id"]
    seat = f"engineer.{story}"
    post("/v1/participants", {"type": "agent", "role": "engineer", "handle": seat, "id": seat}, ADMIN)
    client.put("/v1/sessions/sid-1", json={"participant_id": seat, "ticket_id": story, "pool_id": "local",
                                           "state": "alive"}, headers=ADMIN)
    post("/v1/criteria", {"ticket_id": story, "text": "the ship sheet renders", "check": "command"},
         {"X-Participant": "arch"})
    kt = post("/v1/tickets", {"kind": "story", "work_type": "knowledge", "title": "hl-craft",
                              "parent_id": epic, "assignee": "craft"}, {"X-Participant": "arch"})["id"]
    kcrit = post("/v1/criteria", {"ticket_id": kt, "text": "strategy doc signed by the owner",
                                  "check": "look", "checked_by": "owner"}, {"X-Participant": "arch"})["id"]
    doc = post("/v1/docs", {"doc_type": "strategy_hl", "title": "shape",
                            "body_md": "# Walking skeleton\n- build the **thin** thread first",
                            "scope": epic}, {"X-Participant": "craft"})["id"]
    client.patch(f"/v1/criteria/{kcrit}", json={"evidence_ref": doc}, headers={"X-Participant": "craft"})
    post("/v1/messages", {"ticket_id": story, "kind": "question", "to": "owner", "text": "one?"}, RAVI)
    return {"client": client, "epic": epic, "story": story, "seat": seat, "kt": kt, "kcrit": kcrit, "doc": doc}


def _get(rig, path, **params):
    r = rig["client"].get(path, params=params or None, headers=OWN)
    j = r.json()
    assert j["ok"], j
    return j["value"]


# --------------------------------------------------------------------------- me


def test_decisions_owner_sees_signoff(rig):
    v = _get(rig, "/v1/me/decisions")
    assert v["counts"]["signoffs"] == 1
    so = v["signoffs"][0]
    assert so["criterion"]["id"] == rig["kcrit"]
    assert so["ticket"]["id"] == rig["kt"] and so["ticket"]["epic_id"] == rig["epic"]
    assert so["doc"]["id"] == rig["doc"] and so["doc"]["doc_type"] == "strategy_hl"
    assert "thin" in so["excerpt"]
    assert isinstance(v["gates"], list)


def test_decisions_non_owner_empty_signoffs_and_gates(rig):
    r = rig["client"].get("/v1/me/decisions", headers=RAVI).json()
    assert r["ok"], r
    assert r["value"]["signoffs"] == [] and r["value"]["gates"] == []


def test_people_and_conversations_and_summary(rig):
    people = _get(rig, "/v1/me/people")
    seats = {p["id"]: p for p in people}
    assert rig["seat"] in seats and seats[rig["seat"]]["seat_state"] == "alive"
    assert "owner" not in seats  # people_for excludes the viewer
    convos = _get(rig, "/v1/me/conversations")
    assert any(c["ticket_id"] == rig["story"] and c["unread"] for c in convos)
    summary = _get(rig, "/v1/me/summary")
    assert summary["participant"]["id"] == "owner"
    assert summary["counts"]["waiting_on_you"] >= 1 and "last_seq" in summary


# --------------------------------------------------------------------------- epics / tickets


def test_epics_summary_row(rig):
    rows = {e["id"]: e for e in _get(rig, "/v1/epics/summary")}
    e = rows[rig["epic"]]
    assert e["title"] == "Galaxy site" and e["criteria"]["total"] == 0
    assert "reason" in e["waiting_reason"] and "presence" in e["waiting_reason"]


def test_tickets_table_and_page(rig):
    tbl = _get(rig, "/v1/tickets/table")
    row = next(r for r in tbl["rows"] if r["id"] == rig["story"])
    assert row["epic_id"] == rig["epic"] and row["tags"] == ["assets"]
    assert row["criteria"] == {"passed": 0, "failed": 0, "pending": 1, "total": 1}
    page = _get(rig, f"/v1/tickets/{rig['story']}/page")
    assert page["ticket"]["id"] == rig["story"] and page["epic_id"] == rig["epic"]
    assert len(page["criteria"]) == 1 and page["criteria"][0]["check"] == "command"


def test_epic_page(rig):
    page = _get(rig, f"/v1/epics/{rig['epic']}/page")
    assert "board" in page and "thread" in page and isinstance(page["docs"], list)


# --------------------------------------------------------------------------- docs / activity / library


def test_docs_html_sanitised_with_signoff(client):
    # a doc containing a script tag and an inline handler → the rendered html carries neither
    def post(path, body, headers):
        r = client.post(path, json=body, headers=headers).json()
        assert r["ok"], r
        return r["value"]

    post("/v1/participants", {"type": "human", "role": "owner", "handle": "owner", "id": "owner"}, ADMIN)
    post("/v1/participants", {"type": "agent", "role": "architect", "handle": "arch", "id": "arch"}, ADMIN)
    post("/v1/participants", {"type": "agent", "role": "sme", "handle": "craft", "id": "craft"}, ADMIN)
    epic = post("/v1/tickets", {"kind": "epic", "work_type": "feature", "title": "E"}, OWN)["id"]
    kt = post("/v1/tickets", {"kind": "story", "work_type": "knowledge", "title": "k",
                              "parent_id": epic, "assignee": "craft"}, {"X-Participant": "arch"})["id"]
    kcrit = post("/v1/criteria", {"ticket_id": kt, "text": "signed", "check": "look", "checked_by": "owner"},
                 {"X-Participant": "arch"})["id"]
    body = "# Title\n\n<script>alert(1)</script>\n<img src=x onerror=alert(2)>\n\n[safe](https://ok.test)"
    doc = post("/v1/docs", {"doc_type": "strategy_hl", "title": "d", "body_md": body, "scope": epic},
               {"X-Participant": "craft"})["id"]
    client.patch(f"/v1/criteria/{kcrit}", json={"evidence_ref": doc}, headers={"X-Participant": "craft"})

    v = client.get(f"/v1/docs/{doc}/html", headers=OWN).json()["value"]
    assert "<script" not in v["html"] and "onerror" not in v["html"]
    assert "<h1>Title</h1>" in v["html"] and "https://ok.test" in v["html"]
    assert v["versions"] and v["signoff_criterion"]["id"] == kcrit


def test_activity_and_library(rig):
    days = _get(rig, "/v1/activity")
    assert isinstance(days, list) and all("events" in d for d in days)
    lib = _get(rig, "/v1/library")
    assert any(d["id"] == rig["doc"] for d in lib["docs"])
    assert isinstance(lib["artifacts"], list) and isinstance(lib["links"], list)


# --------------------------------------------------------------------------- avatars


def test_avatar_svg_headers_and_palette(rig):
    r = rig["client"].get("/v1/avatars/owner.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert "max-age=300" in r.headers["cache-control"] and "<svg" in r.text
    # palette override renders a specific human avatar even for a seat id
    r2 = rig["client"].get(f"/v1/avatars/{rig['seat']}.svg", params={"palette": "human-03"})
    assert r2.status_code == 200 and "<svg" in r2.text


def test_me_avatar_get_put_persists_across_app(rig):
    got = _get(rig, "/v1/me/avatar")
    assert got["avatar_id"] in {f"human-{n:02d}" for n in range(1, 9)}
    assert len(got["catalog"]) == 8
    put = rig["client"].put("/v1/me/avatar", json={"avatar_id": "human-05"}, headers=OWN).json()
    assert put["ok"] and put["value"]["avatar_id"] == "human-05"
    # a fresh create_app() re-reads ui-avatars.json → the choice survives
    again = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
    again.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner", "id": "owner"},
               headers=ADMIN)
    v = again.get("/v1/me/avatar", headers=OWN).json()["value"]
    assert v["avatar_id"] == "human-05"


def test_me_avatar_rejects_bad_id(rig):
    r = rig["client"].put("/v1/me/avatar", json={"avatar_id": "nope"}, headers=OWN).json()
    assert not r["ok"] and r["error"]["code"] == "bad_request"


# --------------------------------------------------------------------------- messages / mentions


def test_unresolved_mentions_on_message(rig):
    r = rig["client"].post("/v1/messages", json={"ticket_id": rig["story"], "kind": "note",
                                                 "text": "ping @owner and @ghost"}, headers=OWN).json()
    assert r["ok"], r
    assert r["value"]["unresolved_mentions"] == ["ghost"]


# --------------------------------------------------------------------------- auth (tokens.json)


def test_tokens_require_x_token(monkeypatch, tmp_path):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    (tmp_path / "tokens.json").write_text(json.dumps({"owner": "s3cr3t", "agents": {}}), encoding="utf-8")
    monkeypatch.setenv("EDP8_HOME", str(tmp_path))
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "tokens.json"))
    c = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
    c.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner", "id": "owner"},
           headers=ADMIN)
    assert c.get("/v1/me/summary", headers=OWN).status_code == 401
    r = c.get("/v1/me/summary", headers={**OWN, "X-Token": "s3cr3t"}).json()
    assert r["ok"], r
