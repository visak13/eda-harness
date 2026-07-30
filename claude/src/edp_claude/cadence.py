"""Canonical loop-and-heartbeat cadence config + cron-prompt strings.

DESIGN-v6 W7 (items 4 + 6). One stable, lightweight, dependency-free home
for the reconcile-loop cadence knobs AND the canonical cron-prompt string,
so every layer (the FSM tools here, and W2's later rewire hand-back block)
imports the SAME source of truth instead of re-spelling it.

Principle 6 (no LLM-in-tool) + d7/d8: these are deterministic constants —
no model discretion, no server-side generation of a per-recipe prompt.

--------------------------------------------------------------------------
The ScheduleWakeup-long-prompt pattern is RETIRED at the code level.
--------------------------------------------------------------------------
The old anti-pattern armed the heartbeat cron with a long, per-recipe
prompt (often the verbatim goal). That is banned. The invariant is
"the cron prompt is NEVER the verbatim goal" — NOT "one prompt for all
roles". A wake fires a short, role-appropriate REFLEX; the recipe/plan
state (not the cron string) carries the goal. ScheduleWakeup is a
client-side tool, so no server-side guard can enforce this; enforcement is
that this module is the SINGLE source of the canonical string and no stale
long-prompt cron literal survives in the code paths that reference it.

Role scoping (the invariant, DESIGN-v6 lines 383/389):

* neuron + planner  → RECONCILE_LOOP_CRON_PROMPT (below). They drive the
  recipe/plan via reconcile → next_action and obey the returned wait_hint.
* worker + curiosity → keep their EXISTING check_inbox-based Step-0
  prompts VERBATIM (worker.md Step 0, curiosity.md Step 0). They do NOT
  call reconcile/next_action, so they do NOT use this constant.
"""

import os

# ── Canonical RECONCILE-LOOP cron prompt (neuron + planner ONLY) ───────────
# Exact value is load-bearing (DESIGN-v6 lines 383, 389 + W2's rewire block
# imports it verbatim). Do NOT reword — it is asserted char-for-char by
# tests/test_w7_canonical_prompt.py.
RECONCILE_LOOP_CRON_PROMPT = (
    "call reconcile then next_action and obey wait_hint: "
    "if it says wait, end your turn"
)

# Roles that arm their heartbeat with RECONCILE_LOOP_CRON_PROMPT. Worker and
# curiosity are deliberately absent — they keep their check_inbox prompts.
RECONCILE_LOOP_ROLES = ("neuron", "planner")


# ── Cadence knobs (env-overridable; the shared reconcile-loop config) ──────
EDP_HEARTBEAT_SECS_ENV = "EDP_HEARTBEAT_SECS"
# RENAMED 2026-07-10 (backlog item 11). Was EDP_WAIT_ESCALATE_CYCLES, a count
# of consecutive next_action TICKS. Patience is now WALL-CLOCK, so the knob is
# a MULTIPLIER over the pacing state's expected duration, never a tick count.
# The old name is deliberately NOT accepted as an alias: a knob that keeps its
# spelling while changing its meaning is a trap for the next reader, and
# nothing outside this repo set it.
EDP_WAIT_ESCALATE_MULTIPLIER_ENV = "EDP_WAIT_ESCALATE_MULTIPLIER"
# Absolute wall-clock override; when set it wins over the derived threshold.
EDP_WAIT_ESCALATE_SECS_ENV = "EDP_WAIT_ESCALATE_SECS"

# 30 minutes, RAISED FROM 60s on 2026-07-25 (operator ruling).
#
# The old 60s default treated the heartbeat as the safety net for a stalled
# child. It is not, and never was: the cron exists as a BACKSTOP for a lost
# push, while the event plane is the primary wake. Using cadence to detect a
# stall costs a poll every minute forever and STILL leaves a window, because
# the thing it is looking for is an ABSENCE.
#
# The real fix is on the event plane — an orphaned-action EDGE (see
# `reactive/runtime.py`) rather than a level nobody emits when a shell exits.
# With that edge armed, a tight cron buys nothing, so the default widens and
# the observation budget goes to the shells doing work.
#
# Override with EDP_HEARTBEAT_SECS if a specific deployment wants it tighter.
_DEFAULT_HEARTBEAT_SECS = 1800
_DEFAULT_WAIT_ESCALATE_MULTIPLIER = 3
# Floor on the derived threshold: a 1-minute pacing hint must not make the
# escalation hair-trigger on a fast loop.
_MIN_WAIT_ESCALATE_SECS = 60


def heartbeat_secs() -> int:
    """Heartbeat cadence in seconds (env override, safe default)."""
    try:
        return int(os.environ.get(EDP_HEARTBEAT_SECS_ENV,
                                  str(_DEFAULT_HEARTBEAT_SECS)))
    except ValueError:
        return _DEFAULT_HEARTBEAT_SECS


def wait_escalate_multiplier() -> int:
    """How many expected-durations of NO PROGRESS we tolerate before a wait
    escalates upward. A multiplier, not a tick count (see the env-name note)."""
    try:
        return int(os.environ.get(EDP_WAIT_ESCALATE_MULTIPLIER_ENV,
                                  str(_DEFAULT_WAIT_ESCALATE_MULTIPLIER)))
    except ValueError:
        return _DEFAULT_WAIT_ESCALATE_MULTIPLIER


def wait_escalate_secs(expected_secs: int) -> int:
    """WALL-CLOCK patience, in seconds, before a silent wait escalates.

    Backlog item 11. Escalation used to count next_action ticks, which made the
    real patience a function of the caller's cron interval rather than of the
    work being waited on: with a 10-second `wait_hint` and a 30-minute
    heartbeat, "3 cycles" meant ~90 minutes, not 30 seconds. Worse, the two
    knobs moved in opposite directions — W7's own self-pacing widens the tick,
    which silently rescales a tick-counted patience.

    Deriving the threshold from `expected_secs` (the pacing state's own
    `wait_hint`, in seconds) cuts the tick out of the equation entirely: how
    OFTEN the loop looks can no longer change WHEN it escalates.
    """
    raw = os.environ.get(EDP_WAIT_ESCALATE_SECS_ENV, "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    derived = wait_escalate_multiplier() * max(0, expected_secs)
    return max(_MIN_WAIT_ESCALATE_SECS, derived)
