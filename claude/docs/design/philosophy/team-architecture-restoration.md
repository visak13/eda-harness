# Team architecture restoration (2026-05-21)

Continuation of `ocak-as-helper-not-enforcer.md`. That doc fixed the
OCAK inversion (post-reasoning audit, not pre-reasoning checklist).
This doc reframes the deeper issue underneath it: **the system as
built is a top-down dispatcher with self-judgment baked in. The
system as described is a team with externality, bi-directional comms,
and role-specific discipline.** The old design had the team. We
removed it during consolidation. This doc records the restoration
plan.

Do not read in isolation — `ocak-as-helper-not-enforcer.md` is the
prerequisite and its findings (no LLM in helper tools, intent tools,
flat MCP schema, etc.) stay valid.

## The frame — operating room, not solo surgeon

Claude Code is a token completer fine-tuned for code. It does not
know what is in the user's brain. It interprets and starts working.
The right harness around it is not a smarter MCP tool layer — it is
**a team with clearly-defined roles + bi-directional channels +
external judgment**, running on **deterministic equipment** (the MCP
state machinery) that beeps when vitals drift.

| Surgeon's OR | This system |
|---|---|
| Lead surgeon (thinks, diagnoses, guides) | Neuron — recipe owner across lifetime |
| Specialist surgeon (cardio vs neuro vs ortho) | Planner — shape-specific brief for the work type |
| Scrub team (does the work under guidance) | Workers — single-shot leaf execution |
| Anesthesiologist (separate decision-maker monitoring vitals) | `/critic` — separate shell, adversarial review |
| Monitor specialist (watches for drift) | `/goal-keeper` — tactical-vs-strategic drift |
| M&M reviewer (cross-case learning) | `/pattern-observer` — cross-plan failure aggregation |
| Heart monitor / oxygen / instruments (deterministic, no judgment) | MCP tools — state, persistence, schema, drift checks |
| Pre-op meeting + patient history + OR log | Recipe — shared mental-model state, durable across the team |
| "Hold up, I see something unexpected" | Phase D event router + `pool_ask_caller` |

The old `evolving-deep-agent` had every row on the right. We removed
most of them. This is what restoration looks like.

## What the old design had (verified by reading the code)

Confirmed in `evolving-deep-agent/`:

- **Neuron broken into 5 phases** — `neuron-phase-{a,b,c,d,e}.md` totalling 604 lines. Each phase a focused brief. Phase D explicitly tells the neuron: "Do NOT self-evaluate. Spawn `/critic` for review."
- **Planner had 7 shape pipelines** — `agentic-plan-{creative-production,diagnose-fix-verify,gather-validate-submit,linear-build,modular-build,poc-iterate-build,research-synthesize}.md` totalling 1,200+ lines. Real flexibility per work type. Plus a 1,199-line core brief.
- **Bi-directional comm stack** in MCP — `pool_ask_caller`, `pool_send_to_session`, `notify_driver`, `wait_for_instruction`, `wait_for_notification`, `publish_event`, `subscribe_to_channel`. Per-session inbox files. Monitor-on-tail for non-blocking wake.
- **Three externality shells** — `/critic` (frontier-class Claude adversarial reviewer), `/goal-keeper` (drift detector), `/pattern-observer` (cross-plan learning).
- **Recipe protocol** named **four feedback sources** that drive revisions: action result, recall, neuron verdict, user observation. The "neuron verdict" source IS the externality — separate shells produce verdicts that revise the recipe.
- **Anti-pattern verbatim** in `neuron-phase-d.md`: "Self-evaluating claims of novelty / correctness / security — `/critic` exists for this. Do not answer the question yourself even if you could; the answer needs adversarial review."
- **Planner brief verbatim**: "Treat workers and the neuron as ongoing collaborators, not fire-and-forget. A planner that only writes (spawns workers, posts results) and never reads (responds to clarifications, accepts mid-plan steering) is operating in fire-and-forget mode — which is the failure mode the [protocol exists to fix]."

