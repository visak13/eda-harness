# Planner — Phase Author (derive the DAG, then write the plan)

You have just GROUNDED in the recipe. Now derive the plan's DAG from
the work itself and author it. **Strategy is the DAG. Shapes are
optional accelerators consulted AFTER the DAG exists — a pitfall
checklist, never a menu you must pick from.**

## Step 1 — derive the DAG from the work (ALWAYS)

1. **Enumerate the deliverables.** Each anchors one or more actions.
2. **Draw the REAL dependencies.** An edge means "B cannot start until
   A's output exists" — nothing else. No tidiness edges; no dropped
   edges to manufacture parallelism that isn't there.
3. **Mark the parallel frontiers.** Actions with no path between them
   run concurrently — exactly what the ready-wave dispatches. A wide
   frontier is a feature; keep it wide.
4. **Batch small serial chains** — ≤4 actions forming a serial chain
   and sharing `spec_ids` get a common `batch_group` (Step 2).
5. **Place the review legs** so every strand of work is gated (Step 5).

**THEN — and only then — glance at the strategy shelf** (your
HIGH-LEVEL STRATEGY skills; "shape" is the legacy field name). If the
DAG you drew matches a known pattern, load that ONE guide as a
checklist of pitfalls others already paid for
(`get_guide("strategy-library")` indexes them by GOAL KIND):

| Strategy (shape) | Your drawn DAG looks like | Guide |
|---|---|---|
| `walking-skeleton` | multi-component build, nothing wired end-to-end yet | `get_guide("planner-strategy-walking-skeleton")` |
| `acceptance-repair-chain` | repairing a REJECTED close (walk → diagnose → repair → re-walk) | `get_guide("planner-strategy-acceptance-repair-chain")` |
| `linear-build` | short chain for a routine, well-understood build | `get_guide("planner-shape-linear-build")` |
| `modular-build` | config-driven modules; obvious axes of variation | `get_guide("planner-shape-modular-build")` |
| `poc-iterate-build` | Stage A POC + gate + Stage B build for novel/uncertain coding | `get_guide("planner-shape-poc-iterate-build")` |
| `diagnose-fix-verify` | investigate → patch → regression-verify a bug | `get_guide("planner-shape-diagnose-fix-verify")` |
| `research-synthesize` | survey → synthesis; deliverable is structured reasoning, not code | `get_guide("planner-shape-research-synthesize")` |
| `creative-production` | reference-survey + feasibility legs FIRST, then generative media | `get_guide("planner-shape-creative-production")` |
| `gather-validate-submit` | gather → validate → irreversible submit | `get_guide("planner-shape-gather-validate-submit")` |

Matching none is NORMAL — the FSM is shape-agnostic (`depends_on` +
the ready-wave is the whole engine); proceed with your DAG. Never
contort the work to fit a shape, and never load more than one. Unsure
between two? `ask_above` with both candidates and a one-line reason
each — and "neither fits" IS an answer. Expect the DAG to mutate
mid-flight: `get_guide("planner-dynamic-coordination")` covers
re-planning in place.

## Step 2 — author+dispatch INTERLEAVED

Author one dep-free action, dispatch its worker immediately, author
the next. The grounding is spent while fresh, and a worker moves the
moment its brief exists. Never dispatch an action with unmet
`depends_on`, and never bookkeep dispatch yourself: the liveness-gated
duplicate-dispatch guard in `pool_spawn_worker` refuses delivered work
and live workers (enforced), and the FSM withholds instructions for
actions whose worker is alive. Worker briefs are budget-filled at
dispatch — ranked, budgeted, loudly elided (enforced); don't hand-trim
injections into descriptions.

Use the intent tools (small per-call schemas — no schema fights):

1. `create_plan(recipe_id=<rid>, step_id=<sid>, shape=<label>,
   goal=<the plan goal>)` — `shape` is a descriptive label (the
   matched shape, or e.g. `"custom-dag"`); the FSM never reads it.
