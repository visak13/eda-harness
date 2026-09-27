"""Process identity and teardown, the one implementation every package uses.

strategyll-3b8f4033e0 (S2, s-b7ec13d748), binding:

* A process is named by :class:`ProcId` ``{pid, create_time, name}``, never a bare pid. A pid read off
  disk and handed to a fresh ``psutil.Process`` trusts whatever owns that pid now; :meth:`ProcId.live`
  closes that gap and is fail-closed (a missing create_time means refuse).
* Every stop of a service or seat ends in :func:`kill_tree`: the subtree is snapshotted BEFORE the first
  kill (Windows does not re-parent, so a dead middle process hides its children), then terminate, wait,
  kill. ``Popen.terminate()`` alone is never a stop: the uv venv launcher is a trampoline, and killing it
  orphans the interpreter's own children (probed on this host).
* Descendants come only from ``psutil.Process.children(recursive=True)``, which drops a candidate whose
  create_time is earlier than its parent's (a reused ppid). No hand walk of ppid, no WMI, no taskkill.
* :func:`detach` launches a process out of the caller's tree (the pause watchdog) without powershell/WMI.
* Windows named job objects (``Local\\edp-<kind>-<id>``) give a stop that also reaches orphans.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import psutil

_WIN = sys.platform == "win32"

#: create_time tolerance. Windows reports 100 ns FILETIME, Linux 1/100 s ticks; a reused pid within 1 s
#: of the original start AND with the same name is accepted residual risk (strategy 2/2 §2).
CREATE_TIME_TOLERANCE = 1.0


@dataclass(frozen=True)
class ProcId:
    pid: int
    create_time: float
    name: str = ""

    @classmethod
    def of(cls, pid: int) -> ProcId:
        """Fingerprint a live pid now. Raises psutil.NoSuchProcess when it is gone."""
        p = psutil.Process(int(pid))
        return cls(p.pid, p.create_time(), _name(p))

    @classmethod
    def try_of(cls, pid: int | None) -> ProcId | None:
        if not pid:
            return None
        try:
            return cls.of(pid)
        except (psutil.Error, ValueError, OSError):
            return None

    @classmethod
    def from_json(cls, d: Mapping[str, Any] | None) -> ProcId | None:
        """A persisted record, or None when it cannot name a process safely (no pid or no create_time)."""
        if not d or not d.get("pid") or d.get("create_time") is None:
            return None
        try:
            return cls(int(d["pid"]), float(d["create_time"]), str(d.get("name") or ""))
        except (TypeError, ValueError):
            return None

    def to_json(self) -> dict[str, Any]:
        return {"pid": self.pid, "create_time": self.create_time, "name": self.name}

    def live(self) -> psutil.Process | None:
        """The live process iff it is still THIS one, else None. Fail-closed: any doubt is None."""
        try:
            p = psutil.Process(self.pid)
            if abs(p.create_time() - self.create_time) >= CREATE_TIME_TOLERANCE:
                return None
            if self.name and not same_image(_name(p), self.name):
                return None
            # a zombie has exited; only its parent's wait() is left (CI ubuntu/macos: stop looked like a survivor)
            if p.status() == psutil.STATUS_ZOMBIE:
                return None
            return p
        except (psutil.Error, ValueError, OSError):
            return None

    def probe(self) -> bool | None:
        """Liveness as a tri-state: True (this process runs), False (gone, or the pid now names another
        process), None (the probe itself failed, e.g. AccessDenied). A failed probe is not a death:
        callers that write "done" on False must see None instead. Never use this to authorize a kill."""
        try:
            p = psutil.Process(self.pid)
            if abs(p.create_time() - self.create_time) >= CREATE_TIME_TOLERANCE:
                return False
            if self.name and _name(p) and not same_image(_name(p), self.name):
                return False
            return p.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False
        except (psutil.Error, OSError, ValueError):
            return None

    def alive(self) -> bool:
        p = self.live()
        try:
            return p is not None and p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except psutil.Error:
            return False


_PYTHON_IMAGE = re.compile(r"^python(?:\d+(?:\.\d+)*)?w?$")


def _image_key(name: str) -> str:
    n = name.lower().removesuffix(".exe")
    return "python" if _PYTHON_IMAGE.match(n) else n


def same_image(now: str, recorded: str) -> bool:
    """`now` is the process image `recorded` was, allowing the renames a python launch makes on the SAME pid.

    A macOS framework python execs from `python3.12` into `Python` (…/Python.app/Contents/MacOS/Python) with no
    new pid or create_time, and a venv launcher reads `python` vs `python3.14`. Every spelling of python is
    one image; any other rename is still a different process (pid reuse stays refused)."""
    return now == recorded or _image_key(now) == _image_key(recorded)


def _name(p: psutil.Process) -> str:
    try:
        return p.name()
    except psutil.Error:
        return ""


@dataclass
class KillReport:
    killed: int = 0
    refused: str | None = None
    survivors: list[ProcId] = field(default_factory=list)
    job_terminated: bool = False

    @property
    def ok(self) -> bool:
        return self.refused is None and not self.survivors


def _quiet(fn, *a) -> None:
    try:
        fn(*a)
    except (psutil.Error, OSError):
        pass


def _is_group_leader(p: psutil.Process) -> bool:
    if _WIN:
        return False
    try:
        return os.getpgid(p.pid) == p.pid
    except OSError:
        return False


def _killpg_quiet(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)  # type: ignore[attr-defined]  # POSIX only; callers gate on _is_group_leader
    except OSError:
        pass


def _running(p: psutil.Process) -> bool:
    try:
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:  # AccessDenied on a restricted-token child (codex sandbox): ask by pid only
        return psutil.pid_exists(p.pid)


def _wait(procs: list[psutil.Process], timeout: float) -> list[psutil.Process]:
    """The processes still running after `timeout`. Unlike ``psutil.wait_procs`` this never raises on a
    process we may signal but not wait on (AccessDenied from OpenProcess(SYNCHRONIZE), measured on the
    codex seat's sandboxed shells), and it reaps our own zombie children on POSIX via is_running."""
    deadline = time.monotonic() + timeout
    alive = [p for p in procs if _running(p)]
    while alive and time.monotonic() < deadline:
        time.sleep(0.05)
        alive = [p for p in alive if _running(p)]
    return alive


def kill_tree(target: ProcId | None, *, grace: float = 3.0, job: str | None = None) -> KillReport:
    """Terminate `target` and every descendant; force-kill what survives `grace` seconds.

    Refuses (kills nothing) when `target` is None or no longer the process it names. `job` names a
    Windows job object to terminate as well, which also reaches orphans `children()` cannot see."""
    if target is None:
        return KillReport(refused="no process identity")
    root = target.live()
    if root is None:
        job_done = terminate_job(job) if job else False
        return KillReport(refused="gone or pid reused", job_terminated=job_done)
    try:
        procs = root.children(recursive=True)  # SNAPSHOT FIRST: the tree is lost once the root dies
    except psutil.Error:
        procs = []
    procs.append(root)
    group = _is_group_leader(root)
    job_done = terminate_job(job) if job else False
    if group:
        _killpg_quiet(root.pid, signal.SIGTERM)  # reaches descendants that re-parented to init
    for p in procs:
        _quiet(p.terminate)
    alive = _wait(procs, grace)
    for p in alive:
        _quiet(p.kill)
    if group:
        _killpg_quiet(root.pid, signal.SIGKILL)  # type: ignore[attr-defined]
    still = _wait(alive, 2.0)
    survivors = []
    for p in still:
        pid = ProcId.try_of(p.pid)
        if pid is not None:
            survivors.append(pid)
    return KillReport(killed=len(procs), survivors=survivors, job_terminated=job_done)


def kill_popen(proc: subprocess.Popen | None, *, grace: float = 3.0, job: str | None = None) -> KillReport:
    """`kill_tree` for a child this process holds a Popen for. While the Popen is unreaped its pid cannot
    be reused (POSIX keeps a zombie, Windows keeps the handle), so fingerprinting it now is safe."""
    if proc is None:
        return KillReport(refused="no process")
    if proc.poll() is not None:
        # the root already exited; a job (if any) may still hold its orphans
        return KillReport(refused="already exited", job_terminated=terminate_job(job) if job else False)
    pid = ProcId.try_of(proc.pid)
    rep = kill_tree(pid, grace=grace, job=job)
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass
    return rep


def tree(target: ProcId | None) -> list[psutil.Process]:
    """`target` plus every descendant (root first), or [] when it is not the process it names."""
    root = target.live() if target else None
    if root is None:
        return []
    try:
        return [root, *root.children(recursive=True)]
    except psutil.Error:
        return [root]


# ------------------------------------------------------------------------------------------ spawning

def hidden_flags() -> int:
    """creationflags for a service/sidecar child: own process group, no console window (Windows);
    0 on POSIX, where the caller passes start_new_session=True instead."""
    if not _WIN:
        return 0
    return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]


