"""S14 (pains p-ed42a7ed, p-c62029db): the pool never kills a quiet seat, and every death names itself.

A real private pool (own port, own state, stub harness as the claude bin, dead broker). Nothing here touches the
fleet's pool, board or broker.
"""
from __future__ import annotations

import time

import httpx
from edp_contracts.proc import ProcId, kill_tree

from test_s14_force_quit_no_relaunch import (HANDLES, _free_port, _rows, _spawn_three, _start_pool, kill_ours,  # noqa: F401
                                             no_survivors)


def _wait(pred, secs=30.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        got = pred()
        if got:
            return got
        time.sleep(0.5)
    return None


def test_a_quiet_seat_is_never_killed_and_every_death_carries_a_reason(tmp_path):
    pool, pool_id, base, log = _start_pool(tmp_path, _free_port(), "a")
    try:
        _spawn_three(base)
        time.sleep(10)  # quiet: the shells emit nothing; the retired s26 reaper killed a seat after 120 s of this
        assert {r["handle"]: r["state"] for r in _rows(base)} == {h: "active" for h in HANDLES}
        by = {r["handle"]: r for r in _rows(base)}
        # a self-close names itself
        r = httpx.post(f"{base}/v1/release/{by[HANDLES[0]]['session_id']}",
                       json={"reason": "closed by self: done"}, timeout=30)
        assert r.status_code == 200
        # a crash (the shell's process tree killed from outside) is labelled as one, never blank
        kill_ours(ProcId.of(int(by[HANDLES[1]]["proc"]["pid"])), grace=0.0)
        httpx.post(f"{base}/v1/spawn", json={"role": "worker", "handle": "stub:fq4", "mode": "headless"},
                   timeout=90)  # a spawn counts capacity, which reconciles the row the shell left behind
        crashed = _wait(lambda: next((x for x in _rows(base)
                                      if x["handle"] == HANDLES[1] and x["state"] != "active"), None))
        assert crashed is not None, "the killed seat was never marked dead"
        done = next(x for x in _rows(base) if x["handle"] == HANDLES[0])
        assert done["state"] == "done" and done["dead_reason"].startswith("closed by self"), done
        assert crashed["dead_reason"] and "without close_self" in crashed["dead_reason"], crashed
        # the untouched seat is still alive
        assert next(x for x in _rows(base) if x["handle"] == HANDLES[2])["state"] == "active"
        # there is no idle reaper to arm any more
        assert httpx.post(f"{base}/v1/close_when_idle/{by[HANDLES[2]]['session_id']}", timeout=10).status_code == 404
    finally:
        kill_ours(pool_id, grace=2.0)
