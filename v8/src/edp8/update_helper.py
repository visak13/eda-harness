"""The detached update helper (strategyhl-86b4805322 §4 steps 4-7; S3 s-870e401942).

`heronry update` copies this file into the private run dir and starts it with the base interpreter,
outside the tool venv, then exits: `uv tool install --force` cannot replace a venv any live process has
loaded (measured os error 32). This file is stdlib-only for that reason and imports nothing from edp8.

Plan (JSON, written by the updater): ``caller_pid``, ``install_argv``, ``rollback_install_argv`` (or
null), ``start_argv``, ``stop_argv``, ``health_url``, ``db``, ``backup``, ``log``, ``result``,
``from_version``, ``to_version``. Steps: wait for the caller to exit → install → start → health; any
failure → stop, reinstall the previous artefacts when cached, restore the pre-update DB backup, start.
The outcome is written to ``result`` (``ok`` | ``rolled_back`` | ``failed``) and every step to ``log``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def _log(plan: dict, text: str) -> None:
    with open(plan["log"], "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(UTC).isoformat(timespec='seconds')} {text}\n")


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000 | 0x00100000, False, pid)  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _run(plan: dict, what: str, argv: list[str] | None, timeout: float = 900.0) -> bool:
    if not argv:
        return True
    _log(plan, f"{what}: {' '.join(argv)}")
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        _log(plan, f"{what} failed: {e}")
        return False
    for line in (r.stdout + r.stderr).splitlines()[-40:]:
        _log(plan, f"  | {line}")
    _log(plan, f"{what} exit {r.returncode}")
    return r.returncode == 0


def _healthy(url: str, wait_s: float = 90.0) -> bool:
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310 — loopback URL from our own plan
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1.0)
    return False


def _restore(plan: dict) -> None:
    db, backup = Path(plan["db"]), Path(plan["backup"])
    for side in ("-wal", "-shm"):
        db.with_name(db.name + side).unlink(missing_ok=True)
    shutil.copy2(backup, db)
    _log(plan, f"restored {db} from {backup}")


def main(plan_path: str) -> int:
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    result = {"from": plan["from_version"], "to": plan["to_version"], "state": "failed", "reason": ""}

    def finish(state: str, reason: str = "") -> int:
        result.update(state=state, reason=reason, finished_at=datetime.now(UTC).isoformat(timespec="seconds"))
        Path(plan["result"]).write_text(json.dumps(result, indent=1), encoding="utf-8")
        _log(plan, f"result {state} {reason}".rstrip())
        return 0 if state == "ok" else 1

    _log(plan, f"helper up (pid {os.getpid()}): {plan['from_version']} -> {plan['to_version']}")
    deadline = time.monotonic() + 120.0
    while _pid_alive(int(plan["caller_pid"])) and time.monotonic() < deadline:
        time.sleep(0.3)
    if _pid_alive(int(plan["caller_pid"])):
        return finish("failed", "the heronry process that started the update did not exit; nothing was changed")

    reason = ""
    if not _run(plan, "install", plan["install_argv"]):
        reason = "install failed"
    elif not _run(plan, "start", plan["start_argv"], timeout=300) or not _healthy(plan["health_url"]):
        reason = "the new version did not come up healthy"
    if not reason:
        return finish("ok")

    _log(plan, f"rolling back: {reason}")
    _run(plan, "stop", plan["stop_argv"], timeout=300)
    note = ""
    if plan.get("rollback_install_argv"):
        if not _run(plan, "reinstall previous", plan["rollback_install_argv"]):
            note = "; reinstalling the previous version failed"
    elif reason != "install failed":
        note = "; the previous version's artefacts were not cached, reinstall it with the install script"
    _restore(plan)
    if _run(plan, "start previous", plan["start_argv"], timeout=300) and _healthy(plan["health_url"]):
        return finish("rolled_back", reason + note)
    return finish("failed", reason + note + "; the rollback did not come up either")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
