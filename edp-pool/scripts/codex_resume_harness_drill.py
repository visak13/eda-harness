"""t-f42af1ca59: resume of a closed codex seat must continue its codex thread, never open claude.

A REAL codex seat spawns on a private pool (free port, private state/logs; never the fleet's), lands its
first turn, and is reaped. The pool is stopped and its persisted row is rewritten to the fleet row's shape
(engineer.s-32035a77da, 2026-09-26): model "codex/gpt-6-sol", which today's catalog does not map, and no
recorded harness (a row from before the pool recorded one). A fresh pool on the same state then gets the
POST /v1/resume/<handle> the fleet got. PASS = the relaunched process is the codex runner, it thread-resumed
the SAME thread id, and no claude process started; the thread id before and after is printed.

    <edp-pool venv python> scripts/codex_resume_harness_drill.py [--code <edp-pool src dir>]

`--code` runs the pool from another source tree (a HEAD worktree's edp-pool/src reproduces the bug).
Every seat is reaped and each private pool is stopped with kill_tree on its ProcId.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import psutil
from edp_contracts import settings
from edp_contracts.proc import ProcId, kill_tree, popen_service

V8 = Path(__file__).resolve().parents[2] / "v8"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default=None, help="edp-pool src dir to run the pool from (default: this tree)")
    ap.add_argument("--spawn-model", default="gpt-6-sol", help="a catalog codex id (routes to codex at spawn)")
    ap.add_argument("--row-model", default="codex/gpt-6-sol", help="the unmapped model the fleet row carried")
    ap.add_argument("--settle", type=float, default=25.0, help="seconds to let the relaunched seat boot")
    a = ap.parse_args()

    root = settings.data_dir() / "codex-resume-drill"
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="run-", dir=root))
    t0 = time.monotonic()
    report: dict = {"code": a.code or "working tree", "run": str(tmp)}

    def say(what: str, **data) -> None:
        print(f"[{time.monotonic() - t0:7.2f}s] {what}" + (f" {json.dumps(data, default=str)}" if data else ""),
              flush=True)

    port, dead = _free_port(), _free_port()
    state = tmp / "state" / "pool-state.json"
    shell_logs = tmp / "shell-logs"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP_", "EDP8_"))}
    env.update({
        "EDP_POOL_HOST": "127.0.0.1", "EDP_POOL_PORT": str(port),
        "EDP_POOL_STATE": str(state), "EDP_POOL_LOG_DIR": str(tmp / "pool-logs"),
        "EDP_POOL_SHELL_LOG_DIR": str(shell_logs), "EDP_POOL_PAUSE_TOKENS": str(tmp / "pause"),
        "EDP_POOL_AGENT_HOME": str(V8), "EDP_BROKER_URL": f"http://127.0.0.1:{dead}",
        "EDP8_MCP_URL": f"http://127.0.0.1:{dead}/mcp",   # no board: the seat's tool calls just fail
        "EDP_CODEX_EFFORT": "low", "EDP_SHADOW": "0", "EDP_SPAWN_MODE": "headless",
        "EDP_SKIP_PERMISSIONS": "1", "PYTHONUNBUFFERED": "1",
        "EDP_CLAUDE_CONFIG_DIR": str(settings.env_raw("EDP_CLAUDE_CONFIG_DIR")
                                     or settings.setting("EDP_CLAUDE_CONFIG_DIR").default_value()),
    })
    if a.code:
        env["PYTHONPATH"] = str(Path(a.code).resolve())
    base = f"http://127.0.0.1:{port}"
    handle = f"engineer.s-drill{secrets.token_hex(3)}"
    thread_file = shell_logs / "codex" / "codex-sessions" / f"{handle}.json"
    pools: list[ProcId] = []

    def start_pool(tag: str) -> bool:
        out = (tmp / f"pool-{tag}.out").open("wb")
        p = popen_service([sys.executable, "-m", "edp_pool.main"], env=env, cwd=str(tmp),
                          stdout=out, stderr=subprocess.STDOUT)
        pools.append(ProcId.of(p.pid))
        end = time.monotonic() + 60
        while time.monotonic() < end:
            try:
                httpx.get(f"{base}/v1/pool/capabilities", timeout=2).raise_for_status()
                return True
            except httpx.HTTPError:
                if p.poll() is not None:
                    break
                time.sleep(0.3)
        say("private pool failed to start", tail=(tmp / f"pool-{tag}.out").read_text(errors="replace")[-2000:])
        return False

    def stop_pool() -> None:
        rep = kill_tree(pools.pop(), grace=3.0)
        say("private pool stopped", killed=rep.killed, survivors=len(rep.survivors))

    def row() -> dict:
        rows = httpx.get(f"{base}/v1/sessions", timeout=5).json()
        return next((r for r in rows if r.get("handle") == handle), {})

    def tree_names(proc: dict | None) -> list[str]:
        pid = ProcId.from_json(proc) if proc else None
        if pid is None or not pid.live():
            return []
        rootp = psutil.Process(pid.pid)
        names = []
        for p in [rootp, *rootp.children(recursive=True)]:
            try:
                names.append(p.name())
            except psutil.Error:
                pass
        return names

    try:
        # 1. a real codex seat: spawn, first turn lands, thread recorded
        if not start_pool("spawn"):
            return 2
        r = httpx.post(f"{base}/v1/spawn", json={"role": "engineer", "handle": handle, "mode": "headless",
                                                 "model": a.spawn_model}, timeout=180)
        say("POST /v1/spawn", status=r.status_code, body=r.json())
        end = time.monotonic() + 150
        while time.monotonic() < end and not thread_file.is_file():
            time.sleep(1.0)
        if not thread_file.is_file():
            say("FAIL: no codex thread file", logs=sorted(str(p) for p in shell_logs.rglob("*")))
            return 1
        before = json.loads(thread_file.read_text(encoding="utf-8"))["threadId"]
        spawned = row()
        report["spawn"] = {"harness": spawned.get("harness"), "procs": tree_names(spawned.get("proc")),
                           "thread": before}
        say("spawned", **report["spawn"])
        mirror = shell_logs / "codex" / f"codex-seat.{handle}.jsonl"
        end = time.monotonic() + 90   # the rollout exists once the first input landed (run_tui's witness)
        while time.monotonic() < end and not (mirror.is_file() and "turn/started" in mirror.read_text(
                encoding="utf-8", errors="replace")):
            time.sleep(1.0)
        time.sleep(5.0)
        r = httpx.post(f"{base}/v1/reap/{handle}", timeout=60)
        say("POST /v1/reap", status=r.status_code)
        stop_pool()

        # 2. the fleet row's shape: unmapped model, no recorded harness
        data = json.loads(state.read_text(encoding="utf-8"))
        rows = [s for s in data["sessions"].values() if s.get("handle") == handle]
        for s in rows:
            s["model"] = a.row_model
            (s.get("spawn_settings") or {})["model"] = a.row_model
            s.pop("harness", None)
            (s.get("spawn_settings") or {}).pop("harness", None)
        state.write_text(json.dumps(data), encoding="utf-8")
        say("row rewritten to the fleet shape", model=a.row_model, state=rows[0]["state"],
            claude_session_id=rows[0].get("claude_session_id"))

        # 3. a fresh pool gets the fleet's POST /v1/resume/<handle>
        if not start_pool("resume"):
            return 2
        r = httpx.post(f"{base}/v1/resume/{handle}", timeout=180)
        out = r.json()
        say("POST /v1/resume", status=r.status_code, body=out)
        time.sleep(a.settle)
        after_row = row()
        after = json.loads(thread_file.read_text(encoding="utf-8"))["threadId"] if thread_file.is_file() else None
        procs = tree_names(after_row.get("proc"))
        seat_log = sorted((shell_logs / "codex").glob("*.log"))
        runner = "".join(p.read_text(encoding="utf-8", errors="replace") for p in seat_log)
        report["resume"] = {"result": out, "harness": after_row.get("harness"), "procs": procs,
                            "claude_session_id": after_row.get("claude_session_id"),
                            "thread_before": before, "thread_after": after,
                            "runner_thread_resume": f"thread={before} resume=True" in runner}
        ok = (bool(out.get("resumed")) and not any("claude" in n.lower() for n in procs)
              and after == before and report["resume"]["runner_thread_resume"])
        report["pass"] = ok
        say("RESULT", **report["resume"], passed=ok)
        httpx.post(f"{base}/v1/reap/{handle}", timeout=60)
        (tmp / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        return 0 if ok else 1
    finally:
        while pools:
            stop_pool()


if __name__ == "__main__":
    raise SystemExit(main())
