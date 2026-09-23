"""S-HARVEST token accounting (s-043eb90ccc, criterion c-f588b30545) — re-runnable from cold with the .venv python.

    .venv/Scripts/python.exe scripts/harvest_cost.py --participant qa.epic-<id>
    .venv/Scripts/python.exe scripts/harvest_cost.py --participant qa.epic-<id> --since 2026-09-24T10:00:00Z --json

What one /harvest cost, measured from the seat's own session log, and who else wrote self-improvement
records in that window:

- the seat's log: a Claude seat's transcript (edp-pool/.claude-pool/projects/**.jsonl, the one whose
  whoami result names the participant) or a codex seat's app-server mirror (.logs/**/codex-seat.<pid>.jsonl);
- the window: from the harvest trigger (Claude: the Skill("harvest") call or a Read of harvest/SKILL.md;
  codex: the first item naming harvest/SKILL.md; else the first harvest record call) to the seat's
  close_self (else the end of the log); `--since/--until` override it;
- tokens: Claude — usage summed over the assistant API calls in the window (one per message id);
  codex — thread/tokenUsage total at the window's end minus the total before it;
- other seats: GET /v1/knowledge (lessons + proposed docs) created in the window by anyone but the
  participant; `board` rows are the board's deterministic auto-records (no model call) and are
  counted apart.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

V8 = Path(__file__).resolve().parents[1]
CLAUDE_ROOTS = (V8.parent / "edp-pool" / ".claude-pool" / "projects", Path.home() / ".claude" / "projects")
CODEX_ROOTS = (V8.parent / ".logs", V8 / ".logs")
BOARD_AUTHOR = "board"


def _ts(value: str | float | int | None) -> float | None:
    """ISO-8601 (Z or offset) or epoch seconds -> epoch seconds; None stays None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except ValueError:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def _iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if t is not None else None


