# Observations — Q&A rounds, 2026-08-17

Working list of changes from the Q&A rounds. **STATUS (end of implementation
pass, same day): 1497 tests pass; 1 pre-existing environment failure
(Phoenix :6006 liveness check — stack down; fails on HEAD too).**

| Item | Status |
|---|---|
| F1 role-scoped registration + drift test + eda.bat | DONE |
| F2 compiled recipe brief (renderer / save hook / detail='brief' / drift test) | DONE (Layer 1; Layer-2 advisor distillation deferred) |
| F3 shadow OFF by default + arm_wiring + cards rewired | DONE (files kept for EDP_SHADOW=1 diagnostic; delete after stability) |
| F3b snapshot planes emit {snapshot, changed} | DONE |
| F4 shadow brief silent cut | RETIRED with F3 |
| F5 steer_worker verb + planner grant + card | DONE |
| F6 flow-down gate: advisory at dispatch, enforced at step close | DONE |
| F7 dead-letter warning to sender on broker_send | DONE |
| F8 worker cron literal | RETIRED by arm_wiring (numbers resolve server-side) |
| F9 classic reviewer deafness | DONE (reviewer card boots arm_wiring) |
| F10 where-you-stand / brief pointers in cards | DONE |
| F11 advisor drafts the decomposition (plan_sketch on clear) | DONE (card-level) |
| F12 scheduled progress review (review_due + progress_review event) | DONE |
| F13 ADJUDICATE rides every plan tick | DONE |
| F15 schemas as MCP resources + read-once discipline | DONE (edp://schema/{name}) |
| F16 neuron identity (eda.bat EDP_ROLE=neuron) | DONE |
| F17 worked examples restored selectively | PARTIAL (planner sketch/concern example; sweep the other laws next) |
| F19 evidence-carrying WAIT; pool-side crash publish verified pre-existing | DONE |
| F20 G-SPEC close gate | DONE |
| F21 G-ACCEPT final acceptance pass | DONE (EDP_ACCEPT_GATE kill-switch; conftest defaults gates off for the legacy suite) |
| F22 G-CHALLENGE + challenge_waiver | DONE — REVISED same day (owner: "a worker could have been working — we just lose time"): advisory at dispatch, ENFORCED at step close; workers build while the plan is challenged |
| F23 seats verified; EDA_MODEL override in eda.bat | DONE |

## F24 — NEW (live incident, 2026-08-17 3pm): in-flight MCP calls freeze across turn boundaries
- Measured: a4 reviewer `pool_spawn_worker` dur_ms=1,656,256 (27.6 min) with ZERO
  MCP-server log activity 09:10:43→09:38:16, then full execution in ~3 s at the
  planner's next heartbeat tick. Workers spawned in 1.5-2 s because their calls
  returned mid-turn. Mechanism: the planner ended its turn with the dispatch in
  flight; the harness backgrounded it (task k31hrfdlr) and the stdio MCP session
  suspended until the next wake (= the 1800 s heartbeat, exactly the observed gap).
- Fixes applied: planner card drive-loop law "NEVER end your turn with a spawn in
  flight"; `_reviewer_git_block` moved off the event loop (asyncio.to_thread +
  15 s budget) so the sync git subprocess can no longer push a dispatch across a
  turn boundary on a big workspace.

## F25 — NEW (live incident #2, s4 planner wedge + dead wiring)
- Three failures in one transcript:
  1. **Terminal-plan wedge** — step reopened (o5 fix) while its plan sat
     terminal-succeeded; plan_id is deterministic so no fresh plan; terminal
     refused re-create → no author surface. FIX: `create_plan(reopen=true)`
     resets terminal → dispatching, preserves done actions, worklogs the
     reopen; refusals on the old paths now name it.
  2. **Empty rewire after GC** — the observe TTL sweep took an idle shell's
     indexed spec artifacts; specs_for_handle skipped them; the resume rewire
     handed back EMPTY wiring and the shell hand-composed a wrong monitor
     (FileNotFound exit 1). FIX: GC never sweeps indexed sids
     (all_indexed_sids); an empty hand-back carries empty_wiring_note naming
     arm_wiring().
  3. **Monitor "exit 15, no stderr"** — no code path in driver/pool exits 15;
     signature of harness-side task termination. UNRESOLVED — watch whether
     it recurs post-restart with arm_wiring-composed specs; the planner's
     "driver refuses terminal plans" theory is wrong (the driver doesn't
     read plan state).

## F26 — NEW (live incident #3, close_recipe backgrounded + froze)
- "Close failed on a transient G-COMMIT timeout (git status >10s)" then the
  retry backgrounded again — the F24 pattern at a second call site: the
  commit gate ran `git status`/`rev-parse` as SYNC subprocesses on the MCP
  event loop; a slow workspace pushed the call past the harness's background
  threshold; the neuron "held" with the call in flight → frozen until the
  next tick.
