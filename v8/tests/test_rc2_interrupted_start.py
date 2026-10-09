"""RC2 item 3 (t-e338298d88): `heronry start` after an interrupted (Ctrl+C) start. The earlier run's service is
still coming up (the owner's board warms for minutes), unrecorded: the old start launched a second one beside it
("database is locked", a bound port). Now start adopts it, or stops it and starts afresh, and a failure is one
line naming the command to run, never a traceback."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest
from edp_contracts.identity import home_id_of
from edp_contracts.proc import ProcId

from edp8 import cli, launcher, run_state, settings
from test_launcher_identity import MARKER, home, marker  # noqa: F401 — fixtures

SLOW = r"""
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
port, body, delay = int(sys.argv[1]), sys.argv[2], float(sys.argv[3])
time.sleep(delay)  # an interrupted start's board, still warming
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        data = body.encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


WARMING = r"""
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
port, body, delay, log = int(sys.argv[1]), sys.argv[2], float(sys.argv[3]), sys.argv[4]
end = time.monotonic() + delay
while time.monotonic() < end:  # warming: the log grows, as a board's index build does
    with open(log, "a", encoding="utf-8") as f:
        f.write("warming\n")
    time.sleep(0.3)
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        data = body.encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


def _leftover(tmp_path, marker, port: int, delay: float, *, warming: bool = False) -> subprocess.Popen:
    """A process of this home whose argv ends `-m edp8.service`, as the interrupted start left it. `warming`:
    it appends to the board's log until it listens."""
    script = tmp_path / ("warming_board.py" if warming else "slow_board.py")
    script.write_text(WARMING if warming else SLOW, encoding="utf-8")
    body = json.dumps({"ok": True, "service": "board", "home_id": home_id_of(settings.data_dir())})
    env = {**os.environ, MARKER: marker, "EDP8_RUN_DIR": str(settings.run_dir())}
    extra = [str(launcher._log_path("board"))] if warming else []
    return subprocess.Popen([sys.executable, str(script), str(port), body, str(delay), *extra, "-m", "edp8.service"],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _no_second_board(monkeypatch):
    def detach(*a, **k):
        raise AssertionError("a second board was launched beside the interrupted start's")
    monkeypatch.setattr(launcher, "detach", detach)


def test_a_board_still_coming_up_is_adopted_never_doubled(home, marker, tmp_path, monkeypatch):
    proc = _leftover(tmp_path, marker, home["port"], delay=3.0)
    time.sleep(0.5)
    assert proc.pid in [p.pid for p in launcher.leftovers("board")]  # (and a venv stub's interpreter child)
    _no_second_board(monkeypatch)
    out = launcher.start("board", wait_s=30)
    assert out["state"] == "already_running" and out["reason"] == "adopted from an interrupted start"
    assert run_state.read("board")["pid"] == run_state.listener_pid(home["port"]) and launcher.running("board")
    assert launcher.leftovers("board") == []  # recorded now: the next start has nothing to recover


def test_a_leftover_that_never_answers_is_stopped_before_a_fresh_start(home, marker, tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "RECOVER_STALL_S", 1.0)  # dead-stuck: no log, no CPU
    proc = _leftover(tmp_path, marker, home["port"], delay=3600)
    time.sleep(0.5)
    ident = ProcId.of(proc.pid)
    seen = []

    def detach(*a, **k):
        seen.append(ident.live() is None)
        raise launcher.LaunchError("stop here: the fresh launch is proven elsewhere")
    monkeypatch.setattr(launcher, "detach", detach)
    with pytest.raises(launcher.LaunchError, match="stop here"):
        launcher.start("board", wait_s=2)
    assert seen == [True]  # the leftover was gone before the fresh board was launched


def test_another_homes_process_is_never_a_leftover(home, marker, tmp_path, monkeypatch):
    proc = _leftover(tmp_path, marker, home["port"], delay=3600)
    time.sleep(0.5)
    monkeypatch.setenv("EDP_HOME", str(tmp_path / "homeB"))
    (tmp_path / "homeB").mkdir()
    assert proc.pid not in [p.pid for p in launcher.leftovers("board")]
    proc.kill()


def test_a_failed_start_is_one_line_naming_the_command_never_a_traceback(home, monkeypatch, capsys):
    import sqlite3

    def boom(argv):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setitem(cli._COMMANDS, "start", boom)
    monkeypatch.delenv("HERONRY_DEBUG", raising=False)
    assert cli.main(["start"]) == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err and err.count("\n") == 1
    assert "database is locked" in err and "stop --force`, then `" in err and "start`" in err
    monkeypatch.setenv("HERONRY_DEBUG", "1")
    with pytest.raises(sqlite3.OperationalError):
        cli.main(["start"])


def test_a_leftover_still_warming_is_waited_for_past_the_start_timeout(home, marker, tmp_path, monkeypatch, capsys):
    """Architect m-32709b46b8: a busy leftover is not killed at wait_s and replaced by a board that warms as long."""
    monkeypatch.setattr(launcher, "RECOVER_STALL_S", 2.0)
    monkeypatch.setattr(launcher, "RECOVER_SAY_S", 1.0)
    proc = _leftover(tmp_path, marker, home["port"], delay=6.0, warming=True)
    time.sleep(0.5)
    _no_second_board(monkeypatch)
    out = launcher.start("board", wait_s=1)
    assert out["reason"] == "adopted from an interrupted start" and proc.poll() is None
    assert "still warming up" in capsys.readouterr().out


def test_a_busy_leftover_is_stopped_at_the_ceiling(home, marker, tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "RECOVER_STALL_S", 60.0)
    monkeypatch.setattr(launcher, "RECOVER_CEILING_S", 3.0)
    proc = _leftover(tmp_path, marker, home["port"], delay=3600, warming=True)
    time.sleep(0.5)

    def detach(*a, **k):
        raise launcher.LaunchError("stop here")
    monkeypatch.setattr(launcher, "detach", detach)
    with pytest.raises(launcher.LaunchError, match="stop here"):
        launcher.start("board", wait_s=1)
    proc.wait(timeout=10)


def test_a_start_whose_process_lost_the_port_to_another_start_adopts_the_winner(home, marker, tmp_path, monkeypatch):
    """t-fb8b63874e item 6: the owner's rolled-back update printed `board FAILED … exited during start (pid 37616
    is gone)` while the board was healthy: another start of this home (a supervisor's relaunch) took the port, and
    its board answered a few seconds after this start's process was gone. That board is adopted, not failed."""
    winner: list[subprocess.Popen] = []

    def detach(*a, **k):  # this start's process exits at once; the other start's board answers 2 s later
        winner.append(_leftover(tmp_path, marker, home["port"], delay=2.0))
        mine = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])
        ident = ProcId.of(mine.pid)
        mine.wait()
        return ident, None
    monkeypatch.setattr(launcher, "detach", detach)
    try:
        out = launcher.start("board", wait_s=30)
        assert out["state"] == "already_running" and "another start of this home won the port" in out["reason"]
        assert run_state.read("board")["pid"] == run_state.listener_pid(home["port"])
    finally:
        for w in winner:
            w.kill()
            w.wait()


