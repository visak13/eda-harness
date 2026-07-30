"""Canonical state machines exposed as DATA (FSM-RESPONSIBILITY.md Step 1).

The recipe/plan/action progressions are deterministic, enum-typed state
machines. Exposing their legal transitions to the LLM (via
describe_objects) makes the correct progression part of the OBJECT TYPE
— not behaviour hidden inside next_action. The LLM then mutates state
correctly because the type tells it which moves are legal, instead of
re-deriving (and fumbling) the progression.

These maps MIRROR the transitions the FSM (recipe_fsm / plan_fsm) and the
verify gate (record_action_status) actually drive — keep them in sync if
the FSM changes. This module is pure data: no behaviour, no enforcement
added here (the verify gate stays the load-bearing rule).
"""

# ── recipe.state — the goal lifecycle (recipe_fsm.recipe_next_action) ──────
RECIPE_STATES: dict[str, str] = {
    "created": "just created; carries the verbatim goal + domain",
    "comprehending": "reasoning; declaring expected_outcomes then steps",
    "planning": "selecting the next dependency-ready step to dispatch",
    "executing": "a planner is in flight for a step (WAIT)",
    "reviewing": "all steps dispatched; computing the honest terminal",
    "closed": "terminal (succeeded / partial / failed / abandoned)",
}
RECIPE_TRANSITIONS: dict[str, list[str]] = {
    "created": ["comprehending"],
    "comprehending": ["planning"],
    "planning": ["executing", "reviewing"],
    "executing": ["planning"],            # reconcile: step done OR crash re-dispatch
    "reviewing": ["planning", "closed"],  # a newly-ready step reopens; else close
    "closed": [],                         # terminal
}

# ── plan.state — the plan lifecycle (plan_fsm.plan_next_action) ────────────
PLAN_STATES: dict[str, str] = {
    "drafted": "actions being authored",
    "dispatching": "dispatching dep-ready actions; waiting on any in-flight",
    "acceptance_review": "all actions terminal; resolving terminal_status",
    "terminal": "succeeded / partial / failed",
}
PLAN_TRANSITIONS: dict[str, list[str]] = {
    "drafted": ["dispatching"],
    "dispatching": ["acceptance_review"],
    # P3 advisory FSM (2026-06-10): add_action may REOPEN a plan awaiting
    # its terminal verdict back to dispatching (advisory-recorded) — the
    # alternative was agents recording a whole new plan for one action.
    "acceptance_review": ["terminal", "dispatching"],
    "terminal": [],                       # terminal
}

# ── action.status — the work-unit lifecycle (record_action_status gate) ────
ACTION_STATES: dict[str, str] = {
    "pending": "not yet dispatched (dependencies may be unmet)",
    "in_progress": "dispatched; a worker holds the lock",
    # DECLARED BUT NEVER WRITTEN BY CODE (see the note below). Kept legal because
    # the FSM still READS it (a `verify` action counts as stuck) and a planner may
    # still park one by hand.
    "verify": "a done-CLAIM parked for re-checking (NOT done, NOT failed). "
              "NOTHING transitions into this — see ACTION_TRANSITIONS",
    "done": "complete; evidence required (the CLAIM lands as done — d30)",
    "failed": "abandoned as not completable",
    "skipped": "deliberately not done",
    "needs_review": "flagged for human / critic review — a planner sets this "
                    "deliberately; no code transitions into it",
}

