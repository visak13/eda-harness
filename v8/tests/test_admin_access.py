"""t-882e4d2eeb accounts: Sign out (c-7942213d3f), Request access (c-c0bdff80eb) and retired humans
(c-0785f1b2b1).

Request access end to end: a person with no token asks from the sign-in page; every admin human sees the
pending record; Approve issues the S5 invite and the requester's browser receives the token exactly once
through its claim code; a second claim, a wrong code and the rate limits all fail; the token appears in no
board record, message, event, URL or log line."""

from __future__ import annotations

import json
import logging

import pytest

from admin_support import ADMIN_H, BOB_H, OWNER_TOKEN, make_env
from edp8 import settings
from edp8.admin import access, teammates
from edp8.code_guard import GUARD_COOKIE


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path, monkeypatch)
    e.app.state.public_mode = True  # Remote access on: this board process runs in public mode
    return e


def _ask(env, name="Dana Lee", **kw):
    return env.client.post("/v1/access-requests", json={"name": name, "role_wanted": "owner", "note": "design", **kw})


def _claim(env, code):
    return env.client.post("/v1/access-requests/claim", json={"code": code})


def _whoami(env, handle, token):
    return env.client.get("/v1/whoami", headers={"X-Participant": handle, "X-Token": token})


# ------------------------------------------------------------------ sign out
def test_signout_expires_the_guard_cookie_and_the_next_call_without_the_token_is_401(env):
    assert _whoami(env, "owner", OWNER_TOKEN).status_code == 200
    env.client.cookies.set(GUARD_COOKIE, "gate-value", domain="testserver.local")  # httpx names the host so
    r = env.client.post("/v1/signout")  # no credential needed: a signed-out tab may call it
    assert r.status_code == 200 and r.json()["value"] == {"signed_out": True}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{GUARD_COOKIE}=") and "Max-Age=0" in cookie and "Path=/" in cookie
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert GUARD_COOKIE not in env.client.cookies  # the client dropped it
    # the SPA drops its token and its identity: the next request carries neither and is refused
    assert env.client.get("/v1/whoami", headers={"X-Participant": ""}).status_code == 401
    assert env.client.get("/v1/whoami", headers={"X-Participant": "owner"}).status_code == 401


# ------------------------------------------------------------------ request access
def test_request_access_end_to_end_and_the_token_travels_once(env, caplog):
    caplog.set_level(logging.DEBUG)
    assert env.client.get("/v1/access-requests/available").json()["value"]["enabled"] is True

    r = _ask(env)
    assert r.status_code == 200, r.text
    req_id, code = r.json()["value"]["id"], r.json()["value"]["claim_code"]
    assert _claim(env, code).json()["value"]["status"] == "pending"

    # the record admins see: no code, no token
    rec = env.board.store.get("access_request", req_id)
    assert (rec.status, rec.name, rec.role_wanted) == ("pending", "Dana Lee", "owner")
    assert code not in rec.model_dump_json()
    # the claims file keeps a hash, never the code
    assert code not in (settings.secrets_dir() / access.CLAIMS_FILE).read_text(encoding="utf-8")

    # admins list it; a non-admin human and a code-holder cannot decide it
    listed = env.client.get("/v1/admin/access-requests", headers=ADMIN_H).json()["value"]
    assert [x["id"] for x in listed] == [req_id] and listed[0]["status"] == "pending"
    assert env.client.post(f"/v1/admin/access-requests/{req_id}/approve", headers=BOB_H).status_code == 403
    assert env.client.post(f"/v1/admin/access-requests/{req_id}/approve", json={}).status_code == 403

    ok = env.client.post(f"/v1/admin/access-requests/{req_id}/approve", headers=ADMIN_H, json={})
    assert ok.status_code == 200, ok.text
    assert ok.json()["value"]["handle"] == "dana-lee" and "token" not in ok.text
    assert env.board.participant("dana-lee").type == "human"
    # owner m-ab7c81eb8d: she asked for member; one click on Approve made her a guest
    assert env.board.participant("dana-lee").role == "guest"
    # deciding twice is refused
    assert env.client.post(f"/v1/admin/access-requests/{req_id}/deny", headers=ADMIN_H).status_code == 409

    got = _claim(env, code)
    assert got.status_code == 200, got.text
    v = got.json()["value"]
    assert v["status"] == "approved" and v["handle"] == "dana-lee"
    token = v["token"]
    assert _whoami(env, "dana-lee", token).status_code == 200
    assert env.board.store.get("access_request", req_id).status == "claimed"

    # the claim is burned: the same code again is refused, and the token did not change
    assert _claim(env, code).status_code == 401
    assert _whoami(env, "dana-lee", token).status_code == 200

    # no token in any board record, message or event; no code or token in any log line
    store = env.board.store
    for kind in ("access_request", "message", "event", "participant"):
        for obj in store.query(kind, {}, limit=5000):
            assert token not in obj.model_dump_json(), kind
    for rec_ in caplog.records:
        line = rec_.getMessage()
        assert token not in line and code not in line
    # and no URL: every route took the code in a POST body
    for path in {r.path for r in env.app.routes if hasattr(r, "path")}:
        assert token not in path and code not in path


