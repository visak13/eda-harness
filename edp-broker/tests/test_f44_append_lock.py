"""F44#4 — concurrent appends keep every inbox strictly monotonic.

F36 moved store IO to worker threads; the F34 high-water cache assumed
event-loop serialization, so two simultaneous publishes could stamp the
same timestamp and the strict `ts > cursor` reader hid one forever.
"""

import threading
from datetime import datetime, timezone

from edp_broker.store import InboxStore
from edp_contracts import BrokerMessage


def test_concurrent_appends_stay_strictly_monotonic(tmp_path):
    store = InboxStore(tmp_path)
    stale = datetime(2020, 1, 1, tzinfo=timezone.utc)   # far behind any tail
    n_threads, per_thread = 8, 25

    def _publish(t):
        for i in range(per_thread):
            store.append(BrokerMessage(
                msg_id=f"m-{t}-{i}", ts=stale,
                **{"from": f"s{t}"}, to="inbox-x", kind="fyi",
                body={"n": i}))

    threads = [threading.Thread(target=_publish, args=(t,))
               for t in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    msgs = store.read("inbox-x")
    assert len(msgs) == n_threads * per_thread          # nothing lost
    stamps = [m.ts for m in msgs]
    assert all(b > a for a, b in zip(stamps, stamps[1:]))  # strictly rising
    # a strict cursor walk yields every message exactly once
    cursor, seen = None, 0
    while True:
        batch = [m for m in store.read("inbox-x", since=cursor)]
        if not batch:
            break
        seen += len(batch)
        cursor = batch[-1].ts
    assert seen == n_threads * per_thread