def _rows(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ----------------------------------------------------------------------------- finding the log
def find_log(participant: str, claude_roots=CLAUDE_ROOTS, codex_roots=CODEX_ROOTS) -> tuple[str, Path] | None:
    """The participant's newest session log as (kind, path), kind 'claude' | 'codex'; None if none found."""
    found: list[tuple[float, str, Path]] = []
    for root in codex_roots:
        if root.is_dir():
            found += [(p.stat().st_mtime, "codex", p) for p in root.rglob(f"codex-seat.{participant}.jsonl")]
    needles = (f'"participant": {{"id": "{participant}"', f'\\"participant\\": {{\\"id\\": \\"{participant}\\"')
    for root in claude_roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*.jsonl"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(n in text for n in needles):
                found.append((p.stat().st_mtime, "claude", p))
    if not found:
        return None
    _, kind, path = max(found)
    return kind, path


# ----------------------------------------------------------------------------- Claude transcripts
def _claude_calls(rows: list[dict]):
    """(ts, tool name, input) for every tool_use block in assistant rows."""
    for r in rows:
        msg = r.get("message") or {}
        if r.get("type") != "assistant" or not isinstance(msg.get("content"), list):
            continue
        for b in msg["content"]:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                yield _ts(r.get("timestamp")), str(b.get("name") or ""), b.get("input") or {}


def _is_harvest_record(name: str, args: dict) -> bool:
    base = name.rsplit("__", 1)[-1]
    return base == "record_lesson" or (base == "doc_create" and args.get("status") == "proposed")


def claude_window(rows: list[dict]) -> tuple[float | None, float | None]:
    start = end = None
    first_record = None
    for ts, name, args in _claude_calls(rows):
        trigger = (name == "Skill" and str(args.get("skill", "")).endswith("harvest")) or \
                  (name == "Read" and str(args.get("file_path", "")).replace("\\", "/").endswith("harvest/SKILL.md"))
        if start is None and trigger:
            start = ts
        if first_record is None and _is_harvest_record(name, args):
            first_record = ts
        if name.rsplit("__", 1)[-1] == "close_self" and (start or first_record) and ts >= (start or first_record):
            end = ts
    return (start or first_record), end


def claude_tokens(rows: list[dict], start: float, end: float | None) -> dict[str, int]:
    """Usage over the assistant API calls in [start, end], one per message id (a message split into
    several rows repeats its usage)."""
    seen: set[str] = set()
    tot = {"calls": 0, "input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
           "output_tokens": 0}
    for r in rows:
        msg = r.get("message") or {}
        ts = _ts(r.get("timestamp"))
        if r.get("type") != "assistant" or not msg.get("usage") or ts is None:
            continue
        if ts < start or (end is not None and ts > end):
            continue
        mid = msg.get("id") or r.get("uuid")
        if mid in seen:
            continue
        seen.add(mid)
        tot["calls"] += 1
        for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
            tot[k] += int(msg["usage"].get(k) or 0)
    return tot


# ----------------------------------------------------------------------------- codex seat mirrors
def codex_window(rows: list[dict]) -> tuple[float | None, float | None]:
    start = end = None
    first_record = None
    for r in rows:
        ts, m = r.get("ts"), r.get("msg") or {}
        item = (m.get("params") or {}).get("item") or {}
        # the skills/list catalog at boot names every skill path: only an item the model started counts
        if start is None and m.get("method") == "item/started" and item.get("type") != "mcpToolCall" \
                and "harvest/SKILL.md" in json.dumps(item).replace("\\\\", "/").replace("\\", "/"):
            start = ts
        if item.get("type") == "mcpToolCall":
            tool, args = str(item.get("tool") or ""), item.get("arguments") or {}
            if first_record is None and _is_harvest_record(tool, args if isinstance(args, dict) else {}):
                first_record = ts
            if tool == "close_self" and (start or first_record) and ts >= (start or first_record):
                end = ts
    return (start or first_record), end


def codex_tokens(rows: list[dict], start: float, end: float | None) -> dict[str, int]:
    """thread/tokenUsage `total` at the window's end minus the last total before it."""
    keys = ("inputTokens", "cachedInputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens")
    before = dict.fromkeys(keys, 0)
    after = dict(before)
    calls = 0
    for r in rows:
        m = r.get("msg") or {}
        if m.get("method") != "thread/tokenUsage/updated":
            continue
        total = (m.get("params") or {}).get("tokenUsage", {}).get("total") or {}
        ts = r.get("ts") or 0
        if ts < start:
            before = {k: int(total.get(k) or 0) for k in keys}
            after = dict(before)
        elif end is None or ts <= end:
            after = {k: int(total.get(k) or 0) for k in keys}
            calls += 1
    return {"calls": calls, **{k: after[k] - before[k] for k in keys}}


# ----------------------------------------------------------------------------- board side
def board_records(board: str, participant: str, token: str | None, viewer: str) -> dict:
    req = urllib.request.Request(f"{board}/v1/knowledge", headers={"X-Participant": viewer, **({"X-Token": token} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["value"]


def records_in_window(view: dict, start: float, end: float | None) -> list[dict]:
    """Lessons and proposed docs (by status or provenance) created in [start, end]."""
    out = []
    for le in view.get("lessons", []):
        out.append({"id": le["id"], "kind": "lesson", "created_by": le["created_by"], "at": le["created_at"]})
    for d in view.get("docs", []):
        if d.get("status") == "proposed" or d.get("source"):
            out.append({"id": d["id"], "kind": f"proposed:{d.get('proposes') or 'new'}",
                        "created_by": d["created_by"], "at": d["created_at"]})
    return [r for r in out if start <= _ts(r["at"]) and (end is None or _ts(r["at"]) <= end)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--participant", required=True)
    ap.add_argument("--log", help="the seat's log (default: found by participant)")
    ap.add_argument("--since"), ap.add_argument("--until")
    ap.add_argument("--board", default=os.environ.get("EDP8_BOARD_URL", "http://127.0.0.1:9400"))
    ap.add_argument("--no-board", action="store_true", help="skip the other-seats check")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.log:
        path = Path(a.log)
        kind = "codex" if path.name.startswith("codex-seat.") else "claude"
    else:
        hit = find_log(a.participant)
        if hit is None:
            print(f"no session log found for {a.participant}", file=sys.stderr)
            return 2
        kind, path = hit
    rows = _rows(path)
    start, end = (claude_window if kind == "claude" else codex_window)(rows)
    since, until = _ts(a.since), _ts(a.until)
    start = since if since is not None else start
    end = until if until is not None else end
    if start is None:
        print(f"no harvest found in {path} (pass --since)", file=sys.stderr)
        return 3
    tokens = (claude_tokens if kind == "claude" else codex_tokens)(rows, start, end)
    out = {"participant": a.participant, "log": str(path), "seat": kind,
           "window": {"start": _iso(start), "end": _iso(end)}, "tokens": tokens}
    if not a.no_board:
        viewer = os.environ.get("EDP8_PARTICIPANT") or os.environ.get("EDP_HANDLE") or a.participant
        recs = records_in_window(board_records(a.board, a.participant, os.environ.get("EDP8_TOKEN"), viewer), start, end)
        out["records"] = {
            "by_participant": [r for r in recs if r["created_by"] == a.participant],
            "board_auto": [r for r in recs if r["created_by"] == BOARD_AUTHOR],
            "other_seats": [r for r in recs if r["created_by"] not in (a.participant, BOARD_AUTHOR)],
        }
    if a.json:
        print(json.dumps(out, indent=2))
        return 0
    t = tokens
    if kind == "claude":
        line = (f"{t['calls']} API calls | input {t['input_tokens']} + cache write {t['cache_creation_input_tokens']}"
                f" + cache read {t['cache_read_input_tokens']} | output {t['output_tokens']}")
    else:
        line = (f"{t['calls']} usage updates | input {t['inputTokens']} (cached {t['cachedInputTokens']})"
                f" | output {t['outputTokens']} (reasoning {t['reasoningOutputTokens']})")
    print(f"harvest cost for {a.participant} ({kind} seat) {out['window']['start']} -> {out['window']['end']}: {line}")
    print(f"log: {path}")
    if "records" in out:
        r = out["records"]
        print(f"records in window: {len(r['by_participant'])} by {a.participant}, {len(r['board_auto'])} board "
              f"auto-records (no model), {len(r['other_seats'])} by other seats")
        for row in r["by_participant"] + r["other_seats"]:
            print(f"  {row['id']}  {row['kind']}  by {row['created_by']}  at {row['at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
