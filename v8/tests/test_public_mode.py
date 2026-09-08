"""S17 — reach from another machine: EDP8_PUBLIC_URL drives 0.0.0.0 binding and public
mode fails closed. Trusted single-machine mode is the default and must stay unchanged
(strategy_hl Phase 4 rollback rule: trusted mode is one env var away).

Characterisation FIRST (test_trusted_* ) pins today's behaviour before the public-mode
branch, so a regression in the default path is visible.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.service import create_app, public_startup_error, resolve_host
from edp8.store import Store

ADMIN = {"X-Admin": "secret"}


# --------------------------------------------------------------- resolve_host

def test_resolve_host_defaults_loopback(monkeypatch):
    monkeypatch.delenv("EDP8_HOST", raising=False)
    monkeypatch.delenv("EDP8_PUBLIC_URL", raising=False)
    assert resolve_host() == "127.0.0.1"


def test_resolve_host_public_binds_all(monkeypatch):
    monkeypatch.delenv("EDP8_HOST", raising=False)
    monkeypatch.setenv("EDP8_PUBLIC_URL", "http://host.example:9400")
    assert resolve_host() == "0.0.0.0"


def test_resolve_host_explicit_overrides_public(monkeypatch):
    monkeypatch.setenv("EDP8_PUBLIC_URL", "http://host.example:9400")
    monkeypatch.setenv("EDP8_HOST", "10.0.0.5")
    assert resolve_host() == "10.0.0.5"


# --------------------------------------------------------------- fail-closed gate

def _tokens(tmp_path, data: dict) -> str:
    f = tmp_path / "tokens.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    return str(f)


def test_public_refuses_default_admin_token(tmp_path):
    p = _tokens(tmp_path, {"owner": "s", "agents": {"eng.x": "a"}})
    from pathlib import Path
    err = public_startup_error("dev", Path(p))
    assert err and "EDP8_ADMIN_TOKEN" in err


def test_public_refuses_missing_tokens_file(tmp_path):
    from pathlib import Path
    err = public_startup_error("realsecret", Path(tmp_path / "nope.json"))
    assert err and "missing or invalid" in err


def test_public_refuses_when_no_agent_credentials(tmp_path):
    from pathlib import Path
    p = _tokens(tmp_path, {"owner": "s"})  # human only, no agents map
    err = public_startup_error("realsecret", Path(p))
    assert err and "agent credentials" in err


def test_public_ok_with_admin_and_both_creds(tmp_path):
    from pathlib import Path
    p = _tokens(tmp_path, {"owner": "s", "agents": {"eng.x": "a"}})
    assert public_startup_error("realsecret", Path(p)) is None


def test_public_create_app_raises_on_default_token(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_PUBLIC_URL", "http://host.example:9400")
    monkeypatch.setenv("EDP8_TOKENS", _tokens(tmp_path, {"owner": "s", "agents": {"eng.x": "a"}}))
    with pytest.raises(RuntimeError, match="EDP8_ADMIN_TOKEN"):
        create_app(Board(Store(":memory:")), admin_token="dev")


# --------------------------------------------------------------- trusted mode (characterisation)

def test_trusted_mode_header_only_identity(monkeypatch):
    """Default: no EDP8_PUBLIC_URL, no tokens file → header-only X-Participant is accepted."""
    monkeypatch.delenv("EDP8_PUBLIC_URL", raising=False)
    monkeypatch.setenv("EDP8_TOKENS", "does-not-exist.json")
    app = create_app(Board(Store(":memory:")), admin_token="secret")
    c = TestClient(app)
    assert c.post("/v1/participants", json={"type": "agent", "role": "engineer", "handle": "eng.x", "id": "eng.x"},
                  headers=ADMIN).json()["ok"]
    r = c.get("/v1/whoami", headers={"X-Participant": "eng.x"})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------- public mode 401 (remote impersonation)

@pytest.fixture
def public_client(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_PUBLIC_URL", "http://host.example:9400")
    monkeypatch.setenv("EDP8_TOKENS", _tokens(tmp_path, {"owner": "ownersecret", "agents": {"eng.x": "engsecret"}}))
    app = create_app(Board(Store(":memory:")), admin_token="realsecret")
    c = TestClient(app)
    for pid, role, typ in [("owner", "owner", "human"), ("eng.x", "engineer", "agent")]:
        assert c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                      headers={"X-Admin": "realsecret"}).json()["ok"]
    return c


def test_public_agent_header_only_is_401(public_client):
    r = public_client.get("/v1/whoami", headers={"X-Participant": "eng.x"})
    assert r.status_code == 401


def test_public_human_header_only_is_401(public_client):
    r = public_client.get("/v1/whoami", headers={"X-Participant": "owner"})
    assert r.status_code == 401


def test_public_with_valid_token_ok(public_client):
    r = public_client.get("/v1/whoami", headers={"X-Participant": "eng.x", "X-Token": "engsecret"})
    assert r.status_code == 200, r.text


def test_public_uncredentialed_participant_is_401(public_client):
    """A participant created after start with no seeded secret still cannot act header-only."""
    public_client.post("/v1/participants", json={"type": "agent", "role": "qa", "handle": "qa.y", "id": "qa.y"},
                       headers={"X-Admin": "realsecret"})
    r = public_client.get("/v1/whoami", headers={"X-Participant": "qa.y"})
    assert r.status_code == 401


# --------------------------------------------------------------- §24.1(c) request token wins over env

def test_boardclient_request_token_wins_over_env(monkeypatch):
    """On the shared proxy the process env EDP8_TOKEN is the PROXY's own secret; a per-request seat
    token (forwarded X-Token) must override it so a minted-token seat authenticates as itself."""
    from edp8.client import BoardClient
    monkeypatch.setenv("EDP8_TOKEN", "proxy-secret")
    assert BoardClient(participant="eng.x", token="seat-secret")._headers()["X-Token"] == "seat-secret"
    # no request token → fall back to the process env (the owner's own stdio seat)
    assert BoardClient(participant="owner")._headers()["X-Token"] == "proxy-secret"


def test_mcp_identity_reads_x_token_header():
    from edp8 import mcp_server

    class _Ctx:
        headers = {"X-Participant": "eng.x", "X-Session": "s1", "X-Token": "seat-secret"}

    assert mcp_server._identity_from(_Ctx()) == ("eng.x", "s1", "seat-secret")


# --------------------------------------------------------------- /v1/health

def test_v1_health_shape(monkeypatch):
    monkeypatch.delenv("EDP8_PUBLIC_URL", raising=False)
    app = create_app(Board(Store(":memory:")), admin_token="secret")
    r = TestClient(app).get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["service"] == "board" and "git_rev" in body
