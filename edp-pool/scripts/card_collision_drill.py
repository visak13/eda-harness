"""t-67dad8c6aa: does a role card named like a Claude Code built-in slash command ever run? A REAL claude seat
spawns on a private pool (free port, never the fleet's) for each card name given; each card is the same probe
(write `<name>-probe.txt`, reply done). The card ran iff its probe file appears.

    <pool venv python> scripts/card_collision_drill.py doctor s19ctl [--model claude-haiku-4-5-20251001]

Reuses s2_real_seat_drill.py's recipe: agent home under the data dir (trusted, no folder-trust dialog), the
pool's logged-in claude config, no board and no .mcp.json. Prints one RESULT line per name and the drain-log
tail of any seat whose card did not run (what claude showed instead). Every seat is reaped and the private
pool is stopped with kill_tree on its ProcId.
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
from edp_contracts import settings
from edp_contracts.proc import ProcId, kill_tree, popen_service

CARD = """# /{name} — card collision probe

Use the Write tool to create the file `{name}-probe.txt` in the current directory containing exactly `CARD-RAN`.
Then reply `done` and stop. Do nothing else: no other tools, no questions.
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _claude_argv(base: str, sid: str | None) -> list[str] | None:
    """The seat's claude command line (the launch line the board's diagnosis quoted)."""
    import psutil
    row = next((x for x in httpx.get(f"{base}/v1/sessions", timeout=5).json() if x.get("session_id") == sid), {})
    seat = ProcId.from_json(row.get("proc")) if row.get("proc") else None
    if seat is None or not seat.live():
        return None
    root = psutil.Process(seat.pid)
    for p in [root, *root.children(recursive=True)]:
        try:
            cl = p.cmdline()
        except psutil.Error:
            continue
        if any("claude" in c.lower() for c in cl[:2]) and "--disallowedTools" in cl or "--model" in cl:
            return cl[1:] if len(cl) > 1 else cl
    return root.cmdline()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--work-timeout", type=float, default=150.0)
    ap.add_argument("--mode", choices=("headless", "monitor"), default="headless",
                    help="monitor = the fleet's visible consoles: the card rides argv as the initial prompt")
    ap.add_argument("--disallow", default="",
                    help="EDP_SEAT_DISALLOWED_TOOLS for the seat, as the board sets it for a read-only role")
    a = ap.parse_args()

    root = settings.data_dir() / "card-collision-drill"
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="run-", dir=root))
    t0 = time.monotonic()

    def say(what: str, **data) -> None:
        print(f"[{time.monotonic() - t0:7.2f}s] {what}" + (f" {json.dumps(data, default=str)}" if data else ""),
              flush=True)

    home = tmp / "home"
    (home / ".claude" / "commands").mkdir(parents=True)
    for n in a.names:
        (home / ".claude" / "commands" / f"{n}.md").write_text(CARD.format(name=n), encoding="utf-8")
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
        "EDP_CLAUDE_CONFIG_DIR": str(settings.env_raw("EDP_CLAUDE_CONFIG_DIR")
                                     or settings.setting("EDP_CLAUDE_CONFIG_DIR").default_value()),
    })
    say("drill start", names=a.names, model=a.model, port=port, home=str(home))
    pool_out = (tmp / "pool.out").open("wb")
    pool = popen_service([sys.executable, "-m", "edp_pool.main"], env=env, cwd=str(tmp),
                         stdout=pool_out, stderr=subprocess.STDOUT)
    pool_id = ProcId.of(pool.pid)
    base = f"http://127.0.0.1:{port}"
    results: dict[str, bool] = {}
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
        for n in a.names:
            handle = f"{n}:probe"
            body = {"role": n, "handle": handle, "mode": a.mode, "model": a.model}
            if a.disallow:
                body["env"] = {"EDP_SEAT_DISALLOWED_TOOLS": a.disallow}
            r = httpx.post(f"{base}/v1/spawn", json=body, timeout=120)
            say("POST /v1/spawn", name=n, mode=a.mode, disallow=a.disallow, status=r.status_code, body=r.json())
            time.sleep(3.0)
            say("seat argv", argv=_claude_argv(base, r.json().get("session_id")))
            probe = home / f"{n}-probe.txt"
            deadline = time.monotonic() + a.work_timeout
            while time.monotonic() < deadline and not probe.exists():
                time.sleep(1.0)
            ran = probe.exists() and probe.read_text(encoding="utf-8", errors="replace").strip() == "CARD-RAN"
            results[n] = ran
            if not ran:
                logs = sorted((tmp / "pool-logs").glob(f"*{n}*")) or sorted((tmp / "pool-logs").glob("*"))
                for p in logs:
                    say("drain log tail", file=p.name,
                        tail=p.read_text(encoding="utf-8", errors="replace")[-2500:])
            say("RESULT", name=n, card_ran=ran)
            httpx.post(f"{base}/v1/reap/{handle}", timeout=60)
        return 0
    finally:
        rep = kill_tree(pool_id, grace=3.0)
        say("private pool stopped", killed=rep.killed, survivors=len(rep.survivors), results=results)
        pool_out.close()


if __name__ == "__main__":
    raise SystemExit(main())
