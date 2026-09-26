"""S5 Admin → Seat harnesses (c-3116ef3a92, second half): detection reports path and version for claude,
codex and pi (mockable); update-when-idle refuses while a seat of that harness is live and runs once none
is; a selection with neither claude nor codex is refused; a codex-less selection needs the recorded Fable
acknowledgement."""

from __future__ import annotations

import time
import tomllib

import httpx
import pytest

from admin_support import ADMIN_H, BOB_H, make_env
from edp8 import harness, pool_adapter, settings
from edp8.admin import harnesses as H
from edp8.admin import net

PATHS = {"claude": "C:/bin/claude.exe", "codex": "C:/bin/codex.cmd", "pi": "C:/bin/pi.cmd"}


class Fake:
    """find_tool / probe_version / the vendor command / the pool's sessions, all in one place."""

    def __init__(self):
        self.versions = {"claude": "2.1.0 (Claude Code)", "codex": "codex-cli 0.40.0", "pi": "0.9.1"}
        self.sessions: list[dict] = []
        self.pool_ok = True
        self.runs: list[list[str]] = []

    def find_tool(self, name, key=None):
        return {"npm": "C:/bin/npm.cmd", **PATHS}.get(name)

    def probe(self, argv, timeout=10.0):
        for h, p in PATHS.items():
            if p in argv:
                return self.versions[h]
        return None

    def run(self, argv, timeout=H.UPDATE_TIMEOUT_S):
        self.runs.append(argv)
        if argv[-1] == "update":
            self.versions["claude"] = "2.2.0 (Claude Code)"
        elif argv[-1] == "@openai/codex@latest":
            self.versions["codex"] = "codex-cli 0.41.0"
        return 0, "updated"

    def pool(self):
        return {"ok": True, "value": self.sessions} if self.pool_ok else {"ok": False, "error": "pool down"}


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(H, "find_tool", f.find_tool)
    monkeypatch.setattr(H, "probe_version", f.probe)
    monkeypatch.setattr(H, "tool_argv", lambda p: [p])
    monkeypatch.setattr(H, "_run", f.run)
    monkeypatch.setattr(H, "signed_in", lambda h: {"claude": True, "codex": False}.get(h))
    monkeypatch.setattr(pool_adapter, "sessions", f.pool)
    monkeypatch.setattr(net, "transport", httpx.MockTransport(
        lambda req: httpx.Response(200, json={"version": "9.9.9"}) if req.url.path.endswith("/latest")
        else httpx.Response(404)))
    return f


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_CONFIG_DIR", str(tmp_path / "cfg"))
    home = tmp_path / "home"
    home.mkdir()
    (home / "models.json").write_text('{"models": {"claude-opus-5-5": {"harness": "claude", "provider": "claude"}}}', encoding="utf-8")
    monkeypatch.setattr(settings, "agent_home", lambda: home)
    monkeypatch.delenv("EDP_HARNESSES", raising=False)
    return make_env(tmp_path, monkeypatch, db=str(tmp_path / "board.db"))


