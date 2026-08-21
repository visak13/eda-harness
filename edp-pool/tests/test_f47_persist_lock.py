"""F47#2 — pool state snapshots serialize under one persist lock.

Mutators persist under DIFFERENT domain locks (_transition_lock,
_driver_lock) or none, so a slow writer could serialize a stale snapshot
and replace a newer one after it landed — durably resurrecting, e.g., a
successfully disarmed neuron driver on the next pool restart.
"""

import json
import threading
import time

from edp_pool.service import PoolService
from edp_pool.spawner import FakeSpawner


def _svc(tmp_path):
    svc = PoolService(FakeSpawner())
    svc.state_path = tmp_path / "pool_state.json"
    return svc


def test_persist_blocks_on_the_persist_lock(tmp_path):
    svc = _svc(tmp_path)
    done = threading.Event()

    def _persist():
        svc._persist()
        done.set()

    with svc._persist_lock:
        t = threading.Thread(target=_persist)
        t.start()
        time.sleep(0.2)
        assert not done.is_set()          # snapshot+replace waits its turn
    t.join(timeout=5)
    assert done.is_set()


def test_final_snapshot_reflects_final_state(tmp_path):
    svc = _svc(tmp_path)

    def _mutate(t):
        for i in range(20):
            svc.neuron_drivers[f"r-{t}"] = {"pid": i}
            svc._persist()
        del svc.neuron_drivers[f"r-{t}"]
        svc._persist()

    threads = [threading.Thread(target=_mutate, args=(t,))
               for t in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    on_disk = json.loads(svc.state_path.read_text(encoding="utf-8"))
    # every thread removed its driver LAST — a stale-snapshot replace
    # would resurrect one into the durable file
    assert on_disk["neuron_drivers"] == {}
