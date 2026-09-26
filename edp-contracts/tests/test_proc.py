"""edp_contracts.proc — process identity and tree teardown (S2 s-b7ec13d748, c-d7bd67f704).

Every test launches real processes marked with a per-run env value and asserts none survive it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil
import pytest

from edp_contracts import proc
from edp_contracts.proc import ProcId, kill_tree

RUN = uuid.uuid4().hex
MARK = "EDP_TEST_RUN"

# A process that spawns `depth` more levels below itself, each writing its pid to <dir>/<level>.pid,
# the deepest one sleeping. The spawn is via sys.executable: a uv venv stub adds a trampoline layer,
# which the tree walk must cover as well.
_LEVEL = r"""
import os, subprocess, sys, time
d, depth = sys.argv[1], int(sys.argv[2])
open(os.path.join(d, f"{depth}.pid"), "w").write(str(os.getpid()))
if depth > 1:
    subprocess.Popen([sys.executable, "-c", sys.argv[3], d, str(depth - 1), sys.argv[3]])
time.sleep(600)
"""


def _env() -> dict[str, str]:
    return {**os.environ, MARK: RUN}


def _spawn_tree(tmp: Path, depth: int = 3) -> subprocess.Popen:
    p = subprocess.Popen([sys.executable, "-c", _LEVEL, str(tmp), str(depth), _LEVEL], env=_env())
    deadline = time.time() + 30
    while time.time() < deadline and len(list(tmp.glob("*.pid"))) < depth:
        time.sleep(0.1)
    assert len(list(tmp.glob("*.pid"))) == depth, "tree did not come up"
    return p


def _level_pids(tmp: Path) -> dict[int, int]:
    return {int(f.stem): int(f.read_text()) for f in tmp.glob("*.pid")}


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


@pytest.fixture(autouse=True)
def no_survivors():
    yield
    left = proc.scan_env_marker(MARK, RUN)
    for p in left:  # clean up before failing so one bad test does not leak into the next
        kill_tree(p, grace=1.0)
    assert not left, f"processes survived the test: {left}"


def test_kill_tree_kills_a_three_level_tree(tmp_path):
    root = _spawn_tree(tmp_path, depth=3)
    levels = _level_pids(tmp_path)
    assert all(_alive(p) for p in levels.values())
    rep = proc.kill_popen(root)
    assert rep.refused is None and not rep.survivors, rep
    assert rep.killed >= 3
    assert not any(_alive(p) for p in levels.values()), levels


def test_pid_reuse_is_refused_and_nothing_is_killed(tmp_path):
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], env=_env())
    try:
        real = ProcId.of(victim.pid)
        stale = ProcId(real.pid, real.create_time - 30.0, real.name)  # what a reused pid looks like
        assert stale.live() is None
        rep = kill_tree(stale)
        assert rep.refused == "gone or pid reused" and rep.killed == 0
        assert _alive(victim.pid)
        # a record with no create_time never names a process
        assert ProcId.from_json({"pid": victim.pid}) is None
        assert kill_tree(ProcId.from_json({"pid": victim.pid, "create_time": None})).refused
        assert _alive(victim.pid)
    finally:
        proc.kill_popen(victim, grace=1.0)


def test_process_older_than_its_parent_is_not_killed(tmp_path, monkeypatch):
    """The stale-ppid incident: an OLDER process whose recorded ppid now names our root (the root reused
    a dead parent's pid). psutil's children() drops it by create_time; kill_tree must not touch it."""
    older = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], env=_env())
    older_ids = {p.pid for p in [psutil.Process(older.pid), *psutil.Process(older.pid).children(recursive=True)]}
    time.sleep(1.2)  # make the root strictly younger than `older`
    root = _spawn_tree(tmp_path, depth=2)
    levels = _level_pids(tmp_path)
    real_map = psutil._ppid_map
    forged = lambda: {**real_map(), **{pid: root.pid for pid in older_ids}}  # noqa: E731
    monkeypatch.setattr(psutil, "_ppid_map", forged)
    try:
        assert not ({c.pid for c in psutil.Process(root.pid).children(recursive=True)} & older_ids)
        rep = proc.kill_popen(root)
        assert rep.refused is None and not rep.survivors
        assert not any(_alive(p) for p in levels.values())
        assert all(_alive(p) for p in older_ids), "an older process with a forged ppid was killed"
    finally:
        monkeypatch.undo()
        proc.kill_popen(older, grace=1.0)


def test_procid_json_round_trip_and_live():
    me = ProcId.of(os.getpid())
    assert ProcId.from_json(json.loads(json.dumps(me.to_json()))) == me
    assert me.live() is not None and me.alive()
    assert ProcId(me.pid, me.create_time, "not-" + me.name).live() is None
    assert kill_tree(None).refused == "no process identity"


def test_detach_leaves_the_callers_tree(tmp_path):
    target, _broke = proc.detach([sys.executable, "-c", "import time; time.sleep(600)"], env=_env())
    try:
        assert target.live() is not None
        mine = {c.pid for c in psutil.Process().children(recursive=True)}
        assert target.pid not in mine, "detached target is still in the caller's tree"
    finally:
        rep = kill_tree(target, grace=1.0)
        assert rep.refused is None and not rep.survivors


@pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows-only")
def test_named_job_holds_the_grandchild_and_terminates_orphans(tmp_path):
    name = proc.job_name("test", RUN[:12])
    # the root joins the job before it spawns, as a self-binding service would
    code = ("import sys, subprocess, time\n"
            "from edp_contracts import proc\n"
            f"assert proc.self_bind_job({name!r})\n"
            f"open({str(tmp_path / 'ready')!r}, 'w').write('1')\n"
            + _LEVEL.replace("d, depth = sys.argv[1], int(sys.argv[2])", "d, depth = sys.argv[1], int(sys.argv[2])"))
    root = subprocess.Popen([sys.executable, "-c", code, str(tmp_path), "3", _LEVEL], env=_env())
    deadline = time.time() + 30
    while time.time() < deadline and len(list(tmp_path.glob("*.pid"))) < 3:
        time.sleep(0.1)
    levels = _level_pids(tmp_path)
    assert len(levels) == 3
    assert all(proc.in_job(name, p) for p in levels.values()), "a descendant is outside the job"
    # orphan the grandchild: kill its parent alone, so no children() walk from the root reaches it
    psutil.Process(levels[2]).kill()
    time.sleep(0.5)
    reach = {c.pid for c in psutil.Process(root.pid).children(recursive=True)}
    assert levels[1] not in reach and _alive(levels[1])
    assert proc.terminate_job(name)
    time.sleep(1.0)
    assert not any(_alive(p) for p in levels.values())
    root.wait(timeout=5)