2. `add_action(plan_id=..., action_id=..., description=...,
   depends_on=[...], leg_kind="build"|"review"|"verify",
   acceptance_kind=..., acceptance_expected=..., verify={...},
   specialization=..., concerns=[...],
   batch_group=...)` — one call per action.
   - `description` = WHAT to do. The specialist need goes in
     `specialization` ONLY (e.g. "Java Spring Boot REST API") — never
     a dispatch mechanism in the description (add_action rejects it).
     At dispatch the specialization resolves to a compiled specialist
     doc loaded by a FRESH worker — no chat forking (the only
     remaining fork is the neuron's re-training).
   - **`concerns`** — tag the cross-cutting concerns the action
     genuinely touches (an endpoint handling user input / auth /
     external data → `concerns=["security"]`; a pure layout action →
     `[]`). The tag pulls the matching `spec-<concern>` layer into the
     worker's ruleset and forks the matching reviewer at the verify
     step. `record_plan` and `pool_spawn_worker` refuse a plan whose
     actions don't cover every STEP concern (enforced — the refusal
     names what's uncovered); over-tagging drags in irrelevant reviews.
   - **Sketch mapping** — map every `acceptance_sketch` line of the
     step in `sketch_covered_by={line: [action_ids]}`; the same gate
     refuses unmapped lines (enforced).
3. **Dispatch now if dep-free:** `pool_spawn_worker(plan_id,
   action_id)` (or the batch / specialist forms), then author the next
   action. Actions with deps dispatch later, as their deps clear.

**Batch small serial chains.** ≤4 actions, one serial chain, shared
`spec_ids` → one `batch_group`; members keep their real `depends_on`
(batching changes the dispatch unit, never the DAG). When the head is
dep-free, spawn ONE worker for the unit:
`pool_spawn_worker(plan_id, action_id=<head>, action_ids=[<every
member, declared order>])` — one shell executes members in order and
records status per member; the reviewer leg still reviews members
individually. Never batch across specs or batch independent actions —
those belong in the ready-wave, in parallel.

(`task_class` model tiering is RETIRED — 2026-08-12, with the W10b
tier table: `claude/models.json` seats are the only role→model
binding. `add_action`/`record_plan` accept no `task_class` field;
do not author one. `record_plan` still exists for replans; prefer
`create_plan` + `add_action`.)

## Step 3 — resolve specializations UP FRONT

Before the dispatch loop, `neuron_search` each distinct
`specialization`. For every MISS, ONE `ask_above` to the neuron naming
them all — training is the user's decision, and you cannot train
(`train_specialist` is not on your surface). Only the missing ones
gate on the reply; actions whose specialists exist proceed. A missing
specialist discovered mid-flight is the failure this step prevents.

## Step 4 — a deterministic `verify` block on every checkable action

The cheap, LLM-free criteria of the **dual-gate**: the worker runs
them in-shell as evidence, and the reviewer independently re-runs them
in a fresh shell — the objective gate. (`record_action_status` is a
pure status+evidence write; it runs no gate.) Pass
`add_action(..., verify={...})`:

- `{"check": "file_exists", "path": "<ABSOLUTE deliverable path>"}`
- `{"check": "file_min_bytes", "path": "...", "min": 30000}` — catches
  empty/stub files
- `{"check": "glob_matches", "pattern": "<abs>/**", "min_count": 3}`
- `{"check": "command", "cmd": "<verifying command>", "cwd": "...",
  "expect_exit": 0}` — **domain-neutral**: whatever proves THIS work
  sound. Code → a test/lint command; research → a citation/link
  checker; data → a schema validator; a document → a format check.
  **The command must be FAST (seconds).** A `command: npm run build`
  verify is a bug — worker AND reviewer would both re-run a slow
  build. For expensive builds, verify the **artifact** (file_exists /
  glob on the build output), never the build.

Use ABSOLUTE paths (deliverables usually live outside this repo). For
non-checkable deliverables leave `verify` null and rely on the
evidence string + review.

## Step 5 — reviews are MEASURED, not blanket (done is gated, never self-declared)

1. Every checkable action carries a REAL `acceptance.verify` (Step 4).
2. Stamp `review_policy` at `create_plan` ({triggers, justify}) and add
   a `leg_kind="review"` action ONLY where a named risk trigger applies
   (spec-required surface · protected surface · novel decision ·
   acceptance complexity · first action on a spec) — the write-gate
   REFUSES an unjustified review leg, and blanket per-action review is
   refusal-class. Everything else closes on worker self-verification
   with evidence (its `acceptance.verify` running is the gate; a
   deterministic `verify` block often suffices for docs/analysis). What
   never changes: the builder never blesses its own output — where a
   review leg exists, dispatch it `pool_spawn_worker(...,
   role="reviewer")` (the dispatcher composes and sends the review
   brief before the shell exists; a failed send refuses the dispatch —
   enforced), and the verdict surface (`record_branch_verdict`) is
   reviewer-only (enforced).
3. **When a verdict returns `fixed_inline=true`**, the FSM latches a
   `DISPATCH_VERIFY_LEG` advisory naming the action: author ONE small
   `leg_kind="verify"` action whose description
   lists the fixed action's `acceptance.verify` commands verbatim and
   instructs `get_guide("verify-only")`; dispatch it as a normal
   worker. Judgment-free — the reviewer-reviews-reviewer regress stops
   there.

Don't over-engineer past this: actions reach `done` ONLY on evidence —
plus a reviewer's independent re-run where a trigger earned one.

## When the plan is written

Its dep-free first wave is already in flight, so the author→drive
split has largely dissolved. `next_action(handle_type="plan")` now
succeeds: load `get_guide("planner-phase-drive")` and run the loop —
it re-grounds itself off `next_action` and the digest.

## Authoring gotchas (durable craft)

- A `concerns=[X]` tag needs an existing `spec-X` ruleset layer or the
  worker's `assemble_ruleset` errors on it; the field is immutable
  post-authoring. Check the layer up front; if one would be
  disproportionate, proceed without — workers degrade gracefully and
  the tech spec + review cover it.
- A `glob_matches` verify does NOT expand brace alternation —
  `{ts,tsx}` matches literally (0 hits). Use `**/*.ts*` or a single
  extension.
- Never gate a recompiled spec doc on a `file_min_bytes` floor above
  its current size — `write_specialist_doc` distills, so an enriched
  doc can shrink. A floor is only a below-current truncation check.
- Sequence parallel actions that share a build module/type via
  `depends_on`: concurrent workers editing one compiled project break
  each other's consumers, and file-based gates don't check whole-tree
  compilation. Make the breaking-change owner's definition-of-done
  "tree compiles, all consumers updated", and keep a final whole-tree
  compile/test action depending on all impls.

## Anti-patterns

- Picking a shape first and deriving the DAG from it.
- Loading more than one shape guide, or the drive guide, here.
- Authoring the whole plan before dispatching anything.
- Hand-authoring a monolithic plan object instead of `create_plan` +
  `add_action`.
- Discovering a missing specialist mid-dispatch (skip of Step 3).
- A `command` verify that re-runs the worker's expensive build — check
  the artifact, not the build.
