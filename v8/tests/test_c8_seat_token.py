"""C8 (s-a4fd5df319): seats started by the MCP `spawn` tool carry an EDP8_TOKEN.

The tool calls the pool directly (bundles._spawn → pool_adapter.spawn), so before C8 its seats had no
minted secret and 401'd once the board ran in public mode. POST /v1/sessions/seat-token gets-or-mints
the secret under the same authz as /v1/sessions/spawn; the tool injects it as spawn env.
Every tokens file here is a tmp_path file (EDP8_TOKENS monkeypatched) — never the fleet v8/tokens.json.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

import edp8.bundles as bundles_mod
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}


def _rig(tmp_path, monkeypatch, tokens: dict | None):
    if tokens is None:
        monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "absent-tokens.json"))
        f = None
    else:
        f = tmp_path / "tokens.json"
        f.write_text(json.dumps(tokens), encoding="utf-8")
        monkeypatch.setenv("EDP8_TOKENS", str(f))
    board = Board(Store(":memory:"))
    c = TestClient(create_app(board, admin_token="t"))
    return c, f


def _register(c, pid, role, typ="agent"):
    r = c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid}, headers=ADMIN)
    assert r.json()["ok"], r.text


def _epic_with_story(c, owner_h):
    r = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E"}, headers=owner_h)
    assert r.json()["ok"], r.text
    epic = r.json()["value"]["id"]
    return epic


def _tokened(tmp_path, monkeypatch):
    c, f = _rig(tmp_path, monkeypatch, {"owner": "ownersecret", "agents": {}})
    oh = {"X-Participant": "owner", "X-Token": "ownersecret"}
    _register(c, "owner", "owner", "human")
    epic = _epic_with_story(c, oh)
    arch = f"architect.{epic}"
    _register(c, arch, "architect")
    return c, f, oh, epic, arch


def test_seat_token_mints_once_then_returns_the_same_secret(tmp_path, monkeypatch):
    c, f, oh, epic, _ = _tokened(tmp_path, monkeypatch)
    seat = f"engineer.{epic}"
    _register(c, seat, "engineer")
    r1 = c.post("/v1/sessions/seat-token", json={"participant_id": seat, "ticket_id": epic}, headers=oh)
    assert r1.status_code == 200, r1.text
    tok = r1.json()["value"]["env"]["EDP8_TOKEN"]
    assert tok and json.loads(f.read_text(encoding="utf-8"))["agents"][seat] == tok
    # get-or-mint: a second call (a spawn the pool refused because the seat is alive) never rotates it
    r2 = c.post("/v1/sessions/seat-token", json={"participant_id": seat, "ticket_id": epic}, headers=oh)
    assert r2.json()["value"]["env"]["EDP8_TOKEN"] == tok
    assert c.get("/v1/context", headers={"X-Participant": seat, "X-Token": tok}).status_code == 200


def test_seat_token_is_null_in_trusted_mode_without_a_tokens_file(tmp_path, monkeypatch):
    c, _ = _rig(tmp_path, monkeypatch, None)
    _register(c, "owner", "owner", "human")
    epic = _epic_with_story(c, {"X-Participant": "owner"})
    seat = f"engineer.{epic}"
    _register(c, seat, "engineer")
    r = c.post("/v1/sessions/seat-token", json={"participant_id": seat, "ticket_id": epic},
               headers={"X-Participant": "owner"})
    assert r.status_code == 200 and r.json()["value"]["env"] is None, r.text
    assert not (tmp_path / "absent-tokens.json").exists()


def test_seat_token_authz_matches_spawn(tmp_path, monkeypatch):
    c, f, oh, epic, arch = _tokened(tmp_path, monkeypatch)
    seat = f"engineer.{epic}"
    _register(c, seat, "engineer")
    other_owner_epic = _epic_with_story(c, oh)
    foreign = f"engineer.{other_owner_epic}"
    _register(c, foreign, "engineer")
    arch_tok = c.post("/v1/sessions/seat-token", json={"participant_id": arch, "ticket_id": epic},
                      headers=oh).json()["value"]["env"]["EDP8_TOKEN"]
    ah = {"X-Participant": arch, "X-Token": arch_tok}
    # the architect gets its own epic's seat, never another epic's
    assert c.post("/v1/sessions/seat-token", json={"participant_id": seat, "ticket_id": epic},
                  headers=ah).status_code == 200
    assert c.post("/v1/sessions/seat-token", json={"participant_id": foreign, "ticket_id": other_owner_epic},
                  headers=ah).status_code == 403
    # an engineer seat may not mint anyone's token (not even its own)
    eng_tok = json.loads(f.read_text(encoding="utf-8"))["agents"][seat]
    eh = {"X-Participant": seat, "X-Token": eng_tok}
    assert c.post("/v1/sessions/seat-token", json={"participant_id": seat, "ticket_id": epic},
                  headers=eh).status_code == 403
    # humans and unknown handles are not seats
    r = c.post("/v1/sessions/seat-token", json={"participant_id": "owner", "ticket_id": epic}, headers=oh)
    assert r.json()["ok"] is False and "owner" not in json.loads(f.read_text(encoding="utf-8"))["agents"]
    r = c.post("/v1/sessions/seat-token", json={"participant_id": "engineer.nobody", "ticket_id": epic}, headers=oh)
    assert r.json()["ok"] is False


def test_mcp_spawn_tool_injects_the_minted_token_into_the_pool_spawn(tmp_path, monkeypatch):
    c, f, oh, epic, arch = _tokened(tmp_path, monkeypatch)
    arch_tok = c.post("/v1/sessions/seat-token", json={"participant_id": arch, "ticket_id": epic},
                      headers=oh).json()["value"]["env"]["EDP8_TOKEN"]
    calls = []
    monkeypatch.setattr(bundles_mod, "_pool_call",
                        lambda fn, kw: calls.append((fn, kw)) or {"ok": True, "value": {"session_id": "s1"}})
    set_client(BoardClient(participant=arch, admin_token="t", client=c, token=arch_tok))
    out = ALL_TOOLS["spawn"].handler(ALL_TOOLS["spawn"].args_model(role="engineer", ticket_id=epic))
    assert out["ok"], out
    seat = f"engineer.{epic}"
    spawned = [kw for fn, kw in calls if fn == "spawn"]
    assert len(spawned) == 1
    tok = spawned[0]["env"]["EDP8_TOKEN"]
    assert tok == json.loads(f.read_text(encoding="utf-8"))["agents"][seat]
    assert "EDP8_TOKEN" not in json.dumps(out)  # the secret rides the pool env, never the tool result
    # the seat authenticates with it in token mode, and a header-only call is refused
    assert c.get("/v1/context", headers={"X-Participant": seat, "X-Token": tok}).status_code == 200
    assert c.get("/v1/context", headers={"X-Participant": seat}).status_code == 401


def test_mcp_spawn_tool_adds_no_env_in_trusted_mode(tmp_path, monkeypatch):
    c, _ = _rig(tmp_path, monkeypatch, None)
    _register(c, "owner", "owner", "human")
    epic = _epic_with_story(c, {"X-Participant": "owner"})
    arch = f"architect.{epic}"
    _register(c, arch, "architect")
    calls = []
    monkeypatch.setattr(bundles_mod, "_pool_call",
                        lambda fn, kw: calls.append((fn, kw)) or {"ok": True, "value": {"session_id": "s1"}})
    set_client(BoardClient(participant=arch, admin_token="t", client=c))
    out = ALL_TOOLS["spawn"].handler(ALL_TOOLS["spawn"].args_model(role="engineer", ticket_id=epic))
    assert out["ok"], out
    assert [kw.get("env") for fn, kw in calls if fn == "spawn"] == [None]
