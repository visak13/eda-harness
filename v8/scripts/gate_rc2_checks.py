"""RC2 upgrade gate (c-300f4365a2, t-e338298d88): the API checks on a PRIVATE sandbox home after an upgrade.

    python gate_rc2_checks.py <EDP_HOME> <owner-home-copy-source-kind> [--out <dir>]

Run by gate_rc2_upgrade.ps1 with the sandbox's environment (EDP_HOME, private ports). Reads only the sandbox home's
own files; prints one PASS/FAIL line per check and writes checks.json. Never prints a token: the owner token and the
admin token are read from the sandbox's secrets and only ever sent as headers to the sandbox's loopback board.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path(sys.argv[1])
KIND = sys.argv[2] if len(sys.argv) > 2 else "hop"
OUT = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else HOME / "gate"
OUT.mkdir(parents=True, exist_ok=True)
BOARD = f"http://127.0.0.1:{os.environ['EDP8_PORT']}"
POOL = f"http://127.0.0.1:{os.environ['EDP_POOL_PORT']}"
EFFORT_LOG = Path(os.environ.get("GATE_EFFORT_LOG", HOME / "gate" / "seat-env.jsonl"))
results: list[dict] = []


def check(ok: bool, what: str, **facts) -> bool:
    results.append({"ok": bool(ok), "check": what, **facts})
    print(f"{'PASS' if ok else 'FAIL'}  {what}" + (f"  {json.dumps(facts, default=str)}" if facts else ""), flush=True)
    return bool(ok)


def owner_headers() -> dict[str, str]:
    tokens = json.loads((HOME / "tokens.json").read_text(encoding="utf-8"))
    return {"X-Participant": "owner", "X-Token": tokens["owner"]}


def call(method: str, url: str, body: dict | None = None, headers: dict | None = None, timeout: float = 30) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": str(e)}


def value(j: dict):
    return j.get("value", j) if isinstance(j, dict) else j


OWN = owner_headers()

if "--spawn-codex" in sys.argv:
    # hop2 (architect m-0b95d8413e): one live codex seat through the update. A synthetic epic whose adversary (a
    # codex role) is spawned; the stub codex keeps the seat's `heronry.exe -m edp8.codex_seat.run` up.
    tag = f"rc2gate-codex-{int(time.time())}"
    st, e = call("POST", f"{BOARD}/v1/tickets", {"kind": "epic", "work_type": "feature",
                                                "title": f"RC2 gate synthetic codex epic {tag}"}, OWN)
    epic = (value(e) or {}).get("id")
    st, sp = call("POST", f"{BOARD}/v1/sessions/spawn", {"role": "adversary", "participant_id": f"adversary.{epic}",
                                                         "ticket_id": epic, "mode": "headless"}, OWN, timeout=120)
    choice = (value(sp) or {}).get("seat_choice") if isinstance(value(sp), dict) else None
    check(bool(epic) and st == 200, "a codex seat (the synthetic epic's adversary) is spawned before the update",
          epic=epic, status=st, seat_choice=choice, refused=None if st == 200 else sp)
    (OUT / f"checks-{KIND}.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    sys.exit(0 if all(r["ok"] for r in results) else 1)

if "--spawn-claude-monitor" in sys.argv:
    # hop3rm (architect m-6f9232f522): one seat that outlives `stop --force` as the owner's Claude windows do. A
    # synthetic story's engineer (a Claude role) in monitor mode: the pool opens it in its own visible console, in no
    # job, so only the update's own end of parked shells can stop it. The stub harness waits on that console's input.
    tag = f"rc2gate-claude-{int(time.time())}"
    st, e = call("POST", f"{BOARD}/v1/tickets", {"kind": "epic", "work_type": "feature",
                                                "title": f"RC2 gate synthetic claude epic {tag}"}, OWN)
    epic = (value(e) or {}).get("id")
    st, s = call("POST", f"{BOARD}/v1/tickets", {"kind": "story", "work_type": "chore", "parent_id": epic,
                                                "title": f"RC2 gate synthetic claude story {tag}"}, OWN)
    story = (value(s) or {}).get("id")
    st, sp = call("POST", f"{BOARD}/v1/sessions/spawn", {"role": "engineer", "participant_id": f"engineer.{story}",
                                                         "ticket_id": story, "mode": "monitor"}, OWN, timeout=120)
    choice = (value(sp) or {}).get("seat_choice") if isinstance(value(sp), dict) else None
    check(bool(story) and st == 200, "a Claude seat (a synthetic story's engineer) is spawned in monitor mode before the update",
          story=story, status=st, seat_choice=choice, refused=None if st == 200 else sp)
    (OUT / f"checks-{KIND}.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    sys.exit(0 if all(r["ok"] for r in results) else 1)

if "--resume" in sys.argv:
    # manual010 (t-fd7cf3a6b5): the owner's last manual step, a seat closed before the MSI resumed from the board, as
    # the UI's Resume does (POST /v1/sessions/resume with the owner's headers)
    handle = sys.argv[sys.argv.index("--resume") + 1]
    st, r = call("POST", f"{BOARD}/v1/sessions/resume", {"participant_id": handle, "ticket_id": handle.split(".", 1)[1]},
                 OWN, timeout=120)
    v = value(r) if isinstance(value(r), dict) else {}
    check(st == 200 and r.get("ok", True) is not False and bool(v.get("resumed") or v.get("no_op")),
          "the closed seat resumes from the board after the manual install", handle=handle, status=st,
          resumed=v.get("resumed"), no_op=v.get("no_op"), refused=None if st == 200 else r)
    (OUT / f"checks-{KIND}.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    sys.exit(0 if all(r["ok"] for r in results) else 1)

# 1. every service answers
st, h = call("GET", f"{BOARD}/v1/health")
check(st == 200, "board answers /v1/health", version=value(h).get("version") if isinstance(value(h), dict) else h)
st, _ = call("GET", f"{POOL}/v1/health")
check(st == 200, "pool answers /v1/health")
st, _ = call("GET", f"http://127.0.0.1:{os.environ['EDP_BROKER_PORT']}/v1/health")
check(st == 200, "broker answers /v1/health")
st, _ = call("GET", f"http://127.0.0.1:{os.environ['EDP8_MCP_PORT']}/v1/health")
check(st in (200, 404, 405), "mcp port answers", status=st)

# 2. New epic offers high effort for Claude (item 1: the catalog's caps merged into the owner's catalog)
st, m = call("GET", f"{BOARD}/v1/models", headers=OWN)
models = (value(m) or {}).get("models") or {}
caps = {k: (v or {}).get("effort_cap") for k, v in models.items() if k.startswith("claude-")}
check(caps.get("claude-opus-5-5") == "high" and caps.get("claude-fable-5-1") == "high",
      "catalog: claude-opus-5-5 and claude-fable-5-1 are capped at high (New epic offers high)", caps=caps)

# 3. a story's opus@high pick on a Sonnet-only epic reaches the spawned seat's env (item 7)
sonnet = next((k for k in models if k.startswith("claude-sonnet")), "claude-sonnet-5")
tag = f"rc2gate-{int(time.time())}"
st, e = call("POST", f"{BOARD}/v1/tickets", {"kind": "epic", "work_type": "feature", "title": f"RC2 gate synthetic epic {tag}",
                                            "tags": [f"model:engineer={sonnet}"]}, OWN)
epic = (value(e) or {}).get("id")
st2, s = call("POST", f"{BOARD}/v1/tickets", {"kind": "story", "work_type": "chore", "title": f"RC2 gate synthetic story {tag}",
                                             "parent_id": epic, "tags": ["seat:engineer=claude-opus-5-5@high"]}, OWN)
story = (value(s) or {}).get("id")
check(bool(epic) and bool(story), "a synthetic Sonnet-only epic and a story picking claude-opus-5-5@high",
      epic=epic, story=story, refused=None if story else s)
if story:
    EFFORT_LOG.unlink(missing_ok=True)
    st, sp = call("POST", f"{BOARD}/v1/sessions/spawn", {"role": "engineer", "participant_id": f"engineer.{story}",
                                                         "ticket_id": story, "mode": "headless"}, OWN, timeout=120)
    choice = (value(sp) or {}).get("seat_choice") if isinstance(value(sp), dict) else None
    check(st == 200 and (choice or {}).get("model") == "claude-opus-5-5" and (choice or {}).get("effort") == "high",
          "the board resolves the story pick to claude-opus-5-5@high", status=st, seat_choice=choice)
    seen = None
    for _ in range(60):
        if EFFORT_LOG.is_file() and EFFORT_LOG.read_text(encoding="utf-8").strip():
            seen = [json.loads(x) for x in EFFORT_LOG.read_text(encoding="utf-8").splitlines() if x.strip()][-1]
            break
        time.sleep(1)
    check(bool(seen) and seen.get("EDP_SEAT_EFFORT") == "high" and "claude-opus-5-5" in " ".join(seen.get("argv") or []),
          "the spawned seat's env carries EDP_SEAT_EFFORT=high and its argv the opus model", seat=seen)

# 4. the Code tab: code-server runs although PATH holds a broken one and config.toml has no [code_server] path
cfg = (HOME / "config.toml").read_text(encoding="utf-8")
pin = next((ln for ln in (cfg.split("[code_server]", 1) + [""])[1].split("\n[", 1)[0].splitlines()
            if ln.strip().startswith("path")), None)
if KIND == "hop2":  # the owner's current config still carries the hand pin (backup config.toml.bak-code): recorded
    check(True, "the owner's [code_server] path pin, the line to remove after the restart", line=pin)
else:
    check(pin is None, "config.toml has no [code_server] path pin")
st, c = call("GET", f"{BOARD}/v1/code", headers=OWN)
cv = value(c) or {}
check(st == 200 and bool(cv.get("running") or cv.get("state") == "running"), "the Code tab's code-server is running",
      status={k: cv.get(k) for k in ("state", "running", "version", "source", "path") if k in cv})
st, sess = call("POST", f"{BOARD}/v1/code/session", {}, OWN)
check(st == 200 and bool((value(sess) or {}).get("expires_at")), "the owner can open a Code session (token minted)",
      status=st)

# 4b. the live F5 check: the guard login is one POSTed form; a GET is refused, the minted token logs in once (the
# cookie opens the workbench) and a replay is refused. The token is only ever sent in a POST body, never printed.
CODE = f"http://127.0.0.1:{os.environ['EDP_CODE_PORT']}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def guard(method: str, path: str, form: str | None = None, cookie: str | None = None) -> tuple[int, dict]:
    hdr = {"Origin": CODE}
    if form is not None:
        hdr["Content-Type"] = "application/x-www-form-urlencoded"
    if cookie:
        hdr["Cookie"] = cookie
    req = urllib.request.Request(CODE + path, data=form.encode() if form is not None else None, method=method, headers=hdr)
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=30) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)
    except (urllib.error.URLError, OSError):
        return 0, {}


tok = (value(sess) or {}).get("token") or ""
g_get, _ = guard("GET", "/__edp/login?t=x&next=%2F")
g_post, h = guard("POST", "/__edp/login", form=f"t={tok}&next=%2F")
cookie = (h.get("Set-Cookie") or "").split(";", 1)[0]
g_replay, _ = guard("POST", "/__edp/login", form=f"t={tok}&next=%2F")
g_bench, hb = guard("GET", "/", cookie=cookie)
if g_bench == 302 and "login" not in (hb.get("Location") or ""):  # code-server's own redirect to its default folder
    g_bench, _ = guard("GET", "/" + (hb.get("Location") or "").lstrip("./"), cookie=cookie)
g_nocookie, _ = guard("GET", "/")
check(g_get == 405 and g_post == 302 and bool(cookie) and g_replay == 401 and g_bench == 200 and g_nocookie == 401,
      "live F5: login GET refused 405, POSTed token logs in once (302 + cookie), replay 401, cookie opens the workbench",
      get=g_get, post=g_post, cookie_set=bool(cookie), replay=g_replay, workbench=g_bench, without_cookie=g_nocookie)

# 5. pool settings merged (item 5)
pool_cfg = HOME / ".data" / "claude-pool" / "settings.json"
try:
    sj = json.loads(pool_cfg.read_text(encoding="utf-8-sig"))
except (OSError, ValueError) as ex:
    sj = {"_error": str(ex)}
hooks = json.dumps(sj.get("hooks", {}).get("SessionStart", []))
check("effortLevel" not in sj and "compact" in hooks,
      "pool settings.json: the retired effortLevel pin is gone and the compact SessionStart hook is present",
      keys=sorted(sj)[:20])

# 6. every <file>.new the refresh left
news = sorted(str(p.relative_to(HOME)) for p in HOME.rglob("*.new"))
check(True, "the .new files refresh left (each is explained in the report)", files=news)

# 7. hop2 (architect m-b7abaedb27): after the update no card or skill under the agent home's .claude names a tool the
# installed 0.10.1 lacks (assemble_ruleset was the live case), and no refresh kept an old file with a .new beside it
if KIND == "hop2":
    from gate_agent_home import load_registry, scan
    reg_after, reg_before = OUT / "hop2-tools-0.10.1.json", OUT / "hop2-tools-0.10.0.json"
    try:
        after = load_registry(reg_after)
        if not after:
            raise ValueError(f"{reg_after.name} lists no tools")
    except (OSError, ValueError) as ex:
        after = None
        check(False, "the installed 0.10.1 tool registry was read (heronry.exe -c)", error=str(ex))
    if after is not None:
        before = load_registry(reg_before) if reg_before.is_file() else set()
        found = scan(HOME / "agent-home" / ".claude", after, before - after)
        check(not found["unknown"] and not found["removed"],
              "no file under the agent home's .claude names a tool missing from the 0.10.1 registry",
              tools=len(after), dropped_by_update=sorted(before - after), unknown=found["unknown"], removed=found["removed"])
        check(not found["new_files"], "the refresh kept no card or skill with a .new beside it", new_files=found["new_files"])

(OUT / f"checks-{KIND}.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
sys.exit(0 if all(r["ok"] for r in results) else 1)
