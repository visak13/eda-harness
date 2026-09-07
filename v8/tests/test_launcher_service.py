"""S17 board-side launcher support: the service_restarted event route and the fast pool-down
refusal on spawn/resume (design §22 rule 3 + rule 4)."""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import pool_adapter, run_state
from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path / "run"))
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


def test_service_event_records_and_needs_admin(client):
    body = {"service": "pool", "reason": "listener gone", "by": "supervisor", "git_rev": "abc123"}
    assert client.post("/v1/service_event", json=body).status_code == 403  # no admin
    r = client.post("/v1/service_event", json=body, headers=ADMIN)
    assert r.status_code == 200 and r.json()["ok"], r.text
    # the event is on the board log
    client.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "o", "id": "o"}, headers=ADMIN)
    evs = client.get("/v1/events", params={"subject_id": "service/pool"}, headers={"X-Participant": "o"}).json()
    kinds = [e["kind"] for e in (evs.get("value") or [])]
    assert "service_restarted" in kinds


def test_spawn_refuses_fast_when_pool_down(client, monkeypatch):
    monkeypatch.setattr(pool_adapter, "reachable", lambda timeout=2.0: False)
    run_state.write("pool", pid=1, port=9301, git_rev="x")
    run_state.update("pool", last_ok="2026-09-08T09:00:00+00:00")
    client.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "o", "id": "o"}, headers=ADMIN)
    r = client.post("/v1/sessions/spawn", json={"role": "engineer", "participant_id": "engineer.s-1"},
                    headers={"X-Participant": "o"})
    body = r.json()
    assert body["ok"] is False
    assert "pool is down" in body["error"]["message"] and "2026-09-08T09:00:00" in body["error"]["message"]


def test_v1_health_is_probeable(client):
    assert client.get("/v1/health").json()["service"] == "board"
