"""s-4d93970c9f items 4 and 5: a rollback restores the pre-update DB backup only when the new version changed the
DB, and the parked seats are resumed exactly once per update. Process calls are fakes; the DBs are real sqlite."""

from __future__ import annotations

import sqlite3

import pytest

from edp8 import update_helper as h
from edp8 import updater
from test_update_s10 import _staged_msis


def _db(path, *, extra_column=False, rows=("a",)):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS ticket (id TEXT, title TEXT" + (", migrated INTEGER" if extra_column else "") + ")")
    con.executemany("INSERT INTO ticket (id) VALUES (?)", [(r,) for r in rows])
    con.commit()
    con.close()


def _ids(path):
    con = sqlite3.connect(path)
    try:
        return sorted(r[0] for r in con.execute("SELECT id FROM ticket"))
    finally:
        con.close()


def _plan(tmp_path, **kw):
    return {"db": str(tmp_path / "edp8.db"), "backup": str(tmp_path / "backup.db"), "log": str(tmp_path / "u.log"), **kw}


def test_rows_written_during_the_update_are_kept_when_the_schema_did_not_change(tmp_path):
    _db(tmp_path / "backup.db", rows=("old",))
    _db(tmp_path / "edp8.db", rows=("old", "written-during-update"))
    plan = _plan(tmp_path)
    assert h._restore(plan) == "kept"
    assert _ids(tmp_path / "edp8.db") == ["old", "written-during-update"]
    assert plan["_db"]["case"] == "kept" and "did not change" in plan["_db"]["why"]


def test_the_backup_is_restored_when_the_new_version_migrated_the_db(tmp_path):
    _db(tmp_path / "backup.db", rows=("old",))
    _db(tmp_path / "edp8.db", extra_column=True, rows=("old", "written-by-new-version"))
    plan = _plan(tmp_path)
    assert h._restore(plan) == "restored"
    assert _ids(tmp_path / "edp8.db") == ["old"]
    assert plan["_db"]["case"] == "restored" and "changed the DB schema" in plan["_db"]["why"]


def test_a_changed_migration_marker_alone_restores(tmp_path):
    _db(tmp_path / "backup.db", rows=("old",))
    _db(tmp_path / "edp8.db", rows=("old", "new"))
    con = sqlite3.connect(tmp_path / "edp8.db")
    con.execute("PRAGMA user_version = 7")
    con.close()
    assert h._restore(_plan(tmp_path)) == "restored" and _ids(tmp_path / "edp8.db") == ["old"]


def test_an_unreadable_live_db_is_restored_not_assumed_unchanged(tmp_path):
    _db(tmp_path / "backup.db", rows=("old",))
    (tmp_path / "edp8.db").write_bytes(b"not a database" * 100)
    plan = _plan(tmp_path)
    assert h._restore(plan) == "restored" and _ids(tmp_path / "edp8.db") == ["old"]
    assert "could not be compared" in plan["_db"]["why"]


def test_no_backup_means_nothing_to_restore(tmp_path):
    plan = _plan(tmp_path, backup="")
    assert h._restore(plan) == "none" and plan["_db"]["case"] == "none"


def test_the_result_receipt_names_the_db_case(tmp_path):
    out = {}
    plan = {"_db": {"case": "kept", "why": "rows written during the update kept"}}
    res = {"state": "rolled_back", "reason": "the board reports 0.9.1, not 0.9.2", "from": "0.9.1", **{
        "db_restore": plan["_db"]["case"], "db_restore_reason": plan["_db"]["why"]}}
    assert "rows written during the update kept" in updater.result_text(res) and out == {}


# ------------------------------------------------------------------------------------------ a whole rollback

