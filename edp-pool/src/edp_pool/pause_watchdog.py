"""Out-of-tree auto-resume watchdog for W12's process-suspend pause.

A SUSPEND YOU CANNOT UNDO IS A LEAK. The frozen shell holds its pool spawn-lock
forever, and R5 forbids force-failing it — so nothing can reclaim the action.
The watchdog is the net under `suspend_tree`, and `suspend_tree` REFUSES TO
SUSPEND AT ALL if this net will not launch.

Two properties, both learned the hard way in a1's POC, both non-obvious:

1. THE WATCHDOG MUST LIVE OUTSIDE THE TREE — and `DETACHED_PROCESS` is not
   enough. A detached child is still a DESCENDANT, so `TaskStop` and
   `kill_process_tree` (which walks descendants) take it down at exactly the
   moment it is needed: the crash it exists to survive. Observed directly. So
   it is launched via WMI `Win32_Process.Create`, which reparents it to
   `WmiPrvSE`, and the result is VERIFIED not-a-descendant rather than assumed.
   It also outlives a pool restart, which a pool-child watchdog would not.

2. IT CARRIES A RUN TOKEN, and the token — not a timer — decides whether it
   fires. A watchdog armed by an earlier 70-second probe once fired 43 seconds
   into a live 12-minute freeze and silently resumed the target, while the
   sampler kept printing `frozen`. That is the feature failing in its worst
   direction: the panel says "paused", the tokens burn, and the one person the
   feature exists for is the last to know.

   The token file holds the RUNID of the freeze in progress:

     * MISSING              -> the freeze ended cleanly. STAND DOWN.
     * PRESENT, DIFFERENT   -> a later freeze owns the target. STAND DOWN.
     * PRESENT, MINE        -> the observer died. FIRE.

   `resume()` on a running process is a no-op at the OS level, so FIRING LATE
   IS ALWAYS SAFE. REFUSING TO FIRE IS NOT. When the two errors are asymmetric,
   bias toward the recoverable one.

   The token is released LAST, after the resume (`resume_tree`), so a kill
   between the resume and the release still leaves the watchdog armed.
"""

import argparse
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil

_TOKEN_DIR_ENV = "EDP_POOL_PAUSE_TOKENS"
_DEFAULT_TOKEN_DIR = Path(".pool-logs") / "pause-tokens"
# How often the armed watchdog re-reads its token while waiting. Standing down
# early (token gone / superseded) is the same ruling as standing down at the
# deadline — it just costs less.
_POLL_SECS = 5.0


def token_dir_path(token_dir=None) -> Path:
    if token_dir is not None:
        return Path(token_dir)
    return Path(os.environ.get(_TOKEN_DIR_ENV, str(_DEFAULT_TOKEN_DIR)))


def token_path(token_dir, pid: int) -> Path:
    """One token per TARGET pid — not per freeze. That is what lets a later
    freeze supersede an earlier freeze's watchdog: they contend for the same
    file, and the runid inside it names the winner."""
    return token_dir_path(token_dir) / f"pause-{pid}.owner"


