"""Stack-launcher lifecycle tests (s14/a2 service-startup wiring).

Hermetic: a FAKE Popen + an injected health probe assert the
spawn/health-gate/track/teardown lifecycle with NO real subprocess, socket,
broker, or pool. The two safety properties under test are the ones the action
mandates: tracked-PID teardown on clean exit AND on failure (graceful → hard,
tracked PIDs only) and fail-fast (a dead service tears the rest down).

Run: .venv/Scripts/python -m pytest tests/test_stack_launcher.py -v
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from edp_claude.stack_launcher import (
    ServiceSpec,
    StackLauncher,
    default_services,
    stack_root,
    venv_python,
)


# ── a fake long-lived child ──────────────────────────────────────────────────
class _FakePopen:
    _spawned: list["_FakePopen"] = []
    _next_pid = 60000

    def __init__(self, spec: ServiceSpec):
        self.spec = spec
        _FakePopen._next_pid += 1
        self.pid = _FakePopen._next_pid
        self._rc: int | None = None          # None = still running
        self.graceful_called = False
        self.killed = False
        _FakePopen._spawned.append(self)

    def poll(self):
        return self._rc

    @property
    def returncode(self):
        return self._rc

    # the launcher signals graceful via launcher._signal_graceful (patched in
    # tests to call this), then waits; a graceful child exits 0.
    def graceful(self):
        self.graceful_called = True
        self._rc = 0

    def kill(self):
        self.killed = True
        self._rc = -9

    def wait(self, timeout=None):
        if self._rc is None:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
        return self._rc

    def die(self, rc: int = 1):
        """Simulate the service crashing on its own."""
        self._rc = rc


@pytest.fixture
def launcher_factory(tmp_path, monkeypatch):
    def make(services=None, *, healthy=True):
        _FakePopen._spawned.clear()
        specs = services if services is not None else [
            ServiceSpec("broker", ["b"], tmp_path, health_host="127.0.0.1",
                        health_port=9300),
            ServiceSpec("pool", ["p"], tmp_path, health_host="127.0.0.1",
                        health_port=9301),
            ServiceSpec("supervisor", ["s"], tmp_path),  # no health port
        ]
        lr = StackLauncher(
            specs,
            pidfile=tmp_path / "stack-pids.json",
            spawn=_FakePopen,
            health_probe=lambda host, port: healthy,
            health_timeout_s=0.5, health_poll_s=0.01, settle_s=0.0,
            graceful_timeout_s=0.2)
        # graceful signal → call the fake's graceful() (no real os.kill).
        monkeypatch.setattr(lr, "_signal_graceful",
                            lambda proc: proc.graceful())
        return lr
    return make


# ── start: order, health-gate, tracked PIDs, pidfile ─────────────────────────
def test_start_spawns_in_order_and_writes_pidfile(launcher_factory):
    lr = launcher_factory()
    lr.start()
    try:
        assert [p.spec.name for p in _FakePopen._spawned] == [
            "broker", "pool", "supervisor"]
        assert set(lr.tracked_pids()) == {"broker", "pool", "supervisor"}
        on_disk = json.loads(lr.pidfile.read_text(encoding="utf-8"))
        assert set(on_disk["pids"]) == {"broker", "pool", "supervisor"}
    finally:
        lr.shutdown()


def test_start_tears_down_on_health_failure(launcher_factory):
    # broker never becomes healthy → start() must tear down + raise, leaving
    # nothing tracked and no pidfile.
    lr = launcher_factory(healthy=False)
    with pytest.raises(TimeoutError):
        lr.start()
    assert lr.tracked_pids() == {}
    # the broker we DID spawn was torn down (graceful) — tracked PID only.
    assert _FakePopen._spawned[0].graceful_called is True
    assert not lr.pidfile.exists()


def test_start_detects_service_that_dies_before_port(launcher_factory,
                                                     monkeypatch):
    lr = launcher_factory(healthy=False)
    # make the broker exit immediately so the health wait sees a dead proc.
    orig = _FakePopen.__init__

    def init_then_die(self, spec):
        orig(self, spec)
        if spec.name == "broker":
            self._rc = 3
    monkeypatch.setattr(_FakePopen, "__init__", init_then_die)
    with pytest.raises(RuntimeError, match="before its port"):
        lr.start()
    assert lr.tracked_pids() == {}


# ── teardown: graceful → hard, reverse order, tracked PIDs only ──────────────
def test_shutdown_terminates_all_tracked_graceful(launcher_factory):
    lr = launcher_factory()
    lr.start()
    lr.shutdown()
    assert all(p.graceful_called for p in _FakePopen._spawned)
    assert all(not p.killed for p in _FakePopen._spawned)   # graceful sufficed
    assert lr.tracked_pids() == {}
    assert not lr.pidfile.exists()


def test_shutdown_hard_kills_a_child_that_ignores_graceful(launcher_factory,
                                                           monkeypatch):
    lr = launcher_factory()
    lr.start()
    # a stubborn supervisor: graceful signal does NOT make it exit.
    sup = next(p for p in _FakePopen._spawned if p.spec.name == "supervisor")
    monkeypatch.setattr(lr, "_signal_graceful", lambda proc: None)
    lr.shutdown()
    assert sup.killed is True            # escalated to a hard kill of THAT pid


def test_shutdown_is_idempotent(launcher_factory):
    lr = launcher_factory()
    lr.start()
    lr.shutdown()
    lr.shutdown()  # must not raise
    assert lr.tracked_pids() == {}


# ── supervise: fail-fast on a service that dies ──────────────────────────────
def test_supervise_failfast_when_service_dies(launcher_factory):
    lr = launcher_factory()
    lr.start()
    # the pool crashes on its own; supervise must notice, return 1, tear down.
    pool = next(p for p in _FakePopen._spawned if p.spec.name == "pool")
    pool.die(rc=1)
    rc = lr.supervise(max_runtime=2.0)
    assert rc == 1
    assert lr.tracked_pids() == {}       # whole stack torn down on failure


def test_supervise_clean_stop_returns_zero(launcher_factory):
    lr = launcher_factory()
    lr.start()
    lr._stop.set()                       # an operator Ctrl-C
    assert lr.supervise(max_runtime=2.0) == 0
    assert lr.tracked_pids() == {}


# ── default wiring ───────────────────────────────────────────────────────────
def test_default_services_three_in_order():
    svcs = default_services(Path("/root"))
    assert [s.name for s in svcs] == ["broker", "pool", "supervisor"]
    assert svcs[0].health_port == 9300
    assert svcs[1].health_port == 9301
    assert svcs[2].health_port is None   # supervisor has no port to gate on
    # the supervisor is pointed at the same broker/pool.
    assert svcs[2].env["EDP_BROKER_URL"] == "http://127.0.0.1:9300"
    assert svcs[2].env["EDP_POOL_URL"] == "http://127.0.0.1:9301"


def test_default_services_no_supervisor():
    svcs = default_services(Path("/root"), with_supervisor=False)
    assert [s.name for s in svcs] == ["broker", "pool"]


def test_stack_root_is_real_layout():
    # the resolved root really contains the three sibling project dirs.
    root = stack_root()
    assert (root / "claude").is_dir()
    assert (root / "edp-broker").is_dir()
    assert (root / "edp-pool").is_dir()


def test_venv_python_falls_back_when_absent(tmp_path):
    import sys
    assert venv_python(tmp_path) == sys.executable  # no .venv → current interp
