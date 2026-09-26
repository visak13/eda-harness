"""S5 Admin → Remote access: tailnet status/apply/remove over a faked tailscale CLI, and the Tailscale
auth-key mint against a mocked Tailscale API (c-b680f78023: ephemeral, tags and expiry; refused when no
credential is configured)."""

from __future__ import annotations

import json
import tomllib

import httpx
import pytest

from admin_support import ADMIN_H, make_env
from edp8 import settings, tailnet
from edp8.admin import net

NAME = "box.tail0000.ts.net"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("EDP8_ADMIN_TOKEN", "a-real-admin-secret")
    return make_env(tmp_path, monkeypatch)


class FakeTailscale:
    def __init__(self, running=True):
        self.calls: list[list[str]] = []
        self.serve: dict = {}
        self.running = running

    def __call__(self, cmd):
        self.calls.append(cmd[1:])
        args = cmd[1:]
        if args == ["status", "--json"]:
            if not self.running:
                return 1, "not running"
            return 0, json.dumps({"BackendState": "Running", "Self": {"DNSName": NAME + "."},
                                  "CertDomains": [NAME], "Peer": {}})
        if args == ["serve", "status", "--json"]:
            return 0, json.dumps(self.serve)
        if args[:2] == ["serve", "--bg"]:
            self.serve = {"Web": {f"{NAME}:443": {"Handlers": {"/": {"Proxy": args[-1]}}}}}
            return 0, ""
        if args == ["serve", "reset"]:
            self.serve = {}
            return 0, ""
        return 1, f"unexpected {args}"


@pytest.fixture
def ts(monkeypatch):
    fake = FakeTailscale()
    monkeypatch.setattr(tailnet, "_run", fake)
    monkeypatch.setattr(tailnet, "listeners", lambda: {})
    return fake


