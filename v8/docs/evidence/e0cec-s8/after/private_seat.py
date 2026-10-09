"""Boot a private Claude seat through the pool's REAL lean-boot path (S8, c-7460ed15e8) and check what it carries.

`edp_pool.pty_launcher.build_env` + `edp_pool.lean_boot.apply_env/lean_args` build the env and argv exactly as
`SubprocessSpawner.launch` does; the process is a headless `claude -p` in a scratch CLAUDE_CONFIG_DIR (credentials,
plugins and skills copied; the fleet's config, board, pool and transcripts are never touched; the edp8 MCP url is
a dead port so edp8's own tool names are a constant). Two boots per role: EDP_LEAN_BOOT=0 (before) and lean (after).

Checks (exit 1 when one fails): no claude.ai connector booted; the skill listing == the role's skills;
Cron*/Workflow tools absent; a 40k-char Bash result arrives capped; the cap env reached the shell.
Usage: python private_seat.py --out <dir> --scratch <scratch config dir> [--role engineer] [--model claude-sonnet-5-5]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO / "edp-pool/src"))
sys.path.insert(0, str(HERE))
import measure_boot as mb  # noqa: E402
from edp_pool import lean_boot  # noqa: E402
from edp_pool.pty_launcher import build_env  # noqa: E402

BIG = "head -c 25000 /dev/zero | tr '\\0' x"


def seat_cmd(role: str, model: str, lean: bool, scratch: Path, prompt: str) -> tuple[list[str], dict]:
    os.environ["EDP_LEAN_BOOT"] = "1" if lean else "0"
    os.environ["EDP_CLAUDE_CONFIG_DIR"] = str(scratch)
    for k in (*lean_boot.LEAN_ENV, *lean_boot.CAP_ENV):
        os.environ.pop(k, None)
    env = build_env("s8-private", role, f"{role}.s8-private", None, agent_home=str(mb.AGENT_HOME))
    lean_boot.apply_env(env)
    if not lean:      # the BEFORE boot is the pre-S8 env: no caps either
        for k in lean_boot.CAP_ENV:
            env.pop(k, None)
    env["EDP8_MCP_URL"] = "http://127.0.0.1:1"
    for k in [k for k in env if k.startswith("EDP_") and k not in ("EDP_ROLE", "EDP_HANDLE")]:
        env.pop(k)
    args = ["claude", "-p", prompt, "--output-format", "json", "--model", model, "--dangerously-skip-permissions",
            *lean_boot.lean_args(role, None, mb.AGENT_HOME, scratch)]
    if os.name == "nt":
        args = ["cmd", "/c", *args]
    return args, env


def boot(role: str, model: str, lean: bool, scratch: Path, prompt: str, out: Path, tag: str) -> dict:
    args, env = seat_cmd(role, model, lean, scratch, prompt)
    r = subprocess.run(args, cwd=mb.AGENT_HOME, env=env, capture_output=True, text=True, timeout=300)
    res = json.loads(r.stdout)
    u = res.get("usage") or {}
    total = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    row = {"tag": tag, "lean": lean, "first_call_tokens": total, "session_id": res.get("session_id"),
           "settings_flag": [a for a in args if "settings.json" in a], "result": (res.get("result") or "")[:300]}
    row.update(mb.boot_attachments(scratch, res.get("session_id")))
    row["bash_result_chars"] = bash_result_chars(scratch, res.get("session_id"))
    (out / f"{tag}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return row


def bash_result_chars(cfg: Path, sid: str | None) -> list[int]:
    sizes: list[int] = []
    for p in (cfg / "projects").rglob(f"{sid}.jsonl") if sid else []:
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            c = (o.get("message") or {}).get("content")
            for b in c if isinstance(c, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    t = b.get("content")
                    sizes.append(len(t) if isinstance(t, str) else sum(len(x.get("text", "")) for x in t or []))
    return sizes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scratch", type=Path, required=True)
    ap.add_argument("--role", default="engineer")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    mb.prepare_config(a.scratch)
    (a.scratch / "settings.json").write_text(json.dumps(mb.base_settings(), indent=1), encoding="utf-8")
    quick = "Reply with the single word ok."
    capped = f"Run exactly this one Bash command, then reply with the word done: {BIG}"
    probe = a.scratch / "readprobe.txt"      # ~13k tokens: over the 8000-token Read cap, under the 25000 default
    probe.write_text("\n".join(" ".join(f"w{i * 12 + j}" for j in range(12)) for i in range(1400)), encoding="utf-8")
    read = f"Use the Read tool once on {probe} (no offset, no limit), then reply with the word done."
    rows = {t: boot(a.role, a.model, lean, a.scratch, p, a.out, t)
            for t, lean, p in (("before", False, quick), ("after", True, quick),
                               ("after-bash-cap", True, capped), ("before-bash-cap", False, capped),
                               ("after-read-cap", True, read), ("before-read-cap", False, read))}
    b, n = rows["before"], rows["after"]
    want = set(lean_boot.role_skills(a.role, mb.AGENT_HOME)[0]) | {a.role}
    checks = {
        "no claude.ai connector booted": not any("claude.ai" in s for s in n["mcp_servers"])
        and any("claude.ai" in s for s in b["mcp_servers"]),
        "no connector instructions": n["attachment_chars"]["mcp_instructions_delta"] == 0,
        "skill listing is the role's skills": set(n["skills"]) == want,
        "Cron*/Workflow tools not offered": not {"CronCreate", "CronDelete", "CronList", "Workflow"} & set(n["deferred"]),
        "25k Bash result capped (<= 16k chars)": max(rows["after-bash-cap"]["bash_result_chars"] or [0]) <= 16_000,
        "25k Bash result uncapped before (> 20k chars)": max(rows["before-bash-cap"]["bash_result_chars"] or [0]) > 20_000,
        "Read returned in full before (> 25k chars)": max(rows["before-read-cap"]["bash_result_chars"] or [0]) > 25_000,
        "Read capped after (< 12k chars)": max(rows["after-read-cap"]["bash_result_chars"] or [0]) < 12_000,
        "first-call tokens fell": n["first_call_tokens"] < b["first_call_tokens"],
    }
    summary = {"role": a.role, "model": a.model, "before_tokens": b["first_call_tokens"],
               "after_tokens": n["first_call_tokens"], "delta": n["first_call_tokens"] - b["first_call_tokens"],
               "checks": checks, "rows": rows}
    (a.out / "private_seat.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("before_tokens", "after_tokens", "delta", "checks")}, indent=1))
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