## What we built instead

- Monolithic neuron brief (no phases)
- Monolithic planner brief (no shapes)
- One bi-directional kind on the broker (`plan_closed`)
- Zero externality shells
- `run_ocak_audit` — agent audits its own work (self-investigation, found no wrongdoing)
- No "spawn `/critic`" path; no "ask the user before claiming novelty"

## What we built that's correct (don't dissolve)

The new state machinery is genuinely better than the old prose-only
protocol — the old design failed because the LLM decided when to
follow it; the new FSM doesn't give the LLM that choice. Keep:

- Recipe + plan FSM (deterministic transitions)
- Atomic persistence (worklog, snapshots, `write_atomic`)
- Wake reconcile (F1 broker fast path + F2 disk backstop)
- Schema strictness + instruction-shaped errors
- Intent tools (start_recipe, add_step, record_outcome, close_recipe)
- Flat MCP schema (no payload wrapper)
- Specialist guides on disk (loaded on demand)
- The "no LLM in helper tools" principle

These become **the deterministic equipment the team runs on**. The
team is the briefs + the cluster shells; the MCP layer is the OR's
monitors and instruments.

## The restoration — six meaningful phases

Each phase delivers a real capability. Each is independently
testable. The unit suite stays green at every step.

### Phase 1 — Kill the self-audit + brief discipline
**Delivers:** the false-due-diligence gate is gone; the briefs
explicitly forbid self-evaluation; the comprehension flow returns to
REASON → outcome → declare_step without a placeholder gate that
gives a false signal.

- Remove `run_ocak_audit` as an FSM gate (recipe + plan).
- Keep `run_ocak_audit` / `record_audit_verdict` / `consult_specialist`
  / `get_guide` / specialist guides as tools-available — `/critic`
  will use them when built.
- Add explicit anti-self-evaluation to `neuron.md` (verbatim from old
  phase-d).
- Add "bi-directional collaborators, not fire-and-forget" rule to
  `agentic-plan.md`.
- Update tests for the new flow.

### Phase 2 — Bi-directional comm substrate
**Delivers:** the team can talk. Worker can ask planner. Planner can
ask neuron. Neuron can answer or escalate to user.

- Add `pool_ask_caller(session_id, question)` — escalate up one layer
  with a question.
- Add `pool_send_to_session(session_id, payload)` — answer down one
  layer.
- Add `notify_driver(session_id, kind, body)` — progress reports
  upward.
- Add inbox file per session (`<edp-debug>/inboxes/<sid>.jsonl`).
- Add non-blocking wake — Monitor on inbox tails (per harness
  Monitor tool; not a blocking long-poll).
- Tests for the comm primitives.

### Phase 3 — Phased neuron brief + Phase D (operational curiosity)
**Delivers:** the neuron has explicit operational discipline. Phase D
is the missing observe-execution phase — event-router table, "do not
self-evaluate," spawn-critic-when-warranted.

- Split `neuron.md` into `neuron.md` (dispatcher, ≤50 lines) +
  `docs/guides/neuron-phase-{a,b,c,d,e}.md`.
- FSM emits which phase the neuron is in; `get_guide` loads it.
- Phase D carries the event-router table verbatim from the old
  design.
- Tests for the phase routing.

### Phase 4 — Shape pipelines for planner
**Delivers:** planner adapts to work type (modular build vs POC vs
diagnose-fix-verify vs creative-production, etc.).

- Split `agentic-plan.md` into core dispatcher + 4-7 shape guides
  loaded by `get_guide`.
- Planner picks shape (or neuron hints it via the step description /
  add_step call).
- Tests for shape selection.

### Phase 5 — First externality shell: `/critic`