def _stray(tmp_path, marker, port: int, delay: float, version: str = "0.0.1") -> subprocess.Popen:
    script = tmp_path / "stray_board.py"
    script.write_text(SLOW, encoding="utf-8")
    body = json.dumps({"ok": True, "service": "board", "version": version, "home_id": home_id_of(settings.data_dir())})
    env = {**os.environ, MARKER: marker, "EDP8_RUN_DIR": str(settings.run_dir())}
    return subprocess.Popen([sys.executable, str(script), str(port), body, str(delay), "-m", "edp8.service"],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _launch_marker(monkeypatch, seen):
    def detach(*a, **k):
        seen.append(True)
        raise launcher.LaunchError("stop here: the fresh launch is proven elsewhere")
    monkeypatch.setattr(launcher, "detach", detach)


def test_a_running_board_of_another_version_is_stopped_never_adopted(home, marker, tmp_path, monkeypatch):
    """s-4d93970c9f item 1: a board of this home reporting 0.0.1 while 9.9.9 is installed is stopped, then the
    installed version is launched (a fresh launch is attempted)."""
    monkeypatch.setattr(launcher, "installed_version", lambda: "9.9.9", raising=False)
    proc = _stray(tmp_path, marker, home["port"], delay=0.0)
    time.sleep(1.0)
    ident = ProcId.of(proc.pid)
    gone, seen = [], []
    monkeypatch.setattr(launcher, "detach", lambda *a, **k: (gone.append(ident.live() is None),
                                                              (_ for _ in ()).throw(launcher.LaunchError("stop here")))[1])
    with pytest.raises(launcher.LaunchError, match="stop here"):
        launcher.start("board", wait_s=2)
    assert gone == [True] and not seen


def test_an_interrupted_start_that_comes_up_as_another_version_is_not_adopted(home, marker, tmp_path, monkeypatch):
    """s-4d93970c9f item 1, the owner's case: the leftover answers after warming, as the OLD version."""
    monkeypatch.setattr(launcher, "installed_version", lambda: "9.9.9", raising=False)
    proc = _stray(tmp_path, marker, home["port"], delay=2.0)
    time.sleep(0.5)
    assert proc.pid in [p.pid for p in launcher.leftovers("board")]
    ident = ProcId.of(proc.pid)
    gone = []
    monkeypatch.setattr(launcher, "detach", lambda *a, **k: (gone.append(ident.live() is None),
                                                              (_ for _ in ()).throw(launcher.LaunchError("stop here")))[1])
    with pytest.raises(launcher.LaunchError, match="stop here"):
        launcher.start("board", wait_s=30)
    assert gone == [True]


def test_a_board_of_the_installed_version_is_still_adopted(home, marker, tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "installed_version", lambda: "0.0.1", raising=False)
    proc = _stray(tmp_path, marker, home["port"], delay=0.0)
    time.sleep(1.0)
    _no_second_board(monkeypatch)
    assert launcher.start("board", wait_s=10)["state"] == "already_running"
    proc.kill()
