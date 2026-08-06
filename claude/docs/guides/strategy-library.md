# strategy-library — engineering strategies, trigger-indexed (v7 §2.6)

The PLANNER's approach picker — broader than a DAG shape: HOW to attack
the step. Read this index AFTER grounding, pick at most one strategy
(plus at most one shape checklist AFTER the DAG is drawn); record the
pick in the plan's `shape` field as `<strategy>/<shape>` or
`<base>+<delta>` when you derived. A mid-step switch on recorded
evidence (a failed spike, a steer) is lawful — record WHY in the
worklog; recurring derivations flow back as `shape_learning` events for
ratification into this library.

| strategy | trigger | essence |
|---|---|---|
| walking-skeleton | multi-component step, nothing wired yet | thinnest end-to-end path first; flesh out only what the skeleton proves |
| spike-then-commit | a load-bearing unknown (library fit, perf, API shape) | timeboxed throwaway spike answers the question; then build clean |
| tracer-bullet | new territory + known target | one production-quality path through all layers; clone it sideways |
| strangler-fig | replacing something live | new grows around old; cutover per-seam; old dies last |
| diagnose-fix-verify | a defect/regression step | reproduce first; fix the cause not the symptom; verify the repro dies |
| golden-path-first | user-facing feature with many branches | the happy path ships and is reviewed before any edge case |
| contract-first | two sides built by different shells | the seam's contract (types/API/fixtures) is an action BEFORE either side |

Shape checklists (pitfalls for a DAG you already drew — one at most):
`planner-shape-linear-build` · `-modular-build` · `-poc-iterate-build` ·
`-diagnose-fix-verify` · `-research-synthesize` · `-creative-production`
· `-gather-validate-submit`. A DAG matching no shape is normal.
