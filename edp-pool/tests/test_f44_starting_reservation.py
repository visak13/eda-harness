"""F44#5 — a `starting` reservation is an occupied handle, not a corpse.

A concurrent same-handle spawn used to probe the pid-less starting row as
dead, reap its lock mid-launch, and double-dispatch the work. Fresh
reservations now refuse; only one aged past the grace is recoverable.
"""

from datetime import datetime, timedelta, timezone

from edp_pool.service import PoolService
from edp_pool.spawner import FakeSpawner


def _iso(dt):
    return dt.isoformat()


def _reserve(svc, handle, age_secs):
    sid = "worker:test-res"
    svc.sessions[sid] = {
        "session_id": sid, "role": "worker", "handle": handle,
        "state": "starting", "proc": None,
        "spawned_at": _iso(datetime.now(timezone.utc)
                           - timedelta(seconds=age_secs)),
        "last_seen": _iso(datetime.now(timezone.utc)),
    }
    svc.locks[handle] = sid
    return sid


def test_fresh_starting_reservation_refuses_concurrent_spawn():
    svc = PoolService(FakeSpawner())
    _reserve(svc, "p:a1", age_secs=5)
    res = svc._admit_handle_locked("p:a1")
    assert res is not None
    assert "in flight" in res.message
    assert svc.locks.get("p:a1") == "worker:test-res"   # lock NOT stolen


def test_abandoned_starting_reservation_is_recoverable():
    svc = PoolService(FakeSpawner())
    _reserve(svc, "p:a1", age_secs=600)                 # past the 180s grace
    res = svc._admit_handle_locked("p:a1")
    assert res is None                                  # reaped, admitted
    assert "p:a1" not in svc.locks


def test_unreadable_reservation_age_stays_occupied():
    svc = PoolService(FakeSpawner())
    sid = _reserve(svc, "p:a1", age_secs=5)
    svc.sessions[sid]["spawned_at"] = "not-a-timestamp"
    res = svc._admit_handle_locked("p:a1")
    assert res is not None and "in flight" in res.message
