"""S14 (owner m-e2edc8d256): after the app is force-quit with seats live, a pool restart launches NO shell.

A real private pool (own port, own state file, stub harness as the claude bin, dead broker): spawn three
stub seats, kill the pool and every seat tree the way a force quit does, start a second pool on the same
state file, and count the shells it launches. Nothing here touches the fleet's pool, board or broker.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
from edp_contracts import proc
from edp_contracts.proc import ProcId, kill_tree, popen_service

from test_private_pool_stub_seat import _free_port, _stub_bin, subprocess_stdout

MARK = "EDP_TEST_RUN"
RUN = f"fq-{uuid.uuid4().hex[:8]}"
HANDLES = ["stub:fq1", "stub:fq2", "stub:fq3"]


@pytest.fixture(autouse=True)
def no_survivors():
    yield
    for p in proc.scan_env_marker(MARK, RUN):
        kill_tree(p, grace=1.0)


def kill_ours(ident: ProcId, grace: float) -> None:
    """Stop a process only when it carries this run's marker: never a fleet pid (dec-a8951bd35b)."""
    ours = {p.pid for p in proc.scan_env_marker(MARK, RUN)}
    import psutil
    try:  # a killed child stays a zombie until reaped (POSIX); its environ is unreadable, so it is never "ours"
        gone = psutil.Process(ident.pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        gone = True
    if ident.pid not in ours and gone:
        return  # already gone
    assert ident.pid in ours, f"pid {ident.pid} is not a process this test started; refusing to kill it"
    kill_tree(ident, grace=grace)


def _env(tmp_path: Path, port: int, extra: dict | None = None) -> dict:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("EDP", "HERONRY"))}
    env.update({
        MARK: RUN,
        "EDP_HOME": str(tmp_path / "edp-home"),
        "EDP_POOL_HOST": "127.0.0.1", "EDP_POOL_PORT": str(port),
        "EDP_POOL_STATE": str(tmp_path / "state" / "pool-state.json"),
        "EDP_POOL_LOG_DIR": str(tmp_path / "pool-logs"),
        "EDP_POOL_SHELL_LOG_DIR": str(tmp_path / "shell-logs"),
        "EDP_POOL_PAUSE_TOKENS": str(tmp_path / "pause"),
        "EDP_POOL_AGENT_HOME": str(home),
        "EDP_POOL_CLAUDE_HOME": str(tmp_path / "claude-home"),
        "EDP_BROKER_URL": f"http://127.0.0.1:{_free_port()}",
        "EDP_CLAUDE_BIN": str(_stub_bin(tmp_path)),
        "EDP_SHADOW": "0", "EDP_SPAWN_MODE": "headless",
        "EDP_RESUME_WATCHDOG_SECS": "1",
        "PYTHONUNBUFFERED": "1",
    })
    env.update(extra or {})
    return env


def _start_pool(tmp_path: Path, port: int, tag: str, extra: dict | None = None):
    log = (tmp_path / f"pool-{tag}.out").open("wb")
    pool = popen_service([sys.executable, "-m", "edp_pool.main"], env=_env(tmp_path, port, extra),
                         cwd=str(tmp_path), stdout=log, stderr=subprocess_stdout())
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while True:
        try:
            httpx.get(f"{base}/v1/pool/capabilities", timeout=2).json()
            return pool, ProcId.of(pool.pid), base, log
        except httpx.HTTPError:
            assert pool.poll() is None, (tmp_path / f"pool-{tag}.out").read_text(errors="replace")[-2000:]
            assert time.monotonic() < deadline, "private pool never answered"
            time.sleep(0.3)


def _rows(base: str) -> list[dict]:
    got = httpx.get(f"{base}/v1/sessions", timeout=5).json()
    return got if isinstance(got, list) else got.get("sessions", [])


def _stub_shells() -> list[ProcId]:
    """Seat shells only: the marked processes whose command line runs the stub harness (the marker is also on
    the pool itself and its conhost)."""
    import psutil
    out = []
    for p in proc.scan_env_marker(MARK, RUN):
        try:
            if "stub_harness" in " ".join(psutil.Process(p.pid).cmdline()):
                out.append(p)
        except psutil.Error:
            continue
    return out


def _force_quit(pool_id: ProcId, seat_ids: list[ProcId]) -> None:
    for sid in [pool_id, *seat_ids]:
        kill_ours(sid, grace=0.0)


def _spawn_three(base: str) -> list[ProcId]:
    seats = []
    for h in HANDLES:
        r = httpx.post(f"{base}/v1/spawn", json={"role": "worker", "handle": h, "mode": "headless"}, timeout=90)
        assert r.status_code == 200 and "session_id" in r.json(), r.text
    for row in _rows(base):
        fp = row.get("proc") or {}
        assert fp.get("pid"), row
        seats.append(ProcId.of(int(fp["pid"])))
    assert len(seats) == 3
    return seats


def _count_launches(base: str, before_sids: set[str], seconds: float) -> tuple[list[dict], list[ProcId]]:
    """New session rows (a launch) and live stub shells seen over `seconds` after the restart."""
    deadline = time.monotonic() + seconds
    new: list[dict] = []
    while time.monotonic() < deadline:
        new = [r for r in _rows(base) if r.get("session_id") not in before_sids]
        if new or _stub_shells():
            break
        time.sleep(0.5)
    return new, _stub_shells()


