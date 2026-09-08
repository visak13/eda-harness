"""G1a re-sitting: the adversary-round fixes the returning engineer owns (design §14 findings
1/2/4/9, brief m-72229976e5). #3/#5/#7 landed on 355e89b and are covered by tests/test_s22_findings
+ test_api_views; this file pins the four remaining holes so qa can re-run them from cold.
"""

from __future__ import annotations

import io
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
def client(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


def _post(client, path, body, headers):
    r = client.post(path, json=body, headers=headers)
    j = r.json()
    assert j["ok"], j
    return j["value"]


@pytest.fixture
def rig(client):
    """Two owner-humans, each owning their own epic. Owner A's epic carries a strategy doc and an
    owner-checked, evidence-bearing criterion pending sign-off — the surface findings 1/2 probe."""
    for pid, role, typ in [("alice", "owner", "human"), ("bob", "owner", "human"),
                           ("arch", "architect", "agent"), ("craft", "sme", "agent"),
                           ("coord", "coordinator", "agent")]:
        _post(client, "/v1/participants", {"type": typ, "role": role, "handle": pid, "id": pid}, ADMIN)
    epic_a = _post(client, "/v1/tickets", {"kind": "epic", "work_type": "feature", "title": "A"},
                   {"X-Participant": "alice"})["id"]
    kt = _post(client, "/v1/tickets", {"kind": "story", "work_type": "knowledge", "title": "hl-craft",
                                       "parent_id": epic_a, "assignee": "craft"}, {"X-Participant": "arch"})["id"]
    kcrit = _post(client, "/v1/criteria", {"ticket_id": kt, "text": "strategy signed by the owner",
                                           "check": "look", "checked_by": "owner"}, {"X-Participant": "arch"})["id"]
    doc = _post(client, "/v1/docs", {"doc_type": "strategy_hl", "title": "shape", "body_md": "# skeleton",
                                     "scope": epic_a}, {"X-Participant": "craft"})["id"]
    client.patch(f"/v1/criteria/{kcrit}", json={"evidence_ref": doc}, headers={"X-Participant": "craft"})
    return {"client": client, "epic_a": epic_a, "kt": kt, "kcrit": kcrit, "doc": doc}


# --- finding 1: an owner rules only its own epic's criteria ------------------------------------


def test_verdict_write_refuses_a_foreign_owner(rig):
    c = rig["client"]
    # alice owns epic A; bob is an owner but of nothing here — his verdict must be refused by scope.
    r = c.post("/v1/me/verdict", json={"criterion_id": rig["kcrit"], "verdict": "pass",
                                       "ticket_id": rig["kt"], "evidence_version": 1},
               headers={"X-Participant": "bob"})
    assert r.status_code >= 400 and not r.json()["ok"]
    # alice, the epic's owner, may sign it off.
    ok = c.post("/v1/me/verdict", json={"criterion_id": rig["kcrit"], "verdict": "pass",
                                        "ticket_id": rig["kt"], "evidence_version": 1},
                headers={"X-Participant": "alice"}).json()
    assert ok["ok"] and ok["value"]["criterion"]["verdict"] == "pass"


def test_owner_may_verdict_an_epic_with_no_human_owner(client):
    # a coordinator-created epic has no human owner (epic_owner is None); the scope guard must NOT
    # refuse an owner there — the "reaches every owner" case the helper docstring promises.
    for pid, role, typ in [("alice", "owner", "human"), ("arch", "architect", "agent"),
                           ("craft", "sme", "agent"), ("coord", "coordinator", "agent")]:
        _post(client, "/v1/participants", {"type": typ, "role": role, "handle": pid, "id": pid}, ADMIN)
    epic = _post(client, "/v1/tickets", {"kind": "epic", "work_type": "feature", "title": "agent epic"},
                 {"X-Participant": "coord"})["id"]
    kt = _post(client, "/v1/tickets", {"kind": "story", "work_type": "knowledge", "title": "k",
                                       "parent_id": epic, "assignee": "craft"}, {"X-Participant": "arch"})["id"]
    crit = _post(client, "/v1/criteria", {"ticket_id": kt, "text": "signed", "check": "look",
                                          "checked_by": "owner"}, {"X-Participant": "arch"})["id"]
    doc = _post(client, "/v1/docs", {"doc_type": "strategy_hl", "title": "s", "body_md": "# b",
                                     "scope": epic}, {"X-Participant": "craft"})["id"]
    client.patch(f"/v1/criteria/{crit}", json={"evidence_ref": doc}, headers={"X-Participant": "craft"})
    r = client.post("/v1/me/verdict", json={"criterion_id": crit, "verdict": "pass",
                                            "ticket_id": kt, "evidence_version": 1},
                    headers={"X-Participant": "alice"}).json()
    assert r["ok"] and r["value"]["criterion"]["verdict"] == "pass"


def test_foreign_owner_refused_on_engineer_checked_criterion(rig):
    # finding 2: the owner-scope guard must also cover the engineer-checklist branch, not only the
    # checker branch — a foreign owner cannot verdict any criterion outside its epic.
    c = rig["client"]
    task = _post(c, "/v1/tickets", {"kind": "task", "work_type": "bug", "title": "T", "parent_id": rig["kt"],
                                    "assignee": "craft"}, {"X-Participant": "arch"})["id"]
    tcrit = _post(c, "/v1/criteria", {"ticket_id": task, "text": "self-check", "check": "command"},
                  {"X-Participant": "arch"})["id"]  # a task criterion defaults to checked_by=engineer
    r = c.post("/v1/me/verdict", json={"criterion_id": tcrit, "verdict": "pass", "ticket_id": task,
                                       "evidence_version": 1}, headers={"X-Participant": "bob"})
    assert r.status_code >= 400 and not r.json()["ok"]  # bob owns no epic here


def test_doc_signoff_card_hidden_from_a_foreign_owner(rig):
    c = rig["client"]
    alice_page = c.get(f"/ui/doc/{rig['doc']}", params={"as": "alice"}).text
    bob_page = c.get(f"/ui/doc/{rig['doc']}", params={"as": "bob"}).text
    assert "value='pass'" in alice_page  # the epic's owner sees the Approve control
    assert "value='pass'" not in bob_page  # a foreign owner never sees the card (nor the criterion id)
    assert rig["kcrit"] not in bob_page


# --- finding 2: a sign-off must name the doc version it read ------------------------------------


def test_verdict_requires_evidence_version(rig):
    c = rig["client"]
    r = c.post("/v1/me/verdict", json={"criterion_id": rig["kcrit"], "verdict": "pass",
                                       "ticket_id": rig["kt"]}, headers={"X-Participant": "alice"})
    assert r.status_code == 422  # the field is required — no header-only bypass of the stale check


def test_ui_verdict_form_carries_the_rendered_version(rig):
    c = rig["client"]
    page = c.get(f"/ui/doc/{rig['doc']}", params={"as": "alice"}).text
    assert "name='evidence_version' value='1'" in page
    # and the legacy form now requires it: omitting it is a 422, not a silent null sign-off.
    r = c.post("/ui/me/verdict", data={"as_": "alice", "criterion_id": rig["kcrit"],
                                       "ticket_id": rig["kt"], "verdict": "pass"}, follow_redirects=False)
    assert r.status_code == 422


# --- finding 4: a staged upload is invisible to everyone but its uploader ----------------------


def _upload(c, who):
    r = c.post("/v1/artifacts/upload", files={"file": ("x.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 32),
                                                        "image/png")}, headers={"X-Participant": who})
    j = r.json()
    assert j["ok"], j
    return j["value"]["id"]


def test_staged_artifact_is_404_for_non_uploader(rig):
    c = rig["client"]
    art = _upload(c, "alice")
    for path in (f"/v1/artifacts/{art}", f"/v1/artifacts/{art}/content"):
        assert c.get(path, headers={"X-Participant": "bob"}).status_code == 404  # invisible to others
        assert c.get(path, headers={"X-Participant": "alice"}).status_code == 200  # its uploader still reads it


# --- finding 9: /v1/library?epic scopes artifacts and links, not docs alone --------------------


def test_library_epic_scopes_artifacts_and_links(rig):
    c = rig["client"]
    epic_b = _post(c, "/v1/tickets", {"kind": "epic", "work_type": "feature", "title": "B"},
                   {"X-Participant": "bob"})["id"]
    a_art = _post(c, "/v1/artifacts", {"form": "url", "uri": "https://a", "ticket_id": rig["kt"]},
                  {"X-Participant": "craft"})["id"]
    b_art = _post(c, "/v1/artifacts", {"form": "url", "uri": "https://b", "ticket_id": epic_b},
                  {"X-Participant": "bob"})["id"]
    lib = c.get("/v1/library", params={"epic": rig["epic_a"]}, headers={"X-Participant": "alice"}).json()["value"]
    ids = {x["id"] for x in lib["artifacts"]}
    assert a_art in ids and b_art not in ids  # only epic A's artifact
    assert not any(lk["to_id"] == b_art or lk["from_id"] == epic_b for lk in lib["links"])


def test_library_epic_does_not_leak_a_shared_artifacts_foreign_link(rig):
    # finding 4: an artifact linked to BOTH epic A and epic B must appear in A's library, but A's
    # link list must not carry the edge that ties it to epic B (a link is in-epic only when BOTH
    # ends are in scope).
    c = rig["client"]
    epic_b = _post(c, "/v1/tickets", {"kind": "epic", "work_type": "feature", "title": "B"},
                   {"X-Participant": "bob"})["id"]
    shared = _post(c, "/v1/artifacts", {"form": "url", "uri": "https://shared", "ticket_id": rig["kt"]},
                   {"X-Participant": "craft"})["id"]
    _post(c, "/v1/links", {"from_id": epic_b, "to_id": shared, "relation": "produced"},
          {"X-Participant": "bob"})  # the same artifact also linked to epic B
    lib = c.get("/v1/library", params={"epic": rig["epic_a"]}, headers={"X-Participant": "alice"}).json()["value"]
    assert shared in {a["id"] for a in lib["artifacts"]}  # the artifact is in A's library
    assert not any(lk["from_id"] == epic_b for lk in lib["links"])  # but the epic-B edge is not
