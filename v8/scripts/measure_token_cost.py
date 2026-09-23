"""S20 token-cost measurement (story s-b123a91d3f) — re-runnable from cold with the .venv python.

    .venv/Scripts/python.exe scripts/measure_token_cost.py tools          # per-role tool-surface bytes
    .venv/Scripts/python.exe scripts/measure_token_cost.py invoked [--days 30]   # board tools each role called
    .venv/Scripts/python.exe scripts/measure_token_cost.py boot           # card + CLAUDE.md + tools per role
    .venv/Scripts/python.exe scripts/measure_token_cost.py heartbeat      # one real heartbeat per role replayed

"Before" numbers: `git archive e742f69 v8 | tar -x -C <dir>` then EDP8_MEASURE_ROOT=<dir>/v8 with the same commands.

`tools` counts what the audit (note-5294e42a0f) counted: name + description + args JSON schema per
ToolDef of tools_for_role(role), UTF-8 bytes; `wire` is the MCP tools/list JSON the server really sends.
`invoked` scans the Claude seat transcripts (edp-pool/.claude-pool/projects/*/**.jsonl, subagents
included) for mcp__edp8__<tool> tool_use blocks; a transcript's role is its first /<role> command.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

V8 = Path(__file__).resolve().parents[1]
# EDP8_MEASURE_ROOT=<an extracted older tree's v8/> measures that tree ("before") with the same code
ROOT = Path(os.environ.get("EDP8_MEASURE_ROOT") or V8)
sys.path.insert(0, str(ROOT / "src"))

from edp8.bundles import ROLE_BUNDLES, tools_for_role  # noqa: E402

# pool-spawned seats, and the human's own shells (the owner seat runs there)
TRANSCRIPT_ROOTS = (V8.parent / "edp-pool" / ".claude-pool" / "projects", Path.home() / ".claude" / "projects")
SEAT_ROLES = ("architect", "engineer", "qa", "reviewer", "sme", "owner", "adversary")
_CMD = re.compile(r"<command-name>/(\w+)</command-name>")
_WHOAMI_ROLE = re.compile(r'\\"type\\": \\"(?:agent|human)\\", \\"role\\": \\"(\w+)\\"')


def _schema(t) -> dict:
    """The schema the server advertises: ToolDef.input_schema (S20); the raw pydantic schema before it."""
    return t.input_schema if hasattr(t, "input_schema") else t.args_model.model_json_schema()


def tool_bytes(role: str) -> tuple[int, int]:
    ts = tools_for_role(role)
    return len(ts), sum(len(t.name.encode()) + len(t.description.encode())
                        + len(json.dumps(_schema(t), ensure_ascii=False).encode()) for t in ts)


def wire_bytes(role: str) -> int:
    from edp8.mcp_server import build_role_server
    tl = asyncio.run(build_role_server(role, board_url="http://127.0.0.1:1", admin_token=None).list_tools())
    return len(json.dumps([t.model_dump(exclude_none=True, by_alias=True) for t in tl]).encode())


def cmd_tools(_: argparse.Namespace) -> None:
    print("| role | tools | desc+schema B | wire tools/list B |\n|---|---|---|---|")
    for r in SEAT_ROLES:
        n, b = tool_bytes(r)
        print(f"| {r} | {n} | {b:,} | {wire_bytes(r):,} |")


def _role_of(path: Path) -> str | None:
    """The seat's role: its first /<role> command, else the role its first whoami() returned."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        for i, ln in enumerate(fh):
            m = _CMD.search(ln) if i < 60 else None
            if m and m.group(1) in SEAT_ROLES:
                return m.group(1)
            w = _WHOAMI_ROLE.search(ln)
            if w and w.group(1) in SEAT_ROLES:
                return w.group(1)
    return None


def scan_invoked(days: int) -> dict[str, dict[str, int]]:
    cutoff = time.time() - days * 86400
    used: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for top in sorted(p for root in TRANSCRIPT_ROOTS for p in root.glob("*/*.jsonl")):
        if top.stat().st_mtime < cutoff:
            continue
        role = _role_of(top)
        if role is None:
            continue
        files = [top, *(top.parent / top.stem).glob("**/*.jsonl")]  # the seat's subagents count for it
        for f in files:
            with f.open(encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    if '"tool_use"' not in ln or "mcp__edp8__" not in ln:
                        continue
                    try:
                        content = json.loads(ln).get("message", {}).get("content", [])
                    except json.JSONDecodeError:
                        continue
                    for c in content if isinstance(content, list) else []:
                        if c.get("type") == "tool_use" and str(c.get("name", "")).startswith("mcp__edp8__"):
                            used[role][c["name"].removeprefix("mcp__edp8__")] += 1
    return used


def cmd_invoked(a: argparse.Namespace) -> None:
    used = scan_invoked(a.days)
    for r in SEAT_ROLES:
        bundle = set(ROLE_BUNDLES[r])
        names = sorted(used.get(r, {}), key=lambda k: -used[r][k])
        missing = [n for n in names if n not in bundle]
        print(f"{r}: " + ", ".join(f"{n}×{used[r][n]}" for n in names))
        print(f"  invoked-but-not-in-bundle: {missing or 'none'}")
        print(f"  in-bundle-never-invoked: {sorted(bundle - set(names)) or 'none'}")


def cmd_boot(_: argparse.Namespace) -> None:
    claude_md = len((ROOT / "CLAUDE.md").read_bytes())
    print(f"CLAUDE.md {claude_md:,} B\n| role | card B | tools B | boot B | ≈tokens |\n|---|---|---|---|---|")
    for r in SEAT_ROLES:
        card = len((ROOT / ".claude" / "commands" / f"{r}.md").read_bytes())
        _, tb = tool_bytes(r)
        boot = card + claude_md + tb
        print(f"| {r} | {card:,} | {tb:,} | {boot:,} | {boot // 4:,} |")


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, list):
        return "".join(x.get("text", "") for x in c if isinstance(x, dict))
    return c if isinstance(c, str) else ""


