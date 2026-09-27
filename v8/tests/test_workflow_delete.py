"""t-0c16c00424 (owner m-8724c6bb47: "duplicate option but no option to delete"): DELETE /v1/workflows/{ref}.

- an unpublished draft is deleted outright;
- a published version no epic pins is archived: hidden from the list, listed with ?archived=true, restorable;
- a version any epic pins is refused with 409 naming the epics;
- a built-in preset (Standard, Lean, Solo) is refused;
- only an admin deletes or restores: a non-admin human, an architect and an engineer seat are refused;
- each list row's `delete_outcome` names what Delete would do (the Design tab's confirm reads it).
"""
from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store


class _Pool:
    def spawn(self, role, pid, **_):
        return {"ok": True}


O, B, A, E = ({"X-Participant": p} for p in ("owner", "bob", "arch", "eng"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    b = Board(Store(":memory:"), pool=_Pool(), free_mb=lambda: 10_000)
    c = TestClient(create_app(b, admin_token="t"))
    for pid, role, typ in (("owner", "owner", "human"), ("bob", "owner", "human"), ("arch", "architect", "agent"),
                           ("eng", "engineer", "agent")):
        assert c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                      headers={"X-Admin": "t"}).json()["ok"]
    return c


def _dup(c, new_id: str) -> str:
    d = c.post("/v1/workflows/duplicate", json={"ref": "standard@1", "new_id": new_id}, headers=O).json()["value"]
    return f"{d['id']}@{d['version']}"


def _rows(c, **params) -> dict[str, dict]:
    return {r["ref"]: r for r in c.get("/v1/workflows", params=params, headers=B).json()["value"]}


def test_a_draft_is_deleted_outright(client):
    c = client
    ref = _dup(c, "scratch")
    assert _rows(c)[ref]["delete_outcome"]["action"] == "deleted"
    r = c.delete(f"/v1/workflows/{ref}", headers=O)
    assert r.status_code == 200 and r.json()["value"]["outcome"] == "deleted"
    assert ref not in _rows(c) and ref not in _rows(c, archived="true")
    assert c.get(f"/v1/workflows/{ref}", headers=B).status_code == 404


def test_an_unpinned_published_version_is_archived_and_restorable(client):
    c = client
    ref = _dup(c, "team")
    assert c.post(f"/v1/workflows/{ref}/publish", headers=O).json()["ok"]
    assert _rows(c)[ref]["delete_outcome"]["action"] == "archived"
    r = c.delete(f"/v1/workflows/{ref}", headers=O)
    assert r.status_code == 200 and r.json()["value"]["outcome"] == "archived"
    assert ref not in _rows(c)  # hidden from the list …
    arch = _rows(c, archived="true")[ref]
    assert arch["archived"] is True and arch["delete_outcome"]["action"] == "refused"  # … listed on request
    assert c.get(f"/v1/workflows/{ref}", headers=B).json()["ok"]  # still readable by ref
    # an archived version is not what a new epic picks up by id
    bad = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E", "workflow": "team"},
                 headers=O)
    assert not bad.json()["ok"]
    assert c.post(f"/v1/workflows/{ref}/restore", headers=B).status_code == 400  # admin only
    assert c.post(f"/v1/workflows/{ref}/restore", headers=O).json()["value"]["outcome"] == "restored"
    assert _rows(c)[ref]["archived"] is False
    assert c.post(f"/v1/workflows/{ref}/restore", headers=O).status_code == 409  # not archived now


def test_a_pinned_version_is_refused_with_409_naming_its_epics(client):
    c = client
    ref = _dup(c, "crew")
    assert c.post(f"/v1/workflows/{ref}/publish", headers=O).json()["ok"]
    epics = [c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": f"E{i}", "workflow": ref},
                    headers=O).json()["value"]["id"] for i in range(2)]
    row = _rows(c)[ref]
    assert row["delete_outcome"]["action"] == "refused" and all(e in row["delete_outcome"]["reason"] for e in epics)
    r = c.delete(f"/v1/workflows/{ref}", headers=O)
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "conflict" and all(e in err["message"] for e in epics)
    assert ref in _rows(c)  # untouched


@pytest.mark.parametrize("preset", ["standard@1", "lean@1", "solo@1"])
def test_a_preset_is_refused(client, preset):
    c = client
    assert _rows(c)[preset]["delete_outcome"]["action"] == "refused"
    r = c.delete(f"/v1/workflows/{preset}", headers=O)
    assert r.status_code == 409 and r.json()["error"]["code"] == "immutable"
    assert preset in _rows(c)


@pytest.mark.parametrize("who", [B, A, E], ids=["non-admin human", "architect", "engineer"])
def test_a_non_admin_is_refused(client, who):
    c = client
    ref = _dup(c, "mine")
    r = c.delete(f"/v1/workflows/{ref}", headers=who)
    assert r.status_code == 400 and r.json()["error"]["code"] == "scope"
    assert "admins only" in r.json()["error"]["message"]
    assert ref in _rows(c)


def test_unknown_or_malformed_refs(client):
    c = client
    assert c.delete("/v1/workflows/nope@3", headers=O).status_code == 404
    assert c.delete("/v1/workflows/no-version", headers=O).status_code == 400
