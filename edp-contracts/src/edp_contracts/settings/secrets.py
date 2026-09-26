"""Secret files (tokens.json, generated admin tokens): created private, checked on use.

strategyhl-86b4805322 §3 (enforced): POSIX mode 0600 in a 0700 dir, created O_EXCL under umask 077;
Windows ACL = the current user's SID + SYSTEM only (inheritance removed; SIDs, never localised names).
`problems()` reads the protection back; start/doctor refuse a file it objects to (outside dev mode).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SYSTEM_SID = "S-1-5-18"
_WIN = sys.platform == "win32"


def _run(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True, check=True, timeout=30).stdout


def current_user_sid() -> str:
    """The current Windows user's SID (`whoami /user`)."""
    out = _run(["whoami", "/user", "/fo", "csv", "/nh"]).strip()
    return out.rsplit(",", 1)[-1].strip().strip('"')


def acl_sids(path: Path) -> set[str]:
    """The SIDs holding any access entry on `path` (Windows), via Get-Acl, translated to SIDs."""
    ps = ("(Get-Acl -LiteralPath $env:EDP_ACL_PATH).Access | ForEach-Object { "
          "$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }")
    env = {**os.environ, "EDP_ACL_PATH": str(path)}
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                         text=True, check=True, timeout=60, env=env).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def _restrict_windows(path: Path) -> None:
    sid = current_user_sid()
    _run(["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:F", f"*{SYSTEM_SID}:F"])


def write_secret(path: str | Path, data: str) -> Path:
    """Create `path` holding `data`, readable by the current user only. Refuses to overwrite (O_EXCL)."""
    path = Path(path)
    if _WIN:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        _restrict_windows(path)
        return path
    old = os.umask(0o077)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    finally:
        os.umask(old)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(data)
    return path


def problems(path: str | Path) -> list[str]:
    """Why `path` is not private enough ([] = fine, or absent)."""
    path = Path(path)
    if not path.exists():
        return []
    if _WIN:
        try:
            extra = acl_sids(path) - {current_user_sid(), SYSTEM_SID}
        except (OSError, subprocess.SubprocessError) as e:
            return [f"{path}: ACL unreadable ({e})"]
        return [f"{path}: readable by {sorted(extra)} (only the user and SYSTEM may be)"] if extra else []
    out = []
    if path.stat().st_mode & 0o077:
        out.append(f"{path}: mode {oct(path.stat().st_mode & 0o777)} (want 0600)")
    if path.parent.stat().st_mode & 0o077:
        out.append(f"{path.parent}: mode {oct(path.parent.stat().st_mode & 0o777)} (want 0700)")
    return out
