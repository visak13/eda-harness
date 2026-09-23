"""S-SME-SURFACE (s-698224fca8) live walk on a PRIVATE board with a fake pool and a fake expert.

    .venv/Scripts/python.exe scripts/topic_walk.py before   # the Library as it was (screenshot only)
    .venv/Scripts/python.exe scripts/topic_walk.py live     # the whole topic walk + after screenshots

Reuses scripts/adversary_repro.py's harness: the venv edp8-board.exe on a free loopback port, a temp
EDP8_HOME, embedder none, the fleet env stripped, and an in-process FakePool that records every spawn
(so the resident sme's minted EDP8_TOKEN is captured exactly as a real seat would receive it). The
private board's tokens.json lives in the temp home and EDP8_TOKENS points at it; the fleet
v8/tokens.json is never read or written (its mtime is checked before and after). The sme is driven
through the same MCP tool handlers a seat calls (bundles.ALL_TOOLS) with its own token; the expert is a
human with the token the owner minted for it. topic_research fetches a REAL skills.sh page.
Writes docs/evidence/s-sme-surface/ (walk-log.txt, *.png).
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

OUT = V8 / "docs" / "evidence" / "s-sme-surface"
OWNER_SECRET = "walk-owner-secret"
SKILL_PAGE = "https://skills.sh/wshobson/agents/python-testing-patterns"
LOG: list[str] = []
RESULTS: dict[str, tuple[bool, str]] = {}


def log(line: str) -> None:
    LOG.append(line)
    print(line, flush=True)


def result(name: str, ok: bool, facts: str) -> None:
    RESULTS[name] = (ok, facts)
    log(f"{'PASS' if ok else 'FAIL'} {name}: {facts}")


def start_pool() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H.FakePool)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def shots(*args: str) -> None:
    p = subprocess.run(["node", str(V8 / "scripts" / "topic_walk.mjs"), *args], cwd=str(V8), env={**os.environ, "WALK_OWNER_TOKEN": OWNER_SECRET},
                       capture_output=True, text=True, encoding="utf-8", timeout=240)
    for ln in (p.stdout + p.stderr).strip().splitlines():
        log(f"  ui: {ln}")
    if p.returncode:
        raise SystemExit(f"topic_walk.mjs {args[0]} failed ({p.returncode})")


def feed_frames(base: str, headers: dict, since: int, seconds: float = 3.0) -> list[dict]:
    """The participant's wake feed from `since` (SSE /v1/feed), read for a few seconds — what the seat's
    Monitor line (feed_driver) is built from."""
    frames: list[dict] = []
    deadline = time.monotonic() + seconds
    try:
        with httpx.stream("GET", f"{base}/v1/feed", params={"since": since}, headers=headers, timeout=seconds + 2) as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    frames.append(json.loads(line[6:]))
                if time.monotonic() > deadline:
                    break
    except httpx.HTTPError:
        pass
    return frames


def main(mode: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    fleet = V8 / "tokens.json"
    fleet_mtime = fleet.stat().st_mtime if fleet.exists() else None
    home = Path(tempfile.mkdtemp(prefix="topic-walk-"))
    tokens = home / "tokens.json"
    tokens.write_text(json.dumps({"owner": OWNER_SECRET, "agents": {}}), encoding="utf-8")
    pool, pool_url = start_pool()
    for k in H._STRIP:
        os.environ.pop(k, None)
    os.environ.update(EDP_POOL_URL=pool_url, EDP8_HOME=str(home), EDP8_TOKENS=str(tokens),
                      EDP8_PAIN_FILE=str(home / "pain-points.jsonl"))
    proc, base = H.start_board(home, pool_url)
    log(f"private board pid={proc.pid} {base} pool={pool_url} home={home} (tokens {tokens})")
    owner = {"X-Participant": "owner", "X-Token": OWNER_SECRET}
    http = httpx.Client(base_url=base, timeout=60)

    def call(headers: dict, method: str, path: str, **kw):
        r = http.request(method, path, headers=headers, **kw)
        body = r.json()
        return r.status_code, body

    try:
        http.post("/v1/participants", headers={"X-Admin": H.ADMIN},
                  json={"id": "owner", "handle": "owner", "role": "owner", "type": "human"})
        if mode == "before":
            for title, tags in (("craft: python testing", ["python"]), ("domain: payments", ["payments"])):
                call(owner, "POST", "/v1/docs", json={"doc_type": "strategy_hl", "title": title, "scope": "global",
                                                      "tags": tags, "body_md": "## Enforced\n- a bar [required]\n"})
            shots("before", base, str(OUT))
            return 0
        run_live(base, owner, call)
    finally:
        proc.kill()
        proc.wait(timeout=30)
        pool.shutdown()
        log(f"stopped private board pid={proc.pid}; pool spawns={[s.get('handle') for s in H.SPAWNS]}")
        after = fleet.stat().st_mtime if fleet.exists() else None
        result("fleet tokens.json untouched", after == fleet_mtime, f"mtime before={fleet_mtime} after={after}")
        if mode == "live":
            log("")
            for c, (ok, facts) in RESULTS.items():
                log(f"RESULT {c} {'PASS' if ok else 'FAIL'} — {facts}")
            (OUT / "walk-log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
        shutil.rmtree(home, ignore_errors=True)
    return 0 if all(v[0] for v in RESULTS.values()) else 1


def run_live(base: str, owner: dict, call) -> None:
    from edp8.bundles import ALL_TOOLS, set_client
    from edp8.client import BoardClient

    # 1. the owner opens a topic from the Library (title, tags, seed URL)
    st, r = call(owner, "POST", "/v1/topics", json={"title": "Python testing", "tags": ["python"],
                                                    "seed_url": "https://docs.pytest.org/en/stable/"})
    t = r["value"]["topic"]
    tid, seat = t["id"], f"sme.{t['id']}"
    result("owner opens a topic", st == 200 and t["kind"] == "topic" and t["parent_id"] is None,
           f"{tid} kind={t['kind']} parent={t['parent_id']} assignee={t['assignee']} seat={r['value']['seat']}")
    # 2. the resident seat is spawned through the pool with its own minted token (pool-watch tick)
    for _ in range(60):
        spawned = [s for s in H.SPAWNS if s.get("handle") == seat]
        if spawned:
            break
        time.sleep(1)
    env = (spawned[0].get("env") or {}) if spawned else {}
    sme_token = env.get("EDP8_TOKEN")
    result("resident sme spawned via the pool", bool(spawned and sme_token),
           f"pool got role={spawned[0].get('role') if spawned else None} handle={seat} token={'yes' if sme_token else 'no'}")
    sme = {"X-Participant": seat, "X-Token": sme_token or ""}
    set_client(BoardClient(base_url=base, participant=seat, token=sme_token))

    def tool(name: str, **kw):
        d = ALL_TOOLS[name]
        return d.handler(d.args_model(**kw))

    # 3. the sme researches on its own: skills.sh search, then a REAL skill page, then files a proposal
    s = tool("topic_research", topic_id=tid, query="python testing")
    hits = (s.get("value") or {}).get("results") or []
    result("sme searches skills.sh", bool(s.get("ok") and hits),
           f"receipt={(s.get('value') or {}).get('receipt', {}).get('url')} top={[h['id'] for h in hits[:3]]}")
    p = tool("topic_research", topic_id=tid, url=SKILL_PAGE)
    pv = p.get("value") or {}
    rec = pv.get("receipt") or {}
    result("sme reads a real skills.sh page", bool(p.get("ok") and rec.get("status") == 200 and pv.get("text")),
           f"url={rec.get('url')} status={rec.get('status')} bytes={rec.get('bytes')} fetched_at={rec.get('fetched_at')} "
           f"text[:120]={pv.get('text', '')[:120]!r}")
    body = ("Distilled for this topic from the skills.sh skill page.\n\n## Enforced\n"
            "- [required] a test reads Arrange, Act, Assert — one behaviour per test\n"
            "- [expected] shared setup lives in pytest fixtures (conftest.py), not in helpers\n"
            "- [preferred] parameterize instead of copy-pasted cases\n")
    d = tool("topic_propose", topic_id=tid, title="Python testing: AAA, fixtures, parametrize", body_md=body,
             source_url=SKILL_PAGE, tags=["pytest"])
    doc = (d.get("value") or {}).get("doc") or {}
    head = (doc.get("body_md") or "").splitlines()[:1]
    result("sme files a proposed doc with source + fetched-at", bool(d.get("ok") and doc.get("status") == "proposed"),
           f"{doc.get('id')} status={doc.get('status')} header={head}")
    st_act, act = call(sme, "POST", "/v1/docs", json={"doc_type": "strategy_hl", "title": "x", "body_md": "y",
                                                      "scope": "global"})
    result("sme cannot activate a doc", not act.get("ok"), f"doc_create active → {act.get('error', {}).get('message')}")
    # 4. the sme sets the topic's tags; the owner then edits the same list
    tu = tool("ticket_update", ticket_id=tid, tags=["python", "pytest", "testing"])
    _, pg = call(owner, "GET", f"/v1/topics/{tid}")
    result("sme sets tags", bool(tu.get("ok")) and pg["value"]["tags_set_by"]["by"] == seat,
           f"tags={pg['value']['topic']['tags']} set_by={pg['value']['tags_set_by']}")
    # 5. the owner adds a named human expert; the token comes back once
    st, ex = call(owner, "POST", f"/v1/topics/{tid}/experts", json={"handle": "dana", "name": "Dana (QA lead)"})
    xv = ex["value"]
    expert = {"X-Participant": "dana", "X-Token": xv["token"]}
    _, pg = call(owner, "GET", f"/v1/topics/{tid}")
    result("owner adds an expert", st == 200 and xv["expert"]["role"] == "expert" and xv["expert"]["type"] == "human"
           and xv["token"] not in json.dumps(pg), f"expert={xv['expert']['id']} listed={[e['handle'] for e in pg['value']['experts']]} "
           f"link={xv['link'].split('token=')[0]}token=<redacted>")
    # 6. the expert posts on the thread; the sme is woken (its feed), answers, and proposes a new version
    since = 0  # replay the seat's whole wake feed; the frame for this message id is the proof
    st, m = call(expert, "POST", f"/v1/topics/{tid}/messages",
                 json={"text": "From our suite: we also forbid sleep() in tests — use freezegun or an injected clock.",
                       "kind": "note"})
    frames = [f for f in feed_frames(base, sme, since) if f.get("kind") == "message_sent"]
    woke = [f for f in frames if (f.get("data") or {}).get("message") == m["value"]["id"]]
    result("sme wakes on the expert's message", bool(woke),
           f"feed frame kind=message_sent why={woke[0].get('why') if woke else None} from={woke[0]['data'].get('from') if woke else None}")
    a = tool("message_send", ticket_id=tid, kind="answer", reply_to=m["value"]["id"],
             text="Agreed — the skills.sh page covers time control with freezegun too. I am proposing it as a "
                  "[required] bar in a new version of the topic doc.")
    p2 = tool("topic_propose", topic_id=tid, title="Python testing: AAA, fixtures, parametrize, no sleep",
              body_md=body + "- [required] no time.sleep() in tests: freezegun or an injected clock (expert @dana)\n",
              source_url=SKILL_PAGE, proposes=doc.get("id"))
    # the first proposal must be active for a next-version proposal; if it is still proposed, the board says so
    if not p2.get("ok"):
        call(owner, "POST", f"/v1/docs/{doc.get('id')}/approve")
        p2 = tool("topic_propose", topic_id=tid, title="Python testing: AAA, fixtures, parametrize, no sleep",
                  body_md=body + "- [required] no time.sleep() in tests: freezegun or an injected clock (expert @dana)\n",
                  source_url=SKILL_PAGE, proposes=doc.get("id"))
    d2 = (p2.get("value") or {}).get("doc") or {}
    result("sme answers on the thread and updates the docs as a proposed version",
           bool(a.get("ok") and p2.get("ok") and d2.get("proposes") == doc.get("id") and d2.get("status") == "proposed"),
           f"answer={a.get('value', {}).get('id')} proposal={d2.get('id')} proposes={d2.get('proposes')} "
           f"(owner approved {doc.get('id')} first: {doc.get('id')} is the active doc)")
    # 7. the owner posts too; the sme wakes on it
    since = 0  # replay the seat's whole wake feed; the frame for this message id is the proof
    _, om = call(owner, "POST", f"/v1/topics/{tid}/messages", json={"text": "Thanks both — keep it short.", "kind": "note"})
    frames = [f for f in feed_frames(base, sme, since) if (f.get("data") or {}).get("message") == om["value"]["id"]]
    result("sme wakes on the owner's message", bool(frames), f"why={frames[0].get('why') if frames else None}")
    # 8. the expert's reach: its topic only
    refused = {path: call(expert, "GET", path)[0] for path in ("/v1/whoami", "/v1/knowledge", "/v1/tickets", "/v1/topics")}
    st_doc, _ = call(expert, "GET", f"/v1/topics/{tid}/docs/{doc.get('id')}")
    result("expert reaches only its topic", all(v == 403 for v in refused.values()) and st_doc == 200,
           f"refused={refused} own topic doc={st_doc}")
    # 9. screenshots: Library topics list, Open topic dialog, topic page, owner tag edit, expert view
    shots("after", base, str(OUT), tid, xv["link"])
    _, pg = call(owner, "GET", f"/v1/topics/{tid}")
    result("owner edits the sme's tags (last write wins, shown with who)", pg["value"]["tags_set_by"]["by"] == "owner"
           and "owner-picked" in pg["value"]["topic"]["tags"], f"tags={pg['value']['topic']['tags']} set_by={pg['value']['tags_set_by']}")
    # 10. the owner removes the expert, then closes the topic; the seat is released
    st_rm, _ = call(owner, "DELETE", f"/v1/topics/{tid}/experts/dana")
    st_after, _ = call(expert, "GET", f"/v1/topics/{tid}")
    st_close, cl = call(owner, "POST", f"/v1/topics/{tid}/close")
    result("owner removes the expert and closes the topic", st_rm == 200 and st_after == 401 and cl["value"]["status"] == "done",
           f"remove={st_rm} expert after={st_after} topic status={cl['value']['status']}")
    log(f"thread: {[(x['from']['id'], x['kind'], x['text'][:60]) for x in pg['value']['thread']]}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "live"))
