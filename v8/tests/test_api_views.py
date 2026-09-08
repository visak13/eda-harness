"""Shape + scoping tests for the JSON API (src/edp8/api_views.py, design §4.1, was S3).

Every endpoint is a thin adapter over views.py, so these assert the ENVELOPE and the
owner-scoping/auth rules the adapter owns — not the derivations themselves (tests/test_views.py
pins those against the legacy HTML). The verdict write path, evidence_version and the
stale-verdict refusal ride board.criterion_update's evidence_version/stale_ok kwargs (§14).
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


# --------------------------------------------------------------------------- verdict + evidence_version (§14)


def test_verdict_records_and_stores_version(rig):
    c = rig["client"]
    r = c.post("/v1/me/verdict", json={"criterion_id": rig["kcrit"], "verdict": "pass",
                                       "ticket_id": rig["kt"], "evidence_version": 1,
                                       "note": "looks right"}, headers=OWN).json()
    assert r["ok"], r
    assert r["value"]["criterion"]["verdict"] == "pass"
    assert r["value"]["criterion"]["evidence_version"] == 1
    assert r["value"]["message"] is not None  # a note was posted to the assignee
    # the version rode the criterion_checked event too
    evs = c.get("/v1/events", params={"subject_id": rig["kt"]}, headers=OWN).json()["value"]
    checked = [e for e in evs if e["kind"] == "criterion_checked"]
    assert checked and checked[-1]["data"]["evidence_version"] == 1


def test_verdict_refuses_stale_version_unless_ok(rig):
    c = rig["client"]
    # author moves the doc to v2 after the owner read v1
    up = c.patch(f"/v1/docs/{rig['doc']}", json={"body_md": "# v2 body"},
                 headers={"X-Participant": "craft"}).json()
    assert up["ok"] and up["value"]["version"] == 2
    stale = c.post("/v1/me/verdict", json={"criterion_id": rig["kcrit"], "verdict": "pass",
                                           "ticket_id": rig["kt"], "evidence_version": 1}, headers=OWN)
    assert stale.status_code == 409 and not stale.json()["ok"]
    okr = c.post("/v1/me/verdict", json={"criterion_id": rig["kcrit"], "verdict": "pass",
                                         "ticket_id": rig["kt"], "evidence_version": 1,
                                         "stale_ok": True}, headers=OWN).json()
    assert okr["ok"] and okr["value"]["criterion"]["evidence_version"] == 1


def test_docs_html_serves_named_version(rig):
    c = rig["client"]
    c.patch(f"/v1/docs/{rig['doc']}", json={"body_md": "# second"}, headers={"X-Participant": "craft"})
    v1 = c.get(f"/v1/docs/{rig['doc']}/html", params={"version": 1}, headers=OWN).json()["value"]
    cur = c.get(f"/v1/docs/{rig['doc']}/html", headers=OWN).json()["value"]
    assert "Walking skeleton" in v1["html"] and v1["version"] == 1
    assert "second" in cur["html"] and cur["version"] == 2


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


def test_seats_lists_agent_seats_closed_and_humans(rig):
    """GET /v1/seats (S10, design §4.2/§18.3): agent seats — closed ones INCLUDED with their
    reason — plus a People block of humans, and each seat's latest record_status separate from
    presence. Composed from participants + sessions + status messages."""
    c = rig["client"]
    story, seat = rig["story"], rig["seat"]

    # The engineer seat records a status → it should surface as latest_status (note, role, time),
    # with the "[reviewed]" prefix stripped to the plain note.
    r = c.post("/v1/status", json={"ticket_id": story, "status": "reviewed",
                                   "note": "Owner checks are ready for review."},
               headers={"X-Participant": seat})
    assert r.json()["ok"], r.json()

    # A parked seat and a CLOSED (dead + reason) seat, each its own participant + session.
    for pid, role, state, sid, reason in [
        (f"reviewer.{story}", "reviewer", "parked", "sid-parked", ""),
        (f"qa.{story}", "qa", "dead", "sid-dead", "closed by self: work completed; session saved"),
    ]:
        c.post("/v1/participants", json={"type": "agent", "role": role, "handle": pid, "id": pid}, headers=ADMIN)
        c.put(f"/v1/sessions/{sid}", json={"participant_id": pid, "ticket_id": story, "pool_id": "local",
                                           "state": state, "reason": reason}, headers=ADMIN)

    val = _get(rig, "/v1/seats")
    seats = {s["id"]: s for s in val["seats"]}
    people = {p["id"]: p for p in val["people"]}

    # Humans in the People block, no seat state anywhere on them.
    assert people["owner"]["role"] == "owner" and "state" not in people["owner"]
    assert "ravi" in people

    # The alive engineer seat: state, ticket title, and its latest status (prefix stripped).
    eng = seats[seat]
    assert eng["state"] == "alive"
    assert eng["ticket_title"] == "fix the ship sheet"
    assert eng["latest_status"]["text"] == "Owner checks are ready for review."
    assert eng["latest_status"]["status"] == "reviewed"
    assert eng["latest_status"]["role"] == "engineer"

    # The closed seat is present WITH its reason verbatim (never dropped from the list).
    closed = seats[f"qa.{story}"]
    assert closed["state"] == "dead"
    assert closed["reason"] == "closed by self: work completed; session saved"

    # The parked seat is present; the sme seat 'craft' never had a session → state None (unknown).
    assert seats[f"reviewer.{story}"]["state"] == "parked"
    assert seats["craft"]["state"] is None
    assert seats["craft"]["latest_status"] is None  # never recorded a status

    # Alive sorts before parked before dead (folio-seats order).
    order = [s["id"] for s in val["seats"]]
    assert order.index(seat) < order.index(f"reviewer.{story}") < order.index(f"qa.{story}")


def test_seats_readable_by_any_participant(rig):
    """Seats is not owner-scoped — any authenticated participant sees the roster (parity with
    /v1/sessions). A reviewer gets the same shape as the owner."""
    r = rig["client"].get("/v1/seats", headers=RAVI).json()
    assert r["ok"], r
    assert "seats" in r["value"] and "people" in r["value"]
