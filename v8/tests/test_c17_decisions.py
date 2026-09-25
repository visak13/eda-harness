"""C17 (s-5e83f9d0af, design-10b21760d9 §14.2): the board half of the Decisions tab.

- GET /v1/decisions?scope=<ticket>: the scope's live + withdrawn decisions (a ticket and every ticket
  under it), live binding first then newest, with the row fields the tab shows; the epic's
  participants only.
- POST /v1/decisions with text/detail over the limit: a typed 422 naming the limit (it was a 500).
- POST /v1/me/verdict: a note that fails after the verdict landed is `note_error` on a 200.
- POST /v1/docs/{id}/approve|reject: optional expected_version; a moved-on proposal is a typed 409.
"""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter, delivery
from edp8.board import Board
from edp8.schemas import DECISION_DETAIL_MAX, DECISION_TEXT_MAX
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
OWN = {"X-Participant": "owner"}
ARCH = {"X-Participant": "arch"}


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    board = Board(Store(":memory:"))
    client = TestClient(create_app(board, admin_token="t"), raise_server_exceptions=False)

    def post(path, body, headers):
        r = client.post(path, json=body, headers=headers).json()
        assert r["ok"], r
        return r["value"]

    for pid, role, typ in [("owner", "owner", "human"), ("owner2", "owner", "human"),
                           ("arch", "architect", "agent"), ("craft", "sme", "agent"),
                           ("stranger", "engineer", "agent")]:
        post("/v1/participants", {"type": typ, "role": role, "handle": pid, "id": pid}, ADMIN)
    epic = post("/v1/tickets", {"kind": "epic", "work_type": "feature", "title": "Galaxy site"}, OWN)["id"]
    story = post("/v1/tickets", {"kind": "story", "work_type": "feature", "title": "ship sheet",
                                 "parent_id": epic}, ARCH)["id"]
    other = post("/v1/tickets", {"kind": "story", "work_type": "feature", "title": "star map",
                                 "parent_id": epic}, ARCH)["id"]
    task = post("/v1/tickets", {"kind": "task", "work_type": "feature", "title": "ship sheet css",
                                "parent_id": story}, ARCH)["id"]
    seat = f"engineer.{story}"
    post("/v1/participants", {"type": "agent", "role": "engineer", "handle": seat, "id": seat}, ADMIN)
    # another owner's epic, with its own decision: never listed under this epic
    foreign = post("/v1/tickets", {"kind": "epic", "work_type": "feature", "title": "Other"},
                   {"X-Participant": "owner2"})["id"]
    return {"client": client, "board": board, "post": post, "epic": epic, "story": story, "other": other,
            "task": task, "seat": seat, "foreign": foreign}


def _decide(rig, scope, text, headers=ARCH, **kw):
    return rig["post"]("/v1/decisions", {"scope": scope, "text": text, **kw}, headers)


def _list(rig, scope, headers=OWN):
    r = rig["client"].get("/v1/decisions", params={"scope": scope}, headers=headers)
    return r.status_code, r.json()


# --------------------------------------------------------------------------- the list route