def test_detection_reports_path_version_signed_in_latest(env, fake):
    r = env.client.get("/v1/admin/harnesses", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    rows = {x["harness"]: x for x in r.json()["value"]["harnesses"]}
    assert set(rows) == {"claude", "codex", "pi"}
    for h in rows:
        assert rows[h]["path"] == PATHS[h] and rows[h]["version"] == fake.versions[h], h
        assert rows[h]["latest"] == "9.9.9" and rows[h]["live_seats"] == [] and rows[h]["selected"]
    assert rows["claude"]["signed_in"] is True and rows["codex"]["signed_in"] is False
    assert env.client.get("/v1/admin/harnesses", headers=BOB_H).status_code == 403


def test_detection_without_the_tool(env, fake, monkeypatch):
    monkeypatch.setattr(H, "find_tool", lambda name, key=None: None if name == "pi" else fake.find_tool(name))
    rows = {x["harness"]: x for x in env.client.get("/v1/admin/harnesses?latest=false",
                                                     headers=ADMIN_H).json()["value"]["harnesses"]}
    assert rows["pi"] == {**rows["pi"], "installed": False, "path": None, "version": None, "latest": None}


def test_update_refuses_while_a_seat_of_that_harness_is_live_then_runs(env, fake):
    fake.sessions = [{"handle": "engineer.s-1", "model": "claude-opus-5-5", "state": "active"},
                     {"handle": "adversary.e-1", "model": "gpt-5.5", "state": "parked"}]
    r = env.client.post("/v1/admin/harnesses/claude/update", headers=ADMIN_H)
    assert r.status_code == 409 and "engineer.s-1" in r.text
    assert fake.runs == []
    # a codex seat parked, not live: codex updates now through npm
    r = env.client.post("/v1/admin/harnesses/codex/update", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    assert fake.runs[-1] == ["C:/bin/npm.cmd", "install", "-g", "@openai/codex@latest"]
    v = r.json()["value"]
    assert v["state"] == "done" and v["before"] == "codex-cli 0.40.0" and v["after"] == "codex-cli 0.41.0"
    # the claude seat ends: claude updates with the vendor's own command
    fake.sessions = []
    r = env.client.post("/v1/admin/harnesses/claude/update", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    assert fake.runs[-1] == ["C:/bin/claude.exe", "update"]
    assert r.json()["value"]["after"] == "2.2.0 (Claude Code)"
    rows = {x["harness"]: x for x in env.client.get("/v1/admin/harnesses?latest=false",
                                                     headers=ADMIN_H).json()["value"]["harnesses"]}
    assert rows["claude"]["update"]["state"] == "done" and rows["claude"]["version"] == "2.2.0 (Claude Code)"


def test_update_refuses_when_the_pool_cannot_say(env, fake):
    fake.pool_ok = False
    r = env.client.post("/v1/admin/harnesses/pi/update", headers=ADMIN_H)
    assert r.status_code == 409 and "pool cannot say" in r.text and fake.runs == []


def test_update_wait_mode_runs_once_the_seats_are_gone(env, fake, monkeypatch):
    monkeypatch.setattr(H, "WAIT_POLL_S", 0.05)
    fake.sessions = [{"handle": "engineer.s-1", "model": "claude-opus-5-5", "state": "active"}]
    r = env.client.post("/v1/admin/harnesses/claude/update", headers=ADMIN_H, json={"wait": True})
    assert r.status_code == 200 and r.json()["value"]["state"] == "waiting"
    assert env.client.post("/v1/admin/harnesses/claude/update", headers=ADMIN_H).status_code == 409  # already waiting
    time.sleep(0.3)
    assert fake.runs == []
    fake.sessions = []
    deadline = time.time() + 5
    while time.time() < deadline and not fake.runs:
        time.sleep(0.05)
    assert fake.runs == [["C:/bin/claude.exe", "update"]]


def test_update_unknown_or_missing_harness(env, fake, monkeypatch):
    assert env.client.post("/v1/admin/harnesses/gemini/update", headers=ADMIN_H).status_code == 404
    monkeypatch.setattr(H, "find_tool", lambda name, key=None: None)
    assert env.client.post("/v1/admin/harnesses/pi/update", headers=ADMIN_H).status_code == 409


def _cfg():
    f = settings.config_file()
    return tomllib.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def test_selection_needs_claude_or_codex(env, fake):
    r = env.client.put("/v1/admin/harnesses/selection", headers=ADMIN_H, json={"harnesses": ["pi"]})
    assert r.status_code == 409 and "at least one of claude and codex" in r.text
    assert "seats" not in _cfg()
    assert env.client.put("/v1/admin/harnesses/selection", headers=ADMIN_H,
                          json={"harnesses": ["claude", "gemini"]}).status_code == 400


def test_codexless_selection_needs_the_fable_ack(env, fake):
    ack = harness.ack_path(env.board.store.path)
    r = env.client.put("/v1/admin/harnesses/selection", headers=ADMIN_H, json={"harnesses": ["claude", "pi"]})
    assert r.status_code == 409 and "Fable" in r.text
    assert "seats" not in _cfg() and not ack.exists()
    r = env.client.put("/v1/admin/harnesses/selection", headers=ADMIN_H,
                       json={"harnesses": ["claude", "pi"], "fable_ack": True})
    assert r.status_code == 200, r.text
    assert harness.read_ack(ack)["by"] == "owner"
    assert _cfg()["seats"]["harnesses"] == ["claude", "pi"]
    v = env.client.get("/v1/admin/harnesses", headers=ADMIN_H).json()["value"]
    assert v["selected"] == ["claude", "pi"] and v["fable_ack"]["by"] == "owner" and v["fable_notice"]
    # the recorded acknowledgement stands: a later codex-less selection needs no second one
    r = env.client.put("/v1/admin/harnesses/selection", headers=ADMIN_H, json={"harnesses": ["claude"]})
    assert r.status_code == 200 and _cfg()["seats"]["harnesses"] == ["claude"]
    # a selection with codex needs none at all
    r = env.client.put("/v1/admin/harnesses/selection", headers=ADMIN_H, json={"harnesses": ["codex", "claude"]})
    assert r.status_code == 200 and _cfg()["seats"]["harnesses"] == ["claude", "codex"]


def test_selection_refuses_env_set_but_ignores_models_json_selection(env, fake, monkeypatch):
    monkeypatch.setenv("EDP_HARNESSES", "claude,codex")
    r = env.client.put("/v1/admin/harnesses/selection", headers=ADMIN_H, json={"harnesses": ["claude"]})
    assert r.status_code == 409 and "environment" in r.text
    monkeypatch.delenv("EDP_HARNESSES")
    (settings.agent_home() / "models.json").write_text('{"harnesses": ["claude", "codex"]}', encoding="utf-8")
    r = env.client.put("/v1/admin/harnesses/selection", headers=ADMIN_H, json={"harnesses": ["claude"]})
    assert r.status_code == 409 and "risk acknowledgement" in r.text