def _rows(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return out


def _tool_results(rows: list[dict]) -> dict[str, str]:
    """tool_use_id -> result text."""
    res = {}
    for r in rows:
        c = r.get("message", {}).get("content")
        for x in c if isinstance(c, list) else []:
            if isinstance(x, dict) and x.get("type") == "tool_result":
                res[x.get("tool_use_id")] = _result_text(x)
    return res


def _events_in(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        c = r.get("message", {}).get("content")
        t = c if isinstance(c, str) else "".join(x.get("text", "") for x in c if isinstance(x, dict)) \
            if isinstance(c, list) else ""
        if "<task-notification>" in t and "Monitor event" in t:
            out += re.findall(r"<event>(.*?)</event>", t, re.S)
    return out


def _replay(rows: list[dict], results: dict[str, str], hb: int) -> tuple[str | None, int, int]:
    """(refresh tool, its result bytes, the preceding feed event bytes) for the heartbeat at row hb."""
    refresh_tool, refresh_b = None, 0
    for r in rows[hb + 1:hb + 60]:
        c = r.get("message", {}).get("content")
        for x in c if isinstance(c, list) else []:
            if isinstance(x, dict) and x.get("type") == "tool_use" and x["name"] in (
                    "mcp__edp8__context", "mcp__edp8__context_delta"):
                refresh_tool = x["name"].removeprefix("mcp__edp8__")
                refresh_b = len(results.get(x["id"], "").encode())
        if refresh_tool:
            break
    events = _events_in(rows[:hb])
    return refresh_tool, refresh_b, len((events[-1] if events else "").encode())


def cmd_heartbeat(a: argparse.Namespace) -> None:
    """Replay one real heartbeat turn per role: the last heartbeat of that role's transcript with the most
    heartbeats; its refresh call and the feed event before it, before vs after S20. After = context_delta
    (the card's heartbeat call) bounded by today's page cap, and the event through feed_driver.cap_line."""
    from edp8 import feed_driver
    from edp8.context_delta import delta_budget
    pool = TRANSCRIPT_ROOTS[0]
    by_role: dict[str, list[tuple[Path, list[dict]]]] = defaultdict(list)
    for p in pool.glob("*/*.jsonl"):
        r = _role_of(p)
        if r:
            by_role[r].append((p, _rows(p)))
    beats = lambda rows: [i for i, r in enumerate(rows) if r.get("type") == "user"  # noqa: E731
                          and "edp8 heartbeat" in json.dumps(r.get("message", {}))[:4000]]
    deltas = sorted(len(t.encode()) for lst in by_role.values() for _, rows in lst
                    for t in _tool_results(rows).values() if '"next_cursor"' in t and '"changed"' in t)
    med = deltas[len(deltas) // 2] if deltas else 0
    cap = delta_budget()
    print(f"context_delta results in transcripts: n={len(deltas)} median={med:,} B max={max(deltas or [0]):,} B; "
          f"page cap now {cap:,} B; feed event cap {feed_driver._event_budget():,} B")
    print("| role | transcript · heartbeat row | refresh before | event B | turn before B (≈tok) "
          "| turn after B (≈tok) |\n|---|---|---|---|---|---|")
    for role in SEAT_ROLES:
        cands = [(p, rows, beats(rows)) for p, rows in by_role.get(role, [])]
        cands = [c for c in cands if c[2]]
        if not cands:
            print(f"| {role} | no heartbeat in transcripts | | | | |")
            continue
        path, rows, hbs = max(cands, key=lambda c: len(c[2]))
        tool, rb, eb = _replay(rows, _tool_results(rows), hbs[-1])
        before = rb + eb
        refresh_after = 0 if tool is None else min(rb, cap) if tool == "context_delta" else min(med, cap)
        after = refresh_after + min(eb, feed_driver._event_budget())
        print(f"| {role} | {path.stem[:8]} · {hbs[-1]} | {tool or 'none'} {rb:,} B | {eb:,} | "
              f"{before:,} (≈{before // 4:,}) | {after:,} (≈{after // 4:,}) |")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tools").set_defaults(fn=cmd_tools)
    inv = sub.add_parser("invoked")
    inv.add_argument("--days", type=int, default=30)
    inv.set_defaults(fn=cmd_invoked)
    sub.add_parser("boot").set_defaults(fn=cmd_boot)
    sub.add_parser("heartbeat").set_defaults(fn=cmd_heartbeat)
    args = p.parse_args()
    args.fn(args)
