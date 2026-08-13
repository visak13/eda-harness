"""Console-input injection — the monitor-mode wake pipe (SHADOW.md §1).

A `monitor` shell is a real visible console (CREATE_NEW_CONSOLE): there is
no ConPTY handle to write to after launch, so the shadow's framed wakes
need another route into the shell's keyboard. That route is the Win32 one:
attach to the child's console and post KEY_EVENT records into its input
buffer (AttachConsole + WriteConsoleInputW). The console delivers them to
claude's TUI exactly as if the operator had typed — including under
ENABLE_VIRTUAL_TERMINAL_INPUT, where the console itself converts the key
events to VT sequences.

WHY A HELPER PROCESS. AttachConsole is process-global: a process can be
attached to exactly ONE console, and the pool owns its own (plus it's a
multithreaded server — detaching it to borrow a child's console would be
a race against every log line). So `inject_line()` spawns a tiny
detached helper (`python -m edp_pool.console_input <pid>`, text on
stdin) that attaches, types, and exits. Cost: one short-lived process
per wake — invisible at wake cadence (heartbeats are minutes apart).

Injected lines are SINGLE-line by contract (framed wake digests); the
caller sanitizes newlines. The trailing CR is written after the same
submit delay PtyLaunch uses, so claude's Enter handling is identical on
both routes.
"""

import ctypes
import os
import subprocess
import sys
import time

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_INVALID_HANDLE = ctypes.c_void_p(-1).value

_KEY_EVENT = 0x0001
_VK_RETURN = 0x0D

_SUBMIT_DELAY_ENV = "EDP_SUBMIT_DELAY_MS"
_SUBMIT_DELAY_DEFAULT_MS = 150.0
_HELPER_TIMEOUT_S = 20.0

# ── operator-typing defer (P4, 2026-08-13 hardening run) ──────────────────
# WriteConsoleInputW splices into whatever the operator is mid-typing on
# that console: a live steer was truncated mid-word TWICE by wake lines
# firing into the same input stream ("planner needs to d…i"). Before
# injecting, the helper waits while the operator is plausibly typing INTO
# the target console (it is the FOREGROUND window and physical input landed
# within _DEFER_IDLE_MS); past _DEFER_MAX_S it gives up with exit 4 and the
# shadow re-delivers on its next tick instead of corrupting human input.
_DEFER_MAX_ENV = "EDP_WAKE_DEFER_MAX_S"
_DEFER_MAX_DEFAULT_S = 10.0
_DEFER_IDLE_MS = 4000.0


if sys.platform == "win32":
    import ctypes.wintypes as _wt

    class _KEY_EVENT_RECORD(ctypes.Structure):
        _fields_ = [
            ("bKeyDown", _wt.BOOL),
            ("wRepeatCount", _wt.WORD),
            ("wVirtualKeyCode", _wt.WORD),
            ("wVirtualScanCode", _wt.WORD),
            ("UnicodeChar", _wt.WCHAR),
            ("dwControlKeyState", _wt.DWORD),
        ]

    class _INPUT_RECORD(ctypes.Structure):
        _fields_ = [
            ("EventType", _wt.WORD),
            ("Event", _KEY_EVENT_RECORD),  # union collapsed to KEY_EVENT
        ]


def _key_records(ch: str, vk: int = 0) -> list:
    """One down+up KEY_EVENT pair for a character."""
    recs = []
    for down in (True, False):
        ev = _KEY_EVENT_RECORD(
            bKeyDown=down, wRepeatCount=1, wVirtualKeyCode=vk,
            wVirtualScanCode=0, UnicodeChar=ch, dwControlKeyState=0)
        recs.append(_INPUT_RECORD(EventType=_KEY_EVENT, Event=ev))
    return recs


def _write_records(handle, records: list) -> None:
    k32 = ctypes.windll.kernel32
    arr = (_INPUT_RECORD * len(records))(*records)
    written = ctypes.c_ulong(0)
    if not k32.WriteConsoleInputW(handle, arr, len(records),
                                  ctypes.byref(written)):
        raise OSError(ctypes.get_last_error(), "WriteConsoleInputW failed")


