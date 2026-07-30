# Planner — Phase Author (derive the DAG, then write the plan)

You have just GROUNDED in the recipe (outcomes, decisions, assumptions,
your step goal). Now — and only now — derive the plan's DAG from the
work itself and author it. **Strategy is the DAG. Shapes are optional
accelerators you consult AFTER the DAG exists — a pitfall checklist,
never a menu you must pick from.**

## Step 1 — derive the DAG from the work (ALWAYS)

Draw the plan from the work, not from a template:

1. **Enumerate the deliverables.** What must exist when this step is
   done? Each deliverable anchors one or more actions.
2. **Draw the REAL dependencies.** An edge means "B cannot start until
   A's output exists" — nothing else. Don't add edges for tidiness, and
   don't drop edges to manufacture parallelism that isn't there.
3. **Mark the parallel frontiers.** Actions with no path between them
   run concurrently — that is exactly what the ready-wave dispatches
   (`planner-phase-drive.md`). A wide frontier is a feature; keep it wide.
4. **Batch small serial chains** — ≤4 actions forming a serial chain and
   sharing `spec_ids` get a common `batch_group` (mechanics in Step 2).
5. **Place the review legs** so every strand of work is gated (Step 5).

**THEN — and only then — glance at the shape shelf.** If the DAG you
just drew matches one of these known patterns, load that ONE shape guide
via `get_guide(...)` and use it as a **checklist of known pitfalls**
(mandatory pre-steps, acceptance signals, failure modes others already
hit):

| Shape | Your drawn DAG looks like | Guide |
|---|---|---|
| `linear-build` | A short chain for a routine, well-understood build. CRUD, rename, add a field. Design is uncontroversial. | `get_guide("planner-shape-linear-build")` |
| `modular-build` | Config-driven modules because the goal has obvious axes of variation (multiple variants likely). | `get_guide("planner-shape-modular-build")` |
| `poc-iterate-build` | **Stage A POC + gate + Stage B build** for novel / uncertain coding — performance, ML, integration risk, any riskiest assumption not pre-validated. | `get_guide("planner-shape-poc-iterate-build")` |
| `diagnose-fix-verify` | Investigate → patch → regression-verify for a bug. "X is broken / slow / wrong." | `get_guide("planner-shape-diagnose-fix-verify")` |
| `research-synthesize` | Survey → synthesis legs; deliverable is structured reasoning, not code. | `get_guide("planner-shape-research-synthesize")` |
| `creative-production` | Reference-survey + feasibility-scan legs FIRST, then generative media production — video, image, audio, mods, plugins. | `get_guide("planner-shape-creative-production")` |
| `gather-validate-submit` | Gather → validate → irreversible submit. Form-filling / external submission — validate before submit, escalate before posting. | `get_guide("planner-shape-gather-validate-submit")` |

**If your DAG matches none of these, that is NORMAL — proceed with your
DAG.** The FSM is shape-agnostic: `depends_on` + the ready-wave is the
whole engine, and shapes exist only in prose. A shape guide accelerates
you past pitfalls someone already paid for; it never overrides the
dependencies you derived from the work. NEVER contort the work to fit a
shape, and never load more than one shape guide.

**If you're unsure between two shapes**, `ask_above` to the neuron with
both candidates and a one-line reason for each. Don't guess — and if the
honest answer is "neither fits," that IS the answer: keep your DAG,
skip the shelf.

**Expect the DAG to mutate mid-flight.** When execution discoveries
invalidate the drawn DAG, re-plan in place —
`get_guide("planner-dynamic-coordination")` covers adding, rewiring and
deleting actions and re-firing the wave — instead of pushing a stale
plan to completion.

## Step 2 — author+dispatch INTERLEAVED (no monolithic plan object, no separate drive hand-off)

The authored default is **interleaved**: author one dep-free action, then
**immediately dispatch its worker**, then author the next action, dispatch
it, and so on — you dispatch each dep-free action AS you author it, rather
than authoring the whole plan and handing off to a separate drive phase.
This keeps a worker moving the moment its brief exists, and it means the
grounding you just did is spent while it's fresh.

