"""Measure what each lean-boot knob does to a Claude seat's first-call input tokens (S8, c-7460ed15e8).

A *private seat* here is a headless `claude -p` run with the pool's real settings template, the agent home as cwd
and a scratch CLAUDE_CONFIG_DIR (credentials + plugins copied; the fleet's config dir, board, pool and transcripts
are never touched). The edp8 MCP url points at a dead port, so edp8's own tool names are absent from every arm
(a constant, identical in all arms). First-call tokens = input + cache write + cache read of the single API call.

Usage: python measure_boot.py --out <dir> [--role engineer] [--reps 2] [--arms a,b,c] [--model claude-sonnet-5-5]
Writes <out>/arms.json (per-arm tokens, attachment chars, listed skills/deferred names/connectors).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

POOL_CFG = Path.home() / "AppData/Local/heronry/data/claude-pool"
AGENT_HOME = Path.home() / "AppData/Local/heronry/data/agent-home"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]          # v8/docs/evidence/e0cec-s8/after -> repo root of the worktree
TEMPLATE = REPO / "edp-pool/src/edp_pool/claude_pool_template/settings.json"
sys.path.insert(0, str(REPO / "edp-pool/src"))

# What a role keeps on its skill listing: the skills its card names, plus its own card (user-invocable).
ROLE_SKILLS = {
    "engineer": ["ticket", "methodology", "demo", "verify", "deviation", "doubt", "learn", "pain", "handoff"],
}
ROLE_CARDS = ["adversary", "architect", "doctor", "engineer", "engineer-quick", "qa", "sme"]

# Deferred tools no seat uses (S8 design; the heartbeat moved to the feed driver, so Cron* goes too).
UNUSED_TOOLS = ["Workflow", "CronCreate", "CronDelete", "CronList", "EnterWorktree", "ExitWorktree", "DesignSync",
                "RemoteTrigger", "PushNotification", "NotebookEdit", "EndConversation", "EnterPlanMode",
                "ExitPlanMode", "ArtifactComments", "ArtifactData"]


def prepare_config(dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for name in (".credentials.json", ".claude.json"):
        shutil.copy2(POOL_CFG / name, dst / name)
    for d in ("plugins", "skills"):   # marketplaces/ (a 13 MB plugin catalogue) is skipped: paths exceed MAX_PATH
        if (POOL_CFG / d).is_dir() and not (dst / d).exists():
            shutil.copytree(POOL_CFG / d, dst / d, ignore=shutil.ignore_patterns("marketplaces", ".trash"))


def base_settings() -> dict:
    s = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    s.pop("hooks", None)          # hooks never add tokens; keep the fleet's out of a private run
    return s


def arms(role: str, listed: list[str]) -> dict[str, tuple[dict, dict]]:
    """arm name -> (env additions, settings patch). Cumulative arms are built by the caller."""
    keep = set(ROLE_SKILLS.get(role, [])) | {role}
    off = {n: "off" for n in listed if n not in keep and n not in ROLE_CARDS}
    cards = {n: "user-invocable-only" for n in ROLE_CARDS if n != role}
    skills = {"skillOverrides": {**off, **cards}, "disableBundledSkills": True}
    return {
        "0-baseline": ({}, {}),
        "1-connectors-env": ({"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}, {}),
        "2-connectors-setting": ({}, {"disableClaudeAiConnectors": True}),
        "3-skills": ({}, skills),
        "3a-skill-overrides-only": ({}, {"skillOverrides": skills["skillOverrides"]}),
        "3b-disable-bundled-only": ({}, {"disableBundledSkills": True}),
        "4-deny-unused-tools": ({}, {"permissions": {"deny": UNUSED_TOOLS}}),
        "4a-deny-workflow-only": ({}, {"permissions": {"deny": ["Workflow"]}}),
        "3c-bundled-off+deny-workflow": ({}, {"disableBundledSkills": True, "permissions": {"deny": ["Workflow"]}}),
        "3d-skills+deny-workflow": ({}, {**skills, "permissions": {"deny": ["Workflow"]}}),
        "5-disable-cron-env": ({"CLAUDE_CODE_DISABLE_CRON": "1"}, {}),
        "6-all": ({"ENABLE_CLAUDEAI_MCP_SERVERS": "false", "CLAUDE_CODE_DISABLE_CRON": "1"},
                  {"disableClaudeAiConnectors": True, **skills, "permissions": {"deny": UNUSED_TOOLS}}),
    }


def run_arm(name: str, env_add: dict, patch: dict, role: str, cfg: Path, out: Path, model: str, rep: int) -> dict:
    s = base_settings()
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            s[k] = {**s[k], **v}
        else:
            s[k] = v
    (cfg / "settings.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP", "CLAUDE_CODE_", "ENABLE_CLAUDEAI"))}
    env.update({"CLAUDE_CONFIG_DIR": str(cfg), "EDP_ROLE": role, "EDP8_MCP_URL": "http://127.0.0.1:1",
                "DISABLE_AUTOUPDATER": "1", **env_add})
    cmd = ["claude", "-p", "Reply with the single word ok.", "--output-format", "json", "--model", model,
           "--dangerously-skip-permissions"]
    if os.name == "nt":
        cmd = ["cmd", "/c", *cmd]
    r = subprocess.run(cmd, cwd=AGENT_HOME, env=env, capture_output=True, text=True, timeout=300)
    raw = r.stdout.strip()
    try:
        res = json.loads(raw)
    except ValueError:
        return {"arm": name, "rep": rep, "error": (r.stderr or raw)[-500:]}
    u = res.get("usage") or {}
    total = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + (
        u.get("cache_read_input_tokens") or 0)
    row = {"arm": name, "rep": rep, "first_call_tokens": total, "usage": u, "session_id": res.get("session_id"),
           "cost_usd": res.get("total_cost_usd"), "num_turns": res.get("num_turns")}
    row.update(boot_attachments(cfg, res.get("session_id")))
    (out / f"{name}-{rep}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return row


def boot_attachments(cfg: Path, sid: str | None) -> dict:
    chars: dict[str, int] = {}
    skills: list[str] = []
    deferred: list[str] = []
    servers: list[str] = []
    for p in (cfg / "projects").rglob(f"{sid}.jsonl") if sid else []:
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            a = o.get("attachment") or {}
            t = a.get("type")
            if not t:
                continue
            n = sum(len(x.get("content", "")) for x in o.get("rendered") or [] if isinstance(x.get("content"), str))
            chars[t] = chars.get(t, 0) + n
            if t == "skill_listing":
                skills = list(a.get("names") or [])
            elif t == "deferred_tools_delta":
                deferred += list(a.get("addedNames") or [])
            elif t == "mcp_instructions_delta":
                servers += list(a.get("addedNames") or [])
    keep = ("skill_listing", "deferred_tools_delta", "mcp_instructions_delta", "agent_listing_delta", "instructions")
    return {"attachment_chars": {k: chars.get(k, 0) for k in keep}, "skills": skills, "deferred": deferred,
            "mcp_servers": servers}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--role", default="engineer")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--arms", default="")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--scratch", type=Path, required=True, help="scratch CLAUDE_CONFIG_DIR (created, deleted by caller)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    prepare_config(a.scratch)
    rows: list[dict] = []
    listed: list[str] = []
    want = [x for x in a.arms.split(",") if x]
    plan = arms(a.role, listed)
    first = run_arm("0-baseline", *plan["0-baseline"], a.role, a.scratch, a.out, a.model, 0)
    rows.append(first)
    listed = first.get("skills") or []
    plan = arms(a.role, listed)           # the skill-off list is derived from what the baseline really listed
    for name, (env_add, patch) in plan.items():
        if want and name not in want:
            continue
        for rep in range(a.reps):
            if name == "0-baseline" and rep == 0:
                continue
            rows.append(run_arm(name, env_add, patch, a.role, a.scratch, a.out, a.model, rep))
            print(name, rep, rows[-1].get("first_call_tokens"), rows[-1].get("error", ""), flush=True)
    (a.out / "arms.json").write_text(json.dumps({"role": a.role, "model": a.model, "rows": rows}, indent=1),
                                     encoding="utf-8")


if __name__ == "__main__":
    main()
