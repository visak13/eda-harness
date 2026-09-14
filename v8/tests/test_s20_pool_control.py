"""S20 — pool control plane via the board.

Covers the board side of s-9b5cac0bd5: /v1/sessions/{spawn,resume,reap,close} proxying the
pool with actor authorisation, an Idempotency-Key honoured for 10 minutes, pool-failure
mapping, /v1/pool/capabilities, agent credentials (tokens.json `agents`), and resume-from-
closed routing. The pool is a stub (edp8.pool_adapter monkeypatched) — no real edp-pool.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import pool_adapter
from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}


@pytest.fixture
def app_board():
    board = Board(Store(":memory:"))
    app = create_app(board, admin_token="t")
    return app, board


@pytest.fixture
def client(app_board):
    return TestClient(app_board[0])


def _register(client, pid, role, typ="agent"):
    r = client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid}, headers=ADMIN)
    assert r.json()["ok"], r.text


def _epic(client, owner="owner"):
    r = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "Epic"},
                    headers={"X-Participant": owner})
    assert r.json()["ok"], r.text
    return r.json()["value"]["id"]


def _story(client, epic_id, arch):
    r = client.post("/v1/tickets", json={"kind": "story", "work_type": "chore", "title": "Story",
                                         "parent_id": epic_id}, headers={"X-Participant": arch})
    assert r.json()["ok"], r.text
    return r.json()["value"]["id"]


@pytest.fixture
def rig(client):
    """owner (human) + an epic with an architect seat scoped to it; returns the ids."""
    _register(client, "owner", "owner", "human")
    epic_id = _epic(client)
    arch = f"architect.{epic_id}"
    _register(client, arch, "architect")
    story_id = _story(client, epic_id, arch)
    _register(client, "eng", "engineer")
    return {"epic": epic_id, "arch": arch, "story": story_id}


# ---------------------------------------------------------------- authz (c-68756731c3)

def _stub_spawn(monkeypatch, sink=None):
    calls = sink if sink is not None else []

    def fake(role, participant_id, **kw):
        calls.append({"role": role, "participant_id": participant_id, **kw})
        return {"ok": True, "value": {"session_id": f"sess-{len(calls)}"}, "hint": ""}

    monkeypatch.setattr(pool_adapter, "spawn", fake)
    return calls


def test_owner_may_spawn_any_seat(client, rig, monkeypatch):
    _stub_spawn(monkeypatch)
    r = client.post("/v1/sessions/spawn",
                    json={"role": "engineer", "participant_id": f"engineer.{rig['story']}", "ticket_id": rig["story"]},
                    headers={"X-Participant": "owner"})
    assert r.status_code == 200, r.text
    assert r.json()["value"]["session_id"] == "sess-1"


def test_spawn_registers_the_seat_before_minting(client, rig, monkeypatch):
    """pain p-9ba7b6b6: REST spawn of an unregistered handle registers it (idempotently), so the
    new shell's first MCP call authenticates instead of 401 "participant X is not registered"."""
    calls = _stub_spawn(monkeypatch)
    pid = f"engineer.{rig['story']}"
    assert client.get(f"/v1/participants/{pid}", headers={"X-Participant": "owner"}).status_code != 200
    r = client.post("/v1/sessions/spawn", json={"role": "engineer", "participant_id": pid, "ticket_id": rig["story"]},
                    headers={"X-Participant": "owner"})
    assert r.status_code == 200, r.text
    p = client.get(f"/v1/participants/{pid}", headers={"X-Participant": "owner"})
    assert p.status_code == 200 and p.json()["value"]["role"] == "engineer" and p.json()["value"]["type"] == "agent"
    # the seat can now act as itself (header-only trusted mode in this rig)
    assert client.get("/v1/whoami", headers={"X-Participant": pid}).status_code == 200
    # a second spawn of an already-registered handle is not a conflict
    r2 = client.post("/v1/sessions/spawn", json={"role": "engineer", "participant_id": pid, "ticket_id": rig["story"]},
                     headers={"X-Participant": "owner"})
    assert r2.status_code == 200 and len(calls) == 2


def test_architect_may_spawn_in_own_epic(client, rig, monkeypatch):
    _stub_spawn(monkeypatch)
    r = client.post("/v1/sessions/spawn",
                    json={"role": "engineer", "participant_id": f"engineer.{rig['story']}", "ticket_id": rig["story"]},
                    headers={"X-Participant": rig["arch"]})
    assert r.status_code == 200, r.text


def test_architect_refused_other_epic(client, rig, monkeypatch):
    _stub_spawn(monkeypatch)
    _register(client, "owner2", "owner", "human")
    epic2 = _epic(client, "owner2")
    arch2 = f"architect.{epic2}"
    _register(client, arch2, "architect")
    story2 = _story(client, epic2, arch2)
    r = client.post("/v1/sessions/spawn",
                    json={"role": "engineer", "participant_id": f"engineer.{story2}", "ticket_id": story2},
                    headers={"X-Participant": rig["arch"]})  # arch of epic1 reaching into epic2
    assert r.status_code == 403, r.text
    err = r.json()["error"]
    assert err["code"] == "forbidden"
    assert "owner" in err["allowed"] and any("architect" in a for a in err["allowed"])


