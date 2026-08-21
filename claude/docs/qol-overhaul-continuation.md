# QoL overhaul — session continuation doc (2026-08-21)

**Purpose:** resume the framework quality-of-life overhaul after a session
compact. Plan file: `~/.claude-personal/plans/staged-zooming-fountain.md`
(approved). Friction checklist: `docs/design/qol-baseline.md`. This doc is
the single source of truth for what is DONE, what remains, and the
operator's binding rulings. Read it whole before doing anything.

## Where it stands — commits this run (all pushed to main)

1. `c08451f` — **Phase 0**: end-to-end mock-recipe drill (habit tracker,
   design-first) through the REAL tool layer, role-playing every seat by
   its card. 23 frictions + 5 positives → `docs/design/qol-baseline.md`.
   Also landed the authorized `.bridge.json` slug fix (gpt-5.6 →
   gpt-5.6-sol) + live pain-ledger entries.
2. `385887f` — **Phases 1+2 wave 1**: param aliases; unknown kwargs refuse
   loudly (extra="forbid" on authoring models; create_object translates
   nested acceptance); writes echo minted ids; refusals carry field
   shapes; empty dispatch waves explain themselves; MCP boundary emits
   STRUCTURED TEXT (`tools/render_text.py`); orientation module
   `guides-src/shared/why-and-where.md` compiled into every card (budgets
   raised); position block on every action read (verbatim goal, step N of
   M, prev/next, serves); digest carries verbatim goal + drops
   recipe_saved noise + renders rationale_for_next; proposed bans
   filtered/labeled; sketch_covers patchable (pains #3/#5); eda.bat env
   parity; `.claude-pool` outputStyle=edp-terse + model 4-6→4-8.
3. `d3a7144` — **Phases 3+4 checkpoint**: typed `deliverable` form on
   outcome/step/action (enum incl. `runnable_app` + `pipeline`);
   `Outcome.user_path` (operator's own cold end-to-end path — the
   acceptor walks it); both ride the acceptor consult; producer-verify
   guard stands down for interactive/visual forms; **operator holds**
   (`Recipe.dispatch_hold` — pacing rules as machine constraints; wave +
   spawns refuse while held; neuron card teaches it); grounding brief
   delivered WHOLE (20k ceiling, 6000 lean-advisory); **Sol fabric**:
   `worker:asset`/`visual_critique` routes, write-capable
   `delegate_generate(task_class="asset", out_dir=…)` (Sol writes files),
   `images=[…]` threads through delegate_generate/delegate_review;
   worker/reviewer cards name Sol the visual authority; G-CHALLENGE
   retargeted to BIG recipes only (`EDP_CHALLENGE_GATE_MIN_STEPS`, def 3).

Suites at checkpoint: targeted + guide gates green. **A full-suite run
(claude + edp-pool) has NOT been re-run since `d3a7144`'s last edits —
run it first thing** (`uv run pytest -q --deselect
tests/test_w1_context_diet.py::test_phoenix_reachable`; pool: `cd
../edp-pool && uv run pytest -q`). Phoenix (:6006) is environment-only.

## The corpus audit (2026-08-21) — design ground truth

20 recipes + 31 compiled specs audited. Key findings (full detail was in
the session; the essentials):

- **The real failure axis:** acceptance evidence cited tests/commits;
  the operator's own path was never walked. b33936 closed "all 6 outcomes
  met with live verification" while the app never started (repair recipe
  2270d3 exists solely for it); 39fd30 published a site telling an online
  coach he was offline; #19 harness-site: "pathetic work… revert
  everything" against a recorded bar ("we arent writing an essay… UI
  should be catchy") never turned into a checkable Done-means.
