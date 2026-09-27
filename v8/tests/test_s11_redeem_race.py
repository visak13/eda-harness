"""t-501e39f939 (S11 F1, adversary m-e45404c7cc): a racing invite redemption must not restore access after
Revoke/Remove, and a removed (retired) participant never authenticates, whatever token it holds.

The redemption and revoke/remove share the invite store's lock and a per-handle revocation epoch. A revoke
that lands between the code spend and the token write makes the join fail (401, no token written); a revoke
that arrives while the token write holds the lock waits, then deletes that token. Private in-process boards
and tmp tokens files only (admin_support) — never the fleet tokens.json.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from admin_support import ADMIN_H, BOB_H, BOB_TOKEN, make_env
from edp8.admin import teammates
from edp8 import bundles
from edp8.bundles import ALL_TOOLS
from edp8.client import BoardClient


def _invite(env) -> str:
    r = env.client.post("/v1/admin/teammates/bob/invite", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    return r.json()["value"]["code"]


@pytest.mark.parametrize("action", ["revoke", "remove"])
def test_revoke_between_spend_and_token_write_refuses_the_join(tmp_path, monkeypatch, action):
    """The adversary's window: the code is spent, the token not yet written, and the revoke completes."""
    env = make_env(tmp_path, monkeypatch)
    code = _invite(env)
    entered, resume, first = threading.Event(), threading.Event(), [True]
    real_mode = teammates.token_mode

    def paused_mode(ctx):  # the join's first step after spending the code, before the commit lock
        if first[0]:
            first[0] = False
            entered.set()
            assert resume.wait(10)
        return real_mode(ctx)

    monkeypatch.setattr(teammates, "token_mode", paused_mode)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(env.client.post, "/v1/join", json={"code": code})
        try:
            assert entered.wait(10)
            revoked = env.client.post(f"/v1/admin/teammates/bob/{action}", headers=ADMIN_H)
            assert revoked.status_code == 200, revoked.text
        finally:
            resume.set()
        joined = pending.result(timeout=10)
    assert joined.status_code == 401, joined.text
    assert "bob" not in env.tokens_data()
    assert env.client.get("/v1/whoami", headers=BOB_H).status_code == 401
    assert env.board.participant("bob").retired is (action == "remove")


@pytest.mark.parametrize("action", ["revoke", "remove"])
def test_revoke_during_token_write_waits_then_wins(tmp_path, monkeypatch, action):
    """The adversary's exact seam (paused inside set_token): the revoke now waits for the write, then deletes
    the fresh token, so the joined token is refused afterwards."""
    env = make_env(tmp_path, monkeypatch)
    code = _invite(env)
    entered, resume = threading.Event(), threading.Event()
    real_set = teammates.set_token

    def paused_set(ctx, handle, secret):
        if secret is not None:
            entered.set()
            assert resume.wait(10)
        return real_set(ctx, handle, secret)

    monkeypatch.setattr(teammates, "set_token", paused_set)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(env.client.post, "/v1/join", json={"code": code})
        assert entered.wait(10)
        revoking = pool.submit(env.client.post, f"/v1/admin/teammates/bob/{action}", headers=ADMIN_H)
        try:
            with pytest.raises(TimeoutError):
                revoking.result(timeout=0.5)  # blocked on the redemption's lock
        finally:
            resume.set()
        joined, revoked = pending.result(timeout=10), revoking.result(timeout=10)
    assert revoked.status_code == 200, revoked.text
    assert joined.status_code == 200, joined.text
    token = joined.json()["value"]["token"]
    assert "bob" not in env.tokens_data()
    assert env.client.get("/v1/whoami", headers={"X-Participant": "bob", "X-Token": token}).status_code == 401


def _removed_bob_with_token(env) -> None:
    r = env.client.post("/v1/admin/teammates/bob/remove", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    data = env.tokens_data()
    data["bob"] = BOB_TOKEN  # a token that survived the Remove (a race, a restored backup)
    env.tokens.write_text(json.dumps(data), encoding="utf-8")


def test_retired_participant_with_a_valid_token_is_refused_on_rest(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    _removed_bob_with_token(env)
    r = env.client.get("/v1/whoami", headers=BOB_H)
    assert r.status_code == 401 and "removed" in r.text
    assert "bob" not in env.tokens_data()  # the leftover entry is dropped on sight
    assert env.client.post("/v1/code/session", headers=BOB_H).status_code == 401  # the code-service mint


def test_retired_participant_with_a_valid_token_is_refused_on_sse(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    _removed_bob_with_token(env)
    r = env.client.get("/v1/feed", headers=BOB_H)
    assert r.status_code == 401 and "removed" in r.text


def test_retired_participant_with_a_valid_token_is_refused_on_the_mcp_path(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    _removed_bob_with_token(env)
    monkeypatch.setattr(bundles, "_client", BoardClient(participant="bob", client=env.client, token=BOB_TOKEN))
    out = ALL_TOOLS["whoami"].handler(ALL_TOOLS["whoami"].args_model())
    assert out["ok"] is False and "removed" in str(out), out


def test_retired_admin_is_refused_on_admin_routes_and_rotate_refuses_retired(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    assert env.client.put("/v1/admin/teammates/bob", json={"admin": True}, headers=ADMIN_H).status_code == 200
    _removed_bob_with_token(env)
    assert env.client.get("/v1/admin/teammates", headers=BOB_H).status_code == 403
    assert env.client.post("/v1/admin/teammates/bob/rotate", headers=ADMIN_H).status_code == 409


def test_agent_seat_still_authenticates(tmp_path, monkeypatch):
    """Agents are never retired (a reap does not set it): the class fix leaves seat auth alone."""
    from admin_support import AGENT_H
    env = make_env(tmp_path, monkeypatch)
    assert env.client.get("/v1/whoami", headers=AGENT_H).status_code == 200


def test_reinvite_after_remove_signs_back_in(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    assert env.client.post("/v1/admin/teammates/bob/remove", headers=ADMIN_H).status_code == 200
    joined = env.client.post("/v1/join", json={"code": _invite(env)})
    assert joined.status_code == 200, joined.text
    token = joined.json()["value"]["token"]
    assert env.client.get("/v1/whoami", headers={"X-Participant": "bob", "X-Token": token}).status_code == 200
