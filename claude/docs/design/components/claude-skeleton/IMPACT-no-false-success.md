# IMPACT — no false success (F4.c guard) + OCAK must produce work

**Process:** §5.5 note written BEFORE the change (restoring discipline
after the prior slip).

**Trigger:** HITL #6. The `/clear` killer-check PASSED (resume works —
the project's central claim proven). But the resumed recipe closed
`done — "no outcomes declared; close"` having driven **zero steps**; the
deliverable existed only from an earlier incidental run. That is
**F4.c** (my own AUDIT): a recipe reporting success having
produced/verified nothing — the exact prior-system failure the rewrite
exists to kill.

## Root causes (two)
1. **OCAK** (`ocak.md`) does not guarantee a verifiable, step-bearing
   recipe — it persisted one with no `expected_outcomes` and no
   actionable step.
2. **`recipe_fsm` REVIEWING** treats "no outcomes" as a clean `done`
   (false success), and `succeeded` is reachable without the spine ever
   driving work.

## What changes (build #2; prose + FSM logic, no schema/contract)
- **`ocak.md`**: mandate — every recipe OCAK persists MUST have ≥1
  concrete step that produces the deliverable AND ≥1 `expected_outcome`
  with a concrete `verification`. An empty / outcome-less recipe is
  invalid; never persist one.
- **`recipe_fsm` REVIEWING** — honest terminal, `succeeded` only with
  proof:
  - no step ever reached `done` → `partial` ("spine drove no work —
    deliverable NOT produced/verified; F4.c guard").
  - work driven but no `expected_outcomes` → `partial` ("unverified;
    OCAK must declare outcomes").
  - outcomes all `met` → `succeeded`.
  - else → `partial` ("work driven; outcomes not verified").
  The **only** path to `succeeded` is declared + met outcomes. The
  prior auto-`done` lie is removed.
- **`neuron.md`** `done` handling: write `final_outcome` with
  `status` = `succeeded` only if the instruction rationale says so,
  else `partial`; then `record_recipe(state="closed", final_outcome=…)`.

## Deliberately deferred (flagged, not faked)
- **Marking `outcome.met`** (verifying outcomes) and **critic pre-close
  audit** are real mechanisms with no wiring yet. Faking them = the very
  false-success we're killing. So proper runs will honestly close
  `partial` ("work driven; outcomes not yet verified") — the deliverable
  IS produced by a real planner/worker (what the user wants to see),
  and the system tells the truth about verification. Outcome-verification
  + critic become their own component/TODO
  (`# TODO(outcome-verify)`, `# TODO(critic-audit)`), removing the
  pre-existing critic-loop risk in the old REVIEWING code.

## Blast radius
- edp-claude only. `recipe_fsm` REVIEWING branch + `ocak.md` +
  `neuron.md` prose. Schemas/other tools/contracts untouched. FSM tests
  for REVIEWING updated; new cases for the partial/succeeded matrix.
- Integration additive-safe (3/3 expected green).

## Verdict
Kills the F4.c false-success the user caught; makes `succeeded` mean
proven; unblocks the planner-owns-it test (work is really driven).
Verification/critic honestly deferred, not faked. Proceed.
