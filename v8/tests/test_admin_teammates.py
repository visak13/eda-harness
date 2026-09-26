"""S5 Admin → Teammates (c-b680f78023): an invite creates a human with a one-time code; redeeming it returns a
working token once; a second redeem or one after 24 h is refused; revoke makes the token 401 at once and
rotate invalidates the old token. Agent tokens are listed and revocable."""

from __future__ import annotations

import time

import pytest

from admin_support import ADMIN_H, BOB_H, make_env
from edp8 import settings
from edp8.admin import teammates


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch)


def _invite(env, handle="carol", **kw):
    r = env.client.post("/v1/admin/teammates", headers=ADMIN_H, json={"handle": handle, **kw})
    assert r.status_code == 200, r.text
    return r.json()["value"]


def _whoami(env, handle, token):
    return env.client.get("/v1/whoami", headers={"X-Participant": handle, "X-Token": token})


def test_invite_redeem_once_gives_a_working_token(env):
    v = _invite(env)
    inv = v["invite"]
    assert v["teammate"] == {**v["teammate"], "handle": "carol", "admin": False, "has_token": False}
    assert inv["link"].startswith("http://testserver/ui/join?code=") and inv["code"] in inv["link"]
    assert inv["vscode_link"].startswith("vscode://edp.edp-code/signin?") and "handle=carol" in inv["vscode_link"]
    # the human exists but cannot act until the code is redeemed
    assert env.board.participant("carol").type == "human"
    assert "carol" not in env.tokens_data()
    # the invite file keeps a hash, never the code
    assert inv["code"] not in (settings.secrets_dir() / teammates.INVITES_FILE).read_text(encoding="utf-8")

    r = env.client.post("/v1/join", json={"code": inv["code"]})
    assert r.status_code == 200, r.text
    tok = r.json()["value"]["token"]
    assert r.json()["value"]["handle"] == "carol"
    assert _whoami(env, "carol", tok).status_code == 200

    again = env.client.post("/v1/join", json={"code": inv["code"]})
    assert again.status_code == 401 and "already used or has expired" in again.text
    assert _whoami(env, "carol", tok).status_code == 200  # the failed redeem changed nothing


def test_redeem_after_24h_is_refused(env, monkeypatch):
    inv = _invite(env)["invite"]
    real = time.time
    monkeypatch.setattr(teammates.time, "time", lambda: real() + teammates.INVITE_TTL_S + 1)
    r = env.client.post("/v1/join", json={"code": inv["code"]})
    assert r.status_code == 401
    assert "carol" not in env.tokens_data()


def test_unknown_code_is_refused(env):
    assert env.client.post("/v1/join", json={"code": "nope"}).status_code == 401


def test_revoke_is_immediate_and_rotate_invalidates_old(env):
    inv = _invite(env)["invite"]
    tok = env.client.post("/v1/join", json={"code": inv["code"]}).json()["value"]["token"]
    assert _whoami(env, "carol", tok).status_code == 200

    r = env.client.post("/v1/admin/teammates/carol/rotate", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    new = r.json()["value"]["token"]
    assert new != tok
    assert _whoami(env, "carol", tok).status_code == 401
    assert _whoami(env, "carol", new).status_code == 200

    assert env.client.post("/v1/admin/teammates/carol/revoke", headers=ADMIN_H).status_code == 200
    assert _whoami(env, "carol", new).status_code == 401
    assert "carol" not in env.tokens_data()


def test_revoke_kills_a_pending_invite(env):
    inv = _invite(env)["invite"]
    assert env.client.post("/v1/admin/teammates/carol/revoke", headers=ADMIN_H).status_code == 200
    assert env.client.post("/v1/join", json={"code": inv["code"]}).status_code == 401


def test_reinvite_replaces_the_old_code(env):
    old = _invite(env)["invite"]["code"]
    new = env.client.post("/v1/admin/teammates/carol/invite", headers=ADMIN_H).json()["value"]["code"]
    assert env.client.post("/v1/join", json={"code": old}).status_code == 401
    assert env.client.post("/v1/join", json={"code": new}).status_code == 200


def test_list_shows_last_seen_admin_and_grant(env):
    assert _whoami(env, "bob", BOB_H["X-Token"]).status_code == 200
    rows = {r["handle"]: r for r in env.client.get("/v1/admin/teammates", headers=ADMIN_H).json()["value"]}
    assert rows["owner"]["admin"] and rows["owner"]["init_human"]
    assert not rows["bob"]["admin"] and rows["bob"]["last_seen"] and rows["bob"]["has_token"]
    assert "eng.x" not in rows
    # bob is refused until an admin grants it, then reaches the admin routes
    assert env.client.get("/v1/admin/teammates", headers=BOB_H).status_code == 403
    assert env.client.put("/v1/admin/teammates/bob", headers=ADMIN_H, json={"admin": True}).status_code == 200
    assert env.client.get("/v1/admin/teammates", headers=BOB_H).status_code == 200
    # the init human cannot be demoted
    assert env.client.put("/v1/admin/teammates/owner", headers=ADMIN_H, json={"admin": False}).status_code == 409


def test_creating_an_epic_grants_no_admin(env):
    r = env.client.post("/v1/tickets", headers=BOB_H,
                        json={"kind": "epic", "work_type": "feature", "title": "bob's epic", "words": "do a thing"})
    assert r.status_code == 200, r.text
    assert env.client.get("/v1/admin/teammates", headers=BOB_H).status_code == 403


def test_agent_tokens_listed_and_revoked(env):
    rows = env.client.get("/v1/admin/tokens/agents", headers=ADMIN_H).json()["value"]
    assert [r["handle"] for r in rows] == ["eng.x"] and rows[0]["role"] == "engineer"
    assert "eng-secret" not in str(rows)
    assert env.client.get("/v1/whoami", headers={"X-Participant": "eng.x", "X-Token": "eng-secret"}).status_code == 200
    assert env.client.delete("/v1/admin/tokens/agents/eng.x", headers=ADMIN_H).status_code == 200
    assert env.client.get("/v1/whoami", headers={"X-Participant": "eng.x", "X-Token": "eng-secret"}).status_code == 401
    assert env.tokens_data()["agents"]["eng.x"].startswith("revoked:")
    rows = env.client.get("/v1/admin/tokens/agents", headers=ADMIN_H).json()["value"]
    assert rows[0]["revoked"] is True
    assert env.client.delete("/v1/admin/tokens/agents/eng.x", headers=ADMIN_H).status_code == 404


def test_duplicate_and_reserved_handles(env):
    _invite(env)
    assert env.client.post("/v1/admin/teammates", headers=ADMIN_H, json={"handle": "carol"}).status_code == 409
    assert env.client.post("/v1/admin/teammates", headers=ADMIN_H, json={"handle": "agents"}).status_code == 400
