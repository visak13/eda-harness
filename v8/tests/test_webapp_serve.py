"""S1 seam: the Vite SPA served by FastAPI with an immutable asset cache, a no-store SPA
fallback, and a 503 "not built" page when the bundle is absent — while the legacy renderer
and every `/v1` route are unaffected (design §4.1, §4.4a; criterion c-35447ca142).

The cutover (S12) fixed the built base at `/ui/` (vite base 8680dbc), so the SPA only serves
correctly at the prefix it was built for — `/ui` under the shipping folio default. The two
built-bundle cases therefore run in folio mode and assert `/ui/assets/`; the mount mechanics
(503 fallback, mount_spa returns) stay prefix-agnostic. Case 4 proves create_app() still
boots with no bundle."""

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


@pytest.fixture
def folio_client(monkeypatch):
    # The dist is built with vite base /ui/, so it serves correctly only where the mount prefix
    # matches — /ui under folio. Pin folio here (overriding the autouse ui_prefix fixture) so the
    # SPA the built bundle asserts against is the one create_app actually serves.
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: True)
    monkeypatch.setenv("EDP8_UI", "folio")
    board = Board(Store(":memory:"))
    c = TestClient(create_app(board, admin_token="t"))
    assert c.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner", "id": "owner"},
                  headers=ADMIN).json()["ok"]
    return c


@needs_build
def test_app_prefix_serves_index_html_no_store(folio_client):
    r = folio_client.get("/ui/anything", params={"as": "owner"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers.get("cache-control") == "no-store"
    assert '<div id="root">' in r.text and "/ui/assets/" in r.text


@needs_build
def test_app_assets_are_immutably_cached(folio_client):
    index = folio_client.get("/ui/", params={"as": "owner"}).text
    m = re.search(r"/ui/assets/([^\"']+)", index)
    assert m, "built index.html should reference a fingerprinted /ui/assets/* file"
    a = folio_client.get("/ui/assets/" + m.group(1))
    assert a.status_code == 200
    assert a.headers.get("cache-control") == "public, max-age=31536000, immutable"


def test_public_files_serve_as_themselves_not_the_index(tmp_path: Path):
    # Owner m-20ec2c5207: /ui/brand/favicon.ico returned the HTML fallback, so no favicon or rail
    # logo. Every file Vite copies from web/public is served as itself; a traversal never escapes dist.
    dist = tmp_path / "dist"
    (dist / "brand").mkdir(parents=True)
    (dist / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    (dist / "brand" / "favicon-32.png").write_bytes(b"\x89PNG\r\n\x1a\nxx")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    app = FastAPI()
    assert mount_spa(app, "/ui", dist=dist)
    c = TestClient(app)
    r = c.get("/ui/brand/favicon-32.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")
    assert c.get("/ui/ticket/s-1").headers["content-type"].startswith("text/html")
    assert "nope" not in c.get("/ui/..%2Fsecret.txt").text


@needs_build
def test_built_bundle_ships_brand_icons(folio_client):
    for p in ("favicon.ico", "favicon-32.png", "apple-touch-icon.png", "heronry-64.png"):
        r = folio_client.get("/ui/brand/" + p)
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/"), p


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
    # Under folio the SPA owns /ui; point the default dist somewhere empty and prove create_app()
    # itself does not raise — /ui serves the 503 not-built page instead of failing construction.
    monkeypatch.setenv("EDP8_UI", "folio")
    monkeypatch.setattr("edp8.webapp.serve.DIST_DIR", tmp_path / "nope")
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: True)
    app = create_app(Board(Store(":memory:")), admin_token="t")
    c = TestClient(app)
    assert c.get("/ui/x").status_code == 503
    assert c.get("/healthz").json()["ok"] is True


def test_board_serves_the_private_dist_named_by_edp8_web_dist(monkeypatch, tmp_path):
    """t-b2f8859d30: an e2e board serves its private build (EDP8_WEB_DIST), never the shared packaged dist, so a
    seat's e2e build can't ship to the fleet board."""
    private = tmp_path / "e2e-dist"
    (private / "assets").mkdir(parents=True)
    (private / "index.html").write_text("<!doctype html><title>private-e2e-bundle</title>", encoding="utf-8")
    (private / "assets" / "app-abc.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("EDP8_UI", "folio")
    monkeypatch.setenv("EDP8_WEB_DIST", str(private))
    monkeypatch.setattr("edp8.webapp.serve.DIST_DIR", tmp_path / "shared-must-not-serve")
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: True)
    c = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
    assert "private-e2e-bundle" in c.get("/ui/design").text
    assert c.get("/ui/assets/app-abc.js").status_code == 200


def test_repeated_leading_slashes_redirect_to_the_single_slash_path(client):
    """t-67dad8c6aa: `//ui/library/topics/<id>` (typed by hand) was a bare 404; it now redirects to `/ui/…`,
    query kept, and never to a protocol-relative `//host` Location."""
    r = client.get("http://testserver//ui/library/topics/topic-x?tab=thread", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/ui/library/topics/topic-x?tab=thread"
    r = client.get("http://testserver///evil.example/ui", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/evil.example/ui"
    assert client.get("http://testserver//v1/whoami", headers=H, follow_redirects=True).status_code == 200
    assert client.post("http://testserver//v1/whoami", headers=H, follow_redirects=False).status_code != 308  # GET/HEAD only
