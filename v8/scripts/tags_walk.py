"""t-683d0033bb live case — the owner's Tags input in the new-epic and quick-task dialogs reaches the Library
auto-link, walked on a PRIVATE board with a fake pool (never :9400 / :9301 / v8/tokens.json).

    .venv/Scripts/python.exe scripts/tags_walk.py

Reuses scripts/qa_walk.py's harness (venv edp8-board.exe on a free port, temp EDP8_HOME + its own
EDP8_TOKENS, embedder none, stripped fleet env, LivePool) and drives the SPA through scripts/tags_walk.mjs.
Seeds one active domain doc tagged `web`; the owner creates an epic and a quick task with tags "web, ui";
the epic is signed off through the design gate (the auto-link trigger for an epic). Checks the fleet
tokens.json mtime is unchanged. Writes docs/evidence/s-adv/tags/ (walk-log.txt, *.png).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

V8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V8 / "src"))
sys.path.insert(0, str(V8 / "scripts"))
import adversary_repro as H  # noqa: E402
import qa_walk as Q  # noqa: E402

OUT = V8 / "docs" / "evidence" / "s-adv" / "tags"
FLEET_TOKENS = V8 / "tokens.json"
LOG: list[str] = []
OKS: list[tuple[str, bool]] = []


def log(line: str) -> None:
    LOG.append(line)
    print(line, flush=True)


def check(name: str, ok: bool, facts: str) -> None:
    OKS.append((name, ok))
    log(f"{'PASS' if ok else 'FAIL'} {name}: {facts}")


def ui(base: str, mode: str, args: dict) -> dict:
    p = subprocess.run(["node", str(V8 / "scripts" / "tags_walk.mjs"), base, mode, json.dumps(args), str(OUT)],
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
    fleet_mtime = FLEET_TOKENS.stat().st_mtime if FLEET_TOKENS.exists() else None
    home = Path(tempfile.mkdtemp(prefix="tags-walk-"))
    pool, pool_url = Q.start_pool()
    for k in H._STRIP:
        os.environ.pop(k, None)
    os.environ.update(EDP_POOL_URL=pool_url, EDP8_HOME=str(home), EDP8_TOKENS=str(home / "tokens.json"),
                      EDP8_PAIN_FILE=str(home / "pain-points.jsonl"))
    proc, base = H.start_board(home, pool_url)  # inherits EDP8_TOKENS=<home>/tokens.json
    log(f"private board pid={proc.pid} {base} pool={pool_url} home={home} tokens={home / 'tokens.json'}")
    try:
        http = httpx.Client(base_url=base, timeout=30)

        def call(who: str, method: str, path: str, **kw):
            headers = {"X-Participant": who, **({"X-Admin": H.ADMIN} if who == "admin" else {})}
            r = http.request(method, path, headers=headers, **kw).json()
            assert r["ok"], (path, r)
            return r["value"]

        for pid, role, typ in [("owner", "owner", "human"), ("architect.w", "architect", "agent")]:
            call("admin", "POST", "/v1/participants", json={"id": pid, "handle": pid, "role": role, "type": typ})
        doc = call("owner", "POST", "/v1/docs", json={"doc_type": "domain", "title": "Web craft", "scope": "global",
                                                     "tags": ["web"], "body_md": "- keep the SPA readable"})
        log(f"seeded active domain doc {doc['id']} tags={doc['tags']} status={doc['status']}")

        def links(tid: str) -> list[str]:
            return [lk["to_id"] for lk in call("owner", "GET", "/v1/links", params={"from_id": tid})
                    if lk["relation"] in ("uses_domain", "uses_strategy")]

        def notes(tid: str) -> list[str]:
            return [m["text"] for m in call("owner", "GET", "/v1/messages", params={"ticket_id": tid})
                    if m["created_by"] == "board" and "Library auto-link" in m["text"]]

        # 1) quick task through the SPA dialog — auto-link fires at create
        q = ui(base, "quick-task", {"title": "Tighten the header", "words": "The header wraps on a phone.",
                                    "tags": "web, ui"})
        sid = q.get("story")
        if sid:
            t = call("owner", "GET", f"/v1/tickets/{sid}")
            check("quick-task tags", "web" in t["tags"] and "ui" in t["tags"] and "quick" in t["tags"],
                  f"{sid} tags={t['tags']}")
            check("quick-task auto-link", links(sid) == [doc["id"]] and bool(notes(sid)),
                  f"links={links(sid)} note={notes(sid)[:1]}")
            check("quick-task note visible in the SPA", "Library auto-link at quick task" in (q.get("thread") or ""),
                  f"thread excerpt={(q.get('thread') or '')[:200]!r}")
        else:
            check("quick-task created", False, json.dumps(q)[:300])

        # 2) epic through the SPA dialog; its tags ride the create, auto-link fires at design sign-off
        e = ui(base, "new-epic", {"title": "Readable header", "words": "Make the header readable.", "tags": "web, ui"})
        eid = e.get("epic")
        if eid:
            t = call("owner", "GET", f"/v1/tickets/{eid}")
            check("epic tags", t["tags"][:2] == ["web", "ui"] and any(x.startswith("model:") for x in t["tags"]),
                  f"{eid} tags={t['tags']}")
            design = call("architect.w", "POST", "/v1/docs", json={"doc_type": "design", "title": "d",
                                                                   "scope": eid, "body_md": "# d"})
            # the same steps as tests/test_implicit.py::_signed_off_epic, over REST
            call("architect.w", "POST", "/v1/criteria", json={"ticket_id": eid, "text": "it works",
                                                               "check": "command"})
            call("architect.w", "PATCH", f"/v1/tickets/{eid}", json={"design_ref": design["id"]})
            call("architect.w", "POST", f"/v1/gates/{eid}/design_signoff/open", json={"note": "please"})
            call("owner", "POST", f"/v1/gates/{eid}/design_signoff/answer", json={"answer": "go"})
            log(f"epic {eid} status after sign-off: {call('owner', 'GET', f'/v1/tickets/{eid}')['status']}")
            check("epic auto-link at design sign-off", links(eid) == [doc["id"]] and bool(notes(eid)),
                  f"links={links(eid)} note={notes(eid)[:1]}")
        else:
            check("epic created", False, json.dumps(e)[:300])
    finally:
        proc.kill()
        proc.wait(timeout=30)
        pool.shutdown()
        log(f"stopped private board pid={proc.pid}; pool spawns={len(H.SPAWNS)}")
        after = FLEET_TOKENS.stat().st_mtime if FLEET_TOKENS.exists() else None
        check("fleet tokens.json untouched", after == fleet_mtime, f"mtime before={fleet_mtime} after={after}")
        log("RESULT " + ("PASS" if all(ok for _, ok in OKS) else "FAIL")
            + f" {sum(ok for _, ok in OKS)}/{len(OKS)}")
        (OUT / "walk-log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
        shutil.rmtree(home, ignore_errors=True)
    return 0 if all(ok for _, ok in OKS) else 1


if __name__ == "__main__":
    sys.exit(main())
