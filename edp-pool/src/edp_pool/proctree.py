"""PID-scoped process-tree teardown.

A spawned claude shell is the ROOT of a tree it opens: stdio MCP servers
(`uv run python -m edp_claude.mcp_server`, plus any other configured MCP
servers) and one `python -m edp_claude.reactive.driver` per observe()
subscription. The pool's terminate() used to kill only the ROOT pid
(`TerminateProcess`), so every python child was orphaned and accumulated
across the run — the 2026-06-02 "198 shells froze the machine" incident.

Fix: on pool_close_self / reap, close the WHOLE subtree the shell opened —
the launcher owns the process it spawned, so it closes everything spawned
within it (RAII at the right layer), not a background reaper chasing leaks.

PID-scoped by construction: it walks the descendants of exactly this pid
and nothing else, so it can never touch the broker, the pool, or another
stack's processes (the failure a blanket `taskkill /IM python.exe` caused
— see the guard-destructive hook).
"""

import ctypes
import sys
import uuid
from datetime import datetime, timezone

import psutil

# ── W12: pause via process suspension ────────────────────────────────────
#
# `suspend_tree` / `resume_tree` live beside `kill_process_tree` because they
# share its one non-negotiable property: they act on a pid THIS pool recorded
# at spawn, and on nothing else. A blanket suspend is the same incident as a
# blanket kill — the neuron's foreground shell and the user's own terminal are
# also `claude.exe`, and they carry no pool registry row.
#
# WHAT MAKES THIS DIFFERENT FROM `kill_process_tree`, AND WHY IT NEEDED A POC:
# a kill is verifiable by absence (the pid is gone). A SUSPEND IS NOT. There is
# no field anywhere in the OS that says "this process is paused" and can be
# trusted:
#
#   * `psutil.status()` reported `running` for 4 of 16 pids whose every thread
#     was suspended, and flipped `stopped`→`running` mid-freeze on the root
#     while the shell executed nothing. It PASSES WHILE LYING.
#   * `cpu_times()` deltas are 0.0 for a frozen process AND for an idle one.
#
# The only instrument that discriminates is the THREAD SUSPEND COUNT:
# `SuspendThread` returns the thread's PREVIOUS count, which is > 0 only if the
# thread was already suspended. Each probe is undone immediately with
# `ResumeThread`. See `_thread_prev_suspend_count`.
#
# THE RULE THAT FALLS OUT OF IT (and it is the whole design): "is it frozen" is
# a MEASURED FACT AT READ TIME, never a boolean stored at write time. Nothing
# in this module records "paused = True". `observe_tree_state` re-measures on
# every call. A stored flag is how a pause reports "paused" while the tokens
# burn — the exact inversion the POC caught, where a stale watchdog resumed a
# frozen shell 43 seconds into a 12-minute freeze and the sampler kept printing
# `frozen`.

_IS_WINDOWS = sys.platform == "win32"

# OpenThread access right: the minimum needed to Suspend/Resume.
_THREAD_SUSPEND_RESUME = 0x0002
# SuspendThread/ResumeThread return (DWORD)-1 on failure.
_SUSPEND_ERROR = 0xFFFFFFFF

# Fingerprint tolerance, matched to service._proc_alive / _proc_kill_allowed.
_CREATE_TIME_TOLERANCE_SECS = 1.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _thread_prev_suspend_count(tid: int) -> int | None:
    """The thread's suspend count BEFORE this probe, or None if unreadable.

    `SuspendThread` is the only Windows API that reveals the count, and it
    reveals it by incrementing it — so the probe SUSPENDS the thread for the
    few microseconds until `ResumeThread` undoes it. That side effect is real
    and is accepted deliberately: it is the price of the only instrument that
    does not lie (a1's POC ran it against a live 16-process claude tree on all
    18 samples of a 12-minute freeze with no ill effect).

    Reading `> 0` means the thread was ALREADY suspended by someone else.
    """
    if not _IS_WINDOWS:
        return None
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenThread.restype = ctypes.c_void_p
    k32.SuspendThread.restype = ctypes.c_ulong
    k32.ResumeThread.restype = ctypes.c_ulong
    k32.CloseHandle.argtypes = [ctypes.c_void_p]

    h = k32.OpenThread(_THREAD_SUSPEND_RESUME, False, tid)
    if not h:
        return None
    try:
        prev = k32.SuspendThread(ctypes.c_void_p(h))
        if prev == _SUSPEND_ERROR:
            return None
        # Undo the probe IMMEDIATELY: the count is now prev+1, and this
        # returns it to prev. A probe that measured must never be a probe
        # that changed what it measured.
        k32.ResumeThread(ctypes.c_void_p(h))
        return int(prev)
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def process_freeze_state(pid: int) -> str:
    """`frozen` | `running` | `mixed` | `gone` | `unknown` for ONE pid,
    measured now, from thread suspend counts — never from `psutil.status()`.

    `mixed` is a real answer, not an error: a tree caught mid-suspend has it.
    `unknown` means no thread could be probed (access denied / raced) — an
    instrument that cannot see is never allowed to report `running`.
    """
    try:
        proc = psutil.Process(pid)
        tids = [t.id for t in proc.threads()]
    except psutil.NoSuchProcess:
        return "gone"
    except Exception:  # noqa: BLE001 — AccessDenied / OSError: cannot tell
        return "unknown"
    if not tids:
        return "unknown"
    counts = [_thread_prev_suspend_count(t) for t in tids]
    seen = [c for c in counts if c is not None]
    if not seen:
        return "unknown"
    if all(c > 0 for c in seen):
        return "frozen"
    if all(c == 0 for c in seen):
        return "running"
    return "mixed"


