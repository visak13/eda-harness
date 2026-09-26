"""S2 (s-b7ec13d748): the same PTY contract on every OS, driven through `edp_pool.pty.spawn_pty` with a
real process (tests/fixtures/stub_harness.py), never a fake.

Every test stops its seat with `kill_tree` and the autouse fixture fails the test if any process carrying
this run's marker survives.
"""
from __future__ import annotations

import os
import re
import sys
import time
import uuid
from pathlib import Path

import psutil
import pytest
from edp_contracts import proc
from edp_contracts.proc import ProcId, kill_tree

from edp_pool.pty import PtyClosed, harness_env, inject, spawn_pty

STUB = Path(__file__).parent / "fixtures" / "stub_harness.py"
MARK = "EDP_TEST_RUN"
RUN = f"pty-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def no_survivors():
    yield
    left = proc.scan_env_marker(MARK, RUN)
    for p in left:
        kill_tree(p, grace=1.0)
    assert not left, f"processes survived the test: {left}"


def _env() -> dict[str, str]:
    return harness_env({**os.environ, MARK: RUN, "PYTHONUNBUFFERED": "1"}, rows=30, cols=100)


class Seat:
    def __init__(self, tmp: Path, name: str = "stub") -> None:
        self.pty = spawn_pty([sys.executable, str(STUB)], cwd=str(tmp), env=_env(), rows=30, cols=100,
                             run_dir=tmp, name=name)
        self.ident = ProcId.try_of(self.pty.pid)
        self.out = ""

    def until(self, pattern: str, timeout: float = 20.0) -> re.Match:
        rx = re.compile(pattern)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            m = rx.search(self.out)
            if m:
                return m
            try:
                chunk = self.pty.read(4096)
            except PtyClosed:
                m = rx.search(self.out)
                if m:
                    return m
                raise
            if chunk:
                self.out += chunk
            else:
                time.sleep(0.02)
        raise AssertionError(f"{pattern!r} not seen in {timeout}s; output so far: {self.out[-800:]!r}")

    def send(self, line: str) -> None:
        inject(self.pty, line, submit_delay_ms=50)

    def stop(self) -> None:
        if self.ident is not None:
            kill_tree(self.ident, grace=2.0)
        host = self.pty.host_pid()
        if host:
            h = ProcId.try_of(host)
            if h is not None:
                kill_tree(h, grace=1.0)
        self.pty.close()


@pytest.fixture
def seat(tmp_path):
    s = Seat(tmp_path)
    try:
        yield s
    finally:
        s.stop()


def test_spawn_reaches_ready_and_echoes(seat):
    seat.until("❯")
    assert seat.ident is not None and seat.ident.live()
    seat.send("hello pty")
    seat.until(r"ECHO:hello pty")


def test_resize_reaches_the_child(seat):
    seat.until("❯")
    seat.send("resize?")
    seat.until(r"SIZE:100x30")
    seat.pty.resize(40, 132)
    time.sleep(0.3)
    seat.send("resize?")
    seat.until(r"SIZE:132x40")


def test_exit_code_and_closed_after_drain(seat):
    seat.until("❯")
    seat.send("exit 3")
    seat.until("BYE")
    deadline = time.monotonic() + 20
    closed = False
    while time.monotonic() < deadline:
        try:
            seat.out += seat.pty.read(4096)
        except PtyClosed:
            closed = True
            break
        if not seat.pty.alive() and sys.platform == "win32":
            break  # pywinpty may report the death before its reader hits EOF
        time.sleep(0.05)
    assert closed or not seat.pty.alive()
    deadline = time.monotonic() + 10
    while seat.pty.exit_code() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert seat.pty.exit_code() == 3


def test_tree_kill_leaves_no_descendant(seat):
    gc = int(seat.until(r"GRANDCHILD:(\d+)").group(1))
    seat.until("❯")
    assert psutil.pid_exists(gc)
    seat.stop()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and seat.ident.live():
        time.sleep(0.05)
    assert not seat.ident.live()
    assert not proc.scan_env_marker(MARK, RUN), "the grandchild outlived the tree kill"


@pytest.mark.skipif(sys.platform == "win32", reason="the POSIX host sidecar only")
def test_posix_seat_survives_its_pool_and_reattaches(tmp_path):
    """The pool dies (here: the client side is dropped and the host is left alone); a new pool attaches to
    the same host socket and drives the same seat."""
    from edp_pool.pty._posix import HostedPty, sock_path

    s = Seat(tmp_path, name="survivor")
    try:
        s.until("❯")
        pid = s.pty.pid
        s.pty.close()                              # the old pool's handles are gone; nothing is killed
        again = HostedPty.attach(sock_path(tmp_path, "survivor"))
        assert again.pid == pid
        s.pty, s.out = again, ""
        s.until("❯")                          # the replay carries the earlier output
        s.send("still here")
        s.until("ECHO:still here")
    finally:
        s.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows job objects")
def test_windows_named_job_reaches_an_orphaned_grandchild(tmp_path):
    """The seat's grandchild is orphaned (its parent killed alone, so no tree walk can find it); the seat's
    named job still terminates it."""
    name = proc.job_name("seat", f"pytest-{RUN}")
    s = Seat(tmp_path)
    try:
        gc = int(s.until(r"GRANDCHILD:(\d+)").group(1))
        s.until("❯")
        assert proc.assign_job(name, s.pty.pid)
        # children started after the assign join the job; the one started before is assigned explicitly
        assert proc.assign_job(name, gc)
        psutil.Process(s.pty.pid).kill()
        g = ProcId.of(gc)
        assert g.live()
        assert proc.terminate_job(name)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and g.live():
            time.sleep(0.05)
        assert not g.live()
    finally:
        s.stop()
