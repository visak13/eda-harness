"""S22 host hygiene: orphaned test runners are found (pid, age, stop command) and stopped by identity.

Unit rows drive `orphans.find` with a fake process table; the drill plants REAL orphans (a node "vitest" and
a python "-m pytest" whose launcher exited) and shows `find` reporting them and `stop` ending the tree.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time

import psutil

from edp8 import orphans
from edp8.orphans import Proc

NOW = 1_000_000.0
H = 3600.0


def _t(*procs: Proc) -> dict[int, Proc]:
    return {p.pid: p for p in procs}


def P(pid, ppid, name, cmd, age_h, rss=0):  # noqa: N802
    return Proc(pid, ppid, name, tuple(cmd), NOW - age_h * H, rss)


def test_runner_kinds():
    assert orphans.runner_kind(P(1, 0, "node.exe", ["node", "C:/w/node_modules/vitest/vitest.mjs", "run"], 2)) == "vitest"
    assert orphans.runner_kind(P(1, 0, "node", ["node", "/w/node_modules/.bin/playwright", "test"], 2)) == "playwright"
    assert orphans.runner_kind(P(1, 0, "python.exe", ["python", "-m", "pytest", "-q"], 2)) == "pytest"
    assert orphans.runner_kind(P(1, 0, "pytest.exe", ["pytest"], 2)) == "pytest"
    assert orphans.runner_kind(P(1, 0, "node.exe", ["node", "server.js"], 2)) is None
    assert orphans.runner_kind(P(1, 0, "python.exe", ["python", "-m", "edp8.service"], 2)) is None


def test_orphan_whose_parent_is_gone_is_reported_with_pid_age_and_stop_command():
    t = _t(P(10, 999, "node.exe", ["node", "node_modules/vitest/vitest.mjs", "run"], 2.0, 1700 * 2**20),
           P(11, 10, "node.exe", ["node", "node_modules/vitest/dist/workers/forks.js"], 2.0, 100 * 2**20))
    found = orphans.find(table=t, now=NOW)
    assert [(o.kind, o.pid, o.stop_pid) for o in found] == [("vitest", 10, 10)]  # the worker is not a 2nd row
    o = found[0]
    assert round(o.age_s / H, 1) == 2.0 and o.rss_mb == 1800.0 and o.tree == [10, 11]
    assert o.stop_command == "heronry doctor --stop-orphan 10"


def test_broken_launcher_chain_reports_the_chain_top_as_the_stop_target():
    # claude (gone) -> bash -> npx node -> vitest: bash and npx survive their seat
    t = _t(P(20, 777, "bash.exe", ["bash", "-c", "npx vitest"], 3),
           P(21, 20, "node.exe", ["node", "C:/nvm/node_modules/npm/bin/npx-cli.js", "vitest"], 3),
           P(22, 21, "node.exe", ["node", "web/node_modules/vitest/vitest.mjs"], 3))
    (o,) = orphans.find(table=t, now=NOW)
    assert (o.pid, o.stop_pid, o.tree) == (22, 20, [20, 21, 22])


def test_timeout_wrapper_left_by_a_reaped_shell_is_part_of_the_chain():
    # seen live 2026-09-27: bash (reaped) -> timeout 3000 -> timeout -> venv python -> python -m pytest
    t = _t(P(60, 555, "timeout.exe", ["timeout", "3000", "python", "-m", "pytest"], 2),
           P(61, 60, "timeout.exe", ["timeout", "3000", "python", "-m", "pytest"], 2),
           P(62, 61, "python.exe", ["python", "-m", "pytest", "tests"], 2),
           P(63, 62, "python.exe", ["python", "-m", "pytest", "tests"], 2))
    (o,) = orphans.find(table=t, now=NOW)
    assert (o.pid, o.stop_pid, o.tree) == (62, 60, [60, 61, 62, 63])


def test_attached_runner_and_young_orphan_are_not_reported():
    t = _t(P(30, 0, "claude.exe", ["claude"], 5),
           P(31, 30, "bash.exe", ["bash", "-c", "pytest"], 3),
           P(32, 31, "python.exe", ["python", "-m", "pytest"], 3),             # under a live seat
           P(40, 998, "python.exe", ["python", "-m", "pytest"], 0.5))           # orphaned, but 30 min old
    assert orphans.find(table=t, now=NOW) == []
    assert [o.pid for o in orphans.find(table=t, now=NOW, min_age_s=0)] == [40]


def test_reused_parent_pid_counts_as_gone():
    # the runner's ppid now names a process started AFTER it (Windows keeps stale ppids)
    t = _t(P(50, 51, "python.exe", ["python", "-m", "pytest"], 2), P(51, 0, "claude.exe", ["claude"], 0.1))
    assert [o.pid for o in orphans.find(table=t, now=NOW)] == [50]


def test_posix_reaper_parent_counts_as_gone():
    # POSIX re-parents an orphan to init or a subreaper, so its ppid always names a live, older process
    for reaper in (P(1, 0, "systemd", ["/sbin/init"], 9), P(900, 1, "launchd", ["/sbin/launchd"], 9),
                   P(901, 1, "systemd", ["/lib/systemd/systemd", "--user"], 9)):
        t = _t(reaper, P(70, reaper.pid, "python3", ["python3", "-m", "pytest"], 2))
        assert [o.pid for o in orphans.find(table=t, now=NOW)] == [70], reaper


# ------------------------------------------------------------------------------ the drill (real processes)

def _plant(argv: list[str]) -> int:
    """Start `argv` from a launcher python that exits at once: the child is left without its parent."""
    code = ("import subprocess, sys; "
            f"p = subprocess.Popen({argv!r}, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL"
            + (", creationflags=subprocess.CREATE_NEW_PROCESS_GROUP" if sys.platform == "win32" else ", start_new_session=True")
            + "); print(p.pid)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    return int(out.stdout.strip())


def test_drill_planted_orphans_are_found_and_stopped():
    planted = [_plant([sys.executable, "-c", "import time; time.sleep(120)", "-m", "pytest"])]
    node = shutil.which("node")
    if node:
        planted.append(_plant([node, "-e", "setTimeout(() => {}, 120000)", "node_modules/vitest/vitest.mjs"]))
    try:
        time.sleep(1.0)
        found = {o.pid: o for o in orphans.find(min_age_s=0)}
        for pid in planted:
            assert pid in found, f"planted orphan {pid} not found: {list(found)}"
            o = found[pid]
            print(f"found {o.kind} pid {o.pid} age {o.age_s:.1f}s {o.rss_mb} MB -> {o.stop_command}")
        assert {found[p].kind for p in planted} == ({"pytest", "vitest"} if node else {"pytest"})
        # the doctor's stop path: refuses a pid that is not an orphan, stops a real one by identity
        assert orphans.stop(psutil.Process().pid, min_age_s=0)["stopped"] is None
        for pid in planted:
            out = orphans.stop(found[pid].stop_pid, min_age_s=0)
            assert out["stopped"] == found[pid].stop_pid and not out["survivors"], out
            assert not psutil.pid_exists(pid) or psutil.Process(pid).create_time() != found[pid].create_time
    finally:
        for pid in planted:
            try:
                psutil.Process(pid).kill()
            except psutil.Error:
                pass


def test_vitest_config_does_not_watch():
    """The other half: a bare `vitest` in a seat's PTY runs once instead of watching forever."""
    from pathlib import Path
    cfg = (Path(__file__).resolve().parents[1] / "web" / "vite.config.ts").read_text(encoding="utf-8")
    assert "watch: false," in cfg
