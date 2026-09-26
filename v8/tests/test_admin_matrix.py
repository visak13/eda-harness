"""S5 authorization matrix (c-2d201fb8c8): EVERY `/v1/admin/*` route — enumerated from the app's own route
table, so a route added later is covered without editing this file — answers 403 to a non-admin human
token, an agent token, an X-Participant-only request and a machine X-Admin-only request, and passes the
gate for an admin human token (every GET answers 200). Secrets never come back from a GET, and `/v1/join`
is the only route the admin package adds outside `/v1/admin`."""

from __future__ import annotations

import json
import re

import httpx
import pytest

from admin_support import ADMIN_H, AGENT_H, BOB_H, MACHINE_ADMIN, make_env
from edp8 import control, pool_adapter, tailnet
from edp8.admin import PUBLIC_ROUTES, AdminContext, admin_router
from edp8.admin import harnesses as H
from edp8.admin import net

DENIED = {
    "non-admin human": BOB_H,
    "agent token": AGENT_H,
    "X-Participant only": {"X-Participant": "owner"},
    "X-Admin only": {"X-Admin": MACHINE_ADMIN},
    "admin handle, wrong token": {"X-Participant": "owner", "X-Token": "nope"},
}
SECRETS = ("ts-secret-value", "plane-key-value", "xoxb-bot-value", "SECRETHOOK9999")
SAMPLE = {"svc": "pool", "verb": "restart", "handle": "bob", "h": "pi"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("EDP_CONFIG_DIR", str(cfg))
    (cfg / "slack_map.json").write_text(json.dumps({
        "webhook_url": "https://hooks.slack.com/services/T0/B0/SECRETHOOK9999", "bot_token": "xoxb-bot-value",
        "people": {"bob": {"slack_id": "U1"}}}), encoding="utf-8")
    monkeypatch.setenv("EDP_TAILSCALE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("EDP_TAILSCALE_OAUTH_CLIENT_SECRET", "ts-secret-value")
    monkeypatch.setenv("EDP_PLANE_API_KEY", "plane-key-value")
    # nothing reaches a real process or network: every outward seam is faked
    monkeypatch.setattr(tailnet, "_run", lambda cmd: (1, "tailscale faked off"))
    monkeypatch.setattr(tailnet, "listeners", lambda: {})
    monkeypatch.setattr(net, "transport", httpx.MockTransport(lambda req: httpx.Response(503)))
    monkeypatch.setattr(pool_adapter, "sessions", lambda: {"ok": False, "error": "faked"})
    monkeypatch.setattr(H, "_run", lambda argv, timeout=0: (1, "faked"))
    monkeypatch.setattr(H, "find_tool", lambda name, key=None: None)

    def no_supervisor(*a, **kw):
        raise control.ControlUnavailable("faked")

    monkeypatch.setattr(control, "request", no_supervisor)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Response(503, request=httpx.Request("POST", "http://x")))
    return make_env(tmp_path, monkeypatch)


def _routes(app) -> list[tuple[str, str]]:
    """(method, path) of every /v1/admin route, from the app's OpenAPI table (FastAPI >=0.141 includes
    routers lazily, so `app.routes` holds wrappers; the schema is the flattened table)."""
    out = []
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/v1/admin"):
            out += [(m.upper(), path) for m in ops if m in ("get", "post", "put", "delete", "patch")]
    return sorted(out)


def _concrete(path: str) -> str:
    return re.sub(r"\{(\w+)(?::\w+)?\}", lambda m: SAMPLE.get(m.group(1), "x"), path)


def test_the_route_table_is_the_admin_surface(env):
    routes = _routes(env.app)
    assert len(routes) >= 30, routes
    paths = {p for _, p in routes}
    for expected in ("/v1/admin/settings", "/v1/admin/services/{svc}/{verb}", "/v1/admin/teammates",
                     "/v1/admin/tailnet", "/v1/admin/integrations/slack", "/v1/admin/harnesses",
                     "/v1/admin/updates"):
        assert expected in paths, expected
    # outside /v1/admin the admin package adds only the public routes: the invite redeem, and t-882e4d2eeb's
    # sign out and request access (their own credential-free guards are tested in test_admin_access.py)
    from fastapi import FastAPI
    solo = FastAPI()
    solo.include_router(admin_router(AdminContext(board=env.board, tokens=lambda: {}, write_tokens=lambda h: None,
                                                  tokens_file=env.tokens, last_seen=None)))
    stray = {p for p in solo.openapi()["paths"] if not p.startswith("/v1/admin")}
    assert stray == set(PUBLIC_ROUTES) == {"/v1/join", "/v1/signout", "/v1/access-requests",
                                           "/v1/access-requests/available", "/v1/access-requests/claim"}


@pytest.mark.parametrize("who", list(DENIED))
def test_every_admin_route_refuses_non_admins(env, who):
    wrong = []
    for method, path in _routes(env.app):
        r = env.client.request(method, _concrete(path), headers=DENIED[who], json={})
        if r.status_code != 403:
            wrong.append((method, path, r.status_code, r.text[:120]))
    assert wrong == [], wrong


def test_every_admin_route_passes_the_gate_for_an_admin(env):
    wrong = []
    for method, path in _routes(env.app):
        r = env.client.request(method, _concrete(path), headers=ADMIN_H, json={} if method != "GET" else None)
        if r.status_code in (401, 403) or r.status_code >= 500 and r.status_code not in (502, 503) \
                or method == "GET" and r.status_code != 200:
            wrong.append((method, path, r.status_code, r.text[:160]))
    assert wrong == [], wrong


def test_no_get_returns_a_secret(env):
    for method, path in _routes(env.app):
        if method == "GET":
            body = env.client.get(_concrete(path), headers=ADMIN_H).text
            for s in SECRETS:
                assert s not in body, (path, s)
