# Planner — Dynamic coordination (re-planning the DAG mid-flight)

Load via `get_guide("planner-dynamic-coordination")` when execution
discoveries invalidate the DAG you authored: evidence proves an action
unnecessary, a review finding splits one action into three, a
dependency you drew doesn't exist (or one you didn't draw does). The
authored plan is a hypothesis about the work; revise it **in place** —
the FSM is shape-agnostic, so a plan that ends looking nothing like
the one you authored is a plan that LEARNED, not one that failed.

## The mutation verbs (all on your surface)

- **Add discovered work:** `add_action(plan_id=..., action_id=...,
  description=..., depends_on=[...], acceptance_kind=...,
  verify={...})` — same authoring discipline as planner-phase-author
  (real deps, a real `verify`, `leg_kind`, review
  coverage). A discovered action is not exempt from the standards the
  authored ones met.
- **Rewire dependencies / heal briefs:** `update_object(type="action",
  ids={"plan_id": ..., "action_id": ...}, patch={"depends_on": [...]})`
  — same call shape for a stale `description` or a wrong `verify`
  block (allowed while dispatching; the shells re-run whatever is
  stamped).
- **Delete obsolete work:** `delete_object(type="action", ids={...},
  reason="superseded by a4")` — a REAL reason; it lands in the audit
  trail. Risky-but-legal deletes proceed with advisories (dependents
  auto-rewritten); genuinely unsafe ones are refused — an
  `in_progress` action under a LIVE shell is steered or reaped first,
  never deleted out from under its worker (enforced).

## After every mutation: re-fire the wave

A DAG edit changes what is ready. Immediately re-fire
`next_action(handle=<plan_id>, handle_type="plan", all_ready=true)`
and dispatch the returned frontier — never hand-compute readiness. The
standing guards keep this safe: `depends_on` gating, the
liveness-gated duplicate-dispatch guard in `pool_spawn_worker`
(enforced), and the rule that in-flight workers are steered, not
edited — mutating an action a live worker is executing changes nothing
in its shell.

## Keep the record honest while you steer

- Every structural revision gets a one-line why:
  `emit_recipe_event(kind="learning", ...)` naming what the evidence
  showed and what you changed. A silently mutated DAG is unreviewable.
- Ground revisions in evidence, not vibes: `read_worklog(...)` /
  `read_object(...)` on the surprising result, THEN rewire.

## When to STOP stretching the plan — hand back instead

The boundary is **your step's goal**. Amend freely while every change
serves it; hand the step back with `ask_above(...)` when:

- **The goal itself moved** — the step as scoped is the wrong step
  (wrong deliverable, invalidated assumption, an outcome needing
  re-negotiation). Recipe-map territory; the neuron owns it.
- **The work has outgrown one plan** — your revisions are recreating a
  second step inside this one. Steps are the neuron's unit; propose
  the split upward.
- **A revision would contradict a load-bearing decision or
  constraint** recorded in the recipe. You don't overrule the recipe
  from inside a plan.
- **You are on your third rewire of the same region** — thrash means
  the grounding was wrong, not that the DAG needs a fourth try.

Send the `ask_above` with the evidence: what you authored, what the
work showed, the options you see. "Stop and ask" is a coordination
move, not a failure.

## Anti-patterns

- Pushing a stale plan to completion because it was authored.
- Re-authoring the whole plan when three targeted mutations would do.
- Mutating and not re-firing the wave — an unblocked frontier sitting
  idle is silent wall-clock loss.
- Stretching the step past its goal instead of handing it back. The
  DAG flexes; the step's goal does not.