def popen_service(argv: Sequence[str], **kw: Any) -> subprocess.Popen:
    """Start a long-lived child the way strategy 2/2 §3.1 prescribes: its own session (POSIX) or its own
    group with no window (Windows), stdin closed, never through a shell."""
    kw.setdefault("stdin", subprocess.DEVNULL)
    kw.setdefault("close_fds", True)
    if _WIN:
        kw["creationflags"] = kw.get("creationflags", 0) | hidden_flags()
    else:
        kw.setdefault("start_new_session", True)
    return subprocess.Popen(list(argv), **kw)


# The intermediate `detach` runs: stdlib only, so it works under the base interpreter. It launches the
# target, prints its pid, and exits, leaving the target with a dead parent (out of every caller's tree).
_DETACH_CODE = r"""
import json, subprocess, sys
spec = json.loads(sys.stdin.read())
kw = dict(cwd=spec.get("cwd"), env=spec.get("env"), stdin=subprocess.DEVNULL, close_fds=True)
log = spec.get("log")
out = open(log, "ab") if log else subprocess.DEVNULL
kw["stdout"] = out
kw["stderr"] = subprocess.STDOUT if log else subprocess.DEVNULL
if sys.platform == "win32":
    base = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    try:
        p = subprocess.Popen(spec["argv"], creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)
        broke = True
    except PermissionError:
        p = subprocess.Popen(spec["argv"], creationflags=base, **kw)
        broke = False
    print(json.dumps({"pid": p.pid, "breakaway": broke}), flush=True)
else:
    p = subprocess.Popen(spec["argv"], start_new_session=True, **kw)
    print(json.dumps({"pid": p.pid, "breakaway": True}), flush=True)
"""