> **superseded_by: DESIGN-v6 W9.** Not built, and not to be resurrected from
> this text. `/critic` was retired in favour of the domain `reviewer`
> (`branch_reviewer`), and W9 gives that same role a `scope="direction"` mode
> that reads the deliverable FILES against the verbatim goal. Crucially, W9's
> checkpoint is **advisory**: it is emitted once per due-crossing and never
> holds a dispatch. The "FSM gates: pre-sign-off cannot pass without critic
> verdict" line below is exactly the BLOCKING control mechanism d76 forbids —
> the FSM advises, it does not enforce. Findings become proposals the neuron
> confirms, not gates that stall the build.

**Delivers:** real adversarial review. Spawned on N=3 retry or pre-
sign-off. Returns pivot / abort / extend / continue with red-team
concerns.

- `/critic` session-neuron brief.
- Spawned via the bi-dir comm substrate (Phase 2).
- FSM gates: pre-sign-off cannot pass without critic verdict; N=3
  retry on an action triggers critic.
- `/critic` may load `framework-ocak.md` and apply OCAK against the
  work — this is where OCAK finally lives correctly (post-reasoning,
  by an external reviewer).
- Tests.

### Phase 6 — `/goal-keeper` + `/pattern-observer`

> **superseded_by: DESIGN-v6 W9.** Not built, and not to be resurrected from
> this text. Per user direction no watchdog role joins the flow: the role set
> is neuron / planner / worker / reviewer / specialist plus the on-demand
> consult (o7). `consult_goal_keeper` and `consult_pattern_observer` remain
> callable ON DEMAND; the framework does **not** schedule them, and the
> "FSM gates: plan creation consults goal-keeper" line below is precisely the
> gate W9 replaced with an advisory checkpoint. Text-level drift is covered by
> the direction reviewer's rubric, which reads the verbatim goal and the real
> artifact files rather than comparing text to text.

**Delivers:** the full team. Tactical-vs-strategic drift detection at
plan creation. Cross-plan failure pattern learning end-of-plan.

- Both session-neurons, broker-coordinated.
- FSM gates: plan creation consults goal-keeper; plan close consults
  pattern-observer.
- Tests.

## Sequencing rationale

- Phase 1 is small but removes the smoking gun (self-audit theatre)
  and lands the discipline rules. After Phase 1 the system has *fewer
  false signals*, which is improvement before any new construction.
- Phase 2 is foundation for everything else — the comm stack is
  required by Phases 3-6. It is the biggest "infrastructure" piece;
  worth its own focused sweep.
- Phases 3 and 4 are largely text + small FSM hooks — load the right
  brief at the right time. Once Phase 2 substrate exists, these are
  mechanical.
- Phase 5 (`/critic`) is the first real externality. It's where OCAK
  finally lives in its correct shape.
- Phase 6 completes the team. Goal-keeper + pattern-observer.

After Phase 6, the system has the architecture the old
`evolving-deep-agent` had, running on the new state machinery that
makes the old design's discipline failure no longer possible.

## What does NOT change

- The user-visible MCP tool surface stays flat (no payload wrapper).
- Intent tools, wake, reconcile, persistence — untouched.
- The philosophy doc that came before (`ocak-as-helper-not-enforcer
  .md`) stays valid as-is. This doc is its continuation.

## Open questions to revisit per-phase, not now

- Bi-directional channel implementation detail (Phase 2): inbox files
  vs broker queues vs both. Probably both, with broker as the
  primary and inbox files as the durable record.
- `/critic` model tier (Phase 5): the old design used frontier-class
  Claude. We default to Sonnet for cluster neurons per ADR-025. Worth
  deciding at the time.
- Shape selection mechanism (Phase 4): planner picks vs neuron hints
  vs FSM enforces.

## Records on disk

- `docs/design/philosophy/ocak-as-helper-not-enforcer.md` — previous doc.
- `docs/design/philosophy/team-architecture-restoration.md` — this doc.
- Per-phase IMPACT notes will live at `docs/design/components/team-restoration/IMPACT-phase-N.md`.
- METHODOLOGY gate rows and PROGRESS blocks per phase.
- Scenario logs as we hit them: `docs/design/paper-debug/<scenario>.md`.