# ── what actually WRITES a status (d30), vs what is merely LEGAL ───────────
# The only status the engine ever ASSIGNS is `in_progress`, stamped at dispatch.
# Everything else is written by a SHELL through record_action_status /
# update_object. In particular `verify` and `needs_review` are DECLARED-BUT-
# NEVER-WRITTEN: no code path in src/ assigns either.
#
# `verify` is a vestige of the framework acceptance gate that d30 DELETED.
# record_action_status is now a PURE WRITE — it runs no command and no file/glob
# check — so there is no gate to pass, and therefore nothing to park. An earlier
# version of this comment read "done-claim runs the verify gate: pass -> done,
# fail -> parked in verify", which described machinery that no longer exists.
# Acceptance is DUAL-GATE and both gates are SHELLS: the WORKER runs every
# acceptance.verify criterion in its own shell, and the REVIEWER leg independently
# re-runs it in a fresh one — that re-run IS the objective gate. A recorded `done`
# is a CLAIM and it LANDS as `done`; nothing holds it back.
#
# These states are INERT, not dead: keep them legal (the FSM reads `verify` when
# detecting a stuck action, and a planner may set either by hand), but do not infer
# from this table that any gate parks work there. NOTHING DOES.
ACTION_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["in_progress", "skipped"],
    # pending = crash reset (reconcile re-dispatches a dead worker's action).
    "in_progress": ["verify", "done", "failed", "pending"],
    "verify": ["done", "failed"],          # re-record after fixing deliverable/gate
    "needs_review": ["done", "failed"],
    "done": [], "failed": [], "skipped": [],   # terminal
}


def render_state_machine(states: dict[str, str],
                         transitions: dict[str, list[str]]) -> str:
    """Render a state machine as a compact, LLM-readable block: each
    state, its meaning, and the legal next states (→ … = terminal when
    empty)."""
    lines = []
    for name, meaning in states.items():
        nxt = transitions.get(name, [])
        arrow = " -> " + ", ".join(nxt) if nxt else " -> (terminal)"
        lines.append(f"  {name}{arrow}\n      {meaning}")
    return "\n".join(lines)


# Object-type → its state machine (consumed by describe_objects).
STATE_MACHINES: dict[str, tuple[dict, dict]] = {
    "recipe": (RECIPE_STATES, RECIPE_TRANSITIONS),
    "plan": (PLAN_STATES, PLAN_TRANSITIONS),
    "action": (ACTION_STATES, ACTION_TRANSITIONS),
}


# ── PACING policy (DESIGN-v6 W7 item 1) — server-driven self-paced cadence ──
# A plain data table, sitting BESIDE the state machines above (ROLE_TOOLSETS /
# tables-as-data style): pacing STATE → (wait_hint_MINUTES, wait_reason). There
# is NO logic here — the classifier that maps a live recipe/plan to one of these
# states lives in the FSMs (recipe_fsm.recipe_pacing_state,
# plan_fsm.plan_pacing_state / handle_pacing_state), and the (minutes, reason)
# is surfaced onto next_action / reconcile / status_ping via pacing_hint().
# Principle 6: no LLM anywhere near this — it is deterministic table lookup.
PACING: dict[str, tuple[int, str]] = {  # state -> (hint_minutes, reason)
    "child_in_progress_recent_output": (10, "heads-down; leave alone"),
    "child_in_progress_stale_output":  (2,  "probe: status_ping -> inspect_worker"),
    "verify_pending":                  (1,  "acceptance imminent"),
    "awaiting_user":                   (30, "nothing moves without the user"),
    "idle_or_done":                    (30, "wrap-up cadence"),
}

# A child whose last worklog output is older than this many seconds reads as
# "stale" and flips the pacing state from heads-down (10 min) to probe (2 min).
# Env-overridable (EDP_STALE_OUTPUT_SECS, read in _tools.py). Item 2 (pool-side
# last_output_ts) will refine the SOURCE of that ts, not this threshold.
STALE_OUTPUT_SECS_DEFAULT = 600  # 10 min


def pacing_hint(state: str) -> tuple[int, str]:
    """(wait_hint_minutes, wait_reason) for a pacing state — the single lookup
    every surface (next_action / reconcile / status_ping) goes through. An
    unrecognised state falls back to the idle wrap-up cadence so an unexpected
    key can never crash a heartbeat."""
    return PACING.get(state, PACING["idle_or_done"])
