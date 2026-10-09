"""s-4d93970c9f item 6: scripts/build_release.ps1 builds from a clean worktree and fails unless every package and the
board report the version. Only the cheap `-CheckOnly` path runs here (no web build, no wheels, no MSI)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "build_release.ps1"
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="PowerShell 5.1 (Windows) release build")


def _ps(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-File", str(SCRIPT), *args], capture_output=True, text=True,
                          cwd=REPO)


def _version() -> str:
    from edp8 import __version__
    return __version__


def test_the_script_parses_and_documents_itself():
    cmd = ("$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile("
           f"'{SCRIPT}',[ref]$null,[ref]$e); if($e){{$e|%{{$_.Message}};exit 1}}")
    assert subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True).returncode == 0
    doc = (REPO / "docs" / "release.md").read_text(encoding="utf-8")
    assert "scripts/build_release.ps1" in doc and "only release build" in doc and "SHA256SUMS" in doc


def test_a_clean_worktree_with_the_right_version_passes_the_check(tmp_path):
    r = _ps("-Version", _version(), "-Ref", "HEAD", "-Out", str(tmp_path / "out"), "-CheckOnly")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "CHECK-OK" in r.stdout and f"carries {_version()} in every package" in r.stdout
    assert not (tmp_path / "out" / "work").exists(), "the throwaway worktree is removed"


def test_a_version_the_commit_does_not_carry_is_refused_naming_each_package(tmp_path):
    r = _ps("-Version", "9.9.9", "-Ref", "HEAD", "-Out", str(tmp_path / "out"), "-CheckOnly")
    assert r.returncode != 0
    text = r.stdout + r.stderr
    for name in ("edp-contracts __version__", "edp-pool __version__", "edp-broker __version__", "edp8 (board) __version__"):
        assert name in text, text


def test_a_bad_version_a_bad_ref_and_a_used_folder_are_refused_before_anything_is_built(tmp_path):
    assert "must be X.Y.Z" in (_ps("-Version", "1.2", "-Ref", "HEAD", "-Out", str(tmp_path / "a"))).stderr
    assert "is not a commit" in (_ps("-Version", _version(), "-Ref", "no-such-ref", "-Out", str(tmp_path / "b"))).stderr
    used = tmp_path / "c"
    used.mkdir()
    (used / "stale.whl").write_text("x")
    assert "is not empty" in (_ps("-Version", _version(), "-Ref", "HEAD", "-Out", str(used))).stderr
