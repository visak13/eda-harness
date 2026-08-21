# strategy-library — high-level strategy skills, goal-kind indexed (v7 §2.6)

The PLANNER's approach picker — the HIGH-LEVEL STRATEGY layer ("shape"
is this layer's legacy field name; low-level strategy = the spec docs
workers/reviewers build against). Broader than a DAG shape: HOW to
attack the step. Read this index AFTER grounding, pick at most one
strategy (plus at most one checklist AFTER the DAG is drawn); record
the pick in the plan's `shape` field as `<strategy>/<shape>` or
`<base>+<delta>` when you derived. A mid-step switch on recorded
evidence (a failed spike, a steer) is lawful — record WHY in the
worklog; recurring derivations flow back as `shape_learning` events for
ratification into this library.

## Pick by GOAL KIND first

| goal kind | start from | typical checklist |
|---|---|---|
| research / investigate ("find out", "compare", "audit") | spike-then-commit | `planner-shape-research-synthesize` |
| build, nothing wired yet (new app / pipeline / integration) | walking-skeleton | `planner-strategy-walking-skeleton` |
| build, extending something live | tracer-bullet or strangler-fig | `planner-shape-modular-build` / `-linear-build` |
| fix ("broken / slow / wrong / 500-ing") | diagnose-fix-verify | `planner-shape-diagnose-fix-verify` |
| repair a REJECTED close (failed acceptance, user walked it and it fell over) | acceptance-repair-chain | `planner-strategy-acceptance-repair-chain` |
| creative / visual (assets, look-driven UI) | golden-path-first | `planner-shape-creative-production` |
| proof / submission ("demonstrate", "collect and deliver") | contract-first | `planner-shape-gather-validate-submit` |

A step matching no row is normal — draw the DAG your grounding demands.
Budget rules regardless of pick: ONE worker when one worker ships it;
review at the END for coherence, not per-action ("it's not about
creating a beautiful DAG").

## The strategies

| strategy | trigger | essence |
|---|---|---|
| walking-skeleton | multi-component step, nothing wired yet | thinnest end-to-end path first; flesh out only what the skeleton proves |
| spike-then-commit | a load-bearing unknown (library fit, perf, API shape) | timeboxed throwaway spike answers the question; then build clean |
| tracer-bullet | new territory + known target | one production-quality path through all layers; clone it sideways |
| strangler-fig | replacing something live | new grows around old; cutover per-seam; old dies last |
| diagnose-fix-verify | a defect/regression step | reproduce first; fix the cause not the symptom; verify the repro dies |
| acceptance-repair-chain | a rejected/reopened close | walk the rejection cold; repair the deliverable AND the gate that let it through; re-walk |
| golden-path-first | user-facing feature with many branches | the happy path ships and is reviewed before any edge case |
| contract-first | two sides built by different shells | the seam's contract (types/API/fixtures) is an action BEFORE either side |

Checklists (pitfalls for a DAG you already drew — one at most):
`planner-strategy-walking-skeleton` ·
`planner-strategy-acceptance-repair-chain` ·
`planner-shape-linear-build` · `-modular-build` · `-poc-iterate-build` ·
`-diagnose-fix-verify` · `-research-synthesize` · `-creative-production`
· `-gather-validate-submit`. A DAG matching no checklist is normal.
