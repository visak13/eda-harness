"""Per-role first-call breakdown of Claude Code seat boots (read-only over pool transcripts).

For every main-session transcript (subagent transcripts excluded) it reads the records before the first
assistant API call and buckets the boot attachments by rendered chars (tokens ~ chars/4, ESTIMATED), and
takes the first call's input-side tokens (input + cache write + cache read, MEASURED from usage).

Usage: python first_call_breakdown.py [--dir <projects dir>] [--since YYYY-MM-DD] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

DEFAULT_DIR = Path.home() / "AppData/Local/heronry/data/claude-pool/projects"
BUCKETS = {
    "skill_listing": "skills",
    "deferred_tools_delta": "deferred tool names",
    "mcp_instructions_delta": "mcp server instructions",
    "agent_listing_delta": "agent types",
    "instructions": "CLAUDE.md + instructions",
    "output_style_instructions": "output style",
    "session_context": "session context",
}


def _chars(rec: dict) -> int:
    n = 0
    for x in rec.get("rendered") or []:
        c = x.get("content") if isinstance(x, dict) else None
        if isinstance(c, str):
            n += len(c)
    return n


def boot(path: Path) -> dict | None:
    role = ""
    chars: Counter = Counter()
    skills: list[str] = []
    deferred: list[str] = []
    mcp_servers: list[str] = []
    first_ts = None
    result: dict | None = None
    calls = 0
    with path.open(encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            first_ts = first_ts or o.get("timestamp")
            t = o.get("type")
            if t == "user" and not role:
                c = (o.get("message") or {}).get("content")
                text = c if isinstance(c, str) else " ".join(b.get("text", "") for b in c or [] if isinstance(b, dict))
                m = re.search(r"<command-name>/?([\w-]+)</command-name>", text or "")
                role = m.group(1) if m else ""
            elif t == "attachment":
                a = o.get("attachment") or {}
                at = a.get("type")
                if at in BUCKETS:
                    chars[at] += _chars(o)
                if at == "skill_listing":
                    skills = list(a.get("names") or [])
                elif at == "deferred_tools_delta":
                    deferred += list(a.get("addedNames") or [])
                elif at == "mcp_instructions_delta":
                    mcp_servers += list(a.get("addedNames") or [])
            elif t == "assistant":
                m = o.get("message") or {}
                if m.get("model") == "<synthetic>":
                    continue
                calls += 1
                if result is None:
                    u = m.get("usage") or {}
                    first = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + (
                        u.get("cache_read_input_tokens") or 0)
                    result = {"session": path.stem, "role": role or "?", "ts": first_ts, "first_call_tokens": first,
                              "model": m.get("model", "")}
                # MCP servers connect after the first call: connector attachments land in the first few calls
                if calls >= 12:
                    break
    if result is None:
        return None
    result.update({"chars": dict(chars), "skills": skills, "deferred": deferred, "mcp_servers": mcp_servers})
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--since", default="2026-09-01")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    rows = []
    for p in a.dir.rglob("*.jsonl"):
        if "subagents" in p.parts:
            continue
        b = boot(p)
        if b and b["ts"] and b["ts"][:10] >= a.since and b["first_call_tokens"] > 0:
            rows.append(b)
    by_role: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_role[r["role"]].append(r)
    out: dict = {"since": a.since, "generated": datetime.now().isoformat(timespec="seconds"),
                 "sessions": len(rows), "roles": {}}
    for role, rs in sorted(by_role.items()):
        # a boot with no attachments recorded is a resumed session (attachments are only written fresh once)
        fresh = [r for r in rs if r["chars"].get("skill_listing")]
        med = lambda xs: int(statistics.median(xs)) if xs else 0  # noqa: E731
        ent = {"sessions": len(rs), "fresh_boots_with_attachments": len(fresh),
               "first_call_tokens_median": med([r["first_call_tokens"] for r in rs]),
               "first_call_tokens_median_fresh": med([r["first_call_tokens"] for r in fresh])}
        for key, label in BUCKETS.items():
            ent[f"{label} chars_median"] = med([r["chars"].get(key, 0) for r in fresh])
        ent["skills_count_median"] = med([len(r["skills"]) for r in fresh])
        ent["deferred_tool_names_count_median"] = med([len(r["deferred"]) for r in fresh])
        sk = Counter(s for r in fresh for s in set(r["skills"]))
        ent["skills_seen"] = {k: v for k, v in sk.most_common()}
        dn = Counter(s for r in fresh for s in set(r["deferred"]))
        ent["deferred_names_seen"] = {k: v for k, v in dn.most_common()}
        mc = Counter(s for r in fresh for s in set(r["mcp_servers"]))
        ent["mcp_instruction_servers_seen"] = dict(mc)
        conn = [r for r in fresh if any(s.startswith("claude.ai") for s in r["mcp_servers"])]
        ent["boots_with_claudeai_connectors"] = len(conn)
        ent["connector_first_day"] = min((r["ts"][:10] for r in conn), default=None)
        ent["connector_boot_chars_median"] = med([r["chars"].get("mcp_instructions_delta", 0) for r in conn])
        out["roles"][role] = ent
    text = json.dumps(out, indent=1)
    if a.json:
        a.json.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
