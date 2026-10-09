"""Size distribution of Bash / PowerShell / Read / MCP tool results across the seat transcripts (S8 output caps).

For each tool it reports result count, chars at p50/p90/p99/max, and — for candidate caps — how many results a
cap would have clipped and what share of all result chars sat beyond the cap (the chars a cap saves).
Tokens ~ chars/4 (ESTIMATE, same as eda-context token_split). Read-only; stdlib only.

Usage: python tool_result_sizes.py [--dir <projects dir>] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

DEFAULT_DIR = Path.home() / "AppData/Local/heronry/data/claude-pool/projects"
GROUPS = {"Bash": ("Bash",), "PowerShell": ("PowerShell",), "Read": ("Read",)}
CAPS = {"Bash": [8_000, 12_000, 15_000, 20_000, 30_000], "PowerShell": [8_000, 12_000, 15_000, 20_000, 30_000],
        "Read": [20_000, 40_000, 60_000, 100_000], "mcp": [16_000, 24_000, 40_000]}


def result_chars(block: dict) -> int:
    c = block.get("content")
    if isinstance(c, str):
        return len(c)
    return sum(len(p.get("text", "")) for p in c or [] if isinstance(p, dict) and p.get("type") == "text")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    sizes: dict[str, list[int]] = defaultdict(list)
    for p in a.dir.rglob("*.jsonl"):
        if "subagents" in p.parts:
            continue
        names: dict[str, str] = {}
        try:
            f = p.open(encoding="utf-8", errors="replace")
        except OSError:      # a path past Windows MAX_PATH (a nested scratchpad session): skipped, counted
            sizes["_skipped_files"].append(0)
            continue
        with f:
            for raw in f:
                try:
                    o = json.loads(raw)
                except ValueError:
                    continue
                msg = o.get("message") or {}
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        names[b.get("id", "")] = b.get("name", "")
                    elif b.get("type") == "tool_result":
                        n = names.get(b.get("tool_use_id", ""), "")
                        key = "mcp" if n.startswith("mcp__edp8__") else n if n in GROUPS else None
                        if key:
                            sizes[key].append(result_chars(b))
    out: dict = {"skipped_unreadable_files": len(sizes.pop("_skipped_files", []))}
    for key, xs in sizes.items():
        xs.sort()
        total = sum(xs)
        ent = {"results": len(xs), "total_chars": total, "p50": int(statistics.median(xs)),
               "p90": xs[int(len(xs) * 0.9)], "p99": xs[int(len(xs) * 0.99)], "max": xs[-1], "caps": {}}
        for cap in CAPS[key]:
            clipped = [x for x in xs if x > cap]
            saved = sum(x - cap for x in clipped)
            ent["caps"][str(cap)] = {"results_clipped": len(clipped), "chars_saved": saved,
                                     "share_of_chars_saved": round(saved / total, 4) if total else 0}
        out[key] = ent
    text = json.dumps(out, indent=1)
    if a.json:
        a.json.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
