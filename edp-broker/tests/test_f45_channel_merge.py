"""F45#7 — channel membership mutates as an atomic broker-side merge.

The caller-side GET→PUT protocol replayed a member list read moments
earlier, so two concurrent spawn registrations erased each other and the
resume watchdog (which trusts this registry for @all wakes) never woke
the dropped member.
"""

import threading

from edp_broker.store import ChannelStore


def test_merge_adds_against_current_row(tmp_path):
    ch = ChannelStore(tmp_path)
    ch.put("team-x", ["planner"], topic="the brief")
    row = ch.merge("team-x", add=["w1"])
    assert row["members"] == ["planner", "w1"]
    assert row["topic"] == "the brief"                  # topic kept
    row = ch.merge("team-x", remove=["w1"], topic="new brief")
    assert row["members"] == ["planner"]
    assert row["topic"] == "new brief"


def test_merge_creates_missing_channel(tmp_path):
    ch = ChannelStore(tmp_path)
    row = ch.merge("fresh", add=["@operator"])
    assert row["members"] == ["@operator"]


def test_concurrent_merges_lose_no_member(tmp_path):
    ch = ChannelStore(tmp_path)
    n_threads, per_thread = 8, 10

    def _join(t):
        for i in range(per_thread):
            ch.merge("team-y", add=[f"w-{t}-{i}"])

    threads = [threading.Thread(target=_join, args=(t,))
               for t in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    row = ch.get("team-y")
    assert len(row["members"]) == n_threads * per_thread
