"""S3 (s-870e401942): `heronry update` against a local fake-release fixture.

The release is a folder of wheels plus SHA256SUMS. Two seams are injected through their declared
env-only settings (architect m-3ab493d55b: "the test injects a fake"): EDP_UPDATE_COMPAT_CMD stands in
for the new release's `heronry workflows check`, EDP_UPDATE_INSTALL_CMD for `uv tool install --force`
(it records its argv). Everything else is real: the SHA256 check, the DB backup, the stop, the detached
helper outside the venv, the start, the health probe and the rollback. The real `uv tool install`
upgrade is the story's installed-wheel evidence run.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

import httpx
import pytest
import test_cli_launcher as base
from test_cli_launcher import ROOT, V8, _venv_py, cli

inst = base.inst  # the shared private-instance fixture

NEEDS_VENVS = pytest.mark.skipif(not _venv_py(ROOT / "edp-pool").is_file() or not _venv_py(ROOT / "edp-broker").is_file(),
                                 reason="needs the edp-pool and edp-broker venvs")


def _release(d: Path, version: str = "99.0.0", *, tamper: bool = False) -> Path:
    d.mkdir(parents=True)
    lines = []
    for dist in ("edp8", "edp_contracts", "edp_pool", "edp_broker"):
        name = f"{dist}-{version}-py3-none-any.whl"
        (d / name).write_bytes(f"fake wheel {dist} {version}".encode())
        lines.append(f"{hashlib.sha256((d / name).read_bytes()).hexdigest()}  {name}\n")
    (d / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")
    if tamper:
        (d / f"edp_pool-{version}-py3-none-any.whl").write_bytes(b"swapped")
    return d


def _fake(code: str, *args: str) -> str:
    return json.dumps([sys.executable, "-c", code, *args])


ROWS_FAIL = [{"workflow": "custom-review", "version": 3, "ok": False, "errors": ["role 'qa' lost its checker"]},
             {"workflow": "standard", "version": 1, "ok": True, "errors": []}]
PRINT_ROWS = "import json,sys; print(sys.argv[1]); sys.exit(int(sys.argv[2]))"
RECORD = "import json,sys,pathlib; pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:])); sys.exit(int(sys.argv[2]))"
FAIL_NEW = ("import json,sys,pathlib; w=sys.argv[2]; pathlib.Path(sys.argv[1]).write_text(json.dumps([w]))"
            " if '-99.0.0-' not in w else None; sys.exit(3 if '-99.0.0-' in w else 0)")


def _prev(tmp_path: Path) -> list[str]:
    """`--previous-url` of a fake release of the installed version: the N-1 wheels a rollback needs (S11 F7).
    The version is the product's single source (`edp8.__version__`, what the updater reports), never the
    distribution metadata, which lags in an editable dev venv (0.8.0 vs 0.9.0, qa m-e633397a42)."""
    from edp8 import __version__
    return ["--previous-url", str(_release(tmp_path / "prev", __version__))]


def _status(inst) -> dict:
    return {x["service"]: x for x in json.loads(cli(inst, "status", "--json").stdout)}


def _db(inst) -> Path:
    return next(inst["home"].rglob("edp8.db"))


def _pins(db: Path) -> list[tuple]:
    c = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return sorted(c.execute("SELECT * FROM workflow_pins").fetchall())
    finally:
        c.close()


def _started(inst) -> str:
    """init + start + an epic (so it has a workflow pin); returns the owner token."""
    assert cli(inst, "init", "--harness", "claude", "--agent-home-source", str(V8)).returncode == 0
    r = cli(inst, "start")
    assert r.returncode == 0, r.stdout + r.stderr
    tok = json.loads((inst["home"] / "tokens.json").read_text(encoding="utf-8"))["owner"]
    e = httpx.post(f"http://127.0.0.1:{inst['ports']['board']}/v1/tickets", timeout=10,
                   headers={"X-Participant": "@owner", "X-Token": tok},
                   json={"kind": "epic", "work_type": "feature", "title": "pinned epic"})
    assert e.status_code == 200, e.text
    return tok


def _wait_result(inst, timeout=240) -> dict:
    f = next(iter(inst["home"].rglob("run")), inst["home"] / "run") / "update-result.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hits = list(inst["home"].rglob("update-result.json"))
        if hits:
            try:
                return json.loads(hits[0].read_text(encoding="utf-8"))
            except ValueError:
                pass
        time.sleep(1.0)
    log = list(inst["home"].rglob("update.log"))
    raise AssertionError(f"no {f} after {timeout}s; log: {log[0].read_text() if log else 'none'}")


def test_tampered_or_older_release_is_refused_before_anything_changes(inst, tmp_path):
    assert cli(inst, "init", "--harness", "claude", "--agent-home-source", str(V8)).returncode == 0
    inst["env"]["EDP_UPDATE_INSTALL_CMD"] = _fake(RECORD, str(tmp_path / "installed.json"), "0")
    bad = cli(inst, "update", "--release-url", str(_release(tmp_path / "bad", tamper=True)), "--skip-compat")
    assert bad.returncode == 2 and "SHA256 mismatch for edp_pool-99.0.0" in bad.stderr, bad.stdout + bad.stderr
    old = cli(inst, "update", "--release-url", str(_release(tmp_path / "old", "0.0.1")), "--skip-compat")
    assert old.returncode == 2 and "refusing a downgrade" in old.stderr, old.stdout + old.stderr
    assert not (tmp_path / "installed.json").exists() and not list(inst["home"].rglob("edp8-*.db"))


@NEEDS_VENVS
def test_failing_custom_workflow_aborts_the_update_and_changes_nothing(inst, tmp_path):
    _started(inst)
    try:
        before, pins = _status(inst), _pins(_db(inst))
        inst["env"]["EDP_UPDATE_COMPAT_CMD"] = _fake(PRINT_ROWS, json.dumps(ROWS_FAIL), "1")
        inst["env"]["EDP_UPDATE_INSTALL_CMD"] = _fake(RECORD, str(tmp_path / "installed.json"), "0")
        r = cli(inst, "update", "--release-url", str(_release(tmp_path / "rel")))
        assert r.returncode == 1, r.stdout + r.stderr
        assert "update aborted: 1 workflow(s) fail on 99.0.0" in r.stdout, r.stdout
        assert "FAIL custom-review@3" in r.stdout and "role 'qa' lost its checker" in r.stdout
        assert "ok   standard@1" in r.stdout and "heronry doctor" in r.stdout
        after = _status(inst)
        for svc in ("board", "broker", "pool", "mcp", "supervisor"):  # services untouched: same processes
            assert after[svc]["state"] == "up" and after[svc]["pid"] == before[svc]["pid"], (svc, before[svc], after[svc])
        assert not (tmp_path / "installed.json").exists()          # version untouched: nothing installed
        assert not list(inst["home"].rglob("edp8-*.db"))            # no backup taken, the DB never touched
        assert _pins(_db(inst)) == pins
        # exit 2 (the check cannot run) refuses too, unless --skip-compat
        inst["env"]["EDP_UPDATE_COMPAT_CMD"] = _fake(PRINT_ROWS, "[]", "2")
        r2 = cli(inst, "update", "--release-url", str(tmp_path / "rel"))
        assert r2.returncode == 2 and "could not run (exit 2" in r2.stderr, r2.stdout + r2.stderr
    finally:
        cli(inst, "stop", "--force")


@NEEDS_VENVS
def test_update_backs_up_stops_installs_starts_and_keeps_pins(inst, tmp_path):
    _started(inst)
    try:
        db = _db(inst)
        pins, before = _pins(db), _status(inst)
        assert pins, "the epic should be pinned to a workflow version"
        rel = _release(tmp_path / "rel")
        inst["env"]["EDP_UPDATE_COMPAT_CMD"] = _fake(PRINT_ROWS, json.dumps([ROWS_FAIL[1]]), "0")
        inst["env"]["EDP_UPDATE_INSTALL_CMD"] = _fake(RECORD, str(tmp_path / "installed.json"), "0", "{wheel}", "{with}")
        r = cli(inst, "update", "--release-url", str(rel), *_prev(tmp_path))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "compat check passed (1 workflow(s))" in r.stdout and "backed up the DB to" in r.stdout, r.stdout
        res = _wait_result(inst)
        assert res["state"] == "ok" and res["to"] == "99.0.0", res
        installed = json.loads((tmp_path / "installed.json").read_text(encoding="utf-8"))
        assert installed[1].endswith("edp8-99.0.0-py3-none-any.whl")  # the verified cached copy, with its siblings
        assert sum(a.endswith("-99.0.0-py3-none-any.whl") for a in installed) == 4
        backups = list((db.parent / "backups").glob("edp8-*.db"))
        assert len(backups) == 1
        c = sqlite3.connect(backups[0])
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        c.close()
        after = _status(inst)
        for svc in ("board", "broker", "pool", "mcp", "supervisor"):  # stopped and started again
            assert after[svc]["state"] == "up" and after[svc]["pid"] != before[svc]["pid"], (svc, after[svc])
        assert httpx.get(f"http://127.0.0.1:{inst['ports']['board']}/v1/health", timeout=10).status_code == 200
        assert _pins(db) == pins  # pinned epics stay on their versions
    finally:
        cli(inst, "stop", "--force")


@NEEDS_VENVS
def test_failed_install_rolls_back_to_the_backup_and_restarts(inst, tmp_path):
    _started(inst)
    try:
        db = _db(inst)
        pins = _pins(db)
        # the new wheels fail to install; the previous version's (secured before the stop) reinstall fine
        inst["env"]["EDP_UPDATE_INSTALL_CMD"] = _fake(FAIL_NEW, str(tmp_path / "installed.json"), "{wheel}")
        r = cli(inst, "update", "--release-url", str(_release(tmp_path / "rel")), "--skip-compat", *_prev(tmp_path))
        assert r.returncode == 0 and "WARNING: --skip-compat" in r.stdout, r.stdout + r.stderr
        assert "wheels are cached for a rollback" in r.stdout, r.stdout
        res = _wait_result(inst)
        assert res["state"] == "rolled_back" and res["reason"].startswith("install failed"), res
        assert "-99.0.0-" not in json.loads((tmp_path / "installed.json").read_text(encoding="utf-8"))[0]
        assert _status(inst)["board"]["state"] == "up"
        assert _pins(db) == pins
    finally:
        cli(inst, "stop", "--force")
