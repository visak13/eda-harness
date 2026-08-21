"""F46#3/#4 — reap joins the transition protocol; driver lifecycle locks.

Reap raced the spawn thread's registration (a reaped launch resurrected
as active with the handle lock re-taken); arm/disarm ran concurrently in
worker threads and could leak an untracked duplicate wake driver.
"""

import threading
import time
from datetime import datetime, timezone

import edp_pool.service as svc_mod
from edp_pool.service import PoolService
from edp_pool.spawner import FakeSpawner


def _row(svc, state, handle="p:a1", sid="worker:test-f46"):
    svc.sessions[sid] = {
        "session_id": sid, "role": "worker", "handle": handle,
        "state": state, "proc": None,
        "spawned_at": datetime.now(timezone.utc).isoformat(),
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }
    svc.locks[handle] = sid
    return sid


# ── #3 — reap vs registration ──────────────────────────────────────────────
def test_reap_defers_on_a_starting_row():
    svc = PoolService(FakeSpawner())
    sid = _row(svc, "starting")
    out = svc.reap("p:a1")
    assert out["reaped"] == sid
    assert "REGISTERING" in out["note"]
    assert svc.sessions[sid]["_release_requested"] is True
    assert svc.sessions[sid]["state"] == "starting"     # row not mutated
    assert svc.locks.get("p:a1") == sid                 # lock kept


def test_reap_releases_an_active_row():
    svc = PoolService(FakeSpawner())
    sid = _row(svc, "active")
    out = svc.reap("p:a1")
    assert out["reaped"] == sid
    assert svc.sessions[sid]["state"] == "done"
    assert "p:a1" not in svc.locks


def test_reap_waits_for_the_transition_lock():
    svc = PoolService(FakeSpawner())
    _row(svc, "active")
    done = threading.Event()

    def _reap():
        svc.reap("p:a1")
        done.set()

    with svc._transition_lock:
        t = threading.Thread(target=_reap)
        t.start()
        time.sleep(0.2)
        assert not done.is_set()          # blocked, not racing
    t.join(timeout=5)
    assert done.is_set()


# ── #4 — the neuron-driver lifecycle is one critical section ───────────────
def test_disarm_blocks_until_a_concurrent_arm_commits(monkeypatch):
    svc = PoolService(FakeSpawner())
    spawned = []

    def _slow_spawn(rid, cmd, hb, broker_url):
        time.sleep(0.3)
        spawned.append(rid)
        return 424242

    monkeypatch.setattr(svc_mod, "spawn_neuron_driver", _slow_spawn)
    armed = threading.Event()

    def _arm():
        svc.arm_neuron_driver("r-drv", "claude -p go")
        armed.set()

    t = threading.Thread(target=_arm)
    t.start()
    time.sleep(0.05)
    # disarm must WAIT for the in-flight arm, then remove the committed row
    # — the unlocked shape returned "no driver was armed" and the arm then
    # committed a driver that "disarm" had already reported gone.
    out = svc.disarm_neuron_driver("r-drv")
    t.join(timeout=5)
    assert armed.is_set()
    assert out["ok"]
    assert "no driver was armed" not in out["note"]
    assert "r-drv" not in svc.neuron_drivers
    assert spawned == ["r-drv"]