def _rollback_rig(tmp_path, monkeypatch, *, migrated):
    """The MSI runner against fakes: the new version installs, reports the OLD version (the owner's 12:07Z failure),
    the runner rolls back, relaunches, and resumes. A fake pool counts every POST /v1/resume per seat."""
    _db(tmp_path / "backup.db", rows=("old",))
    _db(tmp_path / "edp8.db", extra_column=migrated, rows=("old", "during"))
    resumes: dict[str, int] = {}

    def http(url, method="GET", **kw):
        if url.endswith("/v1/sessions"):
            return [{"handle": s, "state": "active", "proc": {"pid": 1}} for s in ("seat-a", "seat-b")]
        if "/v1/park/" in url:
            return {"ok": True}
        if "/v1/resume/" in url:
            handle = url.rsplit("/", 1)[1]
            resumes[handle] = resumes.get(handle, 0) + 1
            return {"resumed": True}
        raise AssertionError(f"unexpected endpoint {url}")

    plan = {"kind": "msi", "from_version": "0.9.1", "to_version": "0.9.2", **_staged_msis(tmp_path),
            "install_dir": str(tmp_path), "upgrade_code": "{UC}", "stop_argv": ["stop"], "start_argv": ["start"],
            "health_url": "http://127.0.0.1:1/v1/health", "pool_url": "http://127.0.0.1:1",
            "db": str(tmp_path / "edp8.db"), "backup": str(tmp_path / "backup.db"), "log": str(tmp_path / "u.log"),
            "recover_hint": "reinstall", "holder_wait_s": 0}
    installed = iter(["0.9.2", "0.9.1", "0.9.1", "0.9.1"])
    monkeypatch.setattr(h, "_http", http)
    monkeypatch.setattr(h, "_run", lambda *a, **k: True)
    monkeypatch.setattr(h, "_close_app", lambda p: None)
    monkeypatch.setattr(h, "_end_parked_shells", lambda *a: [])
    monkeypatch.setattr(h, "_stop_code", lambda p: False)
    monkeypatch.setattr(h, "_stop_install_procs", lambda p: [])
    monkeypatch.setattr(h, "holders", lambda *a, **k: [])
    monkeypatch.setattr(h, "related_products", lambda code: [{"code": "{PC}", "version": "0.9.2"}])
    monkeypatch.setattr(h, "_msiexec", lambda *a: 0)
    monkeypatch.setattr(h, "_wait_msi_idle", lambda *a, **k: None)
    monkeypatch.setattr(h, "_installed", lambda p: next(installed, "0.9.1"))
    monkeypatch.setattr(h, "_health_version", lambda *a, **k: "0.9.1")  # the board reports the OLD version
    out: dict = {}

    def finish(state, reason="", **kw):
        out.update(state=state, reason=reason, **kw)
        if plan.get("_db"):
            out.update(db_restore=plan["_db"]["case"], db_restore_reason=plan["_db"]["why"])
        return 0
    return plan, out, resumes, finish, None


@pytest.mark.parametrize("migrated, case, rows", [(False, "kept", ["during", "old"]), (True, "restored", ["old"])])
def test_a_rollback_keeps_or_restores_the_db_and_resumes_each_seat_once(tmp_path, monkeypatch, migrated, case, rows):
    plan, out, resumes, finish, _ = _rollback_rig(tmp_path, monkeypatch, migrated=migrated)
    h._msi_steps(plan, finish)
    assert out["state"] == "rolled_back", out
    assert out["db_restore"] == case and _ids(tmp_path / "edp8.db") == rows
    assert resumes == {"seat-a": 1, "seat-b": 1}, f"each parked seat resumes once, got {resumes}"
    assert out["resumed"] == ["seat-a", "seat-b"]


def test_a_second_resume_in_one_update_is_a_no_op(tmp_path, monkeypatch):
    plan, out, resumes, finish, _ = _rollback_rig(tmp_path, monkeypatch, migrated=False)
    assert h._resume(plan, ["seat-a", "seat-b"]) == ["seat-a", "seat-b"]
    assert h._resume(plan, ["seat-a", "seat-b"]) == ["seat-a", "seat-b"]
    assert h._resume_now(plan, ["seat-a"]) == ["seat-a"]
    assert resumes == {"seat-a": 1, "seat-b": 1}


def test_the_runner_never_waits_for_the_pool_to_resume_seats_itself(tmp_path, monkeypatch):
    """The pool's own resume is off while the lock is held, so the runner must not wait on it (it did, for 120 s)."""
    plan, out, resumes, finish, _ = _rollback_rig(tmp_path, monkeypatch, migrated=False)
    calls = []
    real = h._http

    def http(url, *a, **k):
        calls.append(url)
        return real(url, *a, **k)
    monkeypatch.setattr(h, "_http", http)
    h._resume(plan, ["seat-a"])
    assert not any(u.endswith("/v1/pool/capabilities") for u in calls) and resumes == {"seat-a": 1}


def test_a_guard_whose_exe_an_earlier_msi_moved_aside_is_still_an_install_process(monkeypatch):
    """The owner's 13:05 update: a code guard left by a rolled-back update ran from C:\Config.Msi\*.rbf (the MSI
    moved its in-use heronry.exe aside) while holding the install folder's DLLs. It was not stopped, so the
    Restart Manager named it and the update rolled back. Its command line still names the install's exe."""
    from edp8 import update_helper as h
    folder = r"C:\Users\x\AppData\Local\Programs\Heronry contributors\Heronry Desktop"
    procs = {
        11: (r"C:\Config.Msi\1db3bf34.rbf",
             f'"{folder}\heronry.exe" --heronry-service code-guard --port 19410'),
        12: (r"C:\Config.Msi\aa.rbf", r'"C:\Other\tool.exe" --x'),  # someone else's moved exe: not ours
        13: (f"{folder}\heronry.exe", f'"{folder}\heronry.exe" --heronry-service board'),
    }
    monkeypatch.setattr(h, "_snapshot", lambda: [(pid, 1, "heronry.exe") for pid in procs])
    monkeypatch.setattr(h, "_proc_identity", lambda pid: (1.0, procs[pid][0]))
    monkeypatch.setattr(h, "_cmdline", lambda pid: procs[pid][1])
    got = {p["pid"]: p for p in h.install_procs(folder)}
    assert sorted(got) == [11, 13]
    assert h._is_code_guard(got[11])
