# §5.5 IMPACT — wake reconcile fix (post-HITL, 2026-05-20)

Change to **built** components #2 (claude). Driven by the live HITL
trace `scratch/neuron-session-debug-f8aeb2.md`: the deliverable was
produced + verified on disk, but the recipe wedged in `executing`
forever — `next_action(recipe)` returned `wait` indefinitely.

## Root cause (verified in code, not the log's hypothesis)
The log blamed "no plan registered / colon-vs-dash handle". Wrong — the
plan WAS registered (`.plans/<rid>-s1/` worklog drafted→terminal). The
real cause, two layers:

1. **Address mismatch (bug I introduced this session).**
   `_tools.py:120` `_advance_executing` reconciles by
   `broker.poll(r.recipe_id)`. `stub_broker.send` files by literal
   `msg.to`; `poll` is a literal dict lookup (no alias resolution). My
   `agentic-plan.md` rewrite told the planner
   `broker_send(to="my-neuron", kind="plan_closed")`. `"my-neuron"` ≠
   `recipe_id` → the closure landed in a dead-letter inbox nothing
   polls. WALK-1 stayed green because the test sends `to=rid` directly
   (never exercises activator prose); my guard test asserted
   `"my-neuron" in body` — it locked the bug in.

2. **DESIGN-v5 violation (latent, pre-existing).**
   `_advance_executing` reconciles ONLY from one broker message. It
   never inspects the plan's terminal state on disk. A planner that
   exits between "plan terminal" and `broker_send` wedges the recipe
   permanently — control flow resting on a single miss-able event,
   exactly the disease v5 forbids.

## Fix
- **F1 (address):** planner derives `recipe_id` from `EDP_HANDLE`
  (everything before the last `:`) and sends
  `broker_send(to=<recipe_id>, kind="plan_closed",
  body={"plan_id": <plan_id>})`. Update `agentic-plan.md`,
  `HLD-LLD.md`, and the guard test to assert the recipe_id derivation
  (NOT the literal `"my-neuron"`).
- **F2 (disk = the guarantee, broker = the fast path):**
  `_advance_executing` — after the broker check, if the in-flight
  `spawn_planner` step has NOT advanced, load its plan from disk
  (`plan_id = f"{recipe_id}-{step_id}"`, the documented convention) and
  if `plan.state == PlanState.TERMINAL`, advance the step + recipe →
  PLANNING. Deterministic; survives a planner that died before/without
  emitting `plan_closed`. The broker message remains the low-latency
  path; disk-terminal is the can't-miss backstop.

## Blast radius
- `_tools.py` — `_advance_executing` (+disk fallback; `PlanState`
  import). FSM (`recipe_fsm.py`) UNTOUCHED — it still returns bare WAIT;
  reconciliation stays in the tool (IO out of the pure FSM).
- `agentic-plan.md`, `HLD-LLD.md` — recipient is the recipe_id.
- Tests — guard test asserts recipe_id derivation; new tests:
  (a) plan_closed to recipe_id advances; (b) NO broker msg + terminal
  plan on disk advances (the F2 backstop); (c) non-terminal plan on
  disk still waits.
- contracts/broker/pool — UNTOUCHED.

## Unwedges the live recipe
With F2, the stuck `recipe-…-f8aeb2` self-heals: its plan snapshot is
`terminal/succeeded` on disk, so the next `next_action(recipe)` tick
advances it to PLANNING → REVIEWING → honest close. No manual surgery.

## Convention dependency (noted, accepted)
F2's disk lookup uses `plan_id == f"{recipe_id}-{step_id}"` — the
convention `agentic-plan.md` mandates and this run honoured. A
`PlanStore.find_by(recipe_id, step_id)` scan is more robust but adds a
store method; deferred (`# TODO(plan-lookup-by-step)`), convention is
deterministic and enforced by the activator for now.

## Verdict
F1 is a straight bug fix. F2 is mandated by DESIGN-v5 (not a
preference) and is what makes wake actually deterministic. Proceed to
code; re-run the same HITL goal to confirm the recipe closes.
