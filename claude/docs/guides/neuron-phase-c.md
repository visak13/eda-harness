# Neuron — Phase C (spawn the planner)

You've declared outcomes. Now you declare steps and dispatch a
planner. Each step is a unit of work a planner shell will own end-
to-end.

The FSM emits `declare_step` while no steps exist. Once you add a
step with `execution="spawn_planner"`, the FSM advances to
`spawn_planner` (you call `pool_spawn_planner`) and then to Phase D
(wait + handle messages).

## Declaring steps

```
add_step(
  recipe_id=<rid>,
  description="<one focused unit of work — see sizing below>",
  execution="spawn_planner",   # for real work
  # execution="inline",        # ONLY for trivial one-liners you'd
                               # be embarrassed to spawn a planner for
  serves=["o1"],               # the outcome id(s) this step exists for
                               # (unknown ids refuse; orphan steps are
                               # refused under the v7 write gates)
  estimate={"tokens": 60000, "hours": 1.5},
  # G-EST (enforced): a spawn_planner step REFUSES without an estimate
  # — at least one of tokens/hours. Inline steps are exempt.
)
```

**Sizing a step — right-size before you decompose.** A step is what one
planner shell can hold in one context window of focus, and every
additional step buys durability/parallelism at a real price (a planner
spawn + N shells ≈ 10k+ orchestration tokens). **A goal that fits one
worker is ONE step** — decompose only when the work genuinely exceeds
one shell's focus, when parts must run in parallel, or when a boundary
carries its own risk/review need. Never split by phase label (scaffold /
implement / test / polish) — phases of one coherent build belong to ONE
planner, which sequences them as actions. Keep step descriptions
**specific and bounded**:

- ✅ "Build the single-round game: scaffold, round controller, scoring,
   client/server wiring, tests." (one worker's worth → one step)
- ❌ "Build the app." (too broad — the planner can't shape this)
- ❌ Scaffold / implement / test / polish as four steps of one small
   build. (phase-label split — orchestration cost, no isolation gain)
- ❌ "Rename one variable." (too small — inline it)

## Optional: drift check before dispatch

For non-trivial steps, re-read the recipe's `user_goal_verbatim`
(strategic) against the step's description (tactical) yourself before
spawning the planner, and surface a mismatch to the user rather than
dispatching through it. (The goal-keeper externality that scored this
is a DEAD role — deleted by owner ruling 2026-08-04.) Optional, not
enforced — trivial steps don't need it.

## Multi-step plans — declare the DAG, not a queue

You can call `add_step` multiple times to queue several. **Declare
independent steps WITH `depends_on`** — the dependency edges are what
let independent steps run their planners IN PARALLEL (DESIGN-v7 1.5.1).
A step with no `depends_on` is claiming "I can start now, alongside
anything else"; only a genuinely sequential step names its
predecessor(s). Each step's planner runs in its own shell.

Every step gets its own planner shell over the recipe's lifetime —
so the step count IS the orchestration bill. Multiple steps earn their
cost only when the boundaries are real (parallelism, distinct risk,
genuinely more than one shell's focus).

## Dispatching — the step-frontier WAVE is the default (DESIGN-v7 1.5.1)

Declare independent steps WITH `depends_on`, then fire the whole ready
frontier in ONE call and **spawn EVERY returned step**:

```
next_action(handle=<recipe_id>, handle_type="recipe", all_ready=true)
  → {kind: "dispatch_wave", actions: [<spawn_planner instr>…], capacity: N}
pool_spawn_planner(recipe_id=<rid>, step_id=<instr.args.step_id>)   # per instruction
```

Spawn in `dispatch_order`, up to the payload's `capacity` (the pool's
planner headroom, `EDP_MAX_PLANNERS` − live planners; `capacity=null`
means the probe failed — spawn and let the pool's cap refuse). Steps
past capacity stay stamped `in_progress`; the next wave/reconcile picks
them up as slots free. The wave fires from BOTH `planning` and
`executing` — a step that becomes newly ready while others run is
dispatched by your next wave call, without waiting for the recipe to
drain. A PARKED planner's step is never re-surfaced (it still owns its
handle; the pool resumes it, not you).

The single-step form (`next_action` without `all_ready`, obey its
`spawn_planner`) remains the fallback for an empty wave or an
`execution="inline"` step (inline steps are never wave slots — they run
in YOUR context).

The pool returns the spawned session_id; you don't need to track it.
Once dispatched, the recipe is `executing` and `next_action` returns
`wait` — you're now in Phase D.

## If a spawn fails — the pool self-heals; you NEVER Bash-repair

Claude Code's auto-updater can intermittently leave `bin\claude.exe` a
truncated ~500-byte stub (with leftover `.claude*-TEMP` npm shims),
which breaks every subsequent pool spawn. **This is not yours to fix by
hand.** The pool runs a **pre-spawn health check and auto-repairs the
binary itself** (copies the platform binary from the versions cache,
renames the TEMP shims) before it launches a shell — no restart needed —
and stamps `DISABLE_AUTOUPDATER=1` on every spawned shell so a
mid-flight auto-update can't break a running planner/worker.

If auto-repair can't recover, `pool_spawn_planner` **refuses** with a
`_precondition`-style error naming the fix: the operator runs
`python -m edp_pool.doctor` (binary check/repair, broker/pool health
pings, Phoenix reachability, stale-lock sweep — the one command that
replaces ad-hoc ops archaeology; also a panel button). Your job is to
**relay that refusal to the user (or let the panel notification do it)**
— **never** run `claude.exe` update / reinstall / repair commands in
Bash yourself. That hand-repair is the recurring Opus-waste trap this
guard exists to kill; the neuron does not fix the environment.

## Anti-patterns

- **Lumping a genuinely multi-shell goal into one step.** A 4-hour
  planner is a planner that lost its way mid-context. Decompose when
  the work truly exceeds one shell's focus — but remember the inverse
  is the commoner failure: a one-worker goal split into phase-labelled
  steps multiplies cost without adding isolation.
- **`execution="inline"` for substantive work.** Inline runs in YOUR
  context. If the step is more than ~5 minutes' work, it belongs in
  a planner.
- **Naming steps after outputs ("the report") rather than work
  ("write the report").** The planner reads the step description as
  its goal; phrase it as a goal, not a noun.
- **Adding all 5 steps up front when you don't yet know step 4 + 5's
  shape.** Add what you know; add more as the recipe progresses
  (the FSM accommodates new steps mid-recipe).
