"""S1 seam: the Vite SPA served by FastAPI under `/app` with an immutable asset cache,
a no-store SPA fallback, and a 503 "not built" page when the bundle is absent — while the
legacy `/ui` and every `/v1` route are unaffected (design §4.1, §4.4a; criterion
c-35447ca142). Cases 1–3 require the built bundle (`npm --prefix web run build`); case 4
proves create_app() still boots with no bundle."""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edp8 import broker_adapter
from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store
from edp8.webapp import DIST_DIR, mount_spa

ADMIN = {"X-Admin": "t"}
H = {"X-Participant": "owner"}
DIST_BUILT = (DIST_DIR / "index.html").is_file()
needs_build = pytest.mark.skipif(not DIST_BUILT, reason="run `npm --prefix web run build` first (dist/ absent)")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: True)
    board = Board(Store(":memory:"))
    c = TestClient(create_app(board, admin_token="t"))
    assert c.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner", "id": "owner"},
                  headers=ADMIN).json()["ok"]
    return c


@needs_build
def test_app_prefix_serves_index_html_no_store(client):
    r = client.get("/app/anything", params={"as": "owner"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers.get("cache-control") == "no-store"
    assert '<div id="root">' in r.text and "/app/assets/" in r.text


@needs_build
def test_app_assets_are_immutably_cached(client):
    index = client.get("/app/", params={"as": "owner"}).text
    m = re.search(r"/app/assets/([^\"']+)", index)
    assert m, "built index.html should reference a fingerprinted /app/assets/* file"
    a = client.get("/app/assets/" + m.group(1))
    assert a.status_code == 200
    assert a.headers.get("cache-control") == "public, max-age=31536000, immutable"


def test_legacy_ui_poll_still_returns_json(client):
    r = client.get("/ui/poll", params={"since": 0, "scope": "all"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert "seq" in r.json()


def test_v1_routes_unaffected_by_spa_mount(client):
    r = client.get("/v1/whoami", headers=H)
    assert r.status_code == 200 and r.json()["ok"]


def test_missing_dist_yields_503_not_built_and_app_still_boots(tmp_path: Path):
    # No index.html under the given dist → mount installs the 503 fallback, create_app()
    # equivalent (a bare FastAPI here) still constructs without raising (architect ruling
    # m-f0a5330767: service-unavailable, not a boot failure).
    app = FastAPI()
    served = mount_spa(app, "/app", dist=tmp_path / "dist")
    assert served is False
    c = TestClient(app)
    r = c.get("/app/x")
    assert r.status_code == 503
    assert "web app not built" in r.text.lower()
    assert "npm --prefix web" in r.text  # the build command is named


def test_real_create_app_boots_even_if_bundle_absent(monkeypatch, tmp_path):
    # Point the default dist somewhere empty and prove create_app() itself does not raise.
    monkeypatch.setattr("edp8.webapp.serve.DIST_DIR", tmp_path / "nope")
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: True)
    app = create_app(Board(Store(":memory:")), admin_token="t")
    c = TestClient(app)
    assert c.get("/app/x").status_code == 503
    assert c.get("/healthz").json()["ok"] is True
