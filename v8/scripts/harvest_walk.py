"""S-HARVEST live walk (s-043eb90ccc, criterion c-6038135e64) — the owner approves one qa-harvested proposal
and rejects another in the Library tab of a PRIVATE board, and the brief of a story on a linked epic
is read before and after each ruling.

    .venv/Scripts/python.exe scripts/harvest_walk.py

Starts the venv edp8-board.exe on a free loopback port with a temp EDP8_HOME/DB (embedder none,
hermetic env), seeds owner/architect/qa, two epics linked to one strategy_ll doc, a story on the
second epic; the qa seat files a lesson and a proposed next version (the /harvest writes); the
Library clicks run in chromium via scripts/harvest_walk.mjs. Writes docs/evidence/s-harvest/
(walk-log.txt, brief-*.json, *.png) and stops the board by its own pid. Never touches :9400.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

V8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V8 / "src"))
from edp8.bundles import ALL_TOOLS, set_client  # noqa: E402
from edp8.client import BoardClient  # noqa: E402

OUT = V8 / "docs" / "evidence" / "s-harvest"
ADMIN = "t"
# the fleet's identity/pool env must not leak into a private board (e2e/board.ts hermeticEnv)
_STRIP = ("EDP_POOL_URL", "EDP8_POOL_WATCH", "EDP_BROKER_URL", "EDP8_BOARD_URL", "EDP8_PUBLIC_URL", "EDP8_TOKEN",
          "EDP_HANDLE", "EDP8_PARTICIPANT", "EDP_ROLE", "EDP_SPAWN_SESSION_ID", "EDP8_ADMIN_TOKEN", "EDP8_USAGE_CONFIG")
LOG: list[str] = []


def log(line: str) -> None:
    print(line)
    LOG.append(line)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_board(home: Path) -> tuple[subprocess.Popen, str]:
    """The venv board on a free port with a temp home; returns (process, base url) once /healthz answers."""
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k not in _STRIP}
    env.update(EDP8_HOST="127.0.0.1", EDP8_PORT=str(port), EDP8_DB=str(home / "edp8.db"), EDP8_HOME=str(home),
               EDP8_EMBEDDER="none", EDP8_ADMIN_TOKEN=ADMIN, EDP8_LOG="warning", EDP8_UI="folio")
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
    home = Path(tempfile.mkdtemp(prefix="harvest-walk-"))
    proc, base = start_board(home)
    log(f"private board pid={proc.pid} {base} home={home}")
    try:
        http = httpx.Client(base_url=base, timeout=30)

        def call(who: str, method: str, path: str, **kw):
            headers = {"X-Participant": who, **({"X-Admin": ADMIN} if who == "admin" else {})}
            r = http.request(method, path, headers=headers, **kw).json()
            assert r["ok"], (path, r)
            return r["value"]

        for pid, role, typ in [("owner", "owner", "human"), ("architect.w", "architect", "agent"),
                               ("qa.epic-walk", "qa", "agent")]:
            call("admin", "POST", "/v1/participants", json={"id": pid, "handle": pid, "role": role, "type": typ})
        finished = call("owner", "POST", "/v1/tickets", json={"kind": "epic", "work_type": "feature",
                                                             "title": "Finished epic (harvested)"})["id"]
        nxt = call("owner", "POST", "/v1/tickets", json={"kind": "epic", "work_type": "feature",
                                                        "title": "Next epic on the same craft"})["id"]
        story = call("architect.w", "POST", "/v1/tickets", json={"kind": "story", "work_type": "feature",
                                                                "title": "A story on the next epic",
                                                                "parent_id": nxt})["id"]
        doc = call("owner", "POST", "/v1/docs", json={
            "doc_type": "strategy_ll", "title": "craft: web e2e", "scope": "global", "tags": ["web"],
            "body_md": "Bars for running the browser suite.\n\n## Enforced\n"
                       "- run the full e2e suite before hand-off [required]\n"})
        for e in (finished, nxt):
            call("owner", "POST", "/v1/links", json={"from_id": e, "to_id": doc["id"], "relation": "uses_strategy"})
        log(f"seeded: finished={finished} next={nxt} story={story} doc={doc['id']} v{doc['version']}")

        def brief(tag: str) -> list[str]:
            set_client(BoardClient(base_url=base, participant="owner"))
            tool = ALL_TOOLS["assemble_ruleset"]
            out = tool.handler(tool.args_model(ticket_id=story))
            assert out["ok"], out
            (OUT / f"brief-{tag}.json").write_text(json.dumps(out["value"], indent=2), encoding="utf-8")
            lines = [x["text"] for x in out["value"]["enforced"]]
            log(f"brief {tag}: enforced={lines}")
            return lines

        # the qa seat's /harvest writes, through the same tools a seat calls
        set_client(BoardClient(base_url=base, participant="qa.epic-walk"))
        les = ALL_TOOLS["record_lesson"]
        le = les.handler(les.args_model(domain="testing", topic="e2e",
                                        text="A full browser suite from a doer seat OOMs this host; a doer runs the "
                                             "specs it changed.", evidence=[finished]))["value"]
        dc = ALL_TOOLS["doc_create"]
        good = dc.handler(dc.args_model(
            doc_type="strategy_ll", title="craft: web e2e", scope="global", status="proposed", proposes=doc["id"],
            ticket_id=finished, body_md="Bars for running the browser suite.\n\n## Enforced\n"
                                        "- a doer runs the specs it changed; the full suite is qa's, one seat at a "
                                        "time [required]\n"))["value"]
        bad = dc.handler(dc.args_model(
            doc_type="strategy_ll", title="craft: web e2e", scope="global", status="proposed", proposes=doc["id"],
            ticket_id=finished, body_md="Bars for running the browser suite.\n\n## Enforced\n"
                                        "- skip the browser suite [required]\n"))["value"]
        log(f"qa harvest: lesson {le['id']}; proposals {good['id']} (source={good['source']}), {bad['id']}")

        def ui(mode: str, doc_id: str) -> None:
            walk = subprocess.run(["node", str(V8 / "scripts" / "harvest_walk.mjs"), base, mode, doc_id, str(OUT)],
                                  cwd=str(V8), capture_output=True, text=True, encoding="utf-8", timeout=300)
            for line in (walk.stdout + walk.stderr).splitlines():
                log(f"  ui {mode}: {line}")
            if walk.returncode:
                raise SystemExit(f"ui {mode} failed ({walk.returncode})")

        before = brief("0-before")
        ui("approve", good["id"])  # the owner's click in the Library tab
        approved = brief("1-after-approve")
        ui("reject", bad["id"])
        after = brief("2-after-reject")
        target = call("owner", "GET", f"/v1/docs/{doc['id']}")
        g, b = call("owner", "GET", f"/v1/docs/{good['id']}"), call("owner", "GET", f"/v1/docs/{bad['id']}")
        log(f"target {doc['id']}: v{target['version']} versions={target['versions']}")
        log(f"approved {good['id']}: status={g['status']} resolution={g['resolution']}")
        log(f"rejected {bad['id']}: status={b['status']} resolution={b['resolution']}")
        v2 = ["- a doer runs the specs it changed; the full suite is qa's, one seat at a time [required]"]
        ok = (before == ["- run the full e2e suite before hand-off [required]"] and approved == v2
              and after == v2
              and target["version"] == 2 and b["status"] == "retired" and b["resolution"] == "rejected")
        log(f"RESULT {'PASS' if ok else 'FAIL'}: approve -> brief carries v2; reject -> retired, brief unchanged")
        return 0 if ok else 1
    finally:
        proc.kill()
        proc.wait(timeout=30)
        log(f"stopped private board pid={proc.pid}")
        (OUT / "walk-log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
