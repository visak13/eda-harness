"""qa acceptance walk for epic-6a8a6020fd — the owner-facing criteria of S-ROLES, S-QUICK, S-LIBRARY,
S-IMPLICIT and S-UI, walked from cold on a PRIVATE board with a fake pool (never :9400 / :9301).

    .venv/Scripts/python.exe scripts/qa_walk.py

Reuses scripts/adversary_repro.py's harness (venv edp8-board.exe on a free port, temp EDP8_HOME,
embedder none, stripped fleet env, in-process FakePool) with a liveness that answers alive, and drives
the SPA through scripts/qa_walk.mjs. Writes docs/evidence/qa-epic/walk/ (walk-log.txt, *.png).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx

V8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V8 / "src"))
sys.path.insert(0, str(V8 / "scripts"))
import adversary_repro as H  # noqa: E402

OUT = V8 / "docs" / "evidence" / "qa-epic" / "walk"
LOG: list[str] = []
VERDICTS: dict[str, tuple[bool, str]] = {}


def log(line: str) -> None:
    LOG.append(line)
    print(line, flush=True)


def verdict(crit: str, ok: bool, facts: str) -> None:
    VERDICTS[crit] = (ok, facts)
    log(f"{'PASS' if ok else 'FAIL'} {crit}: {facts}")


class LivePool(H.FakePool):
    """The adversary harness's pool, but every spawned handle is alive (the criteria say 'alive in
    session_query'); sessions carry the model the board sent."""

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/v1/sessions"):
            return self._send(200, [{"session_id": s["session_id"], "role": s["role"], "handle": s["handle"],
                                     "parent": s.get("parent_session"), "state": "active", "model": s.get("model")}
                                    for s in H.SPAWNS])
        if self.path.startswith("/v1/liveness"):
            return self._send(200, {"state": "alive", "answered": True, "last_output_ts": time.time()})
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        if self.path.startswith("/v1/liveness"):
            return self._send(200, {"state": "alive", "answered": True, "last_output_ts": time.time()})
        return super().do_POST()


def start_pool() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), LivePool)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def ui(base: str, mode: str, args: dict) -> dict:
    p = subprocess.run(["node", str(V8 / "scripts" / "qa_walk.mjs"), base, mode, json.dumps(args), str(OUT)],
                       cwd=str(V8), capture_output=True, text=True, encoding="utf-8", timeout=240)
    line = (p.stdout.strip().splitlines() or ["{}"])[-1]
    try:
        out = json.loads(line)
    except json.JSONDecodeError:
        out = {"error": (p.stdout + p.stderr)[-800:]}
    log(f"  ui {mode}: {json.dumps(out)[:900]}")
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="qa-walk-"))
    pool, pool_url = start_pool()
    for k in H._STRIP:
        os.environ.pop(k, None)
    os.environ["EDP_POOL_URL"] = pool_url
    os.environ["EDP8_HOME"] = str(home)
    os.environ["EDP8_PAIN_FILE"] = str(home / "pain-points.jsonl")
    proc, base = H.start_board(home, pool_url)
    log(f"private board pid={proc.pid} {base} pool={pool_url} home={home}")
    try:
        from qa_walk_steps import run_steps
        run_steps(base, home, log, verdict, ui)
    finally:
        proc.kill()
        proc.wait(timeout=30)
        pool.shutdown()
        log(f"stopped private board pid={proc.pid}; pool spawns={len(H.SPAWNS)}")
        log("")
        for c, (ok, facts) in VERDICTS.items():
            log(f"RESULT {c} {'PASS' if ok else 'FAIL'} — {facts}")
        (OUT / "walk-log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
        shutil.rmtree(home, ignore_errors=True)
    return 0 if all(v[0] for v in VERDICTS.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
