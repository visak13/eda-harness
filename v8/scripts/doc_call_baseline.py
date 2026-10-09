"""Doc-call error rate and bytes per doc change, from Claude seat transcripts (s-bdc00a9ed2, design-63db8a7d42 item L).

Counts every `mcp__edp8__doc_*` tool call in the claude-pool transcripts inside a time window, the calls whose result
was an error, the error class (argument shape / section name / version conflict / other), and the median bytes of
the arguments of a doc change (a doc_create, doc_update or doc_edit call that succeeded; failed attempts are
reported apart as attempted_writes). Run it before a release ships (the baseline) and
over a window after, and compare the two JSON outputs.

    python scripts/doc_call_baseline.py --until 2026-10-09 > before.json
    python scripts/doc_call_baseline.py --since 2026-10-20 > after.json

Stdlib only. Reads the transcripts, never writes them.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

CHANGE_TOOLS = {"doc_create", "doc_update", "doc_edit"}
PREFIX = "mcp__edp8__"


def default_projects_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "heronry" / "data" / "claude-pool" / "projects"


def classify(text: str) -> str:
    """The error class of a doc tool result: the board's own message decides, never a guess from the arguments."""
    low = text.lower()
    if "section_match" in low or "section must name" in low:
        return "section_name"
    if "version_conflict" in low or "version_mismatch" in low or "expected version" in low:
        return "version_conflict"
    shape = ("validation error", "unexpected keyword", "extra inputs", "field required", "invalid_arguments",
             "unknown arg", "input should be", "not an accepted argument", "extra_forbidden", "missing")
    if any(s in low for s in shape):
        return "argument_shape"
    return "other"


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def _failed(block: dict, text: str) -> bool:
    if block.get("is_error"):
        return True
    return text.lstrip()[:200].replace(" ", "").startswith('{"ok":false')


def scan(root: Path, since: str | None, until: str | None) -> dict:
    """The cohort is the calls STARTED in the window (by the call's own timestamp); each one's result is joined
    whenever it came back, so a call that crosses midnight is counted in the window it began in, errors included.
    A call with no result in the transcripts is counted apart (`calls_without_result`)."""
    calls: dict[str, tuple[str, int]] = {}  # tool_use id -> (tool, argument bytes); in-window calls only
    totals, errors, classes = Counter(), Counter(), Counter()
    attempt_bytes: list[int] = []   # arguments of every doc_create/update/edit call, failed or not
    change_bytes: list[int] = []    # arguments of the ones whose result was not an error
    answered: set[str] = set()
    files = 0
    for path in root.rglob("*.jsonl"):
        files += 1
        try:
            fh = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if PREFIX + "doc_" not in line and '"tool_result"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                ts = (row.get("timestamp") or "")[:10]
                content = (row.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use" and str(b.get("name", "")).startswith(PREFIX + "doc_"):
                        if (since and ts < since) or (until and ts >= until):
                            continue  # the cohort is chosen by the CALL's timestamp only
                        name = b["name"][len(PREFIX):]
                        size = len(json.dumps(b.get("input") or {}, ensure_ascii=False).encode("utf-8"))
                        calls[b["id"]] = (name, size)
                        totals[name] += 1
                        if name in CHANGE_TOOLS:
                            attempt_bytes.append(size)
                    elif b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                        name, size = calls[b["tool_use_id"]]
                        answered.add(b["tool_use_id"])
                        text = _text(b.get("content"))
                        if _failed(b, text):
                            errors[name] += 1
                            classes[classify(text)] += 1
                        elif name in CHANGE_TOOLS:
                            change_bytes.append(size)
    n, e = sum(totals.values()), sum(errors.values())
    return {
        "window": {"since": since, "until": until, "cohort": "calls started in the window, by the call's timestamp"},
        "transcript_files": files,
        "doc_calls": n, "doc_call_errors": e, "error_rate": round(e / n, 4) if n else None,
        "calls_without_result": len(calls) - len(answered),
        "by_tool": {k: {"calls": totals[k], "errors": errors[k]} for k in sorted(totals)},
        "error_classes": dict(classes),
        "error_class_share": {k: round(v / e, 3) for k, v in classes.items()} if e else {},
        "doc_changes": len(change_bytes),
        "median_bytes_per_change": statistics.median(change_bytes) if change_bytes else None,
        "mean_bytes_per_change": round(statistics.mean(change_bytes)) if change_bytes else None,
        "total_change_bytes": sum(change_bytes),
        "attempted_writes": len(attempt_bytes),
        "median_bytes_per_attempted_write": statistics.median(attempt_bytes) if attempt_bytes else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--projects", type=Path, default=default_projects_dir(), help="claude-pool projects dir")
    ap.add_argument("--since", help="first day included, YYYY-MM-DD (UTC)")
    ap.add_argument("--until", help="first day excluded, YYYY-MM-DD (UTC)")
    a = ap.parse_args(argv)
    if not a.projects.is_dir():
        print(f"no such directory: {a.projects}", file=sys.stderr)
        return 2
    json.dump(scan(a.projects, a.since, a.until), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
