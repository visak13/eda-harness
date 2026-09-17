"""admission — ONE cross-process inference lane for the OpenAI login (consult.py + resident seats).

Design design-97ca02e989 §8 S8 [Astra]: the consult lane was a process-local `threading.Lock`,
so a separate Astra seat could not take part; residency and inference capacity are different
resources, so a seat acquires PER TURN (per provider request), never for its lifetime.

Protocol (cross-language, no fcntl/msvcrt so the Pi extension can implement it byte-for-byte):
  <dir>/lane.queue/<prio>-<ts_ms>-<holder>.json   a waiting ticket; the WAITER TOUCHES IT every poll —
                                                   a ticket not touched for QUEUE_STALE_S is dead and any
                                                   waiter removes it (qa A3: a killed waiter must not block
                                                   the lane forever)
  <dir>/lane.lock/                                 the lock: `mkdir` is atomic on every OS; holder.json inside
                                                   carries a UNIQUE lease_id + ttl_s; mtime refreshed by
                                                   `touch()`; older than its ttl → stale, reclaimable
  <dir>/quota.json                                 consult.py's block record {"blocked_until", "evidence", "seen_at"}
Ordering: tickets sort by (effective priority, ts): "0" beats "1", FIFO within; a ticket that has waited
AGING_S sorts as priority 0 so a stream of consults cannot starve a seat (qa A3).
A waiter takes the lock only when its ticket is first and the lock dir does not exist (or is stale).
Bounded wait → `None` (caller decides: consult returns "lane busy", a seat FAILS CLOSED — qa A2).
Release removes the lock only when holder.json carries this lease's id (qa A4: a reclaimed-as-stale
lease never deletes its replacement's lock; an unreadable holder.json is left for the TTL).
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
QUEUE_STALE_S = float(os.environ.get("EDP8_LANE_QUEUE_STALE_S", "10"))  # a waiter touches its ticket every POLL_S
AGING_S = float(os.environ.get("EDP8_LANE_AGING_S", "120"))  # a ticket this old outranks fresh lower-priority ones
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
    lease_id: str = ""

    def touch(self) -> None:
        try:
            os.utime(self.dir / "lane.lock", None)
        except OSError:
            pass

    def release(self) -> None:
        lock = self.dir / "lane.lock"
        try:
            info = json.loads((lock / "holder.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # replacement holder mid-write, or already gone — never remove what we cannot prove is ours
        if info.get("lease_id") != self.lease_id:
            return  # not ours any more (reclaimed as stale) — never remove another holder's lock
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
            age = time.time() - self.lock.stat().st_mtime
        except OSError:
            return False
        h = self.holder() or {}
        ttl = h.get("ttl_s") if isinstance(h.get("ttl_s"), (int, float)) else LOCK_TTL_S
        return age > ttl

    def waiting(self) -> list[str]:
        """Live tickets in service order (effective priority, then FIFO); dead tickets are removed."""
        try:
            names = [p.name for p in self.queue.iterdir() if p.suffix == ".json"]
        except OSError:
            return []
        now = time.time()
        live: list[tuple[str, str, str]] = []
        for n in names:
            try:
                mtime = (self.queue / n).stat().st_mtime
            except OSError:
                continue
            if now - mtime > QUEUE_STALE_S:
                try:
                    (self.queue / n).unlink()
                except OSError:
                    pass
                continue
            prio, ts = n.split("-")[:2]
            try:
                eff = "0" if now * 1000 - float(ts) >= AGING_S * 1000 else prio
            except ValueError:
                eff = prio
            live.append((eff, ts, n))
        return [n for _, _, n in sorted(live)]

    def status(self) -> dict:
        h = self.holder()
        return {"holder": h, "stale": bool(h) and self.stale(), "waiting": self.waiting(), "ttl_s": LOCK_TTL_S}

    # ---------------------------------------------------------------- acquire / release
    def acquire(self, holder: str, *, priority: int = PRIO_SEAT, max_wait_s: float = 600,
                ttl_s: float | None = None) -> Lease | None:
        """`ttl_s`: how long this holder may go without `touch()` before others reclaim the lock —
        a consult passes its own timeout so a long run is never reclaimed under it (qa A4)."""
        self.queue.mkdir(parents=True, exist_ok=True)
        ticket = self.queue / f"{priority}-{int(time.time() * 1000):013d}-{uuid.uuid4().hex[:6]}.json"
        ticket.write_text(json.dumps({"holder": holder, "priority": priority, "queued_at": _now(), "pid": os.getpid()}), encoding="utf-8")
        deadline = time.time() + max_wait_s
        lease_id = uuid.uuid4().hex
        try:
            while True:
                try:
                    os.utime(ticket, None)  # liveness: a ticket that stops being touched is dead
                except OSError:
                    pass
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
                            json.dumps({"holder": holder, "lease_id": lease_id, "priority": priority, "since": _now(),
                                        "pid": os.getpid(), "ttl_s": ttl_s if ttl_s is not None else LOCK_TTL_S}),
                            encoding="utf-8")
                        return Lease(self.dir, holder, ticket, time.time(), lease_id)
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
