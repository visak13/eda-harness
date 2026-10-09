"""Judge plans against key.json. usage: planjudge.py <claude|codex> <presults subdir>...
Writes <sid>.judge-<judge>.json beside each plan; prints per-story scores. Every FAIL is re-checked by hand."""
import json, os, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).parent
LAB = pathlib.Path(os.environ['LAB_ROOT'])
CLAUDE = "C:/nvm4w/nodejs/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
CODEX = "C:/nvm4w/nodejs/node_modules/@openai/codex/bin/codex.js"
KEY = {}
for _k in (LAB / "plan").glob("*/orig/key.json"):
    KEY.update(json.loads(_k.read_text(encoding="utf-8")))
judge = sys.argv[1]

J = """You are a strict grader. Below is an ANSWER KEY for software story {sid} and an engineer's PLAN.
Grade every key item. Be literal about meaning, lenient about wording: an item counts as present if the plan
clearly requires that same action/constraint (in steps, must_not or criteria_checks), even if phrased differently
or merged with another step. It is ABSENT if missing, vaguer in a way that loses the specific requirement
(e.g. key says "within 24 hours", plan says "promptly"), or contradicted.
- must[i]: "present" | "absent"
- must_not[i]: "ok" if the plan does NOT do/require it (stating it as a must-not is ok), "violated" if any step does
  or requires it.
- order[i]: "kept" if the plan's step order puts `before` ahead of `after`, "broken" if reversed, "missing" if
  either step is absent.
Then list "extras": plan requirements that NO key item supports and that look like a rule the plan invented or
took from a non-applicable/superseded source (ignore generic glue like "open a PR", "write code").
Reply with ONLY JSON:
{{"must": {{"<id>": {{"v": "present|absent", "why": "<plan quote or what is missing>"}}}},
 "must_not": {{"<id>": {{"v": "ok|violated", "why": "..."}}}},
 "order": {{"<id>": {{"v": "kept|broken|missing", "why": "..."}}}},
 "extras": ["<plan text>", ...]}}

ANSWER KEY:
{key}

PLAN:
{plan}
"""


def plan_text(d, sid):
    last = d / f"{sid}.last.txt"
    if last.exists():
        return last.read_text(encoding="utf-8")
    out = (d / f"{sid}.stdout.txt").read_text(encoding="utf-8")
    try:
        return json.loads(out)["result"]
    except Exception:
        return out


def ask(prompt):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP", "HERONRY"))}
    env["CODEX_HOME"] = str(LAB / "codexhome")
    if judge == "claude":
        cmd = [CLAUDE, "-p", "--model", "claude-opus-5-5", "--tools", "", "--strict-mcp-config", "--output-format", "json",
               "--no-session-persistence"]
    else:
        out = ROOT / "work" / "judge.last.txt"
        cmd = ["node", CODEX, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-o", str(out), "-"]
    p = subprocess.run(cmd, cwd=ROOT / "work", env=env, input=prompt, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    txt = json.loads(p.stdout)["result"] if judge == "claude" else (ROOT / "work" / "judge.last.txt").read_text(encoding="utf-8")
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m[0])


for sub in sys.argv[2:]:
    d = ROOT / "presults" / sub
    for sid in KEY:
        if not (d / f"{sid}.stdout.txt").exists():
            continue
        f = d / f"{sid}.judge-{judge}.json"
        try:
            assert '"complete"' in plan_text(d, sid)[-400:], "truncated"
        except Exception:
            print(f"{sub:28} {sid} INVALID (plan output not parseable: harness truncation) — rerun", flush=True)
            continue
        if not f.exists():
            k = KEY[sid]
            f.write_text(json.dumps(ask(J.format(sid=sid, key=json.dumps(k, indent=1), plan=plan_text(d, sid))),
                                    indent=1), encoding="utf-8")
        g = json.loads(f.read_text(encoding="utf-8"))
        miss = [i for i, x in g["must"].items() if x["v"] != "present"]
        viol = [i for i, x in g["must_not"].items() if x["v"] != "ok"]
        ordb = [i for i, x in g.get("order", {}).items() if x["v"] != "kept"]
        k = KEY[sid]
        ok = not (miss or viol or ordb)
        print(f"{sub:28} {sid} {'PASS' if ok else 'FAIL'} must {len(k['must'])-len(miss)}/{len(k['must'])} "
              f"not {len(k['must_not'])-len(viol)}/{len(k['must_not'])} order {len(k['order'])-len(ordb)}/{len(k['order'])} "
              f"extras {len(g.get('extras', []))} | miss {miss} viol {viol} ord {ordb}", flush=True)
