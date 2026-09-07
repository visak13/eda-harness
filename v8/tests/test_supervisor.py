"""S17 — the launcher supervises the services it started (design §22).

The decision core is driven with injected prober/alive/restart/emit so no real process is
needed: a pool whose listener is closed while its process lives is restarted within the 60s
budget; a slow-but-answering service is never restarted; a single miss never restarts.
"""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8 import run_state
from edp8.supervisor import PROBE_INTERVAL, Supervisor


@pytest.fixture(autouse=True)
def isolate_run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path / "run"))


def _sup(services, probe, alive, threshold=3):
    calls = {"restart": [], "emit": []}
    s = Supervisor(services, probe=probe, alive=alive,
                   restart=lambda svc, reason: calls["restart"].append((svc, reason)),
                   emit=lambda svc, reason: calls["emit"].append((svc, reason)),
                   threshold=threshold)
    return s, calls


def test_alive_without_listener_is_restarted_within_60s():
    run_state.write("pool", pid=os.getpid(), port=9301, git_rev="abc")
    s, calls = _sup(["pool"], probe=lambda svc: False, alive=lambda svc: True)
    # 15s ticks: three failed probes reach threshold at t=30s (ticks 1,2,3) — within 60s.
    ticks = 0
    while not calls["restart"] and ticks < 5:
        s.tick()
        ticks += 1
    assert calls["restart"], "listener-closed-while-alive pool was never restarted"
    assert ticks * PROBE_INTERVAL <= 60
    svc, reason = calls["restart"][0]
    assert svc == "pool" and "listener" in reason
    assert calls["emit"] == [("pool", reason)]  # the service_restarted event is posted


def test_slow_but_answering_is_not_restarted():
    """A service that answers (even slowly, within the 5s probe timeout) is never restarted."""
    run_state.write("board", pid=os.getpid(), port=9400, git_rev="abc")
    s, calls = _sup(["board"], probe=lambda svc: True, alive=lambda svc: True)
    for _ in range(6):
        s.tick()
    assert calls["restart"] == []


def test_single_miss_does_not_restart():
    run_state.write("broker", pid=os.getpid(), port=9300, git_rev="abc")
    seq = iter([False, True, True, True])
    s, calls = _sup(["broker"], probe=lambda svc: next(seq), alive=lambda svc: True)
    for _ in range(4):
        s.tick()
    assert calls["restart"] == []


def test_dead_process_reason_is_failed_probes():
    run_state.write("mcp", pid=os.getpid(), port=9402, git_rev="abc")
    s, calls = _sup(["mcp"], probe=lambda svc: False, alive=lambda svc: False, threshold=3)
    for _ in range(3):
        s.tick()
    assert calls["restart"] and "consecutive failed probes" in calls["restart"][0][1]


def test_run_state_roundtrip_and_snapshot():
    run_state.write("pool", pid=os.getpid(), port=9301, git_rev="deadbeef")
    run_state.mark_probe("pool", True)
    run_state.mark_restart("pool", "test reason", git_rev="feedface")
    rec = run_state.read("pool")
    assert rec["git_rev"] == "feedface" and rec["last_restart_reason"] == "test reason" and rec["restarts"] == 1
    snap = {r["service"]: r for r in run_state.snapshot()}
    assert set(snap) == set(run_state.SERVICES)  # a row per known service, even the ones never started
    assert snap["pool"]["state"] == "up"  # our own pid is alive
    assert snap["board"]["state"] == "down"  # never written