**The two existing guards are what make this safe — rely on them, don't
re-implement dispatch tracking:**

- **`depends_on` gating.** You dispatch an action ONLY when its
  `depends_on` is empty/satisfied. An action with unmet deps is authored
  now but left for its dep to clear — never dispatched early. (The FSM's
  `next_action` in the drive shell picks these up as their deps clear; see
  below.)
- **The `_tools.py` duplicate-dispatch guard.** `pool_spawn_worker` refuses,
  unless `force=true`, to dispatch an action that is either (a) already
  `done`/`needs_review` — delivered work — or (b) backed by a **live worker**
  (`pool.liveness(<plan_id>:<action_id>) == "alive"`), whatever its recorded
  status. So a second accidental dispatch of the same action is rejected by
  the tool, and you do not have to bookkeep "did I already spawn this."

  Leg (b) is gated on **liveness, not on the status string**, and that is
  load-bearing. Spawning here — interleaved, straight after `add_action` —
  does NOT stamp the action `in_progress`; only the FSM's own
  `dispatch_action` instruction does. So an interleave-dispatched action sits
  at `pending` with a live worker inside it, and a status-only guard would
  wave a second spawn straight through. (This is C7: it shipped five times on
  s26 and once on s27 before the guard learned to ask the pool.) A **dead** or
  unknown handle stays dispatchable, so crash recovery never deadlocks.

So the interleaving must NEVER dispatch an action with unmet deps and must
never double-dispatch; `depends_on` + the liveness-gated guard are the
authority that enforce both.

Use the intent tools (small, obvious per-call schemas — no
schema-guessing, no retries):

1. `create_plan(recipe_id=<rid>, step_id=<sid>, shape=<matched shape>,
   goal=<the plan goal>)` — the tool fills plan_id + domain. One call.
   `shape` is a descriptive label: pass the shape you matched, or a
   short free-form label (e.g. `"custom-dag"`) when your DAG matched
   none — the FSM never reads it.
