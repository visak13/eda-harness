# What next_action / the FSM actually achieves (read before touching it)

Status: **IMPLEMENTED** (2026-05-30). Steps 1–4 below are built + tested.
Written because a proposed "decouple next_action" change was loose — it
would have moved deterministic state progression into LLM reasoning,
destroying the FSM's reason to exist. This doc pins down the FSM's
responsibility at depth, then the determinism-preserving decoupling.

As-built:
- **Step 1** — state machines exposed as data: `fsm/state_machines.py`
  (RECIPE/PLAN/ACTION states + legal transitions); rendered by
  `describe_objects('recipe'/'plan'/'action')`.
- **Step 2** — observe→act guide: `docs/guides/reactive-streams.md`
  (each rx event → its deterministic response, with `reconcile` as the
  sync step).
- **Step 3** — `reconcile` tool extracted from `next_action`
  (`tools/_tools.py`): `next_action` is now a PURE phase pacer (zero
  IO); `reconcile` owns the broker/pool/disk sync (same logic). Loop:
  react (rx) → reconcile → next_action; heartbeat runs reconcile+
  next_action as the backstop. Briefs + cron prompts updated.
- **Step 4** — determinism re-validated: `test_reconcile_decouple.py`
  proves next_action-alone no longer advances on a plan_closed, and
  reconcile+next_action reproduce the old progression; all FSM/crash/
  reconcile/walkthrough/integration tests migrated to the two-step flow
  and pass.

## The problem the FSM solves: the LLM, left free, fails predictably

A neuron/planner driven by raw LLM reasoning fails in *specific,
repeatable* ways:
- skips comprehension and jumps to work;
- doesn't spawn a planner — starts doing the work itself;
- never closes the recipe (or closes it falsely as "done");
- doesn't set up bi-directional comms;
- regenerates a whole plan/recipe JSON to make a small change → burns
  ~30k tokens and *then* discovers it mis-escaped a string.

`next_action` removes these failure modes by taking the decision **out of
LLM reasoning** and encoding the correct progression **deterministically**.
That determinism — not intelligence — is its entire value. It has no
intelligence: on a crash it polls liveness instead of reading the
worklog; it can't actively wake a shell (the per-shell cron does that).

## The FSM's deterministic responsibilities (enumerated from the code)

**(A) PHASE SEQUENCING — "don't get lost."** A pure function of stored
state → the next legal move:
- Recipe: `CREATED → COMPREHENDING →` (REASON until ≥1 expected_outcome)
  `→` (DECLARE_STEP until ≥1 step) `→ PLANNING →` (SPAWN_PLANNER per
  dependency-ready step) `→ EXECUTING →` (WAIT) `→ REVIEWING → DONE`.
- Plan: `DRAFTED →` (REPLAN if no actions) `→ DISPATCHING →`
  (DISPATCH_ACTION per dep-ready action) `→` (WAIT while any non-terminal)
  `→ ACCEPTANCE_REVIEW → TERMINAL → DONE`.
This is the rail that stops the LLM skipping comprehension / not
spawning / not closing.

**(B) INCREMENTAL STATE MUTATION — "don't burn 30k tokens."** State
changes are small atomic ops via intent tools, never whole-document
regeneration: mark a step `in_progress` *at dispatch* (so it isn't
re-selected), advance an action `pending → in_progress → verify → done`,
append an outcome/decision. The LLM never re-emits the plan JSON, so it
never fumbles escaping. **This already lives on the object surface** —
`update_object`/`create_object` delegate to these intent tools.

**(C) ENUM-CONSTRAINED LEGAL TRANSITIONS — determinism encoded in TYPES.**
`action.status`, `recipe.state`, `plan.state` are fixed-state enums;
`record_action_status` still enforces `done`-requires-evidence (it refuses a
`done` with no evidence), but under **d30 it is a PURE WRITE** — it runs NO
acceptance check and NO LONGER parks failures in `verify`; a done-claim lands
directly as `done` (worker-done-awaiting-review) and the `needs_review` +
worker→reviewer chain is the gate before the step closes. Illegal transitions
are rejected. The progression is correct because the *type* constrains it, not
because the LLM reasoned it.

**(D) HONEST TERMINAL — never lie "done."** `succeeded` only if outcomes
were declared AND met; otherwise `partial`. Computed deterministically.

## What next_action does that is NOT determinism: the stopgaps

**(E) RECONCILIATION (no intelligence — polling).** Inside `next_action`:
- `_advance_executing` → polls broker for `plan_closed`, reads the plan
  file for terminal, polls pool for planner liveness → marks the step
  done / re-dispatches on crash.
