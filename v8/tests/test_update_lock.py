"""s-4d93970c9f item 2: the automatic update lock. While a live updater holds <home>/update/update.lock, no service
starts and the refusal names the update, its step and the elapsed time; a dead updater's lock is cleared; the
GitHub path (`heronry update` with no --release-url) and the installers honour the same file."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from edp8 import cli, code_service, launcher, update_lock, updater

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def home(monkeypatch, tmp_path):
    for k in ("EDP8_DATA", "EDP8_RUN_DIR", "EDP8_LOGS_DIR", "EDP8_HOME", "EDP_CONFIG_DIR", "EDP_DEV",
              update_lock.TOKEN_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EDP_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


def _held(step="park seats", to="9.9.9", pid=None):
    d = updater.update_dir()
    data = update_lock.acquire(d, from_version="9.9.8", to_version=to)
    if pid is not None:
        data["pids"] = [pid]
        update_lock._write(d, data)
    update_lock.step(d, step)
    return data


def _no_launch(monkeypatch):
    def detach(*a, **k):
        raise AssertionError("a service was launched while an update held the lock")
    monkeypatch.setattr(launcher, "detach", detach)


def test_start_is_refused_while_an_update_holds_the_lock(home, monkeypatch):
    _held()
    _no_launch(monkeypatch)
    with pytest.raises(launcher.LaunchError, match=r"update to 9\.9\.9 is in progress \(park seats, \d+:\d\d elapsed\)"):
        launcher.start("board", wait_s=1)
    with pytest.raises(launcher.LaunchError, match="update to 9.9.9 is in progress"):
        launcher.ensure_supervisor(wait_s=1)


def test_cli_start_and_restart_print_the_update_and_start_nothing(home, monkeypatch, capsys):
    _held(step="install")
    _no_launch(monkeypatch)
    assert cli.main(["start", "--no-browser"]) == 3
    assert cli.main(["restart"]) == 3
    err = capsys.readouterr().err
    assert err.count("an update to 9.9.9 is in progress (install,") == 2


def test_the_code_server_does_not_start_during_an_update(home, monkeypatch):
    _held()
    with pytest.raises(code_service.CodeError, match="update to 9.9.9 is in progress"):
        code_service.start(wait_s=1)


def test_the_updaters_own_start_carries_the_token_and_passes(home, monkeypatch):
    data = _held()
    assert update_lock.guard(updater.update_dir())
    monkeypatch.setenv(update_lock.TOKEN_ENV, data["token"])
    assert update_lock.guard(updater.update_dir()) is None
    monkeypatch.setenv(update_lock.TOKEN_ENV, "not-the-token")
    assert update_lock.guard(updater.update_dir())


def test_a_lock_whose_updater_is_dead_is_cleared(home):
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    _held(pid=proc.pid)
    assert update_lock.path_for(updater.update_dir()).is_file()
    assert update_lock.guard(updater.update_dir()) is None
    assert not update_lock.path_for(updater.update_dir()).exists()
    assert launcher.update_block() is None


def test_a_live_lock_is_not_taken_over(home):
    _held(pid=os.getppid())
    with pytest.raises(RuntimeError, match="update to 9.9.9 is in progress"):
        update_lock.acquire(updater.update_dir(), from_version="9.9.8", to_version="9.9.10")


def test_the_github_path_refuses_while_another_update_runs(home, monkeypatch):
    """`heronry update` with no --release-url (the GitHub release) goes through updater.apply, the same entry."""
    _held(pid=os.getppid())
    monkeypatch.setattr(updater, "fetch_release", lambda *a, **k: pytest.fail("fetched a release under the lock"))
    monkeypatch.setattr(updater, "fetch_msi_release", lambda *a, **k: pytest.fail("fetched a release under the lock"))
    with pytest.raises(updater.UpdateError, match="update to 9.9.9 is in progress"):
        updater.apply({})


def test_apply_releases_the_lock_when_it_stops_before_the_helper(home, monkeypatch):
    monkeypatch.setattr(updater, "_apply", lambda opts: (updater._take_lock("1.0.0", "1.0.1"),
                                                         (_ for _ in ()).throw(updater.UpdateError("refused")))[1])
    with pytest.raises(updater.UpdateError):
        updater.apply({})
    assert update_lock.held(updater.update_dir()) is None


def test_apply_keeps_the_lock_once_the_helper_has_it(home, monkeypatch):
    def handed(opts):
        updater._take_lock("1.0.0", "1.0.1")
        updater._LOCK["handed_off"] = True
        return 0
    monkeypatch.setattr(updater, "_apply", handed)
    assert updater.apply({}) == 0
    assert update_lock.held(updater.update_dir())["to"] == "1.0.1"


def test_progress_lines_carry_step_and_elapsed_and_the_lock_step(home, capsys):
    _held()
    d = updater.update_dir()
    update_lock.reset_progress(d)
    updater._say("stop", "the supervisor and services")
    update_lock.progress(d, "result", "ok", final=True)
    rows = [json.loads(x) for x in (d / update_lock.PROGRESS_NAME).read_text(encoding="utf-8").splitlines()]
    assert [r["step"] for r in rows] == ["stop", "result"] and rows[-1]["final"] is True
    assert re.match(r"\[\d+:\d\d\] stop: the supervisor and services", capsys.readouterr().out)
    assert update_lock.read(d)["step"] == "stop"  # the final line never overwrites the step


def test_update_lock_status_exit_code(home, capsys):
    assert updater.main(["--lock-status"]) == 0
    _held(pid=os.getppid())
    assert updater.main(["--lock-status"]) == 3
    assert "update to 9.9.9 is in progress" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------ installers

def _lock_file(root: Path, pid: int) -> None:
    f = root / "update" / "update.lock"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"pids": [pid], "to": "9.9.9", "step": "install"}, indent=1), encoding="utf-8")


def _snippet(path: Path, start: str, end: str) -> str:
    text = path.read_text(encoding="utf-8")
    return text[text.index(start):text.index(end)]


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="posix bash needed (MSYS cannot signal a Windows pid)")
def test_install_sh_refuses_over_a_live_update(tmp_path):
    snippet = _snippet(REPO / "install.sh", "# an update holds", 'if [ -n "$INSTALLED" ]')
    script = f'die() {{ echo "DIE: $*"; exit 1; }}\n{snippet}\necho CLEAR\n'
    me = os.getpid()
    env = {**os.environ, "EDP_HOME": tmp_path.as_posix()}
    _lock_file(tmp_path, me)
    live = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    assert live.returncode == 1 and "DIE: an update to 9.9.9 is in progress (install)" in live.stdout, live.stdout
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    _lock_file(tmp_path / "b", dead.pid)
    env["EDP_HOME"] = (tmp_path / "b").as_posix()
    gone = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    assert gone.returncode == 0 and "CLEAR" in gone.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell 5.1 needed")
def test_install_ps1_refuses_over_a_live_update(tmp_path):
    snippet = _snippet(REPO / "install.ps1", "  # an update holds", "  if ($installed -and")
    script = tmp_path / "t.ps1"
    script.write_text('function Die($s) { Write-Output "DIE: $s"; exit 1 }\n' + snippet + '\nWrite-Output "CLEAR"\n',
                      encoding="utf-8")
    ps = ["powershell", "-NoProfile", "-File", str(script)]
    _lock_file(tmp_path, os.getpid())
    env = {**os.environ, "EDP_HOME": str(tmp_path)}
    live = subprocess.run(ps, env=env, capture_output=True, text=True)
    assert live.returncode == 1 and "DIE: an update to 9.9.9 is in progress (install)" in live.stdout, live.stdout + live.stderr
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    _lock_file(tmp_path / "b", dead.pid)
    env["EDP_HOME"] = str(tmp_path / "b")
    gone = subprocess.run(ps, env=env, capture_output=True, text=True)
    assert gone.returncode == 0 and "CLEAR" in gone.stdout, gone.stdout + gone.stderr


def test_the_helper_joins_the_lock_and_releases_it_at_the_result(home, monkeypatch):
    from edp8 import update_helper as uh
    d = updater.update_dir()
    data = update_lock.acquire(d, from_version="1.0.0", to_version="1.0.1")
    data["pids"] = [os.getppid()]  # the caller, which exits before the helper works
    update_lock._write(d, data)
    plan = {"update_dir": str(d), "lock_token": data["token"], "no_window": True, "log": str(home / "u.log")}
    uh._lock_join(plan)
    assert os.getpid() in update_lock.read(d)["pids"] and os.environ[update_lock.TOKEN_ENV] == data["token"]
    monkeypatch.delenv(update_lock.TOKEN_ENV)
    uh._prog(plan, "install")
    assert update_lock.read(d)["step"] == "install"
    uh._prog_final(plan, "ok", "")
    assert update_lock.held(d) is None
    last = json.loads((d / update_lock.PROGRESS_NAME).read_text(encoding="utf-8").splitlines()[-1])
    assert last["step"] == "result" and last["final"] and last["detail"] == "ok"
    time.sleep(0)


# ------------------------------------------------------------------------------------------ progress window

def test_the_helper_opens_a_visible_console_window_never_hidden(home, monkeypatch):
    from edp8 import update_helper as uh
    seen = {}
    monkeypatch.setattr(uh.sys, "platform", "win32")
    monkeypatch.setattr(uh.subprocess, "Popen", lambda argv, **kw: seen.update(argv=argv, **kw))
    d = updater.update_dir()
    uh._open_window({"update_dir": str(d), "log": str(home / "u.log")})
    assert seen["creationflags"] == 0x00000010  # CREATE_NEW_CONSOLE: its own visible window
    assert seen["argv"][-2] == "--view" and seen["argv"][-1].endswith(update_lock.PROGRESS_NAME)
    assert "startupinfo" not in seen and "stdout" not in seen  # no SW_HIDE, no redirected output


def test_the_window_shows_every_step_with_elapsed_time_and_ends_with_the_result(home, monkeypatch, capsys):
    from edp8 import update_helper as uh
    d = updater.update_dir()
    _held()
    update_lock.reset_progress(d)
    for step in ("verified", "park seats", "stop", "install", "start", "health check", "resume seats"):
        update_lock.progress(d, step)
    update_lock.progress(d, "result", "ok", final=True)
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "")
    assert uh.view(str(d / update_lock.PROGRESS_NAME)) == 0
    out = capsys.readouterr().out
    for step in ("verified", "park seats", "stop", "install", "start", "health check", "resume seats"):
        assert re.search(rf"\[\d+:\d\d\] {step}\n", out), step
    assert re.search(r"\[\d+:\d\d\] result: ok\n", out) and prompts and "Press Enter to close" in prompts[0]


def test_rollback_steps_reach_the_window_through_run_and_msiexec(home, monkeypatch):
    from edp8 import update_helper as uh
    d = updater.update_dir()
    _held()
    update_lock.reset_progress(d)
    plan = {"update_dir": str(d), "log": str(home / "u.log")}
    monkeypatch.setattr(uh.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    uh._run(plan, "reinstall previous", ["x"])
    uh._msiexec(plan, "remove the new version", ["/x", "{C}"], "m.log")
    steps = [json.loads(x)["step"] for x in (d / update_lock.PROGRESS_NAME).read_text(encoding="utf-8").splitlines()]
    assert steps == ["reinstall previous", "remove the new version"]


def test_the_helper_pid_keeps_the_lock_live_after_the_caller_exits(home):
    """The caller adds the detached helper's pid at once: if the caller exits before the helper joins, the lock is
    still held (a lock with only dead pids would be cleared and the helper would run unlocked)."""
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    _held(pid=dead.pid)
    d = updater.update_dir()
    update_lock.add_pid(d, os.getpid())  # the helper, still running
    assert update_lock.held(d) is not None
    assert launcher.update_block() is not None
