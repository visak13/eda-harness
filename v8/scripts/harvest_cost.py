"""S-HARVEST token accounting — seats use the `harvest_cost` MCP tool (S23); this CLI is the human's view (s-043eb90ccc, criterion c-f588b30545) — re-runnable from cold with the .venv python.

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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from edp8.harvest_cost import (  # noqa: E402,F401 — re-exported for tests/test_harvest.py
    BOARD_AUTHOR, CLAUDE_ROOTS, CODEX_ROOTS, V8, _iso, _rows, _ts, board_records, claude_tokens, claude_window,
    codex_tokens, codex_window, find_log, records_in_window)


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
        if not path.is_file():  # S-ADV finding 9: a missing or rotated log is a message, not a traceback
            print(f"no session log at {path} for {a.participant}", file=sys.stderr)
            return 2
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