def read_token(token_dir, pid: int) -> str | None:
    try:
        return token_path(token_dir, pid).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def write_token(token_dir, pid: int, runid: str) -> Path:
    p = token_path(token_dir, pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(runid, encoding="utf-8")
    return p


def should_fire(token_dir, pid: int, runid: str) -> tuple[bool, str]:
    """The watchdog's whole decision, as a pure function of the token.

    Deliberately NOT a function of elapsed time, process state, or anything the
    watchdog could observe about the target. A stale watchdog that reasons from
    what it SEES will resume a freeze it was never armed for — that is the
    43-second incident, exactly.
    """
    current = read_token(token_dir, pid)
    if current is None:
        return False, "run token is gone — the freeze ended cleanly; stand down"
    if current != runid:
        return False, (
            f"run token names a different freeze ({current!r} != {runid!r}) — "
            "a later freeze owns this target; stand down"
        )
    return True, (
        f"run token {runid!r} is still mine at the deadline — the observer "
        "died without resuming; fire"
    )


def disarm(token_dir, pid: int, runid: str | None = None) -> bool:
    """Release the run token. Returns True if THIS freeze's token was removed.

    A token naming a DIFFERENT runid is left alone: a later freeze owns the
    target, and deleting its token would disarm the net under a live freeze.
    `runid=None` removes whatever is there (the pid-is-gone path — a token must
    never outlive the target it names).
    """
    path = token_path(token_dir, pid)
    current = read_token(token_dir, pid)
    if current is None:
        return False
    if runid is not None and current != runid:
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _ps_quote(s: str) -> str:
    """Escape for a PowerShell single-quoted literal."""
    return str(s).replace("'", "''")


def _wmi_launch(cmdline: str, cwd: str) -> int:
    """Create a process OUT OF THIS PROCESS TREE via WMI `Win32_Process.Create`
    and return its pid. The transient `powershell.exe` IS our child; the process
    IT creates is parented to `WmiPrvSE`, which is the entire point.

    Raises on any failure — `arm` turns that into a refusal to suspend.
    """
    ps = (
        # ShowWindow=0 (SW_HIDE): without ProcessStartupInformation the
        # WMI-created console-subsystem child gets a fresh VISIBLE console
        # window parented to WmiPrvSE — the "sidecar shell popping out of
        # nowhere" the operator reported (2026-08-13). The watchdog is a
        # sidecar; it must never own a window.
        "$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly "
        "-Property @{ShowWindow=[uint16]0}; "
        "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        f"-Arguments @{{CommandLine='{_ps_quote(cmdline)}'; "
        f"CurrentDirectory='{_ps_quote(cwd)}'; ProcessStartupInformation=$si}}; "
        "if ($r.ReturnValue -ne 0) { Write-Error \"Create returned "
        "$($r.ReturnValue)\"; exit 2 }; Write-Output $r.ProcessId"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True, timeout=60, check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return int(out.stdout.strip().splitlines()[-1])


def _descendant_pids_of(pid: int) -> set[int]:
    try:
        return {p.pid for p in psutil.Process(pid).children(recursive=True)}
    except Exception:  # noqa: BLE001
        return set()


def arm(*, token_dir, pid: int, create_time: float | None, runid: str | None = None,
        deadline_secs: float = 1800.0, launch_fn=None) -> dict:
    """Write the run token, launch the watchdog OUT OF TREE, and VERIFY it
    landed outside. Never raises — returns `{"ok": False, "error": ...}` so
    `suspend_tree` can refuse the suspend rather than freeze an unwatched shell.
    """
    runid = runid or uuid.uuid4().hex
    deadline_epoch = time.time() + float(deadline_secs)
    tok = write_token(token_dir, pid, runid)

    py = sys.executable
    cwd = str(Path(__file__).resolve().parents[2])   # the edp-pool repo root
    cmdline = (
        f'"{py}" -m edp_pool.pause_watchdog '
        f'--token-dir "{token_dir_path(token_dir)}" '
        f'--pid {pid} --create-time {create_time!r} --runid {runid} '
        f'--deadline-epoch {deadline_epoch!r}'
    )
    launch = launch_fn or _wmi_launch
    try:
        wd_pid = launch(cmdline, cwd)
    except Exception as exc:  # noqa: BLE001 — no watchdog ⇒ no suspend
        disarm(token_dir, pid, runid)
        return {"ok": False, "error": f"watchdog launch failed: {exc!r}",
                "token": str(tok)}

    # VERIFY out-of-tree. Do not assume WMI reparented it: a watchdog inside
    # our own tree dies with us, which is the one crash it exists to survive.
    mine = _descendant_pids_of(os.getpid())
    if wd_pid in mine or wd_pid == os.getpid():
        try:
            psutil.Process(wd_pid).kill()
        except Exception:  # noqa: BLE001
            pass
        disarm(token_dir, pid, runid)
        return {"ok": False, "watchdog_pid": wd_pid, "out_of_tree": False,
                "error": "watchdog landed INSIDE the pool's process tree; "
                         "it would die with the crash it exists to survive",
                "token": str(tok)}

    return {"ok": True, "watchdog_pid": wd_pid, "out_of_tree": True,
            "runid": runid, "token": str(tok),
            "deadline_epoch": deadline_epoch}


def _wait_then_decide(token_dir, pid: int, runid: str,
                      deadline_epoch: float) -> tuple[bool, str]:
    while time.time() < deadline_epoch:
        fire, why = should_fire(token_dir, pid, runid)
        if not fire:
            return False, why          # superseded / released early
        time.sleep(min(_POLL_SECS, max(0.1, deadline_epoch - time.time())))
    return should_fire(token_dir, pid, runid)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="edp_pool.pause_watchdog")
    ap.add_argument("--token-dir", required=True)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--create-time", required=True)
    ap.add_argument("--runid", required=True)
    ap.add_argument("--deadline-epoch", type=float, required=True)
    a = ap.parse_args(argv)

    ct = None if a.create_time in ("None", "none", "") else float(a.create_time)
    fire, why = _wait_then_decide(
        a.token_dir, a.pid, a.runid, a.deadline_epoch)
    if not fire:
        print(f"stand down: {why}")
        return 0

    # Fire. `resume_tree` re-checks the fingerprint, so a recycled pid is
    # refused here exactly as it would be on the pool's own resume path.
    from .proctree import resume_tree
    res = resume_tree(a.pid, ct, token_dir=a.token_dir, runid=a.runid)
    print(f"fired: {why}; resume -> {res.get('ok')} "
          f"state={(res.get('observed') or {}).get('state')}")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