def test_status_apply_remove(env, ts):
    v = env.client.get("/v1/admin/tailnet", headers=ADMIN_H).json()["value"]
    assert v["tailnet_url"] == f"https://{NAME}" and v["public_mode"] is False
    assert v["auth_keys"] == {"configured": False}
    assert "a-real-admin-secret" not in json.dumps(v)

    r = env.client.post("/v1/admin/tailnet/apply", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    port = settings.get("EDP8_PORT")
    assert ["serve", "--bg", "--https=443", f"http://127.0.0.1:{port}"] in ts.calls
    cfg = tomllib.loads(settings.config_file().read_text(encoding="utf-8"))
    assert cfg["network"]["public_url"] == f"https://{NAME}" and cfg["board"]["host"] == "127.0.0.1"
    assert r.json()["value"]["restart_required"] == ["board", "mcp"]

    v = env.client.get("/v1/admin/tailnet", headers=ADMIN_H).json()["value"]
    assert v["public_mode"] and v["serve_proxies"] == [{"from": f"{NAME}:443", "to": f"http://127.0.0.1:{port}"}]

    r = env.client.post("/v1/admin/tailnet/remove", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    assert ["serve", "reset"] in ts.calls
    assert "public_url" not in tomllib.loads(settings.config_file().read_text(encoding="utf-8")).get("network", {})


def test_apply_fails_closed_on_the_dev_admin_token(env, ts, monkeypatch):
    monkeypatch.setenv("EDP8_ADMIN_TOKEN", "dev")
    r = env.client.post("/v1/admin/tailnet/apply", headers=ADMIN_H, json={"force": True})
    assert r.status_code == 409 and "EDP8_ADMIN_TOKEN" in r.text
    assert not any(c[:2] == ["serve", "--bg"] for c in ts.calls)
    assert not settings.config_file().exists()


def test_apply_refuses_without_agent_credentials(env, ts):
    data = env.tokens_data()
    data["agents"] = {}
    env.tokens.write_text(json.dumps(data), encoding="utf-8")
    r = env.client.post("/v1/admin/tailnet/apply", headers=ADMIN_H, json={"force": True})
    assert r.status_code == 409 and "agent credentials" in r.text


def test_apply_refuses_when_tailscale_is_down(env, monkeypatch):
    monkeypatch.setattr(tailnet, "_run", FakeTailscale(running=False))
    monkeypatch.setattr(tailnet, "listeners", lambda: {})
    r = env.client.post("/v1/admin/tailnet/apply", headers=ADMIN_H)
    assert r.status_code == 409 and "tailscale is not running" in r.text


def test_apply_refuses_env_set_public_url(env, ts, monkeypatch):
    monkeypatch.setenv("EDP8_PUBLIC_URL", "https://elsewhere")
    monkeypatch.setenv("EDP8_TOKENS", str(env.tokens))
    r = env.client.post("/v1/admin/tailnet/apply", headers=ADMIN_H)
    assert r.status_code == 409 and "set by the environment" in r.text


# --------------------------------------------------------------- Tailscale auth keys (R7b)

@pytest.fixture
def tsapi(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/api/v2/oauth/token":
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            if form.get("client_secret") != "ts-secret":
                return httpx.Response(401, json={"message": "bad client"})
            return httpx.Response(200, json={"access_token": "tok-1", "token_type": "Bearer"})
        if req.url.path == "/api/v2/tailnet/-/keys":
            assert req.headers["Authorization"] == "Bearer tok-1"
            body = json.loads(req.content)
            return httpx.Response(200, json={"id": "k123", "key": "tskey-auth-k123-XYZ",
                                             "expires": "2026-09-28T00:00:00Z",
                                             "capabilities": body["capabilities"]})
        return httpx.Response(404)

    monkeypatch.setattr(net, "transport", httpx.MockTransport(handler))
    monkeypatch.setenv("EDP_TAILSCALE_API_URL", "https://ts.mock")
    return seen


def test_auth_key_refused_without_credential(env, tsapi):
    r = env.client.post("/v1/admin/teammates/bob/tailscale-key", headers=ADMIN_H)
    assert r.status_code == 409 and "Tailscale auth keys are off" in r.text
    assert tsapi == []


def test_auth_key_mint_sends_ephemeral_tags_expiry(env, tsapi):
    r = env.client.put("/v1/admin/settings", headers=ADMIN_H, json={"values": {
        "tailscale.oauth_client_id": "client-1", "tailscale.oauth_client_secret": "ts-secret"}})
    assert r.status_code == 200, r.text
    assert "ts-secret" not in env.client.get("/v1/admin/settings", headers=ADMIN_H).text
    r = env.client.post("/v1/admin/teammates/bob/tailscale-key", headers=ADMIN_H,
                        json={"expiry_s": 3600, "tags": ["tag:laptop"]})
    assert r.status_code == 200, r.text
    v = r.json()["value"]
    assert v["key"] == "tskey-auth-k123-XYZ" and v["teammate"] == "bob"
    body = json.loads(tsapi[-1].content)
    assert body["expirySeconds"] == 3600
    assert body["capabilities"]["devices"]["create"] == {"reusable": False, "ephemeral": True,
                                                         "preauthorized": True, "tags": ["tag:laptop"]}
    # default tags come from the setting
    r = env.client.post("/v1/admin/teammates/bob/tailscale-key", headers=ADMIN_H, json={"ephemeral": False})
    create = json.loads(tsapi[-1].content)["capabilities"]["devices"]["create"]
    assert r.status_code == 200 and create["tags"] == ["tag:heronry"] and create["ephemeral"] is False
    # the key is never stored
    assert "tskey-auth" not in env.tokens.read_text(encoding="utf-8")
    assert env.client.get("/v1/admin/tailnet", headers=ADMIN_H).json()["value"]["auth_keys"] == {"configured": True}


def test_auth_key_bad_credential_is_502(env, tsapi, monkeypatch):
    monkeypatch.setenv("EDP_TAILSCALE_OAUTH_CLIENT_ID", "client-1")
    monkeypatch.setenv("EDP_TAILSCALE_OAUTH_CLIENT_SECRET", "wrong")
    r = env.client.post("/v1/admin/teammates/bob/tailscale-key", headers=ADMIN_H)
    assert r.status_code == 502 and "refused the OAuth client" in r.text


def test_status_says_the_mode_the_running_board_started_in(env, ts):
    # t-20f0718990: the guided setup's last step (restart) is done only when THIS process runs public;
    # config.toml flips at apply, the running board does not
    v = env.client.get("/v1/admin/tailnet", headers=ADMIN_H).json()["value"]
    assert v["running_public"] is False
    assert env.client.post("/v1/admin/tailnet/apply", headers=ADMIN_H).status_code == 200
    v = env.client.get("/v1/admin/tailnet", headers=ADMIN_H).json()["value"]
    assert v["public_mode"] is True and v["running_public"] is False


def test_guide_renders_the_same_steps(env, tmp_path, monkeypatch):
    # t-20f0718990: Remote access links guides/remote-access.md, rendered through the sanitised markdown path
    home = tmp_path / "home"
    (home / "guides").mkdir(parents=True)
    (home / "guides" / "remote-access.md").write_text("# Remote access\n\n## 2. Install Tailscale\n![d](../assets/guides/x.svg)\n<script>x</script>\n",
                                                     encoding="utf-8")
    monkeypatch.setattr(settings, "agent_home", lambda: home)
    r = env.client.get("/v1/admin/tailnet/guide", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    v = r.json()["value"]
    assert v["path"] == "guides/remote-access.md" and "<h2>2. Install Tailscale</h2>" in v["html"]
    assert "<script>" not in v["html"]
    assert "<img" not in v["html"]  # repo-relative diagrams would render broken; each step shows its own
    (home / "guides" / "remote-access.md").unlink()
    assert env.client.get("/v1/admin/tailnet/guide", headers=ADMIN_H).status_code == 404


def test_the_shipped_guide_names_every_step():
    from pathlib import Path
    body = (Path(__file__).resolve().parents[1] / "guides" / "remote-access.md").read_text(encoding="utf-8")
    for step in ("## 1. What it is for", "## 2. Install Tailscale", "## 3. Sign in", "## 4. Readiness",
                 "## 5. Serve the board", "## 6. Restart the board and MCP"):
        assert step in body, step
    for n in range(1, 7):
        assert f"assets/guides/remote-access-{n}-" in body
