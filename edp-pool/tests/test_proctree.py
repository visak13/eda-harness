"""kill_process_tree — close the whole subtree a shell opened, not just the
root pid (the 2026-06-02 "198 orphaned python shells" fix).
"""

import sys
import time

import psutil

from edp_pool.proctree import kill_process_tree

# a parent that spawns a child which sleeps, then sleeps itself — mirrors a
# claude shell (root) that spawned an MCP server / rx driver (child).
_PARENT_SRC = (
    "import subprocess, sys, time; "
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
    "time.sleep(60)"
)


def _spawn_tree():
    parent = psutil.Popen([sys.executable, "-c", _PARENT_SRC])
    # wait for the grandchild to appear
    for _ in range(50):
        kids = psutil.Process(parent.pid).children(recursive=True)
        if kids:
            return parent, kids[0]
        time.sleep(0.1)
    raise AssertionError("child process never spawned")


def test_kill_process_tree_kills_parent_and_children():
    parent, child = _spawn_tree()
    assert parent.is_running() and child.is_running()

    n = kill_process_tree(parent.pid)
    assert n >= 2                       # root + at least the one child

    gone, alive = psutil.wait_procs([parent, child], timeout=5)
    assert not alive, f"survivors: {[p.pid for p in alive]}"
    assert not parent.is_running()
    assert not child.is_running()


def test_kill_process_tree_is_pid_scoped():
    # killing one tree must NOT touch a sibling tree (the broker/pool/other
    # stacks must survive — the taskkill-nuke failure this guards against).
    victim, victim_child = _spawn_tree()
    bystander, bystander_child = _spawn_tree()
    try:
        kill_process_tree(victim.pid)
        psutil.wait_procs([victim, victim_child], timeout=5)
        assert not victim.is_running() and not victim_child.is_running()
        # the bystander tree is untouched
        assert bystander.is_running() and bystander_child.is_running()
    finally:
        kill_process_tree(bystander.pid)


def test_kill_process_tree_none_and_missing_are_noops():
    assert kill_process_tree(None) == 0
    # a pid that doesn't exist (very high, unlikely to be live)
    assert kill_process_tree(2_000_000_000) == 0
