"""Tests for edp8.service: HTTP layer over Board (FastAPI + TestClient)."""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.search import Index, NullEmbedder
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}


@pytest.fixture
def client():
    app = create_app(Board(Store(":memory:")), admin_token="t")
    return TestClient(app)


@pytest.fixture
def rig(client):
    """Register the standard roles and return handle -> X-Participant header dict."""
    people = [
        ("owner", "owner", "human"),
        ("arch", "architect", "agent"),
        ("eng", "engineer", "agent"),
        ("rev", "reviewer", "agent"),
        ("qa", "qa", "agent"),
        ("coord", "coordinator", "agent"),
    ]
    for pid, role, typ in people:
        r = client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                         headers=ADMIN)
        assert r.json()["ok"], r.text
    return {pid: {"X-Participant": pid} for pid, _, _ in people}


def make_epic(client, rig):
    r = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "Build a hello CLI"},
                     headers=rig["owner"])
    assert r.json()["ok"], r.text
    return r.json()["value"]


# ------------------------------------------------------------------ auth

def test_401_without_x_participant(client):
    r = client.get("/v1/whoami")
    assert r.status_code == 401


def test_admin_token_required_for_participants(client):
    r = client.post("/v1/participants", json={"type": "agent", "role": "engineer", "handle": "e1"})
    assert r.status_code == 403


def test_admin_token_required_for_sessions(client):
    r = client.put("/v1/sessions/s1", json={"participant_id": "p1", "pool_id": "pool", "state": "alive"})
    assert r.status_code == 403


def test_admin_token_wrong_value_rejected(client):
    r = client.post("/v1/participants", json={"type": "agent", "role": "engineer", "handle": "e1"},
                     headers={"X-Admin": "wrong"})
    assert r.status_code == 403


def test_whoami_hint(client, rig):
    r = client.get("/v1/whoami", headers=rig["owner"])
    body = r.json()
    assert body["ok"] is True
    assert "context()" in body["hint"]
    assert body["value"]["participant"]["handle"] == "owner"


def test_whoami_unknown_participant_is_401(client):
    r = client.get("/v1/whoami", headers={"X-Participant": "ghost"})
    assert r.status_code == 401


# ------------------------------------------------------------------ error envelope

def test_error_envelope_shape_on_409(client, rig):
    epic = make_epic(client, rig)
    r = client.patch(f"/v1/tickets/{epic['id']}", json={"status": "ready"}, headers=rig["owner"])
    assert r.status_code == 409
    body = r.json()
    assert body["ok"] is False
    assert set(body["error"].keys()) == {"code", "message"}
    assert body["error"]["code"] == "transition"
    assert "hint" in body
    assert body["hint"]


def test_error_envelope_shape_on_400_scope(client, rig):
    r = client.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "x",
                                          "parent_id": "nope"}, headers=rig["eng"])
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "scope"


def test_error_envelope_shape_on_http_exception(client):
    r = client.get("/v1/whoami")
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "http"


# ------------------------------------------------------------------ core flow sanity

def test_ticket_create_hint_differs_epic_vs_story(client, rig):
    epic = make_epic(client, rig)
    r_epic = client.get(f"/v1/tickets/{epic['id']}", headers=rig["owner"])
    assert r_epic.json()["ok"]

    r_story = client.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "skeleton",
                                                "parent_id": epic["id"]}, headers=rig["arch"])
    assert "criteria" in r_story.json()["hint"]


def test_docs_version_endpoint(client, rig):
    epic = make_epic(client, rig)
    d = client.post("/v1/docs", json={"doc_type": "design", "title": "v1", "body_md": "body v1",
                                       "scope": epic["id"]}, headers=rig["arch"]).json()["value"]
    client.patch(f"/v1/docs/{d['id']}", json={"body_md": "body v2", "title": "v2"}, headers=rig["arch"])
    latest = client.get(f"/v1/docs/{d['id']}", headers=rig["arch"]).json()["value"]
    assert latest["version"] == 2
    assert latest["versions"] == [1, 2]
    old = client.get(f"/v1/docs/{d['id']}?version=1", headers=rig["arch"]).json()["value"]
    assert old["body_md"] == "body v1"


# ------------------------------------------------------------------ events / feed

def test_events_since(client, rig):
    epic = make_epic(client, rig)
    r = client.get("/v1/events?since=0", headers=rig["coord"])
    body = r.json()
    assert body["ok"] is True
    kinds = [e["kind"] for e in body["value"]]
    assert "ticket_created" in kinds


def test_events_subject_id_filter(client, rig):
    epic = make_epic(client, rig)
    r = client.get(f"/v1/events?subject_id={epic['id']}", headers=rig["coord"])
    body = r.json()
    assert body["ok"] is True
    assert all(e["subject_id"] == epic["id"] for e in body["value"])
    assert body["value"]


@pytest.mark.skip(reason="SSE /v1/feed's endless generator hangs TestClient's sync stream "
                         "iterator (the 15s keepalive wait_for blocks the test worker); "
                         "covered instead by test_events_since / test_events_subject_id_filter "
                         "against the equivalent /v1/events replay path.")
def test_feed_streams_replayed_events_then_ready(client, rig):
    epic = make_epic(client, rig)
    with client.stream("GET", "/v1/feed?since=0", headers=rig["coord"]) as r:
        assert r.status_code == 200
        lines = []
        for line in r.iter_lines():
            if line:
                lines.append(line)
            if len(lines) >= 2:
                break
    assert any(l.startswith("data:") for l in lines)
    assert any(": ready" in l for l in lines)


# ------------------------------------------------------------------ find (search)

@pytest.fixture
def search_client():
    idx = Index(embedder=NullEmbedder())
    app = create_app(Board(Store(":memory:"), idx), admin_token="t")
    return TestClient(app)


def test_find_returns_bm25_hits(search_client):
    client = search_client
    r = client.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner", "id": "owner"},
                     headers=ADMIN)
    assert r.json()["ok"], r.text
    hdrs = {"X-Participant": "owner"}
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature",
                                             "title": "Build a hello CLI"}, headers=hdrs).json()["value"]
    r = client.get("/v1/find?q=hello", headers=hdrs)
    body = r.json()
    assert body["ok"] is True
    hits = body["value"]
    assert hits
    assert any(h["id"] == epic["id"] for h in hits)


def test_find_empty_without_index(client, rig):
    r = client.get("/v1/find?q=hello", headers=rig["owner"])
    assert r.json()["value"] == []
