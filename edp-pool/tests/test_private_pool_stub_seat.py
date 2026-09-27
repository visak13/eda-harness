"""S2 (s-b7ec13d748) criterion c-ac06d82a6e: a private pool on a free port spawns a stub-harness seat
through the PTY abstraction, the seat answers, and a reap leaves no process behind. Runs on every OS
(the CI matrix legs run it too).

The pool is a real `python -m edp_pool.main` (uvicorn) with every path in the test's tmp dir, a claude
bin that is the stub harness (a .cmd shim on Windows, which also exercises the toolpath COMSPEC route; a
sh script on POSIX), and a broker URL nothing listens on. It is stopped with `kill_tree` on its ProcId;
nothing here touches the fleet's pool, board or broker.

Set EDP_S2_TRANSCRIPT=<file> to keep the transcript.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
from edp_contracts import proc
from edp_contracts.proc import ProcId, kill_tree, popen_service

STUB = Path(__file__).parent / "fixtures" / "stub_harness.py"
MARK = "EDP_TEST_RUN"
RUN = f"pool-{uuid.uuid4().hex[:8]}"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Transcript:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.t0 = time.monotonic()

    def __call__(self, what: str, **data) -> None:
        line = f"[{time.monotonic() - self.t0:7.2f}s] {what}" + (f" {json.dumps(data, default=str)}" if data else "")
        print(line)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _stub_bin(d: Path) -> Path:
    if sys.platform == "win32":
        p = d / "claude-stub.cmd"
        p.write_text(f'@"{sys.executable}" "{STUB}" %*\r\n', encoding="utf-8")
    else:
        p = d / "claude-stub"
        p.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{STUB}" "$@"\n', encoding="utf-8")
        p.chmod(0o755)
    return p


@pytest.fixture(autouse=True)
def no_survivors():
    yield
    left = proc.scan_env_marker(MARK, RUN)
    for p in left:
        kill_tree(p, grace=1.0)
    assert not left, f"processes survived the test: {left}"


def test_private_pool_spawns_a_stub_seat_and_reaps_it(tmp_path):
    say = Transcript(Path(os.environ.get("EDP_S2_TRANSCRIPT") or tmp_path / "transcript.txt"))
    port, dead_broker = _free_port(), _free_port()
    home = tmp_path / "home"
    home.mkdir()
    stub = _stub_bin(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("EDP", "HERONRY"))}
    env.update({
        MARK: RUN,
        "EDP_HOME": str(tmp_path / "edp-home"),  # never the real profile's config.toml
        "EDP_POOL_HOST": "127.0.0.1", "EDP_POOL_PORT": str(port),
        "EDP_POOL_STATE": str(tmp_path / "state" / "pool-state.json"),
        "EDP_POOL_LOG_DIR": str(tmp_path / "pool-logs"),
        "EDP_POOL_SHELL_LOG_DIR": str(tmp_path / "shell-logs"),
        "EDP_POOL_PAUSE_TOKENS": str(tmp_path / "pause"),
        "EDP_POOL_AGENT_HOME": str(home),
        "EDP_POOL_CLAUDE_HOME": str(tmp_path / "claude-home"),
        "EDP_BROKER_URL": f"http://127.0.0.1:{dead_broker}",
        "EDP_CLAUDE_BIN": str(stub),
        "EDP_SHADOW": "0", "EDP_SPAWN_MODE": "headless",
        "PYTHONUNBUFFERED": "1",
    })
    say("platform", os=sys.platform, python=sys.version.split()[0], port=port, stub=str(stub))
    log = (tmp_path / "pool.out").open("wb")
    pool = popen_service([sys.executable, "-m", "edp_pool.main"], env=env, cwd=str(tmp_path),
                         stdout=log, stderr=subprocess_stdout())
    pool_id = ProcId.of(pool.pid)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                caps = httpx.get(f"{base}/v1/pool/capabilities", timeout=2).json()
                break
            except httpx.HTTPError:
                assert pool.poll() is None, f"private pool exited: {(tmp_path / 'pool.out').read_text(errors='replace')[-2000:]}"
                assert time.monotonic() < deadline, "private pool never answered"
                time.sleep(0.3)
        say("pool up", pid=pool.pid, capabilities=caps)

        r = httpx.post(f"{base}/v1/spawn", json={"role": "worker", "handle": "stub:s2", "mode": "headless"},
                       timeout=90)
        say("POST /v1/spawn", status=r.status_code, body=r.json())
        assert r.status_code == 200 and "session_id" in r.json(), r.text
        sid = r.json()["session_id"]

        rows = httpx.get(f"{base}/v1/sessions", timeout=5).json()
        row = next(x for x in rows if sid in (x.get("session_id"), x.get("sid"), x.get("id")))
        fp = row.get("proc") or {}
        seat_pid = fp.get("pid")
        say("session row", state=row.get("state"), pid=seat_pid, fingerprint=fp)
        assert seat_pid, row
        seat = ProcId.of(int(seat_pid))
        kids = [ProcId.of(p.pid) for p in proc.tree(seat)[1:]]
        say("seat tree", root=seat.to_json(), descendants=[k.to_json() for k in kids])
        assert kids, "the stub seat has no descendants (expected python under the shim, and its grandchild)"

        logs = list((tmp_path / "pool-logs").glob("*.log"))
        deadline = time.monotonic() + 30
        text = ""
        while time.monotonic() < deadline:
            text = "".join(p.read_text(encoding="utf-8", errors="replace") for p in logs) if logs else ""
            if "ECHO:" in text:
                break
            logs = list((tmp_path / "pool-logs").glob("*.log"))
            time.sleep(0.2)
        say("seat drain log", files=[p.name for p in logs], tail=text[-600:])
        assert "❯" in text, "the stub never reached its ready marker through the pool's PTY"
        assert "ECHO:" in text, "the pool's activation never reached the seat"

        live = httpx.get(f"{base}/v1/liveness/stub:s2", timeout=5).json()
        say("GET /v1/liveness", **live)
        assert live["state"] in ("alive", "active", "busy", "idle"), live

        r = httpx.post(f"{base}/v1/reap/stub:s2", timeout=60)
        say("POST /v1/reap", status=r.status_code, body=r.json())
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and (seat.live() or any(k.live() for k in kids)):
            time.sleep(0.1)
        say("after reap", seat_live=seat.live(), descendants_live=[k.pid for k in kids if k.live()])
        assert not seat.live() and not any(k.live() for k in kids)
    finally:
        rep = kill_tree(pool_id, grace=3.0)
        say("private pool stopped by ProcId", pid=pool.pid, killed=rep.killed, survivors=len(rep.survivors))
        log.close()


def subprocess_stdout():
    import subprocess
    return subprocess.STDOUT
