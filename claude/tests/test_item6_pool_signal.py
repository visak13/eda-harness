"""Item 6 — pool plane becomes a crash signal, not idle churn.

Locks: rx.pool(states=['dead']) wakes ONLY on dead rows (a scoped pool wake
= a crash, not every spawn/clean-close), and the lock-list is order-canonical
so a remove-then-readd reorder + session_id churn no longer spuriously wakes.
"""
import time

from edp_claude.reactive.driver import RealConfig, RealSources


class _Resp:
    status_code = 200

    def __init__(self, d):
        self._d = d

    def json(self):
        return self._d


def _drive(monkeypatch, snaps, **pool_kw):
    """Run a pool source over a fixed sequence of /v1/locks snapshots and
    return the list of emitted snapshots."""
    idx = {"i": 0}

    def fake_get(url, timeout=10):
        i = min(idx["i"], len(snaps) - 1)
        idx["i"] += 1
        return _Resp(snaps[i])

    monkeypatch.setattr("httpx.get", fake_get)
    sources = RealSources(RealConfig(repo_root=".", poll_ms=15))
    out = []
    sub = sources("pool", **pool_kw).subscribe(on_next=out.append)
    time.sleep(0.30)
    sub.dispose()
    return out


def test_item6_dead_only_filters_and_suppresses_alive_churn(monkeypatch):
    snaps = [
        # two alive shells (a spawn wave) — dead-only sub must stay quiet
        [{"handle": "r:s1", "session_id": "A", "liveness": "alive"},
         {"handle": "r:s2", "session_id": "B", "liveness": "alive"}],
        # reordered same set + session churn — must NOT wake
        [{"handle": "r:s2", "session_id": "B2", "liveness": "alive"},
         {"handle": "r:s1", "session_id": "A", "liveness": "alive"}],
        # s1 CRASHES → the only event a dead-only sub should see
        [{"handle": "r:s1", "session_id": "A", "liveness": "dead"},
         {"handle": "r:s2", "session_id": "B", "liveness": "alive"}],
    ]
    out = _drive(monkeypatch, snaps, scope="r", states=["dead"])
    # exactly the crash surfaced; the alive spawn-wave + reorder were suppressed
    assert out, "dead-only sub never emitted the crash"
    # F3b: emissions are {snapshot, changed} envelopes
    flat = [row for e in out for row in e["snapshot"]]
    assert flat and all(r["liveness"] == "dead" for r in flat), out
    assert any(r["handle"] == "r:s1" for r in flat), out


def test_item6_reorder_and_session_churn_do_not_wake_default_sub(monkeypatch):
    snaps = [
        [{"handle": "r:s1", "session_id": "A", "liveness": "alive"},
         {"handle": "r:s2", "session_id": "B", "liveness": "alive"}],
        # SAME liveness set, reordered + new session ids — canonical → no emit
        [{"handle": "r:s2", "session_id": "Z", "liveness": "alive"},
         {"handle": "r:s1", "session_id": "Y", "liveness": "alive"}],
    ]
    out = _drive(monkeypatch, snaps, scope="r")
    # only the first real snapshot; the reorder/session churn added no wake
    assert len(out) == 1, out
