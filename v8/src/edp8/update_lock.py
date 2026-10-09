"""The update lock (s-4d93970c9f item 2): one file, `<home>/update/update.lock`, held from before the seats park to
the update's result. While a live updater holds it, nothing starts services: `heronry start`, the desktop app and
the installers say "an update to X is in progress (step, elapsed)" instead. Automatic: the updater takes and
releases it, the user runs nothing. A lock whose updater pids are all dead is cleared.

Stdlib only, no edp8 imports: the updater copies this file beside update-helper.py, which imports it as `update_lock`.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

LOCK_NAME = "update.lock"
TOKEN_ENV = "HERONRY_UPDATE_TOKEN"  # the updater's own start carries the lock's token and passes the guard


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000 | 0x00100000, False, int(pid))  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def path_for(update_dir: Path) -> Path:
    return Path(update_dir) / LOCK_NAME


def read(update_dir: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path_for(update_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(update_dir: Path, data: dict[str, Any]) -> None:
    p = path_for(update_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def live(data: dict[str, Any] | None) -> bool:
    return bool(data) and any(pid_alive(p) for p in data.get("pids") or [])


def held(update_dir: Path) -> dict[str, Any] | None:
    """The lock when a live updater holds it, else None; a lock whose updater pids are all dead is cleared."""
    data = read(update_dir)
    if data is None:
        return None
    if live(data):
        return data
    try:
        path_for(update_dir).unlink(missing_ok=True)
    except OSError:
        pass
    return None


def acquire(update_dir: Path, *, from_version: str, to_version: str, step: str = "starting") -> dict[str, Any]:
    """Take the lock for this process. Raises RuntimeError when another live updater holds it."""
    cur = held(update_dir)
    if cur is not None and os.getpid() not in cur.get("pids", []):
        raise RuntimeError(describe(cur))
    now = time.time()
    data = {"pids": [os.getpid()], "token": secrets.token_hex(8), "from": from_version, "to": to_version,
            "step": step, "started_at": now, "step_at": now}
    _write(update_dir, data)
    return data


def join(update_dir: Path, token: str | None = None) -> dict[str, Any] | None:
    """Add this process's pid to the lock (the helper joins the caller's lock before the caller exits)."""
    data = read(update_dir)
    if data is None or (token and data.get("token") != token):
        return None
    if os.getpid() not in data["pids"]:
        data["pids"].append(os.getpid())
        _write(update_dir, data)
    return data


def add_pid(update_dir: Path, pid: int) -> None:
    """The caller adds the detached helper's pid as soon as it has it, so the lock stays live even when the caller
    exits before the helper has joined (a lock with only dead pids is cleared by the next `held`)."""
    data = read(update_dir)
    if data is not None and int(pid) not in data["pids"]:
        data["pids"].append(int(pid))
        _write(update_dir, data)


def step(update_dir: Path, name: str) -> None:
    data = read(update_dir)
    if data is None:
        return
    data.update(step=name, step_at=time.time())
    _write(update_dir, data)


PROGRESS_NAME = "update-progress.jsonl"


def format_line(rec: dict[str, Any]) -> str:
    sec = int(rec.get("elapsed") or 0)
    detail = f": {rec['detail']}" if rec.get("detail") else ""
    return f"[{sec // 60}:{sec % 60:02d}] {rec.get('step')}{detail}"


def progress(update_dir: Path, name: str, detail: str = "", *, final: bool = False, echo: bool = False) -> str:
    """One visible step of the update: the lock's step (what a blocked start prints), a line in the progress file the
    window follows, and (echo) the same line on stdout for the CLI. Best effort: progress is never a reason to stop."""
    data = read(update_dir)
    began = float((data or {}).get("started_at") or time.time())
    rec = {"t": time.time(), "elapsed": round(time.time() - began, 1), "step": name, "detail": detail, "final": final}
    try:
        with open(Path(update_dir) / PROGRESS_NAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        if not final:
            step(update_dir, name)
    except OSError:
        pass
    text = format_line(rec)
    if echo:
        print(text, flush=True)
    return text


def reset_progress(update_dir: Path) -> None:
    try:
        (Path(update_dir) / PROGRESS_NAME).unlink(missing_ok=True)
    except OSError:
        pass


def release(update_dir: Path) -> None:
    try:
        path_for(update_dir).unlink(missing_ok=True)
    except OSError:
        pass


def describe(data: dict[str, Any], now: float | None = None) -> str:
    elapsed = int((now or time.time()) - float(data.get("started_at") or 0))
    return (f"an update to {data.get('to')} is in progress ({data.get('step')}, {elapsed // 60}:{elapsed % 60:02d} "
            f"elapsed); wait for it to finish, then run `heronry start` if the services are not up")


def guard(update_dir: Path) -> str | None:
    """None when services may start; else the one line saying an update is in progress. The updater's own
    processes carry the lock's token in the environment and pass."""
    data = held(update_dir)
    if data is None:
        return None
    if os.environ.get(TOKEN_ENV) and os.environ[TOKEN_ENV] == data.get("token"):
        return None
    return describe(data)
