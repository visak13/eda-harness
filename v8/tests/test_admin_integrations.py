"""S5 Admin → Integrations (c-3116ef3a92, first half): the Slack test ping works against a mock webhook;
slack_map.json round-trips unchanged for unedited keys; secrets are masked; Plane / code-server / VS Code
have status and test endpoints."""

from __future__ import annotations

import json

import httpx
import pytest

from admin_support import ADMIN_H, make_env
from edp8 import settings
from edp8.admin import net

HOOK = "https://hooks.slack.com/services/T000/B000/SECRETHOOK1234"
CAROL_HOOK = "https://hooks.slack.com/services/T000/B111/CAROLHOOK9876"
ORIGINAL = {
    "board_url": "http://100.64.0.1:9400",
    "webhook_url": HOOK,
    "bot_token": "xoxb-very-secret",
    "people": {"carol": {"slack_id": "U123", "quiet": [22, 7], "webhook_url": CAROL_HOOK},
               "dave": {"slack_id": "U456", "quiet": None}},
    "x_custom": {"nested": [1, 2, {"k": "v"}]},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_CONFIG_DIR", str(tmp_path / "cfg"))
    f = tmp_path / "cfg" / "slack_map.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps(ORIGINAL, indent=2), encoding="utf-8")
    e = make_env(tmp_path, monkeypatch)
    e.slack = f
    return e


def test_get_masks_secrets(env):
    r = env.client.get("/v1/admin/integrations/slack", headers=ADMIN_H)
    assert r.status_code == 200
    body = r.text
    for secret in ("xoxb-very-secret", "SECRETHOOK", "CAROLHOOK"):
        assert secret not in body
    v = r.json()["value"]
    assert v["bot_token_set"] and v["webhook_set"] and v["config"]["bot_token"] == "********"
    assert v["config"]["webhook_url"].startswith("https://hooks.slack.com/") and v["config"]["webhook_url"].endswith("1234")
    assert set(v["people_effective"]) == {"carol", "dave"}


def test_put_round_trips_unedited_keys(env):
    view = env.client.get("/v1/admin/integrations/slack", headers=ADMIN_H).json()["value"]["config"]
    # the SPA sends back what it got (masks included) with one field edited
    view["board_url"] = "https://box.tail0000.ts.net"
    r = env.client.put("/v1/admin/integrations/slack", headers=ADMIN_H, json={"values": view})
    assert r.status_code == 200, r.text
    got = json.loads(env.slack.read_text(encoding="utf-8"))
    assert got["board_url"] == "https://box.tail0000.ts.net"
    for k in ("webhook_url", "bot_token", "people", "x_custom"):
        assert got[k] == ORIGINAL[k], k
    assert list(got) == list(ORIGINAL)
    # a partial PUT touches only its key
    r = env.client.put("/v1/admin/integrations/slack", headers=ADMIN_H, json={"values": {"bot_token": "xoxb-new"}})
    got = json.loads(env.slack.read_text(encoding="utf-8"))
    assert got["bot_token"] == "xoxb-new" and {k: got[k] for k in ORIGINAL if k not in ("board_url", "bot_token")} == \
        {k: ORIGINAL[k] for k in ORIGINAL if k not in ("board_url", "bot_token")}


def test_put_refuses_a_non_slack_webhook(env):
    r = env.client.put("/v1/admin/integrations/slack", headers=ADMIN_H,
                       json={"values": {"webhook_url": "https://evil.example/hook"}})
    assert r.status_code == 400
    assert json.loads(env.slack.read_text(encoding="utf-8")) == ORIGINAL


@pytest.fixture
def slack_mock(monkeypatch):
    posts: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        posts.append(req)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: client.post(url, **{k: v for k, v in kw.items() if k != "timeout"}))
    return posts


def test_slack_test_ping_default_webhook(env, slack_mock):
    r = env.client.post("/v1/admin/integrations/slack/test", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    assert str(slack_mock[-1].url) == HOOK
    assert "test ping from owner" in json.loads(slack_mock[-1].content)["text"]


def test_slack_test_ping_one_person(env, slack_mock):
    r = env.client.post("/v1/admin/integrations/slack/test", headers=ADMIN_H, json={"handle": "carol"})
    assert r.status_code == 200, r.text
    # bot token + slack_id: a DM through chat.postMessage
    assert str(slack_mock[-1].url) == "https://slack.com/api/chat.postMessage"
    assert env.client.post("/v1/admin/integrations/slack/test", headers=ADMIN_H,
                           json={"handle": "nobody"}).status_code == 404


def test_slack_test_ping_failure_is_502(env, monkeypatch):
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: client.post(url, json=kw.get("json")))
    assert env.client.post("/v1/admin/integrations/slack/test", headers=ADMIN_H).status_code == 502


def test_plane_status_put_and_test(env, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        if req.headers.get("X-API-Key") == "pk" and req.url.path == "/api/v1/workspaces/ws/projects/p1/":
            return httpx.Response(200, json={"name": "Heronry"})
        return httpx.Response(403)

    monkeypatch.setattr(net, "transport", httpx.MockTransport(handler))
    v = env.client.get("/v1/admin/integrations/plane", headers=ADMIN_H).json()["value"]
    assert v["configured"] is False
    assert env.client.post("/v1/admin/integrations/plane/test", headers=ADMIN_H).status_code == 409
    r = env.client.put("/v1/admin/integrations/plane", headers=ADMIN_H, json={"values": {
        "plane.url": "https://plane.mock", "plane.api_key": "pk", "plane.workspace": "ws", "plane.project": "p1"}})
    assert r.status_code == 200, r.text
    assert "pk" not in json.dumps(r.json()["value"]["settings"])
    assert r.json()["value"]["restart_required"] == ["board"]
    r = env.client.post("/v1/admin/integrations/plane/test", headers=ADMIN_H)
    assert r.status_code == 200 and "Heronry" in r.text
    assert env.client.put("/v1/admin/integrations/plane", headers=ADMIN_H,
                          json={"values": {"board.port": 1}}).status_code == 400


def test_code_server_and_vscode(env, monkeypatch):
    monkeypatch.setenv("EDP_CODE_PORT", "1")  # nothing listens on port 1
    v = env.client.get("/v1/admin/integrations/code-server", headers=ADMIN_H).json()["value"]
    assert v["port"] == 1 and v["running"] is False
    assert env.client.post("/v1/admin/integrations/code-server/test", headers=ADMIN_H).status_code == 502
    v = env.client.get("/v1/admin/integrations/vscode", headers=ADMIN_H).json()["value"]
    assert v["vsix_url"] == f"https://github.com/{settings.get('EDP_UPDATE_REPO')}/releases/latest"
    assert v["signin_links"]["bob"].startswith("vscode://edp.edp-code/signin?board=")
    monkeypatch.setattr(net, "transport", httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True})))
    assert env.client.post("/v1/admin/integrations/vscode/test", headers=ADMIN_H).status_code == 200
    summary = env.client.get("/v1/admin/integrations", headers=ADMIN_H).json()["value"]
    assert set(summary) == {"slack", "plane", "code_server", "vscode"}