def tree_pids(pid: int) -> list[int]:
    """Snapshot of `pid` + every descendant, root FIRST. Snapshotting before
    acting matters for the same reason it does in `kill_process_tree`: once
    the root is frozen its children can still be enumerated, but a tree read
    after a partial teardown is a different tree."""
    try:
        root = psutil.Process(pid)
    except (psutil.NoSuchProcess, ValueError):
        return []
    try:
        kids = root.children(recursive=True)
    except psutil.NoSuchProcess:
        kids = []
    return [pid, *[k.pid for k in kids]]


def fingerprint_matches(pid: int | None, create_time: float | None) -> tuple[bool, str]:
    """May we SIGNAL this pid? Fail-closed, and deliberately as strict as
    `service._proc_kill_allowed`: a suspend is as irreversible-in-the-wrong-
    hands as a kill (a frozen process cannot be asked whether it minded).

    A missing `create_time` is a REFUSAL, not a best-effort pid match. Pids are
    recycled; suspending a recycled pid freezes an innocent process that
    nothing will ever resume.
    """
    if not pid:
        return False, "no pid"
    if create_time is None:
        return False, "no recorded create_time — cannot defeat pid reuse"
    try:
        live = psutil.Process(pid).create_time()
    except Exception:  # noqa: BLE001 — NoSuchProcess / bad pid
        return False, f"pid {pid} is already gone"
    if abs(live - create_time) >= _CREATE_TIME_TOLERANCE_SECS:
        return False, (
            f"pid {pid} create_time mismatch (recorded {create_time!r}, "
            f"live {live!r}) — the pid was reused by a different process"
        )
    return True, f"pid {pid} fingerprint matched"


def observe_tree_state(pid: int, create_time: float | None = None) -> dict:
    """MEASURE, right now, whether `pid`'s tree is frozen. F0's whole point.

    Returns `{"state", "frozen", "measured_at", "instrument", "pids", ...}`.
    `frozen` is `True` only when EVERY probeable process in the tree reads
    `frozen`; a tree with one running process is `mixed`, never `frozen`.

    NOTHING here reads a stored flag, and nothing here writes one. Callers that
    want to show a user "this shell is paused" must call this and show what it
    returns. `state == "unknown"` is a legitimate answer and must be rendered
    as unknown — an instrument that cannot see must not report a clean result.
    """
    fp_ok, fp_why = (True, "not checked")
    if create_time is not None:
        fp_ok, fp_why = fingerprint_matches(pid, create_time)
        if not fp_ok:
            return {
                "pid": pid, "state": "unknown", "frozen": None,
                "fingerprint_ok": False, "fingerprint": fp_why,
                "measured_at": _utc_now_iso(),
                "instrument": "thread-suspend-count", "pids": [],
            }
    pids = tree_pids(pid)
    if not pids:
        return {
            "pid": pid, "state": "gone", "frozen": False,
            "fingerprint_ok": fp_ok, "fingerprint": fp_why,
            "measured_at": _utc_now_iso(),
            "instrument": "thread-suspend-count", "pids": [],
        }
    rows = [{"pid": p, "state": process_freeze_state(p)} for p in pids]
    # A child that died mid-read is not evidence about the freeze.
    live = [r["state"] for r in rows if r["state"] != "gone"]
    if not live:
        state = "gone"
    elif all(s == "frozen" for s in live):
        state = "frozen"
    elif all(s == "running" for s in live):
        state = "running"
    elif any(s == "unknown" for s in live) and not any(
            s in ("frozen", "mixed") for s in live):
        state = "unknown"
    else:
        state = "mixed"
    return {
        "pid": pid, "state": state, "frozen": state == "frozen",
        "fingerprint_ok": fp_ok, "fingerprint": fp_why,
        "measured_at": _utc_now_iso(),
        "instrument": "thread-suspend-count", "pids": rows,
    }


