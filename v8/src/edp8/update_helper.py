"""The detached update helper (strategyhl-86b4805322 §4 steps 4-7; S3 s-870e401942).

`heronry update` copies this file into the private run dir and starts it with the base interpreter,
outside the tool venv, then exits: `uv tool install --force` cannot replace a venv any live process has
loaded (measured os error 32). This file is stdlib-only for that reason and imports nothing from edp8.

Plan (JSON, written by the updater): ``caller_pid``, ``install_argv``, ``rollback_install_argv`` (or
null), ``start_argv``, ``stop_argv``, ``health_url``, ``db``, ``backup``, ``log``, ``result``,
``from_version``, ``to_version``, ``recover_hint``. Steps: wait for the caller to exit → install → start →
health; any failure → stop, reinstall the previous artefacts when cached, restore the pre-update DB
backup (when one was taken), start. The outcome is written to ``result`` on every path, a crash included:
``ok``, ``rolled_back`` (only when the previous code was reinstalled and came up) or ``failed`` (with
``recover_hint``). Every step goes to ``log``.

``--compat <plan>`` runs the release's compatibility check (``compat_argv``, a ``uv tool run``) before anything
stops and writes ``{rc, stdout, stderr}`` to ``compat_out``, on every path: the installed app never launches uv
as its own child (owner AV ruling m-631a9ad2a7), so this helper is the only runtime uv caller.

A plan with ``kind: "msi"`` (S2 spike s-725ef36c03, design-b6a55eed13 §4.G) is the desktop bundle's update. The
updater copies this file AND the bundle's Python runtime to ``<home>\\update\\`` and runs it from there, so no
process of the update holds a file in the install folder. Steps: wait for the caller → park the live seats
(pool ``/v1/park``) → stop the services (the installed ``heronry.exe stop --force``) → wait until the Restart
Manager reports no process holding a file in the install folder → ``msiexec /i <new.msi> /qn`` (per-user, the same
INSTALLFOLDER; never an uninstall) → start the services (+ the app) → health 200 at the new version → resume the
parked seats. On a failure the previous version is put back: Windows Installer already rolled a failed msiexec
back, so the runner only relaunches it; a new version that installed but did not come up healthy is removed and
the cached previous MSI reinstalled. ``result`` carries ``state`` (ok | rolled_back | failed), a plain ``reason``,
``timings`` and ``parked``/``resumed``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

try:
    from . import update_lock
except ImportError:  # run as a script from the staging dir (update_lock.py sits beside it)
    # the bundle's stub runs a script through runpy, which does not put the script's folder on the path; 0.10.2's
    # stub did not either, and its `heronry update` died here (owner m-8b37e6b58e), so the helper adds it itself
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import update_lock  # type: ignore[no-redef]


def _prog(plan: dict, step: str, detail: str = "") -> None:
    """A visible step (the lock's step, the progress file, the window); best effort."""
    if plan.get("update_dir"):
        try:
            update_lock.progress(Path(plan["update_dir"]), step, detail)
        except Exception:  # noqa: BLE001 -- progress is never a reason to stop
            pass


def _lock_join(plan: dict) -> None:
    """Join the caller's update lock (so it stays live when the caller exits), carry its token in the environment
    so this helper's own `heronry start` passes the guard, and open the progress window."""
    if not plan.get("update_dir"):
        return
    try:
        if plan.get("lock_token"):
            os.environ[update_lock.TOKEN_ENV] = plan["lock_token"]
        update_lock.join(Path(plan["update_dir"]), plan.get("lock_token"))
        _open_window(plan)
    except Exception as e:  # noqa: BLE001
        _log(plan, f"update lock/window not set up ({type(e).__name__}: {e})")


def _prog_final(plan: dict, state: str, reason: str) -> None:
    """The result line, then the lock is released: from here services may start."""
    if not plan.get("update_dir"):
        return
    d = Path(plan["update_dir"])
    try:
        update_lock.progress(d, "result", f"{state}" + (f": {reason}" if reason else ""), final=True)
    finally:
        update_lock.release(d)


def _open_window(plan: dict) -> None:
    """A visible console that follows the progress file until the result (never hidden)."""
    if sys.platform != "win32" or plan.get("no_window"):
        return
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--view",
                      str(Path(plan["update_dir"]) / update_lock.PROGRESS_NAME)],
                     creationflags=0x00000010)  # CREATE_NEW_CONSOLE: its own visible window
    _log(plan, "progress window opened")


def view(progress_file: str, *, pid: int = 0, created: float = 0.0, inline: bool = False,
         result_file: str = "") -> int:
    """Follow the progress file: print each step with its elapsed time, then the result.

    The window (`inline` False, an update started from the tray) waits for a key at the end. `inline` is the shell
    that typed `heronry update` (owner m-584d63e760): bin/heronry.cmd runs this from the copy outside the install
    folder, so the shell waits through install or rollback; it exits 0 when the update installed, else 1, after the
    result's recovery line. With `pid` (the helper), a helper that ends without writing a result is said so within
    seconds instead of a wait for a line that never comes."""
    print("Heronry update: " + ("this shell returns when it is done." if inline else
                                "do not close this window; it ends with the result.") + "\n", flush=True)
    seen, deadline, gone_at = 0, time.monotonic() + 3 * 3600, None
    while time.monotonic() < deadline:
        try:
            lines = Path(progress_file).read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for raw in lines[seen:]:
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            print(update_lock.format_line(rec), flush=True)
            if rec.get("final"):
                return _view_end(str(rec.get("detail") or ""), inline, result_file)
        seen = len(lines)
        if pid and not _alive(pid, created):
            gone_at = gone_at or time.monotonic()
            if time.monotonic() - gone_at > 3.0:  # a last line may still be on its way
                print("\nThe update helper ended without a result. Heronry may be stopped: run `heronry status`, "
                      "and `heronry start` if the services are down. Its log: "
                      + os.path.expandvars("%LOCALAPPDATA%\\heronry\\Logs\\update.log"),
                      flush=True)
                return _view_end("", inline, result_file, code=1)
        time.sleep(0.5)
    return 1


def _view_end(detail: str, inline: bool, result_file: str, code: int | None = None) -> int:
    ok = detail.split(":", 1)[0].strip() in ("ok", "incomplete")  # incomplete: installed, a seat did not resume
    hint = ""
    if not ok and result_file:
        try:
            hint = str(json.loads(Path(result_file).read_text(encoding="utf-8")).get("recover_hint") or "")
        except (OSError, ValueError):
            hint = ""
    if detail:
        print("\n" + ("Updated." if ok else "The update did not install.") + (f" If Heronry does not come back: {hint}"
                                                                                if hint else ""), flush=True)
    if not inline:
        try:
            input("\nPress Enter to close.")
        except EOFError:
            time.sleep(30)
    return (0 if ok else 1) if code is None else code


def _alive(pid: int, created: float = 0.0) -> bool:
    """The helper still runs: its pid is live, has not exited, and (with `created`) is the same process."""
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return False
    finally:
        k32.CloseHandle(h)
    if created:
        ident = _proc_identity(pid)
        return ident is not None and abs(ident[0] - created) < 2.0
    return True