def detach(argv: Sequence[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
           log: str | None = None, timeout: float = 30.0, via: str | None = None) -> tuple[ProcId, bool]:
    """Launch `argv` OUT OF this process's tree; return its ProcId and whether it left the job.

    An intermediate process starts the target (own session on POSIX; own group, no window and
    CREATE_BREAKAWAY_FROM_JOB on Windows, retried without breakaway when the job forbids it) and exits.
    The target then has a dead parent, so no ``children()`` walk from the caller reaches it, and a
    ``kill_tree`` of the caller leaves it running. The target runs with CREATE_NO_WINDOW, never
    DETACHED_PROCESS, so a venv launcher stub cannot pop a fresh visible console.

    `via` is the interpreter that runs the intermediate (default: this one). It must be a console program:
    the pid comes back on its stdout, which a GUI-subsystem app stub (Heronry Desktop.exe) never delivers."""
    spec = {"argv": list(argv), "cwd": cwd, "env": dict(env) if env is not None else None, "log": log}
    py = via or getattr(sys, "_base_executable", None) or sys.executable
    out = subprocess.run([py, "-c", _DETACH_CODE], input=json.dumps(spec), capture_output=True, text=True,
                         timeout=timeout, check=True, creationflags=hidden_flags())
    lines = (out.stdout or "").strip().splitlines()
    if not lines:
        raise RuntimeError(f"could not start {argv[0]}: {py} reported no process id"
                           + (f" ({out.stderr.strip()[-300:]})" if (out.stderr or "").strip() else ""))
    rec = json.loads(lines[-1])
    return ProcId.of(int(rec["pid"])), bool(rec.get("breakaway"))


# ------------------------------------------------------------------------------ Windows job objects
#
# A named job without KILL_ON_JOB_CLOSE: its members outlive the creator's handle (a pool or supervisor
# restart must not kill seats and services). A kernel object's NAME lives only while some handle is open,
# so `assign_job` duplicates one handle into the member itself: the name then lives exactly as long as
# the member, and a later `OpenJobObjectW(name)` + `TerminateJobObject` kills every member, orphans
# included (measured on this host: with every handle closed, OpenJobObjectW(name) fails).

_JOB_OBJECT_TERMINATE = 0x0008
_JOB_OBJECT_QUERY = 0x0004
_JOB_OBJECT_ASSIGN_PROCESS = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED = 0x1000
_PROCESS_DUP_HANDLE = 0x0040
_DUPLICATE_SAME_ACCESS = 0x0002
_JOB_EXTENDED_LIMIT_INFO = 9
_LIMIT_BREAKAWAY_OK = 0x00000800
_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


def job_name(kind: str, ident: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in f"{kind}-{ident}")
    return f"Local\\edp-{safe}"


def _k32():
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenJobObjectW.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.AssignProcessToJobObject.restype = wintypes.BOOL
    k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.TerminateJobObject.restype = wintypes.BOOL
    k.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    k.IsProcessInJob.restype = wintypes.BOOL
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    k.SetInformationJobObject.restype = wintypes.BOOL
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE),
                                  wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.DuplicateHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def _set_limits(k, job, flags: int) -> bool:
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rt", "wt", "ot")]

    class _Ext(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    info = _Ext()
    info.BasicLimitInformation.LimitFlags = flags
    return bool(k.SetInformationJobObject(job, _JOB_EXTENDED_LIMIT_INFO, ctypes.byref(info), ctypes.sizeof(info)))


def assign_job(name: str, pid: int) -> bool:
    """Put `pid` into the named job (created BREAKAWAY_OK, no KILL_ON_JOB_CLOSE). False off Windows or on
    any failure: the job is an extra reach for orphans, `kill_tree` stays the floor."""
    if not _WIN:
        return False
    k = _k32()
    job = k.CreateJobObjectW(None, name)
    if not job:
        return False
    import ctypes
    from ctypes import wintypes

    proc = None
    try:
        _set_limits(k, job, _LIMIT_BREAKAWAY_OK)
        proc = k.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE | _PROCESS_DUP_HANDLE, False, int(pid))
        if not proc or not k.AssignProcessToJobObject(job, proc):
            return False
        # park one handle inside the member so the job's name outlives this call (see above)
        held = wintypes.HANDLE()
        k.DuplicateHandle(k.GetCurrentProcess(), job, proc, ctypes.byref(held), 0, False, _DUPLICATE_SAME_ACCESS)
        return True
    finally:
        if proc:
            k.CloseHandle(proc)
        k.CloseHandle(job)


