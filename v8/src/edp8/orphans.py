"""Orphaned test runners (S22 host hygiene): a vitest, playwright or pytest run whose seat is gone.

A seat that closes mid-run can leave its test runner behind (2026-09-27: a `vitest run` from a closed seat
ran 2 h at 85% of a core and 1.7 GB). `find()` reports every such runner older than `min_age_s`; `heronry
doctor` prints each with pid, age, memory and the stop command, and `heronry doctor --stop-orphan <pid>`
stops that tree by process identity (ProcId + kill_tree), never by name.

"Its seat is gone" = walking up from the runner through launcher processes (shells, npm/npx, uv) the chain
breaks: a parent that no longer exists, or a pid now naming a NEWER process (Windows reuses pids and keeps
the stale ppid, so a parent must be at least as old as its child). A runner under a live claude/codex shell,
an editor or a terminal is attached and never reported.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Iterable

import psutil

from edp_contracts.proc import ProcId, kill_tree

MIN_AGE_S = 3600.0
_TOL = 1.0  # create_time rounding across psutil calls
# wrappers too: coreutils `timeout 3000 pytest` sits between a reaped shell and its runner (2026-09-27)
_SHELLS = {"bash", "sh", "zsh", "dash", "cmd", "powershell", "pwsh", "conhost", "uv", "uvx", "timeout", "env", "nohup"}


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    name: str
    cmdline: tuple[str, ...]
    create_time: float
    rss: int = 0


@dataclass
class Orphan:
    kind: str                       # vitest | playwright | pytest
    pid: int                        # the runner process
    create_time: float
    name: str
    age_s: float
    stop_pid: int                   # the top of its broken launcher chain: stopping it stops everything under it
    stop_create_time: float
    stop_name: str
    rss_mb: float                   # the whole tree under stop_pid
    cmd: str
    tree: list[int] = field(default_factory=list)

    @property
    def stop_command(self) -> str:
        return f"heronry doctor --stop-orphan {self.stop_pid}"

    def to_json(self) -> dict:
        return {"kind": self.kind, "pid": self.pid, "age_h": round(self.age_s / 3600, 2), "rss_mb": self.rss_mb,
                "stop_pid": self.stop_pid, "stop": self.stop_command, "cmd": self.cmd}


def _base(name: str) -> str:
    n = os.path.basename(name or "").lower()
    return n[:-4] if n.endswith(".exe") else n


def runner_kind(p: Proc) -> str | None:
    """vitest | playwright | pytest when `p` is a test runner process, else None."""
    exe = _base(p.name)
    args = [a.replace("\\", "/").lower() for a in p.cmdline]
    if _launcher(p):  # `npx vitest` is the launcher above the runner, not the runner
        return None
    if exe in ("node", "bun", "deno"):
        if any("vitest" in a for a in args[1:]):
            return "vitest"
        if any("playwright" in a for a in args[1:]) and "test" in args:
            return "playwright"
        return None
    if exe in ("pytest", "py.test"):
        return "pytest"
    if exe.startswith("python") or exe == "py":
        for i, a in enumerate(args[1:], 1):
            if a == "-m" and i + 1 < len(args) and args[i + 1] in ("pytest", "py.test"):
                return "pytest"
            if _base(a) in ("pytest", "py.test"):
                return "pytest"
    return None


def _launcher(p: Proc) -> bool:
    """A process that only starts others (a shell, npm/npx, uv): the chain above a runner goes through these."""
    exe = _base(p.name)
    if exe in _SHELLS:
        return True
    if exe == "node":
        return any(x in a.replace("\\", "/").lower() for a in p.cmdline[1:] for x in ("npm-cli", "npx-cli", "/npm/", "/npx"))
    return False


def snapshot() -> dict[int, Proc]:
    out: dict[int, Proc] = {}
    for p in psutil.process_iter(["pid", "ppid", "name", "cmdline", "create_time", "memory_info"]):
        i = p.info
        try:
            out[i["pid"]] = Proc(i["pid"], i.get("ppid") or 0, i.get("name") or "", tuple(i.get("cmdline") or ()),
                                 float(i.get("create_time") or 0.0), getattr(i.get("memory_info"), "rss", 0) or 0)
        except (TypeError, ValueError):
            continue
    return out


def _parent(table: dict[int, Proc], p: Proc) -> Proc | None:
    """p's parent iff it still exists AND is not younger than p (a reused pid names a newer process)."""
    q = table.get(p.ppid)
    if q is None or q.pid == p.pid or q.create_time > p.create_time + _TOL:
        return None
    return q


def _children(table: dict[int, Proc]) -> dict[int, list[Proc]]:
    kids: dict[int, list[Proc]] = {}
    for p in table.values():
        par = _parent(table, p)
        if par is not None:
            kids.setdefault(par.pid, []).append(p)
    return kids


def _subtree(kids: dict[int, list[Proc]], root: Proc) -> list[Proc]:
    out, stack = [], [root]
    while stack:
        p = stack.pop()
        out.append(p)
        stack.extend(kids.get(p.pid, []))
    return out


def find(*, min_age_s: float = MIN_AGE_S, table: dict[int, Proc] | None = None,
         now: float | None = None, exclude: Iterable[int] = ()) -> list[Orphan]:
    """Every test runner older than `min_age_s` whose launcher chain is broken (its seat is gone)."""
    table = snapshot() if table is None else table
    now = time.time() if now is None else now
    skip = set(exclude)
    kids = _children(table)
    found: dict[int, Orphan] = {}
    for p in table.values():
        kind = runner_kind(p)
        if kind is None or p.pid in skip or now - p.create_time < min_age_s:
            continue
        parent = _parent(table, p)
        if parent is not None and runner_kind(parent) is not None:
            continue  # a worker of another runner: its root is reported
        top, cur = p, parent
        while cur is not None and _launcher(cur):
            top, cur = cur, _parent(table, cur)
        if cur is not None:
            continue  # attached: a live non-launcher ancestor (a seat shell, an editor, a terminal)
        if top.pid in found or top.pid in skip:
            continue
        tree = _subtree(kids, top)
        found[top.pid] = Orphan(kind=kind, pid=p.pid, create_time=p.create_time, name=p.name,
                                age_s=now - p.create_time, stop_pid=top.pid, stop_create_time=top.create_time,
                                stop_name=top.name, rss_mb=round(sum(x.rss for x in tree) / 2**20, 1),
                                cmd=" ".join(p.cmdline)[:200], tree=[x.pid for x in tree])
    return sorted(found.values(), key=lambda o: -o.age_s)


def stop(pid: int, *, min_age_s: float = MIN_AGE_S) -> dict:
    """Stop the orphan whose stop_pid is `pid` — only if a fresh scan still reports it — by identity."""
    for o in find(min_age_s=min_age_s):
        if o.stop_pid == pid:
            rep = kill_tree(ProcId(o.stop_pid, o.stop_create_time, o.stop_name))
            return {"stopped": pid, "killed": rep.killed, "refused": rep.refused,
                    "survivors": [s.pid for s in rep.survivors]}
    return {"stopped": None, "refused": f"pid {pid} is not an orphaned test runner (older than "
                                        f"{min_age_s / 3600:g} h) in a fresh scan"}