def _log(plan: dict, text: str) -> None:
    """Best effort (S13 F2): the log is diagnostics, never a step. A log that cannot be written must not stop the
    helper between stopping the old install and bringing a version back up."""
    try:
        with open(plan["log"], "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(UTC).isoformat(timespec='seconds')} {text}\n")
    except (OSError, KeyError):
        pass


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000 | 0x00100000, False, pid)  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _run(plan: dict, what: str, argv: list[str] | None, timeout: float = 900.0) -> bool:
    if not argv:
        return True
    _prog(plan, what)
    _log(plan, f"{what}: {' '.join(argv)}")
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        _log(plan, f"{what} failed: {e}")
        return False
    for line in (r.stdout + r.stderr).splitlines()[-40:]:
        _log(plan, f"  | {line}")
    _log(plan, f"{what} exit {r.returncode}")
    return r.returncode == 0


def _healthy(url: str, wait_s: float = 90.0) -> bool:
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310  # nosec B310  # loopback URL from our own plan
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1.0)
    return False


def _post_event(plan: dict, state: str, reason: str) -> None:
    """Best effort: the outcome on the board's event log (POST /v1/service_event, admin token from its file; never
    logged), so the feed and the tray's board panel show the reason string. A board that is down, or an older one
    without the route, is skipped: update-result.json is the record."""
    board, tok_f = plan.get("board_url"), plan.get("admin_token_file")
    if not board or not tok_f or not plan.get("board_ours"):  # the token goes only to this home's own board
        return
    try:
        token = Path(tok_f).read_text(encoding="utf-8").strip()
        why = f"update {plan['from_version']} -> {plan['to_version']}: {state}" + (f": {reason}" if reason else "")
        _http(f"{board}/v1/service_event", "POST", timeout=10, token=token,
              body={"service": "app", "reason": why[:900], "by": "updater", "git_rev": plan["to_version"]})
    except (OSError, ValueError, KeyError) as e:
        try:
            _log(plan, f"board event not recorded ({type(e).__name__})")
        except OSError:
            pass


def _db_marker(path: Path) -> tuple | None:
    """The DB's schema and migration marker: (PRAGMA user_version, a digest of every table/index/trigger/view
    definition). None when the file cannot be read (a missing or damaged DB is never judged unchanged)."""
    import sqlite3
    try:
        con = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None
    try:
        ver = con.execute("PRAGMA user_version").fetchone()[0]
        rows = con.execute("SELECT type, name, tbl_name, COALESCE(sql, '') FROM sqlite_master ORDER BY type, name").fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return ver, hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()


def _restore(plan: dict) -> str:
    """Put the pre-update DB backup back only when the new version changed the DB (its schema or migration marker
    differs from the backup's); otherwise keep the rows written during the update. Returns "restored", "kept" or
    "none", and records which in plan["_db"] for the receipt."""
    if not plan.get("backup"):  # no DB existed before the update, so none was backed up (S11 F5)
        _log(plan, "no DB backup was taken (no DB before the update); DB left as is")
        plan["_db"] = {"case": "none", "why": "no DB existed before the update; nothing to restore"}
        return "none"
    db, backup = Path(plan["db"]), Path(plan["backup"])
    live, was = _db_marker(db), _db_marker(backup)
    if live is not None and was is not None and live == was:
        why = "the new version did not change the DB schema or migration marker; rows written during the update kept"
        _log(plan, f"DB kept: {why}")
        plan["_db"] = {"case": "kept", "why": why}
        return "kept"
    why = ("the new version changed the DB schema or migration marker" if live is not None and was is not None else
           "the DB could not be compared with its backup")
    for side in ("-wal", "-shm"):
        db.with_name(db.name + side).unlink(missing_ok=True)
    shutil.copy2(backup, db)
    _log(plan, f"restored {db} from {backup}: {why}")
    plan["_db"] = {"case": "restored", "why": f"{why}; the pre-update backup was restored"}
    return "restored"


def main(plan_path: str) -> int:
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    result = {"from": plan["from_version"], "to": plan["to_version"], "state": "failed", "reason": ""}
    done: list[int] = []

    def finish(state: str, reason: str = "", **extra) -> int:
        result.update(extra)
        if plan.get("_db"):  # which DB case applied on a rollback: restored from the backup, or rows kept
            result.update(db_restore=plan["_db"]["case"], db_restore_reason=plan["_db"]["why"])
        result.update(state=state, reason=reason, recover_hint=plan.get("recover_hint") or "",
                      finished_at=datetime.now(UTC).isoformat(timespec="seconds"))
        Path(plan["result"]).write_text(json.dumps(result, indent=1), encoding="utf-8")
        done.append(0 if state == "ok" else 1)
        try:
            _log(plan, f"result {state} {reason}".rstrip())
        except OSError:
            pass
        _post_event(plan, state, reason)
        _prog_final(plan, state, reason)
        return done[-1]

    _lock_join(plan)
    try:
        return _steps(plan, finish)
    except BaseException as e:  # every terminal path writes an outcome (S11 F5), a crash included
        if not done:
            hint = plan.get("recover_hint") or "reinstall the previous version with the install script"
            finish("failed", f"the update helper crashed ({type(e).__name__}: {e}); {hint}")
        if isinstance(e, Exception):
            return 1
        raise


def _steps(plan: dict, finish) -> int:
    _log(plan, f"helper up (pid {os.getpid()}): {plan['from_version']} -> {plan['to_version']}")
    deadline = time.monotonic() + 120.0
    while _pid_alive(int(plan["caller_pid"])) and time.monotonic() < deadline:
        time.sleep(0.3)
    if _pid_alive(int(plan["caller_pid"])):
        return finish("failed", "the heronry process that started the update did not exit; nothing was changed")
    if plan.get("kind") == "msi":
        return _msi_steps(plan, finish)

    reason = ""
    if plan.get("code_running"):
        _stop_code(plan)  # a running code-server holds the tool environment and would keep the old extension
    if not _run(plan, "install", plan["install_argv"]):
        reason = "install failed"
    elif not _run(plan, "start", plan["start_argv"], timeout=300) or not (_prog(plan, "health check")
                                                                          or _healthy(plan["health_url"])):
        reason = "the new version did not come up healthy"
    else:
        _start_code(plan)
    parked = list(plan.get("parked") or [])  # S10 #7: the in-process apply parked them before it stopped anything
    if not reason:
        resumed = _resume(plan, parked)
        missing = _not_resumed(parked, resumed)
        if missing:  # S18-2: the install stays; the outcome names what did not come back
            return finish("incomplete", f"updated to {plan['to_version']}{_resume_note(missing)}", parked=parked,
                          resumed=resumed, resume_failed=missing)
        return finish("ok", parked=parked, resumed=resumed)

    _log(plan, f"rolling back: {reason}")
    _run(plan, "stop", plan["stop_argv"], timeout=300)
    hint = plan.get("recover_hint") or "reinstall the previous version with the install script"
    # rolled_back only when the previous code was reinstalled (S11 F7); anything short of that is failed
    reinstalled = bool(plan.get("rollback_install_argv")) and _run(plan, "reinstall previous",
                                                                    plan["rollback_install_argv"])
    note = "" if reinstalled else ("; reinstalling the previous version failed" if plan.get("rollback_install_argv")
                                   else "; the previous version's wheels were not cached, so it was not reinstalled")
    _restore(plan)
    up = _run(plan, "start previous", plan["start_argv"], timeout=300) and _healthy(plan["health_url"])
    if up:
        _start_code(plan)
    resumed = _resume(plan, parked) if up else []
    if reinstalled and up:
        return finish("rolled_back", reason, parked=parked, resumed=resumed)
    if not up:
        note += "; the rollback did not come up either"
    return finish("failed", f"{reason}{note}; {hint}", parked=parked, resumed=resumed)


