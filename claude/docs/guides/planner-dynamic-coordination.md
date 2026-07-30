# Planner — Dynamic coordination (re-planning the DAG mid-flight)

Load via `get_guide("planner-dynamic-coordination")` when execution
discoveries invalidate the DAG you authored: a worker's evidence proves
an action unnecessary, a review finding splits one action into three, a
dependency you drew turns out not to exist (or one you didn't draw
does). The authored plan is a hypothesis about the work; this guide is
how you revise it **in place** — the FSM is shape-agnostic, so a plan
that ends looking nothing like the one you authored is a plan that
LEARNED, not a plan that failed.

Some work is a fixed circuit — input → output, the shape known up
front. Some work is driving a car: you steer continuously off what the
road shows you. Both run on the same engine (`depends_on` + the ready
wave); this mode just mutates the DAG between waves.

## The mutation verbs (all live on your surface)

**Add work you discovered:**
`add_action(plan_id=..., action_id=..., description=...,
depends_on=[...], acceptance_kind=..., verify={...})` — same authoring
discipline as planner-phase-author (real deps, a real `verify`,
`task_class`, review coverage). A discovered action is not exempt from
the standards the authored ones met.

**Rewire dependencies:**
`update_object(type="action", ids={"plan_id": ..., "action_id": ...},
patch={"depends_on": [...]})` — point an existing action at its REAL
prerequisites. Use the same call shape to heal a stale `description` or
correct a wrong `verify` block (allowed while dispatching — the
worker/reviewer re-run whatever is stamped).

**Delete obsolete work:**
`delete_object(type="action", ids={"plan_id": ..., "action_id": ...},
reason="superseded by a4")` — for work that is genuinely obsolete
(superseded scope, a wrongly authored action). Give a REAL reason; it
lands in the audit trail. Risky-but-legal deletes proceed with
advisories (dependents' `depends_on` auto-rewritten); genuinely unsafe
ones are refused — an `in_progress` action under a LIVE shell must be
steered or reaped first, never deleted out from under its worker.

## After every mutation: re-fire the wave

A DAG edit changes what is ready. Immediately re-fire:

    next_action(handle=<plan_id>, handle_type="plan", all_ready=true)

and dispatch every returned ready action (`pool_spawn_worker` per
action, or one spawn per batch head — planner-phase-drive.md carries
the loop). Do not hand-compute readiness after a rewire; the wave is
the authority on what your edit unblocked.

The standing guards keep mid-flight edits safe — rely on them:

- **`depends_on` gating** — a rewired action dispatches only when its
  new deps are satisfied.
- **The liveness-gated duplicate-dispatch guard** — `pool_spawn_worker`
  refuses an action that is already delivered or has a live worker, so
  a re-fired wave never double-spawns work already underway.
- **In-flight workers are steered, not edited.** Mutating an action a
  live worker is executing changes nothing in its shell. Steer it, or
  reap it and re-author.

## Keep the record honest while you steer

- Every structural revision gets a one-line why:
  `emit_recipe_event(kind="learning", ...)` (or a worklog note) naming
  what the evidence showed and what you changed. A silently mutated DAG
  is unreviewable.
- Ground revisions in evidence, not vibes: `read_worklog(...)` /
  `read_object(...)` on the action whose result surprised you, THEN
  rewire.

## When to STOP stretching the plan — hand back instead

Re-planning has a boundary: **your step's goal**. Amend the DAG freely
while every change still serves the step goal you grounded on. Hand
the step back to the neuron with `ask_above(...)` — do NOT keep
stretching — when:

- **The goal itself moved.** The discovery means the step as scoped is
  the wrong step (wrong deliverable, invalidated assumption the neuron
  grounded you on, an outcome that now needs re-negotiating with the
  user). That is recipe-map territory — the neuron owns it.
- **The work has outgrown one plan.** Your revisions are recreating a
  second step inside this one (a distinct deliverable with its own
  review structure). Steps are the neuron's unit; propose the split
  upward rather than smuggling it into your DAG.
- **A revision would contradict a load-bearing decision or constraint**
  recorded in the recipe. You don't overrule the recipe from inside a
  plan.
- **You are on your third rewire of the same region.** Thrash is a
  signal the grounding was wrong, not that the DAG needs a fourth try.

Send the `ask_above` with the evidence attached: what you authored,
what the work showed, the options you see. "Stop and ask" is a
coordination move, not a failure.

## Anti-patterns

- **Pushing a stale plan to completion** because it was authored —
  finishing actions the evidence already obsoleted.
- **Re-authoring the whole plan** (or a new plan) when three targeted
  mutations would do. Amend in place; history stays attached.
- **Mutating and not re-firing the wave** — an unblocked frontier
  sitting idle is silent wall-clock loss.
- **Stretching the step past its goal** instead of handing it back to
  the neuron. The DAG flexes; the step's goal does not.
