"""scripts/install-heronry.cmd, the by-hand installer shipped beside every MSI (owner m-584d63e760): it verifies the
installer against SHA256SUMS, lists anything still running from the install folder (an exe moved to C:\\Config.Msi
included, by its command line), installs with the folder quoted the way msiexec accepts, and shows each step.

Run here in its read-only `--check` mode, with LOCALAPPDATA pointed at an empty folder so no real install is seen."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe script")

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "install-heronry.cmd"
CRLF = "\r\n"


def _release(tmp_path: Path, good_sum: bool = True) -> Path:
    rel = tmp_path / "release"
    rel.mkdir()
    msi = rel / "Heronry Desktop-9.9.9.msi"
    msi.write_bytes(b"not really an msi")
    digest = hashlib.sha256(msi.read_bytes()).hexdigest() if good_sum else "0" * 64
    (rel / "SHA256SUMS").write_text(f"{digest}  {msi.name}\n", encoding="ascii", newline="\n")
    text = SCRIPT.read_text(encoding="ascii")
    (rel / "install-heronry.cmd").write_bytes((CRLF.join(text.splitlines()) + CRLF).encode("ascii"))
    return rel


def _check(rel: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "LOCALAPPDATA": str(tmp_path / "localappdata"), "TEMP": str(tmp_path)}
    return subprocess.run(f'cmd /d /s /c ""{rel / "install-heronry.cmd"}" --check"', input="\n", capture_output=True,
                          text=True, env=env, timeout=120)


def test_check_mode_verifies_the_installer_and_finds_nothing_running_and_changes_nothing(tmp_path):
    r = _check(_release(tmp_path), tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[1/6] Checking the installer against SHA256SUMS" in r.stdout and "  OK " in r.stdout
    assert "  none" in r.stdout and "nothing was changed" in r.stdout


def test_an_installer_that_does_not_match_its_checksum_is_refused(tmp_path):
    r = _check(_release(tmp_path, good_sum=False), tmp_path)
    assert r.returncode == 1 and "checksum mismatch" in r.stdout, r.stdout + r.stderr
    assert "The install did not complete" in r.stdout


def test_the_install_line_quotes_the_folder_as_msiexec_accepts_and_shows_its_progress():
    text = SCRIPT.read_text(encoding="ascii")
    line = next(ln for ln in text.splitlines() if "msiexec /i" in ln)
    assert line.startswith('start "" /wait msiexec /i "%MSI%" MSIINSTALLPERUSER=1 ALLUSERS=2 INSTALLFOLDER="%DIR%"')
    assert "/passive" in line and "/qn" not in line and '/l*v "%LOG%"' in line
    # the holder check matches a moved-aside exe by its command line, as update_helper.install_procs does
    assert "$_.CommandLine" in text and "--heronry-service code-guard" in text


def test_after_installing_it_keeps_the_installer_where_the_next_update_looks_for_its_rollback(tmp_path, monkeypatch):
    """owner m-4b4e1dac4f: after a by-hand 0.10.3 install, `heronry update` refused ("couldn't secure the installed
    0.10.3's MSI for a rollback"): the cache it reads (updater.cached_msi) was empty. The script's cache step, run
    on its own here, fills it so that cached_msi finds the installer."""
    rel = _release(tmp_path)
    text = SCRIPT.read_text(encoding="ascii").splitlines()
    start = next(i for i, ln in enumerate(text) if ln.startswith("rem keep this installer"))
    end = next(i for i, ln in enumerate(text) if ln.startswith("echo [5/6]"))
    step = tmp_path / "cache-step.cmd"
    step.write_bytes((CRLF.join(["@echo off", "setlocal", f'set "HERE={rel}\\"',
                                 f'set "MSI={rel / "Heronry Desktop-9.9.9.msi"}"', *text[start:end]]) + CRLF)
                     .encode("ascii"))
    local = tmp_path / "localappdata"
    env = {**os.environ, "LOCALAPPDATA": str(local)}
    r = subprocess.run(f'cmd /d /s /c ""{step}""', capture_output=True, text=True, env=env, timeout=60)
    assert "kept the installer" in r.stdout, r.stdout + r.stderr
    from edp8 import settings, updater
    monkeypatch.setattr(settings, "data_dir", lambda: local / "heronry" / "data")
    got = updater.cached_msi("9.9.9")
    assert got is not None and got.name == "Heronry Desktop-9.9.9.msi"


def test_the_release_build_ships_it_beside_the_msi():
    ps1 = (REPO / "scripts" / "build_release.ps1").read_text(encoding="utf-8")
    assert 'scripts\\install-heronry.cmd' in ps1 and 'Join-Path $release "install-heronry.cmd"' in ps1
