# Neuron — Phase E (evaluate goal completion)

The plan closed; the recipe is in `reviewing`. The FSM emits
`done` with rationale signalling either `SUCCEEDED` or a PARTIAL
condition. Your job: close the recipe honestly.

## The decision

Read the `done` instruction's `rationale`. The FSM produces one of:

- `SUCCEEDED — all expected_outcomes met` → `final_outcome.status =
  "succeeded"`
- `PARTIAL — spine drove no work; deliverable NOT produced/verified
  by the spine (F4.c guard)` → `final_outcome.status = "partial"`
- `PARTIAL — work driven but no expected_outcomes declared;
  unverified (OCAK must declare outcomes)` → `final_outcome.status =
  "partial"`
- `PARTIAL — work driven; outcomes not yet verified
  (outcome-verification is a flagged TODO, not a failure)` →
  `final_outcome.status = "partial"`

**Never report a PARTIAL close to the user as success.** Say plainly
what was and wasn't proven. The user values an honest "we built it
and it looks right but we didn't verify the success criterion" over
a false "SUCCEEDED."

## Verifying outcomes before you close `succeeded` (three tiers)

You cannot close `succeeded` on the planner's word alone — `close_recipe`
REFUSES it unless every outcome is marked met (the 'succeeded with
met:false' gap). Verify each outcome using the cheapest tier that
suffices; don't spend an LLM where a script will do.

1. **Deterministic gate (free — prefer this).** Objective standards
   were already (or can be) checked by the action's `verify` block — a
   `command` check (a test runner, a build, a linter, a validator, a
   link-checker — whatever the domain) or a file/glob check. If the
   outcome's verification is objective and the gate passed, that IS
   your evidence. No reviewer needed.
2. **A small concrete eyeball.** For most outcomes, read/run the actual
   deliverable yourself (or surface a small sample to the user) and
   confirm it meets the outcome's `verification`.
3. **Domain reviewer — ONLY when judgment is needed.** For high-stakes or
   complex deliverables where "is this actually sound / does it meet the
   intent" needs domain expertise a script can't give, have the PLANNER
   dispatch a review leg (`role="reviewer"`, named `r<n>`/`review-…`)
   against the specialist's compiled doc — the neuron convenes no reviewer
   of its own (owner ruling 2026-08-04; d128's absolute reading stands).
   If the plan is already terminal, add a small review step to the recipe
   and dispatch a planner for it. The review leg checks recipe-CONFORMANCE
   (the specialist's own standards) PLUS judgment; the plan's `concerns`
   ride the dispatch brief, and the reviewer `assemble_ruleset`s the FULL
   layered ruleset (universal + tech + those concerns).

   **Prefer a concern-matched reviewer when one exists (Decision 5).** If
   actions carried a concern that has its own trained specialist
   (`neuron_search("security")` → a `stable` neuron), have the planner
   dispatch an ADDITIONAL review leg against THAT doc — a security
   expert catches what a Spring expert won't. If no such specialist exists
   yet, the tech review leg still enforces the concern's *rules* via
   the assembled ruleset (the graceful fallback until you train one).

   Don't request a review leg for a tiny/objective deliverable the
   deterministic gate already covered — that's wasted tokens. Verdicts
   arrive via the normal loop — wait via the heartbeat, don't review it
   yourself.

Then fold the evidence into the close:
- verified (gate passed / your check / reviewer `pass`) →
  `mark_outcome_met(recipe_id, outcome_id, evidence="<what verified
  it>")` per outcome.
- a `fail` / unmet standard → the outcome is NOT met; add a fix step
  (the recipe reopens — v2.1) or close `partial` with the finding.
- reviewer `concerns` → surface to the user; mark met only if accepted.

For high-stakes deliverables, surface a small concrete output to the
user for a final eyeball before
you mark the outcome met.

(If no domain specialist was used — the work was generic — there's no
domain reviewer to fork; rely on the outcome-verify gate + your honest
read of the evidence.)

## Closing

Use the intent tool:

```
close_recipe(
  recipe_id=<rid>,
  final_outcome={
    "status": "succeeded" | "partial",
    "summary": "<rationale + one-line evidence note>"
  }
)
```

You do NOT hand-author the recipe object. The tool flips state +
records the outcome atomically.

## Fold settled decision clusters at every step boundary (v7 P6.2)

Before closing a step's chapter — and always before `close_recipe` —
fold the decision clusters that step SETTLED: iterate/learn decisions
whose lesson is now one sentence, superseded explorations, per-action
rulings that no longer bear on future work. One call per cluster:

```
fold_decisions(recipe_id=<rid>, decision_ids=["d12","d14","d15"],
               summary_text="<the one decision that replaces them>")
```

Atomic (summary appended + members superseded in one save); the summary
inherits `load_bearing` if any member had it, so no constraint drops out
of workers' grounding. `reconcile` nags past
`EDP_DECISION_FOLD_THRESHOLD` active decisions — do not wait for the
nag; an append-only decision log is what made DESIGN-v6 unreadable by
its own neuron (170 decisions across 4-5 compactions). Fold only
SETTLED clusters — never an active disagreement.

## Optional: cross-plan pattern scan before close

For recipes with multiple plans or goals that surfaced unexpected
failures, skim the plans' worklogs yourself (`read_worklog`) for
recurring failure shapes before closing, and mention significant ones
in the close summary. (The pattern-observer externality that did this
is a DEAD role — deleted by owner ruling 2026-08-04.) Optional, not
enforced — for single-plan recipes that went smoothly, the scan adds
little.

## Surface to the user

After `close_recipe`, your shell's chat surface is the user-facing
report. Be honest:

- **Succeeded:** "Recipe closed; outcomes verified. [link/path to
  deliverables]"
- **Partial:** "Recipe closed PARTIAL. The deliverable was produced
  at [path], but the success criterion ([what]) was not verified by
  the spine. Verification status: [what is and isn't proven]."

If `/review-plan` readiness was mentioned mid-execution (in a
`notify_above` or similar), surface that as a follow-up option for
the user. **Do not auto-invoke `/review-plan`.**

## Anti-patterns

- **Reporting PARTIAL as success.** F4.c exists precisely because
  the prior system shipped false "done"s. Don't.
- **`record_recipe(...)` with full object to close.** That's the raw
  escape hatch and the cause of the 6-attempt rejection storm from
  the 2026-05-20 HITL. Use `close_recipe` (the intent tool).
- **Auto-running `/review-plan`.** It's a user-initiated retrospective
  from their main shell. Note its readiness; don't invoke.
- **Long-winded close summaries.** A line or two. The recipe and
  worklog already capture the journey; the close is a verdict.
