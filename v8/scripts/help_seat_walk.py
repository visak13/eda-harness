"""t-67dad8c6aa (c-7ba9097c4a): a REAL Claude Help seat boots on its card and answers on the help thread.

A PRIVATE heronry instance (free ports, EDP_HOME under this repo so claude trusts the agent home, env marker)
-> `heronry init --harness claude` -> `heronry start` -> `heronry doctor --agent "<question>"` (the same
POST /v1/help the rail's Ask for help sends) -> the pool spawns `doctor.<topic>` -> this script records the
seat's claude launch line and waits for the seat's reply on the thread -> `heronry stop`, no survivors.

    <v8 venv python> scripts/help_seat_walk.py [--timeout 180]

The seat uses the pool's logged-in claude config (EDP_CLAUDE_CONFIG_DIR, default edp-pool/.claude-pool) and
the catalog's doctor model, so it spends real tokens. Never touches the fleet's board, pool or broker.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx
import psutil

V8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V8 / "tests"))
import test_cli_launcher as base  # noqa: E402
from edp_contracts.proc import kill_tree, scan_env_marker  # noqa: E402

QUESTION = ("Health check from a walk: which services are up? Answer on this thread in two lines, "
            "citing the read tool you used.")


def _launch_lines(marker: str, value: str) -> list[list[str]]:
    """Every claude process of this instance carrying the Help card prompt or the seat's deny list."""
    out = []
    for ident in scan_env_marker(marker, value):
        try:
            cl = psutil.Process(ident.pid).cmdline()
        except psutil.Error:
            continue
        if any("claude" in c.lower() for c in cl[:3]) and any(a == "/doctor" or a.startswith("--disallowedTools")
                                                               for a in cl):
            out.append(cl)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=180.0)
    a = ap.parse_args()
    t0 = time.monotonic()

    def say(what: str, **data) -> None:
        print(f"[{time.monotonic() - t0:7.2f}s] {what}" + (f" {json.dumps(data, default=str)}" if data else ""),
              flush=True)

    root = V8 / ".data" / "help-seat-walk"
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f"inst-{uuid.uuid4().hex[:6]}"
    tmp.mkdir()
    board, mcp, pool, broker = base._free_ports(4)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP", "HERONRY", "CLAUDE_CONFIG_DIR", "PYTHONPATH"))}
    env.update(EDP_HOME=str(tmp / "home"),
               EDP_CLAUDE_CONFIG_DIR=os.environ.get("EDP_CLAUDE_CONFIG_DIR") or str(base.ROOT / "edp-pool" / ".claude-pool"),
               EDP8_PORT=str(board), EDP8_MCP_PORT=str(mcp), EDP_POOL_PORT=str(pool), EDP_BROKER_PORT=str(broker),
               EDP8_EMBEDDER="none", PYTHONIOENCODING="utf-8", HERONRY_NO_UPDATE_CHECK="1")
    env[base.MARKER] = uuid.uuid4().hex
    for svc, project in (("POOL", base.ROOT / "edp-pool"), ("BROKER", base.ROOT / "edp-broker")):
        env[f"EDP_{svc}_PYTHON"] = str(base._venv_py(project))
    inst = {"env": env, "ports": {"board": board, "mcp": mcp, "pool": pool, "broker": broker}, "home": tmp / "home"}
    say("private instance", ports=inst["ports"], home=str(inst["home"]), claude_config=env["EDP_CLAUDE_CONFIG_DIR"])
    ok = False
    try:
        r = base.cli(inst, "init", "--harness", "claude", "--agent-home-source", str(V8))
        say("init", rc=r.returncode, tail=r.stdout[-400:])
        assert r.returncode == 0, r.stderr[-800:]
        mj = inst["home"] / "agent-home" / "models.json"
        if mj.exists():  # the fleet file's `harnesses` key would add codex/pi to a claude-only walk
            reg = json.loads(mj.read_text(encoding="utf-8"))
            reg.pop("harnesses", None)
            mj.write_text(json.dumps(reg, indent=2), encoding="utf-8")
        r = base.cli(inst, "start", "--no-browser")
        say("start", rc=r.returncode, tail=re.sub(r"code=[^ ]+", "code=<redacted>", r.stdout)[-400:])
        assert r.returncode == 0, r.stderr[-800:]
        r = base.cli(inst, "doctor", "--agent", QUESTION)
        say("heronry doctor --agent", rc=r.returncode, out=r.stdout.strip()[-400:], err=r.stderr.strip()[-400:])
        assert r.returncode == 0
        topic = re.search(r"(topic-[0-9a-f]+)", r.stdout).group(1)
        seat = f"doctor.{topic}"
        tokens = next(inst["home"].rglob("tokens.json"))
        data = json.loads(tokens.read_text(encoding="utf-8"))
        owner = next(k for k, v in data.items() if isinstance(v, str))
        headers = {"X-Participant": owner, "X-Token": data[owner]}
        url = f"http://127.0.0.1:{board}"
        deadline = time.monotonic() + a.timeout
        launch: list[list[str]] = []
        reply = None
        while time.monotonic() < deadline and reply is None:
            launch = launch or _launch_lines(base.MARKER, env[base.MARKER])
            page = httpx.get(f"{url}/v1/topics/{topic}", headers=headers, timeout=10).json().get("value") or {}
            thread = page.get("thread") or []
            msgs = thread.get("messages", thread) if isinstance(thread, dict) else thread
            reply = next((m for m in msgs if isinstance(m, dict) and m.get("created_by") == seat), None)
            if reply is None:
                time.sleep(3.0)
        seat_row = (httpx.get(f"{url}/v1/help", headers=headers, timeout=10).json().get("value") or [{}])[0].get("seat")
        say("seat launch line", argv=launch[0][1:] if launch else None)
        say("help list seat", seat=seat_row)
        if reply:
            say("seat reply", message_id=reply.get("id"), after_s=round(time.monotonic() - t0, 1),
                text=str(reply.get("text"))[:400])
        else:
            say("no reply from the seat", seat=seat, waited_s=a.timeout)
        ok = bool(launch and reply and "--model" in launch[0])  # monitor: argv ends in /doctor; headless types it
        return 0 if ok else 1
    finally:
        s = base.cli(inst, "stop")
        say("stop", rc=s.returncode)
        for ident in scan_env_marker(base.MARKER, env[base.MARKER]):
            kill_tree(ident, grace=2.0)
        say("RESULT", ok=ok, survivors=len(scan_env_marker(base.MARKER, env[base.MARKER])))


if __name__ == "__main__":
    raise SystemExit(main())