def _restart_and_count(tmp_path, port, before, seconds=None, extra=None):
    seconds = seconds or float(os.environ.get("S14_OBSERVE_SECS", "15"))  # the owner proof runs 300
    pool2, pool2_id, base, log2 = _start_pool(tmp_path, port, "b", extra)
    return pool2_id, base, log2, *_count_launches(base, before, seconds)


def test_restart_after_a_force_quit_launches_no_shell(tmp_path):
    port = _free_port()
    pool, pool_id, base, log = _start_pool(tmp_path, port, "a")
    pool2_id = None
    try:
        seats = _spawn_three(base)
        before = {r["session_id"] for r in _rows(base)}
        _force_quit(pool_id, seats)
        log.close()
        assert not _stub_shells(), "the force quit left shells running"
        pool2_id, base, log2, new, shells = _restart_and_count(tmp_path, port, before)
        assert new == [], f"the restart launched {len(new)} new session(s): {new}"
        assert shells == [], f"the restart left live shells: {shells}"
        rows = {r["handle"]: r for r in _rows(base)}
        assert all(rows[h]["state"] == "dead" and rows[h].get("interrupted") for h in HANDLES), rows
        assert all(rows[h]["dead_reason"].startswith("interrupted:") for h in HANDLES), rows
    finally:
        for pid in (pool2_id, pool_id):
            if pid is not None:
                kill_ours(pid, grace=2.0)


def test_parked_seats_are_interrupted_too_and_only_the_updaters_park_is_relaunched(tmp_path):
    """Two ordinary parked seats and one parked for the update: after a force quit the watchdog (heartbeat band
    forced to 1 s, so every parked row is overdue) resumes NONE of the ordinary ones."""
    port = _free_port()
    extra = {"EDP_PARKED_HEARTBEAT_SECS": "1"}
    pool, pool_id, base, log = _start_pool(tmp_path, port, "a", extra)
    pool2_id = None
    try:
        seats = _spawn_three(base)
        for h in HANDLES[:2]:
            assert httpx.post(f"{base}/v1/park/{h}", timeout=30).json()["parked"] is True
        r = httpx.post(f"{base}/v1/park/{HANDLES[2]}", json={"for_update": True}, timeout=30).json()
        assert r["parked"] is True, r
        assert {x["handle"]: x.get("park_for_update") for x in _rows(base)}[HANDLES[2]] is True
        before = {r["session_id"] for r in _rows(base)}
        _force_quit(pool_id, seats)
        log.close()
        pool2_id, base, log2, new, shells = _restart_and_count(tmp_path, port, before, 12, extra)
        rows = {r["handle"]: r for r in _rows(base)}
        for h in HANDLES[:2]:
            assert rows[h]["state"] == "dead" and rows[h].get("interrupted"), rows[h]
        launched = {r["handle"] for r in new}
        assert not launched & set(HANDLES[:2]), f"an ordinary parked seat was relaunched: {launched}"
        assert not rows[HANDLES[2]].get("park_for_update"), "the updater's park flag is spent once the pool resumes it"
        deadline = time.monotonic() + 30  # the one automatic relaunch: `resuming` until its shell reports in
        while rows[HANDLES[2]]["state"] == "resuming" and time.monotonic() < deadline:
            time.sleep(0.5)
            rows = {r["handle"]: r for r in _rows(base)}
        assert rows[HANDLES[2]]["state"] == "active", rows[HANDLES[2]]
        assert len(_stub_shells()) >= 1
    finally:
        for pid in (pool2_id, pool_id):
            if pid is not None:
                kill_ours(pid, grace=2.0)


def test_an_interrupted_seat_is_resumed_only_when_someone_asks(tmp_path):
    port = _free_port()
    pool, pool_id, base, log = _start_pool(tmp_path, port, "a")
    pool2_id = None
    try:
        seats = _spawn_three(base)
        before = {r["session_id"] for r in _rows(base)}
        _force_quit(pool_id, seats)
        log.close()
        pool2_id, base, log2, new, shells = _restart_and_count(tmp_path, port, before, 8)
        assert new == [] and shells == []
        r = httpx.post(f"{base}/v1/resume/{HANDLES[0]}", timeout=90)  # the Resume action
        assert r.status_code == 200, r.text
        rows = {x["handle"]: x for x in _rows(base)}
        assert rows[HANDLES[0]]["state"] == "active", rows[HANDLES[0]]
        assert all(rows[h]["state"] == "dead" for h in HANDLES[1:]), "only the asked seat comes back"
        import psutil
        tree = {rows[HANDLES[0]]["proc"]["pid"]} | {c.pid for c in psutil.Process(rows[HANDLES[0]]["proc"]["pid"]).children(recursive=True)}
        shells = {s.pid for s in _stub_shells()}
        assert shells and shells <= tree, f"a shell outside the resumed seat is running: {shells - tree}"
    finally:
        for pid in (pool2_id, pool_id):
            if pid is not None:
                kill_ours(pid, grace=2.0)