def test_epic_scope_lists_its_own_and_every_descendant_decision_binding_first_then_newest(rig):
    b = rig["board"]
    msg = rig["post"]("/v1/messages", {"ticket_id": rig["story"], "kind": "note", "text": "we pick CSS grid"},
                      {"X-Participant": rig["seat"]})
    old_bind = _decide(rig, rig["epic"], "binding rule on the epic", binding=True)
    on_story = _decide(rig, rig["story"], "grid on the ship sheet", detail="why: two columns", source=msg["id"])
    on_task = _decide(rig, rig["task"], "css in one file")
    on_other = _decide(rig, rig["other"], "star map uses svg")
    gone = _decide(rig, rig["epic"], "withdrawn later")
    rig["client"].post(f"/v1/decisions/{gone['id']}/withdraw", json={"reason": "mistaken"}, headers=OWN)
    replaced = _decide(rig, rig["epic"], "first take")
    succ = _decide(rig, rig["epic"], "second take", replaces=[replaced["id"]])
    _decide(rig, rig["foreign"], "not ours", headers={"X-Participant": "owner2"})
    # make the order observable: decided_at strictly increasing in creation order, the binding one oldest
    base = old_bind and b.store.get("decision", old_bind["id"]).created_at
    for i, did in enumerate([old_bind["id"], on_story["id"], on_task["id"], on_other["id"], gone["id"], succ["id"]]):
        d = b.store.get("decision", did)
        d.decided_at = base + timedelta(minutes=i)
        b.store.put("decision", d)

    code, j = _list(rig, rig["epic"])
    assert code == 200 and j["ok"], j
    v = j["value"]
    ids = [r["id"] for r in v["decisions"]]
    # binding (live) first, then newest; replaced and other epics' records absent
    assert ids == [old_bind["id"], succ["id"], gone["id"], on_other["id"], on_task["id"], on_story["id"]]
    assert replaced["id"] not in ids
    assert v["counts"] == {"live": 5, "withdrawn": 1}
    assert v["can_manage"] is True and v["epic"] == rig["epic"]
    row = next(r for r in v["decisions"] if r["id"] == on_story["id"])
    for k in ("text", "detail", "source", "decided_by", "decided_at", "binding", "status", "replaces"):
        assert k in row, k
    assert row["detail"] == "why: two columns" and row["decided_by"] == "arch"
    assert row["source"] == msg["id"] and row["source_kind"] == "message" and row["source_ticket"] == rig["story"]
    assert next(r for r in v["decisions"] if r["id"] == succ["id"])["replaces"] == [replaced["id"]]
    w = next(r for r in v["decisions"] if r["id"] == gone["id"])
    assert w["status"] == "withdrawn" and w["withdrawn_reason"] == "mistaken"


def test_story_scope_lists_the_story_and_its_tasks_only(rig):
    s = _decide(rig, rig["story"], "story rule")
    t = _decide(rig, rig["task"], "task rule")
    _decide(rig, rig["epic"], "epic rule")
    _decide(rig, rig["other"], "sibling rule")
    code, j = _list(rig, rig["story"], headers={"X-Participant": rig["seat"]})
    assert code == 200, j
    assert {r["id"] for r in j["value"]["decisions"]} == {s["id"], t["id"]}
    assert j["value"]["can_manage"] is False  # an engineer seat reads, never manages


def test_refused_to_non_participants_with_a_typed_403(rig):
    _decide(rig, rig["epic"], "rule")
    for who in ("stranger", "owner2"):  # an unrelated seat; another human owner of another epic
        code, j = _list(rig, rig["epic"], headers={"X-Participant": who})
        assert code == 403 and j["ok"] is False and j["error"]["code"] == "forbidden", (who, j)
    # participants: the epic's owner, its architect (created its stories), a seat named for one of its tickets
    for who in ("owner", "arch", rig["seat"]):
        code, j = _list(rig, rig["story"], headers={"X-Participant": who})
        assert code == 200 and j["ok"], (who, j)


def test_unknown_scope_is_a_typed_refusal_not_a_500(rig):
    code, j = _list(rig, "s-doesnotexist")
    assert code < 500 and j["ok"] is False


# --------------------------------------------------------------------------- the 240-char 500


@pytest.mark.parametrize("field,cap", [("text", DECISION_TEXT_MAX), ("detail", DECISION_DETAIL_MAX)])
def test_over_long_decision_is_a_typed_422_naming_the_limit(rig, field, cap):
    body = {"scope": rig["epic"], "text": "short", field: "x" * (cap + 1)}
    r = rig["client"].post("/v1/decisions", json=body, headers=ARCH)
    j = r.json()
    assert r.status_code == 422, (r.status_code, j)
    assert j["ok"] is False and j["error"]["code"] == "too_long"
    assert str(cap) in j["error"]["message"] and field in j["error"]["message"]
    # nothing was written
    assert rig["board"].store.query("decision", {"scope": rig["epic"]}) == []
    # at the limit it records
    ok = rig["client"].post("/v1/decisions", json={**body, field: "x" * cap}, headers=ARCH).json()
    assert ok["ok"], ok


# --------------------------------------------------------------------------- verdict note_error