def _signal_tree(pids: list[int], action: str) -> list[int]:
    """`suspend` or `resume` each pid; return the ones actually signalled.
    A pid that vanished mid-sweep is skipped, never an error."""
    done = []
    for p in pids:
        try:
            proc = psutil.Process(p)
            getattr(proc, action)()
            done.append(p)
        except psutil.NoSuchProcess:
            continue
        except Exception:  # noqa: BLE001 — AccessDenied on a system child
            continue
    return done


def suspend_tree(
    pid: int, create_time: float | None, *,
    token_dir=None, deadline_secs: float = 1800.0,
    arm_watchdog: bool = True, launch_fn=None,
) -> dict:
    """Freeze `pid`'s whole tree. Idempotent. Returns a dict carrying the
    MEASURED post-condition — never a claim that isn't observed.

    Order of operations, each one load-bearing:

    1. FINGERPRINT OR REFUSE. `pid` must still carry the `create_time` the pool
       recorded at spawn. Nothing else may be suspended, ever.
    2. ARM THE WATCHDOG *FIRST*, and REFUSE THE WHOLE SUSPEND IF IT WILL NOT
       LAUNCH. A suspend you cannot undo is a leak: the shell stays frozen
       forever holding its pool spawn-lock, and R5 forbids force-failing it.
       An unwatched freeze is worse than no freeze.
    3. Root first, then descendants — a frozen root cannot spawn a child that
       escapes the sweep.
    4. VERIFY BY MEASUREMENT. If the tree does not read `frozen`, UNDO
       everything and report failure. We never return "paused" on faith.
    """
    ok, why = fingerprint_matches(pid, create_time)
    if not ok:
        return {"ok": False, "refused": why, "observed": None}

    already = observe_tree_state(pid)
    if already["state"] == "frozen":
        # IDEMPOTENT — but "already frozen" is NOT automatically "already
        # watched". A tree frozen out-of-band (an earlier pool process, a
        # crashed observer, a human with a debugger) has NO run token and
        # NOTHING under it. Returning ok here would report a paused shell whose
        # freeze nobody can undo — precisely the leak the watchdog exists to
        # prevent, reached through the one branch written to be a harmless
        # no-op. So: check for the token, and ADOPT an orphaned freeze.
        from .pause_watchdog import arm as _arm
        from .pause_watchdog import read_token
        if not arm_watchdog or read_token(token_dir, pid) is not None:
            return {"ok": True, "idempotent": True, "adopted": False,
                    "runid": None, "watchdog": None, "observed": already,
                    "note": "tree was already frozen and its run token is "
                            "held — nothing signalled"}
        runid = uuid.uuid4().hex
        wd = _arm(token_dir=token_dir, pid=pid, create_time=create_time,
                  runid=runid, deadline_secs=deadline_secs, launch_fn=launch_fn)
        if not wd.get("ok"):
            # We did not create this freeze, so we do not silently undo it.
            # We report it, loudly, as what it is.
            return {"ok": False, "observed": already, "watchdog": wd,
                    "refused": (
                        "tree is ALREADY FROZEN AND UNWATCHED (no run token) "
                        f"and a watchdog would not launch ({wd.get('error')}). "
                        "Nothing is holding a resume for it — resume it "
                        "explicitly.")}
        return {"ok": True, "idempotent": True, "adopted": True,
                "runid": runid, "watchdog": wd, "observed": already,
                "note": "tree was already frozen but UNWATCHED; adopted it and "
                        "armed an auto-resume watchdog"}

    pids = tree_pids(pid)
    if not pids:
        return {"ok": False, "refused": f"pid {pid} vanished", "observed": None}

    runid = uuid.uuid4().hex
    watchdog = None
    if arm_watchdog:
        from .pause_watchdog import arm
        watchdog = arm(
            token_dir=token_dir, pid=pid, create_time=create_time,
            runid=runid, deadline_secs=deadline_secs, launch_fn=launch_fn,
        )
        if not watchdog.get("ok"):
            return {
                "ok": False, "observed": None, "watchdog": watchdog,
                "refused": (
                    "the out-of-tree auto-resume watchdog would not launch "
                    f"({watchdog.get('error')}); refusing to suspend — an "
                    "unresumable freeze holds the shell's pool lock forever"
                ),
            }

    # BEFORE the freeze: a suspended window blocks on WM_SETTEXT. See the
    # window-title section below for the measurement.
    title = mark_window_title(pid, pids)

    _signal_tree(pids, "suspend")
    observed = observe_tree_state(pid)
    if observed["state"] != "frozen":
        # Undo. A partial freeze is the worst state to leave a shell in.
        _signal_tree(list(reversed(pids)), "resume")
        restore_window_title(pid, pids)
        if arm_watchdog:
            from .pause_watchdog import disarm
            disarm(token_dir=token_dir, pid=pid, runid=runid)
        return {
            "ok": False, "observed": observe_tree_state(pid),
            "watchdog": watchdog,
            "refused": (
                f"tree did not verify as frozen (measured {observed['state']!r}"
                "); suspension was rolled back"
            ),
        }

    return {"ok": True, "idempotent": False, "runid": runid,
            "watchdog": watchdog, "observed": observed, "window_title": title}


