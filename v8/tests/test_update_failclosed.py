"""S11 F3, F5, F7 (t-df9f2730b9): the app update fails closed and its outcome file tells the truth.

F3: the pool cannot say which seats are live -> `heronry update` refuses before the backup or the stop
(--force overrides); the admin apply and the harness update share the helper. F5: a rollback with no DB
backup (no DB before the update) skips the restore, and every terminal path of the detached helper
writes update-result.json, a crash included. F7: the installed version's wheels are secured before
anything stops, else the update refuses without --force; `rolled_back` means the previous code was
reinstalled, anything less is `failed` with the manual recovery line. Private temp homes only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from edp8 import launcher, settings, update_helper, updater
from edp8.admin import updates


class ReachedStop(Exception):
    pass


def _release_dir(d: Path, version: str) -> Path:
    d.mkdir(parents=True)
    lines = []
    for dist in updater.WHEELS:
        name = f"{dist}-{version}-py3-none-any.whl"
        (d / name).write_bytes(f"fake wheel {dist} {version}".encode())
        lines.append(f"{hashlib.sha256((d / name).read_bytes()).hexdigest()}  {name}\n")
    (d / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")
    return d


@pytest.fixture
def app_update(monkeypatch):
    """`updater.apply` up to the stop: an installed 1.0.0, a verified 2.0.0, a running pool."""
    monkeypatch.setenv("EDP_DEV", "0")
    monkeypatch.setattr(launcher, "bundled", lambda: False)
    monkeypatch.setattr(updater, "_uv_tool_env", lambda: True)
    monkeypatch.setattr(updater, "current_version", lambda: "1.0.0")
    monkeypatch.setattr(updater, "fetch_release", lambda url, tag=None: updater.Release("2.0.0", {}))
    monkeypatch.setattr(updater, "download", lambda rel: {})
    monkeypatch.setattr(updater, "secure_previous", lambda version, url=None: {"edp8": Path("prev.whl")})
    monkeypatch.setattr(launcher, "running", lambda svc: True)
    calls: list[str] = []
    monkeypatch.setattr(updater, "backup_db", lambda db, v: calls.append("backup") or Path("b.db"))

    def stop():
        calls.append("stop")
        raise ReachedStop()
    monkeypatch.setattr(updater, "_stop_all", stop)
    return calls


# ------------------------------------------------------------------------------------------ F3

def test_unknown_live_seats_refuses_before_backup_or_stop(app_update, monkeypatch):
    monkeypatch.setattr(launcher, "live_seats", lambda: None)
    with pytest.raises(updater.UpdateError) as e:
        updater.apply({})
    assert "couldn't confirm no seats are working" in str(e.value) and "--force" in str(e.value)
    assert app_update == []


def test_unknown_live_seats_with_force_proceeds(app_update, monkeypatch):
    monkeypatch.setattr(launcher, "live_seats", lambda: None)
    with pytest.raises(ReachedStop):
        updater.apply({"force": True})
    assert app_update[-1] == "stop"


def test_live_seats_refuse_and_none_live_proceeds(app_update, monkeypatch):
    monkeypatch.setattr(launcher, "live_seats", lambda: ["engineer.x (pid 7)"])
    with pytest.raises(updater.UpdateError, match=r"1 seat\(s\) are live \(engineer.x"):
        updater.apply({})
    assert app_update == []
    monkeypatch.setattr(launcher, "live_seats", lambda: [])
    with pytest.raises(ReachedStop):
        updater.apply({})


def test_cli_main_prints_the_refusal(app_update, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "live_seats", lambda: None)
    assert updater.main([]) == 2
    assert "update refused: couldn't confirm no seats are working" in capsys.readouterr().err


def test_admin_apply_refusal_fails_closed(monkeypatch):
    monkeypatch.setenv("EDP_DEV", "0")
    monkeypatch.setattr(launcher, "bundled", lambda: False)
    monkeypatch.setattr(updater, "_uv_tool_env", lambda: True)
    monkeypatch.setattr(launcher, "running", lambda svc: True)
    monkeypatch.setattr(launcher, "live_seats", lambda: None)
    assert "couldn't confirm no seats are working" in updates.refusal(force=False)
    assert updates.refusal(force=True) is None


def test_seat_block_is_the_one_rule():
    assert launcher.seat_block([]) is None
    assert "couldn't confirm" in launcher.seat_block(None, "ask to wait")
    assert launcher.seat_block(None, "ask to wait").endswith("ask to wait")
    assert "2 seat(s) are live (a, b)" in launcher.seat_block(["a", "b"])


# ------------------------------------------------------------------------------------------ F7 (apply side)

def test_unsecured_previous_wheels_refuse_before_backup_or_stop(app_update, monkeypatch):
    monkeypatch.setattr(launcher, "live_seats", lambda: [])
    monkeypatch.setattr(updater, "secure_previous", lambda version, url=None: None)
    with pytest.raises(updater.UpdateError, match="couldn't secure the installed 1.0.0's wheels"):
        updater.apply({})
    assert app_update == []
    with pytest.raises(ReachedStop):
        updater.apply({"force": True})


def test_secure_previous_fetches_the_installed_release_into_the_cache(tmp_path, monkeypatch):
    rel = _release_dir(tmp_path / "rel-1.0.0", "1.0.0")
    assert updater.cached("1.0.0") is None
    got = updater.secure_previous("1.0.0", str(rel))
    assert got and set(got) == set(updater.WHEELS)
    assert all(p.parent == settings.data_dir() / "updates" / "1.0.0" for p in got.values())
    assert updater.secure_previous("1.0.0") == got  # now from the cache, no fetch


def test_secure_previous_asks_github_for_the_installed_tag(monkeypatch):
    asked = []

    def fetch(url, tag=None):
        asked.append((url, tag))
        raise OSError("offline")
    monkeypatch.setattr(updater, "fetch_release", fetch)
    assert updater.secure_previous("1.2.3") is None
    assert asked == [(None, "v1.2.3")]


def test_secure_previous_refuses_another_version(tmp_path):
    rel = _release_dir(tmp_path / "rel", "1.0.1")
    assert updater.secure_previous("1.0.0", str(rel)) is None


# ------------------------------------------------------------------------------------------ the helper (F5, F7)

def _plan(tmp_path: Path, *, backup: str = "", rollback: list[str] | None = None) -> Path:
    plan = {"from_version": "1.0.0", "to_version": "2.0.0", "caller_pid": 0,
            "install_argv": ["new"], "rollback_install_argv": rollback,
            "start_argv": ["start"], "stop_argv": ["stop"], "health_url": "http://127.0.0.1:1/v1/health",
            "db": str(tmp_path / "edp8.db"), "backup": backup, "log": str(tmp_path / "update.log"),
            "result": str(tmp_path / "update-result.json"), "recover_hint": updater.recover_hint("1.0.0")}
    p = tmp_path / "update-plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    return p


def _drive(monkeypatch, *, fail: set[str] = frozenset(), health: list[bool] | None = None) -> list[str]:
    calls: list[str] = []

    def run(plan, what, argv, **kw):
        calls.append(what)
        return what not in fail
    ups = iter(health or [])
    monkeypatch.setattr(update_helper, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(update_helper, "_run", run)
    monkeypatch.setattr(update_helper, "_healthy", lambda url, *a, **k: next(ups, True))
    return calls


def _result(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "update-result.json").read_text(encoding="utf-8"))


def test_ok_path_writes_ok(tmp_path, monkeypatch):
    _drive(monkeypatch)
    assert update_helper.main(str(_plan(tmp_path))) == 0
    assert _result(tmp_path)["state"] == "ok"


def test_failed_install_without_a_db_backup_rolls_back_without_raising(tmp_path, monkeypatch):
    calls = _drive(monkeypatch, fail={"install"})
    assert update_helper.main(str(_plan(tmp_path, rollback=["prev"]))) == 1
    res = _result(tmp_path)
    assert res["state"] == "rolled_back" and res["reason"] == "install failed", res
    assert "reinstall previous" in calls and not (tmp_path / "edp8.db").exists()
    assert "no DB backup was taken" in (tmp_path / "update.log").read_text(encoding="utf-8")


def test_failed_install_without_backup_or_cached_wheels_is_failed(tmp_path, monkeypatch):
    calls = _drive(monkeypatch, fail={"install"})
    assert update_helper.main(str(_plan(tmp_path))) == 1
    res = _result(tmp_path)
    assert res["state"] == "failed" and "was not reinstalled" in res["reason"], res
    assert "install.ps1 -Version v1.0.0" in res["reason"] and "reinstall previous" not in calls


def test_unhealthy_new_version_without_cached_wheels_is_never_rolled_back(tmp_path, monkeypatch):
    """F7 repro: install ok, first health fails, second passes, no previous wheels -> failed, not rolled_back."""
    db, backup = tmp_path / "edp8.db", tmp_path / "backup.db"
    db.write_text("new schema"); backup.write_text("old schema")
    calls = _drive(monkeypatch, health=[False, True])
    update_helper.main(str(_plan(tmp_path, backup=str(backup))))
    res = _result(tmp_path)
    assert res["state"] == "failed" and "not reinstalled" in res["reason"] and "install.ps1" in res["reason"], res
    assert "reinstall previous" not in calls and db.read_text() == "old schema"


def test_unhealthy_new_version_with_cached_wheels_rolls_back(tmp_path, monkeypatch):
    db, backup = tmp_path / "edp8.db", tmp_path / "backup.db"
    db.write_text("new schema"); backup.write_text("old schema")
    calls = _drive(monkeypatch, health=[False, True])
    update_helper.main(str(_plan(tmp_path, backup=str(backup), rollback=["prev"])))
    res = _result(tmp_path)
    assert res["state"] == "rolled_back" and res["reason"] == "the new version did not come up healthy", res
    assert calls == ["install", "start", "stop", "reinstall previous", "start previous"]
    assert db.read_text() == "old schema"


def test_failed_reinstall_of_the_previous_version_is_failed(tmp_path, monkeypatch):
    _drive(monkeypatch, fail={"install", "reinstall previous"})
    update_helper.main(str(_plan(tmp_path, rollback=["prev"])))
    res = _result(tmp_path)
    assert res["state"] == "failed" and "reinstalling the previous version failed" in res["reason"], res


def test_rollback_that_does_not_come_up_is_failed(tmp_path, monkeypatch):
    _drive(monkeypatch, fail={"install", "start previous"})
    update_helper.main(str(_plan(tmp_path, rollback=["prev"])))
    res = _result(tmp_path)
    assert res["state"] == "failed" and "the rollback did not come up either" in res["reason"], res


def test_caller_that_never_exits_is_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(update_helper, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(update_helper.time, "monotonic", iter(range(0, 10_000, 200)).__next__)
    monkeypatch.setattr(update_helper.time, "sleep", lambda s: None)
    assert update_helper.main(str(_plan(tmp_path))) == 1
    assert _result(tmp_path)["state"] == "failed"


def test_a_crash_anywhere_still_writes_a_failed_result(tmp_path, monkeypatch):
    _drive(monkeypatch, fail={"install"})

    def boom(plan):
        raise PermissionError(13, "Access is denied", plan["db"])
    monkeypatch.setattr(update_helper, "_restore", boom)
    assert update_helper.main(str(_plan(tmp_path, backup=str(tmp_path / "b.db")))) == 1
    res = _result(tmp_path)
    assert res["state"] == "failed" and "crashed (PermissionError" in res["reason"], res
    assert "install.ps1 -Version v1.0.0" in res["reason"]