def _signoff(rig):
    post = rig["post"]
    kt = post("/v1/tickets", {"kind": "story", "work_type": "knowledge", "title": "hl-craft",
                              "parent_id": rig["epic"], "assignee": "craft"}, ARCH)["id"]
    kcrit = post("/v1/criteria", {"ticket_id": kt, "text": "strategy doc signed by the owner",
                                  "check": "look", "checked_by": "owner"}, ARCH)["id"]
    doc = post("/v1/docs", {"doc_type": "strategy_hl", "title": "shape", "body_md": "# shape",
                            "scope": rig["epic"]}, {"X-Participant": "craft"})["id"]
    rig["client"].patch(f"/v1/criteria/{kcrit}", json={"evidence_ref": doc}, headers={"X-Participant": "craft"})
    return kt, kcrit


@pytest.mark.parametrize("where", ["message_send", "after_message"])
def test_verdict_stands_and_reports_note_error_when_the_note_fails(rig, monkeypatch, where):
    kt, kcrit = _signoff(rig)

    def boom(*a, **k):
        raise RuntimeError("broker down")

    if where == "message_send":
        monkeypatch.setattr(rig["board"], "message_send", boom)
    else:
        monkeypatch.setattr(delivery, "after_message", boom)
    r = rig["client"].post("/v1/me/verdict", json={"criterion_id": kcrit, "verdict": "fail", "ticket_id": kt,
                                                   "evidence_version": 1, "note": "the diagram is missing"},
                           headers=OWN)
    j = r.json()
    assert r.status_code == 200 and j["ok"], j
    v = j["value"]
    assert v["criterion"]["verdict"] == "fail"
    assert "broker down" in v["note_error"] and "verdict recorded" in v["note_error"]
    assert (v["message"] is None) == (where == "message_send")  # posted-but-undelivered keeps its id
    assert rig["board"].store.get("criterion", kcrit).verdict.value == "fail"


def test_verdict_without_failure_has_no_note_error(rig):
    kt, kcrit = _signoff(rig)
    j = rig["client"].post("/v1/me/verdict", json={"criterion_id": kcrit, "verdict": "pass", "ticket_id": kt,
                                                   "evidence_version": 1, "note": "good"}, headers=OWN).json()
    assert j["ok"] and j["value"]["message"] and "note_error" not in j["value"]


# --------------------------------------------------------------------------- approve/reject expected_version


def _proposal(rig):
    p = rig["post"]("/v1/docs", {"doc_type": "strategy_ll", "title": "ll", "body_md": "# v1", "scope": rig["epic"],
                                 "status": "proposed"}, {"X-Participant": "craft"})
    up = rig["client"].patch(f"/v1/docs/{p['id']}", json={"body_md": "# v2"}, headers={"X-Participant": "craft"}).json()
    assert up["ok"] and up["value"]["version"] == 2, up
    return p["id"]


@pytest.mark.parametrize("verb", ["approve", "reject"])
def test_resolve_with_a_stale_expected_version_is_a_typed_409_naming_both(rig, verb):
    pid = _proposal(rig)
    r = rig["client"].post(f"/v1/docs/{pid}/{verb}", json={"expected_version": 1}, headers=OWN)
    j = r.json()
    assert r.status_code == 409 and j["error"]["code"] == "version_mismatch", j
    assert "v1" in j["error"]["message"] and "v2" in j["error"]["message"]
    assert rig["board"].store.get("doc", pid).status.value == "proposed"  # nothing ruled


@pytest.mark.parametrize("verb,status", [("approve", "active"), ("reject", "retired")])
def test_resolve_with_the_matching_version_rules(rig, verb, status):
    pid = _proposal(rig)
    j = rig["client"].post(f"/v1/docs/{pid}/{verb}", json={"expected_version": 2}, headers=OWN).json()
    assert j["ok"], j
    assert j["value"]["doc"]["status"] == status


def test_resolve_without_a_body_still_rules(rig):
    pid = _proposal(rig)
    j = rig["client"].post(f"/v1/docs/{pid}/approve", headers=OWN).json()
    assert j["ok"] and j["value"]["doc"]["status"] == "active", j
