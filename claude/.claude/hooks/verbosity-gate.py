#!/usr/bin/env python
"""Stop hook — measure (and, armed, nudge on) over-budget final prose in
SPAWNED shells (v7 WS4 §2.7/§2.8).

THE BURN THIS EXISTS TO CLOSE (user ruling, 2026-08-05): only the neuron's
gate surfaces are read by a human; every other role's end-of-turn narration
is written for NO READER — measured live at ~0.5-1k output tokens per wake,
dozens of wakes a day. The API-level ceiling (CLAUDE_CODE_MAX_OUTPUT_TOKENS,
stamped per seat from models.json) is the hard cap; THIS hook is the
behavioral layer under it: it measures the final assistant text of every
spawned shell's turn and — when armed — nudges a shell that narrated past
the budget to stop doing that.

SCOPE: shells WITH an EDP_ROLE only (spawned). The foreground seat carries
no EDP_ROLE (capture-session gates on exactly that absence) and its gate
surfaces are legitimately long — it must pass through untouched.

MODES (worker-close-nudge discipline, measured rollout):
  * PROBE (default): log {role, chars, over} to .logs/verbosity-gate.jsonl
    and ALWAYS allow the stop. Zero risk; WS5 drills read this log to
    calibrate the budget before anyone arms it.
  * ARMED (EDP_VERBOSITY_GATE=1): over-budget final text gets ONE
    decision=block + additionalContext nudge per session (cap 1 — a shell
    that re-narrates after the nudge is logged, never looped).

Budget: EDP_VERBOSITY_BUDGET_CHARS (default 1200 ≈ 300 tokens — generous
for `OK w=10m` + a short pyramid; tiny against a narration essay).

FAIL-OPEN, ALWAYS. Any error allows the stop. A hook that breaks a shell is
worse than a shell that narrates.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_BLOCKS = 1
DEFAULT_BUDGET_CHARS = 1200

LOG = Path(__file__).resolve().parent.parent.parent / ".logs" / "verbosity-gate.jsonl"
STATE = Path(__file__).resolve().parent.parent.parent / ".logs" / "verbosity-gate-state.json"

NUDGE = (
    "YOUR FINAL TEXT EXCEEDED THE VERBOSITY BUDGET, AND THERE IS NO READER "
    "ON THIS WINDOW.\n\nEverything you narrated is (or belongs) in the "
    "record: record_* tools carry results, the worklog carries progress, "
    "the panel renders state. The contract (terse-output + the cron "
    "prompt): a wake's final text is at most `OK w=<wait>`; a no-change "
    "wake emits NOTHING. End your turn now with at most one line."
)


def _log(payload: dict) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except Exception:
        pass


def _blocks_for(session_id: str) -> int:
    try:
        return int(json.loads(STATE.read_text(encoding="utf-8")).get(session_id, 0))
    except Exception:
        return 0


def _bump(session_id: str) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data[session_id] = int(data.get(session_id, 0)) + 1
        STATE.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def _final_text_chars(transcript_path: str) -> int | None:
    """Length of the LAST assistant message's text parts. None = unknown —
    and None must be treated as 'do not act', never as 'over budget'."""
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8",
                                                errors="replace").splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        msg = row.get("message") if isinstance(row, dict) else None
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return len(content)
        if isinstance(content, list):
            return sum(len(p.get("text", ""))
                       for p in content
                       if isinstance(p, dict) and p.get("type") == "text")
        return None
    return None


def main() -> int:
    raw = ""
    parse_error = None
    try:
        raw = sys.stdin.read()
    except Exception as exc:          # noqa: BLE001
        parse_error = f"stdin read failed: {exc!r}"
    event = {}
    if parse_error is None and raw.strip():
        try:
            event = json.loads(raw.lstrip("﻿"))
        except Exception as exc:      # noqa: BLE001
            parse_error = f"stdin was not JSON: {exc!r}"

    role = (os.environ.get("EDP_ROLE") or "").strip().lower()
    session_id = event.get("session_id") or ""
    armed = (os.environ.get("EDP_VERBOSITY_GATE") or "").lower() in (
        "1", "true", "yes", "on")
    try:
        budget = int(os.environ.get("EDP_VERBOSITY_BUDGET_CHARS",
                                    str(DEFAULT_BUDGET_CHARS)))
    except ValueError:
        budget = DEFAULT_BUDGET_CHARS

    chars = _final_text_chars(event.get("transcript_path") or "") \
        if role else None
    blocks = _blocks_for(session_id)
    over = chars is not None and chars > budget

    _log({
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "edp_role": role or None,
        "final_chars": chars,
        "budget": budget,
        "over": over,
        "prior_blocks": blocks,
        "armed": armed,
        "parse_error": parse_error,
    })

    # role present (spawned) · measurably over · armed · under the cap
    if armed and role and over and blocks < MAX_BLOCKS:
        _bump(session_id)
        json.dump({
            "decision": "block",
            "reason": (f"final text {chars} chars exceeds the "
                       f"{budget}-char spawned-shell budget"),
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": NUDGE,
            },
        }, sys.stdout)
        return 0
    return 0   # allow the stop


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)   # fail-open, always
