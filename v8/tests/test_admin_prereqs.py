"""t-08612be1b0: the setup wizard's "Your tools" API reads the one manifest; Install runs the one install step."""

from __future__ import annotations

import sys

from admin_support import ADMIN_H, BOB_H, make_env
from edp_contracts import prereqs as pq
from edp8.admin import prereqs_api

PRESENT = {"uv", "node", "codex", "winget", "npm"}  # git and claude missing


def _fake_machine(monkeypatch, present):
    def which(p):
        name = p.command or p.name
        return f"C:/fake/{name}.exe" if name in present else None

    monkeypatch.setattr(pq, "_which", which)
    monkeypatch.setattr(pq, "_probe", lambda argv: {"node": "v22.1.0", "uv": "uv 0.9.11", "git": "git version 2.47.0",
                                                    "codex": "codex-cli 0.46.0"}.get(
        argv[0].rsplit("/", 1)[-1].removesuffix(".exe")))
    monkeypatch.setattr(pq, "this_os", lambda: "win32")
    monkeypatch.setattr(pq, "refresh_path", lambda: None)
    monkeypatch.setattr("edp8.admin.harnesses.signed_in", lambda h: h == "codex")


def test_checklist_rows_and_admin_only(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    _fake_machine(monkeypatch, set(PRESENT))
    assert env.client.get("/v1/admin/setup/prereqs", headers=BOB_H).status_code == 403
    v = env.client.get("/v1/admin/setup/prereqs", headers=ADMIN_H).json()["value"]
    rows = {r["name"]: r for r in v["rows"]}
    assert set(rows) == {p.name for p in pq.MANIFEST}
    assert rows["git"]["state"] == "missing" and rows["git"]["installable"] and "Git.Git" in rows["git"]["fix"]
    assert rows["node"]["state"] == "ok" and rows["node"]["version"] == "v22.1.0"
    assert rows["tailscale"]["state"] == "off" and rows["tailscale"]["feature"]
    assert rows["codex"]["signed_in"] is True and rows["codex"]["login"] == "codex login"
    assert rows["claude"]["signed_in"] is None and "CLAUDE_CONFIG_DIR" in rows["claude"]["login"]
    assert v["harness_ok"] is True
    assert v["not_needed"][0]["name"] == "docker"


def test_install_runs_the_one_step_and_reports(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    present = set(PRESENT)
    _fake_machine(monkeypatch, present)
    ran = []

    def run(argv):
        ran.append(argv)
        present.add(argv[argv.index("--only") + 1])
        return 0, "installed git"

    monkeypatch.setattr(prereqs_api, "_run", run)
    real_start = prereqs_api.Jobs.start
    monkeypatch.setattr(prereqs_api.Jobs, "start", lambda self, n, by: real_start(self, n, by, background=False))
    assert env.client.post("/v1/admin/setup/prereqs/git/install", headers=BOB_H).status_code == 403
    r = env.client.post("/v1/admin/setup/prereqs/git/install", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    assert ran == [[sys.executable, "-m", "edp8.cli", "prereqs", "install", "--only", "git", "--yes"]]
    v = env.client.get("/v1/admin/setup/prereqs", headers=ADMIN_H).json()["value"]
    git = next(x for x in v["rows"] if x["name"] == "git")
    assert git["state"] == "ok" and git["job"]["state"] == "done"
    # already there, unknown, or no recipe on this machine: refused
    assert env.client.post("/v1/admin/setup/prereqs/git/install", headers=ADMIN_H).status_code == 409
    assert env.client.post("/v1/admin/setup/prereqs/docker/install", headers=ADMIN_H).status_code == 404
    present.discard("winget")
    r = env.client.post("/v1/admin/setup/prereqs/tailscale/install", headers=ADMIN_H)
    assert r.status_code == 409 and "tailscale.com/download" in r.json()["error"]["message"]


def test_failed_install_shows_its_output(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    _fake_machine(monkeypatch, set(PRESENT))
    monkeypatch.setattr(prereqs_api, "_run", lambda argv: (1, "winget: no network"))
    real_start = prereqs_api.Jobs.start
    monkeypatch.setattr(prereqs_api.Jobs, "start", lambda self, n, by: real_start(self, n, by, background=False))
    env.client.post("/v1/admin/setup/prereqs/git/install", headers=ADMIN_H)
    v = env.client.get("/v1/admin/setup/prereqs", headers=ADMIN_H).json()["value"]
    job = next(x for x in v["rows"] if x["name"] == "git")["job"]
    assert job["state"] == "failed" and job["exit"] == 1 and "no network" in job["output"]