- FIX (superseded same day by owner ruling — "remove that piece of
  garbage"): `_git_capture` is DELETED outright. MCP tool calls launch NO
  external programs. The reviewer brief's `git` entry is now an INSTRUCTION
  (run status/diff/log YOURSELF in the named workspace); the G-COMMIT close
  gate is RETIRED (`commit_waiver_ref` accepted-and-ignored for caller
  compat); committed-tree evidence = the reviewer's own in-shell git re-run
  + the worker's stated landed commit + the G-ACCEPT pass. A concurrent
  live memory confirmed the in-server git check hung >1800 s on a clean
  Windows repo. The neuron card keeps the in-flight law from F24.
- HOST ADVICE (not code): on big workspaces run
  `git config core.fsmonitor true` + `git config core.untrackedCache true`
  — `git status` drops from ~10 s to sub-second, which removes this entire
  class at the source.

## F27 — NEW (jobsearch post-mortem): named artifacts are requirement sources
- FULL TRACE of the "poor results" recipe: F11 WAS live — Fable (curiosity)
  authored the plan_sketch; the neuron transcribed it near-verbatim into
  o1-o5/s1-s5; the planner + worker implemented it faithfully. Fable
  ground-truthed the skill DIR (file list) and its overrides/contract but
  never carried the skill's own bars ("20-30 validated results, >=40
  inspected, multiple source families") into any outcome — zero grep hits
  anywhere in the record. The "ONE test run" narrowing that produced 4 rows
  is literally the sketch's risk-note line, propagated with perfect
  fidelity through neuron→planner→worker. Also found: the a2 worker relaxed
  the user's recorded "Keep strict (require disclosed pay)" answer
  unilaterally (documented in the run log, never escalated).
- FIX (applied): curiosity card — "A named artifact IS a requirement
  source": read it, carry its measurable bars into outcomes verbatim;
  narrowing a bar is a SCOPE decision to ASK the user, never a risk note.
  G-ACCEPT judge instruction now includes "ANY artifact the goal NAMES".
- Open: worker-side guard for "recorded user answer overridden by caveat"
  (the disclosed-pay relaxation should have been an ask_above).

## F28 — NEW: right-sizing at authoring (the "5 steps vs one ChatGPT response" question)
- Root economics: orchestration buys durability/parallelism/verification,
  never intelligence — its per-step fixed cost (planner+workers+review+
  gates, minutes + ~10k+ tokens each) cannot amortize on one-sitting work,
  so on small goals the fleet is mathematically incapable of beating one
  direct pass. Nothing in the framework asked "should this decompose at
  all?" — the cards celebrated decomposition, so a one-hour job became 5
  serial steps × full ceremony.
- FIX (applied): neuron Law 5 rewritten — "Right-size before you decompose:
  steps buy parallelism and resume points, never tidiness; a one-sitting
  goal is ONE step (or done directly outside a recipe); two steps that
  share one worker's sitting are one step." Curiosity sketch rule — line 1
  of every plan_sketch states whether the goal fits one worker's sitting.

## F29 — NEW: the sketch→map seam gets eyes (curiosity survives to verify)
- Hole: curiosity self-closed the moment it delivered plan_sketch; the
  neuron's transcription into outcomes/steps was reviewed by nobody, and
  the user's comprehension signoff showed a paraphrase brief, not the
  sketch. (The neuron's "EnterPlanMode" analog existed — AWAIT_USER — but
  approved a summary of a copy of the plan.)
- FIX (applied, card-level): (1) the comprehension brief shown to the user
  IS the plan_sketch verbatim + step mapping; (2) clear=true no longer
  closes curiosity — Step 4: the neuron sends the RECORDED outcomes+steps
  back to the same shell, which diffs them against its own sketch and
  replies fidelity ok/discrepancies; it closes only after that reply (or
  reap on abandonment). Advisory-weight by design (no new hard gate —
  the G-CHALLENGE serialization lesson).

## F30 — Codex-bridge adversarial review of F1-F29 (2026-08-18) + fixes
- Ran gpt-5.6 (fresh thread, findings-only) over the design record + three
  compiled cards. 17 findings; raw output in claude/.sol_review_out.txt.
- FIXED same day: (#4) curiosity clear now replies status='awaiting_fidelity'
  — only the fidelity reply is 'done' (card + tool notes); (#5) order is now
  record map → fidelity diff → THEN user signoff on the verified map (post-
  signoff map edits force re-signoff); (#6) neuron boot reordered — recipe_id
  exists before arm_wiring; (#13) this doc's F6 line corrected to match the
  implementation (enforced at step close); (#1 middle path, owner-approved)
  the neuron verifies the tree in ITS OWN shell at close (git status +
  rev-parse in Bash, output in close evidence) — no MCP tool runs git.
- OPEN design calls (adjudicated real, awaiting owner ruling): (#2) G-ACCEPT
  checker is neuron-fed — strongest cure is an independent reviewer-leg
  acceptance shell; (#9) G-CHALLENGE keys on action COUNT, so batching ducks
  it — should key on step estimate/risk; (#7/#8) arm_wiring lifecycle not
  atomic (orphaned indexed sids GC-protected forever; re-run can double
  Monitors); (#11) reopen keeps stale done evidence when the bar changed;
  (#14) G-SPEC misses stale GLOBAL specs; (#15) fidelity round has no retry
  protocol. Accepted-by-design: #3 (fidelity advisory weight), #16 (waiver
  is an audited sentence), #10/#12/#17 (inherent scope statements).

## F31 — the ACCEPTOR role (owner ruling 2026-08-18): Fable's final pass in
## its own shell, FSM-explicit
- New role "acceptor" (advisor seat, /acceptor card, own toolset, read-only
  CRUD): fetches its OWN evidence — the checker is never fed by the party
  it judges (closes Sol #2). Verifies against the VERBATIM goal + named
  artifacts; fixes small verifiable defects in-shell; records
  acceptance_verdict.
- FSM-explicit: InstructionKind.DISPATCH_ACCEPTANCE emitted at
  all-outcomes-met (pure FSM); the tool layer downgrades to DONE on a
  recorded 'pass' (or gate off). Neuron obeys with dispatch_acceptance
  (consult-before-spawn). Interim passes mid-recipe:
  dispatch_acceptance(interim=true) — wired into the F12 review_due
  obligation ("a spawn in between steps to do a plain review").
- Subagent quality rule (card): Fable may fan out Sonnet/Haiku subagents to
  GATHER; their reports are untrusted drafts — it spot-verifies every
  load-bearing claim; the verdict is its alone.

## F32 — remaining Sol findings taken up (owner: "the rest are valid")
- Adversary charter (#indep): adversarial_challenge now carries a
  PREDEFINED charter — independent framing, never codes, suggested_fix per
  finding, priority hunt list.
- #9: G-CHALLENGE keys on RISK, not action count — required when actions >=
  min OR the step estimate is big (EDP_CHALLENGE_GATE_MIN_HOURS=2 /
  _MIN_TOKENS=50000), so batching cannot duck the adversary.
- #7: indexed subscriptions age out at a LONG TTL (7d,
  EDP_REACTIVE_INDEXED_TTL_SECS) and are unregistered on sweep — no more
  immortal ghosts.
- #11: create_plan(reopen=true) returns a stale-done warning naming the
  preserved actions to revalidate (status='verify' / supersede).
- #14: G-SPEC also refuses on DECAYED consulted specialists (stable but
  trained past EDP_SPEC_DECAY_TTL_DAYS=90).
- #15: fidelity retry protocol — neuron resends the SAME round once after a
  silent heartbeat; curiosity replies idempotently (same verdict, never a
  re-diff).

Open threads: delete shadow.py/shadow_spawner.py once stable; F2 Layer-2
(advisor-distilled narrative, epoch-stamped); F17 full example sweep;
steer-ack ledger nested-ack fix; rx.orphaned dash/colon fix (excluded from
composed wiring specs meanwhile).

Original findings follow (historical record of the Q&A).

**Doc-wide principle (owner ruling, round 2):** every agent-visible write is strategic —
short, imperative, one worked example, one paragraph of big-picture. No 20-30k-token
guides; agents treat unexplained bulk as optional. Validation moves INTO code (evidence
pushed into instructions) instead of expecting agents to burn tokens validating.

## F1 — Per-role tool registration (revised, round 2)
- `.mcp.json` pins `EDP_ROLE_SCOPE=warn`; all ~87 tools visible everywhere.
- Fix:
  1. MCP server registers ONLY `toolset_for_role(EDP_ROLE)` at startup.
  2. REVISE `ROLE_TOOLSETS` and add a drift test: every registered tool class must
     appear in >=1 role set or an explicit `_UNSCOPED`/retired list — so new tools
     can never silently fall outside the role map.
  3. BASE SHELL (spawned by `eda.bat`, not the pool): stamp `EDP_ROLE=neuron`,
     pass `--dangerously-skip-permissions`, and pin `--model claude-opus-4-8`
     (models.json binds pool spawns only; the base shell must self-pin).

## F2 — Compiled recipe/plan brief (revised: idempotency + coverage, round 2)
- Recipe is bookkeeping-shaped; only readable narrative is state-synthesis.md
  (step-close only, opt-in). Specs' compiled.md proves the readable form works.
- Fix: a PURE renderer `render_recipe_brief(recipe) -> markdown` (goal verbatim →
  outcomes+met → active decisions as prose → constraints/bans → open steps with
  concerns + acceptance_sketch → pending). Same for plans.
  - **Idempotency guarantee:** the renderer is a deterministic pure function of the
    stored JSON — same state, byte-identical brief. Regeneration hooks into
    `RecipeStore.save()`/`PlanStore.save()` (every mutation path already funnels
    there), so the brief can never lag the record.
  - **New-field coverage:** a CI drift test walks the Pydantic schema and asserts
    every field is either rendered or named in an explicit EXCLUDED list — a new
    recipe/plan field fails CI until the renderer accounts for it.
  - **Concerns visibility:** concerns get a dedicated brief section AND repeat on
    each step/action row; worker/reviewer grounding PREPENDS the brief (or its
    scoped slice) so a subagent cannot miss cross-cutting obligations.
  - **Quality (round 3):** code guarantees structure/completeness/currency, NOT
    prose quality. Two layers: Layer 1 = deterministic skeleton (idempotent, the
    contract). Layer 2 = advisor-seat distilled narrative (compiled.md pipeline
    shape: LLM distills, gate reviews), regenerated at step close / on demand,
    STAMPED with the grounding epoch it distilled at (LLM output can't be
    idempotent — staleness must be readable instead). Source quality: write gates
    + strategic-writing rule apply to agents authoring decisions too.

## F3 — REMOVE THE SHADOW (owner ruling, round 2: "I just want it gone")
Replaces the earlier Monitor-tail proposal. The shadow hijacks the console, delivers
machine events as user-role text, and killed agent-owned wiring. Restore monitor+cron
for EVERY role (the neuron pattern), with the token cost solved at the tool layer:
- New MCP tool **`arm_wiring()`** (the "form you tick"): reads role+handle from env,
  composes the role's default rx spec server-side (the same table shadow_spawner's
  ROLE_SPECS held), creates the subscription, and returns pre-filled, verbatim:
  `monitor_cmd` (run under Monitor) + CronCreate args (canonical prompt, resolved
  heartbeat number). Optional flags for extras (e.g. `watch_plan=true`). Boot wiring
  becomes 3 calls total (arm_wiring → Monitor → CronCreate); no rx-DSL learning, no
  guide reading, no guessing.
- Worker/reviewer brief delivery returns to the classic boot (check_inbox +
  read_object) — 2 tool calls, correct attribution, full untruncated grounding
  (also retires F4's silent [:4000] cut, which dies with the shadow).
- What the shadow also did and its replacements:
  - crashed-shell flowback → MOVES POOL-SIDE (round 3): the pool is the OS parent
    of every shell; on process exit without recorded terminal status the POOL
    publishes `crashed` to the parent inbox. Crash detection must never depend on
    the crashed party emitting anything.
  - close-on-terminal → agent-owned close (cards) + Stop-hook backstop +
    pool close_when_idle (exist).
  - driver supervision (deaf-subscription re-arm) → `arm_wiring` re-issue is
    idempotent (reused=true); add a liveness line to reconcile output: "your driver
    for sub-X emitted last at T" so deafness is visible in the loop the agent
    already runs.
- Default `EDP_SHADOW=0`, then delete shadow.py/shadow_spawner.py once stable.

## F3b — Classic Monitor must output WHAT CHANGED (round 2)
- Driver already emits full event dicts for event planes (broker/worklog/events).
  Snapshot planes (rx.pool/rx.plan) emit the changed snapshot, not the delta.
- Fix: for snapshot planes, emit `{"event": {...}, "changed": {<key>: {from, to}}}`
  so a wake names the transition (e.g. a4: in_progress→failed) without a reconcile
  round.

## F4 — Shadow brief `[:4000]` silent cut — RETIRED BY F3 (shadow removal).

## F5 — Planner steer path
- Card says "send a steer over the broker"; planner toolset likely lacks broker_send
  (memory: only reply() on worker-opened threads works).
- Fix: routed `steer_worker(action_id, body)` verb — resolves address from the plan,
  enforces steer_ack correlation. Verify ROLE_TOOLSETS while doing F1.

## F6 — Flow-down gate serializes authoring; first worker spawns late
- `_step_flowdown_gaps` refuses ANY dispatch until every concern/sketch line is
  covered → full plan before first spawn, contradicting "author+dispatch interleaved".
- Fix: dispatch carries an advisory only; the full-coverage check is ENFORCED
  at STEP CLOSE (record_step_result). (Corrected 2026-08-18 — this line
  previously said "plan ratification", contradicting the implementation;
  Sol adversarial-review finding #13.)

## F7 — Broker dead letters (revised: WHO ACTS, round 2)
- Send to a nonexistent/never-polled inbox succeeds silently.
- Fix: surface to the SENDER, synchronously — the send result carries
  `delivered_to_known_inbox: false` + the known-alias suggestions; the sender is the
  one shell guaranteed alive and contextful at that moment. Backstop: reconcile
  advisory to the neuron listing aged undelivered mail. Nothing async-only.

## F8 — worker.md literal `${EDP_WORKER_HEARTBEAT_MIN:-5}` in cron
- Fix: bake the resolved number at bootdocs compile time. (Matters more post-F3:
  every role arms classic cron again — via arm_wiring, which resolves it server-side.)

## F9 — Classic reviewer deafness
- reviewer.md arms no wiring. Post-F3 fix: reviewer card boot = arm_wiring like
  every other role.

## F10 — "WHERE YOU STAND" header in every brief/card
- Goal verbatim (1 line) → your step → your action → what accepting it unblocks →
  one paragraph of WHY (FSM anti-drift purpose). Strategic-writing rule applies.

## F11 — Advisor seat should PLAN, not just interrogate
- Curiosity (Fable) only asks questions; never drafts decomposition, never reads code.
- Fix direction: comprehension produces a plan-quality readable artifact (advisor
  drafts goal decomposition/workstreams as markdown, repo access allowed); recipe
  becomes the durable state of that plan via F2's brief. Keep the user-question loop;
  drop the ceremony that doesn't serve it.

## F12 — Scheduled plan-vs-actual review ("scrum")
- Every N step closes or M hours, next_action emits a REVIEW instruction:
  budget_status + outcome coverage + open risks → one gate surface to the user.

## F13 — Plan FSM never says ADJUDICATE
- Open challenges surface only as spawn refusals. Fix: plan next_action emits
  ADJUDICATE_CHALLENGES when the sidecar has open ids.

## F14 — superseded by F21 (final acceptance pass covers close-time adversary).

## F15 — Schema: read once, reference by symbol (revised again, round 3)
- Round-2 "schema in tool descriptions" WITHDRAWN as spoon-feeding (owner ruling).
- Three-tier rule:
  1. Refusals name legal values (error messages doing their job — kept).
  2. NO incident lore in agent-visible text ("X failed once → always Y" is banned);
     incidents live in code gates + tests only. Guides stay generic + agentic.
  3. Canonical object schema is READ ONCE at boot and referenced thereafter —
    expose recipe/plan/action/step as MCP RESOURCES with stable URIs
    (harness supports ReadMcpResource); cards say "your objects: edp://recipe,
    edp://plan — read once at boot" and never restate a field. Cache-friendly
    (stable early context, pays once vs per-request description bloat).
    Compaction risk handled by the existing reground path (re-read one resource).

## F16 — Neuron identity
- Fold into F1 item 3: eda.bat stamps EDP_ROLE=neuron; whoami resolves neuron inbox
  from open-recipe state, not a prose note.

## F17 — Restore worked examples, not length
- Baseline cards (474/530/209 lines) worked because of examples. Keep the diet;
  add one 2-3-line example per authoring-law line (acceptance_sketch,
  sketch_covered_by, concerns). Strategic-writing rule applies.

## F18 — Wave/pool coupling — subsumed by F19 (evidence-carrying instructions).

## F19 — NEW: WAIT instructions must carry evidence (the FSM-trust fix)
- Observed: worker crashes, FSM says wait, neuron sits 30 min. Agents either trust
  the FSM blindly or would burn 3-10k tokens validating it.
- Fix: validation moves into code. `_enrich_wait` already names awaited actions —
  now ALSO probe pool liveness for each awaited handle and stamp it into the WAIT
  payload: `awaiting: [{handle, liveness, last_worklog_ts}]`. A dead/phantom handle
  makes the instruction itself say "a4 is DEAD — reconcile will re-dispatch; do not
  wait". Cheap agent-side check when doubt remains: `status_ping` (~1 liveness call
  + 1 worklog line, few hundred tokens) — name it in the card as THE sanctioned
  doubt-check.
- Round 3 — "what if the crash produces no event?": detection never depends on
  events from the child. Layer 1: pool-side exit→publish (see F3 — OS-level,
  guaranteed). Layer 2: the liveness stamp here is a PULL executed when the WAIT
  is built; the cron heartbeat guarantees a tick, so worst-case detection latency
  = one heartbeat interval, bounded and known.

## F20 — NEW: recipe closed while specialist never compiled
- Root cause: Guard B fires only at worker spawn when an action carries spec_ids.
  The TRAINING flow (train_specialist → write_specialist_doc → pending_review) has
  no close gate; and specs are GLOBAL, so planners can stamp old recipes' specs —
  a recipe can look spec-healthy while its own training died.
- Fix: close_recipe gate — refuse while (a) this recipe spawned specialist sessions
  whose spec has no compiled doc, or (b) neurons this recipe created sit in
  pending_review untriaged. Reconcile advisory when a training shell dies.

## F21 — NEW: final goal-vs-delivery acceptance pass (the "did I get what I asked" gate)
- Today close = outcomes met with evidence + G-OUTCOME waivers + reviewer legs.
  NOTHING re-reads user_goal_verbatim against the delivered artifact end-to-end.
- Fix: close_recipe gains a terminal gate: an independent acceptance verdict —
  a checker/advisor-seat pass fed (user_goal_verbatim + outcomes + evidence +
  workspace diff) producing pass/gaps, recorded as an artifact; gaps block close;
  the USER's signoff is the final override. Enforced by the close gate, not by
  discipline.

## F22 — NEW: adversarial challenge is never called — enforce it
- Owner observation: codex usage never changes around a recipe; no agent calls it.
- Fix: extend G-ADJ — a plan's FIRST non-review dispatch requires either >=1
  recorded challenge for the plan or an explicit recorded waiver
  (record_context kind='challenge_waiver', rationale). Plus F13's instruction.

## F23 — Seats verified (round 2)
- models.json is correct post-investigation: judgment/builder/checker=claude-opus-4-8,
  advisor=claude-fable-5 (curiosity only). No Fable residue in the registry; the
  Fable-for-all run left no config. Remaining: eda.bat model pin (F1 item 3).

## F33 — Adversarial campaign Round 1 (prompts & cards lens), 2026-08-18
Full-framework Codex review, R1 per docs/adversarial-campaign.md. 20 findings;
raw output claude/.sol_review_out-r1.txt (gitignored). Verdicts + dispositions:

| # | Finding (short) | Verdict | Disposition |
|---|---|---|---|
| 1 | Fail review verdict never blocks plan success | CONFIRM | G-VERDICT: plan FSM reopens fail-verdicted done actions at the success boundary + bumps verify_failures (G-REWORK cap is the loop escape); reviewer cards now require passed= on every verdict |
| 2 | verify-only guide converts red checks into done | CONFIRM | verify-only.md: exit codes decide status — any non-zero/unexecutable → status=failed with verbatim output |
| 3 | Review brief is multi-target; reviewer card taught singular | CONFIRM | reviewer card (src+deep guide): target is a LIST, one verdict PER target, own leg closes only after every target verdicted |
| 4 | neuron-phase-b contradicts F29 awaiting_fidelity | CONFIRM | Phase B rewritten around awaiting_fidelity → record map → fidelity round → done |
| 5 | neuron-phase-e says direct close_recipe, omits acceptor | CONFIRM | Phase E rewritten: dispatch_acceptance → verdict pass → close; partial closes owe no pass |
| 6 | Specialist parks for answers with no wake plane taught | CONFIRM | specialist.md card: arm_wiring at boot + disarm at close; specialist-card guide: park-only-if-armed law |
| 7 | verify-only omits the enforced grounding echo | CONFIRM | folded into the verify-only.md rewrite (echo + teardown + close order) |
| 8 | dispatch_acceptance spawns unlimited rival acceptors | CONFIRM | in-flight latch: acceptance_dispatched with no later verdict returns the same acceptor idempotently; force=true is the confirmed-dead escape |
| 9 | Phase A resume path skips resume_recipe | CONFIRM | Phase A: resolve_recipe SELECTS only; resume branch calls resume_recipe + executes the rewire |
| 10 | Phase C add_step example refused by G-EST | CONFIRM | example now carries serves + estimate |
| 11 | Planner guides mandate blanket review legs the gate refuses | CONFIRM | planner-card.md + planner-phase-author.md: measured review policy (named risk triggers), matching the compiled card + write-gate |
| 12 | Phase C phase-label decomposition defeats F28 right-sizing | CONFIRM | Phase C: right-size before decomposing; one-worker goal = one step; phase-label split is now the named anti-pattern |
| 13 | Shared modules teach verbs the role cannot see | CONFIRM | vocabulary-core: map-not-toolset preamble + executor-seat loop note; terse-core: role-neutral evidence line |
| 14 | Phase D instructs nonexistent append_revision | CONFIRM | replaced with record_context(kind="north_star_update") |
| 15 | consult_curiosity catalog entry describes wrong schema | CONFIRM | catalog rewritten from the live schema (decision+context, context IS delivered) |
| 16 | seed_comprehension_specialists catalog promises dead roles/spawns | CONFIRM | catalog rewritten: registers records only, spawns no shells |
| 17 | Early-exit paths leak monitors/crons/seats | CONFIRM | disarm-before-close added to every early exit (reviewer, curiosity, worker, acceptor, specialist) |
| 18 | recipe FSM rationale advises removed /critic | CONFIRM | rationale routes to adversarial_challenge / interim dispatch_acceptance |
| 19 | Non-gate done satisfiable by bare assertion | REJECT (by design) | the gate flag IS the tier: G-RUNS execution proof protects outcome-bearing checks; requiring structured runs on every action re-serializes all work (the G-CHALLENGE lesson) |
| 20 | Curiosity card: two mutually exclusive first actions | CONFIRM | boot line now reads Step 0 then Step 1 |

Suite after fixes: 1516 passed, 5 skipped; only test_phoenix_reachable fails
(environment, :6006 down). Cards recompiled within budget (worker 2456/2500,
curiosity 1691/1700). One contract test updated (test_activators_env_brief
close-ordering → first-record < last-close; the boot early exit legitimately
closes without a status).

## F34 — Adversarial campaign Round 2 (memory & state layer), 2026-08-18
13 findings (raw: claude/.sol_review_out-r2.txt); OWNER RULING: "all worth
fixing". All 13 addressed:

| # | Finding (short) | Fix |
|---|---|---|
| 1 | Unlocked load-modify-save loses concurrent updates | store/ipc_lock.py (msvcrt/fcntl, reentrant) + optimistic version check in Recipe/PlanStore.save — stale save raises StoreConflict ("re-read and re-apply"); fresh objects (version==1) adopt the disk version |
| 2 | Rollup races appenders; crash double-archives | rollup + append+rollup pairs run under the object lock; a re-run whose head tail-matches the last segment resumes the crash instead of re-archiving |
| 3 | Sidecars overwritten before main JSON (crash split-brain) | content-addressed sidecar names (context/d1-<sha10>.md): changed content publishes NEW bytes; old refs never overwritten; missing sidecar recreates at the same ref (fail-safe, byte-identity preserved) |
| 4 | Snapshots reference mutable sidecars (rollback lies) | same CAS fix — old snapshots keep hydrating old bytes; gc_sidecars sweep in compact_recipe_store deletes only files no live JSON or snapshot references |
| 5 | Gate evidence rolls out of the hot events tail | GATE_PINNED_KINDS (acceptance_verdict/dispatched, user_gate_answer, step_forced_done, progress_review) + grounding echoes carried into the rewritten tail (newest 200) |
| 6 | Cursors on sender timestamps hide late/equal-ts mail | broker append stamps per-inbox monotonic ts (max(sender, prev+1µs)), cache seeded from file on restart. RESIDUAL: cursor persists before the tool result returns — process death in that window skips mail; check_inbox(replay=true) is the recovery |
| 7 | plan:a1 / plan_a1 share one inbox file | read() filters by the message's resolved destination. RESIDUAL: mail addressed via an alias deleted later becomes invisible on replay (alias map is the resolver) |
| 8 | Rollup truncation makes rx followers deaf | _tail_jsonl detects size<pos, re-reads from 0, dedupes by record ts (equal-ts records within the same µs may dedupe — heartbeat is the catch-up) |
| 9 | search_context serves superseded decisions as active | returned decision rows cross-checked against canonical recipe (≤1 bounded load per decision-bearing search) + sidecar repaired in passing; w15 zero-load contract narrowed accordingly |
| 10 | Promoted spec amendments never drain on recompile | write_doc appends status="compiled" markers for the promoted set — the overlay drains exactly as the design note always claimed |
| 11 | One torn JSONL line poisons broker/spec reads | tolerant per-line parse (skip, never abort) in InboxStore.read/query/get_message + read_learnings |
| 12 | No fsync — acknowledged saves can un-happen | write_atomic fsyncs by default (EDP_FSYNC=0 opt-out; conftest opts the suite out); appends opt-in via EDP_FSYNC_APPEND=1 (trails are advisory; object state is the durable tier) |
| 13 | Neuron lifecycle/counters race (archived resurrection) | set_status conditional in SQL (archived is terminal; force=true un-archives), touch/flag increment in SQL |

Also this round (owner request): the /pain skill — role-agnostic framework
pain-point flight recorder. Any seat appends ONE structured JSON line to
docs/pain-points.jsonl (ts/role/handle/severity/area/symptom/expected/
evidence/workaround/cost) when the framework fights it (refusal vs card,
phantom verb, dead wake, improvising around a tool), then continues.
Trigger law compiled into every role card via seat-law + neuron/curiosity
sources; hand cards (acceptor/specialist) updated; budgets worker 2600,
curiosity 1800.

Suite: 1532+10 new pass across claude (only Phoenix env-fail) + 14 broker
tests (4 new). Tiering tests updated to the CAS naming contract; w15
steady-state contract narrowed (≤1 load on decision rows, 0 otherwise);
agentic-plan line backstop 230→250 (token budgets remain the gate).

## F35 — Adversarial campaign Round 3 (FSM & gates, split R3a+R3b), 2026-08-18
R3 burst the sol 900s turn cap twice → split into R3a (state machines, 10
findings) + R3b (gates, 13 findings); raw: .sol_review_out-r3a/-r3b.txt.
Owner ruling: fix all per recommendation. Also hardened from the incident:
per-delegate timeout_secs in .bridge.json (config decision) + planner-card
right-size-the-challenge law. 22 CONFIRM fixed, 1 PARTIAL (R3b#2 replay half
fixed, neuron-as-user-channel trust boundary accepted), 1 minimal (R3b#12).

Acceptance integrity (R3a#1+R3b#1+R3b#7, one package): acceptance_verdict is
acceptor-only (role-less shells exempt) with verdict enum enforced; the
server stamps a recipe fingerprint (goal+outcomes+steps) on every verdict;
DONE/G-ACCEPT honor only a FINAL pass whose fingerprint is current; the
dispatch latch is mode-matched (interim never suppresses final) and expires
(EDP_ACCEPT_LATCH_TTL_SECS, 3600) instead of wedging on a dead acceptor.

Plan FSM: G-DEPS (failed action blocking a pending dependent reopens with a
counted cycle — deadlock → bounded rework → G-REWORK freeze; lone failures
keep partial semantics) · G-VERDICT covers skipped actions · batch members
carry batch_owner (live head suppresses member re-dispatch in readiness AND
pool_spawn_worker; cleared at terminal) · record_branch_verdict requires
passed=true|false on action verdicts.

Recipe plane: reconcile completes a step only on terminal_status=succeeded
(partial/failed park the step on a LOUD await_user decision; legacy
plan_closed messages without terminal_status stay trusted) · unacked
dispatches recover (step_dispatch_emitted stamps + EDP_DISPATCH_ACK_GRACE_
SECS; unknown liveness + no plan + past grace = reset to pending) ·
create_plan(reopen) with a CHANGED goal flips preserved done actions to
verify (same-goal reopens keep them) + reopen churn counter ≥3 warns ·
add_step refuses CLOSED recipes; add_step in REVIEWING stamps
comprehension.signoff_stale and the FSM reopen AWAIT_USERs until a fresh
signoff clears it · resume_recipe resets failed-respawn steps to pending.

Gate hardenings: G-STEP keys on immutable execution_origin (flip-to-inline
laundering dead) · G-CHALLENGE step close also requires zero OPEN
challenges; role=reviewer dispatches only declared review/verify legs; plan
challenges assemble content server-side · G-REWORK enforced at
pool_spawn_worker (frozen refuses; G-REWORK:<plan>:<action> user answer
unfreezes; spawn opens a verify cycle) · G-RUNS: done needs a run with
exit_code=0 matching the declared verify command; planner cannot downgrade
a derived gate without a user answer (G-GATE target) · G-SPEC: missing
specs block close, registry read failure fails closed, waiver target
carries a demand hash (replay-scoped) · grounding echo requires a non-empty
restatement · flow-down at close requires mapped actions to have delivered
· G-EST validates positive finite numbers and a malformed estimate fails
G-CHALLENGE closed.

Suite: 1545 passed (+15 new in test_f35_round3.py; Phoenix env-fail only).
Updated to new contracts: test_f25 (verify-flip + same-goal counterpart),
test_wp1 (gate downgrade needs override), test_s26/test_reviewer_restoration
(passed= + declared review legs), test_fsm/test_recipe_map_integrity
(signoff_stale). RESIDUALS (recorded): grounding echo cross-action tolerance
kept for batch heads; flow-down stays declaration-level beyond the
delivered-action check; R3b#2 user-channel authentication is a trust
boundary, not a gate.

## F36 — Adversarial campaign Round 4 (spawn/wiring/lifecycle), 2026-08-18
15 findings (raw: .sol_review_out-r4.txt); owner: "OK go" on all three
groups. All 15 addressed.

Wake plane (the deaf-Monitor class): the follower is PARTIAL-LINE SAFE
(binary reads; offset advances only past newline-terminated records — a
mid-append read can no longer half-consume a wake) · follow-only sources
start from a bounded ARM-GAP LOOKBACK (EDP_WIRING_LOOKBACK_SECS, 120)
instead of EOF/connect-time, closing the arm→Monitor-start drop window
(ts-dedupe absorbs restart duplicates; ts-less history stays unreplayed) ·
the driver writes a heartbeat sidecar (<spec>.hb) every tick and EXITS
when its spec is deleted (unobserve now actually stops a live driver) ·
arm_wiring reuse is honest: reused=true only with a fresh heartbeat, else
"start the monitor_cmd" · SIDs carry a sha8 of the full handle (collision
overwrites dead) · the supervisor restart budget REFUNDS after healthy
uptime (EDP_SUP_RESTART_RESET_SECS, 600).

Pool honesty: spawn admission is atomic under the transition lock with a
'starting' reservation row that counts against every cap; failed launches
roll back; a release racing registration is honored right after (no
phantom active rows) · parked shells count against a HARD live-process
cap (EDP_MAX_LIVE_SHELLS, default 2x total) · close_when_idle treats
missing output instrumentation as UNKNOWN (two consecutive quiet checks
before a reap — never one blind sample; leaked-shell cleanup preserved) ·
status_ping keeps the pool byte-timestamp, judges staleness on the
freshest evidence, and calls an alive shell with NO evidence UNKNOWN
progress (probe band) — absence of evidence stopped counting as progress ·
PTY activation registers the process FIRST and terminates on activation
failure (no orphans; junk EDP_SUBMIT_DELAY_MS tolerated) · park captures
rx-file baselines into the manifest; the resume watchdog seeds from them
(events in the park→first-tick gap now fire resume).

Loop hygiene (the freeze class): the broker's store IO runs off its
asyncio loop (to_thread on publish/inbox/query/message/SSE reads) · the
three hottest locked store writes in the MCP tools (next_action recipe+
plan saves, record_action_status) run via asyncio.to_thread. RESIDUAL
(recorded): remaining store writes stay sync on the loop — short critical
sections; full async-store migration is a follow-up if contention shows.

Also: shadow tests updated to the F3 default-off contract (were
pre-existing reds — the pool suite had not run since F3).

Suites: claude 1548 (+3), edp-pool 303 (+3), edp-broker 29 — all green
(Phoenix env-fail only). NOTE: pool/broker changes need the STACK RESTART
to take effect in the live fleet.

## F37 — Adversarial campaign Round 5 (role surfaces & trust), 2026-08-18
12 findings (raw: .sol_review_out-r5.txt). Threat-model ruling (owner,
2026-08-18): single-operator local fleet — the adversary is a confused or
prompt-injected AGENT, never a hostile local process. CONFIRMED 7 + the
cheap halves of 2; REJECTED the multi-tenant auth infrastructure.

| # | Finding | Verdict |
|---|---------|---------|
| 5 | unset/unknown EDP_ROLE fails open to full registry | CONFIRM — fixed |
| 12 | EDP_ROLE_SCOPE typo falls to warn-mode | CONFIRM — fixed |
| 9 | worker mutates actions in a foreign plan | CONFIRM — fixed |
| 11 | planner CRUD checks type, not ownership | CONFIRM — fixed |
| 10 | worker composes broker_send via observe(effect=) | CONFIRM — fixed |
| 1 | role-less shell can mint acceptance_verdict | PARTIAL — spawned-role-less refused; operator console kept |
| 6 | agent-authored text framed as instructions | CONFIRM — envelopes shipped |
| 4 | broker unauthenticated | provenance-metadata half TAKEN; auth half REJECTED (single-operator) |
| 8 | secrets inherited into every shell | env-hygiene half TAKEN (strip + redact); isolated bridge service DEFERRED until a keyed HTTP delegate exists |
| 2 | pool control-plane unauthenticated | REJECT — out of scope for a single-operator localhost fleet (revisit if ever exposed) |
| 3+7 | headless --dangerously-skip-permissions / acceptor write reach | OWNER RULING: keep acceptor EDIT (fix-what-it-safely-can); headless-skip is what headless means here |

Identity fails CLOSED: attribution.is_spawned()/trusted_as() are the one
trust pivot (EDP_HANDLE = pool-stamped); build_mcp REFUSES an unknown
EDP_ROLE and a spawned shell with no role; EDP_ROLE_SCOPE is a strict
enum (unknown aborts; in-tool guard treats non-'warn' as enforce) · the
neuron-only guards (north_star_update, global facts) and the acceptor
verdict guard use trusted_as, so an absent role on a spawned shell is
untrusted, not exempt. Ownership: record_action_status refuses a worker
writing outside its handle's plan (grounding echo now unskippable);
update/delete_object bind a planner to its OWN plan's objects. Effects:
observe/register_rule refuse an effect action outside the initiating
role's toolset (driver re-checks at arm). Framing (#6): specialist
groundings carry a provenance banner (single-doc bit-for-bit superseded);
recipe briefs open with a rendered-data framing line; check_inbox returns
a `framing` field on every delivery; shadow briefs framed as dispatcher
claims; worker card gains the framing law; acceptor card marks its brief
sender-authored. Provenance (#4 half): HttpBroker.send stamps
body._sender {role, handle} from the server env at the one outbound seam.
Secret hygiene (#8 half): pool build_env strips credential-shaped names
(EDP_/ANTHROPIC_/CLAUDE_ kept; EDP_SPAWN_ENV_KEEP passthrough); bridge
redacts the API key from provider error text before agent/audit.

Suites: claude 1564 (+16 new in test_f37_round5.py), edp-pool 306 (+3 in
test_f37_spawn_secret_hygiene.py), edp-broker 29 — all green (Phoenix
env-fail only). Updated to new contracts:
test_w4_roles (unknown role fails CLOSED), test_multi_spec_selection /
test_specialist_compiled_doc / test_tool_output_bounds (banner-framed
groundings). NOTE: pool changes need the STACK RESTART to reach the live
fleet.

## F38 — Adversarial campaign Round 6 (delegation bridge & external seams), 2026-08-19
15 findings (raw: .sol_review_out-r6.txt). Same threat model as F37
(single-operator local fleet; the adversary is a confused/prompt-injected
AGENT + plain bugs). All 15 CONFIRMED and fixed — no rejects this round.

| # | Finding | Fix |
|---|---------|-----|
| 1 | CLI model pin never passed to Codex; audit reports it anyway | build_argv/run_sol thread `-m <model>`; bridge passes delegate.model |
| 2 | delegate override bypasses route authorization | _bridge_delegate_for consults routes FIRST; an override must be routed for the caller's role (role-less console exempt) |
| 3 | concurrent CLI calls share one output file → cross-answer bleed | per-invocation `.sol-last-message-<pid>-<ns>.txt` + `.sol-run-*.jsonl`; destination pre-deleted; 7-day sweep |
| 4 | slot reaper steals a live long turn; owner deletes replacement's lock | staleness 2400 (> max 1800 timeout); reap only aged AND provably dead (cross-platform _pid_alive); ownership nonce gates release |
| 5 | recipe budget charges fleet-wide delegate spend | audit rows stamp `caller`; _delegate_actuals filters by recipe; unattributed legacy rows reported separately, never charged to all |
| 6 | contract-broken challenge counts as a clean pass | parse_findings returns None on a broken contract (vs [] for a valid empty hunt); delegate_call fails the run; G-CHALLENGE never satisfied by prose |
| 7 | audit read errors silently ignored while totals called complete | _delegate_actuals counts audit_errors; budget note says INCOMPLETE when any sidecar unreadable |
| 8 | threads.json unlocked RMW + shared tmp loses mappings after paid turn | unique per-writer tmp name; save_thread wrapped so a persist race never fails a paid successful turn |
| 9 | planner-stamped arbitrary per-action model overrides the registry | model override must be a model the seat registry (models.json) pins; else pre-launch refuse + rollback |
| 10 | server-assembled challenge silently truncates the fields under review | LOUD elision markers (…[+N chars elided]) on description/acceptance clips |
| 11 | CLI byte-cap escapes as uncaught SolBridgeError past budget check | check_budget preflights the 30KB argv cap for cli delegates as BridgeError; _run_cli translates SolBridgeError→BridgeError |
| 12 | malformed HTTP 200 body bypasses the provider-failure path + audit | JSON decode + usage int-conversion errors → structured ok=false, audited |
| 13 | failed HTTP attempts recorded as billable token/cost | a failed call records zero usage/zero cost; billing truth follows `ok` |
| 14 | acceptor model claim contradicts registry + card | card says "designated acceptance seat (models.json binds it)", not "strongest model" |
| 15 | worker card promises file-producing asset delegation the bridge can't do | card says a routed asset delegation returns a TEXT draft only; you materialize it |

Also portability: _pid_alive gained a Windows ctypes OpenProcess path
(os.kill(pid,0) is POSIX-only — on Windows signal 0 is CTRL_C_EVENT); the
slot reaper retries acquisition immediately after freeing a dead slot.

Suites: claude 1576, edp-pool 306, edp-broker 29 — all green (Phoenix
env-fail only). New: tests/test_f38_round6.py. Updated to new contracts:
test_bridge (findings-contract None vs []), test_v7_budget + test_wp2_gates
(caller-scoped audit rows). NOTE: none of these change pool/broker code, so
no stack restart is required for F38.

## F39 — live pain report + F38 post-review fixes, 2026-08-20
Source 1: the /pain skill's FIRST live catch (docs/pain-points.jsonl,
acceptor-369ca226, 2026-08-19) — arm_wiring had no wiring profile for role
`acceptor`, so the card-mandated boot wiring refused and the whole
acceptance pass ran DEAF (ask_above answers could never wake it). FIX:
acceptor added to _WIRING_SPECS (rx.broker(me)), _WIRING_REFLEX_PROMPTS,
heartbeat table; NEW drift gate (test_f39_acceptor_wiring.py) — every role
whose toolset grants arm_wiring must have a wiring spec + reflex prompt.

Source 2: independent post-review of the Opus-4.8 F38 commit (operator
request). Two confirmed, both fixed:
- _caller_recipe treated ANY colon-less caller (`neuron`,
  `acceptor-<hex>`, `curiosity-<hex>`) as a recipe id — their spend was
  billed to a phantom recipe instead of the honest unattributed bucket.
  Now: no lineage shape (no `:`) → unattributed.
- _pid_alive (Windows): windll GetLastError() reads stale error state and
  the default c_int restype truncates a 64-bit HANDLE → could misread
  dead-vs-alive at the slot reaper. Now WinDLL(use_last_error=True) +
  get_last_error() + explicit restype/argtypes; live-verified against a
  real and a nonexistent pid.

Suites: claude 1580, edp-pool 306, edp-broker 29 — green (Phoenix
env-fail only). Claude-side only; no stack restart needed.

## F40 — Adversarial campaign Round 7 (convergence re-attack), 2026-08-20
14 findings against the F35/F37/F38/F39 fixes themselves (raw:
.sol_review_out-r7.txt). NOT converged: 12 CONFIRMED (mostly unfixed
TWINS of patched seams), 2 REJECTED.

| # | Finding | Verdict / fix |
|---|---------|---------------|
| 2 | planner NATIVE mutators (create_plan/record_plan/add_action/record_action_status/record_step_result) skip the own-plan rule the generic CRUD got | CONFIRM — one _planner_foreign_plan_refusal helper wired into all five |
| 3 | worker ownership plan-granular only; a1's shell could skip unrelated a2 | CONFIRM — action-granular: own action or same batch_group sibling |
| 4 | array of all-invalid findings filtered to [] = clean pass | CONFIRM (half) — non-empty array with zero valid entries → contract break; prose-wrapped valid arrays stay accepted (pragmatic) |
| 5 | secret markers missed ACCESS_KEY/_PAT/AUTH_CONFIG/PASSWD/… | CONFIRM — marker set widened; denylist architecture stands (F37 ruling) |
| 6 | audit append failure silently lost paid spend | CONFIRM (cheap) — audit-degraded marker latched; totals report audit_errors until cleared |
| 7 | bare-handle (acceptor/curiosity) spend invisible to every recipe cap | CONFIRM — EDP_PARENT lineage (see #13) makes their caller `<recipe>:<handle>` → attributed; residual unattributed spend NAMED in the gate detail |
| 9 | caller-supplied _sender rode the "server-stamped" trust | CONFIRM — stamp is unconditional; a supplied _sender is dropped |
| 10 | delegate override authorized role-wide, not per task-class | CONFIRM — override must equal the resolved route for (role, task_class) |
| 11 | subscription reuse compared effect EXISTENCE, not content | CONFIRM — content compared; a changed effect is a re-spec, never reused |
| 12 | 7-day GC could sweep a LIVE >7-day subscription (reuse never renewed mtime; heartbeat ignored) | CONFIRM — reuse touches the spec (lease renewal); GC spares a fresh (<15min) driver heartbeat |
| 13 | acceptor's ask_above had no derivable parent (bare handle) | CONFIRM — pool stamps EDP_PARENT (parent_session) at spawn+resume; _self_and_parent_addresses and _sol_caller consume it |
| 14 | slot crash between mkdir and pid write = immortal orphan | CONFIRM — missing/junk pid past the stale age reaps |
| 1 | policy files (.bridge.json/models.json) agent-writable; wants signing | REJECT — hostile-local-actor class (R5 ruling); any shell-holding agent can equally edit source; recorded |
| 8 | threads.json unlocked RMW can lose a mapping | REJECT — accepted residual (F38): worst case is one fresh thread, never a lost result |

Suites: claude 1586, edp-pool 308, edp-broker 29 — green (Phoenix
env-fail only). New: tests/test_f40_round7.py (8) + 2 pool EDP_PARENT
tests; test_s26 lifecycle updated to own-plan handles (the reap-arm gate
it pins is unchanged). NOTE: the EDP_PARENT stamp is POOL code — the
live fleet needs a STACK RESTART for #13/#7.

## F41 — Adversarial campaign Round 8 (second convergence pass), 2026-08-20
9 findings (raw: .sol_review_out-r8.txt); lens = twin-hunt on F40's own
fixes + the memory/state layer. 7 CONFIRMED (2 with scoped fixes), 1
REJECT. The round again yielded the twin class: sidecar mutators missed
the F40 ownership guard, SpecStore missed the F34 locking, write_doc's
drain checked nothing, the dispatch-intent stamp missed the F34 pin.

| # | Finding | Verdict |
|---|---------|---------|
| 1 | SpecStore last-writer-wins saves (twin of F34 R2 #1) | CONFIRM — locked optimistic-version save; add_entry + resolve_spec_learnings RMW under the object lock |
| 2 | plan-sidecar mutators skip planner ownership (twin of F40#2) | CONFIRM — _planner_foreign_plan_refusal wired into record_grounding_brief, adversarial_challenge(plan target, pre-paid-call), challenge_waiver, challenge_adjudication |
| 3 | no budget check at the paid bridge seam; degraded latch fail-open | PARTIAL — _bridge_call(ctx,…) enforces the caller recipe's delegate_usd cap before every paid call (refusal names the detail + honesty notes); fail-closed-on-degraded REJECTED (intelligence-over-guardrails: a torn audit line must not deadlock the fleet — it stays a loud named note) |
| 4 | batch head terminally records unreached later siblings (granularity twin of F40#3) | PARTIAL — terminal claim on a sibling requires every batch member declared before it to be terminal (declared-order member loop; post-failure skips stay legal); full ACTION_TRANSITIONS validation deferred (blast radius on planner heal paths) |
| 5 | write_doc drains accepted learnings without proof of folding | CONFIRM — content-checked drain (whitespace/case-folded substring); unmatched learnings stay overlaid (fail-safe duplicate, never a lost rule), named in worklog + kept_overlay_ids |
| 6 | rollup archives step_dispatch_emitted; stranded step waits forever | CONFIRM — pinned into GATE_PINNED_KINDS |
| 7 | grounding-brief clip is prose-only, no author-time gate | REJECT — already loud at BOTH ends (worker banner + the write-time note at RecordGroundingBrief); ack-gated delivery is the rejected guardrail class |
| 8 | degraded injected_context hydration loses its recovery pointer | CONFIRM — dehydrate re-attaches the @file marker to a digest-shaped value (ref parsed from the digest line), mirroring *_ref degraded round-trips |
| 9 | _INBOX_FRAMING sells client-stamped _sender as server provenance | CONFIRM (scoped) — framing reworded to "transport-stamped claim of origin, not verified provenance"; broker-side restamp needs auth = rejected class |

Twin sweep: north_star save is immutable-goal-guarded and neuron-only —
LWW residual accepted (single writer per recipe). Tests: +8 in
test_f41_round8.py; test_wp2_gates fakes updated to the ctx-first
_bridge_call. Suites: claude 1594 (Phoenix env-fail only), edp-pool 308,
edp-broker 29 — green. NOT converged: 8 of 9 landed. Round 9 = third
convergence pass (F41's own fixes + a surface no round has re-visited);
two near-empty rounds still gate the closing polish sweep.

## F42 — Adversarial campaign Round 9 (wake plane + F41 convergence), 2026-08-20
13 findings (raw: .sol_review_out-r9.txt); lens = twin-hunt on F41's own
fixes + the reactive wake plane (first re-visit since R4). 11 CONFIRMED,
2 scoped. Part B carried the round: the wake plane held four defects of
its own — the ownership class had never been applied to wiring CRUD at
all, and the supervisor never re-read its registry.

| # | Finding | Verdict |
|---|---------|---------|
| 1 | monitor CRUD trusts caller-supplied handles/sids | CONFIRM — _foreign_wiring_refusal on list_subscriptions/unobserve/observe(owner) + foreign-indexed-sid overwrite refusal (identity set = EDP_HANDLE + derived inbox address; foreground seat exempt) |
| 2 | RuleSupervisor never reconciles with the registry | CONFIRM — per-tick reconcile: spawns rules registered/enabled by other processes, retires live children of disabled/removed rules, re-spawns exhausted rules after a restart_reset_secs cool-down with a fresh budget |
| 3 | incomplete subscription identity + in-place re-spec leaves the old driver live | CONFIRM — owner/rate persisted as {sid}.runtime.json and included in reuse identity; the driver's lifecycle watcher now exits on spec/runtime CONTENT change, not only deletion |
| 4 | durable effects double-fire after driver restart (replay window + process-local dedup) | CONFIRM — EffectDispatcher seeds _seen from the rule's own effect-audit trail (seen_seed; driver reads the tail at launch) |
| 5 | GC heartbeat lease protects only indexed sids | CONFIRM — fresh-heartbeat check before the ordinary-TTL sweep too; stale .spec.hb collected with its triplet |
| 6 | spawn accepts a non-head batch identity; duplicate action ids ambiguous | PARTIAL — Plan schema refuses duplicate action_ids; pool_spawn_worker refuses a head that is not the group's first declared member (rolls stamped members back); full member-set equality deferred |
| 7 | record_context(kind=note) writes foreign plan worklogs | CONFIRM — planner + worker ownership legs (twin of F41#2) |
| 8 | learning resolution not idempotent (stale read outside lock, no status re-check) | CONFIRM — states read under the object lock; only latest-status 'proposed' transitions; retries are no-ops |
| 9 | substring drain fooled by negated/superseded mentions | CONFIRM — unit-anchored match (whole bullet/line, wraps folded) replaces substring |
| 10 | digest inference from resembling content (false @file markers, stale resurrection) | CONFIRM — anchored _DIGEST_RX full-match, exact-ref equality in _dehydrate_field, context/-scoped re-markers |
| 11 | grounding brief sidecar published before the optimistic save | CONFIRM — load+sidecar+save one critical section under the plan object lock |
| 12 | unacked steers roll out of the hot tail | PARTIAL — steer_sent pinned in GATE_PINNED_KINDS; message_sent/msg_kind=steer pinned in plan worklogs; a durable outstanding-steer ledger deferred (open thread: nested-ack fix) |
| 13 | ack ledger unlocked whole-file RMW | CONFIRM — RMW under the recipe object lock |

Tests: +14 in test_f42_round9.py; test_observe_tool artifact count updated
(.runtime.json). Suites: claude 1608 (Phoenix env-fail only), edp-pool
308, edp-broker 29 — green. NOT converged: Part A (F41's own fixes)
yielded mostly refinements, but Part B proved un-re-visited surfaces
still hold whole defect classes. Round 10 = the remaining un-re-visited
surfaces (FSM/gates since R3, prompts/cards since R1) + F42's own fixes.

## F43 — Adversarial campaign Round 10 (FSM/gates + prompts/cards re-visit), 2026-08-20
8 findings (raw: .sol_review_out-r10.txt); lens = FSM/gates (last pass R3),
prompts/cards (last pass R1), + F42's own fixes. 7 CONFIRMED, 1 scoped.
Yield keeps declining (13 -> 8); two findings were defects in the
freshest fixes (F42's canonical head, F42's driver watcher scope) — the
convergence loop is now mostly eating its own tail.

| # | Finding | Verdict |
|---|---------|---------|
| 1 | G-RUNS reads `command` but authors declare `cmd`; empty declared matches all; bidirectional substring accepts `echo pytest -q` | CONFIRM — reads `cmd` (legacy `command` fallback); one-directional token-contiguous match; echo/printf/cat/print/type first-token runs prove nothing |
| 2 | G-ACCEPT fingerprints map shape only; unfingerprinted pass grandfathered | PARTIAL — fingerprint now carries DELIVERY SUBSTANCE (per-step status, plan terminal_status, per-action evidence digests) when ctx-fed; a verdict with no fingerprint is never honored; full artifact hashing deferred |
| 3 | F42 canonical head deadlocks a batch whose earlier members are terminal | CONFIRM — canonical = first NON-terminal member in declared order (matches the FSM dispatch unit) |
| 4 | reconcile recovers only ip[0]; a live s1 shadows s2's recovery forever | CONFIRM — _advance_executing sweeps EVERY in-flight planner step (single broker poll, per-step _advance_one_planner_step, first instruction returned) |
| 5 | driver watcher misses bindings/effect changes + absent-to-present runtime | CONFIRM — watcher snapshots all four sidecars; a different or newly-present value retires the driver |
| 6 | supervisor reconcile keyed by name; replace=True invisible to a live child; stale cooldown outlives a correction | CONFIRM — _rule_generation (spec+bindings+effect+owner hash) tracked per child; changed generation terminates + rematerializes with a fresh budget and clears the cooldown |
| 7 | every worker card says record_action_status "runs NO gate" and omits `runs` | CONFIRM — guides-src/roles/worker.md, compiled card, and worker-card.md now document the runs ledger + declared-cmd match; recompiled at 2599/2600 |
| 8 | multi-bullet accepted rule can never drain (units split nested bullets) | CONFIRM — parent+nested-children composites added to _doc_units; the rule's own bullets normalize away; whole-unit negation guard preserved |

Contract updates: test_wp1_gates _RUN matches the declared cmd;
f21/f31/f35 verdicts now stamp the ctx-fed fingerprint (unfingerprinted
passes are refused by design). Tests: +8 in test_f43_round10.py. Suites:
claude 1616 (Phoenix env-fail only), edp-pool 308, edp-broker 29 — green.
NOT converged, but close: every surface has now had a post-churn re-visit.
Round 11 = full-framework convergence sweep; if near-empty, one more
confirming round, then the closing compact-framework polish sweep.

## F44 — Adversarial campaign Round 11 (full-framework convergence sweep), 2026-08-20
9 findings (raw: .sol_review_out-r11.txt); lens = whole framework, fresh
eyes, empty-array-means-converged. All 9 CONFIRMED (several scoped). NOT
an empty round — but the character shifted: three genuinely NEW
cross-subsystem races that no single-lens round could see (the broker
append thread race, the pool starting-reservation steal, the acceptance
attempt binding), plus twins/edges of the freshest fixes.

| # | Finding | Verdict |
|---|---------|---------|
| 1 | verdicts re-stamped with the CURRENT fingerprint at emission; dispatch recorded after spawn (fast verdict wedges the latch) | CONFIRM — dispatch fingerprint recorded BEFORE the brief/spawn, rides the brief, and the verdict is stamped with the DISPATCHED fp (never recomputed); failed launches append acceptance_dispatch_aborted, which releases the latch |
| 2 | version-1 reconstructions bypass optimistic concurrency (record_plan/record_recipe replace-and-erase) | CONFIRM — _whole_object_replacement_refusal: replacing an existing object requires carrying its current version; the fresh-object adoption no longer fires through the raw tools |
| 3 | fingerprint omits review verdicts; verdicts mutable on terminal plans | CONFIRM — record_branch_verdict refuses TERMINAL plans (reopen is the correction path); review_verdict.passed joins the delivery fingerprint |
| 4 | broker append thread race breaks per-inbox monotonicity (message hidden forever) | CONFIRM — InboxStore.append runs the tail-read/stamp/cache/write under a process lock; concurrency regression pins uniqueness + lossless cursor walk |
| 5 | concurrent same-handle spawn steals a starting reservation (double shell) | CONFIRM — a `starting` holder is occupied; only a reservation aged past EDP_STARTING_REAP_GRACE_SECS (180s) is recoverable; unreadable age = occupied |
| 6 | batch recovery ignores the recorded owner once the head action is terminal (resets work in flight) | CONFIRM — ready-wave dispatch now stamps batch_owner (twin of the single-dispatch stamp); phantom recovery probes the OWNER handle regardless of the owner action's status |
| 7 | observe re-spec non-atomic: validate-after-write, obsolete sidecars survive, present-to-absent invisible | CONFIRM — full config validated before ANY write; re-spec deletes sidecars absent from the new generation; driver watcher treats present-to-absent (non-spec) as a re-spec |
| 8 | F43 canonical head ignores dependency readiness (blocked first member deadlocks the plan) | CONFIRM — canonical = first nonterminal member whose depends_on are done/skipped (mirrors _ready_actions) |
| 9 | print-only G-RUNS bypass via shell wrappers (cmd /c echo …) | CONFIRM — the print verb is sought past wrapper/flag tokens (cmd/powershell/sh/bash/uv/env/npx…) |

Tests: +9 claude (test_f44_round11.py), +3 edp-pool
(test_f44_starting_reservation.py), +1 edp-broker
(test_f44_append_lock.py). Suites: claude 1625 (Phoenix env-fail only),
edp-pool 311, edp-broker 30 — green. Convergence read: the single-lens
seams are exhausted (R10 8 → R11 9, but R11's yield is concentrated in
cross-subsystem protocol/concurrency, a class the charter only now aimed
at). Round 12 = a SECOND full-framework sweep with the same
empty-is-valid charter + the F44 residuals recorded; an empty or
noise-only R12 declares convergence → the closing polish sweep.

## F45 — Adversarial campaign Round 12 (second convergence sweep), 2026-08-21
8 findings (raw: .sol_review_out-r12.txt); lens = whole framework again,
F44's own fixes named as the prime target, empty-array-means-converged.
All 8 CONFIRMED. NOT converged — but the round validated the charter's
aim: three highs attack seams the freshest fixes (F44#1, F43#1) had just
reshaped, and the mediums are the remaining caller-side RMW protocols of
the exact class R11 opened (channel registry GET→PUT, starting-row
release, spawn-seam readiness).

| # | Finding | Verdict |
|---|---------|---------|
| 1 | verdicts bind to the recipe-global LAST dispatch, not the emitting acceptor's own; caller-supplied recipe_id trusted (stale/foreign acceptor mints a pass for work it never judged) | CONFIRM — a spawned acceptor's verdict now requires an acceptance_dispatched record naming ITS handle (uses that record's fingerprint, never a rival's) and refuses a recipe_id conflicting with its spawn lineage |
| 2 | G-RUNS containment accepts an unknown no-op prefix (`true pytest -q`, `command echo pytest -q`) — declared tokens present as mere argv | CONFIRM — ANCHORED match: the declared sequence must begin within the recognized wrapper prefix or exactly at the executable position; python/py join the wrapper set |
| 3 | record_branch_verdict lets a reviewer record/overwrite verdicts on an unrelated plan (reopen or bless work it never reviewed) | CONFIRM — plan-scope twin of F37#9/F40#2: a spawned shell whose handle names an existing plan stamps only THAT plan; planners route through _planner_foreign_plan_refusal |
| 4 | acceptance_dispatch_aborted is not gate-pinned — rollup archives the abort while the dispatch stays pinned, resurrecting the in-flight latch for the TTL | CONFIRM — abort joins GATE_PINNED_KINDS |
| 5 | pool_spawn_worker admits the requested action unconditionally (F44#8's own-inclusion) with no dependency check — a confused planner launches work before its prerequisites | CONFIRM — the spawn seam re-validates readiness: every unit member's depends_on must be done/skipped or an EARLIER member of the admitted unit; refusal rolls the pre-stamps back |
| 6 | release() reads/flags a `starting` row without _transition_lock — registration can replace the row and drop the release flag (closed shell stays active) | CONFIRM — the starting-latch and the active-close state flip run under _transition_lock; kill/viewport stay outside it |
| 7 | channel membership is caller-side stale GET→PUT (pool spawn registration ×2, grounding-topic update) — concurrent spawns erase each other's registration and @all wakes miss the dropped member | CONFIRM — broker-side atomic merge (PATCH /v1/channels/{name}, ChannelStore.merge under a lock); pool + tools callers send deltas, GET→PUT survives only as the pre-F45-broker fallback |
| 8 | handle_index RMW is unlocked with a SHARED temp filename; observe swallows the OSError and reports success (subscription silently un-handbackable) | CONFIRM — index RMW under the stores' interprocess object_lock + pid-unique temp; observe returns a loud index_degraded note telling the owner to re-observe after compact/restart |

Tests: +14 claude (test_f45_round12.py), +2 edp-pool
(test_f45_release_lock.py), +3 edp-broker (test_f45_channel_merge.py).
Suites: claude 1639 (Phoenix env-fail only), edp-pool 313, edp-broker 33
— green. Convergence read: yield is flat (9 → 8) but narrowing in KIND —
no new defect class this round; everything is either a twin of a shipped
guard or the same unlocked-RMW/protocol class R11 named. Round 13 = third
convergence sweep (F45's fixes as the prime target + any remaining
caller-side RMW); empty or noise-only declares convergence → the closing
compact-framework polish sweep.