def test_a_wrong_code_fails(env):
    _ask(env)
    assert _claim(env, "not-a-code").status_code == 401


def test_deny_tells_the_browser_once_then_burns(env):
    v = _ask(env).json()["value"]
    assert env.client.post(f"/v1/admin/access-requests/{v['id']}/deny", headers=ADMIN_H).status_code == 200
    assert _claim(env, v["claim_code"]).json()["value"] == {"status": "denied"}
    assert _claim(env, v["claim_code"]).status_code == 401
    assert env.board.store.get("access_request", v["id"]).status == "denied"


def test_ask_rate_limit_per_client(env):
    for i in range(access.ASK_PER_CLIENT):
        assert _ask(env, name=f"p{i}").status_code == 200
    r = _ask(env, name="one-more")
    assert r.status_code == 429 and "too many" in r.text


def test_ask_rate_limit_is_per_forwarded_client_behind_tailscale_serve(env):
    for i in range(access.ASK_PER_CLIENT):
        assert _ask(env, name=f"a{i}").status_code == 200
    # another machine behind the same loopback proxy has its own budget
    r = env.client.post("/v1/access-requests", json={"name": "b"}, headers={"X-Forwarded-For": "100.64.0.9"})
    assert r.status_code == 200, r.text


def test_claim_rate_limit(env):
    code = _ask(env).json()["value"]["claim_code"]
    for _ in range(access.CLAIM_PER_CLIENT):
        assert _claim(env, code).status_code == 200
    assert _claim(env, code).status_code == 429


def test_off_when_remote_access_is_off(env):
    env.app.state.public_mode = False
    av = env.client.get("/v1/access-requests/available").json()["value"]
    assert av["enabled"] is False and "Remote access is off" in av["reason"]
    r = _ask(env)
    assert r.status_code == 409 and "Remote access is off" in r.text


def test_approve_with_a_taken_handle_asks_for_another(env):
    v = _ask(env, name="Bob").json()["value"]
    r = env.client.post(f"/v1/admin/access-requests/{v['id']}/approve", headers=ADMIN_H, json={})
    assert r.status_code == 409 and "choose another handle" in r.text
    r = env.client.post(f"/v1/admin/access-requests/{v['id']}/approve", headers=ADMIN_H, json={"handle": "bob2"})
    assert r.status_code == 200 and r.json()["value"]["handle"] == "bob2"


# ------------------------------------------------------------------ retired humans
def _people(env, headers=ADMIN_H):
    return {p["handle"] for p in env.client.get("/v1/me/people", headers=headers).json()["value"]}


def _seats(env):
    return env.client.get("/v1/seats", headers=ADMIN_H).json()["value"]


