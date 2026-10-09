"""qa 0.10.7 (architect m-f04c23905e item 5): after `heronry update` the code server kept serving the old EDP Chat
extension until `heronry stop code; heronry start code`. The updater now records whether the code server answered
(`code_running`), the helper stops it before it installs and starts it after the new version is healthy (a start
installs the new vsix), on a uv tool install and on the bundle, and again after a rollback. Private temp homes only."""

from __future__ import annotations

import json
from pathlib import Path

from edp8 import code_service, update_helper, updater


def _plan(tmp_path: Path, **extra) -> Path:
    plan = {"from_version": "1.0.0", "to_version": "2.0.0", "caller_pid": 0, "install_argv": ["new"],
            "rollback_install_argv": ["prev"], "start_argv": ["py", "-m", "edp8.cli", "start"],
            "stop_argv": ["py", "-m", "edp8.cli", "stop", "--force"], "health_url": "http://127.0.0.1:1/v1/health",
            "install_dir": str(tmp_path), "db": str(tmp_path / "edp8.db"), "backup": "", "log": str(tmp_path / "update.log"),
            "result": str(tmp_path / "update-result.json"), "recover_hint": "reinstall", **extra}
    p = tmp_path / "update-plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    return p


def _drive(monkeypatch, *, fail: set[str] = frozenset()) -> list[tuple[str, list[str]]]:
    calls: list[tuple[str, list[str]]] = []

    def run(plan, what, argv, **kw):
        calls.append((what, list(argv)))
        return what not in fail
    monkeypatch.setattr(update_helper, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(update_helper, "_run", run)
    monkeypatch.setattr(update_helper, "_healthy", lambda url, *a, **k: True)
    monkeypatch.setattr(update_helper, "install_procs", lambda folder: [])
    return calls


def test_a_running_code_server_is_stopped_before_the_install_and_started_after_the_new_version_is_up(tmp_path, monkeypatch):
    calls = _drive(monkeypatch)
    assert update_helper.main(str(_plan(tmp_path, code_running=True))) == 0
    names = [c[0] for c in calls]
    assert names == ["stop code", "install", "start", "start code"], names
    assert dict(calls)["stop code"] == ["py", "-m", "edp8.cli", "stop", "code"]
    assert dict(calls)["start code"] == ["py", "-m", "edp8.cli", "start", "code"]


def test_no_code_server_means_no_code_commands(tmp_path, monkeypatch):
    calls = _drive(monkeypatch)
    assert update_helper.main(str(_plan(tmp_path, code_running=False))) == 0
    assert [c[0] for c in calls] == ["install", "start"]


def test_a_rollback_brings_the_code_server_back_too(tmp_path, monkeypatch):
    calls = _drive(monkeypatch, fail={"install"})
    assert update_helper.main(str(_plan(tmp_path, code_running=True))) == 1
    names = [c[0] for c in calls]
    assert names[0] == "stop code" and names[-1] == "start code" and "start previous" in names, names


def test_the_bundle_stops_a_recorded_code_server_the_process_scan_cannot_see(tmp_path, monkeypatch):
    calls = _drive(monkeypatch)  # install_procs finds nothing: only the updater's record says the server ran
    plan = {"start_argv": [r"C:\Heronry\heronry.exe", "start", "--no-browser"], "install_dir": str(tmp_path),
            "log": str(tmp_path / "u.log"), "code_running": True}
    assert update_helper._stop_code(plan) is True
    assert plan["_code_was_running"] is True
    assert calls == [("stop code", [r"C:\Heronry\heronry.exe", "stop", "code"])]
    update_helper._start_code(plan)
    assert calls[-1] == ("start code", [r"C:\Heronry\heronry.exe", "start", "code"])


def test_a_stopped_code_server_is_not_started_by_an_update(tmp_path, monkeypatch):
    calls = _drive(monkeypatch)
    plan = {"start_argv": ["heronry", "start"], "install_dir": str(tmp_path), "log": str(tmp_path / "u.log")}
    assert update_helper._stop_code(plan) is False
    update_helper._start_code(plan)
    assert calls == []


def test_the_updater_records_whether_the_code_server_answers(monkeypatch):
    monkeypatch.setattr(code_service, "status", lambda: {"state": "up"})
    assert updater._code_up() is True
    monkeypatch.setattr(code_service, "status", lambda: {"state": "down"})
    assert updater._code_up() is False

    def boom():
        raise RuntimeError("no record")
    monkeypatch.setattr(code_service, "status", boom)
    assert updater._code_up() is False
