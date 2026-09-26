"""S5 Admin → Settings: GET lists every registry key (secrets masked, env read-only), PUT writes
config.toml or the owner-only secrets file and refuses env-set keys with a named reason."""

from __future__ import annotations

import tomllib

import pytest

from admin_support import ADMIN_H, make_env
from edp8 import settings


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_CONFIG_DIR", str(tmp_path / "cfg"))
    return make_env(tmp_path, monkeypatch)


def _rows(client):
    r = client.get("/v1/admin/settings", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    return {row["key"]: row for g in r.json()["value"]["groups"] for row in g["settings"]}


def test_get_lists_every_registry_key(env):
    rows = _rows(env.client)
    assert set(rows) == {s.key for s in settings.all_settings()}
    for row in rows.values():
        assert {"restart_required", "source", "read_only", "secret", "doc", "group", "type"} <= set(row)


def test_secret_is_write_only_and_masked(env, monkeypatch):
    monkeypatch.setenv("EDP8_PLANE_API_KEY", "plane-live-key")
    rows = _rows(env.client)
    row = rows["plane.api_key"]
    assert row["secret"] and row["value"] == "********" and row["default"] is None
    body = env.client.get("/v1/admin/settings", headers=ADMIN_H).text
    assert "plane-live-key" not in body
    monkeypatch.delenv("EDP8_PLANE_API_KEY")
    r = env.client.put("/v1/admin/settings", headers=ADMIN_H, json={"values": {"plane.api_key": "k-123"}})
    assert r.status_code == 200, r.text
    assert "k-123" not in r.text
    assert "k-123" not in (settings.config_file().read_text(encoding="utf-8") if settings.config_file().exists() else "")
    assert settings.get("EDP8_PLANE_API_KEY") == "k-123"
    assert tomllib.loads(settings.secret_settings_file().read_text(encoding="utf-8"))["plane"]["api_key"] == "k-123"
    assert "k-123" not in env.client.get("/v1/admin/settings", headers=ADMIN_H).text


def test_put_writes_config_and_names_restart(env):
    r = env.client.put("/v1/admin/settings", headers=ADMIN_H, json={"values": {"EDP_CODE_PORT": "9555"}})
    assert r.status_code == 200, r.text
    v = r.json()["value"]
    assert settings.get("EDP_CODE_PORT") == 9555
    assert tomllib.loads(settings.config_file().read_text(encoding="utf-8"))["code_server"]["port"] == 9555
    assert v["updated"][0]["source"] == "config"
    # null returns the key to its default
    r = env.client.put("/v1/admin/settings", headers=ADMIN_H, json={"values": {"EDP_CODE_PORT": None}})
    assert r.status_code == 200 and settings.source("EDP_CODE_PORT") == "default"


def test_env_set_key_refuses_put_with_reason(env, monkeypatch):
    monkeypatch.setenv("EDP_CODE_PORT", "9411")
    row = _rows(env.client)[settings.setting("EDP_CODE_PORT").key]
    assert row["read_only"] and "EDP_CODE_PORT" in row["read_only_reason"]
    r = env.client.put("/v1/admin/settings", headers=ADMIN_H, json={"values": {"EDP_CODE_PORT": "9555"}})
    assert r.status_code == 409
    assert "set by the environment variable EDP_CODE_PORT" in r.text


def test_put_is_all_or_nothing_and_validates(env, monkeypatch):
    monkeypatch.setenv("EDP_CODE_PORT", "9411")
    r = env.client.put("/v1/admin/settings", headers=ADMIN_H,
                       json={"values": {"EDP8_SLACK_MAP": "x.json", "EDP_CODE_PORT": "1"}})
    assert r.status_code == 409 and not settings.config_file().exists()
    r = env.client.put("/v1/admin/settings", headers=ADMIN_H, json={"values": {"board.port": "not-a-number"}})
    assert r.status_code == 400
    r = env.client.put("/v1/admin/settings", headers=ADMIN_H, json={"values": {"no.such": 1}})
    assert r.status_code == 404


def test_env_only_key_is_never_written(env):
    s = next(s for s in settings.all_settings() if s.env_only and settings.env_raw(s.env) is None)
    r = env.client.put("/v1/admin/settings", headers=ADMIN_H, json={"values": {s.key: "x"}})
    assert r.status_code == 409 and "environment-only" in r.text
