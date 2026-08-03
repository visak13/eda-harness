# Planner shape: linear-build

> **OPTIONAL ACCELERATOR** — a pitfall checklist for a DAG you already
> drew (planner-phase-author Step 1). Never contort work to fit this
> file; a DAG matching no shape is normal — proceed with your DAG.

**When this shape applies:** routine, well-understood builds. Add a
field, rename a symbol, build standard CRUD where the design is
uncontroversial. No POC needed, no module decomposition justified, no
novel performance assumptions.

**When this shape does NOT apply** (pick another):
- Performance-sensitive code with uncertain feasibility →
  `poc-iterate-build`
- Goal has obvious axes of variation ("now do same with Y") →
  `modular-build`
- Bug fix → `diagnose-fix-verify`
- Pure research / synthesis → `research-synthesize`

## Plan structure

- **Flat list of leaf actions** — no sub-plans, no stages.
- Each action specifies **file paths, signatures, schemas** —
  predictable from description alone.
- Each action has an `acceptance` object — typically
  `{"kind": "tests_pass"}` for code, `{"kind": "manual_review"}` for
  light/uncoded work.
- Dependencies via `depends_on` when later actions need earlier
  outputs.
- Estimated total: 3-12 actions for a typical step.

## Action sizing

- ✅ "Add `created_at` timestamp column + migration + model update +
  test." (one focused action)
- ✅ "Wire the new POST /users endpoint to the existing service."
- ❌ "Build the API." (too broad — split into auth + endpoints +
  tests)
- ❌ "Rename one variable." (too small — collapse with neighbours)

## Anti-patterns

- **Routing performance-sensitive work here.** If the feasibility of
  hitting a target metric is genuinely uncertain, use
  `poc-iterate-build` — every action will look "done" while the
  system-level requirement quietly fails.
- **Skipping acceptance signals.** Each action's acceptance is what
  the planner (and the review leg) reads to know the action
  succeeded. Empty acceptance = no verification.