- `_advance_plan_liveness` → polls pool for worker liveness → crash
  recovery.
- `_refresh_comprehension` → polls broker for curiosity-clear.
These are dumb polling stopgaps: crash detection by liveness poll (never
reads the worklog), no active wake (the cron/rx does that), no reasoning
about *why* something died.

## The key realization (where my earlier proposal was wrong)

A, B, C, D are **genuine determinism that MUST be preserved**. My loose
proposal ("move reconciliation to the neuron reacting via CRUD") sounded
like "hope the LLM reasons the state change correctly" — which would
destroy it.

But look closer at (E): the *action* reconciliation ultimately takes —
"mark the step done", "reset a crashed action to pending" — is itself a
**deterministic object mutation** (`record_step_result`,
`record_action_status`). So decoupling (E) does NOT mean the LLM reasons
out the mutation. It means:
- **rx provides the intelligence to NOTICE the event** (a `plan_closed`,
  a dead `pool` lock, a `dispatch_failed` worklog line);
- **a GUIDE hand-holds the correct response** ("on plan_closed →
  record_step_result(done); on a crash → read the worklog to confirm,
  then reap + reset");
- **the response is a deterministic, enum-constrained object op.**
The determinism of the mutation is fully preserved; only the *noticing*
moves from dumb polling to rx intelligence.

This is the whole thesis the rewrite rests on: **next_action gives
determinism, rx gives intelligence, and you only get BOTH when the
object model encodes the legal progression (types + enums + encapsulated
invariants) AND guides hand-hold the LLM through observe→act.** rx
without guides loses determinism; next_action without rx loses
intelligence.

## Target: where each responsibility lives after decoupling

| responsibility | today | target | determinism preserved by |
|---|---|---|---|
| (A) phase sequencing | next_action | **next_action** (pure, read-only on state) | the FSM stays the rail |
| (B) incremental mutation | intent tools (already) | object surface (`update/create_object`) | atomic intent tools, no JSON regen |
| (C) enum transitions | schemas + verify gate | object surface + **enums EXPOSED in describe_objects** | the type constrains the LLM |
| (D) honest terminal | next_action FSM | **next_action** | deterministic computation |
| (E) reconciliation | next_action (polling) | explicit `reconcile` op, triggered by rx, **also run by the heartbeat backstop** | the mutation is still a deterministic object op; backstop prevents a missed rx event from hanging |

## Concrete, non-loose plan (in dependency order)

1. **Expose the state machines as data** (lowest risk, highest leverage,
   directly serves "expose a type as enum when it has fixed state"):
   `describe_objects('action'/'recipe'/'plan')` returns the status/state
   **enum values AND the legal transition map** (e.g.
   `pending→in_progress→{verify,done,failed,pending}`, `verify→{done,failed}`,
   `needs_review→{done,failed}`). Under d30 the record/status=done path goes
   `in_progress→done` directly (pure write); the `verify` state is retained in
   the map as a **dormant** state (still constructible directly, e.g. W7
   pacing) but is unreachable via `record_action_status`.
   The LLM then sees the correct progression as part of the object type,
   not as next_action's hidden behavior. No behavior change; pure
   determinism-made-visible. **This is the foundation — do it first.**

2. **Write the observe→act guides** (the missing "intelligence
   determinism"): for each rx event class, the exact deterministic
   response. `plan_closed → record_step_result`; `pool` dead-lock →
   read worklog → reap + reset; `dispatch_failed ×3 → escalate`. Without
   these, rx is capability without correctness.

3. **Extract `reconcile` from next_action** into an explicit op with the
   SAME deterministic logic (plan_closed→step done; disk-terminal
   backstop; crash→reset/surface). next_action becomes a pure read-only
   phase pacer. The neuron calls `reconcile` on an rx wake; the heartbeat
   cron calls `reconcile` then `next_action` as the backstop — so
   robustness is identical to today, the logic just isn't hidden.

4. **Re-validate determinism**: every FSM transition test must still
   pass; add tests that `reconcile` + `next_action` compose to the same
   progression `next_action`-alone produced before. The acceptance bar:
   the deterministic behavior is byte-for-byte preserved; only the
   *trigger* (rx vs internal poll) and the *visibility* (enums exposed,
   guides written) change.

Step 1 + 2 are pure additions (no behavior change) and can ship
immediately. Step 3 is the structural change and must be gated on Step 4
proving the progression is unchanged. **No "assume the LLM will figure
it out" anywhere — every state move stays a deterministic, typed,
guided object op.**
