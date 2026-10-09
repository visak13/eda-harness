"""s-4d93970c9f item 5: a pool started while the update lock is held does not resume `park_for_update` rows (the
updater resumes each seat once, after the final version is healthy); any resume consumes the mark."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from edp_pool.service import PoolService, _proc_fingerprint
from edp_pool.spawner import FakeSpawner


def _parked_then_shell_ended(tmp_path, monkeypatch):
    shell = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    state = tmp_path / "pool-state.json"
    svc1 = PoolService(FakeSpawner(), state_path=state)
    monkeypatch.setattr(svc1, "_inbox_depth", lambda h: 3)
    sid = svc1.spawn("planner", "rec-x:s1", None, claude_session="base-1")
    svc1.sessions[sid]["proc"] = _proc_fingerprint(shell.pid)
    svc1.park_session(sid, flush_timeout=0.05, flush_quiesce=0.01, for_update=True)
    shell.kill()  # what the update does to a parked seat's shell
    shell.wait()
    return state, sid


def test_a_pool_started_mid_update_leaves_the_parked_seats_for_the_updater(tmp_path, monkeypatch):
    state, sid = _parked_then_shell_ended(tmp_path, monkeypatch)
    lock = tmp_path / "update.lock"
    lock.write_text(json.dumps({"pids": [os.getpid()], "to": "9.9.9"}), encoding="utf-8")
    monkeypatch.setenv("EDP_UPDATE_LOCK", str(lock))
    svc2 = PoolService(FakeSpawner(), state_path=state)  # started while the update holds the lock
    assert svc2.resume_updater_parked(delay=0) == [] and svc2.spawner.launched == []
    assert svc2.sessions[sid]["state"] == "parked" and svc2.sessions[sid]["park_for_update"] is True


def test_a_dead_updaters_lock_does_not_hold_the_resume(tmp_path, monkeypatch):
    state, _ = _parked_then_shell_ended(tmp_path, monkeypatch)
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    lock = tmp_path / "update.lock"
    lock.write_text(json.dumps({"pids": [gone.pid], "to": "9.9.9"}), encoding="utf-8")
    monkeypatch.setenv("EDP_UPDATE_LOCK", str(lock))
    svc2 = PoolService(FakeSpawner(), state_path=state)
    assert svc2.resume_updater_parked(delay=0) == ["rec-x:s1"] and len(svc2.spawner.launched) == 1


def test_the_updaters_own_resume_consumes_the_mark_so_a_later_pool_start_does_not_repeat_it(tmp_path, monkeypatch):
    state, sid = _parked_then_shell_ended(tmp_path, monkeypatch)
    monkeypatch.delenv("EDP_UPDATE_LOCK", raising=False)
    svc2 = PoolService(FakeSpawner(), state_path=state)
    svc2.resume("rec-x:s1")  # the updater's POST /v1/resume
    assert "park_for_update" not in svc2.sessions[sid]
    svc3 = PoolService(FakeSpawner(), state_path=state)
    assert svc3.resume_updater_parked(delay=0) == [] and svc3.spawner.launched == []
