"""A fake PTY at the `edp_pool.pty_launcher.spawn_pty` seam (S2), for tests that drive PtyLaunch without a
real process on any OS.

`spawn_like(argv, cwd=, dimensions=, env=)` returns a winpty-shaped stand-in (read/isalive/write/
terminate[/pid]); it is wrapped in the real `WinPty` adapter, so the PtyClosed/str contract is the
production one. Identity and teardown are faked too: a stand-in's pid is not a process, and it must never
reach a real `kill_tree` or a Windows job (a fake pid 4242 can be a live process on the host).
"""
from __future__ import annotations

import itertools
import types

_FAKE_PIDS = itertools.count(3_000_000_001)


def install(monkeypatch, spawn_like) -> dict:
    from edp_pool import pty_launcher as pl
    from edp_pool.pty._win import WinPty

    procs: dict[int, object] = {}

    def _spawn_pty(argv, *, cwd, env, rows=50, cols=200, run_dir=None, name=None):
        proc = spawn_like(list(argv), cwd=cwd, dimensions=(rows, cols), env=env)
        w = WinPty()
        w._p = proc
        w.pid = getattr(proc, "pid", None) or next(_FAKE_PIDS)
        procs[w.pid] = proc
        return w

    def _kill_tree(ident, **_kw):
        proc = procs.get(getattr(ident, "pid", None))
        if proc is not None:
            proc.terminate(force=True)

    monkeypatch.setattr(pl, "spawn_pty", _spawn_pty)
    monkeypatch.setattr(pl, "kill_tree", _kill_tree)
    monkeypatch.setattr(pl, "assign_job", lambda *_a, **_k: False)
    monkeypatch.setattr(pl, "ProcId", types.SimpleNamespace(
        try_of=lambda pid: types.SimpleNamespace(pid=pid) if pid in procs else None))
    return procs
