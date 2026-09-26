"""S2 (s-b7ec13d748) c-ac06d82a6e, live half: a REAL claude seat spawns, works and is reaped through the
new process layer, on a private pool on a free port. Never the fleet's pool, board or broker.

    <pool venv python> scripts/s2_real_seat_drill.py [--model claude-haiku-4-5-20251001] [--out transcript.txt]

The seat's agent home is a fresh dir under <data dir>/s2-drill holding one role card (`/s2probe`: write a file, then stop), so the
seat reaches no board and loads no .mcp.json. The claude login is the pool's default config dir. Proof of
work is the file the seat writes; proof of reap is its whole tree gone, checked by (pid, create_time).
The private pool is stopped with kill_tree on its ProcId.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from edp_contracts import proc, settings
from edp_contracts.proc import ProcId, kill_tree, popen_service
from edp_contracts.toolpath import find_tool

CARD = """# /s2probe — S2 process-layer drill

Use the Write tool to create the file `s2-probe.txt` in the current directory containing exactly `S2-OK`.
Then reply `done` and stop. Do nothing else: no other tools, no questions.
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--out", default=None)
    ap.add_argument("--work-timeout", type=float, default=180.0)
    a = ap.parse_args()

    # under the data dir: inside the repo the fleet's claude config already trusts, so the seat does not
    # stop at the folder-trust dialog (which the pool never answers)
    root = settings.data_dir() / "s2-drill"
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="run-", dir=root))
    out = Path(a.out) if a.out else tmp / "transcript.txt"
    t0 = time.monotonic()

    def say(what: str, **data) -> None:
        line = f"[{time.monotonic() - t0:7.2f}s] {what}" + (f" {json.dumps(data, default=str)}" if data else "")
        print(line, flush=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    home = tmp / "home"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".claude" / "commands" / "s2probe.md").write_text(CARD, encoding="utf-8")
    port, dead_broker = _free_port(), _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP_", "EDP8_"))}
    env.update({
        "EDP_POOL_HOST": "127.0.0.1", "EDP_POOL_PORT": str(port),
        "EDP_POOL_STATE": str(tmp / "state" / "pool-state.json"),
        "EDP_POOL_LOG_DIR": str(tmp / "pool-logs"),
        "EDP_POOL_SHELL_LOG_DIR": str(tmp / "shell-logs"),
        "EDP_POOL_PAUSE_TOKENS": str(tmp / "pause"),
        "EDP_POOL_AGENT_HOME": str(home),
        "EDP_BROKER_URL": f"http://127.0.0.1:{dead_broker}",
        "EDP_SHADOW": "0", "EDP_SPAWN_MODE": "headless", "EDP_SKIP_PERMISSIONS": "1",
        "PYTHONUNBUFFERED": "1",
        # the logged-in claude config the fleet's pool pins (a temp cwd has no repo to derive it from)
        "EDP_CLAUDE_CONFIG_DIR": str(settings.setting("EDP_CLAUDE_CONFIG_DIR").default_value()
                                     if not settings.env_raw("EDP_CLAUDE_CONFIG_DIR")
                                     else settings.env_raw("EDP_CLAUDE_CONFIG_DIR")),
    })
    say("drill start", claude_config=env["EDP_CLAUDE_CONFIG_DIR"], os=sys.platform, python=sys.version.split()[0], port=port, home=str(home),
        claude=find_tool("claude"), model=a.model)
    pool_out = (tmp / "pool.out").open("wb")
    pool = popen_service([sys.executable, "-m", "edp_pool.main"], env=env, cwd=str(tmp),
                         stdout=pool_out, stderr=subprocess.STDOUT)
    pool_id = ProcId.of(pool.pid)
    base = f"http://127.0.0.1:{port}"
    ok = False
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                httpx.get(f"{base}/v1/pool/capabilities", timeout=2).raise_for_status()
                break
            except httpx.HTTPError:
                if pool.poll() is not None or time.monotonic() > deadline:
                    say("private pool failed to start", tail=(tmp / "pool.out").read_text(errors="replace")[-2000:])
                    return 2
                time.sleep(0.3)
        say("private pool up", pid=pool.pid, ident=pool_id.to_json())

        r = httpx.post(f"{base}/v1/spawn", json={"role": "s2probe", "handle": "s2probe:live", "mode": "headless",
                                                 "model": a.model}, timeout=120)
        say("POST /v1/spawn", status=r.status_code, body=r.json())
        if r.status_code != 200 or "session_id" not in r.json():
            return 3
        sid = r.json()["session_id"]
        row = next(x for x in httpx.get(f"{base}/v1/sessions", timeout=5).json() if x.get("session_id") == sid)
        seat = ProcId.from_json(row.get("proc"))
        tree = [ProcId.of(p.pid) for p in proc.tree(seat)]
        say("seat registered", state=row.get("state"), seat=seat.to_json() if seat else None,
            tree=[f"{t.pid}:{t.name}" for t in tree])

        probe = home / "s2-probe.txt"
        deadline = time.monotonic() + a.work_timeout
        while time.monotonic() < deadline and not probe.exists():
            time.sleep(1.0)
        worked = probe.exists() and probe.read_text(encoding="utf-8", errors="replace").strip() == "S2-OK"
        logs = sorted((tmp / "pool-logs").glob("*.log"))
        tail = logs[0].read_text(encoding="utf-8", errors="replace")[-1500:] if logs else ""
        say("seat work", wrote=probe.exists(), content_ok=worked, drain_log=[p.name for p in logs])
        if not worked:
            say("drain log tail", tail=tail)
        live = httpx.get(f"{base}/v1/liveness/s2probe:live", timeout=5).json()
        say("GET /v1/liveness", **live)

        tree = [ProcId.of(p.pid) for p in proc.tree(seat)] or tree
        r = httpx.post(f"{base}/v1/reap/s2probe:live", timeout=60)
        say("POST /v1/reap", status=r.status_code, body=r.json())
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and any(t.live() for t in tree):
            time.sleep(0.2)
        left = [f"{t.pid}:{t.name}" for t in tree if t.live()]
        say("after reap", tree_size=len(tree), survivors=left)
        ok = worked and not left
        return 0 if ok else 1
    finally:
        rep = kill_tree(pool_id, grace=3.0)
        say("private pool stopped by ProcId", pid=pool.pid, killed=rep.killed, survivors=len(rep.survivors))
        pool_out.close()
        say("RESULT", ok=ok, transcript=str(out))


if __name__ == "__main__":
    raise SystemExit(main())