2. `add_action(plan_id=<rid>-<sid>, action_id=..., description=...,
   depends_on=[...], executor_mode="subagent"|"inline",
   acceptance_kind=..., acceptance_expected=..., verify={...},
   specialization=..., concerns=[...])` — one call per action; the tool
   builds the Acceptance object for you. Set `specialization` (e.g. "Java
   Spring Boot REST API", "React + Tailwind grid layout") when an action
   needs real domain expertise. Leave it null for ordinary work.
   **The specialist need goes in THIS field ONLY — never write "call
   get_specialization", "branch_specialist", or any dispatch mechanism in
   the `description` (add_action rejects it).** Description = WHAT to do;
   `specialization` = who does it.

   **How a specialist action runs (NO FORK).** At dispatch you resolve the
   `specialization` to a stable neuron, stamp its `spec_id` onto the
   action, and `pool_spawn_worker` — a **fresh** worker that loads the
   specialist's **compiled doc(s)** (`get_specialist_docs`) as its grounding.
   You do **NOT** fork the trained chat — the compiled doc is the baseline,
   and the execution fork is retired (the only remaining fork is the
   neuron's re-training, `update_specialist`). (See `planner-phase-drive.md`
   → `dispatch_action`.)

3. **Dispatch it now if it's dep-free.** Immediately after `add_action`
   returns, if the action's `depends_on` is empty, dispatch its worker
   (`pool_spawn_worker(plan_id, action_id)` for ordinary work, or the
   resolve-then-spawn path for a specialist action — see
   `planner-phase-drive.md` → `dispatch_action`). Then author the next
   action. Do NOT wait until the whole plan is written. If the action has
   deps, leave it — it dispatches later, when its deps clear, in the drive
   loop. The `depends_on` check + the liveness-gated duplicate-dispatch guard
   above are what keep this from ever dispatching too early or twice.

   Because this spawn leaves the action at `pending` (see above), the FSM asks
   the pool before it dispatches: on your next `next_action` it sees the live
   worker and returns `wait` — naming the action it withheld — instead of
   instructing you to spawn a second shell for work already underway.

**Batch small serial chains (DESIGN-v7 1.4 — `batch_group`).** The
dominant DESIGN-v6 plan shape — a short serial chain of small actions
sharing the same `spec_ids` (write → wire → test, each `depends_on` the
previous) — paid a full cold ~30s shell spawn PER action. Author such a
chain with a shared `add_action(..., batch_group="<name>")` and it
dispatches as ONE unit: one worker shell executes the members in declared
order and records status per member. Rules of thumb:

- Batch **≤4 actions** that form a serial chain and share `spec_ids` (one
  grounding serves all members). Do NOT batch across different specs, and
  do NOT batch independent actions — independent actions belong in the
  ready-wave, in parallel, each on its own shell.
- Members keep their real `depends_on` — batching changes the dispatch
  unit, never the DAG.
- **Dispatch a batched chain as a unit, never member-by-member:** when the
  chain's head is dep-free, spawn ONE worker —
  `pool_spawn_worker(plan_id, action_id=<head>,
  action_ids=[<every member, declared order>])` — instead of the
  per-action interleaved spawn. (In the drive loop the FSM does this
  arithmetic for you: the head's `dispatch_action` carries
  `batch_action_ids`.) Each member still gets its own
  `acceptance.verify`; a reviewer leg reviews members individually.

**Stamp a `task_class` per action AT AUTHORING TIME (DESIGN-v7 1.3).**
While the action's shape is fresh in your head, classify it — dispatch
resolves the model tier from the class you pass to
`pool_spawn_worker(..., task_class=...)` (the MODEL_TIERS table in
`tools/roles.py`; per-action `Action.model` still wins when stamped):

- `"coding"` — a bounded, fully-specified coding action with an
  objectively checkable gate. The one MEASURED Sonnet tier; needs no
  opt-in flag.
- `"narrow"` — bounded single-file work, no open-ended judgment, no
  irreversible side-effects. CANDIDATE (unmeasured): resolves to Sonnet
  only with `allow_candidate_tier=true`; otherwise safely degrades to the
  Opus default.
- `"verify"` — a verify-only leg: re-run recorded `acceptance.verify`
  commands and transcribe output, judge nothing, fix nothing. CANDIDATE
  (unmeasured), same opt-in rule as `narrow`.
- omit (default `"*"`) — everything with real judgment in it. Resolves to
  the host default (Opus).

Never guess a class DOWN to chase cost: an unknown/wrong class degrades to
the safe Opus tier, and the reviewer leg (always Opus — never tiered) is
what makes a cheaper worker safe at all.

**Tag cross-cutting `concerns` (Decision 3b/4).** Security, accessibility,
performance and the like are ORTHOGONAL to the tech specialization — they
don't belong in any tech spec. Instead, tag the *action* with the concerns
it touches: an endpoint handling user input / auth / external data →
`concerns=["security"]`; a pure layout action → `concerns=[]`. This pulls
the matching `spec-<concern>` layer (e.g. OWASP rules) into the worker's
assembled ruleset, and at the verify step the dispatcher forks the
**matching reviewer** (a security action → a security reviewer; a Spring
action → a Spring reviewer) to enforce it. A non-tagged action has the
concern structurally absent — it can't leak in where it doesn't belong.
Tag only what the action genuinely touches; over-tagging drags in
irrelevant reviews.

(The monolithic `record_plan(plan)` still exists for replans, but prefer
`create_plan` + `add_action` — they never have schema fights, the way
`start_recipe`/`add_step` don't.)

## Step 3 — resolve specializations UP FRONT (v2.3)

Once actions are authored, before the dispatch loop, take the set of
distinct `specialization` values and `neuron_search` each. For every
MISS, `ask_above` the neuron in ONE message: *"these actions need
specialists that don't exist: [...] — train them?"* The neuron surfaces
to the user (training is the user's decision). Resolve the answer
(trained-and-stable vs proceed-without) before dispatching those
actions — so a missing specialist is never discovered mid-flight. Don't
block actions whose specialists already exist or that need none; only
the missing ones gate on the neuron's reply.

**You NEVER train a specialist yourself — `train_specialist` is an
orchestrator tool you cannot call.** Resolving up front here just means
you escalate the gap to the neuron early; the neuron (not you) decides
whether to train.

## Step 4 — author a deterministic `verify` block on every checkable action

It's the cheap, LLM-free CRITERIA the dual-gate runs — both the worker
(in its own shell, as evidence) and the reviewer (fresh shell, the
objective re-run) execute it; author a real one for anything a check can
decide rather than leaving it to reviewer judgement alone. Pass it as
`add_action(..., verify={...})`:

- `{"check": "file_exists", "path": "<ABSOLUTE path to deliverable>"}`
- `{"check": "file_min_bytes", "path": "...", "min": 30000}` (catches
  empty/stub files)
- `{"check": "glob_matches", "pattern": "<abs>/**", "min_count": 3}`
- `{"check": "command", "cmd": "<any verifying command>", "cwd": "...",
  "expect_exit": 0}` — **domain-neutral**: the command is whatever
  proves THIS work is sound. Code → a test/lint command; research → a
  citation/link checker; data → a schema validator; a document → a
  format check. The worker runs it and the reviewer re-runs it; a
  criterion that doesn't exit `expect_exit` fails the dual-gate.
  **The command MUST be FAST (seconds) and must NOT re-run expensive
  work the worker already did.** A `command: npm run build` verify is a bug
  — the worker already built, so both the worker AND the reviewer would
  re-run a ~10-min build just to re-prove it. For an expensive
  build/compile, the worker runs it as part of its WORK and the verify
  checks the **artifact** instead — e.g.
  `{"check": "file_exists", "path": "<...>/dist/index.html"}` or a glob
  on the build output. Reserve `command` for quick checks (a fast test
  subset, a linter, a validator), not slow builds.

`record_action_status` runs NOTHING (d30) — it is a pure status+evidence
write. The worker runs this check in its own shell as it works (reporting
the result as evidence) and the reviewer independently re-runs it in a
fresh shell; that reviewer re-run is what stops a worker claiming done for
something it didn't produce. Use ABSOLUTE paths (the deliverable usually
lives outside this repo). For
non-file deliverables (tests pass / a metric / a judgement) leave
`verify` null and rely on the evidence string + `/critic` review.

## Step 5 — every plan MUST include a review/verify step (done is gated, never self-declared)

Don't over-engineer this — rely on the d30 **dual-gate**: the worker runs
each `acceptance.verify` criterion in-shell, the reviewer independently
re-runs it, and the FSM runs no gate. Two rules, always:

1. **Every checkable action carries a REAL `acceptance.verify`** (Step 4).
   The worker runs those criteria in-shell and records `done` + evidence
   (a pure write — the FSM runs no gate, and the action stays `done`; no
   code moves it to `needs_review`). The REVIEWER then independently re-runs
   the criteria in a fresh shell — that re-run is the objective gate. Nothing
   in code compels the reviewer leg; YOU do, by always authoring one.
2. **Every plan includes an explicit review/verify step.** For CODE work
   that means a dedicated **reviewer leg** — a separate reviewer action
   (via the matching `concerns`/reviewer-fork) that validates quality, not
   the builder self-blessing its own output. For docs / analysis a
   deterministic `verify` block (or planner self-validation) is enough. No
   plan reaches its goal without a step that checks the work.

**Author and dispatch the review leg as a REVIEWER, not a worker (v7
P4.1).** Dispatch it `pool_spawn_worker(..., role="reviewer")` — the
dispatcher then code-composes and sends the review brief (reviewed action
ids + descriptions, acceptance criteria, evidence paths, spec_ids) into
the reviewer's inbox, so it can never boot into silence (the d100 empty-
inbox no-op). The reviewer stamps `record_branch_verdict` per reviewed
action and closes its OWN leg with `record_action_status` (own-leg-
guarded). Do NOT re-dispatch review work as `role="worker"` — that was
the d67/d100 workaround this replaces, and it produced testers, not
reviewers.

**When a verdict returns `fixed_inline=true`, dispatch ONE verify-only
leg (v7 P4.2).** The FSM hands you a latched `DISPATCH_VERIFY_LEG`
advisory naming the action: author a small `task_class="verify"` action
whose description lists the fixed action's `acceptance.verify` commands
verbatim and instructs `get_guide("verify-only")`, and dispatch it as a
normal worker. It re-runs the commands and transcribes raw output —
judgment-free, so the reviewer-reviews-reviewer regress stops there.

That is the whole mechanism: actions reach `done` ONLY on evidence + a reviewer pass;
the planner's only job here is to make sure the review/verify step is
actually in the plan.

## When the plan is written (and its dep-free actions already dispatched)

Because you dispatched each dep-free action as you authored it, the
author→drive split has largely dissolved: by the time the plan exists,
its first wave of workers is already in flight. The plan now exists, so
`next_action(handle_type="plan")` will succeed and returns the drive
instructions (`dispatch_action` for actions whose deps have since
cleared, `wait`, `done`). Load `get_guide("planner-phase-drive")` and run
the loop; it re-grounds itself off `next_action` (and, after a
compaction, `get_recipe_digest`) — there is no context to compact by hand
here. Your heartbeat re-invokes you on the next wake and the drive loop
carries the plan the rest of the way to `done`.

## Verify & concerns authoring gotchas (folded from foreground lore, W15/a6)

- **A `concerns=[X]` tag needs a `spec-X` ruleset layer** or the worker's
  `assemble_ruleset` errors on that `concerns` tag; the field is IMMUTABLE
  post-authoring. Check the layer exists up front (as you do for a tech
  `specialization`). If a layer is disproportionate, proceed-without — the tech
  spec's in-craft rules + planner review cover it (workers degrade gracefully;
  the missing layer is not a blocker).