# ------------------------------------------------------------------------------------------ msi (Windows)

def msi_property(path: str, name: str) -> str | None:
    """A Property-table value of the .msi at `path` (ProductVersion, UpgradeCode, ProductCode), None when the
    file is not a readable MSI database (a truncated or corrupt download fails here, before anything stops)."""
    import ctypes
    from ctypes import wintypes
    msi = ctypes.WinDLL("msi")
    db, view, rec = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
    try:
        if msi.MsiOpenDatabaseW(ctypes.c_wchar_p(path), None, ctypes.byref(db)):
            return None
        q = f"SELECT `Value` FROM `Property` WHERE `Property`='{name}'"
        if msi.MsiDatabaseOpenViewW(db, ctypes.c_wchar_p(q), ctypes.byref(view)) or msi.MsiViewExecute(view, 0):
            return None
        if msi.MsiViewFetch(view, ctypes.byref(rec)):
            return None
        size = wintypes.DWORD(512)
        buf = ctypes.create_unicode_buffer(size.value)
        if msi.MsiRecordGetStringW(rec, 1, buf, ctypes.byref(size)):
            return None
        return buf.value
    finally:
        for h in (rec, view, db):
            if h.value:
                msi.MsiCloseHandle(h)


def related_products(upgrade_code: str) -> list[dict]:
    """The installed products sharing `upgrade_code`: [{code, version}] (any scope this user sees)."""
    import ctypes
    from ctypes import wintypes
    msi = ctypes.WinDLL("msi")
    out, i = [], 0
    while True:
        code = ctypes.create_unicode_buffer(39)
        if msi.MsiEnumRelatedProductsW(ctypes.c_wchar_p(upgrade_code), 0, i, code):
            return out
        size = wintypes.DWORD(64)
        ver = ctypes.create_unicode_buffer(size.value)
        msi.MsiGetProductInfoW(code, ctypes.c_wchar_p("VersionString"), ver, ctypes.byref(size))
        out.append({"code": code.value, "version": ver.value})
        i += 1


def holders(folder: str, limit: int = 20, images_only: bool = False, log=None, tries: int = 3,
            pause_s: float = 0.5) -> list[str] | None:
    """Processes the Restart Manager sees holding any file under `folder` (open handles and loaded images):
    ["name (pid N)"], [] when none, None when the Restart Manager could not answer `tries` times running.
    `images_only` registers only .exe/.dll/.pyd (measured on the 0.9.1 bundle: 273 of 4634 files, 4.6 s vs 34 s
    with 6 holders live), the cheap poll while services exit; the full scan then catches any other held file once.
    t-fb8b63874e: the owner's update got None here and rolled back with no rc on record. Each look's return codes
    go to `log`, and a failed call or a holder list that changed between the two RmGetList calls (234 again: a
    process started or ended in between) is retried before None is answered."""
    for attempt in range(1, max(1, tries) + 1):
        got, rcs = _rm_look(folder, limit, images_only)
        if log:
            log(f"restart manager look {attempt}/{tries} ({'images' if images_only else 'all files'}): {rcs}")
        if got is not None:
            return got
        if attempt < tries:
            time.sleep(pause_s)
    return None


def _rm_look(folder: str, limit: int, images_only: bool) -> tuple[list[str] | None, dict]:
    """One Restart Manager session: (holders or None, the return code of every call made)."""
    import ctypes
    from ctypes import wintypes

    class _Unique(ctypes.Structure):
        _fields_ = [("pid", wintypes.DWORD), ("start", wintypes.FILETIME)]

    class _Info(ctypes.Structure):
        _fields_ = [("proc", _Unique), ("app", wintypes.WCHAR * 256), ("svc", wintypes.WCHAR * 64),
                    ("type", ctypes.c_int), ("status", wintypes.ULONG), ("ts", wintypes.DWORD),
                    ("restartable", wintypes.BOOL)]

    files = [os.path.join(d, f) for d, _, fs in os.walk(folder) for f in fs
             if not images_only or f.lower().endswith((".exe", ".dll", ".pyd"))]
    rm = ctypes.WinDLL("rstrtmgr")
    sess, key = wintypes.DWORD(), ctypes.create_unicode_buffer(64)
    rcs: dict = {"files": len(files), "start": rm.RmStartSession(ctypes.byref(sess), 0, key)}
    if rcs["start"]:
        return None, rcs
    try:
        rcs["register"] = []
        for i in range(0, len(files), 1000):
            chunk = files[i:i + 1000]
            arr = (ctypes.c_wchar_p * len(chunk))(*chunk)
            rcs["register"].append(rm.RmRegisterResources(sess, len(chunk), arr, 0, None, 0, None))
            if rcs["register"][-1]:
                return None, rcs
        need, count, why = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
        rcs["list1"] = rm.RmGetList(sess, ctypes.byref(need), ctypes.byref(count), None, ctypes.byref(why))
        if rcs["list1"] == 0:
            return [], rcs
        if rcs["list1"] != 234:  # ERROR_MORE_DATA: there are holders
            return None, rcs
        rcs["need"] = need.value
        info = (_Info * need.value)()
        count = wintypes.UINT(need.value)
        rcs["list2"] = rm.RmGetList(sess, ctypes.byref(need), ctypes.byref(count), info, ctypes.byref(why))
        if rcs["list2"]:  # 234 again: the list grew between the two calls
            return None, rcs
        return [f"{info[k].app or '?'} (pid {info[k].proc.pid})" for k in range(min(count.value, limit))], rcs
    finally:
        rm.RmEndSession(sess)


