"""RC2 gate, t-fb8b63874e: log every Restart Manager return code on an install folder while an update runs.

    python gate_rm_probe.py <install dir> <out.jsonl> <stop file> [--every 1.0]

The same calls as update_helper.holders() (RmStartSession, RmRegisterResources per 1000 files, RmGetList twice),
images-only like the helper's poll, one JSON line per look until <stop file> exists. Read-only: it registers files
and lists holders; it never calls RmShutdown and changes nothing.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone


class _Unique(ctypes.Structure):
    _fields_ = [("pid", wintypes.DWORD), ("start", wintypes.FILETIME)]


class _Info(ctypes.Structure):
    _fields_ = [("proc", _Unique), ("app", wintypes.WCHAR * 256), ("svc", wintypes.WCHAR * 64),
                ("type", ctypes.c_int), ("status", wintypes.ULONG), ("ts", wintypes.DWORD),
                ("restartable", wintypes.BOOL)]


def look(folder: str, images_only: bool = True) -> dict:
    t0 = time.monotonic()
    files = [os.path.join(d, f) for d, _, fs in os.walk(folder) for f in fs
             if not images_only or f.lower().endswith((".exe", ".dll", ".pyd"))]
    rm = ctypes.WinDLL("rstrtmgr")
    sess, key = wintypes.DWORD(), ctypes.create_unicode_buffer(64)
    out: dict = {"at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "files": len(files)}
    out["start_rc"] = rm.RmStartSession(ctypes.byref(sess), 0, key)
    if out["start_rc"]:
        return out
    try:
        out["register_rcs"] = []
        for i in range(0, len(files), 1000):
            chunk = files[i:i + 1000]
            arr = (ctypes.c_wchar_p * len(chunk))(*chunk)
            out["register_rcs"].append(rm.RmRegisterResources(sess, len(chunk), arr, 0, None, 0, None))
        need, count, why = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
        out["list1_rc"] = rm.RmGetList(sess, ctypes.byref(need), ctypes.byref(count), None, ctypes.byref(why))
        out["list1_need"] = need.value
        if out["list1_rc"] == 234:
            info = (_Info * need.value)()
            count = wintypes.UINT(need.value)
            out["list2_rc"] = rm.RmGetList(sess, ctypes.byref(need), ctypes.byref(count), info, ctypes.byref(why))
            out["list2_need"] = need.value
            if out["list2_rc"] == 0:
                out["holders"] = [f"{info[k].app or '?'} (pid {info[k].proc.pid})" for k in range(count.value)]
    finally:
        out["end_rc"] = rm.RmEndSession(sess)
        out["secs"] = round(time.monotonic() - t0, 2)
    return out


def main(argv: list[str]) -> int:
    folder, out, stop = argv[0], argv[1], argv[2]
    every = float(argv[argv.index("--every") + 1]) if "--every" in argv else 1.0
    with open(out, "a", encoding="utf-8") as f:
        while not os.path.exists(stop):
            try:
                rec = look(folder) if os.path.isdir(folder) else {"at": datetime.now(timezone.utc).isoformat(),
                                                                  "missing": folder}
            except OSError as e:
                rec = {"at": datetime.now(timezone.utc).isoformat(), "error": str(e)}
            f.write(json.dumps(rec) + "\n")
            f.flush()
            time.sleep(every)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