- **A `glob_matches` verify does NOT expand brace alternation** — `{ts,tsx}` is
  matched literally (0 hits). Use `**/*.ts*` or a single extension, or a real
  deliverable false-parks in `verify`.
- **Never gate a recompiled spec doc on a `file_min_bytes` floor ABOVE its
  current size.** `write_specialist_doc` DISTILLS (it doesn't dump), so an
  enriched doc can get SMALLER; content fidelity comes from human review, not
  byte count. A floor is fine only as a below-current not-truncated sanity check.
- **Sequence parallel actions that share a build module/type via `depends_on`.**
  Concurrent forks editing one Maven/Gradle project break each other's consumers
  (a shared type change → sibling files stop compiling), and file-based verify
  gates don't check whole-tree compilation. Make the breaking-change owner's
  definition-of-done "tree compiles/tests green — all consumers updated," tell an
  innocent finished sibling to mark done now (don't touch sibling-owned files),
  and keep a final whole-tree compile/test action `depends_on` all impls.

## Anti-patterns

- **Contorting the work to fit a shape** — picking a shape first and
  deriving the DAG from it. The DAG comes from the work; a shape is a
  pitfall checklist matched afterwards, and matching none is normal.
- **Loading more than one shape guide**, or loading the drive guide here.
  At most one shape checklist; author each action and dispatch it as
  authored; the drive guide takes over for the remaining deps + close.
- **Authoring the whole plan before dispatching anything.** The default is
  interleaved — a dep-free action's worker launches the moment its brief
  exists, not after the last action is written.
- **Hand-authoring a full plan object** instead of `create_plan` +
  `add_action`.
- **Discovering a missing specialist mid-dispatch** because you skipped
  the up-front `neuron_search` sweep.
- **A `command` verify that re-runs the worker's expensive build.** Check
  the artifact, not the build.
