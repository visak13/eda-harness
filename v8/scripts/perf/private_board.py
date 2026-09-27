"""S22 perf harness: a private board on a COPY of the fleet DB (never the fleet itself).

    python scripts/perf/private_board.py setup  <dir>            # sqlite online backup of the fleet DB + a private owner token
    python scripts/perf/private_board.py start  <dir> [--port N] [--web-dist D] [--timing] [--src <checkout>]
    python scripts/perf/private_board.py stop   <dir>

The copy follows the S9 drill (scripts/drill_cutover_copy.ps1): the DB by SQLite online backup (the fleet
DB is only read), no pool-state.json, no Slack map, no tokens of the fleet. The board runs with an allowlisted
env (no EDP* from the seat shell, the web/e2e/hermeticEnv.ts rule), a private home and run dir, the embedder
off, no pool, no broker, no RSI. `<dir>/board.json` records its identity {pid, create_time, port}; stop kills
exactly that tree (psutil children, snapshot before the kill), never by image name.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import psutil

V8 = Path(__file__).resolve().parents[2]
FLEET_DB = V8 / ".data" / "edp8.db"
OWNER = "owner"
ALLOW = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
         "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH", "USERNAME", "USER", "LOGNAME", "LOCALAPPDATA",
         "APPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "NUMBER_OF_PROCESSORS",
         "OS", "LANG", "TZ"}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def setup(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    db = d / "edp8.db"
    if db.exists():
        db.unlink()
    ro = sqlite3.connect(f"file:{FLEET_DB}?mode=ro", uri=True)
    out = sqlite3.connect(db)
    ro.backup(out)
    out.close()
    ro.close()
    from edp_contracts.settings.secrets import write_secret
    (d / "tokens.json").unlink(missing_ok=True)
    write_secret(d / "tokens.json", json.dumps({OWNER: secrets.token_urlsafe(24), "agents": {}}))
    print(f"copied {FLEET_DB} -> {db} ({db.stat().st_size // 1024} KB)")


def token(d: Path) -> str:
    return json.loads((d / "tokens.json").read_text(encoding="utf-8"))[OWNER]


def headers(d: Path) -> dict[str, str]:
    return {"X-Participant": OWNER, "X-Token": token(d)}


def env_for(d: Path, port: int, web_dist: str | None, timing: bool, src: str | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith("EDP") and (k.upper() in ALLOW or k.upper().startswith(("UV_", "PROCESSOR_")))}
    env.update(EDP_HOME=str(d), EDP8_HOME=str(d), EDP8_RUN_DIR=str(d / ".run"), EDP8_DB=str(d / "edp8.db"),
               EDP8_TOKENS=str(d / "tokens.json"), EDP8_HOST="127.0.0.1", EDP8_PORT=str(port),
               EDP8_ADMIN_TOKEN=secrets.token_urlsafe(24), EDP8_EMBEDDER="none", EDP8_LOG="warning", EDP8_UI="folio", EDP8_RSI="0",
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if web_dist:
        env["EDP8_WEB_DIST"] = web_dist
    if timing:
        env["EDP8_TIMING"] = "1"
    if src:  # another checkout's code (e.g. a HEAD worktree for the "before" numbers) ahead of the editable install
        root = Path(src).resolve()
        env["PYTHONPATH"] = os.pathsep.join(str(root / p) for p in ("v8/src", "edp-contracts/src"))
    return env


def start(d: Path, port: int | None, web_dist: str | None, timing: bool, src: str | None = None) -> dict:
    port = port or free_port()
    py = V8 / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = V8 / ".venv" / "bin" / "python"
    log = open(d / "board.log", "ab")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    p = subprocess.Popen([str(py), "-m", "edp8.service"], cwd=str(V8), env=env_for(d, port, web_dist, timing, src),
                         stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                         start_new_session=os.name != "nt")
    import httpx
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if p.poll() is not None:
            raise SystemExit(f"board exited early ({p.returncode}); see {d / 'board.log'}")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/v1/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    else:
        raise SystemExit("board did not answer /v1/health in 90 s")
    rec = {"pid": p.pid, "create_time": psutil.Process(p.pid).create_time(), "port": port,
           "base": f"http://127.0.0.1:{port}"}
    (d / "board.json").write_text(json.dumps(rec), encoding="utf-8")
    print(json.dumps(rec))
    return rec


def _board_proc(d: Path) -> psutil.Process | None:
    f = d / "board.json"
    if not f.exists():
        return None
    rec = json.loads(f.read_text(encoding="utf-8"))
    try:
        proc = psutil.Process(rec["pid"])
    except psutil.NoSuchProcess:
        return None
    return proc if abs(proc.create_time() - rec["create_time"]) < 0.01 else None


def board_pids(d: Path) -> list[psutil.Process]:
    """The private board's own process tree (the venv stub + the interpreter it launches)."""
    proc = _board_proc(d)
    if proc is None:
        return []
    return [proc, *proc.children(recursive=True)]


def stop(d: Path) -> None:
    tree = board_pids(d)  # snapshot before the first kill
    for p in reversed(tree):
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(tree, timeout=10)
    left = [p.pid for p in tree if p.is_running()]
    print(f"stopped {[p.pid for p in tree]}; survivors {left}")
    (d / "board.json").unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("setup", "start", "stop"))
    ap.add_argument("dir")
    ap.add_argument("--port", type=int)
    ap.add_argument("--web-dist")
    ap.add_argument("--timing", action="store_true")
    ap.add_argument("--src", help="a checkout root whose v8/src + edp-contracts/src run instead of this tree")
    a = ap.parse_args()
    d = Path(a.dir).resolve()
    if a.cmd == "setup":
        setup(d)
    elif a.cmd == "start":
        start(d, a.port, a.web_dist, a.timing, a.src)
    else:
        stop(d)


if __name__ == "__main__":
    sys.exit(main())
