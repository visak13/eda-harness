"""bin/heronry.cmd, the `heronry` command on PATH (owner m-584d63e760): it passes the CLI's exit code through, and
when the CLI left a follow script (an update handed over) it runs it in the same shell and returns its exit code.

heronry.exe is stood in for by a copy of cmd.exe, which takes `/c <command>` and so can exit with a code or write
the follow script the way the real CLI does."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe shim")

SHIM = Path(__file__).resolve().parents[1] / "desktop" / "scripts" / "heronry.cmd"
CRLF = "\r\n"


def _install(tmp_path: Path) -> Path:
    root = tmp_path / "Heronry Desktop"
    (root / "bin").mkdir(parents=True)
    shutil.copyfile(Path(os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe")), root / "heronry.exe")
    text = SHIM.read_text(encoding="ascii")
    (root / "bin" / "heronry.cmd").write_bytes((CRLF.join(text.splitlines()) + CRLF).encode("ascii"))
    return root / "bin" / "heronry.cmd"


def _run(shim: Path, tmp_path: Path, cli: str) -> subprocess.CompletedProcess:
    """`heronry <args>` typed in cmd, where the stand-in heronry.exe runs `cli`."""
    env = {**os.environ, "TEMP": str(tmp_path), "TMP": str(tmp_path)}
    return subprocess.run(f'cmd /d /s /c ""{shim}" /c {cli}"', capture_output=True, text=True, env=env, timeout=60)


def _follow_template(tmp_path: Path, lines: list[str]) -> str:
    """The stand-in CLI's command: it leaves a follow script as write_follow does (the viewer's output, an exit
    code) at %HERONRY_FOLLOW%, then exits 0 as the CLI does after a hand-over."""
    tpl = tmp_path / "template.cmd"
    tpl.write_bytes((CRLF.join(["@echo off", *lines]) + CRLF).encode("ascii"))
    mk = tmp_path / "handover.cmd"
    mk.write_bytes((CRLF.join(["@echo off", f'copy /y "{tpl}" "%HERONRY_FOLLOW%" >nul', "exit /b 0"]) + CRLF)
                   .encode("ascii"))
    return f'call "{mk}"'


def test_the_cli_exit_code_passes_through_when_no_update_was_handed_over(tmp_path):
    r = _run(_install(tmp_path), tmp_path, "exit 5")
    assert r.returncode == 5, r.stdout + r.stderr
    assert not list(tmp_path.glob("heronry-follow-*.cmd"))


def test_a_follow_script_left_by_the_cli_runs_in_the_same_shell_and_its_exit_code_is_returned(tmp_path):
    cli = _follow_template(tmp_path, ["echo [0:42] install: msiexec", "echo result: ok",
                                      'exit /b 0'])
    r = _run(_install(tmp_path), tmp_path, cli)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[0:42] install: msiexec" in r.stdout and "result: ok" in r.stdout, r.stdout + r.stderr
    assert not list(tmp_path.glob("heronry-follow-*.cmd")), "the shim deletes the follow script after it ran"


def test_a_failed_update_followed_in_the_shell_returns_non_zero(tmp_path):
    cli = _follow_template(tmp_path, ["echo result: rolled_back", 'exit /b 1'])
    r = _run(_install(tmp_path), tmp_path, cli)
    assert r.returncode == 1 and "result: rolled_back" in r.stdout, r.stdout + r.stderr


def test_the_build_writes_the_checked_in_shim():
    ps1 = (SHIM.parent / "build_windows.ps1").read_text(encoding="utf-8")
    assert 'Join-Path $PSScriptRoot "heronry.cmd"' in ps1
    text = SHIM.read_text(encoding="ascii")
    last = [ln for ln in text.splitlines() if ln.strip()][-1]
    # one command line: cmd has read it whole before heronry.exe runs and the installer replaces this file
    assert last.startswith('"%~dp0..\\heronry.exe" %*') and 'call "%HERONRY_FOLLOW%"' in last and last.endswith("call exit /b %%HERONRY_RC%%")