def test_engineer_refused(client, rig, monkeypatch):
    _stub_spawn(monkeypatch)
    r = client.post("/v1/sessions/spawn",
                    json={"role": "engineer", "participant_id": f"engineer.{rig['story']}", "ticket_id": rig["story"]},
                    headers={"X-Participant": "eng"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_reap_close_resume_share_the_guard(client, rig, monkeypatch):
    for verb in ("reap", "close", "resume"):
        r = client.post(f"/v1/sessions/{verb}",
                        json={"participant_id": f"engineer.{rig['story']}", "ticket_id": rig["story"]},
                        headers={"X-Participant": "eng"})
        assert r.status_code == 403, f"{verb}: {r.text}"


# ---------------------------------------------------------------- idempotency (c-68756731c3)

def test_idempotency_key_replays_no_second_shell(client, rig, monkeypatch):
    calls = _stub_spawn(monkeypatch)
    body = {"role": "engineer", "participant_id": f"engineer.{rig['story']}", "ticket_id": rig["story"]}
    h = {"X-Participant": "owner", "Idempotency-Key": "abc"}
    r1 = client.post("/v1/sessions/spawn", json=body, headers=h)
    r2 = client.post("/v1/sessions/spawn", json=body, headers=h)
    assert r1.json()["value"]["session_id"] == r2.json()["value"]["session_id"]
    assert len(calls) == 1  # the pool was hit exactly once — no second shell


def test_idempotency_distinct_keys_spawn_twice(client, rig, monkeypatch):
    calls = _stub_spawn(monkeypatch)
    body = {"role": "engineer", "participant_id": f"engineer.{rig['story']}", "ticket_id": rig["story"]}
    client.post("/v1/sessions/spawn", json=body, headers={"X-Participant": "owner", "Idempotency-Key": "k1"})
    client.post("/v1/sessions/spawn", json=body, headers={"X-Participant": "owner", "Idempotency-Key": "k2"})
    assert len(calls) == 2


# ---------------------------------------------------------------- pool down (c-68756731c3)

def test_pool_down_maps_to_503_with_hint(client, rig, monkeypatch):
    monkeypatch.setattr(pool_adapter, "spawn", lambda *a, **k: {
        "ok": False, "error": {"code": "unavailable", "message": "pool unreachable: conn refused"},
        "hint": "start the pool (edp-pool) and retry"})
    r = client.post("/v1/sessions/spawn",
                    json={"role": "engineer", "participant_id": f"engineer.{rig['story']}", "ticket_id": rig["story"]},
                    headers={"X-Participant": "owner"})
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["ok"] is False and body["error"]["code"] == "unavailable"
    assert body["hint"]  # a next-step hint is present


def test_pool_error_maps_to_502(client, rig, monkeypatch):
    monkeypatch.setattr(pool_adapter, "reap", lambda *a, **k: {
        "ok": False, "error": {"code": "pool", "message": "handle not found"}, "hint": ""})
    r = client.post("/v1/sessions/reap",
                    json={"participant_id": f"engineer.{rig['story']}", "ticket_id": rig["story"]},
                    headers={"X-Participant": "owner"})
    assert r.status_code == 502
    assert r.json()["hint"]  # a hint is synthesised when the pool gave none


# ---------------------------------------------------------------- capabilities (c-277b59dd3e)

def test_capabilities_passthrough(client, rig, monkeypatch):
    monkeypatch.setattr(pool_adapter, "capabilities", lambda: {
        "ok": True, "value": {"resume_parked": True, "resume_closed": True, "park": True, "spawn": True}})
    r = client.get("/v1/pool/capabilities", headers={"X-Participant": "owner"})
    assert r.status_code == 200
    v = r.json()["value"]
    assert v == {"resume_parked": True, "resume_closed": True, "park": True, "spawn": True}


def test_capabilities_not_hardcoded(client, rig, monkeypatch):
    monkeypatch.setattr(pool_adapter, "capabilities", lambda: {
        "ok": True, "value": {"resume_parked": True, "resume_closed": False, "park": True, "spawn": True}})
    r = client.get("/v1/pool/capabilities", headers={"X-Participant": "owner"})
    assert r.json()["value"]["resume_closed"] is False  # reflects the pool, not a constant


def test_capabilities_pool_down_all_false_with_reason(client, rig, monkeypatch):
    monkeypatch.setattr(pool_adapter, "capabilities", lambda: {
        "ok": False, "error": {"code": "unavailable", "message": "pool unreachable"}})
    r = client.get("/v1/pool/capabilities", headers={"X-Participant": "owner"})
    v = r.json()["value"]
    assert v["resume_parked"] is False and v["resume_closed"] is False
    assert v["park"] is False and v["spawn"] is False
    assert v["reason"]


# ---------------------------------------------------------------- agent creds (c-6884a09e9f)

def _app_with_tokens(tmp_path, tokens: dict):
    f = tmp_path / "tokens.json"
    f.write_text(json.dumps(tokens), encoding="utf-8")
    os.environ["EDP8_TOKENS"] = str(f)
    board = Board(Store(":memory:"))
    app = create_app(board, admin_token="t")
    return app, board, f


def test_agent_header_only_401_with_tokens(tmp_path, monkeypatch):
    app, board, f = _app_with_tokens(tmp_path, {"agents": {"eng": "sekret"}})
    try:
        c = TestClient(app)
        _register(c, "eng", "engineer")
        # header-only (no X-Token) is refused once a secret is configured for the agent
        assert c.get("/v1/context", headers={"X-Participant": "eng"}).status_code == 401
        # the correct minted token authenticates
        assert c.get("/v1/context", headers={"X-Participant": "eng", "X-Token": "sekret"}).status_code == 200
        # a wrong token is refused
        assert c.get("/v1/context", headers={"X-Participant": "eng", "X-Token": "nope"}).status_code == 401
    finally:
        os.environ.pop("EDP8_TOKENS", None)


def test_agent_200_without_tokens(tmp_path, monkeypatch):
    os.environ.pop("EDP8_TOKENS", None)
    board = Board(Store(":memory:"))
    c = TestClient(create_app(board, admin_token="t"))
    _register(c, "eng", "engineer")
    assert c.get("/v1/context", headers={"X-Participant": "eng"}).status_code == 200  # trusted mode unchanged


def _epic_tok(client, headers):
    r = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "Epic"}, headers=headers)
    assert r.json()["ok"], r.text
    return r.json()["value"]["id"]