def _operator_active_on_console() -> bool:
    """Runs INSIDE the helper, already attached to the target console.
    True when the operator is plausibly typing into THAT console: it is the
    foreground window AND system-wide physical input landed within the last
    _DEFER_IDLE_MS. Fail-open: any API failure reads as 'not active' — a
    broken heuristic must degrade to the old always-inject behavior, never
    to lost wakes."""
    if sys.platform != "win32":
        return False
    try:
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        hwnd = k32.GetConsoleWindow()
        if not hwnd or hwnd != u32.GetForegroundWindow():
            return False

        class _LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", _wt.UINT), ("dwTime", _wt.DWORD)]

        li = _LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(li)
        if not u32.GetLastInputInfo(ctypes.byref(li)):
            return False
        idle_ms = (k32.GetTickCount() - li.dwTime) & 0xFFFFFFFF
        return idle_ms < _DEFER_IDLE_MS
    except Exception:  # noqa: BLE001 — heuristic only, never block delivery
        return False


def _inject_into_attached_console(text: str, submit_delay_ms: float) -> None:
    """Runs INSIDE the helper, already attached to the target console:
    open CONIN$, type the text, wait the submit delay, press Enter."""
    k32 = ctypes.windll.kernel32
    handle = k32.CreateFileW(
        "CONIN$", _GENERIC_READ | _GENERIC_WRITE,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE, None, _OPEN_EXISTING, 0, None)
    if handle == _INVALID_HANDLE or not handle:
        raise OSError("cannot open CONIN$ of attached console")
    try:
        records = []
        for ch in text:
            records.extend(_key_records(ch))
        # chunked writes: huge single writes can exceed the input buffer
        for i in range(0, len(records), 256):
            _write_records(handle, records[i:i + 256])
        time.sleep(submit_delay_ms / 1000.0)
        _write_records(handle, _key_records("\r", vk=_VK_RETURN))
    finally:
        k32.CloseHandle(handle)


def _helper_main(argv: list[str]) -> int:
    """`python -m edp_pool.console_input <pid>` — text on stdin. Exit 0 on
    delivery, 2 on attach failure (target console gone), 3 otherwise, 4
    deferred (operator actively typing on the target console — nothing was
    injected; the caller re-delivers later)."""
    if sys.platform != "win32":
        return 3
    try:
        pid = int(argv[0])
    except (IndexError, ValueError):
        return 3
    text = sys.stdin.read().rstrip("\r\n")
    try:
        delay = float(os.environ.get(_SUBMIT_DELAY_ENV,
                                     _SUBMIT_DELAY_DEFAULT_MS))
    except ValueError:
        delay = _SUBMIT_DELAY_DEFAULT_MS
    k32 = ctypes.windll.kernel32
    k32.FreeConsole()          # detach whatever console we were given
    if not k32.AttachConsole(pid):
        return 2
    try:
        try:
            defer_max = float(os.environ.get(_DEFER_MAX_ENV,
                                             _DEFER_MAX_DEFAULT_S))
        except ValueError:
            defer_max = _DEFER_MAX_DEFAULT_S
        deadline = time.monotonic() + max(0.0, defer_max)
        while _operator_active_on_console():
            if time.monotonic() >= deadline:
                return 4       # deferred, nothing injected
            time.sleep(0.5)
        _inject_into_attached_console(text, delay)
    except OSError:
        return 3
    finally:
        k32.FreeConsole()
    return 0


def inject_line(pid: int, text: str) -> bool:
    """Pool-side entry: deliver one line + Enter into the console owned by
    `pid`, via the detached helper. True on delivery; False on failure OR
    when the helper deferred because the operator was typing on that console
    (exit 4) — the shadow keeps the frame and re-delivers on a later tick.
    Never raises — a failed wake is logged by the caller's ledger, not fatal
    to the shadow (fail-open supervision)."""
    if sys.platform != "win32" or not pid:
        return False
    # single-line contract: a stray newline would submit mid-wake.
    text = " ".join(text.splitlines())
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "edp_pool.console_input", str(pid)],
            input=text, text=True, encoding="utf-8",
            timeout=_HELPER_TIMEOUT_S, capture_output=True,
            # CREATE_NO_WINDOW, NOT DETACHED_PROCESS (watcher-caught
            # 2026-08-13, live fleet): sys.executable here is the VENV
            # python.exe, which is a RELAUNCHER stub — it CreateProcess's
            # the real interpreter as a child. DETACHED_PROCESS detached
            # only the stub; the relaunched child, born console-less with
            # no flags, made Windows ALLOCATE A FRESH VISIBLE CONSOLE —
            # one popup per wake (the "shadow popups"). CREATE_NO_WINDOW
            # gives the stub a hidden console the child INHERITS; the
            # helper's FreeConsole()/AttachConsole(pid) dance is unchanged.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


if __name__ == "__main__":
    sys.exit(_helper_main(sys.argv[1:]))
