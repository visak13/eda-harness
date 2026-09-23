"""S-ADV (s-966102b3c9) — qa reproduction of the adversary round's findings (consult run
20260923T195543Z-751643bd, gpt-6-astra) against this tree, from cold, on a PRIVATE board.

    .venv/Scripts/python.exe scripts/adversary_repro.py

Starts the venv edp8-board.exe on a free loopback port with a temp EDP8_HOME (embedder none, hermetic
env) and a FAKE POOL (this process; /v1/limits, /v1/spawn, /v1/sessions, /v1/pool/capabilities,
/v1/liveness) so every spawn path runs end to end without a shell. Each finding is one function that
prints REPRO / NOT-REPRO with the observed facts; the exit code is the count of reproduced findings.
Never touches :9400. Log: docs/evidence/s-adv/repro-log.txt.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

V8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V8 / "src"))
sys.path.insert(0, str(V8 / "scripts"))

OUT = V8 / "docs" / "evidence" / "s-adv"
ADMIN = "t"
_STRIP = ("EDP_POOL_URL", "EDP8_POOL_WATCH", "EDP_BROKER_URL", "EDP8_BOARD_URL", "EDP8_PUBLIC_URL", "EDP8_TOKEN",
          "EDP_HANDLE", "EDP8_PARTICIPANT", "EDP_ROLE", "EDP_SPAWN_SESSION_ID", "EDP8_ADMIN_TOKEN", "EDP8_USAGE_CONFIG",
          "EDP_POOL_AGENT_HOME", "EDP_AGENT_HOME")
LOG: list[str] = []
RESULTS: list[tuple[str, bool, str]] = []


def log(line: str) -> None:
    print(line)
    LOG.append(line)


def result(name: str, reproduced: bool, facts: str) -> None:
    RESULTS.append((name, reproduced, facts))
    log(f"{'REPRO    ' if reproduced else 'NOT-REPRO'} {name}: {facts}")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ----------------------------------------------------------------------------- fake pool
SPAWNS: list[dict] = []


class FakePool(BaseHTTPRequestHandler):
    def _send(self, code: int, body: object) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/v1/limits"):
            return self._send(200, {"max_workers": 6})
        if self.path.startswith("/v1/pool/capabilities"):
            return self._send(200, {"resume_parked": True, "resume_closed": True, "park": True, "spawn": True})
        if self.path.startswith("/v1/sessions"):
            return self._send(200, [{"session_id": s["session_id"], "role": s["role"], "handle": s["handle"],
                                     "parent": s.get("parent_session"), "state": "running"} for s in SPAWNS])
        if self.path.startswith("/v1/liveness"):
            return self._send(200, {"state": "dead"})
        return self._send(404, {"error": "no"})

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/v1/spawn":
            body["session_id"] = f"sess-{len(SPAWNS) + 1}"
            SPAWNS.append(body)
            return self._send(200, {"session_id": body["session_id"], "handle": body.get("handle")})
        if self.path.startswith("/v1/liveness"):
            return self._send(200, {"state": "dead"})
        return self._send(200, {"ok": True})

    def log_message(self, *a):  # quiet
        pass


def start_fake_pool() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakePool)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def start_board(home: Path, pool_url: str) -> tuple[subprocess.Popen, str]:
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k not in _STRIP}
    (home / "models.json").write_text((V8 / "models.json").read_text(encoding="utf-8"), encoding="utf-8")
    env.update(EDP8_HOST="127.0.0.1", EDP8_PORT=str(port), EDP8_DB=str(home / "edp8.db"), EDP8_HOME=str(home),
               EDP8_EMBEDDER="none", EDP8_ADMIN_TOKEN=ADMIN, EDP8_LOG="warning", EDP8_UI="folio",
               EDP_POOL_URL=pool_url)
    exe = V8 / ".venv" / "Scripts" / "edp8-board.exe"
    proc = subprocess.Popen([str(exe)], cwd=str(V8), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                return proc, base
        except httpx.HTTPError:
            pass
        if proc.poll() is not None:
            raise SystemExit(f"board exited early ({proc.returncode})")
        time.sleep(0.5)
    proc.kill()
    raise SystemExit("board did not answer /healthz")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="adv-repro-"))
    pool, pool_url = start_fake_pool()
    # the in-process MCP tool probes (bundles.spawn → pool_adapter) read THIS process's env: point them
    # at the fake pool and the temp home, never at the fleet pool (2026-09-23: a first run spawned three
    # real shells D/Q/E2 on :9301 before this guard existed — reaped by hand)
    for k in _STRIP:
        os.environ.pop(k, None)
    os.environ["EDP_POOL_URL"] = pool_url
    os.environ["EDP8_HOME"] = str(home)
    proc, base = start_board(home, pool_url)
    log(f"private board pid={proc.pid} {base} fake pool {pool_url} home={home}")
    try:
        http = httpx.Client(base_url=base, timeout=30)

        def call(who: str, method: str, path: str, **kw) -> dict:
            headers = {"X-Participant": who, **({"X-Admin": ADMIN} if who == "admin" else {})}
            r = http.request(method, path, headers=headers, **kw)
            try:
                return r.json()
            except ValueError:
                return {"ok": False, "status": r.status_code, "text": r.text[:200]}

        def ok(who: str, method: str, path: str, **kw) -> dict:
            r = call(who, method, path, **kw)
            assert r.get("ok"), (who, method, path, r)
            return r["value"]

        for pid, role, typ in [("owner", "owner", "human"), ("A", "architect", "agent"), ("A2", "architect", "agent"),
                               ("E", "engineer", "agent"), ("Q", "qa", "agent"), ("D", "adversary", "agent")]:
            ok("admin", "POST", "/v1/participants", json={"id": pid, "handle": pid, "role": role, "type": typ})
        X = ok("owner", "POST", "/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "epic X",
                                                    "assignee": "A"})["id"]
        Y = ok("owner", "POST", "/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "epic Y",
                                                    "assignee": "A2"})["id"]
        S = ok("A", "POST", "/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "story S",
                                                "parent_id": X, "assignee": "E"})["id"]
        log(f"seeded X={X} (architect A) Y={Y} (architect A2) S={S} (engineer E)")

        # ---- 1. architect spawns an owner-role participant -------------------------------------
        r = call("A", "POST", "/v1/sessions/spawn", json={"role": "owner", "participant_id": "new-owner",
                                                          "ticket_id": X})
        made = call("owner", "GET", "/v1/participants/new-owner")
        mv = made.get("value") or {}
        role = mv.get("role") or (mv.get("participant") or {}).get("role") if made.get("ok") else None
        log(f"   participant new-owner read: {json.dumps(made)[:200]}")
        result("1 architect mints an owner via /v1/sessions/spawn", bool(r.get("ok")) and role == "owner",
               f"spawn ok={r.get('ok')} error={(r.get('error') or {}).get('message', '')[:80]!r} "
               f"participant new-owner role={role}")

        # ---- 4. architect spawns a foreign-epic participant id under its own ticket ------------
        SPAWNS.clear()
        r = call("A", "POST", "/v1/sessions/spawn", json={"role": "engineer", "participant_id": f"engineer.{Y}",
                                                          "ticket_id": X})
        result("4 architect spawns engineer.<other epic> by naming its own ticket", bool(r.get("ok")),
               f"spawn ok={r.get('ok')} pool got handles={[s.get('handle') for s in SPAWNS]} "
               f"error={(r.get('error') or {}).get('message', '')[:80]!r}")

        # ---- 3. qa/adversary as assignee through PATCH and the MCP spawn tool -------------------
        p1 = call("E", "PATCH", f"/v1/tickets/{S}", json={"assignee": "Q"})
        p2 = call("E", "PATCH", f"/v1/tickets/{S}", json={"assignee": "D"})
        p3 = call("owner", "PATCH", f"/v1/tickets/{S}", json={"assignee": "Q"})
        now = ok("owner", "GET", f"/v1/tickets/{S}")
        assignee_now = (now.get("ticket") or now).get("assignee")
        result("3a PATCH assignee=qa/adversary accepted", bool(p1.get("ok") or p2.get("ok") or p3.get("ok")),
               f"engineer→Q ok={p1.get('ok')} engineer→D ok={p2.get('ok')} owner→Q ok={p3.get('ok')} "
               f"assignee now={assignee_now}")
        ok("owner", "PATCH", f"/v1/tickets/{S}", json={"assignee": "E"})
        from edp8.bundles import ALL_TOOLS, set_client  # noqa: E402
        from edp8.client import BoardClient  # noqa: E402
        S2 = ok("A", "POST", "/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "story S2",
                                                 "parent_id": X})["id"]  # unassigned
        set_client(BoardClient(base_url=base, participant="owner"))
        SPAWNS.clear()
        sp = ALL_TOOLS["spawn"]
        mcp = sp.handler(sp.args_model(role="adversary", participant_id="D", ticket_id=S2))
        after = ok("owner", "GET", f"/v1/tickets/{S2}")
        a2 = (after.get("ticket") or after).get("assignee")
        result("3b MCP spawn(role=adversary, ticket_id=<unassigned story>) assigns the adversary",
               bool(mcp.get("ok")) and a2 == "D", f"mcp ok={mcp.get('ok')} assignee={a2} pool={len(SPAWNS)} spawn(s)")
        SPAWNS.clear()
        mcp_e = sp.handler(sp.args_model(role="qa", participant_id="Q", ticket_id=S))  # S has a live-less assignee E
        after_s = ok("owner", "GET", f"/v1/tickets/{S}")
        result("3c MCP spawn(role=qa) on a story with an assignee keeps the doer",
               (after_s.get("ticket") or after_s).get("assignee") != "E",
               f"mcp ok={mcp_e.get('ok')} assignee={(after_s.get('ticket') or after_s).get('assignee')}")

        # ---- 2. MCP spawn tool as an engineer (no REST authz) ----------------------------------
        set_client(BoardClient(base_url=base, participant="E"))
        SPAWNS.clear()
        mcp2 = sp.handler(sp.args_model(role="engineer", participant_id="E2", ticket_id=S2, assign=False))
        result("2 MCP spawn tool as an engineer reaches the pool", bool(mcp2.get("ok")) and len(SPAWNS) > 0,
               f"tool ok={mcp2.get('ok')} error={(mcp2.get('error') or {}).get('message', '')[:100]!r} "
               f"pool spawns={len(SPAWNS)}")
        rest2 = call("E", "POST", "/v1/sessions/spawn", json={"role": "engineer", "participant_id": "E3",
                                                             "ticket_id": S2})
        log(f"   (REST spawn as engineer: ok={rest2.get('ok')} status={rest2.get('status')} "
            f"{(rest2.get('error') or {}).get('message', str(rest2.get('text')))[:100]!r})")

        # ---- 5. architect edits another epic's model tags --------------------------------------
        t5 = call("A", "PATCH", f"/v1/tickets/{Y}", json={"tags": ["model:engineer=gpt-6-sol"]})
        y = ok("owner", "GET", f"/v1/tickets/{Y}")
        result("5 architect A sets model tags on epic Y (architect A2's)", bool(t5.get("ok")),
               f"patch ok={t5.get('ok')} Y.tags={(y.get('ticket') or y).get('tags')}")

        # ---- 10. unknown / out-of-role model id accepted ---------------------------------------
        ok("owner", "PATCH", f"/v1/tickets/{X}", json={"tags": ["model:engineer=gpt-does-not-exist"]})
        SPAWNS.clear()
        sp10 = call("owner", "POST", "/v1/sessions/spawn", json={"role": "engineer", "participant_id": "E10",
                                                                 "ticket_id": S2})
        got = [s.get("model") for s in SPAWNS]
        result("10 unknown model id in model:<role>= reaches the pool", bool(sp10.get("ok")) and "codex/gpt-does-not-exist" in got,
               f"spawn ok={sp10.get('ok')} pool model={got} seat_choice={(sp10.get('value') or {}).get('seat_choice')}")
        ok("owner", "PATCH", f"/v1/tickets/{X}", json={"tags": []})

        # ---- 8. duplicate pain id → two lessons ----------------------------------------------
        from edp8 import records  # noqa: E402
        from edp8.board import Board  # noqa: E402
        from edp8.store import Store  # noqa: E402
        b = Board(Store(":memory:"))
        pf = home / "pains.jsonl"
        pf.write_text('{"id":"p-one","symptom":"first symptom","area":"testing"}\n'
                      '{"id":"p-one","symptom":"updated symptom","area":"testing"}\n', encoding="utf-8")
        records._pain_seen.clear()
        made8 = records.lessons_from_pains(b, pf)
        result("8 one pain id filed twice makes two lessons", len(made8) == 2,
               f"lessons={len(made8)} evidence={[le.evidence for le in made8]}")

        # ---- 6. harvest_cost codex accounting across threads ---------------------------------
        import harvest_cost  # noqa: E402
        rows = [{"ts": 1, "msg": {"method": "thread/tokenUsage/updated", "params": {"threadId": "old", "tokenUsage": {"total": {"inputTokens": 10000, "totalTokens": 10000}}}}},
                {"ts": 11, "msg": {"method": "thread/tokenUsage/updated", "params": {"threadId": "new", "tokenUsage": {"total": {"inputTokens": 100, "totalTokens": 100}}}}}]
        tok = harvest_cost.codex_tokens(rows, 10, None)
        result("6 harvest_cost.codex_tokens goes negative across threads", tok.get("inputTokens", 0) < 0,
               f"inputTokens={tok.get('inputTokens')} totalTokens={tok.get('totalTokens')}")

        # ---- 9. harvest_cost --log missing file -----------------------------------------------
        r9 = subprocess.run([str(V8 / ".venv" / "Scripts" / "python.exe"), "-B", str(V8 / "scripts" / "harvest_cost.py"),
                             "--participant", "qa.test", "--log", "__missing_review_log__.jsonl", "--no-board"],
                            cwd=str(V8), capture_output=True, text=True, timeout=120)
        result("9 harvest_cost --log <missing> tracebacks", "Traceback" in r9.stderr,
               f"rc={r9.returncode} stderr_tail={r9.stderr.strip().splitlines()[-1][:100] if r9.stderr.strip() else ''!r}")

        # ---- 7. library http_get total deadline ---------------------------------------------
        from edp8 import library  # noqa: E402
        import edp8.library as lib_mod  # noqa: E402

        class _Resp:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def iter_bytes(self):
                clock["t"] = 9.0
                yield b"a"
                clock["t"] = 18.0
                yield b"b"

        class _Client:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, *a, **k):
                return _Resp()

            def stream(self, *a, **k):
                return _Resp()

        clock = {"t": 0.0}
        real_client, real_mono = lib_mod.httpx.Client, lib_mod.time.monotonic
        lib_mod.httpx.Client = _Client  # type: ignore[assignment]
        lib_mod.time.monotonic = lambda: clock["t"]  # type: ignore[assignment]
        try:
            try:
                library.http_get("https://raw.githubusercontent.com/x/y/main/SKILL.md")
                obs = f"returned at t={clock['t']}"
                late = clock["t"] > 10
            except Exception as e:  # noqa: BLE001
                import traceback
                obs = f"{type(e).__name__}: {e} at t={clock['t']} :: {traceback.format_exc().splitlines()[-3][:120]}"
                late = clock["t"] > 10
        finally:
            lib_mod.httpx.Client, lib_mod.time.monotonic = real_client, real_mono
        result("7 http_get 10 s total deadline is checked only after a blocking read", late, obs)

        n = sum(1 for _, r_, _ in RESULTS if r_)
        log(f"RESULT: {n}/{len(RESULTS)} findings reproduced")
        return n
    finally:
        proc.kill()
        proc.wait(timeout=30)
        pool.shutdown()
        log(f"stopped private board pid={proc.pid}")
        (OUT / "repro-log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
