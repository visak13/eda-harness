"""W12 — pool-side spawn defaults, and the toggle that must never exist.

DESIGN-v6 §W12 lists `EDP_SKIP_PERMISSIONS` among the panel's spawn-config
toggles. THAT LINE IS OVERRULED by a standing user constraint: he deliberately
set up manual permissions and will not dangerously-skip. It is not gated, not
confirmed, not rendered-and-disabled — it is ABSENT, and the pool REFUSES the
key rather than accepting and ignoring it. Accepting-and-ignoring is how a
caller learns a dangerous switch "works".
"""

import json

import pytest
from fastapi.testclient import TestClient

from edp_pool import pty_launcher as pl
from edp_pool.service import create_app
from edp_pool.spawn_defaults import (
    ALLOWED_KEYS,
    BANNED_KEYS,
    BannedSpawnDefault,
    load_spawn_defaults,
    save_spawn_defaults,
)
from edp_pool.spawner import FakeSpawner


@pytest.fixture
def defaults_file(tmp_path, monkeypatch):
    p = tmp_path / "spawn_defaults.json"
    monkeypatch.setenv("EDP_SPAWN_DEFAULTS", str(p))
    return p


@pytest.fixture
def client(tmp_path, monkeypatch, defaults_file):
    monkeypatch.setenv("EDP_POOL_HOST", "127.0.0.1")
    app = create_app(FakeSpawner(), broker_url="http://b:9300",
                     state_path=tmp_path / "state.json")
    return TestClient(app, base_url="http://127.0.0.1:9301")


# ── the switch that is not there ──────────────────────────────────────────

def test_skip_permissions_is_not_a_settable_key():
    assert "skip_permissions" not in ALLOWED_KEYS
    assert not any("permission" in k for k in ALLOWED_KEYS)
    assert "EDP_SKIP_PERMISSIONS" in BANNED_KEYS


@pytest.mark.parametrize("key", sorted(BANNED_KEYS))
def test_saving_a_banned_key_is_refused_loudly_not_dropped_silently(
        key, defaults_file):
    with pytest.raises(BannedSpawnDefault) as e:
        save_spawn_defaults({key: True})
    assert "manual permissions" in str(e.value)
    assert not defaults_file.exists(), "a refused write must write nothing"


def test_no_browser_post_can_reach_the_switch(client, defaults_file):
    r = client.post("/v1/panel/spawn_defaults",
                    json={"model": "claude-sonnet-5", "skip_permissions": True})
    assert r.status_code == 400
    assert "manual permissions" in r.json()["refused"]
    assert not defaults_file.exists()


def test_an_unknown_key_is_dropped_rather_than_persisted(defaults_file):
    written = save_spawn_defaults({"model": "m", "nonsense": 1})
    assert written == {"model": "m"}
    assert json.loads(defaults_file.read_text(encoding="utf-8")) == {"model": "m"}


# ── the keys that ARE settable ────────────────────────────────────────────

def test_roundtrip_through_the_panel(client, defaults_file):
    r = client.post("/v1/panel/spawn_defaults",
                    json={"model": "claude-sonnet-5", "spawn_mode": "monitor",
                          "rtk": True})
    assert r.status_code == 200
    assert r.json()["applies_to"] == "fresh spawns only"
    assert client.get("/v1/panel/spawn_defaults").json()["defaults"] == {
        "model": "claude-sonnet-5", "spawn_mode": "monitor", "rtk": True}


def test_a_bad_spawn_mode_is_refused(defaults_file):
    with pytest.raises(BannedSpawnDefault):
        save_spawn_defaults({"spawn_mode": "chaos"})


def test_absent_or_corrupt_file_degrades_to_no_defaults(defaults_file):
    assert load_spawn_defaults() == {}
    defaults_file.write_text("{ not json", encoding="utf-8")
    assert load_spawn_defaults() == {}, (
        "a corrupt config must never fail a spawn")


# ── the seam: build_argv / build_env read it ──────────────────────────────

def test_build_argv_takes_model_from_defaults(defaults_file):
    assert pl.build_argv("c.exe", extra=[], defaults={}) == ["c.exe"]
    assert pl.build_argv("c.exe", extra=[], defaults={"model": "claude-sonnet-5"}) \
        == ["c.exe", "--model", "claude-sonnet-5"]


def test_an_explicit_model_beats_the_panel_default(defaults_file):
    """The caller knows something the panel does not — a per-action tier is an
    intentional override, not a fallback."""
    argv = pl.build_argv("c.exe", extra=[], model="claude-opus-4-8",
                         defaults={"model": "claude-sonnet-5"})
    assert argv == ["c.exe", "--model", "claude-opus-4-8"]


def test_build_argv_reads_the_file_when_no_defaults_are_passed(defaults_file):
    save_spawn_defaults({"model": "claude-sonnet-5"})
    assert pl.build_argv("c.exe", extra=[]) == [
        "c.exe", "--model", "claude-sonnet-5"]


def test_build_argv_still_emits_nothing_when_there_is_no_file(defaults_file):
    """Byte-identical to pre-W12 argv when nothing is configured."""
    assert pl.build_argv("c.exe", extra=["--x"]) == ["c.exe", "--x"]


def test_spawn_defaults_never_add_skip_permissions_to_argv(defaults_file):
    save_spawn_defaults({"model": "m", "spawn_mode": "monitor", "rtk": True})
    argv = pl.build_argv("c.exe", extra=[])
    assert "--dangerously-skip-permissions" not in argv


def test_build_env_rtk_default_overrides_the_ambient_env(defaults_file, monkeypatch):
    """A panel toggle that an inherited `EDP_RTK=0` silently overrode would be
    a lie in the UI."""
    monkeypatch.setenv("EDP_RTK", "0")
    env = pl.build_env("s", "worker", "p:a", "http://b", defaults={"rtk": True})
    assert env["EDP_RTK"] == "1"

    monkeypatch.setenv("EDP_RTK", "1")
    env = pl.build_env("s", "worker", "p:a", "http://b", defaults={"rtk": False})
    assert "EDP_RTK" not in env


def test_build_env_falls_back_to_the_env_when_the_file_is_silent(
        defaults_file, monkeypatch):
    monkeypatch.setenv("EDP_RTK", "1")
    assert pl.build_env("s", "worker", "p:a", "http://b",
                        defaults={})["EDP_RTK"] == "1"
    monkeypatch.delenv("EDP_RTK", raising=False)
    assert "EDP_RTK" not in pl.build_env("s", "worker", "p:a", "http://b",
                                         defaults={})


def test_spawn_mode_precedence_body_beats_defaults_beats_env(
        client, defaults_file, monkeypatch):
    monkeypatch.setenv("EDP_SPAWN_MODE", "headless")
    save_spawn_defaults({"spawn_mode": "monitor"})
    svc = client.app.state.svc

    client.post("/v1/spawn", json={"role": "worker", "handle": "p:a1"})
    assert svc.sessions[svc.locks["p:a1"]]["mode"] == "monitor"  # file > env

    client.post("/v1/spawn",
                json={"role": "worker", "handle": "p:a2", "mode": "headless"})
    assert svc.sessions[svc.locks["p:a2"]]["mode"] == "headless"  # body > file
