"""stop.* must verify the process is gone before it reports "stopped" (S17 c-c0f2ceea9b; qa drill
2026-09-10 found stop.ps1 printing "stopped" while all five services survived)."""

import subprocess
import sys

import psutil

from edp8 import run_state


def test_stop_service_kills_recorded_pid_tree_and_clears_record(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path))
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        run_state.write("pool", pid=child.pid, port=None, git_rev="x")
        res = run_state.stop_service("pool", timeout_s=6)
        assert res["recorded"] is True
        assert child.pid in res["killed"]
        assert res["still_running"] == []
        assert not psutil.pid_exists(child.pid) or psutil.Process(child.pid).status() == psutil.STATUS_ZOMBIE
        assert run_state.read("pool") is None
    finally:
        if child.poll() is None:
            child.kill()


def test_stop_service_reports_not_running_without_a_record(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path))
    res = run_state.stop_service("board")
    assert res == {"service": "board", "recorded": False, "killed": [], "still_running": []}


def test_stop_service_leaves_a_foreign_bridge_pid_alone(tmp_path, monkeypatch):
    """A bridge record whose pid is no longer a slack_bridge (reused pid, another fleet) is never killed."""
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path))
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        run_state.write("bridge", pid=child.pid, port=None, git_rev="x")
        res = run_state.stop_service("bridge", timeout_s=3)
        assert res["killed"] == [] and res["still_running"] == []
        assert child.poll() is None  # untouched
        assert run_state.read("bridge") is None  # nothing of ours left → record cleared
    finally:
        child.kill()
