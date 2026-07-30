"""DESIGN-v7 1.2 — the capacity model split into three named knobs.

EDP_MAX_WORKERS (6) and EDP_MAX_PLANNERS (4) are per-role throughput caps;
EDP_MAX_TOTAL_SHELLS (10) is the true all-roles resource guard. Reviewers
are exempt from the per-role caps (count under total only) so a review leg
can never eat a builder slot — the DESIGN-v6 "~2 effective builders" bug.
Every refusal must NAME its env knob: the operator's fix is one env var.
"""

import pytest

from edp_pool.service import PoolService
from edp_pool.spawner import FakeSpawner


@pytest.fixture
def svc():
    return PoolService(FakeSpawner())


def test_planner_cap_fifth_refused_naming_the_knob(svc):
    # planners were previously UNCAPPED (the old capacity branch guarded
    # role=="worker" only) — v7's parallel-planner frontier needs this cap.
    for i in range(4):
        assert isinstance(svc.spawn("planner", f"rec-{i}:s1", None), str)
    res = svc.spawn("planner", "rec-4:s1", None)
    assert not isinstance(res, str)
    assert res.code == "pool_capacity_exceeded"
    assert "max planners = 4" in res.message
    assert "EDP_MAX_PLANNERS" in res.message


def test_planner_cap_env_override(monkeypatch):
    monkeypatch.setenv("EDP_MAX_PLANNERS", "2")
    svc = PoolService(FakeSpawner())
    assert isinstance(svc.spawn("planner", "r0:s1", None), str)
    assert isinstance(svc.spawn("planner", "r1:s1", None), str)
    res = svc.spawn("planner", "r2:s1", None)
    assert not isinstance(res, str) and "EDP_MAX_PLANNERS" in res.message


def test_reviewer_is_exempt_from_the_worker_cap(svc):
    # fill the worker cap completely...
    for i in range(6):
        assert isinstance(svc.spawn("worker", f"p:a{i}", None), str)
    assert not isinstance(svc.spawn("worker", "p:a7", None), str)
    # ...and a reviewer STILL spawns (it counts under the total only).
    assert isinstance(svc.spawn("reviewer", "p:review", None), str)


def test_total_cap_refusal_names_edp_max_total_shells(monkeypatch):
    # Shrink the total so the test doesn't need 10 sessions; mix roles to
    # prove the guard is all-roles (reviewer included — its exemption is
    # from the PER-ROLE caps, never from the resource guard).
    monkeypatch.setenv("EDP_MAX_TOTAL_SHELLS", "4")
    svc = PoolService(FakeSpawner())
    assert isinstance(svc.spawn("worker", "p:a1", None), str)
    assert isinstance(svc.spawn("planner", "r:s1", None), str)
    assert isinstance(svc.spawn("reviewer", "p:rev1", None), str)
    assert isinstance(svc.spawn("reviewer", "p:rev2", None), str)
    res = svc.spawn("reviewer", "p:rev3", None)
    assert not isinstance(res, str)
    assert res.code == "pool_capacity_exceeded"
    assert "max total shells = 4" in res.message
    assert "EDP_MAX_TOTAL_SHELLS" in res.message


def test_total_cap_frees_when_a_shell_dies(monkeypatch):
    # the guard reads the liveness-reconciled count, not raw rows — a dead
    # shell must never hold a total-cap slot.
    monkeypatch.setenv("EDP_MAX_TOTAL_SHELLS", "2")
    svc = PoolService(FakeSpawner())
    sid = svc.spawn("worker", "p:a1", None)
    svc.spawn("reviewer", "p:rev", None)
    assert not isinstance(svc.spawn("worker", "p:a2", None), str)  # full
    svc.spawner.kill(sid)                                          # one dies
    assert isinstance(svc.spawn("worker", "p:a2", None), str)      # slot back


def test_garbage_env_values_degrade_to_defaults(monkeypatch):
    # a typo in start-stack.bat must never crash the pool or zero a cap.
    monkeypatch.setenv("EDP_MAX_WORKERS", "lots")
    monkeypatch.setenv("EDP_MAX_PLANNERS", "")
    monkeypatch.setenv("EDP_MAX_TOTAL_SHELLS", "ten")
    from edp_pool.service import (
        _max_planners,
        _max_total_shells,
        _max_workers,
    )
    assert _max_workers() == 6
    assert _max_planners() == 4
    assert _max_total_shells() == 10