def resume_tree(pid: int, create_time: float | None, *,
                token_dir=None, runid: str | None = None) -> dict:
    """Unfreeze `pid`'s tree, then release the watchdog's run token LAST.

    Descendants first, root last (the mirror of suspend). Resuming an already-
    running process is a no-op at the OS level, so this is safe to call twice
    and safe to call late — which is exactly why the watchdog is allowed to
    fire on a freeze that already ended.

    THE TOKEN IS RELEASED LAST, AFTER the resume is measured. If this process
    is killed between the resume and the release, the watchdog is still armed
    and will fire harmlessly on an already-running tree. The reverse ordering
    would leave a frozen shell with nothing watching it.
    """
    ok, why = fingerprint_matches(pid, create_time)
    if not ok:
        # The pid is gone: nothing to resume, and the token must not outlive
        # the target it names.
        from .pause_watchdog import disarm
        disarm(token_dir=token_dir, pid=pid, runid=runid)
        return {"ok": True, "note": f"nothing to resume: {why}",
                "observed": None, "token_released": True}

    pids = tree_pids(pid)
    _signal_tree(list(reversed(pids)), "resume")
    observed = observe_tree_state(pid)
    restore_window_title(pid, pids)

    released = False
    if observed["state"] in ("running", "gone", "mixed", "unknown"):
        from .pause_watchdog import disarm
        released = disarm(token_dir=token_dir, pid=pid, runid=runid)
    if observed["state"] == "frozen":
        return {"ok": False, "observed": observed, "token_released": False,
                "refused": "tree still measures as frozen after resume"}
    return {"ok": True, "observed": observed, "token_released": released}


# ── W12 / a1 §6.3: make the freeze LEGIBLE at the shell ──────────────────
#
# The user force-closed a1's first fixture because a process-suspended
# monitor-mode shell presents to an operator EXACTLY as a hung one: frozen
# window, no output, no sign the freeze is intentional. That is not cosmetic —
# it destroyed a 12-minute measurement and nearly produced a finding that would
# have refuted the whole mechanism.
#
# THE POOL WRITES ITS OWN CHILD'S WINDOW TITLE, FROM OUTSIDE. This injects no
# code into the Claude Code shell and adds no in-shell affordance: it is
# LEGIBILITY, NOT CONTROL. DESIGN-v6's W12 non-goal ("no controls injected
# inside Claude Code shells") is the user's own and is not crossed here — a
# window title is not a control; a status line inside the shell would be.
#
# Only VISIBLE windows owned by a pid in the ALREADY-FINGERPRINT-VERIFIED tree
# are touched. Every failure is swallowed: a title is a courtesy, and it must
# never be the reason a pause fails or a resume is refused.
#
# TWO THINGS MEASURED HERE, BOTH OF WHICH CHANGED THE CODE:
#
# 1. THE TITLE MUST BE WRITTEN *BEFORE* THE FREEZE. `SetWindowTextW` on another
#    process's window sends `WM_SETTEXT` and BLOCKS on the target thread. Probed
#    against a real suspended console: it did not return in 6 seconds. Marking
#    after the suspend would hang a pool worker thread on every pause of a
#    monitor-mode shell — the pause endpoint would freeze the pool.
#
# 2. EVEN SO, NEVER USE THE BLOCKING CALL. Every write goes through
#    `SendMessageTimeoutW(..., SMTO_ABORTIFHUNG, 500ms)`, which returned 0 in
#    0.51 s against that same frozen window instead of hanging. A window that
#    will not accept the text is an honest `marked: 0`, never a stall.
#
# `GetWindowTextW` is safe by design (it reads the caption from the window
# structure for cross-process windows rather than sending `WM_GETTEXT`), so
# reading a frozen title does not hang.