def test_spawn_mints_token_injects_and_it_authenticates(tmp_path, monkeypatch):
    # public mode: owner has a token in tokens.json and must present it on every call
    app, board, f = _app_with_tokens(tmp_path, {"owner": "ownersecret"})
    captured = {}

    def fake_spawn(role, participant_id, **kw):
        captured["env"] = kw.get("env")
        return {"ok": True, "value": {"session_id": "s1"}}

    monkeypatch.setattr(pool_adapter, "spawn", fake_spawn)
    try:
        c = TestClient(app)
        oh = {"X-Participant": "owner", "X-Token": "ownersecret"}
        _register(c, "owner", "owner", "human")
        epic = _epic_tok(c, oh)
        seat = f"engineer.{epic}"
        _register(c, seat, "engineer")
        r = c.post("/v1/sessions/spawn", json={"role": "engineer", "participant_id": seat, "ticket_id": epic},
                   headers=oh)
        assert r.status_code == 200, r.text
        # a per-seat EDP8_TOKEN was minted and injected into the shell env
        assert captured["env"] and captured["env"].get("EDP8_TOKEN")
        minted = captured["env"]["EDP8_TOKEN"]
        # and it is persisted in tokens.json's agents map and authenticates the seat
        agents = json.loads(f.read_text(encoding="utf-8")).get("agents", {})
        assert agents.get(seat) == minted
        assert c.get("/v1/context", headers={"X-Participant": seat, "X-Token": minted}).status_code == 200
        assert c.get("/v1/context", headers={"X-Participant": seat}).status_code == 401
    finally:
        os.environ.pop("EDP8_TOKENS", None)


# ---------------------------------------------------------------- resume-from-closed routing (c-441256a773)

def test_resume_routes_to_resume_closed_when_row_done(client, rig, monkeypatch):
    seat = f"engineer.{rig['story']}"
    monkeypatch.setattr(pool_adapter, "sessions", lambda: {
        "ok": True, "value": [{"handle": seat, "state": "done", "session_id": "old"}]})
    hit = {}

    def _closed(pid):
        hit["closed"] = pid
        return {"ok": True, "value": {"session_id": "new"}}

    def _parked(pid):
        hit["parked"] = pid
        return {"ok": True, "value": {}}

    monkeypatch.setattr(pool_adapter, "resume_closed", _closed)
    monkeypatch.setattr(pool_adapter, "resume", _parked)
    r = client.post("/v1/sessions/resume", json={"participant_id": seat, "ticket_id": rig["story"]},
                    headers={"X-Participant": "owner"})
    assert r.status_code == 200, r.text
    assert hit.get("closed") == seat and "parked" not in hit  # routed to resume_closed


def test_resume_uses_normal_resume_when_parked(client, rig, monkeypatch):
    seat = f"engineer.{rig['story']}"
    monkeypatch.setattr(pool_adapter, "sessions", lambda: {
        "ok": True, "value": [{"handle": seat, "state": "parked", "session_id": "p"}]})
    hit = {}

    def _closed(pid):
        hit["closed"] = pid
        return {"ok": True, "value": {}}

    def _parked(pid):
        hit["parked"] = pid
        return {"ok": True, "value": {"session_id": "r"}}

    monkeypatch.setattr(pool_adapter, "resume", _parked)
    monkeypatch.setattr(pool_adapter, "resume_closed", _closed)
    r = client.post("/v1/sessions/resume", json={"participant_id": seat, "ticket_id": rig["story"]},
                    headers={"X-Participant": "owner"})
    assert r.status_code == 200, r.text
    assert hit.get("parked") == seat and "closed" not in hit
