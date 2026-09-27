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
import threading
import time
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import workflow as wflow
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


# ---- R2-C (adversary m-a300de4933): delete is serialized against publish and epic pinning
@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    b = Board(Store(":memory:"), pool=_Pool(), free_mb=lambda: 10_000)
    c = TestClient(create_app(b, admin_token="t"))
    assert c.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner", "id": "owner"},
                  headers={"X-Admin": "t"}).json()["ok"]
    return b, c


def _epic(c, ref: str):
    return c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "Pinned during delete",
                                       "workflow": ref}, headers=O)


def _held_delete(b, monkeypatch, ref: str):
    """Start DELETE ref on a thread and hold it inside its pin check (where the race window used to be)."""
    entered, resume = threading.Event(), threading.Event()
    orig = b.workflows.pins

    def paused():
        got = orig()
        if threading.current_thread().name.startswith("r2c-delete"):
            entered.set()
            assert resume.wait(20)
        return got

    monkeypatch.setattr(b.workflows, "pins", paused)
    pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="r2c-delete")
    task = pool.submit(b.workflows.delete, ref, by="owner")
    assert entered.wait(10)
    return pool, task, resume


def test_r2c_publish_and_pin_wait_for_a_draft_delete_and_never_pin_it(env, monkeypatch):
    b, c = env
    b.workflows.duplicate("standard@1", new_id="race", by="owner")
    pool, task, resume = _held_delete(b, monkeypatch, "race@1")
    try:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="r2c-other") as others:
            pub = others.submit(b.workflows.publish, "race", 1, by="owner")
            time.sleep(0.3)
            assert not pub.done()  # blocked on the lock the delete holds, not interleaved
            resume.set()
            assert task.result(timeout=20)["outcome"] == "deleted"
            with pytest.raises(wflow.WorkflowError):  # the draft is gone: no resurrection as published
                pub.result(timeout=20)
    finally:
        resume.set()
        pool.shutdown()
    r = _epic(c, "race@1")
    assert r.status_code in (400, 404, 409) and "race@1" not in b.workflows.pinned_refs()


def test_r2c_an_epic_pin_waits_for_an_archive_and_is_refused(env, monkeypatch):
    b, c = env
    b.workflows.duplicate("standard@1", new_id="race", by="owner")
    b.workflows.publish("race", 1, by="owner")
    b.workflows.resolve("race@1")  # the epic create resolves before it pins: that step stays unlocked
    monkeypatch.setattr(b, "_workflow_choice", lambda wf: wf)  # choice ran before the archive (the old window)
    pool, task, resume = _held_delete(b, monkeypatch, "race@1")
    try:
        created = pool.submit(_epic, c, "race@1")
        time.sleep(0.3)
        assert not created.done()
        resume.set()
        assert task.result(timeout=20)["outcome"] == "archived"
        r = created.result(timeout=20)
    finally:
        resume.set()
        pool.shutdown()
    assert r.status_code == 409 and "archived" in r.json()["error"]["message"]
    assert "race@1" not in b.workflows.pinned_refs()
    assert not [t for t in b.tickets(kind="epic") if t.title == "Pinned during delete"]  # no pinless epic left


def test_r2c_a_pin_that_lands_first_makes_the_delete_refuse_and_the_definition_resolves(env):
    b, c = env
    b.workflows.duplicate("standard@1", new_id="race", by="owner")
    b.workflows.publish("race", 1, by="owner")
    eid = _epic(c, "race@1").json()["value"]["id"]
    r = c.delete("/v1/workflows/race@1", headers=O)
    assert r.status_code == 409 and eid in r.json()["error"]["message"]
    assert b.workflows.pin_of(eid) == "race@1"
    assert type(b.workflows)(b.store).resolve("race@1").d.ref == "race@1"  # a fresh registry resolves the pin


def test_r2c_restore_of_an_archived_version_then_pin_is_allowed(env):
    b, c = env
    b.workflows.duplicate("standard@1", new_id="race", by="owner")
    b.workflows.publish("race", 1, by="owner")
    assert b.workflows.delete("race@1", by="owner")["outcome"] == "archived"
    assert b.workflows.restore("race@1")["outcome"] == "restored"
    eid = _epic(c, "race@1").json()["value"]["id"]
    assert b.workflows.pin_of(eid) == "race@1"