_TITLE_PREFIX = "[EDP PAUSED] "
_saved_titles: dict[int, str] = {}

_WM_SETTEXT = 0x000C
_SMTO_ABORTIFHUNG = 0x0002
_TITLE_TIMEOUT_MS = 500


def _user32():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.SendMessageTimeoutW.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_wchar_p,
        ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
    u.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    u.IsWindowVisible.argtypes = [ctypes.c_void_p]
    u.IsWindowVisible.restype = ctypes.c_bool
    return u


def _set_title(u, hwnd: int, text: str) -> bool:
    """WM_SETTEXT with a hard timeout. NEVER `SetWindowTextW` — see above."""
    out = ctypes.c_size_t(0)
    rc = u.SendMessageTimeoutW(ctypes.c_void_p(hwnd), _WM_SETTEXT, None, text,
                               _SMTO_ABORTIFHUNG, _TITLE_TIMEOUT_MS,
                               ctypes.byref(out))
    return rc != 0


def _tree_windows(pids: list[int]) -> list[tuple[int, int]]:
    """`(hwnd, pid)` for every VISIBLE top-level window owned by a pid in
    `pids`. Empty on non-Windows, and empty for a headless ConPTY shell — which
    has no window at all. That absence is reported honestly by the caller.

    The visibility filter is not cosmetic: a console's owning `conhost.exe` also
    owns invisible `MSCTFIME UI` / `Default IME` helper windows, and an
    unfiltered sweep renamed all three."""
    if not _IS_WINDOWS or not pids:
        return []
    wanted = set(pids)
    found: list[tuple[int, int]] = []
    try:
        u = _user32()
        cb_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def _cb(hwnd, _lparam):
            owner = ctypes.c_ulong(0)
            u.GetWindowThreadProcessId(
                ctypes.c_void_p(hwnd), ctypes.byref(owner))
            if owner.value in wanted and u.IsWindowVisible(hwnd):
                found.append((hwnd, owner.value))
            return True

        u.EnumWindows(cb_type(_cb), 0)
    except Exception:  # noqa: BLE001
        return []
    return found


def mark_window_title(pid: int, pids: list[int]) -> dict:
    """Prefix the shell's console-window title so a human can tell an
    intentional freeze from a hang. CALL THIS BEFORE SUSPENDING — a frozen
    window cannot accept `WM_SETTEXT`.

    `{"marked": 0, "reason": ...}` is an HONEST NEGATIVE, not a failure: a
    headless shell has no window, and a shell already frozen by someone else
    cannot be marked at all."""
    wins = _tree_windows(pids)
    if not wins:
        return {"marked": 0, "reason": "no visible window in this tree "
                "(headless ConPTY shells have none)"}
    marked = 0
    try:
        u = _user32()
        for hwnd, _owner in wins:
            buf = ctypes.create_unicode_buffer(512)
            u.GetWindowTextW(ctypes.c_void_p(hwnd), buf, 512)
            current = buf.value or ""
            if current.startswith(_TITLE_PREFIX):
                continue
            if _set_title(u, hwnd, _TITLE_PREFIX + current):
                _saved_titles[hwnd] = current
                marked += 1
    except Exception as exc:  # noqa: BLE001
        return {"marked": marked, "reason": f"title write failed: {exc!r}"}
    return {"marked": marked, "reason": "" if marked else
            "window found but the title write did not take (frozen or hung)"}


def restore_window_title(pid: int, pids: list[int]) -> dict:
    """Put back whatever title we replaced. CALL THIS AFTER RESUMING. A title we
    never saved is left alone — we do not invent one."""
    wins = _tree_windows(pids)
    restored = 0
    try:
        u = _user32()
        for hwnd, _owner in wins:
            old = _saved_titles.pop(hwnd, None)
            if old is None:
                continue
            if _set_title(u, hwnd, old):
                restored += 1
    except Exception:  # noqa: BLE001
        pass
    return {"restored": restored}


def kill_process_tree(pid: int | None, grace: float = 3.0) -> int:
    """Terminate `pid` and ALL its descendants; return the count signalled.

    Snapshots the subtree BEFORE killing anything — once the root dies its
    children reparent and the tree is lost. Graceful `terminate()` first,
    then force-`kill()` whatever survives `grace` seconds.
    """
    if pid is None:
        return 0
    try:
        root = psutil.Process(pid)
    except (psutil.NoSuchProcess, ValueError):
        return 0
    try:
        procs = root.children(recursive=True)   # snapshot the subtree FIRST
    except psutil.NoSuchProcess:
        procs = []
    procs.append(root)
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(procs, timeout=grace)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    return len(procs)
