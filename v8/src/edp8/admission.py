"""admission — ONE cross-process inference lane for the OpenAI login (consult.py + resident seats).

Design design-97ca02e989 §8 S8 [Astra]: the consult lane was a process-local `threading.Lock`,
so a separate Astra seat could not take part; residency and inference capacity are different
resources, so a seat acquires PER TURN (per provider request), never for its lifetime.

Protocol (cross-language, no fcntl/msvcrt so the Pi extension can implement it byte-for-byte):
  <dir>/lane.queue/<prio>-<ts_ms>-<holder>.json   a waiting ticket (prio "0" beats "1"); FIFO within prio
  <dir>/lane.lock/                                 the lock: `mkdir` is atomic on every OS; holder.json inside,
                                                   mtime refreshed by `touch()`; older than TTL → stale, reclaimable
  <dir>/quota.json                                 consult.py's block record {"blocked_until", "evidence", "seen_at"}
A waiter takes the lock only when its ticket is the first in the queue and the lock dir does not exist
(or is stale). Bounded wait → `None` (caller decides: consult returns "lane busy", a seat retries next tick).
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

LOCK_TTL_S = int(os.environ.get("EDP8_LANE_TTL_S", "900"))  # a holder that stops touching for 15 min is dead
POLL_S = 0.25
PRIO_HUMAN = 0  # consult() on behalf of a seat that is answering a human
PRIO_SEAT = 1  # a resident seat's own turn / a routine consult


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Lease:
    dir: Path
    holder: str
    ticket: Path
    acquired_at: float

    def touch(self) -> None:
        try:
            os.utime(self.dir / "lane.lock", None)
        except OSError:
            pass

    def release(self) -> None:
        lock = self.dir / "lane.lock"
        try:
            info = json.loads((lock / "holder.json").read_text(encoding="utf-8"))
            if info.get("holder") != self.holder:
                return  # not ours any more (reclaimed as stale) — never remove another holder's lock
        except (OSError, ValueError):
            pass
        shutil.rmtree(lock, ignore_errors=True)


class Lane:
    def __init__(self, dir: str | os.PathLike[str]) -> None:
        self.dir = Path(dir)
        self.queue = self.dir / "lane.queue"
        self.lock = self.dir / "lane.lock"

    # ---------------------------------------------------------------- state
    def holder(self) -> dict | None:
        try:
            info = json.loads((self.lock / "holder.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None if not self.lock.is_dir() else {"holder": "?", "since": None}
        return info

    def stale(self) -> bool:
        try:
            return time.time() - self.lock.stat().st_mtime > LOCK_TTL_S
        except OSError:
            return False

    def waiting(self) -> list[str]:
        try:
            return sorted(p.name for p in self.queue.iterdir() if p.suffix == ".json")
        except OSError:
            return []

    def status(self) -> dict:
        h = self.holder()
        return {"holder": h, "stale": bool(h) and self.stale(), "waiting": self.waiting(), "ttl_s": LOCK_TTL_S}

    # ---------------------------------------------------------------- acquire / release
    def acquire(self, holder: str, *, priority: int = PRIO_SEAT, max_wait_s: float = 600) -> Lease | None:
        self.queue.mkdir(parents=True, exist_ok=True)
        ticket = self.queue / f"{priority}-{int(time.time() * 1000):013d}-{uuid.uuid4().hex[:6]}.json"
        ticket.write_text(json.dumps({"holder": holder, "priority": priority, "queued_at": _now()}), encoding="utf-8")
        deadline = time.time() + max_wait_s
        try:
            while True:
                first = self.waiting()[:1]
                if first and first[0] == ticket.name:
                    if self.lock.is_dir() and self.stale():
                        shutil.rmtree(self.lock, ignore_errors=True)
                    try:
                        self.lock.mkdir()
                    except FileExistsError:
                        pass
                    else:
                        (self.lock / "holder.json").write_text(
                            json.dumps({"holder": holder, "priority": priority, "since": _now(), "pid": os.getpid()}), encoding="utf-8")
                        return Lease(self.dir, holder, ticket, time.time())
                if time.time() >= deadline:
                    return None
                time.sleep(POLL_S)
        finally:
            try:
                ticket.unlink(missing_ok=True)
            except OSError:
                pass


def lane_dir_from_env(default: Path) -> Path:
    override = os.environ.get("EDP8_LANE_DIR", "").strip()
    return Path(override) if override else default