- **Form substitution class:** visual/interactive asks discharged as
  markup/prose/records/probes (#19, #9, #1, #3).
- **Shapes in live use** (planners improvise beyond the 7-guide library):
  `research-synthesize`, `walking-skeleton/custom-dag`, `linear-build`,
  `diagnose-fix-verify`, `custom-dag`, `acceptance-repair-chain`.
- **Specs almost never engaged:** the Fit PWA (c08468, 10 steps) ran 9 of
  10 plans with ZERO specs. Spec engagement, not spec quality, is the
  first-order inconsistency cause.
- **Spec gaps:** no visual bar in the UI specs that governed b33936
  (react-typescript, doc-ingestion-frontend have zero "look at the
  screen"); `spec-universal` and `spec-edp-claude-core-framework-engineer`
  have NO compiled.md; 4 docs lack "Grounded in"; 6-way duplicated
  google-pwa specs with different bars; project specs never carry coding
  standards.

## STATUS UPDATE (2026-08-21, post-compact run) — R1–R4 EXECUTED

R1 DONE: `planner-strategy-walking-skeleton.md` +
`planner-strategy-acceptance-repair-chain.md` shipped;
`strategy-library.md` is now the goal-kind selection index; vocabulary
swept in planner/worker/reviewer cards (shape = high-level strategy
skill, spec docs = low-level strategy skills; field/guide names kept as
aliases); `no_low_level_strategy` dispatch ADVISORY live in
pool_spawn_worker (build leg + ≥3-step recipe + no spec_ids).
R2 DONE: `.specs/spec-universal/compiled.md` authored (MIT 6.102 triad,
GoF/Fowler/Pragmatic/McConnell/12-factor, mapped to the v5 entries);
specialist.md gained cut-it-LOUDLY (+`cut` in the close body), the
dedup rule (`neuron_search` granted to _SPECIALIST), and the mandatory
visual/UX-bar section; acceptor.md gained the user_path walk law.
R3 DONE: curiosity consult carries `user_goal_verbatim`;
`awaiting_user_iteration` protocol in curiosity+neuron cards (done only
on a sign-off round); batch verbs `record_outcome(outcomes=[…])` and
`add_action(actions=[…])` (atomic, single save); role-map images via
the Sol write path (docs/maps/). F10/F20 deferred with reasons — see
qol-baseline.md final disposition.
R4: re-drill 28/28 PASS; tool audit 106 results / 93 tools, zero JSON;
suites green (broker 33, pool 319, claude full); Sol second review run
and adjudicated. Regressions: tests/test_qol_r1_r3.py (8).

## REMAINING WORK (in order) — [historical; executed above]

### R1 — Strategy-skill layer (the operator's "not a framework" charge)
- High-level strategies (rename: shape = high-level strategy skill for
  agentic-plan): legitimize observed live shapes as guides —
  add `planner-strategy-walking-skeleton.md` and
  `planner-strategy-acceptance-repair-chain.md` alongside the 7
  `planner-shape-*` guides; sweep naming shape→"high-level strategy" in
  cards/guides (keep `shape` field name + old guide names as aliases;
  stores contain them). The strategy-library guide becomes the selection
  index by GOAL KIND (research / build / fix / creative / proof).
- Low-level strategies (specialization = low-level strategy skill(s) for
  worker/reviewer): **spec-engagement advisory** — when
  `pool_spawn_worker` dispatches a build action on a plan whose recipe
  has ≥3 steps and the action carries no spec_ids, append a loud
  advisory ("who taught this worker the house style? no low-level
  strategy doc is stamped") — advisory, NOT a gate (intelligence over
  guardrails).
- Vocabulary sweep in guides/cards per the operator's explicit rename
  ruling. Bootdocs recompile + guide gates after.

### R2 — Low-level strategy depth
- Compile `spec-universal` (`.specs/spec-universal/compiled.md`): the
  engineering floor — architecture/design-pattern/coding-standard
  baseline distilled from authoritative published sources (operator ruling:
  explore MIT/Stanford/classic material via WebSearch — distill, never
  paste). Several existing docs already defer to it by name.
- Specialist card (`.claude/commands/specialist.md`, hand-maintained):
  add (a) the duty to FLAG goal directives it scopes out (softening
  "project-agnostic: cut it" → "cut it LOUDLY in the training-complete
  report"), (b) a MANDATORY visual/UX bar section for any spec whose
  scope touches a human-visible surface ("a green gate does not
  discharge looking" — copy the phrasing from
  spec-application-design-language, the corpus's best), (c) dedup rule:
  before creating, search existing specs; extend, don't fork.
- The acceptor card (`.claude/commands/acceptor.md`, hand-maintained):
  add the user_path law — an outcome carrying `user_path` is judged by
  WALKING it cold; met_evidence citing only tests/commits is not
  evidence. (The consult body already ships `user_path` + `deliverable`.)

### R3 — Phase 5 remainder
- Curiosity lifecycle: gets the VERBATIM GOAL in its consult body (add
  `user_goal_verbatim` to the consult body in ConsultCuriosity when
  recipe resolvable); stays open for operator iteration on the sketch
  (new status `awaiting_user_iteration` between awaiting_fidelity and
  done — closes ONLY after reviewing the final recorded recipe AND the
  operator had the chance to iterate).
- Batch authoring verbs (latency): accept `outcomes=[...]` on
  record_outcome or a new batched form; actions list on add_action —
  collapse the serial ceremony.
- F20 seat-gating consistency + F10 fidelity-protocol order (baseline
  doc) — lower priority; fix if cheap.
- Visual role-map images (`docs/maps/`, one per role, generated via the
  Sol bridge write path now live) referenced from cards.

### R4 — Verification (the run is NOT done until this passes)
1. Full suites: claude + edp-pool + edp-broker.
2. **Re-drive the SAME mock recipe end-to-end** following the UPDATED
   guides (drill driver + scenes live in the OLD session scratchpad —
   likely gone; recreate driver.py from the pattern: make_context(scratch
   home) + build_registry per role env, stub state persisted to JSON).
   Check off every item in `docs/design/qol-baseline.md`; append the
   final disposition.
3. Tool-output audit: script calls EVERY MCP tool (well-defined mocks),
   asserts structured-text non-JSON returns; eyeball readability.
4. **GPT SOL SECOND REVIEW (operator directive, verbatim ask):** before
   closing this task, call Sol — plain question: *"is this framework
   generic and does it cover all my pain points"* — give it this doc,
   `docs/design/qol-baseline.md`, and `git log`/diffstat of the four+
   commits. Mechanics: `run_sol(prompt=…, workdir=r"C:\Projects\Learning\
   eda-base3", sandbox="read-only", caller="qol-overhaul",
   advisor="sol", effort="high", new_thread=True, timeout_secs=1800)` —
   launch DETACHED (10-min harness cap orphans a foreground codex):
   Start-Process the claude venv python on a runner script,
   RedirectStandardOutput to `.sol_review_out-qol.txt`, poll with bounded
   Wait-Process. Adjudicate its findings (proposals, not orders), fix
   what's confirmed, report the verdict to the operator.
5. Ledger + commit + push.

## Operator rulings (BINDING — collected this session)
- All five strands, one campaign; don't destroy the framework.
- Pipeline: goal → ocak audit (curiosity) → planner (high-level strategy
  skills; budgeted — 1 worker when 1 ships it; reviewers at the end for
  coherence, not beautiful DAGs) → worker/reviewer (low-level strategy:
  brief + compiled.md; architecture + design patterns + coding standards
  always).
- Renames: shape = high-level strategy skill; specialization = low-level
  strategy skill(s).
- Adversarial review: generated CODE, not the planner's own plan; big
  recipes only; Sol is the adversary (Fable trips safeguards — never
  adversarial).
- Sol = multimodal visual/creative authority, used wherever needed;
  image gen = tell Sol via the bridge to write files into a dir (DONE:
  delegate_generate asset path); enums + proper tool descriptions
  everywhere so no wrong strings.
- MCP returns structured text, not JSON (DONE at the boundary).
- Curiosity understands what it plans for; closes only after reviewing
  the generated recipe; stays open for iteration.
- edp-terse output style STAYS; spawned-shell settings parity with
  eda.bat (DONE).
- Lean everywhere; visual maps for role orientation.
- Mock-drill before AND after (before: DONE; after: R4.2).
- **Sol reviews this whole overhaul before close (R4.4) and similar Sol
  involvement becomes standing framework doctrine.**
- Don't overfit to one recipe — design against the whole corpus (the
  audit above is the ground truth; the operator called out overfitting
  once already).

Standing owner doctrine: intelligence over guardrails; no spoon-feeding
(strategies carry behavior, not hardcoded prompts); models.json is truth;
no incident lore in agent-visible text; commits carry
`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; bootdocs
recompile for card/guide changes (`python -m edp_claude.bootdocs`) and
run the guide gates (test_w4_roles, test_s26_guide_tool_names,
test_v7_bootdocs, test_activators_env_brief) after every guides-src edit.

## Session lessons (avoid re-learning)
- NEVER edit guides-src/manifest while a full suite runs — the drift
  gates read files at runtime and flake.
- Code (.py) edits are safe mid-run (imported at collection).
- Bash heredocs chaining `&&` around `uv run python - <<EOF` breaks into
  a REPL on this host — write a script file and run it.
- Bare `python` hits the Store shim (exit 9009) — always `uv run python`.
- `.claude-pool` is gitignored — `git add -f` the two config files only.
- Pool skeleton settings are NOT tracked by default; changes there are
  local-live immediately.
- The live fleet still needs a STACK RESTART for all of this (pool F36+
  and everything in this overhaul) — operator's action.
- Sol campaign Round 15 (adversarial hardening) is PARKED separately:
  `docs/adversarial-campaign-round15-continuation.md` — do not confuse
  the two workstreams.