def test_removed_revoked_and_expired_humans_leave_every_people_list(env, monkeypatch):
    # carol: invited, pending -> listed; erin: invited and redeemed, then revoked -> gone
    for h in ("carol", "erin"):
        assert env.client.post("/v1/admin/teammates", headers=ADMIN_H, json={"handle": h}).status_code == 200
    assert {"bob", "carol", "erin"} <= _people(env)
    erin_code = teammates.invite_store().issue("erin", "owner")[0]
    assert env.client.post("/v1/join", json={"code": erin_code}).status_code == 200
    assert env.client.post("/v1/admin/teammates/erin/revoke", headers=ADMIN_H).status_code == 200
    assert "erin" not in _people(env)

    # Remove = revoke + retire, with the init human and self refused
    assert env.client.post("/v1/admin/teammates/owner/remove", headers=ADMIN_H).status_code == 409
    r = env.client.post("/v1/admin/teammates/bob/remove", headers=ADMIN_H)
    assert r.status_code == 200 and r.json()["value"]["removed"] is True
    assert "bob" not in env.tokens_data()
    assert env.client.get("/v1/whoami", headers=BOB_H).status_code == 401
    assert env.board.participant("bob").retired is True
    assert "bob" not in _people(env)

    # carol's invite expires unredeemed -> gone too
    real = teammates.time.time
    monkeypatch.setattr(teammates.time, "time", lambda: real() + teammates.INVITE_TTL_S + 1)
    assert "carol" not in _people(env)
    monkeypatch.setattr(teammates.time, "time", real)

    seats = _seats(env)
    people = {p["handle"] for p in seats["people"]}
    retired = {p["handle"] for p in seats["retired"]}
    assert "owner" in people and not people & {"bob", "erin"}
    assert {"bob", "erin"} <= retired  # history greys these names

    # the admin list still shows the removed teammate, flagged
    rows = {x["handle"]: x for x in env.client.get("/v1/admin/teammates", headers=ADMIN_H).json()["value"]}
    assert rows["bob"]["retired"] is True and rows["erin"]["retired"] is False and rows["erin"]["has_token"] is False

    # a fresh invite brings a removed teammate back
    inv = env.client.post("/v1/admin/teammates/bob/invite", headers=ADMIN_H)
    assert inv.status_code == 200 and env.board.participant("bob").retired is False
    assert "bob" in _people(env)


def test_trusted_mode_lists_every_human_not_removed(tmp_path, monkeypatch):
    e = make_env(tmp_path, monkeypatch)
    e.tokens.unlink()  # no tokens file: trusted single-machine mode, header-only identity
    h = {"X-Participant": "owner"}
    assert "bob" in _people(e, h)
    bob = e.board.participant("bob")
    e.board.store.put("participant", bob.model_copy(update={"retired": True}))
    assert "bob" not in _people(e, h)


def test_views_rule_without_a_service_skips_only_retired(env):
    from edp8 import views
    from edp8.board import Board
    from edp8.store import Store
    b = Board(Store(":memory:"))
    p = b.participant_create("human", "owner", "zed")
    assert views.human_active(b, p) is True
    assert views.human_active(b, p.model_copy(update={"retired": True})) is False


def test_claims_file_is_json_of_hashes(env):
    code = _ask(env).json()["value"]["claim_code"]
    data = json.loads((settings.secrets_dir() / access.CLAIMS_FILE).read_text(encoding="utf-8"))
    assert list(data) == [access._hash(code)]


def test_expired_requests_neither_fill_the_cap_nor_answer_pending(env):
    """S11 F4 (m-7597af9fac): one live_pending() rule. Requests past the TTL used to count against MAX_PENDING
    while the admin list hid them, so a full queue of stale rows 429'd every new asker."""
    from datetime import timedelta

    from edp8.schemas import AccessRequest, now
    old = now() - timedelta(seconds=access.CLAIM_TTL_S + 3600)
    for i in range(access.MAX_PENDING):
        env.board.store.put("access_request", AccessRequest(id=f"acc-old-{i}", created_by="", name=f"Old {i}",
                                                            created_at=old))
    assert env.client.get("/v1/admin/access-requests", headers=ADMIN_H).json()["value"] == []
    assert env.board.store.get("access_request", "acc-old-0").status == "expired"  # marked on read
    r = _ask(env, name="Legitimate new person")
    assert r.status_code == 200, r.text
    listed = env.client.get("/v1/admin/access-requests", headers=ADMIN_H).json()["value"]
    assert [q["name"] for q in listed] == ["Legitimate new person"]
    # the cap still binds on live requests only
    for i in range(access.MAX_PENDING - 1):
        env.board.store.put("access_request", AccessRequest(id=f"acc-live-{i}", created_by="", name=f"Live {i}"))
    assert len(access.live_pending(env.board)) == access.MAX_PENDING
    assert _ask(env, name="One too many").status_code == 429
    # a claim whose request went past the TTL while it waited answers expired (not pending), then is spent
    q = env.board.store.get("access_request", r.json()["value"]["id"])
    env.board.store.put("access_request", q.model_copy(update={"created_at": old}))
    code = r.json()["value"]["claim_code"]
    c = _claim(env, code)
    assert c.status_code == 200 and c.json()["value"] == {"status": "expired"}
    assert env.board.store.get("access_request", q.id).status == "expired"
    assert _claim(env, code).status_code == 401
    # and an admin cannot approve it any more
    assert env.client.post(f"/v1/admin/access-requests/{q.id}/approve", headers=ADMIN_H).status_code == 409


