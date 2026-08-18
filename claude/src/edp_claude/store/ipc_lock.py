"""Interprocess per-object lock (F34 R2 #1/#2, 2026-08-18).

Every spawned shell runs its OWN MCP server process, so two shells can
execute load-modify-save on the same recipe/plan concurrently. os.replace
makes each individual write atomic (no torn JSON) but does nothing to
serialize WRITERS — the slower saver silently erased the faster one's
mutation, and the events/worklog rollup could rewrite a hot file that
another process had appended to after the rollup's read.

This module provides the one primitive both stores use: an advisory
FILE lock scoped to an object directory. The critical sections are short
(version check + write + append + rollup), so contention is rare and the
timeout generous. Windows uses msvcrt.locking on a dedicated `.lock`
file; POSIX uses fcntl.flock. The lock file itself is never deleted —
deleting a lock file another process holds open is the classic unlock
race, and one empty file per object dir is free.

Reentrant per (process, thread) via a thread-local depth counter keyed
by the lock path, so a save() that triggers rollup_events (which also
locks) cannot deadlock itself.
"""

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_LOCAL = threading.local()

#: seconds to wait for a peer's critical section before giving up.
LOCK_TIMEOUT_DEFAULT = 10.0


class StoreLockTimeout(TimeoutError):
    """A peer process held the object lock past the timeout."""


class StoreConflict(RuntimeError):
    """Optimistic-concurrency failure: the object changed on disk after
    this process loaded it. The caller must re-read and re-apply."""


def _held() -> dict:
    d = getattr(_LOCAL, "held", None)
    if d is None:
        d = _LOCAL.held = {}
    return d


@contextmanager
def object_lock(obj_dir: Path, timeout: float = LOCK_TIMEOUT_DEFAULT):
    """Hold the advisory lock for `obj_dir` (an object's directory).
    Blocks up to `timeout` seconds, then raises StoreLockTimeout.
    Reentrant within the same thread."""
    obj_dir = Path(obj_dir)
    key = str(obj_dir.resolve()) if obj_dir.exists() else str(obj_dir)
    held = _held()
    if held.get(key, 0) > 0:          # reentrant fast path
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return

    obj_dir.mkdir(parents=True, exist_ok=True)
    lock_path = obj_dir / ".lock"
    # open (never delete — see module docstring)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        _acquire(fd, timeout, lock_path)
        held[key] = 1
        try:
            yield
        finally:
            held[key] = 0
            _release(fd)
    finally:
        os.close(fd)


if os.name == "nt":
    import msvcrt

    def _acquire(fd: int, timeout: float, lock_path: Path) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise StoreLockTimeout(
                        f"could not acquire {lock_path} within {timeout}s "
                        "— a peer shell is holding a long write; retry, or "
                        "check for a hung process.")
                time.sleep(0.05)

    def _release(fd: int) -> None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _acquire(fd: int, timeout: float, lock_path: Path) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise StoreLockTimeout(
                        f"could not acquire {lock_path} within {timeout}s "
                        "— a peer shell is holding a long write; retry, or "
                        "check for a hung process.")
                time.sleep(0.05)

    def _release(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
