"""Cutover switch: EDP8_UI=folio|legacy (design §4.1 Transition, S12; criteria c-a8c1be7137,
c-e36e437482).

Proves both mappings on one board, parametrised by mode, WITHOUT deleting the legacy renderer:
  folio  (default) — SPA at /ui, legacy renderer reachable at /ui-legacy/*, /ui/poll fixed
  legacy           — legacy renderer at /ui, SPA at /app, /ui/poll fixed
and that /ui/poll answers identically under both, plus the missing-build 503 under folio.

The rich legacy-renderer characterisation lives in test_ui_live / test_views (pinned to
EDP8_UI=legacy so their golden masters never move); this file is the parity proof across the
switch. Set EDP8_TEST_UI_PREFIX=/ui-legacy to run the legacy-page smoke against folio's mount.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter
from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store
from edp8.webapp import serve

ADMIN = {"X-Admin": "t"}
OWN = {"X-Participant": "owner"}


def _app(monkeypatch, mode: str) -> TestClient:
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    monkeypatch.setenv("EDP8_UI", mode)
    c = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))

    def post(path, json, headers):
        r = c.post(path, json=json, headers=headers).json()
        assert r["ok"], r
        return r["value"]

    post("/v1/participants", {"type": "human", "role": "owner", "handle": "owner", "id": "owner"}, ADMIN)
    epic = post("/v1/tickets", {"kind": "epic", "work_type": "feature", "title": "Cutover epic"}, OWN)["id"]
    c.epic = epic  # type: ignore[attr-defined]
    return c


def test_folio_serves_spa_at_ui_and_legacy_at_ui_legacy(monkeypatch):
    c = _app(monkeypatch, "folio")
    # SPA owns /ui (a built dist serves index.html; a missing one 503s — both are the SPA, not legacy).
    spa = c.get("/ui")
    assert spa.status_code in (200, 503)
    assert "app-shell" not in spa.text or "<div id=" in spa.text  # not the legacy server-rendered shell
    # Legacy renderer is retained and reachable at /ui-legacy/*.
    me = c.get("/ui-legacy/me", params={"as": "owner"})
    assert me.status_code == 200
    assert "id='page-body'" in me.text and c.epic  # legacy server-rendered HTML
    # A stale legacy path under /ui is now the SPA catch-all (client router redirects it), not a 404 stack.
    assert c.get("/ui/me", params={"as": "owner"}).status_code in (200, 503)


def test_legacy_mode_restores_previous_mapping(monkeypatch):
    c = _app(monkeypatch, "legacy")
    me = c.get("/ui/me", params={"as": "owner"})
    assert me.status_code == 200 and "id='page-body'" in me.text  # legacy renderer back at /ui
    assert c.get("/app").status_code in (200, 503)  # SPA at /app
    # /ui-legacy is NOT mounted in legacy mode.
    assert c.get("/ui-legacy/me", params={"as": "owner"}).status_code == 404


@pytest.mark.parametrize("mode", ["folio", "legacy"])
def test_poll_is_fixed_at_ui_poll_under_both_modes(monkeypatch, mode):
    c = _app(monkeypatch, mode)
    r = c.get("/ui/poll", params={"since": 0, "scope": "all"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"seq", "new"} and isinstance(body["seq"], int)


def test_missing_build_under_folio_returns_503_naming_the_command(monkeypatch, tmp_path):
    monkeypatch.setattr(serve, "DIST_DIR", tmp_path / "does-not-exist")
    c = _app(monkeypatch, "folio")
    r = c.get("/ui")
    assert r.status_code == 503
    assert "web app not built" in r.text
    assert "npm --prefix web" in r.text  # names the build command, not a stack trace


def test_legacy_pages_answer_at_the_test_prefix(monkeypatch):
    """c-a8c1be7137 'parametrised by prefix': EDP8_TEST_UI_PREFIX picks which mount the legacy
    smoke runs against — /ui (legacy mode, default) or /ui-legacy (folio mode)."""
    prefix = os.environ.get("EDP8_TEST_UI_PREFIX", "/ui")
    mode = "legacy" if prefix == "/ui" else "folio"
    c = _app(monkeypatch, mode)
    for path in ("/me", "/tickets", ""):
        r = c.get(prefix + path, params={"as": "owner"})
        assert r.status_code == 200, (prefix + path, r.status_code)
        assert "id='page-body'" in r.text
    # /ui/poll stays fixed regardless of the legacy mount prefix.
    assert c.get("/ui/poll", params={"since": 0, "scope": "all"}).status_code == 200