# ------------------------------------------------------------------ who is external (owner m-ab7c81eb8d)
def _pending_id(env, name):
    r = _ask(env, name=name)
    assert r.status_code == 200, r.text
    return r.json()["value"]["id"]


def test_a_person_can_only_ask_for_or_be_granted_guest_or_member(env):
    assert env.client.get("/v1/access-requests/available").json()["value"]["roles"] == ["guest", "owner"]
    for role in ("architect", "engineer", "qa", "expert", "doctor"):
        assert _ask(env, name=f"Asker {role}", role_wanted=role).status_code == 400, role
    req = _pending_id(env, "Ana Ruiz")
    for role in ("architect", "engineer", "qa", "expert"):
        r = env.client.post(f"/v1/admin/access-requests/{req}/approve", headers=ADMIN_H, json={"role": role})
        assert r.status_code == 400, role
    assert env.board.store.get("access_request", req).status == "pending"


def test_approve_grants_member_only_when_the_admin_chooses_it(env):
    req = _pending_id(env, "Lee Park")
    ok = env.client.post(f"/v1/admin/access-requests/{req}/approve", headers=ADMIN_H, json={"role": "owner"})
    assert ok.status_code == 200, ok.text
    assert env.board.participant("lee-park").role == "owner"


def test_a_guest_cannot_be_approved_as_an_admin(env):
    req = _pending_id(env, "Sam Cole")
    r = env.client.post(f"/v1/admin/access-requests/{req}/approve", headers=ADMIN_H, json={"admin": True})
    assert r.status_code == 400 and "guest cannot be an admin" in r.text
    assert env.board.store.get("access_request", req).status == "pending"


def _notice_of(env, data):
    notices = env.board.store.query("message", {"created_by": "board"}, limit=100)
    return next(m for m in notices if data["id"] in m.text)


def test_f5_simultaneous_expiry_settles_every_notice_on_an_attention_read(env, monkeypatch):
    """Nobody opens /v1/admin/access-requests: the attention and inbox reads reconcile expiry themselves."""
    first, second = _ask(env).json()["value"], _ask(env, name="Kim Ro").json()["value"]
    n1, n2 = _notice_of(env, first), _notice_of(env, second)
    assert n1.id in env.client.get("/v1/me/attention", headers=ADMIN_H).text
    real_time = access.time.time
    monkeypatch.setattr(access.time, "time", lambda: real_time() + access.CLAIM_TTL_S + 60)  # both expire together
    att = env.client.get("/v1/me/attention", headers=ADMIN_H).text
    assert n1.id not in att and n2.id not in att
    for rid in (first["id"], second["id"]):
        assert env.board.store.get("access_request", rid).status == "expired"


def test_f5_simultaneous_expiry_settles_every_notice_on_an_inbox_read(env, monkeypatch):
    first, second = _ask(env).json()["value"], _ask(env, name="Kim Ro").json()["value"]
    n1, n2 = _notice_of(env, first), _notice_of(env, second)
    real_time = access.time.time
    monkeypatch.setattr(access.time, "time", lambda: real_time() + access.CLAIM_TTL_S + 60)
    inbox = env.client.get("/v1/inbox", headers=ADMIN_H).text
    assert n1.id not in inbox and n2.id not in inbox


def test_f5_the_claim_path_settles_an_expired_request(env, monkeypatch):
    data = _ask(env).json()["value"]
    notice = _notice_of(env, data)
    real_time = access.time.time
    monkeypatch.setattr(access.time, "time", lambda: real_time() + access.CLAIM_TTL_S + 60)
    assert _claim(env, data["claim_code"]).status_code == 401
    assert env.board.store.get("access_request", data["id"]).status == "expired"
    assert notice.id not in env.client.get("/v1/me/attention", headers=ADMIN_H).text