def _http(url: str, method: str = "GET", timeout: float = 30.0, body: dict | None = None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["X-Admin"] = token
    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310  # nosec B310  # loopback URL from our own plan
        body = r.read().decode("utf-8", "replace")
    return json.loads(body) if body.strip() else None


class Parked(list):
    """The handles parked; `.failed` holds the live seats that did not park (S18-2), `.procs` each parked
    seat's process fingerprint as the pool recorded it ({pid, create_time, name}; t-fb8b63874e)."""
    failed: list[str] = []
    procs: dict = {}


def _park(plan: dict) -> list[str]:
    """The handles parked (a Parked; see _park_all)."""
    procs: dict = {}
    got, failed = _park_all(plan, procs)
    out = Parked(got)
    out.failed = failed
    out.procs = procs
    return out


def _park_all(plan: dict, procs: dict | None = None) -> tuple[list[str], list[str]]:
    """Park every live seat on the pool for the update: (parked, failed). S14's contract (architect
    m-e5b2846ef5): `{"for_update": true}` sets row.park_for_update, and the next pool start fork-resumes exactly
    those rows once, after its health check. A pool without that capability ignores the body; _resume covers it.
    S18-2: a seat the pool listed as live but that did not park is `failed`; the caller installs nothing then."""
    pool = plan.get("pool_url")
    if not pool:
        return [], []
    _prog(plan, "park seats")
    try:
        rows = _http(f"{pool}/v1/sessions")
    except (OSError, ValueError) as e:
        _log(plan, f"park: the pool did not answer ({e}); no seat parked")
        return [], []
    rows = rows.get("sessions", rows) if isinstance(rows, dict) else rows
    rows = rows.values() if isinstance(rows, dict) else rows or []
    parked, failed = [], []
    for r in rows:
        if r.get("state") in ("active", "starting") and r.get("handle"):
            try:
                got = _http(f"{pool}/v1/park/{r['handle']}", "POST", timeout=60, body={"for_update": True})
                _log(plan, f"park {r['handle']}: {json.dumps(got)[:300]}")
                parked.append(r["handle"])
                if procs is not None:
                    procs[r["handle"]] = r.get("proc")
            except (OSError, ValueError) as e:
                _log(plan, f"park {r['handle']} failed: {e}")
                failed.append(r["handle"])
    return parked, failed


def _not_resumed(parked: list[str], resumed: list[str]) -> list[str]:
    return [h for h in parked if h not in resumed]


def _resume_note(missing: list[str]) -> str:
    return (f"; seat(s) {', '.join(missing)} did not resume: resume them from the Seats tab"
            if missing else "")


def _services_down(plan: dict) -> bool:
    """S18-2: a stop that reported failure counts as done only when the board no longer answers its health check."""
    return _health_version(plan["health_url"], wait_s=5.0) is None


def _resume(plan: dict, handles: list[str]) -> list[str]:
    """Resume the parked seats, once each, here and now: the updater is the only resumer while it holds the update
    lock (a pool started mid-update leaves `park_for_update` rows alone), and it calls this only after the final
    version (new or rolled back) answered health. A seat already resumed in this run is not resumed again."""
    if not handles:
        return []
    _prog(plan, "resume seats", ", ".join(handles))
    return _resume_now(plan, handles)


def _resume_now(plan: dict, handles: list[str]) -> list[str]:
    """Resume each handle through POST /v1/resume now, never twice in one update (`plan["_resumed"]` remembers)."""
    pool, done = plan.get("pool_url"), []
    if not pool:
        return done
    already = plan.setdefault("_resumed", [])
    for h in handles:
        if h in already:
            done.append(h)
            continue
        try:
            got = _http(f"{pool}/v1/resume/{h}", "POST", timeout=120)
            _log(plan, f"resume {h}: {json.dumps(got)[:300]}")
            already.append(h)
            done.append(h)
        except (OSError, ValueError) as e:
            _log(plan, f"resume {h} failed: {e}")
    return done


def _health_version(url: str, wait_s: float = 120.0) -> str | None:
    """The version a healthy board reports, None when it never answered 200 within wait_s."""
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        try:
            got = _http(url, timeout=3)
            v = (got or {}).get("version") or ((got or {}).get("value") or {}).get("version")
            return str(v or "?")
        except (OSError, ValueError):
            time.sleep(1.0)
    return None


def _same(a: str | None, b: str | None) -> bool:
    """'0.9.2.dev0' (wheel) == '0.9.2' (MSI ProductVersion, numeric only) on the numeric release segment."""
    def num(s: str) -> tuple:
        out = []
        for part in (s or "").strip().removeprefix("v").split("."):
            if not part[:1].isdigit():
                break
            out.append(int("".join(c for c in part if c.isdigit()) or 0))
            if not part.isdigit():
                break
        while len(out) > 1 and out[-1] == 0:
            out.pop()
        return tuple(out)
    return bool(a and b) and num(a) == num(b)


def _msiexec(plan: dict, what: str, args: list[str], log_name: str) -> int:
    """msiexec with no UI, no reboot, a verbose log beside the update log; its exit code. Not /qb: basic UI
    still raises a modal Retry/Cancel box on a damaged cabinet (error 1335), which held the S2 drill for
    10 minutes with nobody to answer it; /qn fails the install instead (1603) and the runner rolls back."""
    _prog(plan, what)
    mlog = str(Path(plan["log"]).with_name(log_name))
    cmd = msi_cmdline([*args, "/qn", "/norestart", "/l*v", mlog])
    _log(plan, f"{what}: {cmd}")
    try:
        r = subprocess.run(cmd, timeout=MSIEXEC_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        _log(plan, f"{what} did not finish within {MSIEXEC_TIMEOUT_S:.0f} s; the client was killed")
        return MSI_TIMEOUT
    except OSError as e:
        _log(plan, f"{what} failed to run: {e}")
        return -1
    _log(plan, f"{what} exit {r.returncode} (log {mlog})")
    return r.returncode


#: a msiexec that outlives this is killed and counted a failure whose state is unknown: the Installer service may
#: still be rolling back or have committed, so the runner waits for it, looks at what is registered, and repairs
MSIEXEC_TIMEOUT_S = 900.0
MSI_TIMEOUT = -2
#: msiexec exits that mean "installed": 0 ok; 3010/1641 installed but files were in use and wait for a reboot,
#: which the runner treats as a failure (the folder is half old until the reboot)
MSI_OK = 0
MSI_REASONS = {1602: "the installer was cancelled", 1603: "the installer failed (fatal error; see the msiexec log)",
               1618: "another installation is in progress", 1620: "the installer package could not be opened",
               1638: "this version is already installed", 3010: "files were in use; the install waits for a reboot",
               1641: "the installer started a reboot"}


_MSI_PROPERTY = re.compile(r"^([A-Z_][A-Z0-9_.]*)=(.*)$")


def msi_cmdline(args: list[str]) -> str:
    """The msiexec command line for `args`, as one string (t-fd7cf3a6b5). A list makes subprocess quote a whole
    `INSTALLFOLDER=C:\\…\\Heronry Desktop` token, and msiexec refuses that form with 1639 (invalid command line),
    so every real update into the default per-user folder failed. msiexec wants the value quoted instead:
    `PROP="value"`. Options (`/i`, `/l*v`) stay bare; every other token (a package, a log path, a product code) is
    quoted whole. No token may hold a double quote: Windows paths cannot. A quoted value never ends in a backslash
    (architect m-eab86ba45f): `"C:\\dir\\"` reads as an escaped quote, so a folder's trailing backslash is dropped
    (`C:\\dir` names the same folder) and a bare drive root, which has no such spelling, is refused."""
    def quoted(v: str) -> str:
        if v.endswith("\\"):
            if re.fullmatch(r"[A-Za-z]:\\+", v):
                raise ValueError(f"a drive root as a msiexec value: {v!r}")
            v = v.rstrip("\\")
        return f'"{v}"'

    out = ["msiexec"]
    for a in args:
        if '"' in a:
            raise ValueError(f"a double quote in a msiexec argument: {a!r}")
        m = _MSI_PROPERTY.match(a)
        out.append(a if a.startswith("/") else f"{m.group(1)}={quoted(m.group(2))}" if m else quoted(a))
    return " ".join(out)


def _msi_install_args(plan: dict, msi_path: str) -> list[str]:
    return ["/i", msi_path, "MSIINSTALLPERUSER=1", "ALLUSERS=2", f"INSTALLFOLDER={plan['install_dir']}",
            "REBOOT=ReallySuppress"]


def _msi_busy() -> bool:
    """Windows Installer is running a transaction (its `Global\\_MSIExecute` mutex exists). A killed or timed-out
    msiexec client leaves the service rolling back for a minute or more; a relaunch before it ends finds a
    half-restored folder (S2 drill: start failed, the folder came back 60 s later)."""
    if sys.platform != "win32":
        return False
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenMutexW.restype = ctypes.c_void_p
    h = k32.OpenMutexW(0x00100000, False, "Global\\_MSIExecute")  # SYNCHRONIZE
    if h:
        k32.CloseHandle(ctypes.c_void_p(h))
        return True
    return ctypes.get_last_error() == 5  # access denied: it exists


def _wait_msi_idle(plan: dict, wait_s: float = 600.0) -> None:
    deadline = time.monotonic() + wait_s
    if _msi_busy():
        _log(plan, "Windows Installer is still busy (rolling back?); waiting for it to finish")
    while _msi_busy() and time.monotonic() < deadline:
        time.sleep(2.0)


def _verified_sum(plan: dict, key: str) -> str | None:
    """The SHA256 the updater verified for plan[key] ("msi" or "previous_msi"): the plan's `<key>_sha256`, else the
    SHA256SUMS the download wrote beside the file. None when neither names it."""
    if plan.get(f"{key}_sha256"):
        return str(plan[f"{key}_sha256"]).lower()
    path = Path(plan[key])
    try:
        for line in (path.parent / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == path.name:
                return parts[0].lower()
    except OSError:
        pass
    return None


def _changed(plan: dict, key: str) -> str | None:
    """S13 F6: why the installer file plan[key] must not reach msiexec (it differs from the bytes the updater
    verified, or no verified digest is known), or None when it is the verified file. Checked before anything stops
    and again right before each msiexec that uses it."""
    if not plan.get(key):
        return None
    want = _verified_sum(plan, key)
    if not want:
        return f"{Path(plan[key]).name} has no verified SHA256 on record"
    try:
        got = hashlib.sha256(Path(plan[key]).read_bytes()).hexdigest()
    except OSError as e:
        return f"{Path(plan[key]).name} cannot be read ({e})"
    return None if got == want else f"{Path(plan[key]).name} changed since it was verified (SHA256 {got[:12]}…)"


def _installed(plan: dict) -> str | None:
    rows = related_products(plan["upgrade_code"])
    return rows[0]["version"] if len(rows) == 1 else (",".join(r["version"] for r in rows) or None)


def _msi_steps(plan: dict, finish) -> int:
    """The MSI update. S13 F2: the phase reached is tracked, so an exception after the stop still brings a version
    back. Before the install, the unchanged old install is restarted and the parked seats resumed; from the install
    on, the rollback path runs. The receipt keeps the original error and any recovery error."""
    t0, timings = time.monotonic(), {}
    phase = ["none"]  # none -> parked -> stopped -> installing -> installed
    parked: list[str] = []
    rollback: list = []  # the update's back(), once defined

    def mark(step: str) -> None:
        timings[step] = round(time.monotonic() - t0, 1)

    def relaunch(version: str) -> str | None:
        _run(plan, "start", plan["start_argv"], timeout=300)
        _prog(plan, "health check")
        got = _health_version(plan["health_url"])
        _log(plan, f"health after start: {got!r} (want {version})")
        if got:  # the update stopped the opt-in code server: bring it back
            _start_code(plan)
        if plan.get("app_argv") and got:
            _detach_app(plan)
        return got

    try:
        return _msi_update(plan, finish, phase, parked, rollback, mark, relaunch, timings)
    except Exception as e:  # noqa: BLE001 -- every exception past the stop must bring a version back
        if phase[0] == "none":
            raise  # nothing was parked or stopped: main() records the crash
        err = f"the update helper failed while {phase[0]} ({type(e).__name__}: {e})"
        _log(plan, f"recovering: {err}")
        try:
            if phase[0] in ("parked", "stopped") or not rollback:  # nothing was installed: the old install is intact
                got = relaunch(plan["from_version"])
                resumed = _resume(plan, parked) if got else []
                ok = _same(got, plan["from_version"])
                tail = ("; nothing was installed and the previous version was restarted" if ok else
                        f"; the previous version did not come back (health {got}); {plan.get('recover_hint')}")
                missing = _not_resumed(parked, resumed)
                return finish("rolled_back" if ok else "failed", err + tail + _resume_note(missing), timings=timings,
                              parked=parked, resumed=resumed, resume_failed=missing, error=err, health_version=got)
            installed_new = phase[0] == "installed"
            if phase[0] == "installing":  # msiexec may or may not have committed: look at what is registered
                _wait_msi_idle(plan)
                installed_new = _same(_installed(plan), plan["to_version"])
            return rollback[0](err, installed_new)
        except Exception as e2:  # noqa: BLE001
            rec = f"{type(e2).__name__}: {e2}"
            return finish("failed", f"{err}; recovery also failed ({rec}); {plan.get('recover_hint')}",
                          timings=timings, parked=parked, error=err, recovery_error=rec)


def _msi_update(plan: dict, finish, phase: list[str], parked: list[str], rollback: list, mark, relaunch,
                timings: dict) -> int:
    fault = plan.get("fault") or ""
    bad = _changed(plan, "msi") or _changed(plan, "previous_msi")
    if bad:  # S13 F6: fail before anything is parked or stopped
        return finish("failed", f"{bad}; nothing was stopped or installed. Run the update again to re-download",
                      timings=timings)
    got_parked = _park(plan)
    park_failed = list(getattr(got_parked, "failed", []))
    parked_procs = dict(getattr(got_parked, "procs", None) or {})
    parked.extend(got_parked)
    phase[0] = "parked"
    mark("parked")
    if park_failed:  # S18-2: a live seat that did not park would be killed mid-turn: install nothing
        resumed = _resume_now(plan, parked)
        missing = _not_resumed(parked, resumed)
        return finish("failed", f"seat(s) {', '.join(park_failed)} could not be parked; nothing was stopped or "
                      f"installed{_resume_note(missing)}", timings=timings, parked=parked, park_failed=park_failed,
                      resumed=resumed, resume_failed=missing)
    if not _run(plan, "stop", plan["stop_argv"], timeout=300) and not _services_down(plan):
        # S18-2: the stop failed and the board still answers: installing over running services is refused
        got = relaunch(plan["from_version"])
        resumed = _resume(plan, parked) if got else []
        missing = _not_resumed(parked, resumed)
        return finish("failed", "the services did not stop (the stop command failed and the board still answers); "
                      f"nothing was installed{_resume_note(missing)}", timings=timings, parked=parked,
                      resumed=resumed, resume_failed=missing, health_version=got)
    phase[0] = "stopped"
    _close_app(plan)
    _end_parked_shells(plan, parked, parked_procs)
    _stop_code(plan)
    _stop_install_procs(plan)
    mark("stopped")
    held: list[str] | None = None
    deadline = time.monotonic() + float(plan.get("holder_wait_s", 30))

    def log(text: str) -> None:
        _log(plan, text)

    while True:  # at least one look, then poll while the stopped services exit
        held = holders(plan["install_dir"], images_only=True, log=log)
        if held == [] or time.monotonic() >= deadline:
            break
        time.sleep(1.0)
    if held == []:
        held = holders(plan["install_dir"], log=log)
    mark("holders_checked")
    _log(plan, f"holders in {plan['install_dir']}: {held}")

    def back(reason: str, installed_new: bool) -> int:
        _log(plan, f"rolling back: {reason}")
        reinstalled = False
        if installed_new:
            _run(plan, "stop", plan["stop_argv"], timeout=300)
            code = (related_products(plan["upgrade_code"]) or [{}])[0].get("code")
            prev = plan.get("previous_msi")
            if not prev:
                return finish("failed", f"{reason}; the previous installer is not cached; {plan.get('recover_hint')}",
                              timings=timings, parked=parked)
            bad_prev = _changed(plan, "previous_msi")
            if bad_prev:  # S13 F6: never reinstall bytes other than the verified previous installer
                return finish("failed", f"{reason}; not rolled back: {bad_prev}; {plan.get('recover_hint')}",
                              timings=timings, parked=parked)
            # a downgrade is refused by MajorUpgrade, so the broken new version is removed first (rollback only)
            rc_x = _msiexec(plan, "remove the new version", ["/x", code], "msiexec-rollback-remove.log") if code else -1
            rc_i = _msiexec(plan, "reinstall the previous version", _msi_install_args(plan, prev),
                            "msiexec-rollback-install.log")
            reinstalled = rc_x == 0 and rc_i == 0
        if installed_new:  # the new version may have migrated the DB
            _restore(plan)
        _wait_msi_idle(plan)
        now = _installed(plan)
        got = relaunch(plan["from_version"])
        prev = plan.get("previous_msi")
        if not got and not installed_new and prev and not _changed(plan, "previous_msi"):
            # Windows Installer's own rollback did not leave a working old version: repair it from the cached MSI
            # (/fa reinstalls every file of the registered product; /i when the product is gone altogether)
            _run(plan, "stop", plan["stop_argv"], timeout=300)
            args = ["/fa", prev] if _same(now, plan["from_version"]) else _msi_install_args(plan, prev)
            reinstalled = _msiexec(plan, "repair the previous version", args, "msiexec-rollback-repair.log") == 0
            now = _installed(plan)
            got = relaunch(plan["from_version"])
        mark("rolled_back")
        resumed = _resume(plan, parked) if got else []
        missing = _not_resumed(parked, resumed)
        ok = bool(got) and _same(got, plan["from_version"]) and _same(now, plan["from_version"]) \
            and (reinstalled or not installed_new)  # the board must report the old version, not just answer
        state = "rolled_back" if ok else "failed"
        tail = "" if ok else f"; the previous version did not come back (installed {now}, health {got}); " \
                             f"{plan.get('recover_hint')}"
        return finish(state, f"{reason}{tail}{_resume_note(missing)}", timings=timings, parked=parked,
                      resumed=resumed, resume_failed=missing, installed=now, health_version=got)

    rollback.append(back)
    spared = plan.get("_spared_seats") or []
    if spared:  # the fail-safe: a live seat outside the parked set still runs a feed monitor from the install folder
        return back(f"{untracked_reason(spared)}; nothing was installed", False)
    if held:
        return back(f"files in the install folder are held by {'; '.join(_describe(h) for h in held)}; "
                    "nothing was installed", False)
    if held is None:
        return back("could not confirm that no process holds the install folder (Restart Manager); "
                    "nothing was installed", False)
    args = _msi_install_args(plan, plan["msi"])
    bad = _changed(plan, "msi")
    if bad:  # S13 F6: the exact file msiexec gets is the verified one, checked again at the last moment
        return back(f"{bad}; nothing was installed", False)
    phase[0] = "installing"
    rc = _msiexec(plan, "install", args, "msiexec-install.log")
    if rc != MSI_TIMEOUT:  # a timed-out client leaves the outcome unknown: it stays "installing"
        phase[0] = "installed" if rc in (MSI_OK, 3010, 1641) else "stopped"
    mark("installed")
    if rc == MSI_TIMEOUT:
        _wait_msi_idle(plan)  # the killed client leaves the service finishing or rolling back
        changed = _same(_installed(plan), plan["to_version"])
        return back(f"msiexec did not finish within {MSIEXEC_TIMEOUT_S:.0f} s", changed)
    if rc != MSI_OK:
        why = MSI_REASONS.get(rc, "the installer failed")
        changed = rc in (3010, 1641)
        return back(f"msiexec exit {rc}: {why}" + ("" if changed else "; Windows Installer rolled its changes back"),
                    changed)
    now = _installed(plan)
    if not _same(now, plan["to_version"]):
        return back(f"the installer finished but {now!r} is installed, not {plan['to_version']}", True)
    got = None if fault == "unhealthy" else relaunch(plan["to_version"])
    mark("relaunched")
    if not got:
        return back("the new version did not answer its health check" + (" (forced: fault=unhealthy)" if fault else ""),
                    True)
    if not _same(got, plan["to_version"]):
        return back(f"the board reports {got}, not {plan['to_version']}", True)
    resumed = _resume(plan, parked)
    mark("resumed")
    missing = _not_resumed(parked, resumed)
    if missing:  # S18-2: the new version stays installed; never an unqualified ok with seats left parked
        return finish("incomplete", f"updated to {plan['to_version']}{_resume_note(missing)}", timings=timings,
                      parked=parked, resumed=resumed, resume_failed=missing, installed=now, health_version=got)
    return finish("ok", "", timings=timings, parked=parked, resumed=resumed, installed=now, health_version=got)


def _proc_identity(pid: int) -> tuple[float, str] | None:
    """(creation time in epoch seconds, image path) of a live process, None when it cannot be read (Windows)."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        c, e, k, u = (wintypes.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            return None
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return None
        ticks = (c.dwHighDateTime << 32) | c.dwLowDateTime
        return (ticks - 116444736000000000) / 1e7, buf.value
    finally:
        k32.CloseHandle(h)


def _same_process(pid: int, want: dict) -> bool:
    """`pid` is still the process the updater saw: same image path and the same start time (1 s slack)."""
    got = _proc_identity(pid)
    return (got is not None and os.path.normcase(got[1]) == os.path.normcase(str(want.get("exe", "")))
            and abs(got[0] - float(want.get("created", 0))) < 1.5)


def _close_app(plan: dict) -> None:
    """End the desktop app windows that were open when the update started (`app_pids`, found by the updater from the
    image path): closing the window only hides it to the tray, and its exe would be a held file. They hold no
    service (the GUI owns none), and `app_argv` brings the app back after the update."""
    procs = plan.get("app_procs") or {}
    for pid in plan.get("app_pids") or []:
        if pid == os.getpid() or not _pid_alive(int(pid)):
            continue
        want = procs.get(str(pid))
        if not want or not _same_process(int(pid), want):  # the pid was read up to 120 s ago and may be reused
            _log(plan, f"not closing pid {pid}: it is no longer the desktop app that was open")
            continue
        _log(plan, f"closing the desktop app (pid {pid})")
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=30,
                           stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            _log(plan, f"close failed: {e}")


def _end_parked_shells(plan: dict, parked: list[str], procs: dict) -> list[str]:
    """t-fb8b63874e (architect m-4e2fe95fac): park leaves a seat's shell alive, and its feed monitor (a child
    running the installed heronry.exe) holds the install folder. Each seat this update parked is ended here, after
    the services stopped: its recorded process (claude.exe, or a codex seat's heronry.exe) and its tree, which holds
    the feed monitor and any codex child. The pool's start then fork-resumes each `park_for_update` row exactly once
    (its process is gone), and that one fresh shell's first turn re-arms its monitor. A pid whose start time or
    image no longer matches the fingerprint is another process and is left alone, as is every unparked seat."""
    ended: list[str] = []
    for h in parked:
        fp = procs.get(h) or {}
        if not fp.get("pid") or fp.get("create_time") is None:
            _log(plan, f"parked seat {h}: no process fingerprint, its shell is left alone")
            continue
        pid = int(fp["pid"])
        got = _proc_identity(pid)
        if got is None:
            _log(plan, f"parked seat {h} (pid {pid}): its shell is already gone")
            continue
        image = os.path.basename(got[1])
        if abs(got[0] - float(fp["create_time"])) >= 1.5 or (fp.get("name") and _image_key(image) != _image_key(fp["name"])):
            _log(plan, f"parked seat {h}: pid {pid} is now another process ({image}), left alone")
            continue
        _log(plan, f"ending parked seat {h}: {_describe_proc({'pid': pid, 'name': image, 'cmdline': _cmdline(pid)})}"
                   " with its children (its feed monitor); the pool resumes the seat once after the start")
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=30,
                           stdin=subprocess.DEVNULL)
            ended.append(h)
        except (OSError, subprocess.TimeoutExpired) as e:
            _log(plan, f"ending parked seat {h} (pid {pid}) failed: {e}")
    return ended


def _image_key(name: str) -> str:
    n = name.lower()
    return n[:-4] if n.endswith(".exe") else n


def _is_code_guard(p: dict) -> bool:
    return "--heronry-service code-guard" in (p.get("cmdline") or "")


def _code_argv(plan: dict, verb: str) -> list[str]:
    """`heronry <verb> code` through the same launcher as the plan's start command ([exe, start, ...] for the bundle,
    [python, -m, edp8.cli, start] for a uv tool install)."""
    argv = list(plan["start_argv"])
    return [*argv[:argv.index("start")], verb, "code"]


def _start_code(plan: dict) -> None:
    """Bring the code server back once the new version is up: its start installs the new EDP Chat vsix, and a
    code-server that kept running would go on serving the old extension (qa 0.10.7)."""
    if plan.get("_code_was_running"):
        _run(plan, "start code", _code_argv(plan, "start"), timeout=300)


def _stop_code(plan: dict) -> bool:
    """The opt-in code server is left out of `stop all` unless it autostarts (cli.py `_targets`). When its guard
    runs from the install folder it is stopped through the product's own `heronry stop code`, which knows its
    child, and started again after the relaunch."""
    # the updater saw the service up before it handed over (plan["code_running"]): that decides, wherever the guard's
    # process runs from (qa 0.10.7: a code-server the process scan missed kept serving the old extension)
    if not plan.get("code_running") and not any(_is_code_guard(p) for p in install_procs(plan["install_dir"])):
        return False
    plan["_code_was_running"] = True
    _run(plan, "stop code", _code_argv(plan, "stop"), timeout=120)
    return True


def _stop_install_procs(plan: dict) -> list[dict]:
    """The backstop after the parked shells and the code server ended (t-fb8b63874e): anything still running from
    the install folder (an orphaned feed monitor, a code guard `stop code` missed) holds its exe and DLLs, so the
    MSI cannot replace them. Each is stopped by its own pid, never with /T: a stray process tree under a
    heronry.exe must not take an unrelated child with it. Each is named in the log. A feed monitor with a live
    seat above it (a shell the pool did not track, so the update did not park and end it) is never stopped: it is
    that seat's only wake plane. It is kept in plan["_spared_seats"] and the update rolls back naming the seat
    (architect m-95b5fe285e; `heronry update` refuses such a seat up front)."""
    left = [p for p in install_procs(plan["install_dir"]) if p["pid"] != os.getpid()]
    seats = {f["feed"]["pid"]: f["seat"] for f in seat_feeds(plan["install_dir"], left) if f["seat"]}
    spared: dict[int, dict] = {}
    for pid, seat in seats.items():
        spared[seat["pid"]] = seat
        _log(plan, f"sparing the feed monitor pid {pid}: its seat {_describe_proc(seat)} lives, and ending the "
                   "monitor alone would leave that seat unable to wake")
    plan["_spared_seats"] = list(spared.values())
    left = [p for p in left if p["pid"] not in seats]
    for p in left:
        if _is_code_guard(p):
            plan["_code_was_running"] = True
        _log(plan, f"stopping {_describe_proc(p)}: it runs from the install folder")
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(p["pid"])], capture_output=True, timeout=30,
                           stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            _log(plan, f"stop of pid {p['pid']} failed: {e}")
    return left


def _snapshot() -> list[tuple[int, int, str]]:
    """(pid, parent pid, exe name) of every running process (Toolhelp32; Windows)."""
    import ctypes
    from ctypes import wintypes

    class _Entry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("ppid", wintypes.DWORD), ("prio", ctypes.c_long), ("flags", wintypes.DWORD),
                    ("exe", wintypes.WCHAR * 260)]

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    out: list[tuple[int, int, str]] = []
    try:
        e = _Entry()
        e.size = ctypes.sizeof(_Entry)
        ok = k32.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(e))
        while ok:
            out.append((int(e.pid), int(e.ppid), e.exe))
            ok = k32.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(e))
    finally:
        k32.CloseHandle(wintypes.HANDLE(snap))
    return out


def install_procs(folder: str) -> list[dict]:
    """[{pid, name, image, cmdline}] of every running process whose executable lies under `folder` (Windows)."""
    root = os.path.normcase(os.path.abspath(folder)).rstrip("\\/") + os.sep
    out: list[dict] = []
    for pid, _ppid, exe in _snapshot():
        ident = _proc_identity(pid) if pid else None
        if ident and os.path.normcase(ident[1]).startswith(root):
            out.append({"pid": pid, "name": exe, "image": ident[1], "cmdline": _cmdline(pid)})
        elif ident and _moved_aside(ident[1]):
            # an earlier MSI moved this process's in-use exe to <drive>\Config.Msi\*.rbf; it still holds the
            # folder's DLLs (the owner's 13:05 update: a code guard left by a rolled-back update). Its command line
            # still names the exe it was started as.
            cmd = _cmdline(pid)
            if os.path.normcase(_argv0(cmd)).startswith(root):
                out.append({"pid": pid, "name": exe, "image": ident[1], "cmdline": cmd})
    return out


def _moved_aside(image: str) -> bool:
    return os.path.normcase(os.sep + "Config.Msi" + os.sep) in os.path.normcase(image)


def _argv0(cmdline: str) -> str:
    """The program a command line starts: its first token, quoted or not."""
    s = (cmdline or "").strip()
    if s.startswith('"'):
        return s[1:].split('"', 1)[0]
    return s.split(" ", 1)[0]


def _is_feed(p: dict) -> bool:
    return "edp8.feed_driver" in (p.get("cmdline") or "")


def seat_feeds(folder: str, procs: list[dict] | None = None) -> list[dict]:
    """[{feed, seat}]: each feed monitor running from `folder`, with the live seat shell above it (claude.exe, or a
    codex seat's `heronry.exe -m edp8.codex_seat.run`) or None. A parent that started after its child is a reused
    pid, not the parent, and ends the walk."""
    table = {pid: (ppid, exe) for pid, ppid, exe in _snapshot()}
    return [{"feed": p, "seat": _seat_above(p["pid"], table)}
            for p in (install_procs(folder) if procs is None else procs) if _is_feed(p)]


def _seat_above(pid: int, table: dict, depth: int = 8) -> dict | None:
    cur = pid
    for _ in range(depth):
        ppid, _exe = table.get(cur, (0, ""))
        if not ppid or ppid not in table:
            return None
        child, parent = _proc_identity(cur), _proc_identity(ppid)
        if not child or not parent or parent[0] > child[0] + 1.0:
            return None
        name = table[ppid][1]
        if name.lower() == "claude.exe" or (name.lower() == "heronry.exe" and "edp8.codex_seat.run" in _cmdline(ppid)):
            return {"pid": ppid, "name": name, "image": parent[1], "cmdline": _cmdline(ppid),
                    "created": parent[0]}
        cur = ppid
    return None


def untracked_seats(folder: str, tracked: set[int]) -> list[dict]:
    """The live seats with a feed monitor running from `folder` whose shell is not in `tracked` (the pids of the
    pool's active rows): an update cannot park and resume them, so ending their monitor would leave them deaf."""
    seen: dict[int, dict] = {}
    for f in seat_feeds(folder):
        s = f["seat"]
        if s and s["pid"] not in tracked:
            seen.setdefault(s["pid"], s)
    return list(seen.values())


def untracked_reason(seats: list[dict]) -> str:
    """The refusal and the fail-safe's rollback reason: each seat by name, pid and command line (no token values),
    and the remedy."""
    return (f"seat(s) running outside the pool's tracking still hold a feed monitor in the install folder: "
            f"{'; '.join(_describe_proc(s) for s in seats)}. Close this window, or resume the seat through the "
            "board, then run update again")


def _cmdline(pid: int) -> str:
    """A process's command line (ProcessCommandLineInformation, Windows 8.1+), "" when it cannot be read."""
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes

    class _Ustr(ctypes.Structure):
        _fields_ = [("length", wintypes.USHORT), ("maximum", wintypes.USHORT), ("buffer", ctypes.c_void_p)]

    k32, nt = ctypes.windll.kernel32, ctypes.windll.ntdll
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        size = wintypes.ULONG(0)
        nt.NtQueryInformationProcess(wintypes.HANDLE(h), 60, None, 0, ctypes.byref(size))
        if not size.value:
            return ""
        buf = ctypes.create_string_buffer(size.value)
        if nt.NtQueryInformationProcess(wintypes.HANDLE(h), 60, buf, size, ctypes.byref(size)):
            return ""
        u = _Ustr.from_buffer(buf)
        return ctypes.wstring_at(u.buffer, u.length // 2) if u.buffer and u.length else ""
    finally:
        k32.CloseHandle(wintypes.HANDLE(h))


_SECRET_FLAG = re.compile(r"(?i)((?:--?|/)[\w-]*(?:token|secret|password|passwd|key|auth)[\w-]*)(=|\s+)(\"[^\"]*\"|\S+)")
_SECRET_RUN = re.compile(r"[A-Za-z0-9_\-+=]{32,}")


def _redact(cmdline: str) -> str:
    """A command line with no token values: the value after a token/secret/key/password flag and any long opaque
    run (32+ base64- or hex-like characters) become ***. Paths and flags stay readable."""
    return _SECRET_RUN.sub("***", _SECRET_FLAG.sub(lambda m: f"{m.group(1)}{m.group(2)}***", cmdline))


def _describe_proc(p: dict, width: int = 240) -> str:
    """name (pid N): the command line with no token values, cut at `width` (a resumed seat carries its prompt)."""
    line = _redact(p.get("cmdline") or "") or "(command line unreadable)"
    return f"{p.get('name') or '?'} (pid {p['pid']}): {line if len(line) <= width else line[:width - 1] + '…'}"


def _describe(holder: str) -> str:
    """A Restart Manager holder ("name (pid N)") with its command line, no token values."""
    m = re.search(r"\(pid (\d+)\)$", holder)
    line = _redact(_cmdline(int(m.group(1)))) if m else ""
    return f"{holder}: {line}" if line else holder


def _detach_app(plan: dict) -> None:
    """Relaunch the desktop app (it was open when the update started) out of this process's tree."""
    try:
        subprocess.Popen(plan["app_argv"], cwd=plan["install_dir"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        _log(plan, f"app relaunched: {' '.join(plan['app_argv'])}")
    except OSError as e:
        _log(plan, f"app relaunch failed: {e}")


def _extract_bundle(ex: dict) -> str:
    """An administrative image of the new MSI (`msiexec /a`, no elevation, no registry, no services: it only lays the
    files out) and the path of the console `heronry.exe` in it. Measured on the 0.8.0 bundle: 26 s, 205 MB, runs
    standalone. The target must stay short: the bundle's tree overflows MAX_PATH from a deep folder (1320)."""
    dest = Path(ex["dir"])
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(msi_cmdline(["/a", ex["msi"], "/qn", f"TARGETDIR={dest}"]), timeout=600, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise OSError(f"msiexec /a exited {r.returncode}")
    cands = [p for p in dest.rglob(ex["exe"]) if "app_packages" not in p.parts]
    beside_gui = [p for p in cands if (p.parent / ex.get("gui", "?")).is_file()]
    if not (beside_gui or cands):
        raise OSError(f"no {ex['exe']} in the extracted installer")
    return str((beside_gui or cands)[0])


def compat(plan_path: str) -> int:
    """The release's workflow check. `compat_argv` is the uv path (`uv tool run`); `extract` is the MSI path: unpack the
    new installer, run ITS heronry.exe with `compat_args`, remove the unpacked copy."""
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    res = {"rc": 2, "stdout": "", "stderr": "the compatibility check did not run"}
    ex = plan.get("extract")
    try:
        argv = plan.get("compat_argv")
        if ex:
            argv = [_extract_bundle(ex), *plan["compat_args"]]
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=float(plan.get("timeout", 600)), stdin=subprocess.DEVNULL)
        res = {"rc": r.returncode, "stdout": r.stdout, "stderr": r.stderr}
    except (OSError, subprocess.TimeoutExpired) as e:
        res["stderr"] = f"the compatibility check could not run ({type(e).__name__}: {e})"
    finally:  # the waiting `heronry update` reads this file, so it is written on every path
        out = Path(plan["compat_out"])
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(json.dumps(res), encoding="utf-8")
        os.replace(tmp, out)
        if ex:
            shutil.rmtree(ex["dir"], ignore_errors=True)
    return 0


def _view_cli(argv: list[str]) -> int:
    """`--view <progress> [--pid N] [--created T] [--result F] [--inline]`"""
    opts: dict[str, str] = {}
    rest = list(argv[1:])
    while rest:
        k = rest.pop(0)
        if k == "--inline":
            opts["inline"] = "1"
        elif k in ("--pid", "--created", "--result") and rest:
            opts[k[2:]] = rest.pop(0)
    return view(argv[0], pid=int(opts.get("pid") or 0), created=float(opts.get("created") or 0),
                inline=bool(opts.get("inline")), result_file=opts.get("result", ""))


if __name__ == "__main__":
    sys.exit(compat(sys.argv[2]) if sys.argv[1] == "--compat" else
             _view_cli(sys.argv[2:]) if sys.argv[1] == "--view" else main(sys.argv[1]))
