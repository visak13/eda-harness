"""S8 — the cross-process inference admission lane (epic-6a8a6020fd)."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path

from edp8 import admission
from edp8.admission import PRIO_HUMAN, PRIO_SEAT, Lane


def test_single_holder_and_fifo(tmp_path):
    lane = Lane(tmp_path)
    a = lane.acquire("a", max_wait_s=1)
    assert a and lane.holder()["holder"] == "a"
    assert lane.acquire("b", max_wait_s=0.6) is None  # bounded wait, no throw
    assert lane.waiting() == []  # b's ticket is gone after giving up
    a.release()
    assert lane.holder() is None
    b = lane.acquire("b", max_wait_s=1)
    assert b and lane.holder()["holder"] == "b"
    b.release()


def test_priority_beats_fifo(tmp_path):
    lane = Lane(tmp_path)
    hold = lane.acquire("hold", max_wait_s=1)
    order: list[str] = []

    def waiter(name, prio):
        lease = lane.acquire(name, priority=prio, max_wait_s=10)
        order.append(name)
        time.sleep(0.05)
        lease.release()

    import threading

    t_seat = threading.Thread(target=waiter, args=("seat", PRIO_SEAT))
    t_seat.start()
    time.sleep(0.3)
    t_human = threading.Thread(target=waiter, args=("human", PRIO_HUMAN))
    t_human.start()
    time.sleep(0.3)
    hold.release()
    t_seat.join(5)
    t_human.join(5)
    assert order == ["human", "seat"]


def test_stale_lock_is_reclaimed(tmp_path, monkeypatch):
    lane = Lane(tmp_path)
    a = lane.acquire("dead", max_wait_s=1)
    assert a
    old = time.time() - 3600
    os.utime(lane.lock, (old, old))
    monkeypatch.setattr(admission, "LOCK_TTL_S", 60)
    assert lane.stale()
    b = lane.acquire("alive", max_wait_s=1)
    assert b and lane.holder()["holder"] == "alive"
    a.release()  # the dead holder's late release must NOT remove alive's lock
    assert lane.holder()["holder"] == "alive"
    b.release()


def test_cross_process(tmp_path):
    """Two OS processes: the second blocks until the first releases (real lane use: consult vs seat)."""
    code = (
        "import sys,time;from edp8.admission import Lane;l=Lane(sys.argv[1]);"
        "x=l.acquire(sys.argv[2],max_wait_s=10);print('got',time.time(),flush=True);time.sleep(float(sys.argv[3]));x.release();print('rel',time.time(),flush=True)"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    p1 = subprocess.Popen([sys.executable, "-c", code, str(tmp_path), "p1", "1.5"], stdout=subprocess.PIPE, text=True, env=env)
    time.sleep(0.5)
    p2 = subprocess.Popen([sys.executable, "-c", code, str(tmp_path), "p2", "0"], stdout=subprocess.PIPE, text=True, env=env)
    o1, _ = p1.communicate(timeout=20)
    o2, _ = p2.communicate(timeout=20)
    rel1 = float(o1.split("rel ")[1])
    got2 = float(o2.split("got ")[1].split()[0])
    assert got2 >= rel1 - 0.01
    assert Lane(tmp_path).holder() is None and Lane(tmp_path).waiting() == []


def test_consult_uses_the_shared_lane(tmp_path, monkeypatch):
    """consult() must hold the file lane while running, so a seat's turn queues behind it."""
    from edp8 import consult

    monkeypatch.setenv("EDP8_SOL_LOG_DIR", str(tmp_path))
    seen: dict = {}

    def fake_locked(*a, **k):
        seen["holder"] = Lane(tmp_path).holder()
        return {"ok": True, "value": {"answer": "x"}}

    monkeypatch.setattr(consult, "_consult_locked", fake_locked)
    monkeypatch.setattr(consult, "_resolve_bin", lambda: "codex")
    out = consult.consult("second_opinion", "q")
    assert out["ok"] and seen["holder"] and seen["holder"]["holder"].startswith("consult:")
    assert Lane(tmp_path).holder() is None  # released in finally
