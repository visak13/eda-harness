#!/usr/bin/env python
"""Stop hook — nudge a finished WORKER shell to close itself.

THE LEAK THIS EXISTS TO CLOSE (operator, 2026-07-25). A worker finishes its
action, records a terminal status, and then ENDS ITS TURN without calling
`pool_close_self`. The shell stays alive holding a pool slot. Claude Code
shows it as awaiting input — but THERE IS NO HUMAN ON THAT WINDOW. The whole
rx design routes a shell's needs to the operator THROUGH THE NEURON. A worker
waiting for direct attention has misread its own architecture, and nobody is
coming.

WHY THIS TRIGGER AND NOT THE OBVIOUS ONES.
  * NOT cron deletion — the neuron and planners re-arm heartbeats constantly
    for self-pacing, so a cron event is not a close signal.
  * NOT Monitor teardown — a planner legitimately stops and re-arms a Monitor
    mid-life (observed live: un-merging an orphan leg from its inbox), and a
    SPECIALIST never arms one at all. A signal some roles never emit cannot be
    the mechanism.
  * `Stop` fires at END OF TURN, which IS the moment the leak happens.

SCOPE IS DELIBERATELY NARROW: a CLEAN WORKER CLOSE. Crashes belong to the rx
plane (rx.pool / rx.orphaned) and are not this hook's business. Planners,
reviewers, specialists and the neuron are OUT OF SCOPE and must pass through
untouched — a planner blocked mid-step, or a parked one told to close, would
be a far worse failure than the leak.

TWO MODES.
  * PROBE (default): log what we see and ALWAYS allow the stop. Zero risk.
    This exists because the docs do NOT state whether `Stop` fires inside a
    SPAWNED worker process at all (our shells are separate Claude Code
    instances, not Task subagents). That is an assumption, so it gets measured
    before anything is built on it.
  * ARMED (EDP_WORKER_CLOSE_NUDGE=1): additionally, when the guard passes,
    emit decision=block + additionalContext so the shell READS the nudge and
    acts IN THE SAME TURN. `additionalContext` alone is not enough — it is not
    read until the next model request, which for an idle worker never comes.

LOOP PROTECTION IS MANDATORY AND HAS NO BUILT-IN. There is no
`stop_hook_active` field. A hook that blocks unconditionally makes a shell
that can NEVER end its turn, burning tokens forever — strictly worse than the
leak. So blocks are counted per session and capped; past the cap the stop is
allowed and the failure is logged rather than hidden.

FAIL-OPEN, ALWAYS. Any error here allows the stop. A hook that breaks a shell
is worse than a shell that lingers.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Cap on how many times ONE session may be blocked. Two is enough for a shell
# that simply forgot; a shell that ignores two nudges has a different problem
# and must not be trapped in a loop.
MAX_BLOCKS = 2

LOG = Path(__file__).resolve().parent.parent.parent / ".logs" / "worker-close-nudge.jsonl"
STATE = Path(__file__).resolve().parent.parent.parent / ".logs" / "worker-close-nudge-state.json"

NUDGE = (
    "YOUR WORK IS RECORDED TERMINAL AND YOUR SHELL IS STILL OPEN.\n\n"
    "THERE IS NO HUMAN ON THIS WINDOW. Nobody will answer you here. The "
    "reactive plane routes a shell's needs to the operator THROUGH THE "
    "NEURON — if you need something, send it to your planner or the neuron "
    "over the broker. Ending your turn to wait for attention strands you and "
    "holds a pool slot nothing else can use.\n\n"
    "Finish your close sequence NOW: stop your Monitor, delete your cron, "
    "then call pool_close_self. If you genuinely have remaining work, do it "
    "instead — but do not simply stop."
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


def _action_is_terminal(handle: str) -> bool | None:
    """Is the action this shell OWNS recorded terminal?

    `handle` is `<plan_id>:<action_id>`. Returns None when it cannot be
    determined — and None must be treated as "do not act", never as "yes".
    """
    if not handle or ":" not in handle:
        return None
    plan_id, _, action_id = handle.rpartition(":")
    plans_root = Path(__file__).resolve().parent.parent.parent / ".plans"
    # Phase 6 fix (2026-07-30): plans live at .plans/<plan_id>.json — the
    # <plan_id>/ DIRECTORY is the sidecar (worklog/evidence/snapshots) and
    # holds no plan.json. The original candidates both pointed inside the
    # sidecar dir, so this check ALWAYS returned None and the guard could
    # never pass. The sidecar forms are kept as fallbacks only.
    for candidate in (plans_root / f"{plan_id}.json",
                      plans_root / plan_id / "plan.json",
                      plans_root / plan_id / f"{plan_id}.json"):
        try:
            plan = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        for a in plan.get("actions", []):
            if a.get("action_id") == action_id:
                return a.get("status") in ("done", "failed", "skipped")
    return None


def main() -> int:
    # READ AND PARSE SEPARATELY, AND LOG EITHER WAY. The first version of
    # this returned early on a parse failure WITHOUT logging — so the one
    # case the probe most needed to capture (stdin absent or malformed) was
    # the one case it could not report. That is the exact silent-failure
    # shape this hook exists alongside, committed inside the instrument
    # meant to measure it. Never return before the record is written.
    raw = ""
    parse_error = None
    try:
        raw = sys.stdin.read()
    except Exception as exc:          # noqa: BLE001
        parse_error = f"stdin read failed: {exc!r}"
    event = {}
    if parse_error is None and raw.strip():
        try:
            # lstrip the BOM: a piping shell can prepend one (PowerShell does),
            # and a probe that reports "not JSON" for a byte-order mark would
            # read as "the hook never fired" — a false negative in the very
            # instrument being trusted to answer that question.
            event = json.loads(raw.lstrip("﻿"))
        except Exception as exc:      # noqa: BLE001
            parse_error = f"stdin was not JSON: {exc!r}"

    role = (os.environ.get("EDP_ROLE") or "").strip().lower()
    # Phase 6 fix (2026-07-30): the launcher stamps EDP_HANDLE; nothing in
    # the repo ever set EDP_SPAWN_HANDLE — the 2026-07-25 probe RECORDED
    # exactly this ("EDP_SPAWN_HANDLE was NULL, so the guard as first
    # written could never have passed") and it was logged, not fixed. Read
    # the real variable first; keep the old name as a fallback.
    handle = (os.environ.get("EDP_HANDLE")
              or os.environ.get("EDP_SPAWN_HANDLE") or "").strip()
    spawn_sid = (os.environ.get("EDP_SPAWN_SESSION_ID") or "").strip()
    session_id = event.get("session_id") or ""
    armed = (os.environ.get("EDP_WORKER_CLOSE_NUDGE") or "").lower() in (
        "1", "true", "yes", "on")

    terminal = _action_is_terminal(handle)
    blocks = _blocks_for(session_id)

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "hook": event.get("hook_event_name"),
        "stop_reason": event.get("stop_reason"),
        "session_id": session_id,
        "cwd": event.get("cwd"),
        # THE MEASUREMENT THIS PROBE EXISTS FOR: is EDP_ROLE even set here?
        # If a spawned worker never appears in this log, `Stop` does not fire
        # in spawned shells and this whole approach needs a different seam.
        "edp_role": role or None,
        "edp_spawn_handle": handle or None,
        "edp_spawn_session_id": spawn_sid or None,
        "action_terminal": terminal,
        "prior_blocks": blocks,
        "armed": armed,
        "parse_error": parse_error,
        "raw_len": len(raw),
        # PROBE MEASUREMENT, 2026-07-25: the first run proved `Stop` DOES fire
        # in spawned shells (a curiosity shell logged here with EDP_ROLE set)
        # — but EDP_SPAWN_HANDLE was NULL, so the guard as first written could
        # never have passed. Capture every EDP_* var rather than guessing which
        # one carries the action, since guessing is what produced the hole.
        "edp_env": {k: v for k, v in os.environ.items()
                    if k.startswith("EDP_") and "TOKEN" not in k
                    and "KEY" not in k and "SECRET" not in k},
    }

    # ── the guard. EVERY clause must pass. ────────────────────────────────
    # role is exactly "worker"      — scope is a clean WORKER close only
    # the shell owns a handle       — otherwise we cannot check its work
    # its action IS terminal        — None (unknown) does NOT pass
    # under the block cap           — loop protection, no built-in exists
    should_nudge = (
        role == "worker"
        and bool(handle)
        and terminal is True
        and blocks < MAX_BLOCKS
    )
    record["should_nudge"] = should_nudge
    if role == "worker" and terminal is True and blocks >= MAX_BLOCKS:
        record["note"] = ("block cap reached — allowing the stop; this shell "
                          "ignored the nudge and is a different problem")
    _log(record)

    if armed and should_nudge:
        _bump(session_id)
        json.dump({
            "decision": "block",
            "reason": "worker work is recorded terminal but the shell is still open",
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
