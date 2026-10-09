"""S17 completeness run: codex (model pinned) plans each lab story through the REAL edp8 tools (edpserver.py).
usage: s17run.py <A|B> [story ids...]   env: S17_WT, LAB_ROOT, LAB_DOCS (default pyr), LAB_TAG (default s17)
The prompt is the plan lab's (planrun.py), with the real tool names."""
import json
import os
import pathlib
import subprocess
import sys
import ctypes
import time


class _MS(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def free_mb() -> int:
    m = _MS()
    m.dwLength = ctypes.sizeof(_MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return int(m.ullAvailPhys // (1024 * 1024))


FLOOR_MB = 600  # architect m-7ab6d05e20: stop cleanly below this, before a story and every 10 s during it

HERE = pathlib.Path(__file__).parent
LAB = pathlib.Path(os.environ["LAB_ROOT"])
PY = str(HERE.parents[3] / ".venv" / "Scripts" / "python.exe")  # v8/.venv
CODEX = "C:/nvm4w/nodejs/node_modules/@openai/codex/bin/codex.js"
MODEL = "gpt-6-astra"  # pinned: the fleet's codex seat model (design-f39cf0db7d criterion c-e8ecddefcf)
epic = sys.argv[1]
docs = os.environ.get("LAB_DOCS", "pyr")
want = sys.argv[2:]
STORIES = [s["id"] for s in json.loads((LAB / "plan" / epic / docs / "stories.json").read_text(encoding="utf-8"))]
OUT = HERE / "presults" / f"{os.environ.get('LAB_TAG', 's17')}-codex-real-{epic}-{docs}"
OUT.mkdir(parents=True, exist_ok=True)
WORK = HERE / "work"
WORK.mkdir(exist_ok=True)
SERVER = (HERE / "edpserver.py").as_posix()
TOOLS = ["ticket_read", "doc_read", "find"]
PROMPT = ("You are the engineer about to implement story {sid} of a software project. The story ticket "
          "(ticket_read(ticket_id='{sid}')), its design and the team's process docs are ONLY reachable through the "
          "`lab` MCP tools ({tools}). Do not use any other "
          "tool or file access. Work out every process rule that applies to THIS story (and which ones do not, "
          "because of scope, exceptions, or later amendments/precedence), then write the implementation plan. Use "
          "only what the documents say; never invent rules.\n\n"
          "Reply with ONLY a JSON object:\n"
          '{{"steps": [{{"n": 1, "do": "<concrete step>", "per": "<doc id / section or rule id it follows>"}}, ...],\n'
          ' "must_not": [{{"rule": "<what this story must NOT do, incl. rules that look applicable but are switched off '
          'for it>", "per": "<doc id / section>"}}, ...],\n'
          ' "criteria_checks": [{{"criterion": "<criterion id>", "how": "<how the plan verifies it>"}}, ...],\n'
          ' "complete": <true if you are certain you covered every applicable rule>}}\n'
          "Order `steps` in the order they must happen.")

for sid in (want or STORIES):
    log = OUT / f"{sid}.calls.jsonl"
    log.unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP", "HERONRY"))}
    env.update({"PYTHONPATH": "", "CODEX_HOME": str(LAB / "codexhome")})
    senv = {"S17_WT": os.environ["S17_WT"], "LAB_ROOT": LAB.as_posix(), "LAB_EPIC": epic, "LAB_DOCS": docs,
            "LAB_LOG": log.as_posix()}
    e = ", ".join(f'{k}="{v}"' for k, v in senv.items())
    srv = f'mcp_servers.lab={{command="{PY}", args=["{SERVER}"], env={{{e}}}}}'
    cmd = ["node", CODEX, "exec", "-m", MODEL, "--skip-git-repo-check", "--ephemeral", "--json",
           "-s", "read-only", "-c", srv, "-c", "mcp_servers.lab.startup_timeout_sec=120",
           "-c", 'mcp_servers.lab.default_tools_approval_mode="approve"',
           "-o", str(OUT / f"{sid}.last.txt"), PROMPT.format(sid=sid, tools=", ".join(TOOLS))]
    t0 = time.time()
    lo = hi = free_mb()
    if lo < FLOOR_MB:
        print(json.dumps({"s": sid, "stopped": "memory", "free_mb": lo, "before": True}), flush=True)
        sys.exit(3)
    so_f, se_f = OUT / f"{sid}.stdout.txt", OUT / f"{sid}.stderr.txt"
    with open(so_f, "w", encoding="utf-8") as fo, open(se_f, "w", encoding="utf-8") as fe:
        p = subprocess.Popen(cmd, cwd=WORK, env=env, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL, text=True,
                             encoding="utf-8", errors="replace")
        rc = None
        while rc is None:
            try:
                rc = p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                f = free_mb()
                lo, hi = min(lo, f), max(hi, f)
                if f < FLOOR_MB or time.time() - t0 > 1500:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
                    p.wait()
                    rc = "memory" if f < FLOOR_MB else "timeout"
    so = so_f.read_text(encoding="utf-8")
    calls = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    print(json.dumps({"s": sid, "rc": rc, "secs": round(time.time() - t0), "calls": len(calls),
                      "chars_read": sum(c["chars"] for c in calls), "free_mb_min": lo, "free_mb_peak": hi,
                      "by_tool": {t: sum(c["chars"] for c in calls if c["tool"] == t) for t in TOOLS}}), flush=True)
    if rc == "memory":
        sys.exit(3)
