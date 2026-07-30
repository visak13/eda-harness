"""Fire ONE neuron turn — the resume_cmd target for arm_external_driver.

The NEURON registers this via arm_external_driver (its analog of a Claude
neuron self-arming CronCreate + Monitor); the POOL's driver then execs:

    <claude venv python> neuron_resume.py <prompt words...>

No quotes anywhere (every path is space-free), so it survives shlex,
cmd, and CreateProcess identically. Resolution happens AT FIRE TIME:
the real opencode.exe (resolve_opencode), the neuron session by its fixed
title, and the live server if one is up (--attach renders the turn in any
attached TUI; without a server the turn still runs against the shared
store).
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

FLEET = Path(__file__).resolve().parent
URL = os.environ.get("EDP_NEURON_URL", "http://127.0.0.1:4747")
TITLE = "edp-neuron-live"

def resolve_exe() -> str:
    out = subprocess.run(
        [sys.executable, str(FLEET / "resolve_opencode.py")],
        capture_output=True, text=True)
    exe = (out.stdout or "").strip()
    if not exe:
        sys.exit("neuron_resume: opencode.exe not resolvable")
    return exe


def session_id() -> str:
    """THE NEWEST edp-neuron session, full stop — the seat the operator
    is actually driving. (2026-07-20 root cause: preferring the fixed
    --auto title first resumed a STALE kickoff session — the driver woke
    a second, invisible neuron while the operator's own session sat
    'BLOCKED' forever. The operator's seat is always the newest.)"""
    db = FLEET / ".fleet-data" / "opencode" / "opencode.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    row = con.execute(
        "select id from session where agent='edp-neuron' "
        "order by time_created desc limit 1").fetchone()
    if not row:
        row = con.execute(
            "select id from session where title=? "
            "order by time_created desc limit 1", (TITLE,)).fetchone()
    if not row:
        sys.exit("neuron_resume: no edp-neuron session exists yet")
    return row[0]


def server_up() -> bool:
    try:
        import httpx
        httpx.get(URL + "/", timeout=2)
        return True
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    prompt = " ".join(sys.argv[1:]) or (
        "call reconcile then next_action and obey wait_hint: if it says "
        "wait, end your turn.")
    # SEAT GATE (2026-07-21, operator: "the neuron shell is dead but its
    # subagents still keep popping up"): the seat's server being down
    # means the OPERATOR CLOSED THE SEAT. The old fallback ran the
    # neuron headless-and-invisible — an unwatchable PM dispatching a
    # visible fleet, the exact no-invisible-shells violation. Now: seat
    # closed ⇒ this fire is a loud no-op; the driver keeps ticking and
    # driving resumes the moment the seat relaunches. Parked children
    # finish their current work either way.
    if not server_up():
        sys.stderr.write(
            "neuron_resume: SEAT CLOSED (no server at %s) — holding all "
            "driving; relaunch launch-opencode-neuron.bat to resume.\n"
            % URL)
        return 3
    argv = [resolve_exe(), "run", prompt,
            "--agent", "edp-neuron", "--variant", "medium", "--auto",
            "--dir", str(FLEET),
            "--session", session_id(), "--continue",
            "--attach", URL]
    env = dict(os.environ)
    env.setdefault("EDP_ROLE", "neuron")
    env.setdefault("EDP_BROKER_URL", "http://127.0.0.1:9300")
    env.setdefault("EDP_POOL_URL", "http://127.0.0.1:9301")
    env.setdefault("XDG_DATA_HOME", str(FLEET / ".fleet-data"))
    env["PWD"] = str(FLEET)
    return subprocess.run(argv, cwd=str(FLEET), env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
