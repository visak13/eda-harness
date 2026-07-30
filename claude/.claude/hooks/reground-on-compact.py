#!/usr/bin/env python3
"""SessionStart hook — re-ground a freshly-COMPACTED shell (DESIGN-v6 W13).

When Claude Code compacts a session's context (auto-compact or the manual
`/compact`), the shell wakes with its grounding thinned out: the W1 recipe
digest and W2 Monitor wiring it built at cold-start may no longer be in
context. This hook fires automatically on that event and nudges the shell to
RE-GROUND on its very next turn.

Contract (confirmed against the live Claude Code hooks docs by action a1):
the SessionStart hook receives one JSON object on stdin carrying a `source`
field whose value is one of `startup` / `resume` / `clear` / `compact`. This
hook fires ONLY when `source == 'compact'`; for every other source (and any
malformed / unreadable input) it is a clean NO-OP — prints nothing, exits 0,
leaving session start exactly as it is today. On the compact case it prints a
structured SessionStart `additionalContext` block (honored on compact) that is
injected before the shell's first post-compaction prompt.

COMPOSE, do not duplicate (d36 / principle-6 / principle-6-O(1)):
  - The hook does NOT re-implement or emit the recipe digest, and does NOT run
    an LLM or fire a slash command. It emits only a small BOUNDED banner that
    DIRECTS the shell's next reconcile-loop turn to call
    `next_action(reground=true)` — the existing, code-assembled (no-LLM)
    re-ground path (`_reground_payload`) that the neuron/planner reconcile
    loop already calls on wake. That call pulls the full W1 digest + banner +
    W2 monitor-rewire block from the ONE source of truth. So the payload here
    stays O(1): a fixed-size directive, never recipe-size output.
  - The step-count-gap backstop (recipe_fsm.py, grew_steps>=2) is untouched
    and remains the secondary safety net if this hook is ever absent.

FAIL-SAFE is mandatory: a SessionStart hook must NEVER break session start.
Any exception collapses into a clean no-op (exit 0, no output). Kept
dependency-free + tiny so it adds negligible latency to session start."""
import json
import sys

# The bounded re-ground directive injected as additionalContext on compact.
# Fixed size (O(1)) — it carries NO digest itself; it points the shell at the
# existing next_action(reground=true) path, which assembles the real payload.
_BANNER = (
    "CONTEXT WAS JUST COMPACTED — your grounding may be thinned out. Before "
    "acting on anything else, your VERY NEXT reconcile-loop turn must call "
    "next_action(reground=true) (neuron/planner: pass your recipe/plan "
    "handle). That returns the full W1 recipe digest + banner + W2 monitor "
    "rewire block from the single source of truth — read the "
    "changes_since_your_last_ground delta first, re-arm your Monitor wiring "
    "+ reconcile-loop heartbeat from the `rewire` block, and RE-LOAD the "
    "role CONTRACT CARD named in the `reload_role_guides` block (Phase 5: "
    "the card, <=100 lines, replaced the old orchestrator-launch + "
    "neuron-phase full-guide reload — pull those on demand only when the "
    "card points at them) BEFORE continuing to drive the FSM. Do not "
    "narrate this re-grounding; execute it. (A worker shell that does not "
    "run a reconcile loop can ignore this — check_inbox and continue your "
    "one action.)")


def reground_context(data: dict) -> str | None:
    """Return the additionalContext string to inject IFF this SessionStart
    fired for a compaction (`source == 'compact'`), else None (no-op for
    startup / resume / clear / anything unexpected). Pure + importable for
    tests."""
    if not isinstance(data, dict):
        return None
    if (data.get("source") or "") != "compact":
        return None
    return _BANNER


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 — unreadable input → clean no-op
        return 0
    try:
        additional = reground_context(data)
        if additional is None:
            return 0  # not a compaction (or bad input) → leave startup as-is
        print(json.dumps({"hookSpecificOutput": {  # noqa: T201 — stdout IS
            # the hook interface: the harness reads this SessionStart block and
            # injects additionalContext before the first post-compaction prompt.
            "hookEventName": "SessionStart",
            "additionalContext": additional,
        }}))
        return 0
    except Exception:  # noqa: BLE001 — FAIL-SAFE: never break session start.
        return 0


if __name__ == "__main__":
    sys.exit(main())
