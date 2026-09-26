"""S5 Admin → Updates, in process: the Releases check against a fixture reports available / up to date,
and apply refuses up front what `heronry update` would refuse (the live apply is in
test_admin_services_live)."""

from __future__ import annotations

import httpx
import pytest

from admin_support import ADMIN_H, BOB_H, make_env
from edp8 import control, updater


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch)


def _api(monkeypatch, tag: str):
    seen = []

    def get(url, *, timeout=30.0, headers=None):
        seen.append(url)
        return httpx.Response(200, json={"tag_name": tag, "html_url": "https://example.invalid/r"},
                              headers={"ETag": '"e1"'}, request=httpx.Request("GET", url))

    monkeypatch.setattr(updater, "_get", get)
    monkeypatch.setenv("EDP_UPDATE_API", "https://api.mock")
    monkeypatch.setattr(updater, "current_version", lambda: "1.2.0")
    return seen


def test_check_reports_available_from_the_fixture(env, monkeypatch):
    seen = _api(monkeypatch, "v1.3.0")
    v = env.client.get("/v1/admin/updates?force=true", headers=ADMIN_H).json()["value"]
    assert v["current"] == "1.2.0" and v["latest"] == "1.3.0" and v["available"] is True
    assert seen[0].startswith("https://api.mock/repos/") and seen[0].endswith("/releases/latest")
    assert env.client.get("/v1/admin/updates", headers=BOB_H).status_code == 403


def test_check_up_to_date(env, monkeypatch):
    _api(monkeypatch, "v1.2.0")
    v = env.client.get("/v1/admin/updates?force=true", headers=ADMIN_H).json()["value"]
    assert v["available"] is False and v["latest"] == "1.2.0"


def test_apply_refuses_a_dev_checkout(env, monkeypatch):
    monkeypatch.setenv("EDP_DEV", "1")
    r = env.client.post("/v1/admin/updates/apply", headers=ADMIN_H)
    assert r.status_code == 409 and "dev mode" in r.text


def test_apply_needs_the_supervisor(env, monkeypatch):
    monkeypatch.delenv("EDP_DEV", raising=False)
    monkeypatch.setenv("EDP_UPDATE_INSTALL_CMD", '["true"]')

    def unavailable(*a, **kw):
        raise control.ControlUnavailable("no supervisor")

    monkeypatch.setattr(control, "request", unavailable)
    r = env.client.post("/v1/admin/updates/apply", headers=ADMIN_H)
    assert r.status_code == 503 and "supervisor" in r.text
