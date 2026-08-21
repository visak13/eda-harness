"""F45#6 — a starting-row release is part of the registration transition.

release() used to read/flag the starting row WITHOUT _transition_lock, so
a shell's fast pool_close_self could set _release_requested on the old row
after registration (holding the lock) had read it as false but before it
replaced the row — the flag vanished and the closed shell stayed active.
"""

import threading
import time
from datetime import datetime, timezone

from edp_pool.service import PoolService
from edp_pool.spawner import FakeSpawner


def _starting(svc, handle="p:a1", sid="worker:test-rel"):
    svc.sessions[sid] = {
        "session_id": sid, "role": "worker", "handle": handle,
        "state": "starting", "proc": None,
        "spawned_at": datetime.now(timezone.utc).isoformat(),
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }
    svc.locks[handle] = sid
    return sid


def test_starting_release_waits_for_the_transition_lock():
    svc = PoolService(FakeSpawner())
    sid = _starting(svc)
    done = threading.Event()

    def _release():
        svc.release(sid)
        done.set()

    with svc._transition_lock:            # registration's critical section
        t = threading.Thread(target=_release)
        t.start()
        time.sleep(0.2)
        # the release must BLOCK — the old shape flagged the row mid-window
        assert not done.is_set()
        assert not svc.sessions[sid].get("_release_requested")
    t.join(timeout=5)
    assert done.is_set()
    assert svc.sessions[sid]["_release_requested"] is True


def test_starting_release_flags_row_when_uncontended():
    svc = PoolService(FakeSpawner())
    sid = _starting(svc)
    svc.release(sid)
    assert svc.sessions[sid]["_release_requested"] is True
    assert svc.sessions[sid]["state"] == "starting"      # row not replaced
    assert svc.locks.get("p:a1") == sid                  # lock kept for reg