def terminate_job(name: str | None, exit_code: int = 1) -> bool:
    """Kill every member of the named job. False off Windows, or when no such job exists."""
    if not _WIN or not name:
        return False
    k = _k32()
    job = k.OpenJobObjectW(_JOB_OBJECT_TERMINATE, False, name)
    if not job:
        return False
    try:
        return bool(k.TerminateJobObject(job, exit_code))
    finally:
        k.CloseHandle(job)


def in_job(name: str, pid: int) -> bool:
    """Is `pid` a member of the named job (IsProcessInJob)? False off Windows."""
    if not _WIN:
        return False
    import ctypes
    from ctypes import wintypes

    k = _k32()
    job = k.OpenJobObjectW(_JOB_OBJECT_QUERY, False, name)
    if not job:
        return False
    proc = k.OpenProcess(_PROCESS_QUERY_LIMITED, False, int(pid))
    try:
        res = wintypes.BOOL(False)
        return bool(proc) and bool(k.IsProcessInJob(proc, job, ctypes.byref(res))) and bool(res.value)
    finally:
        if proc:
            k.CloseHandle(proc)
        k.CloseHandle(job)


def self_bind_job(name: str) -> bool:
    """A python service's first act on Windows: join its own named job before it spawns anything, so
    every descendant is a member from birth (no race). False off Windows."""
    return assign_job(name, os.getpid())


def scan_env_marker(key: str, value: str, pids: Iterable[int] | None = None) -> list[ProcId]:
    """Live processes whose environment carries `key=value` (the tests' no-survivor fixture).
    Processes whose environment is unreadable are skipped."""
    out: list[ProcId] = []
    if pids is None:
        it: Iterable[psutil.Process] = psutil.process_iter()
    else:
        it = [q for q in (ProcId.try_of(p) for p in pids) if q is not None and q.live() is not None]
        it = [psutil.Process(q.pid) for q in it]  # type: ignore[misc]
    for p in it:
        try:
            if p.environ().get(key) == value:
                out.append(ProcId(p.pid, p.create_time(), _name(p)))
        except (psutil.Error, OSError):
            continue
    return out
