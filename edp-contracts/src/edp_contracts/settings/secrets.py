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
    """The SIDs holding any access entry on `path`'s DACL (Windows), read through the Win32 security API
    (no powershell in a runtime path, S2 s-b7ec13d748). Raises OSError when the DACL cannot be read."""
    import ctypes
    from ctypes import wintypes

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
                                          ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                          ctypes.POINTER(ctypes.c_void_p)]
    adv.GetNamedSecurityInfoW.restype = wintypes.DWORD
    adv.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    adv.GetAce.restype = wintypes.BOOL
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    adv.ConvertSidToStringSidW.restype = wintypes.BOOL
    k32.LocalFree.argtypes = [ctypes.c_void_p]

    class _Acl(ctypes.Structure):
        _fields_ = [("AclRevision", ctypes.c_ubyte), ("Sbz1", ctypes.c_ubyte), ("AclSize", ctypes.c_ushort),
                    ("AceCount", ctypes.c_ushort), ("Sbz2", ctypes.c_ushort)]

    class _AceHeader(ctypes.Structure):
        _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte), ("AceSize", ctypes.c_ushort)]

    se_file_object, dacl_info = 1, 0x4
    dacl, sd = ctypes.c_void_p(), ctypes.c_void_p()
    rc = adv.GetNamedSecurityInfoW(str(path), se_file_object, dacl_info, None, None, ctypes.byref(dacl), None,
                                   ctypes.byref(sd))
    if rc != 0:
        raise OSError(rc, f"GetNamedSecurityInfoW failed for {path}")
    try:
        out: set[str] = set()
        if not dacl.value:
            return {"S-1-1-0"}  # a NULL DACL grants everyone access
        count = _Acl.from_address(dacl.value).AceCount
        for i in range(count):
            ace = ctypes.c_void_p()
            if not adv.GetAce(dacl, i, ctypes.byref(ace)):
                raise OSError(ctypes.get_last_error(), f"GetAce {i} failed for {path}")
            # ACCESS_ALLOWED/DENIED(_CALLBACK) aces: header, ACCESS_MASK, then the SID
            if _AceHeader.from_address(ace.value).AceType not in (0, 1, 9, 10):
                continue
            sid_str = wintypes.LPWSTR()
            if not adv.ConvertSidToStringSidW(ace.value + ctypes.sizeof(_AceHeader) + 4, ctypes.byref(sid_str)):
                raise OSError(ctypes.get_last_error(), f"ConvertSidToStringSidW failed for {path}")
            out.add(sid_str.value)
            k32.LocalFree(sid_str)
        return out
    finally:
        k32.LocalFree(sd)


def _restrict_windows(path: Path) -> None:
    """REPLACE the DACL with a protected one: the current user + SYSTEM, full control, nothing else.

    Not `icacls /inheritance:r /grant:r`: that drops inherited aces and re-grants the two SIDs but KEEPS
    every other explicit ace, and an elevated creator's new file carries explicit OWNER RIGHTS (S-1-3-4) and
    Administrators (S-1-5-32-544) aces (GitHub's windows runner, CI run 36323612069)."""
    import ctypes
    from ctypes import wintypes

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    adv.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    adv.SetFileSecurityW.restype = wintypes.BOOL
    k32.LocalFree.argtypes = [ctypes.c_void_p]

    sddl = f"D:P(A;;FA;;;{current_user_sid()})(A;;FA;;;{SYSTEM_SID})"
    sd = ctypes.c_void_p()
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd), None):
        raise OSError(ctypes.get_last_error(), f"cannot build the private ACL for {path}")
    try:
        dacl_info, protected_dacl = 0x4, 0x80000000
        if not adv.SetFileSecurityW(str(path), dacl_info | protected_dacl, sd):
            raise OSError(ctypes.get_last_error(), f"SetFileSecurityW failed for {path}")
    finally:
        k32.LocalFree(sd)


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
