"""S10 Admin → Cut release: owner-only, dispatches release.yml with the right inputs through one seam, never
echoes the token, records an audit row. No network: the dispatch seam is replaced."""

from __future__ import annotations

import json

import pytest

from admin_support import ADMIN_H, BOB_H, make_env
from edp8.admin import release

TOKEN = "ghp_SECRETvalue0123456789"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("EDP_RELEASE_TOKEN", TOKEN)
    monkeypatch.setenv("EDP_UPDATE_REPO", "acme/fork")
    e = make_env(tmp_path, monkeypatch)
    bob = e.board.participant("bob")
    e.board.store.put("participant", bob.model_copy(update={"admin": True}))  # an admin, but not the owner
    return e


@pytest.fixture
def calls(monkeypatch):
    seen: list[tuple] = []

    def fake(repo, ref, inputs, token):
        seen.append((repo, ref, inputs, token))
        return 204, ""

    monkeypatch.setattr(release, "dispatch", fake)
    return seen


def test_get_says_who_can_cut_and_why_not(env, monkeypatch):
    v = env.client.get("/v1/admin/release", headers=ADMIN_H).json()["value"]
    assert v["can_cut"] is True and v["repo"] == "acme/fork" and v["default_ref"] == "main" and v["token_set"] is True
    assert TOKEN not in json.dumps(v)
    bob = env.client.get("/v1/admin/release", headers=BOB_H).json()["value"]
    assert bob["can_cut"] is False and "only the owner" in bob["reason"]
    monkeypatch.setenv("EDP_RELEASE_TOKEN", "")
    v = env.client.get("/v1/admin/release", headers=ADMIN_H).json()["value"]
    assert v["can_cut"] is False and v["token_set"] is False and "Release token" in v["reason"]


def test_an_admin_who_is_not_the_owner_is_refused_and_nothing_is_dispatched(env, calls):
    r = env.client.post("/v1/admin/release/cut", headers=BOB_H, json={"version": "0.10.0"})
    assert r.status_code == 403 and "only the owner" in r.text
    assert calls == []


def test_a_malformed_version_is_refused(env, calls):
    for bad in ("0.10", "latest", "v0.10.0-rc1", "", "0.10.0; rm"):
        r = env.client.post("/v1/admin/release/cut", headers=ADMIN_H, json={"version": bad})
        assert r.status_code == 422, (bad, r.text)
    assert calls == []


def test_without_a_token_nothing_is_dispatched(env, calls, monkeypatch):
    monkeypatch.setenv("EDP_RELEASE_TOKEN", "")
    r = env.client.post("/v1/admin/release/cut", headers=ADMIN_H, json={"version": "0.10.0"})
    assert r.status_code == 403 and "Release token" in r.text and calls == []


def test_the_default_is_a_dry_run_that_publishes_nothing(env, calls):
    r = env.client.post("/v1/admin/release/cut", headers=ADMIN_H, json={"version": "0.10.0"})
    assert r.status_code == 202, r.text
    assert calls == [("acme/fork", "main", {"tag": "v0.10.0", "dry_run": "true", "publish": "false"}, TOKEN)]
    v = r.json()["value"]
    assert v["runs_url"] == "https://github.com/acme/fork/actions/workflows/release.yml" and v["by"] == "owner"
    assert TOKEN not in r.text and "validates only" in r.json()["hint"]


def test_publish_is_ignored_while_dry_run_is_on_and_sent_when_it_is_off(env, calls):
    env.client.post("/v1/admin/release/cut", headers=ADMIN_H, json={"version": "v0.10.0", "publish": True})
    assert calls[-1][2] == {"tag": "v0.10.0", "dry_run": "true", "publish": "false"}
    r = env.client.post("/v1/admin/release/cut", headers=ADMIN_H,
                        json={"version": "0.10.0", "dry_run": False, "publish": True})
    assert r.status_code == 202 and calls[-1][2] == {"tag": "v0.10.0", "dry_run": "false", "publish": "true"}
    assert "then publishing" in r.json()["hint"]


def test_every_cut_is_audited_without_the_token(env, calls, tmp_path):
    env.client.post("/v1/admin/release/cut", headers=ADMIN_H, json={"version": "0.10.0"})
    text = (tmp_path / "data" / "release-cuts.jsonl").read_text(encoding="utf-8")
    row = json.loads(text.splitlines()[-1])
    assert row["by"] == "owner" and row["tag"] == "v0.10.0" and row["dry_run"] == "true" and row["status"] == 204
    assert TOKEN not in text
    assert env.client.get("/v1/admin/release", headers=ADMIN_H).json()["value"]["last"]["tag"] == "v0.10.0"


def test_a_github_refusal_is_reported_without_the_token(env, monkeypatch):
    monkeypatch.setattr(release, "dispatch", lambda *a: (422, f"Workflow does not have workflow_dispatch; sent {TOKEN}"))
    r = env.client.post("/v1/admin/release/cut", headers=ADMIN_H, json={"version": "0.10.0"})
    assert r.status_code == 502 and "422" in r.text and TOKEN not in r.text


def test_a_transport_error_is_reported_without_the_token(env, monkeypatch):
    def boom(*a):
        raise OSError(f"connect failed for Bearer {TOKEN}")

    monkeypatch.setattr(release, "dispatch", boom)
    r = env.client.post("/v1/admin/release/cut", headers=ADMIN_H, json={"version": "0.10.0"})
    assert r.status_code == 502 and TOKEN not in r.text and "could not reach GitHub" in r.text


def test_the_real_dispatch_posts_the_documented_request(env, monkeypatch):
    import httpx

    from edp8.admin import net
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(url=str(req.url), auth=req.headers["authorization"], body=json.loads(req.content))
        return httpx.Response(204)

    monkeypatch.setattr(net, "transport", httpx.MockTransport(handler))
    assert release.dispatch("acme/fork", "main", {"tag": "v1.2.3"}, "tok") == (204, "")
    assert seen == {"url": "https://api.github.com/repos/acme/fork/actions/workflows/release.yml/dispatches",
                    "auth": "Bearer tok", "body": {"ref": "main", "inputs": {"tag": "v1.2.3"}}}
