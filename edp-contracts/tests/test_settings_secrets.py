"""Secret files are private on create and checked on read (strategyhl-86b4805322 §3, S1 spike)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from edp_contracts.settings import secrets


def test_write_secret_is_private_and_reads_back_clean(tmp_path: Path) -> None:
    p = secrets.write_secret(tmp_path / "secrets" / "tokens.json", "{}")
    assert p.read_text(encoding="utf-8") == "{}"
    assert secrets.problems(p) == []
    if sys.platform == "win32":
        assert secrets.acl_sids(p) == {secrets.current_user_sid(), secrets.SYSTEM_SID}
    else:
        assert p.stat().st_mode & 0o777 == 0o600 and p.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DACL")
def test_restrict_drops_explicit_aces_too(tmp_path: Path) -> None:
    # an elevated creator's file carries explicit OWNER RIGHTS + Administrators aces (CI run 36323612069)
    p = tmp_path / "t.json"
    p.write_text("{}", encoding="utf-8")
    subprocess.run(["icacls", str(p), "/grant", "*S-1-3-4:F", "*S-1-5-32-544:R"], capture_output=True, check=True)
    assert {"S-1-3-4", "S-1-5-32-544"} <= secrets.acl_sids(p)
    secrets._restrict_windows(p)
    assert secrets.acl_sids(p) == {secrets.current_user_sid(), secrets.SYSTEM_SID}
    assert secrets.problems(p) == [] and p.read_text(encoding="utf-8") == "{}"


def test_write_secret_refuses_to_overwrite(tmp_path: Path) -> None:
    p = secrets.write_secret(tmp_path / "t.json", "a")
    with pytest.raises(FileExistsError):
        secrets.write_secret(p, "b")


def test_a_loose_file_is_reported(tmp_path: Path) -> None:
    p = tmp_path / "loose.json"
    p.write_text("{}", encoding="utf-8")
    if sys.platform == "win32":
        subprocess.run(["icacls", str(p), "/grant", "*S-1-1-0:R"], capture_output=True, check=True)  # Everyone
    else:
        os.chmod(p, 0o644)
    assert secrets.problems(p), "a world-readable secret must be reported"


def test_absent_is_fine(tmp_path: Path) -> None:
    assert secrets.problems(tmp_path / "nope.json") == []
