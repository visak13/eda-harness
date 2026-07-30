# DESIGN-v6 — Compaction-proof, enforced, self-paced orchestration

**Status:** APPROVED for implementation (2026-07-02)
**Scope:** hardening/optimization pass on the existing edp stack (`claude\` MCP server + `edp-broker` :9300 + `edp-pool` :9301). **No rewrite.** Fifteen workstreams in five phases, each independently landable, lazy migration for all 38 legacy recipe dirs. Role set is FIXED: neuron, planner, worker, reviewer, specialist (+ the on-demand consult shell) — no new watchdog roles. Spec authoring belongs to the specialist role only; the neuron triages and spawns, never authors spec content.
**Legacy fixture:** `.recipes\recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8` — every workstream must load it byte-identically (the tiering hydrate guarantee is the regression bar) and is tested against it.

## Guiding principles

1. **Enforce in code, push deterministically.** Prose discipline measurably failed: 322 learnings → 0 folded; banned patterns regenerated for 14 days; a day lost to a silent load-bearing assumption.
2. **Workers are disposable focused shells.** The compiled spec doc IS the worker-facing condensed spec; reviewers enforce the SAME doc for correctness while workers own business logic. Flowback keeps that doc current (W3).
3. **The server hands shells their wiring; it never asks them to remember it** (epochs, monitor re-arm, pacing, canonical prompts).
4. **Measured-only adoption** for model tiers and compression claims (MODEL-TIERING-BENCHMARK.md discipline; the withdrawn Haiku-heartbeat is the precedent).
5. **Guards refuse and explain — they never rewrite model output** (standing user mandate). Every fail-closed guard uses `_precondition(...)` with a self-healing instruction (Guard-B house style).
6. **The FSM is an ADVISORY GOD — an anti-drift rail, not an oracle (user's own framing, 2026-07-04, reconciling REDESIGN-fsm-as-guide §8 C1 with the P3 advisory change).** It paces, prompts, and keeps agents in check over FLOW ("50% of free next-step choices are bad — that's why we play god with the FSM"), but agents keep their brains: they verify state via the object surface and reconcile when the FSM's view disagrees with reality. The division: **fail-closed is reserved for DETERMINISTIC state-correctness checks** (Guard B missing-doc, close_recipe honesty, verify≠done, W2 constraint string-matches, W8 unacked-assumption set, W15 protected-spec cap — all direct descendants of shipped precedents, no apology needed) — never for judgment calls, and NEVER an LLM inside a tool (`ocak-as-helper-not-enforcer`: a helper's `_run` must not call an LLM; genuine review happens in a separate shell). "Advisory" is reserved for the genuinely non-blocking nags: `_comprehension_recheck`, W9's DIRECTION_REVIEW_DUE, W4's warn mode.

## House patterns (binding for all workstreams)

- Tool classes with **flat InputModels** in `tools\_tools.py` — `build_mcp` synthesizes MCP schemas from `InputModel.model_fields`; no opaque payload wrappers.
- **Tables-as-data**: ROLE_TOOLSETS, PACING, MODEL_TIERS, snapshot retention — same style as `fsm\state_machines.py` transition tables.
- All OBJECT-STATE writes through `store\atomic.py` (plan/recipe/spec stores + snapshots + tiering sidecars); stores are the single load/save chokepoint (the tiering constraint). Scope note (Phase-0 audit): a few auxiliary control files (`reactive\registry.py`, the cron ts in `_tools.py`, `stack_launcher.py`) `write_text` directly BY DESIGN — reviewers must not flag those.
- Windows + uv per component. Toolset/env changes reach fresh spawns only (MCP is fresh-per-spawn; broker+pool are the only persistent processes — a "coordinated restart" bounces those two).

## Measured failure evidence (baseline)

From recipe 0e7ca8 (14 active days, 458 versions) and code exploration:

| # | Failure | Evidence |
|---|---------|----------|
| 1 | Compaction losses | Crossed messages (neuron re-requested delivered work); worker "I was about to redo SF-3; now held"; user's "emphatic re-grounding" (`context\d50.md`) because workers kept regenerating banned `format=schema` calls |
| 2 | Flowback dead | 322 `learning` events → 1 `spec_learning_proposed` → 0 folded; `spec-local-gemma-ollama-llm-engineer\compiled.md` kept mandating the banned pattern; read path never touches `learnings.jsonl` |
| 3 | Role/memory confusion | `mcp_server.py` registers all 79 tools unconditionally; 4 overlapping memory verbs; flat global `.memory\facts.jsonl` with confirmed cross-recipe pollution; band-aid meta-specs (spec-role-clarity, spec-actor-clarity, spec-actor-identifier, spec-concern-validator) |
| 4 | Context blowup | recipe.json 205KB (~53k tok, 319 decisions inlined), events.jsonl 1.25MB (~319k tok), context\ 661KB, 457 snapshots = 46.7MB; full re-ground ≈ 220k tokens |
| 5 | Deadly assumptions | `record_assumption` (_tools.py:1780) has no `load_bearing` flag; assumptions excluded from `_comprehension_recheck` (recipe_fsm.py:261); only gate = one-time comprehension signoff |
| 6 | Direction drift | Workers hardcoded HTML generation + regex against a simple ask; goal-keeper is on-demand-only, text-vs-text; no artifact-level audit exists |
| 7 | No self-pacing | `reactive\driver.py` poll_ms=2000, no rate limiting (**as-audited 2026-07-04; the remedy is NOT a debounce — see §W7.4, amended 2026-07-11, where the debounce this row implied became the defect**); pacing = manually retuned crons (planner-phase-drive.md, the cron-retune paragraph — **removed by W6.5, s29/a3b**); ScheduleWakeup-with-verbatim-goal regression (scratch\neuron-session-debug-f8aeb2.md:47); stale `docs\design\REDESIGN-fsm-as-guide.md:166,193` still mandates ScheduleWakeup |
| 8 | All-Opus cost | `Action.model` worker-only structurally (http_pool.py:41,58,96 take no model); no token ledger (grep-confirmed); OTel/Phoenix :6006 exists unread |

---

## W1 — Structured decisions, tiering-composed context diet, and the long-horizon north star

**Problem:** evidence #4 and #6 above, plus: over months the only "what is this app now" grounding is re-reading everything — the ReactiveAgents `AGENT_ARCHITECTURE.md` "canonical doc wins over code" pattern exists only outside the harness. Decisions are prose blobs with contradictions as supersede-chains (d313→…→d319).

### Design

**1. Typed Decision schema** (`schemas\recipe.py`). New optional fields (legacy-compatible):

- `title: str` — required for NEW writes, ≤ 90 chars
- `kind: Literal["constraint","direction","scope","preference","fact","legacy"]`
- `subject: str = ""` — dedupe key (e.g. `"worker-llm-call-format"`); supersede-by-subject gives edit semantics instead of chains
- `constraint: Constraint | None` where `Constraint = {match: str, match_kind: "regex"|"substring", applies_to: list[str] (["action_result","spec_doc","llm_payload"]), message: str}` — the executable form, consumed by W2/W9 guards
- `body` capped at 1200 chars at write time (tool refuses longer: "split, or attach a context file ref")

`RejectedOption` gains the same `constraint` field — a ban becomes checkable, not remembered.

**2. Compose with tiering — do NOT build a parallel mechanism.** `store\tiering.py` (P2, 2026-06-10) already tiers `Decision.text` → `context/<id>.md` sidecars with digest-inline + hydrate-on-load byte-identity, and legacy files hydrate as a no-op:

- **Extend tiering coverage**: today it covers `Decision.text`, `RecipeStep.description`, `Acceptance.actual`, and `Plan.injected_context` values (tiering.py:117-177); W1 adds `Decision.rationale`, `Assumption.text`, `RejectedOption.text`, and `Action.description`. Note `Assumption`/`RejectedOption` have NO `*_ref` field or emission-gating `model_serializer` yet — add both, mirroring `Decision._ser_load_bearing_gate` (recipe.py:64-79).
- **`EDP_TIER_WRITE=1` is ALREADY set** (start-stack.bat:30, inherited by spawns via `build_env`'s `os.environ.copy()`). **The real adoption hole is the FOREGROUND neuron shell** — launched by `claude-personal`, not start-stack, so its env lacks the flag, and most `record_*` saves originate there. Fix: add the flag to the `eda.bat` wrapper / document it for the `claude-personal` profile function. Threshold stays 600B (`EDP_TIER_THRESHOLD_BYTES`).
- Rationale vs. the rejected alternative: a separate `decisions.jsonl` externalization would duplicate what tiering does with weaker guarantees (two hydration paths). One load/save chokepoint wins.
- The `dNNN.md` duplicate-write habit is retired naturally: tiering's sidecar becomes the only on-disk full text (existing dNNN.md files stay as history).

**3. Snapshot retention.** `RecipeStore.save` snapshots every version (457 × ~100KB on the fixture). Retention policy as data: keep last 10 full + every 25th; GC on save behind `EDP_SNAPSHOT_GC=1`. One-shot maintenance tool `compact_recipe_store(recipe_id)` for existing dirs. With tiering-on, snapshots also shrink (they snapshot the dehydrated payload).

**4. Event rollups.** Segment `events.jsonl` at 1000 records (`events.0001.jsonl`, …); on rollover write `events.0001.digest.md` **in code** (counts by kind, ts range, learning/spec tallies — no LLM). The hot path never reads full history.

**5. North-star object (long-horizon view).** New per-recipe artifact `.recipes\<id>\north_star.json` + rendered `north_star.md`:

- Fields: `user_goal_verbatim` (immutable after comprehension signoff — **code-enforced**: patch attempts → `_precondition`), `current_shape` (what the app IS now: components, entry points, canonical doc paths, with the "canonical doc wins over code" rule stated), `active_constraints` (auto-derived view of W1.1 constraints + bans — never hand-written), `evolution_log` (append-only dated entries "what changed and why", ≤ 400 chars each), `updated_at/by`.
- **Code-gated updates:** written only via `record_context(kind=north_star_update, ...)` (W4), neuron/planner only (role table). Each update appends to evolution_log and patches `current_shape` fields explicitly.
- **Freshness guard:** step completion with zero north_star updates in the step emits a `north_star_stale` warning event. W9's direction audit grounds on north_star.
- Exposed via `read_object("north_star", ...)` — which requires HAND-WIRING (no generic registration exists): a new `_CATALOG` entry (objects.py:38), an explicit `if obj_type == "north_star":` branch in `read_object`'s if-chain (objects.py:505-614) + a north_star store loader, and matching branches in `update_object`/`query_objects` if writable/queryable. `describe_objects` auto-iterates `_CATALOG`, so it's covered once the entry exists. (Phase 1 already stubbed the write path: `record_context(kind=north_star_update)` is wired with a neuron-only role check and a `_precondition` deferring storage to W1 — _tools.py:1914-1925.)

**6. `get_recipe_digest(recipe_id)` — the 5-10k-token re-ground packet.** Idempotent tool returning, in order:

1. north_star (goal verbatim + current_shape + last 5 evolution entries)
2. recap (as `recipe_context` today: state/phase/outcome/step counts)
3. full text of ACTIVE load-bearing decisions + all constraints/bans
4. title index of remaining decisions
5. open steps/actions
6. `pending_spec_learnings` (W3) + `pending_assumptions` (W8) counts
7. latest event-digest pointer + `grounding_epoch` (W2)

`neuron.md` cold-start and the W5/W10 consult shells ground from this instead of raw files. **Additive to Step 0, not a replacement:** the neuron's launch spec-loading (`ensure_orchestrator` + `ensure_universal` + `get_specialization`) is NOT raw-file grounding and remains — it seeds spec-universal before any worker `assemble_ruleset`. The digest replaces the recipe.json/events.jsonl reads only.

### Migration (lazy)

Legacy recipes hydrate untouched (tiering guarantee); first save under `EDP_TIER_WRITE=1` dehydrates. Legacy decisions get `title=_decision_title(text)` (already at `fsm\recipe_fsm.py:334`), `kind="legacy"` on first load. North_star for legacy recipes is synthesized on first `get_recipe_digest` call from `user_goal_verbatim` + active decisions, marked `synthesized=true` until the neuron confirms it.

### Files

`store\tiering.py`, `store\recipe_store.py`, `schemas\recipe.py` (+plan.py Action.description), `tools\_tools.py` (GetRecipeDigest, CompactRecipeStore, north_star routing), `fsm\recipe_fsm.py`, `objects.py`, `.claude\commands\neuron.md`, `start-stack.bat` / pool `build_env`.

### Acceptance

- Neuron cold-start of 0e7ca8 via `get_recipe_digest` < 10k tokens (OTel-measured).
- recipe.json < 30KB after one save with tiering-on; hydrated-model byte-identity tests pass.
- North_star survives and leads the digest; immutable-goal patch refused.
- Snapshot dir shrinks under GC; event segments + digests generated at rollover.

**Size: L** (foundation; mostly mechanical given tiering exists).

---

## W2 — Compaction-proof operation: epochs, fail-closed guards, monitor rewire hand-back

**Problem:** evidence #1 and #7. The RP-B pointer index relies on the LLM *noticing* it was compacted. Monitor wiring: `.reactive\<sid>.spec` persists and `observe()` is idempotent (`reused=True`), but the agent must *remember* to re-observe; some shells regress to ScheduleWakeup with the verbatim goal; the stale REDESIGN doc still mandates ScheduleWakeup.

### Design

**1. Grounding epochs — server-side detection.**

- `grounding_epoch = sha256(active load-bearing decision ids+texts + constraints/bans + pending-unacked load-bearing assumption ids (W8))[:12]`, carried in every `recipe_context()` push and in `read_object('action')` grounding.
- **STATELESS epoch comparison (code-grounding correction 2026-07-04 — a server-side `last_acked_epoch` store is infeasible: the only per-handle state today is the in-memory `_WAIT_CYCLES` dict (_tools.py:122) which resets on MCP restart, and MCP is fresh-per-spawn, so a stored ack cannot survive).** `next_action`/`reconcile` gain inputs `ack_epoch: str | None` and `reground: bool = False`; the server compares `ack_epoch` against the freshly-recomputed `grounding_epoch` from the loaded recipe — the recipe IS the state. Trigger table:
  - `ack_epoch` present and MATCHES → steady-state pointer index (or W7's short-circuit).
  - `ack_epoch` present and STALE → the ground moved (new constraint/assumption/decision) → full digest with a "ground changed" banner.
  - `ack_epoch` ABSENT → steady-state response + the current epoch echoed in the push (lean cron ticks stay cheap — they never carried an epoch and never will; this is NOT treated as compaction).
  - `reground=true` → full digest + rewire block unconditionally. **Compaction detection is the HARNESS's job, not epoch inference:** W13's SessionStart(compact) hook fires deterministically after a compaction and injects "run /reground now" — /reground calls `next_action(reground=true)`. The FSM's existing step-count-gap detection (recipe_fsm.py:415) stays as the backstop for shells that missed the hook.
- Role .md files add one line: "echo the epoch from your last context push on interactive turns." An echo of a stale epoch is the ground-change trigger; the compaction trigger is the hook.
- Note: `recipe_context()` (recipe_fsm.py:352-427) carries no epoch today — the field is new, but the delivery seam is confirmed (the push already fires on every next_action, _tools.py:210/234).

**2. Monitor rewire hand-back.** The `reground=true` (and stale-epoch) response ALSO includes a `rewire` block the shell executes verbatim:

- `observe_specs`: the persisted `.reactive\<sid>.spec` content(s) for this handle + the exact `observe(...)` call to re-issue + "run monitor_cmd under Monitor" (idempotency makes re-running safe). **Code-grounding correction:** specs are keyed by `subscription_id` with NO handle association persisted (only an optional free-form `owner` field, _tools.py:5153) — a **new handle→sid index at the `.reactive` root** must be written by `observe()` at subscribe time. The lookup lives in the observe layer in `_tools.py` (which owns the `.reactive` dir), NOT `reactive\driver.py` (that's just the Rx subprocess).
- `heartbeat`: the CANONICAL cron prompt constant (W7) and current cadence — **never** the verbatim goal.
- Where a `register_rule`→RuleSupervisor rule exists for the handle, note it as the durable path already active (no re-arm needed).

A compacted shell is HANDED its wiring back; it doesn't reconstruct it from memory. Requires `reactive\driver.py` to expose a per-handle spec lookup.

**3. Constraint guards (Guard-B precedent, fail closed).** New `src\edp_claude\guards.py`: `check_constraints(recipe, payload_kind, text) -> list[Violation]` executing every active `constraint` where `payload_kind ∈ applies_to`. Wired into:

- `RecordActionStatus` (_tools.py:1565, _run :1579): completion text matching a banned constraint → `_precondition` naming the decision id + message. The worker learns why at the moment of violation.
- `PoolSpawnWorker` (_tools.py:1948): scan each stamped spec's compiled doc (**overlaid form**, W3) with `applies_to=["spec_doc"]`. Contradicting doc → **refuse spawn**: "spec X contradicts decision dNNN — resolve via flowback (W3) before dispatch." This is d50's "THE FIX IS AT THE SOURCE" in code: a poisoned spec can never reach another worker.
- `emit_recipe_event` / `broker_send` bodies: warn-only stamp (don't block comms).

**4. Duplicate-dispatch guard.** `PoolSpawnWorker` refuses actions already `done`/`in_review` unless `force=true`, echoing the recorded completion — the "neuron re-requested delivered work" case becomes a refusal with the answer attached.

**5. Retire the stale doc.** `docs\design\REDESIGN-fsm-as-guide.md:166,193`: replace ScheduleWakeup guidance with a pointer to the canonical loop-and-heartbeat guide (W6.5), or mark the doc RETIRED header-first (the `ocak.md` retirement pattern).

**6. Acceptance is a pure write — NOTHING executes inside the tool call (long-standing hang bug, code-grounded).** > **SUPERSEDED by d29 (2026-07-05):** the detached pool-runner design below was NOT shipped. d29 (authoritative user directive) removed acceptance-command execution *end to end* rather than relocating it to the pool — there is no `EDP_DETACHED_VERIFY`, no `POST /v1/verify` pool endpoint, no `verify_result` broker kind, and no async verify conclusion. The problem framing is retained for history; the shipped model is the corrected bullets that follow. The original hang: `record_action_status`'s acceptance gate ran `check: "command"` verifies via `subprocess.run` INSIDE the MCP tool call (`_verify_acceptance`). Two prior fixes (async-off-the-loop 2026-05-26; `stdin=DEVNULL`) narrowed but did not kill the class: on Windows a verify command that spawns a detached child (built .exe, dev server, GUI) leaves grandchildren holding the captured stdout/stderr pipes after the timeout kills the direct child — the tool call blocks past its own timeout (the code's own comment recorded 1014s past a 600s timeout). This is structurally unfixable inside `subprocess.run(capture_output=True)`. **SHIPPED model (d29, refined by d30 to RUN-NOTHING + DUAL-GATE — see below):**

- **`record_action_status` is a pure status+evidence write** — it records the claim + evidence and RETURNS IMMEDIATELY. Under **d30** it runs LITERALLY NOTHING: no acceptance command AND no file/glob check (the d29 in-process `_verify_nonexecuting` pure-check gate is removed by a1b). It spawns zero subprocesses, enqueues no detached verify, and cannot hang. A recorded `done` no longer parks at a framework `verify` state — that state is unreachable-on-record under d30, replaced by `needs_review` + the worker→reviewer chain.
- **DUAL-GATE acceptance — the SHELLS run every gate, not the framework (d30)** — every `acceptance.verify` criterion (command AND file/glob alike) is handed to both briefs: the WORKER runs it in its own shell as part of the work and reports the result as plain-prose evidence, and the REVIEWER independently re-runs it in a fresh shell — that reviewer re-run IS the objective gate (the worker→reviewer chain). Role division: the neuron TRACKS, the planner ENFORCES (requires evidence + a reviewer pass before the step closes), the worker/reviewer IMPLEMENT (run their gates). Planners author acceptance as `manual_review` carrying the criteria on the action; no MCP tool and no pool ever executes it. This routing is GUIDE CONTENT (there is no single brief-composer to auto-inject into — that would be the app-authored-structure anti-pattern d29/principle-6 forbid).
- **Inert-data rule:** worker-supplied done-message/evidence text is data, categorically — the tool executes nothing, so no worker string can ever run. The a1 constraint guards still run at the record seam (a banned-pattern completion is refused citing the decision id).

### Migration

Legacy prose decisions have no `constraint` → guards no-op on them (advisory continuity). The neuron retrofits constraints onto load-bearing decisions via `record_context` amend (supersede-by-subject).

### Files

New `guards.py`; `tools\_tools.py` (NextAction/Reconcile ack_epoch+reground inputs, PoolSpawnWorker :1948, ObserveStream handle→sid index); `fsm\recipe_fsm.py` (epoch computation in recipe_context, rewire assembly); `docs\design\REDESIGN-fsm-as-guide.md`; role .md epoch-echo line. (SUPERSEDED-by-d29 item-6 files that were NOT built or were later removed: the `_verify_acceptance` split in `_tools.py`, the async-verify conclusion in `fsm\plan_fsm.py`, and the pool verify-runner module in `edp-pool\src\edp_pool\service.py` — d29 removed acceptance-command execution end to end, and d30 (a1b) further removes the pure `_verify_nonexecuting` stat/glob check — the tool now runs NO gate at all, and the `verify` state is unreachable-on-record, replaced by `needs_review`.)

### Acceptance

- No-ack_epoch session receives full digest + rewire block containing its actual persisted observe spec and the canonical cron prompt.
- Banned-pattern completion refused citing the decision id; contradicting-doc spawn refused; done-action spawn refused.
- Grep confirms no ScheduleWakeup mandate remains in live docs.
- **Pure-write acceptance (d29, refined by d30 to run-nothing + dual-gate):** `record_action_status` returns instantly and executes ZERO subprocesses (records status + evidence only), running NO gate at all — no command AND no file/glob check (d30); a grep/unit test asserts NO acceptance-execution path (`_run_command_verify` / `_verify_acceptance` / `_verify_nonexecuting` / detached pool runner / `verify_result` / `EDP_DETACHED_VERIFY`) remains reachable from any Tool `_run` path; a recorded `done` moves to `needs_review` (the `verify` state is unreachable-on-record); EVERY `acceptance.verify` criterion (command AND file/glob) appears in BOTH the worker brief (worker runs it in its own shell) and the reviewer brief (reviewer independently re-runs it = the gate); a worker done-message containing an executable string is recorded as inert data and nothing executes.

**Size: L.** Depends on W1 (constraints, digest), W7 (canonical prompt + verify_pending cadence), W8 (pending-assumption set). (The item-6 detached-verify pool runner was NOT built — d29 removed acceptance-command execution end to end instead of relocating it pool-side.)

---

## W3 — Automated spec flowback with a one-decision human gate

**Problem:** evidence #2. Compiled docs are the ONLY grounding workers AND reviewers read — a stale doc poisons both sides. The intended loop has ~7 manual LLM/human steps and the live read path never sees `learnings.jsonl`.

### Design

**1. Auto-propose.** ADD A BRANCH to `EmitRecipeEvent` (_tools.py:2761 — today it writes ONLY to the recipe worklog): when `kind=="learning"` and a `spec_id` is resolvable — explicit in body, or derived by loading the lineage action and reading `action.effective_spec_ids()` (schemas/plan.py:210; `_resolve_recipe_lineage` (_tools.py:2638) returns recipe+action, NOT the spec — single-element ⇒ the stamped spec; multi-spec actions require explicit `body.spec_id`) — the branch ALSO appends a `proposed` record to `SpecStore.learnings_path`. Precedent: `ProposeSpecLearning` (_tools.py:4098-4119) already performs both writes. `propose_spec_learning` remains as an explicit verb but is no longer load-bearing. Structured record:

```json
{"learning_id": "...", "rule_text": "...", "tag": "[required]|[expected]|[hint]",
 "overrides": "<fragment of compiled.md this replaces, or null>",
 "source": {"recipe_id": "...", "action_id": "..."}, "status": "proposed"}
```

Legacy free-text records still parse (existing loose-list handling in spec_store.py).

**2. Deterministic triage surfacing.** `recipe_context()`/`get_recipe_digest` include `pending_spec_learnings: {spec_id: n}`. "Specs this recipe consults" is NOT a recipe field — derive in code from the recipe's plans' `action.spec_ids` (primary) + `specialist_consults[].specialist_id` (needs the neuron→spec hop). `close_recipe` (_tools.py:1185 — already guards unfinished steps :1216 and unmet outcomes :1234; the clean place to add this) with pending learnings emits a warning event. The neuron cannot forget — it's pushed every tick.

**3. Single cheap gate.** New `resolve_spec_learnings(spec_id, accept: list[str], reject: list[str], note="")` (batch; supersedes per-item `resolve_spec_learning`). On accept, **code** (no LLM): appends resolution records (status word stays `promoted` — the vocabulary `read_learnings` already parses), appends each accepted rule to `spec.entries`, bumps version via `SpecStore.save`. **A genuine semantic change, not a rename:** today's `resolve_spec_learning` (_tools.py:4173-4191) only MARKS promoted/rejected and explicitly leaves entry-append + recompile to a human — the accept-folds-into-entries path is new code. Human involvement = one accept/reject decision on a compact diff the neuron presents ("3 rules proposed for spec-X, 1 overrides an existing mandate — accept?").

**4. Read-path overlay — accepted learnings are live immediately.** `SpecStore.read_doc(spec_id, with_overlay=True)` — the param is NET-NEW (`read_doc` at spec_store.py:63 takes no overlay arg; its docstring explicitly says the live read path never touches learnings):

- Compose `compiled.md` + auto-generated `## Field amendments (accepted, pending recompile)` section from accepted-but-not-recompiled learnings, each tagged, with the header rule "**amendments override any contradicting rule above**."
- A learning with `overrides` gets the matched base fragment annotated with a `> SUPERSEDED by amendment Ln:` prefix (substring match; unmatched → amendment still appended).
- `GetSpecialistDoc`/`GetSpecialistDocs` (_tools.py:4319/4351), `BranchReviewer` grounding, and W2's spawn-time contradiction guard ALL read the overlaid form — workers and reviewers stay on the same, current doc.
- Full SME recompile (`update_specialist` → `write_specialist_doc` → `record_spec_version`) becomes periodic hygiene that clears the overlay — no longer the gate to visibility.

### Migration

Legacy learnings render as `rule_text=<summary>`. **E2E verification case:** accept the stranded 0e7ca8 proposal ("CONTENT IS RAW, NEVER SERIALIZED") and confirm the next `get_specialist_docs` grounding marks the banned mandate superseded.

### Files

`store\spec_store.py` (overlay compose, accepted-pending query), `tools\_tools.py` (EmitRecipeEvent, ResolveSpecLearnings, GetSpecialistDoc(s), spawn-guard hookup), `fsm\recipe_fsm.py` (pending counts), `.claude\commands\{neuron,specialist,reviewer}.md`.

### Acceptance

- Worker learning event auto-appears as proposed; neuron tick shows the count.
- One batch accept → overlaid grounding supersedes the banned mandate; reviewer spawn receives the overlaid doc.
- Zero LLM steps between emit and overlay except the one human accept.

**Size: M.**

---

## W4 — Role-scoped tools + one routed memory verb + scoped facts

**Problem:** evidence #3. Role discipline is 100% prose, patched with band-aid meta-specs.

### Design

**1. Per-role registration at the `build_mcp` seam** (mcp_server.py:~61). Data table in new `tools\roles.py`:

```python
ROLE_TOOLSETS: dict[str, set[str] | None] = {
    "worker":   {  # ≤ 22
        "whoami", "check_inbox", "reply", "ask_above", "notify_above",
        "emit_recipe_event", "read_object", "query_objects", "describe_objects",
        "get_specialist_docs", "record_action_status", "record_context",
        "recall", "observe", "status_ping", "pool_close_self", "get_guide", ...},
    "planner":  {...},   # ≤ 28 (adds spawn/plan/worklog/consult tools)
    "reviewer": {...},   # ≤ 14
    "specialist": {...},
    "consult":  {...},   # W5
    "neuron":   NEURON_SET,  # full set MINUS the spec-authoring verbs (below)
}

# Spec-authoring verbs belong to the SPECIALIST role ONLY (W15 evidence: the neuron,
# holding all tools, "just did" specialist updates itself instead of launching the
# update-specialist shell). The neuron TRIAGES (resolve_spec_learnings) and SPAWNS
# (train_specialist / update flows); it never authors spec content:
SPECIALIST_ONLY = {"add_spec_entry", "update_specialist", "write_specialist_doc",
                   "create_specialization"}
# assemble_ruleset is SPECIAL: WRITE-side (recompile) is specialist work, but
# neuron-phase-e:58 instructs REVIEWERS to load the full layered ruleset with it.
# Resolution: reviewer floor keeps assemble_ruleset (it is a read/compose, not an
# authoring write) — or expose the same composition via get_specialist_docs(with_ruleset=true)
# and sweep phase-e; decide at reviewer-enforce time, never enforce reviewer scope before.
# (ensure_orchestrator/ensure_universal stay with the neuron — idempotent launch floor, not authoring.)
```

**DERIVE the sets, don't author them (regression lesson, 2026-07-04).** The first W4 cut omitted `update_object`/`delete_object` from the planner set — but the planner's OWN guides instruct them (`update_object` ×3, `delete_object` ×1 across agentic-plan.md + planner-phase-*.md): a planner patches its plan/actions (deps, model, status rollbacks) through the generic CRUD verbs, and the omission left a live planner unable to update its own plan (it had to re-author the whole action set via `record_plan`). Rules:

1. **Each role's toolset is DERIVED from its contract, not hand-authored:** parse the role's .md + its phase/shape guides for tool references — that union is the floor; additions beyond it need a stated reason in a table comment. A unit test regenerates the derived floor from the guide files and fails if ROLE_TOOLSETS drops below it (guides and toolsets can never drift apart again).
2. **Warn-then-enforce rollout:** `build_mcp` honors `EDP_ROLE_SCOPE=warn|enforce` (default `warn` for one full recipe per role). In warn mode all tools register, but off-set calls are logged (`role_scope_violation` worklog events with role+tool). Flip to `enforce` only after a recipe completes with zero unexpected violations for that role — the FSM-advisory pattern applied to tool scoping.
3. **CRUD verbs are scoped by OBJECT TYPE in-tool, not dropped from sets:** `update_object`/`delete_object` stay in the planner set with an in-tool role guard — planner may mutate `plan`/`action` objects only; neuron additionally `recipe`/`step`/`north_star`; worker gets read-only CRUD (`read_object`/`query_objects`/`describe_objects`) + `record_action_status`. Refusals name the role and allowed types (`_precondition` style).

`build_mcp` reads `EDP_ROLE` (already stamped by `pty_launcher.build_env`) and filters `build_registry(ctx)` output by name. Absent/unknown role → full set (the human foreground shell has no EDP_ROLE). Off-role calls become **impossible**, not discouraged. After verification, archive the meta-specs (spec-role-clarity, spec-actor-clarity, spec-actor-identifier, spec-concern-validator).

**2. `record_context(kind, ...)`** — the consolidation the code already flags (`_tools.py:1678` TODO). One tool, `kind ∈ {decision, assumption, rejected_option, fact, north_star_update}`; flat InputModel = union of today's `_CtxIn` + `_RememberIn` fields + W1's `title/subject/constraint` + `load_bearing` (honored for assumptions too — W8). Routing in code: decision/assumption/rejected_option → recipe context; north_star_update → north_star (W1.5); fact → scoped memory (below). Old verbs (`record_decision`/`record_assumption`/`record_rejected_option`/`remember`) stay as classes for tests but leave every role toolset.

**3. Scoped facts.** `.memory\global\facts.jsonl` + `.memory\recipe\<recipe_id>\facts.jsonl` + `.memory\domain\<domain>\facts.jsonl`:

- `record_context(kind=fact)` defaults scope to the caller's recipe (EDP_HANDLE lineage, same resolution as `_self_and_parent_addresses`).
- `scope="global"` must be explicit and is neuron-only (role table enforces).
- `recall(query, scope=None)` searches caller-recipe + named domain + global, results scope-tagged.
- Migration lazy: legacy `.memory\facts.jsonl` read as global fallback; moved to `global\` on first write.

### Files

`mcp_server.py`, new `tools\roles.py`, `tools\__init__.py` (`build_registry(ctx, role=None)`), `tools\_tools.py` (RecordContext, memory scope threading), role .md sweeps (verb rename).

### Acceptance

- Spawned worker's MCP `tools/list` returns ≤ 22 tools.
- Derived-floor test passes: every tool referenced in a role's .md/guides is present in that role's set (regenerated from the guide files, not hand-maintained).
- One full recipe per role runs under `EDP_ROLE_SCOPE=warn` with zero unexpected `role_scope_violation` events before enforce is flipped; a planner in enforce mode successfully patches its own action deps via `update_object` (the 2026-07-04 regression case).
- Worker fact lands recipe-scoped; another recipe's recall doesn't surface it unless global.
- Unit test: every name in ROLE_TOOLSETS exists in ALL_TOOL_CLASSES (drift catch).

**Size: M. Implement FIRST** — it's the seam every new tool registers into.

---

## W5 — Consult channel (inbox + convened consult shell)

**Problem:** evidence — no user→running-shell channel; only touchpoint is the neuron foreground shell. The user runs a stronger-model foreground session but can't afford it routinely → ladder defaults to consult-Opus (W10); stronger tiers only by explicit choice.

### Design

**1. Consult delivery — post to the NEURON'S OWN inbox with `kind="consult"` (code-grounding correction 2026-07-04).** The broker's SSE/StreamHub and `rx.broker` are PER-RECIPIENT (StreamHub keyed by recipient, edp-broker/service.py:53-70) — a message posted to a *separate* `consult:<recipe_id>` recipient would NOT wake a neuron observing its own `recipe_id` inbox, however the kinds filter is set. So consults are delivered to the EXISTING `recipe_id` recipient (the neuron's inbox — auto-created, durable, already observed) carrying `kind="consult"` or `kind="steer"` (both already registered in edp-contracts/broker.py:53-56; the kind registry refuses unregistered kinds fail-closed). The user posts from their own foreground session via `broker_send(to=<recipe_id>, kind="consult", ...)` or a documented `curl` one-liner to :9300. Delivery planes:

- **Push:** the neuron's existing `observe()` spec ADDS `consult`/`steer` to its kinds filter (`rx.broker` filters by kind — reactive/runtime.py:45-53) — SSE wakes the shell mid-run on its existing subscription; no second Monitor.
- **Poll backstop:** `reconcile` (NOT `next_action`, which does zero external IO by design — _tools.py:196-200; broker polling lives in reconcile at :345) already polls the recipe inbox; it stashes a `consult_pending` flag ONTO THE RECIPE (recipe_context is a pure function of the Recipe and cannot poll), which the digest then surfaces. W2's reground re-delivers undrained consults after compaction.
- `steer` = directive ("stop doing X"). A drained steer without a subsequent `record_context` decision referencing its id **re-surfaces next tick** (code check in reconcile).

**2. `convene_consult(recipe_id, question, spec_ids=[], model=None, mode="monitor")`** — pool spawn `role="consult"`, mode=monitor (visible console the user can type into), model per W10's tier table (consult default = opus; stronger tiers only when explicitly passed). New `.claude\commands\consult.md`: activation calls `get_recipe_digest` (cheap grounding — why W1 matters here), reads the question from the spawn brief / consult inbox, optionally loads overlaid spec docs, answers to the asker's inbox + `consult:<recipe_id>`, records keep-worthy findings via `record_context(kind=decision, by="consult")` (neuron confirms). Callable by neuron, planner (role table), the user's foreground session, or W10's escalation path.

**3. Direct PTY injection (escape hatch — HEADLESS shells only, code-grounded):** pool endpoint `POST /v1/shells/{handle}/inject` reusing `PtyLaunch.send_activation → self._proc.write` (pty_launcher.py:513-522) — which exists ONLY for headless `PtyLaunch` shells. Monitor-mode shells are `ConsoleLaunch` (CREATE_NEW_CONSOLE `Popen`, NO writable stdin, console_launcher.py:30-38) — you CANNOT inject into a monitor console, and you don't need to: the monitor consult shell takes direct keyboard input (its whole purpose). Env-flag gated; `steer` remains the sanctioned cross-shell channel.

**Spawn notes (confirmed feasible with zero pool changes):** `role="consult", mode="monitor"` works on the existing `/v1/spawn` — the capacity cap applies only to `role=="worker"` (service.py:161), and `activation_text` falls back to `/{role}` for unmapped roles (pty_launcher.py:297-304), so the spawn emits `/consult` and works as soon as `.claude\commands\consult.md` exists (fails loudly as "Unknown command" if it doesn't).

### Files

`tools\_tools.py` (ConveneConsult, NextAction consult drain, steer-ack check), `clients\http_pool.py` (consult spawn call, model param — W10a made the non-worker methods model-aware; the edp-pool /v1/spawn body is already generic), `edp-pool\src\edp_pool\service.py`/`pty_launcher.py` (ONLY for the optional inject endpoint — the spawn path needs no pool change), new `consult.md`, `neuron.md`/`agentic-plan.md` observe-spec update, guide entry with the curl one-liner.

### Acceptance

- Consult posted from a second shell wakes a live neuron mid-run and re-surfaces after a forced compaction.
- `convene_consult` opens a visible console grounded < 15k tokens that answers to the inbox.
- Unacked steer re-surfaces every tick until a decision references it.

**Size: M.** Depends on W1 (digest) + W10a (generic model param).

---

## W6 — Tool-layer + guide optimization

**Problem:** 79 tools inflate every spawned prompt; Bash output uncompressed; redundant tool pairs; the react→reconcile→next_action loop is restated in **8 files** and the CronCreate-heartbeat rule in **14 files** (grep-measured 2026-07-04 — the earlier "4-5 places" UNDERcounted; the dedup win is larger than claimed). Note `reactive-streams.md` has already been split into `-reference`/`-effects` companions — the trim targets all three. User constraint: condense WITHOUT dumbing down — phase-driving prevents hallucination and stays.

### Design

**1. External tools — honest cost/benefit analysis and verdicts.**

> **THE ROWS BELOW ARE THE MEASURED RECORD (s30, 2026-07-12), NOT THE ORIGINAL DESIGN'S EXPECTATIONS.** Several things this section originally asserted turned out FALSE and are corrected here rather than softened. Every citation is to a decision id VERIFIED against the recipe sidecar and to a LIVE file path, stated.

| Tool | Mechanism | Token effect | Value-loss risk | Verdict |
|---|---|---|---|---|
| **rtk** (github.com/rtk-ai/rtk) | PreToolUse hook on the **Bash matcher only** (d169). It does **not** wrap a whole command string: it passes a *single simple command* to rtk's own `rtk rewrite`, behind three gates (shape → presence → adapter) and `EDP_RTK=1`. Live at `claude\.claude\hooks\rtk-pretooluse.py` (symbol: `rewrite()`); a local Rust binary compresses that command's OUTPUT before it enters context, costing zero model tokens. | **MEASURED (d165, d168; `docs\design\s30-plugin-enablement\RTK-MEASUREMENT.md` Part II §4, Part III §5) — no vendor number is quoted.** 54%–94% on the search-and-listing family: `grep` 89.9%, `wc` 94.1%, `find` 80.1%, `ps` 68.8%, `ls` 53.9–67.7%. **0%, clean pass-through**, on file reads, disk usage, dependency listings and test runs. **No basket/headline ratio is published** — the command mix, not the tool, sets it. | **The "errors kept verbatim" claim is MEASURED FALSE, and it is a real cost, not a footnote.** Driven against real failing commands: a failing `wc` loses its error text **ENTIRELY** (empty stderr, bare exit); `git` errors are **REWRITTEN**; `grep`/`cat` error paths are **MSYS-mangled** into a path the agent cannot copy back out and re-run. Exit codes survive, so **a failure still reads as a failure** — but **an agent cannot always learn WHY it failed**, and that degrades exactly the signal a worker needs to self-correct. Separately, rtk's `find` truncates with no retrieval pointer and dropped an entire requested subtree. The claim has been **STRUCK** from the hook docstring, not softened. | **KEEP THE HOOK — but the honest verdict is: SAFE IS ESTABLISHED; VALUABLE IS NOT.** *Safe:* the d165 corruption class (a leading builtin or bare assignment silently dropped, exit 0 — so `cd <dir> && rm -rf <rel>` could delete against the WRONG cwd and report success) is now **structurally unreachable**, proved by a differential ON/OFF matrix with a positive control; a2f then closed the absent-binary residual at **zero** measured compression cost, proved byte-identical. **The defect was OURS, not rtk's** — rtk wraps a single executable and publishes `rtk rewrite` for exactly this; our hook was wrapping an arbitrary shell string. *Not valuable:* rtk compresses **exactly the commands our own standards route through the `Grep`/`Glob`/`Read` tools instead of Bash**. The overlap with what our workers actually put through Bash is thin — and the better agents follow their own instructions, the thinner it gets. Weigh the 54–94% against the lost error text; **neither half alone is the honest answer.** |
| **caveman** (github.com/juliusbrussee/caveman) | Skill instructing terse "caveman" prose; `caveman-shrink` compresses MCP tool descriptions; `caveman-compress` shrinks memory files. | Realistic total-session savings ~4-10% (prose is a small slice of agent output). `caveman-shrink` has NO headroom here — mcp_server.py:121 already emits one-liner descriptions. | HIGH: degrades readability of worklogs, decisions, and user-facing reports — exactly the artifacts this design depends on for grounding, review, and human triage. | **SKIP.** Optionally evaluate `caveman-compress` on W1 event digests later (out of v6 core). |
| **graphify** (github.com/safishamsi/graphify → `Graphify-Labs/graphify`; the PyPI distribution is **`graphifyy`**) | Pre-session Tree-sitter+NetworkX knowledge graph of a repo; the agent queries the graph instead of re-reading files. Exercised **CLI-only** — nothing was hooked into the harness and no installer path was invoked. | **MEASURED NEGATIVE (d163, d169; `docs\design\s30-plugin-enablement\GRAPHIFY-MEASUREMENT.md` §4 and §7.4).** Numbers are a3c's **clean-shell** re-drive; a3's originals were gathered in an rtk-corrupted shell, so they were audited and independently re-measured — **and every one of the six reproduced exactly, byte-for-byte. The two sets are IDENTICAL. a3 is vindicated, and we say so rather than quietly swapping the numbers.** Against the real alternative an agent uses (grep + read), the flagship `query` path costs **2.1× more** tokens on Q1 and **38.2× more** on Q2 — and **answered 2 of 3 real structural questions WRONG**. `explain` (single symbol) is the one win: **0.72×** (210 vs 292 tok) and richer. The **build** is genuinely cheap and was not oversold: **~28 s wall-clock, 0 LLM tokens** (local tree-sitter AST). | **The vendor's self-reported reduction ratio on this repo MUST NEVER BE QUOTED AS OUR RESULT.** Its denominator is a **naive full-corpus paste** (~299,800 tok) — a baseline nobody would ever use. Against a strawman you beat, any tool wins; against the real alternative you replace, you may lose. A self-reported ratio is a claim about *the denominator the vendor chose* (d163). | **DO NOT WIRE IT INTO THE HARNESS.** The build works, the graph is queryable, the tool is not inert — it was given a fair corpus and its best shot on a clean graph, **and it lost to grep.** The revisit condition is **CAPABILITY-gated, NOT size-gated:** revisit only if graphify gains (a) registry / string-keyed-dispatch modelling and (b) source-vs-test weighting. **Both dominant failure causes SCALE AGAINST it, not with it** — the call edge an agent wants does not exist in the AST at all (this codebase dispatches tools by string through a registry), and **57.7% of the graph's nodes come from test files**, which BFS surfaces ahead of source. ***"Too small, revisit when it's bigger" is the flattering explanation, and it is FALSE.*** |

**1b. `guard-destructive` — WHAT IT BLOCKS, AND WHAT IT DOES NOT (d167).** We told the user this hook "genuinely protects pool workers now." That sentence claimed a scope the code does not have, and the name is what generated the overclaim.

Enumerated from the live source, `claude\.claude\hooks\guard-destructive.py` (symbol: `decide()`), it blocks **exactly four patterns, and all four are PROCESS KILLS**:

1. `taskkill /IM <critical>` — kills every process by image name.
2. `taskkill /F /T` with **no** `/PID` — force-kills a whole tree with no specific target.
3. `Stop-Process -Name <critical>`.
4. `pkill` / `killall` matching `<critical>`.

The critical-name set is `python`, `pythonw`, `node`, `claude`, `uvicorn`, `conhost`.

**IT DOES NOT COVER FILE DELETION AT ALL.** There is no `rm`, no `rm -rf`, no `Remove-Item`, no `del` in it. A recursive-delete probe **sailed straight through it** — measured (a3b), not inferred.

**That coverage is DELIBERATE AND CORRECT, not a gap to be widened.** The hook's own docstring names its purpose — *"deny blanket process-kills that nuke the whole stack"* — and it exists because of a specific incident (2026-05-31: a worker ran a name-kill to clear one stray monitor and killed the broker, the pool, every MCP server, and every sibling shell). Its policy is exactly R10: **allow targeted kills by PID, deny kills by NAME.** A hook that also blocked `rm -rf` would have blocked the user's OWN authorized deletion of the shadow trees (d164). **Nothing here needs widening.**

**The defect is the NAME, not the code. Read it as `guard-mass-process-kill`.** It is real, it is proven live on both the Bash and PowerShell matchers, and it is **narrower than the sentence people remember it by**. Do not write, anywhere, a claim about this hook whose scope exceeds those four process-kill patterns.

**1c. THE CORRECTED DIAGNOSIS — what we believed, and what we then measured (d166).** Three things in the record were wrong. They are published here, not buried, because one of them reached the user and he ruled on it.

- **The destructive-guard "gap" NEVER EXISTED.** The belief (still on the record as **d155**, status `active`) was: *the pool config has no hooks block, therefore pool workers run without `guard-destructive`.* **The premise was TRUE; the inference was FALSE.** Pool shells also read the **PROJECT** config, `claude\.claude\settings.json`, which registers `guard-destructive.py` on **both** the Bash and PowerShell matchers. **PROOF (a2d, measured):** a2c had removed rtk from the POOL config, yet a2d's POOL-spawned shell **still had the rtk hook live** — it can only have come from the project config. **So pool workers had the guard all along; no worker was ever unguarded, and a2's addition to the pool config was REDUNDANT, not protective.** This was escalated to the user as a real safety gap, and **he ruled on a gap that did not exist.** The first link in that error chain was ours.
- **rtk was inert for ONE reason, not two.** The record claimed two independent causes — the binary was absent **and** the hook "never loaded for pool shells" because the pool config had no hooks. **The second is FALSE**, by the same two-config proof above. rtk no-opped for exactly one reason: **THE BINARY WAS ABSENT** (d4).
- **The rtk hazard was PROJECT-WIDE, not pool-only.** The project config wires rtk for **every** shell, so the broken wrapper was live in **every** shell — pool workers and foreground alike — from install until the fix. Bounded honestly (d169): the rtk hook is on the **Bash matcher only**, in both configs, so it could never rewrite a PowerShell tool call, and `Read`/`Grep`/`Glob` never route through Bash. The hazard was *every Bash command in every shell*, which is not the same as *every shell's every action* — **imprecision that OVERSTATES is still imprecision.**

**Where the REAL token savings in this design come from** (each a bigger lever than any external tool): W7's reconcile short-circuit (idle ticks collapse to one line — the largest waste today), W1's digest (220k → <10k re-grounds), W4's role-scoped tools, W6.5's guide dedup, W10's model tiering, W12's token-free pause (zero burn while away) — and the 1-hour prompt cache below.

- **Codified as CORE coding-standard #18** (`required`, O(1)-in-domain tool output): the s17 hot-path bounding — `recipe_context`, `get_recipe_digest`, `read_object`/`query_objects`, and the `*_list` tools all reshaped to a window+cursor **by construction** with full-fidelity-one-read (`detail='full'`/`fields`) preserved — is the single biggest per-tick lever, and it is now a reviewer-enforced rule so a newly added tool cannot reintroduce a one-row-per-decision/action/event payload that grows with recipe/plan/event count.

**2b. 1-hour prompt cache (verified against code.claude.com/docs/en/prompt-caching.md — HIGH leverage for this harness).** Claude Code caches automatically; the TTL depends on auth: Claude subscription (Max/Pro) = **1-hour TTL by default**; API-key / Bedrock / Foundry = 5-minute default with an explicit opt-in: **`ENABLE_PROMPT_CACHING_1H=1`** (bills cache writes at the higher 1h-write rate — 2× vs 1.25× — worth it when a shell is re-read ≥3× within the hour, which every heartbeat-driven shell is). Action: stamp `ENABLE_PROMPT_CACHING_1H=1` in `build_env` for all spawned shells when the stack runs on API-key auth (no-op on subscription). Effect on W7: with a 1-hour TTL every 10-30-min wake band rides a warm cache (~0.1× read) instead of a cold full-price re-read of the shell's entire context — this changes PACING from cache-constrained to purely workload-driven; keep the TTL comment in the table but bands no longer need to squeeze under 5 minutes. Note: on subscription, exceeding the plan limit into usage credits silently drops the TTL back to 5 min.

**Cache-invalidator discipline for periodically-woken shells** (each of these forces a full recompute of the cached prefix — encode as rules in the loop-and-heartbeat guide + pool behavior): never switch `/model` or `/effort` mid-session (set at spawn — W10a does); never connect/disconnect MCP servers mid-session; Claude Code UPGRADES invalidate all prefixes on resume — `DISABLE_AUTOUPDATER=1` (W14) is therefore ALSO a cache protection, not just a breakage guard; keep cwd/shell/platform stable across wakes (the pool already does); `/compact` rebuilds the conversation cache but reuses the system-prompt cache (compaction cost is bounded).

**4. Consolidation (rides W4's role table) — the GUIDE SWEEP lands in the SAME change, or the derived-floor test rightly fails.** The guides pervasively instruct the old verbs (`record_decision`/`remember` in neuron.md:262 + phase-d; `get_specialist_doc` in worker.md/reviewer.md; `propose_spec_learning`/`resolve_spec_learning` in worker.md 1b + neuron.md:314). Retiring a verb from the MCP surface while a guide still instructs it recreates the planner/update_object regression class. Therefore each consolidation = one atomic change: retire the verb from toolsets AND replace every reference across neuron.md, agentic-plan.md, worker.md, reviewer.md, and all phase/shape guides, THEN regenerate the derived-floor test from the swept guides:

- 4 memory verbs → `record_context` — **toolset half ALREADY DONE in Phase 1** (`_CONSOLIDATED_OUT`, roles.py:43-48); the GUIDE sweep (neuron.md, phase-d, worker/reviewer references) is the outstanding half. `get_specialist_doc`/`propose_spec_learning`/`resolve_spec_learning` are still IN role toolsets (roles.py:59/101/102) — those retire here with their sweeps.
- `get_specialist_doc` → `get_specialist_docs` (sweep: worker.md Step 2, reviewer.md Step 2, planner-phase-author:54)
- `propose_spec_learning`/`resolve_spec_learning` → auto-propose + batch `resolve_spec_learnings` (sweep: worker.md 1b, reviewer.md Step 3, neuron.md:314, phase-d)
- **`record_recipe`/`record_plan` STAY in the neuron/planner floors** — drive's `replan` instruction and phase-a/e escape-hatch references still name them (audit found live call sites); only retire `record_step` if the call-site audit comes back empty.

Targets — **CORRECTED 2026-07-11 (s29/a3b). The original line read "worker ≤ 22, reviewer ≤ 14, planner ≤ 28, neuron ≤ 45" and all four numbers were wrong.** Three sat BELOW the derived floor and one was unreachable by construction. These are the MEASURED, decision-backed values (`tools\roles.py`; ceilings pinned by the `CEILINGS` constant in `tests\test_w4_roles.py` — cited by SYMBOL, not line: s29/a4 found this citation pointing at `# (s29/a3b).` because the line had already shifted, which is the very cite-a-referent-you-did-not-read failure this pass exists to kill):

| role | ceiling | why it is not the old number |
|---|---|---|
| **worker** | **≤ 21** | was 22. Every intermediate move was a derived-floor RAISE under a recorded decision (`assemble_ruleset`, d62(a), 22→23); W6.4 then retired `get_specialist_doc` + `propose_spec_learning` and the floor DROPPED to 21. |
| **reviewer** | **≤ 17** | was 14. Raised 14→15 (W15 `search_context`), 15→16 (s25/a4 applying d62), 16→17 (d62(a) `assemble_ruleset`), 17→19 (W9 part 2); then W6.4 withdrew `propose_spec_learning` (→18) and s29/a2 removed `record_direction_verdict` with the neuron-facing direction surface (→**17**). |
| **planner** | **≤ 34** | was 28. Five decision-cited raises: 27→29 (d14/d15 plan-CRUD restore), →30 (W15 `search_context`), →31 (W5 `convene_consult`), →32 (d17 `get_recipe_digest`), →34 (s25/a4 applying d62: `status_ping` + `neuron_search`). W6.4 retires none of the planner's verbs. |
| **neuron** | **NO CEILING — the "≤ 45" was never implementable** | `_NEURON` is DERIVED (`roles.py`): `registry − SPECIALIST_ONLY − RETIRED_VERBS` = **87 − 4 − 8 = 75**. No subtraction the design specifies reaches 45, and **no test has ever asserted a neuron ceiling** — so nothing was relaxed to get here; the bound simply never existed in code. |

**Each ceiling DROP is as load-bearing as each raise.** Consolidation lowers the derived floor, so the ceiling must drop with it: a ceiling left at the old number is not headroom, it is slack that lets the surface regrow silently.

**A ceiling is a CONSEQUENCE of decisions, never a budget handed down.** This line drifted for one reason: every raise was recorded against a decision and the DOC was never brought back into sync — so the code stayed decision-correct while the design accumulated four false numbers, and a reader trusting the design would have "fixed" working code. Do not cite a remembered ceiling; re-derive it from `roles.py` and cite the decision that moved it. The per-role inventory snapshot at `docs\design\v6-audit\role-toolsets-derived.md` must reproduce the derived surface.

**5. Guide condensation (W6.5).** One canonical guide `loop-and-heartbeat.md`: the react→reconcile→next_action contract, the ONE canonical cron prompt constant (W7), the monitor re-arm rule. Every other guide and role .md replaces its restatement with a one-line `get_guide("loop-and-heartbeat")` pointer. Trim: reactive-streams.md ~15-20% (keep decision tables, cut narrative), architecture-vocabulary.md ~10-15%, planner-phase-drive.md ~10% (checklist stays; remove the manual cron-retune paragraph at :70-72 — superseded by W7). **Keep every phase gate and refusal rule intact.** Measure per-role activation token cost (OTel) before/after; regression bar: a smoke recipe completes with no new hallucination-class failures.

### Files

`claude\.claude\settings.json`, new hook script, `tools\roles.py`, `.claude\commands\*.md`, `docs\guides\*` (+ new loop-and-heartbeat.md), `edp-pool\...\pty_launcher.py` (EDP_RTK env).

### Acceptance

- Worker activation prompt tokens drop materially vs. baseline (OTel).
- ~~rtk visible in a spawned worker transcript; cleanly absent with EDP_RTK=0.~~ **MET, and superseded by a stronger bar (s30).** "Visible in a transcript" proves the hook *fires*; it does not prove the hook is *correct* — the s30 wrapper fired perfectly while silently corrupting what commands MEANT (d165). The bar that actually holds is the one a2e/a2f ran: a **differential ON/OFF semantics matrix with a positive control** (prove the harness can still SEE the bug before trusting a no-divergence result), plus compression measured as a number so the fix cannot pass by making rtk inert. See `docs\design\s30-plugin-enablement\RTK-MEASUREMENT.md`.
- Grep shows the loop/heartbeat text exists in exactly one guide.
- Smoke recipe completes on condensed guides.

**Size: S/M** (rtk S; condensation M, editorial with measurement).

> **REGISTERED ≠ FUNCTIONING ≠ HARMLESS — the durable lesson of the rtk row, and it generalizes past rtk.** We proved a third state exists beyond the two we knew. The hook was *registered* (in the config), it was *functioning* (it fired, observed, and it genuinely compressed) — **and it was still wrong**: it ran exactly as designed and corrupted what it wrapped, exit 0. That state is caught only by **exercising the command and comparing MEANING**; every hook-fires check PASSED throughout. Before trusting an OFF arm, ask what the OFF arm itself changes — **a harness that does not reproduce the real shell will mismeasure the real shell, quietly, in the direction that looks like a clean null.** That trap bit this recipe twice (d165's `rtk bash -c` false-zero; d168's `bash -c` dropping the `rg` shell function and reading it as "absent").

---

## W7 — Self-paced cadence (server-driven pacing) — NEW

**Problem:** evidence #7. Pacing lives in manually retuned crons; reconcile prompts fire into heads-down workers; the worklog is event-driven only, so a 20-40 min reasoning block writes nothing (status_ping/inspect_worker docstrings admit it), making busyness invisible.

### Design

**1. Computed `wait_hint`.** Code-grounded state: `status_ping` already carries a `wait_hint` field (_tools.py:2238) but it is qualitative PROSE keyed to liveness, with no `wait_reason`; `next_action` returns `heartbeat_secs`/`wait_cycles` via `_enrich_wait` (_tools.py:125-172) but no hint; `reconcile` returns `{changed, detail, alert}` with none. W7 upgrades `wait_hint` to a minutes-valued hint + adds `wait_reason`, on all three outputs. Pacing policy table (data):

```python
PACING = {  # state → (hint_minutes, rationale)
    "child_in_progress_recent_output":  (10, "heads-down; leave alone"),
    "child_in_progress_stale_output":   (2,  "probe: status_ping → inspect_worker"),
    "verify_pending":                   (1,  "acceptance imminent"),
    "awaiting_user":                    (30, "nothing moves without the user"),
    "idle_or_done":                     (30, "wrap-up cadence"),
}
```

Inputs available in code: action statuses, last worklog ts, pool liveness. `next_action`/`reconcile`/`status_ping` return `wait_hint` + `wait_reason`.

**2. Busyness signal.** Pool-side `last_output_ts`: NOT tracked anywhere today (code-grounded) — the liveness probe is pid/create_time-fingerprint based and `GET /v1/liveness/{handle}` returns a bare `{handle, state}` (service.py:387). But the pool DOES drain every PTY to a per-session log (`<log_dir>\<safe_handle>.log`, spawner.py:205 / pty_launcher.py:444-483), so `last_output_ts` = that file's mtime — derive it there. Two shape changes required: the pool endpoint returns `{state, last_output_ts}`, and `HttpPool.liveness` (clients/http_pool.py:120-123, currently returns the bare state string) changes return type — sweep its call sites.

**3. Reconcile short-circuit — the actual enforcement.** The FSM cannot call the shell's client-side Cron tools, so pacing is enforced where the server CAN act:

- **Canonical RECONCILE-LOOP cron prompt (neuron + planner ONLY)** (exported in the loop-and-heartbeat guide + W2's rewire block): `"call reconcile then next_action and obey wait_hint: if it says wait, end your turn"`. **Worker and curiosity keep their existing check_inbox-based prompts verbatim** (worker.md Step 0: check_inbox → continue-with-answer / else status_ping + end turn; curiosity.md Step 0: check_inbox → process NEW consult / else end) — they do not call reconcile/next_action. The invariant is "never the verbatim goal", NOT "one prompt for all roles". The rewire block (W2) hands each role ITS OWN canonical prompt.
- **Short-circuit:** rides the EXISTING `changed=False` path — an idle `reconcile` already returns `changed=False, detail="nothing to reconcile (recipe record already matches reality)"` (_tools.py:283-327; `changed` = "did this tick mutate the record to match reality", computed from `_recipe_sig` before/after + step sync + liveness — there is NO per-tick snapshot and none is needed). W7 makes the pair cheap end-to-end: when reconcile returns `changed=False` AND the inbox poll surfaces nothing new AND `ack_epoch` matches, `next_action` returns the one-line `{no_change: true, wait_hint, wait_reason}` instead of the full instruction+context push. The inbox-diff and epoch inputs are NEW to this computation (today's `changed` doesn't include them). Token cost of over-frequent ticks collapses even if the cron interval is never retuned.
- Shells SET the cron interval from `wait_hint` at arm time and MAY re-arm when the hint changes band (one-line guide rule) — but correctness never depends on it.

**4. Rx-noise suppression + Monitor re-arm rule.**

> **AMENDED 2026-07-11 (s29/a3b) — THE KIND-FILTER HALF OF THIS SECTION WAS THE DEFECT, NOT THE FIX.** This section originally said: restrict `observe()` specs to wake-worthy kinds PER ROLE — neuron keeps `question, answer, steer, progress, plan_closed`; planner keeps `done, question, answer, steer`; worker keeps `answer, steer`. **That prescription shipped, and it made the two DRIVING roles deaf to their own mail.** The kind lists omitted `alert` — *the kind reserved for things that must interrupt* — so every alert addressed to the neuron landed in its inbox and never woke it: that the enforce-flip gate was unsound; that the objective gate could not record its verdict; that `record_context` silently drops a `constraint`. And, exactly, **the message telling the neuron its filter had been changed.** The list was ALSO hand-copied into four guides and the code, and all four drifted (the neuron's set appears as 6 kinds, 5 kinds, and 4 kinds, no two agreeing).
>
> **CORRECTED RULE: the neuron and planner subscribe `rx.broker(me)` with NO kind filter.** Every message addressed to you wakes you (`kinds=None` applies no filter — `reactive/runtime.py`). Rate-limit and filter the CHATTY BROADCAST planes (`rx.pool`, `rx.recipe_events`), **never your directed inbox** — total inbound volume is ~40 messages / 12h, so the filter never saved what it cost. Narrow sets remain correct for the SHORT-LIVED roles (worker `answer, steer`; curiosity `answer, consult`), which exist to be told one thing. Single home for the table: `docs\guides\loop-and-heartbeat.md`; never re-spell it. **The channel that carries bad news must not be filterable by the thing the bad news is about.**
>
> RESIDUAL, recorded not fixed: the wake set is narrowed in TWO independent places — the shell's `observe` spec and `ROLE_WAKE_KINDS` (`reactive/runtime.py`) — with no reconciliation and no warning when a directed message arrives outside either. **A shell can silently stop hearing messages addressed to it, and nothing tells it.** Candidate fix (W2): a directed message a subscription cannot deliver raises a countable warning, and `alert` becomes undroppable.

**Do NOT drop `plan_closed`/`done`/`question` — they are the primary wakes** (a prior draft of this section did exactly that; corrected against the guides 2026-07-04). The `observe()` surface gains a per-spec `min_interval_ms` knob (default 0 = today's behavior) so a chatty stream can't machine-gun a Monitor wake. **AMENDED 2026-07-11 (s29/a3), and the amendment is the point:** this section originally specified the knob as a DEBOUNCE compiled down to `RxRuntime.debounce_ms`, and that is what shipped — applied to the whole COMPILED (merged) pipeline. It was wrong. Debounce waits for the stream to fall SILENT for the window and keeps only the burst's LAST item, so with `rx.pool` (a 2s poller) merged into the spec the quiet never comes: a worker's `done` was not delayed, it was DISCARDED, and the pool snapshot that beat it was delivered in its place (a planner went deaf for four minutes). Throttle-on-merge fails identically — a single knob on a merged stream is the wrong SHAPE, whatever the operator. The knob is therefore a PER-SOURCE RATE LIMIT (`ops.sample`), applied by `RxRuntime` to the polled snapshot sources ONLY (`pool`/`plan`/`external`, `RATE_LIMITABLE_SOURCES`) as the spec constructs them — BEFORE any `rx.merge`. The critical planes (`worklog`/`broker`/`recipe_events`, `CRITICAL_SOURCES`) are never limited at any setting, so no knob value can starve a once-only event. Pinned by `tests/test_w7_debounce.py::test_a_critical_event_survives_a_continuous_chatty_co_source`, which goes RED against both defective shapes. (This completes the DELIVERY half of the d31/s15 event-loss fix: s15 hardened EMISSION — the legible `action_status_changed` worklog line — and that fix is intact and working; it explicitly deferred the pool dedup-snapshot residual, and that residual is what the debounce amplified into starvation. INCOMPLETE, NOT REGRESSED.) **The Monitor re-arm rule — AMENDED 2026-07-11 (s29/a3): this section's original claim was FALSE and it shipped into two guides.** It said a Monitor invocation is CONSUMED when its event fires, so the shell should immediately re-run the SAME `monitor_cmd`. The driver does NOT exit on fire: `driver.run` subscribes and blocks, and its sources (broker SSE, file tails, pollers) never complete, so it keeps streaming one NDJSON line per event until `TaskStop`. Re-running the `monitor_cmd` starts a SECOND driver on the same spec — a planner obeying the rule literally reached FOUR live drivers, every event arriving 4x. Note the self-contradiction the guides inherited: the same guidance ALSO warns that a second `observe()` mints a duplicate driver, so its re-arm rule manufactured the exact duplicate its sibling rule forbids. Canonical rule now: **arm the Monitor ONCE (`persistent: true`), handle each wake, do NOT re-run the `monitor_cmd`; re-arm only on evidence the driver is gone.** And because a dead or STARVING subscription is indistinguishable from a quiet channel, VERIFY the driver is live after arming and after any restart/compaction — absence of wakes is not evidence of absence of events. Post-compact, the cmd string is gone from context — W2's rewire block hands it back. For neuron-critical subscriptions, `register_rule` → RuleSupervisor is the durable path that survives shell restarts entirely.

**5. Kill the ScheduleWakeup-long-prompt pattern.** Canonical constant + W2's rewire hand-back + the stale-doc fix (W2.5). No server-side code guard is possible (ScheduleWakeup is client-side) — enforcement = the rewire block always carries the canonical prompt and W6.5 makes it the only documented form.

### Files

`fsm\recipe_fsm.py` + `fsm\plan_fsm.py` (wait_hint computation + reconcile short-circuit), `tools\_tools.py` (NextAction/Reconcile/StatusPing outputs), `reactive\runtime.py` (**per-source rate limit** — `RATE_LIMITABLE_SOURCES` vs `CRITICAL_SOURCES`; the knob is applied here as the spec constructs each source, NOT in the driver) + `reactive\driver.py` (hands the knob to the runtime; `_apply_debounce` is DELETED and the compiled pipeline is never wrapped), `edp-pool\...\service.py` (last_output_ts), guides + role .md (canonical prompt, hint-obeying rule).

### Acceptance

- Simulated 20-min heads-down worker: planner ticks return no_change one-liners with wait_hint ≥ 10 min.
- A worker answer flips the next tick to full instruction within one cadence.
- **Per-source rate-limit forcing test** (AMENDED 2026-07-11, s29/a3 — this line used to read "Driver debounce unit test", and a unit test of the debounce is precisely what could NOT have caught the defect the debounce caused): a low-frequency CRITICAL event must SURVIVE a continuous high-frequency co-source **with the knob ON** (`tests/test_w7_debounce.py::test_a_critical_event_survives_a_continuous_chatty_co_source`), and it must go RED against BOTH defective shapes — merged-stream debounce and naive throttle-on-merge. Plus: the knob still quiets the chatty plane, and no critical source is rate-limited at any setting. The absence of exactly this test is why the starvation shipped.
- Token cost of an idle planner hour drops by an order of magnitude vs. baseline (OTel).

**Size: M.**

---

## W8 — Assumption gate (deadly assumptions) — NEW

**Problem:** evidence #5. A load-bearing assumption recorded after signoff flows into dependent work with no user-surfacing gate; the user lost a day and found out via code review.

### Design

**1. Schema.** `Assumption` gains `load_bearing: bool = False`, `status: Literal["pending","acked","rejected"] = "pending"` (non-load-bearing default to acked), `acked_by/at`, `affects: list[str] = []` (step/action ids, optional). Written via `record_context(kind=assumption, load_bearing=true, ...)`. Code-grounded state: `record_context` already ACCEPTS `load_bearing` for assumptions but the routing target `RecordAssumption` (_tools.py:1780-1798) constructs `Assumption(id,text,by,at)` and DROPS it — the surface exists, the persistence is this workstream's work (schema field + routing fix together).

**2. Fail-closed dispatch guard (Guard-B style).** `PoolSpawnWorker` AND `PoolSpawnPlanner` refuse to spawn while the recipe has PENDING load-bearing assumptions — any pending (simple default), or scoped via `affects` when populated. `_precondition` message: "recipe has N unacked load-bearing assumptions [ids+titles] — surface to the user (neuron: one batched AskUserQuestion) and ack via record_user_answer(assumption_id=...) before dispatching dependent work." **Dependent work cannot start on an unconfirmed assumption.**

**Two assumption classes — do NOT collapse them (guide alignment):** the worker/planner "grounding note" path (worker.md Step 2.5, agentic-plan.md grounding: `notify_above(kind='grounding')` then PROCEED, deliberately non-blocking) is UNCHANGED — that's a shell's own in-flight working assumption. The gate applies only to `record_context(kind=assumption, load_bearing=true)` — user-confirmable, day-costing-if-wrong assumptions. Add one line to worker.md Step 2.5 / the planner grounding guide: "if being wrong about this would cost the user a day, it is not a grounding note — record it load_bearing and let the gate hold dependent work." The `record_user_answer(assumption_id=...)` extension is consistent with the existing ask_user→record_user_answer path (neuron-protocol-reference:17).

**3. Batched surfacing.** `recipe_context()`/`get_recipe_digest` carry `pending_assumptions: [{id, title, body}]`; `neuron.md` rule: present ALL pending as ONE AskUserQuestion batch (a single cheap decision, mirroring W3's gate philosophy). `record_user_answer` extended to accept `assumption_id` — note it is comprehension-BRANCH-only today (`_UAIn = {recipe_id, branch_id, answer}`, _tools.py:1651-1674; resolves Branch.status/verdict + clears open_questions): the assumption path is a NEW second mode on the same tool (mutually-exclusive `branch_id`/`assumption_id`), and reject→rejected_option-candidate is an entirely new flow.

**Guard wiring note:** `PoolSpawnPlanner` (_tools.py:1934-1940) is a trivial passthrough today — no guards of any kind, and it does NOT thread `model` either (W10a made the HTTP client model-aware; the TOOL-level threading for planner spawns is still pending — fold into W8's guard change or W10b, one edit either way).

**4. Compaction-safe.** Pending-unacked ids feed W2's `grounding_epoch` — a compact can't lose the gate; the full-digest push re-lists them.

**5. Escape hatch (visible, never silent).** The neuron may proceed ONLY by recording an explicit decision `kind=direction` "proceeding on unacked assumption aN at user risk" — which is itself pushed in every digest thereafter (auditable).

### Migration

Legacy assumptions load as `status="acked"` (grandfathered) — the gate applies to new writes only; no legacy recipe is bricked.

### Files

`schemas\recipe.py` (Assumption), `tools\_tools.py` (RecordContext routing, PoolSpawnWorker/PoolSpawnPlanner guard, RecordUserAnswer), `fsm\recipe_fsm.py` (pending list, epoch input), `neuron.md`, `agentic-plan.md`.

### Acceptance

- Planner records a load-bearing assumption → next worker spawn refused naming it → neuron tick shows the batch → one AskUserQuestion + record_user_answer → spawn proceeds.
- Forced compact does not drop the pending list.
- Legacy recipe dispatches unaffected.

**Size: S/M.** Depends on W4 (record_context); feeds W2 (epoch).

---

## W9 — Direction integrity: artifact-sampling audits at FSM checkpoints — NEW

> **⚠ THE NEURON-FACING HALF OF W9 IS SUPERSEDED AND REMOVED (d128 user
> correction; d129; d132 Phase 5).** Everything below that addresses the NEURON
> — the `DIRECTION_REVIEW_DUE` checkpoint, the `actions_done_since_direction_review`
> counter, the overdue spawn nag, the `off_track` push, `branch_reviewer(scope="direction")`,
> `record_direction_verdict`, and the reviewer's direction mode — no longer exists in
> the code. **The reviewer is the PLANNER's subagent and is never available to the
> neuron**, so a checkpoint ordering the neuron to branch one asserted a capability
> it does not hold. The neuron's direction integrity is **curiosity (OCAK) +
> signoff**: comprehension_recheck → a curiosity consult when bias-risk is high, the
> decision is large, or the recipe is fresh → the recorded signoff (a mutually-agreed
> decision may be signed off without a consult).
>
> **What survives:** the PLANNER's reviewer (`branch_reviewer(scope="spec")`) — the
> objective acceptance gate (d29/d30) — and the constraint proposal → neuron
> confirmation → teeth chain (`confirm_direction_constraints`), which serves every
> caller, not just a direction reviewer. Section text below is kept as the historical
> record of what was built and why.

**Problem:** evidence #6. The neuron blindly trusts worker progress; reviewers check task-level correctness against the spec doc, not recipe direction. Goal-keeper is on-demand-only and text-vs-text; recipe/plan SELF-audit gates were deliberately removed (recipe_fsm.py:70-99, plan_fsm.py:21-25; `docs\design\philosophy\ocak-as-helper-not-enforcer.md` — audits must not be self-graded). NOTHING reads deliverable files against the verbatim goal. Motivating failure: workers hardcoded HTML generation + piles of regex against a simple ask, and nobody caught it.

### Design (NO NEW ROLE — user constraint: the role set is neuron / planner / worker / reviewer / specialist. Direction integrity rides the EXISTING reviewer, in a separate shell, FSM-scheduled, never self-graded)

**1. FSM-scheduled checkpoints.** The RECONCILE/TOOL LAYER maintains `actions_done_since_direction_review` as a recipe field (code-grounding correction: `recipe_next_action` is a PURE function of the Recipe and sees steps, not plan actions — actions live on Plan objects; so reconcile aggregates action statuses across the recipe's plans and stamps the counter, and the FSM reads the field. The neuron never counts anything; its Phase-D loop is step/plan-granular). At every N actions done (default 5, per-recipe overridable) or at each step completion, `next_action` emits `DIRECTION_REVIEW_DUE` — a NEW `InstructionKind` member (schemas/instruction.py:24) — to the neuron: "branch a direction reviewer." Overdue by > 2N actions → `PoolSpawnWorker` warns (not blocks — a genuinely advisory nag, like `_comprehension_recheck`; the teeth are the constraints the review produces). **Router wiring (required — an instruction kind nobody consumes falls through):** add `DIRECTION_REVIEW_DUE` to the neuron instruction-kinds table in `neuron-protocol-reference.md` and a Phase-D router row in `neuron-phase-d.md`: "branch a direction reviewer via `branch_reviewer(scope=\"direction\", ...)`; the verdict returns as `handle_messages`." The off_track→surface-to-user path reuses the existing `comprehension_recheck` handling (phase-d:141-146, stashed via ctx — recipe_fsm.py:424-426).

**2. Reviewer direction mode.** Extend `branch_reviewer(...)` with `scope: "spec" | "direction"` (default `"spec"` — today's behavior, unchanged). **Input-contract carve-out (code-grounded):** `_BranchReviewerIn` currently REQUIRES `neuron_id` and refuses unless that neuron is `stable` with a compiled doc (_tools.py:4385-4436) — direction review has no specialist domain, so `scope="direction"` makes `neuron_id` optional and SKIPS the stable/compiled-doc preconditions, and its brief is assembled via a different grounding path than today's `{task,target,criteria,spec_id,concerns}` message. "Same shell type, same skill file" holds; "one extra mode" on the tool means a real branch in its input contract. `reviewer.md` gains a direction-mode section. In direction mode the reviewer's grounding is assembled deterministically by the spawn tool:

- `get_recipe_digest` — led by north_star (W1.5): verbatim goal + current_shape + active constraints.
- **Artifact SAMPLE:** paths harvested **in code** — primary source: `Acceptance.verify` dicts carry literal paths/globs (`{check:"file_exists", path}`, `{check:"glob_matches", pattern}` — schemas/plan.py:31-37); secondary: `Acceptance.actual` + `actual_ref` evidence sidecars (plan.py:21-26) — for the reviewed window's done actions. The reviewer reads the actual files, not summaries.
- Rubric: does this artifact serve the verbatim goal? does it violate any active constraint/ban? is it gratuitous complexity relative to the goal? (the hardcoded-HTML+regex class is exactly a gratuitous-complexity finding).

This keeps the user's division of labor intact: workers = business logic, reviewers = correctness — where "correctness" now includes *directional* correctness against the north star, not only spec adherence. Same shell type, same skill file, one extra mode.

**3. Findings become enforcement, not prose.**

- Constraint-shaped findings → the reviewer proposes `record_context(kind=rejected_option, constraint={...})` records; neuron confirms in one batch → W2 guards then block recurrence at `record_action_status`/spawn time.
- Stack-craft findings → `emit_recipe_event(kind="learning", spec_id=...)` → W3 auto-propose → spec overlay. The review feeds BOTH enforcement loops.
- Verdict recorded on the recipe — NOT a drop-in reuse of `record_audit_verdict` (code-grounded: that tool is OCAK-shaped — `findings: dict{O,C,A,K}`, `verdict: passed|gaps_found|overridden_by_user`, persisted as `OcakAudit`, _tools.py:3566 / schemas/recipe.py:196-205). W9 needs a sibling/extended schema: `{on_track|drifting|off_track, findings: list, sampled_paths: list}`. (`record_branch_verdict` is comprehension-branch machinery — not the hook.) `off_track` → the neuron's next_action carries an AWAIT-style surface-to-user instruction (the comprehension-recheck pattern, recipe_fsm.py:261).

**4. Goal-keeper NOT wired in.** Per user direction, no watchdog roles (goal-keeper/drift-checker) join the flow — `consult_goal_keeper` remains available on demand but the framework does not schedule it. Text-level drift is covered by the direction reviewer's rubric (it reads the verbatim goal directly). **Supersession housekeeping (philosophy audit):** this reverses `team-architecture-restoration.md` Phase 6 (FSM-gated goal-keeper/pattern-observer) and Phase 5 (blocking pre-sign-off critic) — mark BOTH sections `superseded_by: DESIGN-v6 W9` in that doc (the ocak.md retirement pattern) so future grounding doesn't resurrect them. **Role-set clarification (internal consistency):** "no new role" means no new WATCHDOG/reviewer role; W5's `consult` is a human-comms channel shell in the same category as curiosity/pattern-observer (which are also `_ROLE_ACTIVATOR` roles outside the working five) — it does not reopen the role set.

### Files

`fsm\recipe_fsm.py` (checkpoint counter, DIRECTION_REVIEW_DUE, off_track surfacing), `tools\_tools.py` (BranchReviewer scope param + deterministic grounding assembly + evidence-path harvest, verdict recording), `.claude\commands\reviewer.md` (direction-mode section), `neuron.md`.

### Acceptance

- A recipe with 5 done actions emits DIRECTION_REVIEW_DUE; the direction reviewer spawn receives the verbatim goal + real artifact paths.
- A seeded gratuitous-artifact fixture yields an off_track verdict that surfaces to the neuron AND a proposed constraint that subsequently blocks a matching `record_action_status`.
- `scope="spec"` reviews are byte-identical to today's behavior; reviews never run in the reviewed shell; no new role exists in `ROLE_TOOLSETS`.

**Size: M.** Depends on W1 (north_star, digest), W2 (constraint teeth); feeds W3. (Smaller than before — no new role, no new command file beyond a reviewer.md section.)

---

## W10 — Model tiering + consult-escalation ladder — NEW

**Problem:** evidence #8. Everything runs Opus, including audits and heartbeat shells. Only Sonnet is measured-safe (MODEL-TIERING-BENCHMARK.md §5: quality-delta ~0, −40% cost, narrow workers only); "Haiku-heartbeat WITHDRAWN" shows unmeasured tiers get pulled. No token ledger, though OTel/Phoenix :6006 already captures per-request tokens with per-shell `edp.role/handle/recipe_id` attrs (`_shell_otel_env` — pty_launcher.py:322 post-W14; the :148 anchor is pre-Phase-1).

### Design

**1. W10a — ✅ SHIPPED in Phase 1.** All 6 non-worker `HttpPool` methods now thread `model` (http_pool.py:41-118); the edp-pool server side was already generic (`build_argv --model` — pty_launcher.py:228/250 post-W14 — and `service.py:330` reads `model` from any spawn body). Residual W10a item folded into W10b: the TOOL-level `PoolSpawnPlanner` (_tools.py:1934) still doesn't accept/pass `model` (see W8's guard wiring note). (There is no consult route — W5's `convene_consult` builds its spawn call model-aware from birth on the generic /v1/spawn body.)

**2. `MODEL_TIERS` data table** (`tools\roles.py`, next to ROLE_TOOLSETS): `(role, task_class) → {model, status: "measured"|"candidate"}`:

- **measured:** worker/narrow → `claude-sonnet-4-6` (benchmark §5: quality-delta ~0, −40% cost); everything else → `None` (host default Opus).
- **candidates (NOT defaults):** worker/coding → `claude-sonnet-5` (near-Opus coding quality at $3/$15 vs Opus 4.8's $5/$25 — 40% cheaper per token, intro $2/$10 through 2026-08-31 — BUT its new tokenizer produces ~30% more tokens for the same text, so the net saving is smaller than sticker; it also follows instructions more literally, so compiled spec docs must state scope explicitly); direction-reviewer (W9) → sonnet. Reviewer-as-defense-layer stays Opus until benchmarked — degrade the safety net last. A candidate tier is used only when the spawn passes `allow_candidate_tier=true` (explicit experiment), and each candidate ships with a named benchmark task in the table comment. **No tier goes default without a MODEL-TIERING-BENCHMARK.md entry** (the withdrawn-Haiku discipline).
- **Why switching coding workers to Sonnet won't wreck the framework — the guardrails are model-agnostic:** the compiled spec doc is the worker's grounding regardless of model (W3 keeps it current); W2 constraint guards refuse banned output in code; the dual-gate acceptance check (worker runs it, reviewer independently re-runs — d30) catches wrong deliverables; the reviewer (Opus) rectifies; W10's escalation ladder convenes an Opus consult when a Sonnet worker churns. The framework's correctness never rested on the worker's model — it rests on the gates. Expected failure mode of Sonnet workers is more escalations/review-fixes on the hardest actions, which the benchmark run must quantify before default flip.
- Bookkeeping ticks (reconcile/next_action) are NOT spawns — their cost is attacked by W7's short-circuit, not tiering.

**3. Escalation ladder (stuck → consult-opus).** Stuck-detection **in code**, in `reconcile`/plan FSM. `ESCALATE_CONSULT` = a new `InstructionKind` member (like DIRECTION_REVIEW_DUE):

- Signals (code-grounded): re-dispatch churn IS directly readable — `Action.attempt` (plan.py:66) / `RecipeStep.attempt` (recipe.py:119), and `_comprehension_recheck` already keys off `attempt >= 2` (recipe_fsm.py:274). **Failed-ACCEPTANCE cycles have NO counter today** (`attempt` counts re-dispatch, not failed verifies) — add a `verify_failures` counter field bumped by the gate, or derive from a worklog scan (counter preferred: cheap, deterministic). Third signal: a worker parked on a question > 2× wait_hint.
- Response: `next_action` emits `ESCALATE_CONSULT` instructing the planner/neuron to `convene_consult(recipe_id, question=<auto-composed from the stuck action's acceptance diff + worklog tail>, model=<tier table: consult → opus>)` (W5). **Stronger-than-Opus tiers are NEVER auto-selected** — only when the user passes them explicitly. The consult verdict arrives on the asker's inbox; acting on it is recorded via `record_context`.

**4. Per-shell token ledger — ~~`cost_report(recipe_id)`~~ NOT BUILT. WITHDRAWN BY USER RULING (d77), 2026-07-10.**

> **DO NOT BUILD THIS, AND DO NOT SUBSTITUTE FOR IT.** The user withdrew it in these words: *"cost report is not shell count. I dont want you to build a dumb harness and hardcode the requirements… This discipline should exist within its role."* The thing he asked for is **discipline in the neuron's role** — a neuron composes a recipe sensibly BECAUSE a step costs a planner plus its workers — and that belongs in the orchestrator/neuron guide as **prose the model reads and reasons with, NOT a tool that computes a number the model then obeys.** W10b therefore keeps model tiering (d53) and the escalation ladder, and drops this line item. o4's verification clause requiring `cost_report` was formally removed (d115); its absence blocks nothing.
>
> **Phoenix being reachable is NOT a licence to build it anyway.** Two corrections to the original text, which is preserved here because both errors are instructive: (1) it asserted *"Phoenix is currently DOWN"* — **that is d4, and d4 is STALE.** Phoenix answers **HTTP 200 on :6006** (self-probed 2026-07-11, s29/a3b; independently probed by three earlier shells). (2) The original's own code-grounding still stands and is the reason a substitute is impossible to verify honestly: **there is NO Phoenix query surface anywhere in the tree** — the only Phoenix code is `doctor.check_phoenix`, a reachability ping. A client written against it could not be acceptance-verified. **A fabricated cost number is a finding of the same class as a fabricated `status="measured"` row.**

### Files

W10a: `claude\src\edp_claude\clients\http_pool.py` ONLY (the 6 non-worker methods — edp-pool is already generic, no changes there). W10b: `tools\roles.py` (MODEL_TIERS), `tools\_tools.py` (spawn tools thread model, ESCALATE_CONSULT — **no `CostReport`; see item 4**), `fsm\{plan_fsm,recipe_fsm}.py` (stuck signals), `MODEL-TIERING-BENCHMARK.md` (candidate entries).

### Acceptance

- Reviewer spawn with the explicit candidate flag launches on Sonnet; default spawns unchanged (Opus).
- A fixture with 2 failed acceptance cycles emits ESCALATE_CONSULT with an auto-composed question.
- ~~`cost_report` returns per-role token totals for a live recipe.~~ **REMOVED (d77/d115): the tool is not built, so this criterion cannot be met by any honest evidence and its absence blocks nothing.** Do not manufacture evidence for a clause you have been told not to satisfy.
- No candidate tier ever selected without the explicit flag (unit test).

**Size: M.**

---

## W11 — Suspend/resume: close a live session, resume via one command — NEW

**Problem:** recipes run for weeks (0e7ca8: 14 active days), but there is no sanctioned way to STOP. Closing the foreground neuron shell orphans live planner/worker shells and their crons; resuming means manually re-grounding and hand-reconciling pool/broker reality. The plumbing half-exists: the pool pins `--session-id` at spawn and supports `--resume <base> --fork-session` (`pty_launcher.build_session_args`), but only the specialist snapshot/branch path uses it, and the foreground neuron's claude session id is unknown to the harness (it isn't pool-spawned).

### Design

**1. Session registry (pool) — with the LOAD-BEARING PREREQUISITE the earlier draft understated (code-grounded 2026-07-04).** "The pool already pins a session id per spawn" is FALSE for planners/workers: `spawn_planner`/`spawn_worker` pass NO `claude_session` (http_pool.py:41-62), `svc.spawn` forwards it to the spawner but never STORES it, and with both session args None, `build_session_args` returns `[]` (pty_launcher.py:271-273) → claude auto-generates a session id the pool never learns. Only specialist/reviewer spawns pin one. **Therefore W11 step zero: pin a fresh `claude_session` (uuid) on EVERY planner spawn and persist it.** Current store shape (service.py:190-208): `svc.sessions` keyed by pool sid (`role:uuid`) with `{session_id, role, handle, parent, state, proc:{pid,create_time}}`, `locks: handle→sid`, both durably persisted (service.py:91-122) — ADD `claude_session_id`, `spawned_at`, `last_seen` (recipe_id is parseable from the planner handle `<recipe>:<step>`; store it explicitly anyway). `GET /v1/sessions` EXISTS unfiltered (service.py:379-381) and `HttpPool.sessions()` takes no filter (http_pool.py:125) — extend both with `recipe_id`. Without the pinning, the planner fork-resume below has nothing to fork.

**2. Foreground session capture (hook, not memory).** A `SessionStart` hook in `claude\.claude\settings.json` (hooks receive `session_id` in their JSON input) appends `{session_id, cwd, config_dir: $env:CLAUDE_CONFIG_DIR, started_at}` to `claude\.sessions\foreground.jsonl`. When a `/neuron` activation binds to a recipe, the neuron records the current foreground session id onto the recipe (`recipe.neuron_session_id`, via the normal store path) — captured in code at bind time, not remembered by the LLM.

**Launcher compatibility (user's protocol — do not change it):** the user launches the base session via a PowerShell profile function `claude-personal` (`$env:CLAUDE_CONFIG_DIR="$HOME\.claude-personal"; claude @args`). Session transcripts live under `CLAUDE_CONFIG_DIR`, so `claude --resume <id>` only finds the session when run under the SAME config dir. Therefore: the suspension manifest and `suspend_recipe` output must print the resume command as `claude-personal --resume <neuron_session_id>` (the function passes args through), derived from the captured `config_dir` — never a bare `claude --resume`. Project hooks and MCP config are cwd-scoped, not launcher-scoped, so `claude-personal` needs no changes — the only requirement is launching FROM the agent home (`C:\Projects\Learning\eda-base3\claude`); a convenience `eda.bat` wrapper that sets `CLAUDE_CONFIG_DIR`, cd's to the agent home, and forwards args covers the from-anywhere case.

**3. `suspend_recipe(recipe_id, reason="")`** (neuron-only, role table):

- Sends a broker `steer` park message to each live planner handle ("finish the current tool call, record_action_status/worklog your state, then pool_close_self"); waits a bounded grace period, then `pool_reap` for stragglers. Workers are disposable by design — they are simply reaped; their actions stay `in_progress` and reconcile handles them on resume.
- Writes a **suspension manifest** `.recipes\<id>\suspension.json` in code: `grounding_epoch`, open steps/actions + statuses, the session registry snapshot for this recipe (handles + claude session ids), pending assumptions/learnings counts, `neuron_session_id`, `suspended_at`, `reason`, and a printed **resume command**.
- Stamps `recipe.suspended_at` (orthogonal to FSM state — suspension is not a transition; `Recipe` is `extra="forbid"` so this and `neuron_session_id` are NEW emission-gated optional fields, the established house pattern per `Decision._ser_load_bearing_gate` / `Comprehension.baseline` — recipe.py:64-79/170-184) and emits a `recipe_suspended` event. Suspended recipes refuse dispatch (`PoolSpawnWorker`/`PoolSpawnPlanner` precondition: "recipe is suspended — resume_recipe first").

**4. Resume via one command.** Two entry points, same code path:

- **`/neuron resume <recipe_id>`** — extend the neuron activation to accept a `resume` arg. Works in any fresh shell.
- **`claude --resume <neuron_session_id>`** — printed in the manifest and by `suspend_recipe`'s output, for full conversational continuity of the foreground neuron. On first `next_action` the W2 epoch check fires anyway (the resumed session has no fresh `ack_epoch` state server-side), so it gets the full digest + rewire block regardless.

New tool `resume_recipe(recipe_id)`:

- Reads the manifest **if present** (a manifest is an optimization, not a requirement — see crash-resume below).
- `reconcile` against pool/broker reality: dead handles cleaned, stale locks released, in-flight action statuses trued up from worklogs.
- Re-grounds via `get_recipe_digest` (W1) — cheap by construction.
- For each in-flight step, re-spawns the planner with `resume_session=<its old claude_session_id>` + `--fork-session` (existing pool support) so the planner keeps its working context; workers are re-dispatched fresh through normal `next_action` flow (disposable by design).
- Clears `suspended_at`, emits `recipe_resumed`, re-arms the heartbeat via the canonical prompt (W7).

**5. Crash-resume is the same path minus the manifest.** `resume_recipe` on a recipe with no `suspension.json` (power loss, killed stack, closed laptop) degrades to pure reconcile + digest + fresh spawns — no data loss because all state is already durable (recipe/plan JSON, broker JSONL inboxes with persisted cursors, spec store). The manifest only adds session-continuity niceties (planner forks, the printed resume command).

**Synergy note:** W2 makes resume nearly free — any resumed or forked session that can't echo the current epoch is handed the full digest and its monitor wiring on the first tick. W11 is deliberately thin: registry + manifest + park/reap choreography + the one-command entry points.

### Migration

Nothing to migrate — suspension is a new, optional record. Legacy recipes resume via the manifest-less crash path.

### Files

`edp-pool\src\edp_pool\{service,spawner}.py` (session registry + endpoint), `clients\http_pool.py`, `tools\_tools.py` (SuspendRecipe, ResumeRecipe, suspended-dispatch precondition in PoolSpawnWorker/PoolSpawnPlanner), `claude\.claude\settings.json` + hook script (SessionStart capture), `.claude\commands\neuron.md` (resume activation arg), `tools\roles.py`, `fsm\recipe_fsm.py` (suspended surfacing in recipe_context).

### Acceptance

- Suspend a live recipe with an active planner: planner parks and closes within the grace period, manifest written with its session id, dispatch refused while suspended.
- `/neuron resume <id>` in a fresh shell: re-grounds < 10k tokens, re-spawns the planner forked from its old session (verify the fork carries prior context), work continues; `suspended_at` cleared.
- Kill the stack mid-step with no manifest → `resume_recipe` recovers via reconcile alone; no duplicate dispatch of `done` actions (W2 guard).
- `claude --resume <neuron_session_id>` continues the foreground conversation and receives the full digest + rewire on first tick.

**Size: M.** Depends on W1 (digest), W2 (epoch/rewire, duplicate-dispatch guard), W7 (canonical heartbeat re-arm); pairs naturally with W10a (both touch the spawn API).

---

## W12 — Browser control panel + token-free pause + inline plan review — NEW

**Problem (user):** no control surface outside the shells. (a) While the user is away, crons/monitors keep firing reconcile ticks — and even "pausing" today means SENDING A PROMPT, which itself burns tokens. (b) Spawn defaults (model tier, `EDP_SPAWN_MODE`, `EDP_SKIP_PERMISSIONS`, `EDP_RTK`) are only editable by hand-editing env/config. (c) There is no plan-mode-like interaction for big decisions: the user cannot comment on specific lines of a proposed plan/design the way PR review allows — multiple structured comments in one pass. (d) Gates that need the user (assumptions, comprehension signoff) are invisible until the user happens to look at the terminal.

**Explicit non-goals (user):** no launch-time binding of the user's own claude-personal session; no controls injected inside Claude Code shells. A separate small browser app.

### Design

**1. Token-free pause via process suspension (the key mechanism).** New pool endpoints `POST /v1/shells/{handle}/pause` and `/resume`: suspend/resume the shell's PROCESS TREE (`psutil.Process.suspend()` → NtSuspendProcess on Windows; the pool already tracks pid+create_time fingerprints). A suspended process executes nothing — its harness crons don't fire, its Monitor subprocess is frozen with it, its MCP connections just idle. **Zero tokens, no prompt sent.** Resume unfreezes; the next tick pays one reconcile (short-circuited by W7 if nothing changed; epoch-checked by W2 if the world moved). `POST /v1/recipes/{id}/pause` fans out to every live shell of a recipe. This is strictly better than any prompt-based pause and also pairs with W11: pause = temporary freeze (state in RAM), suspend_recipe = durable park (state on disk).

**2. The panel app.** Small static single-page UI (no build toolchain — one HTML file + vanilla JS) served by the pool (`GET /panel`), talking to pool + broker HTTP APIs (same-origin via a thin pool-side proxy for broker :9300 to avoid CORS). Views:

- **Shells:** live list (role, handle, recipe, liveness, `last_output_ts` from W7) with Pause / Resume / Wind-down buttons. Wind-down = W11's park steer + grace + reap (for the zombie-base-shell case). Pause-all / Resume-all per recipe. **`last_output_ts` is `None` for EVERY monitor-mode shell** — the column this line names is unavailable by construction for the shells we actually run. It is rendered as honestly unavailable, **never substituted** with a plausible stand-in.
- **Gates:** pending load-bearing assumptions (W8), pending spec learnings (W3), `consult_pending` — with an answer box that posts a structured broker message. **Browser notification** (Notification API) when a gate appears — this is the "user loses a day waiting" fix: the recipe FSM emits gate events, the panel long-polls/SSEs the broker and notifies.

> **AMENDED 2026-07-11 (s29/a3b), superseding the original: the gate-answer box may NOT mint a user ruling.** This line used to specify a *"`record_user_answer`-shaped ack for assumptions"* riding a steer the neuron executes. **That is an AUTHORSHIP CLAIM, and this system cannot make one.** The panel binds to loopback with no auth (the user's informed choice — he is the sole user and it is never exposed). **A SHELL can POST to it too:** a worker has Bash, runs on the loopback interface, and can set any header it likes. And the root is older than W12 — **`broker_send` takes `from_` AS A PARAMETER, so the `from` field is SELF-ASSERTED and any shell may claim any handle.**
>
> **THEREFORE: NO MESSAGE FIELD IN THIS SYSTEM CERTIFIES ITS AUTHOR.** A panel stamp certifies **the PATH TRAVELLED, not the author** (`via=panel`, `authenticated=false`) — it was never an authorship claim, and no mutation-proof can make it one. **A panel-sourced comment is NOT a user ruling.** It may INFORM; for anything LOAD-BEARING the neuron confirms with the human **out-of-band** — which is not a nice habit but *the only mechanism that exists* (it is how a relayed user quote was verified as authentic, by asking him).
>
> Two hard bans follow. **(1) Never name the stamp after the user** — not `user_answer`, not `user_sourced`, no field containing the word USER. A field named for the user on an unauthenticated channel is a fabricated licence compressed into an identifier, and every future reader would read it as authorship. **(2) NEVER WRITE THE CLAIM THAT A SHELL IS INCAPABLE OF FORGING A USER RULING.** That claim is FALSE, and it may appear nowhere — not in code, docstring, comment, field name, panel markup, or any report. (This ban deliberately does not reproduce the forbidden sentence verbatim, so that a grep for it stays clean and any hit is a real one.) What IS provable, and all that is: **the stamp cannot be omitted.** That true sentence is strictly narrower than the false one, and the gap between them is the most dangerous defect shape in this project: **a guard that is real, proven, and NARROWER THAN THE SENTENCE PEOPLE WILL REMEMBER IT BY** — the suite is honest and the SUMMARY guards nothing.
- **Plan review (the plan-mode-like interaction):** the neuron writes big decisions/plans as markdown briefs to `.recipes\<id>\briefs\<n>.md` (new convention, one `record_context(kind=decision)` pointer each). The panel renders the brief; the user selects text → adds a comment; submits ALL comments in one batch as ONE broker message `kind="review_comments"`, body `{brief, comments: [{anchor_quote, comment}]}` → the neuron's `recipe_id` inbox (push via its existing observe subscription — SSE is per-recipient, so the panel posts to that recipient, same rule as W5). **`review_comments` must be `register_kind`'d** — the broker kind registry refuses unregistered kinds fail-closed (edp-contracts/broker.py:86-93; it is not in CORE_KINDS). ~~The neuron treats each anchored comment as a structured user answer.~~ **SUPERSEDED 2026-07-11 (s29/a3b) — see the authorship amendment above: an anchored comment arrives through an unauthenticated local channel, so the neuron treats it as INPUT, never as a recorded user ruling.** Nothing converts a panel message into a user answer: no `record_user_answer` call, no user-answer-shaped payload, no auto-ack landing as a ruling. It is still the PR-review interaction the CLI lacks, without touching the CLI.
- **Spawn config:** toggles for default model tier, `EDP_SPAWN_MODE` (headless/monitor), `EDP_SKIP_PERMISSIONS`, `EDP_RTK` — written to a pool-side `spawn_defaults.json` that `build_env`/`build_argv` read per spawn. Changes affect FRESH spawns only (banner says so). This answers the "modify any setting" ask at the right seam — the pool is what launches shells, not the user's own claude-personal session.
- **Cost:** ~~per-role/handle token totals via W10's `cost_report` (Phoenix :6006).~~ **UNAVAILABLE — and the reason must be stated, not worked around (amended 2026-07-11, s29/a3b).** This view's ONLY data source is `cost_report`, and `cost_report` was **deliberately never built**: the user withdrew it (d77 — *"cost report is not shell count. I dont want you to build a dumb harness"*). So W12 specified a panel view over a source that does not exist.
  **Render it EXPLICITLY UNAVAILABLE, with the reason. NO PLAUSIBLE SUBSTITUTE** — not a token estimate, not a shell count, not a direct Phoenix query (Phoenix answering HTTP 200 is not a licence; d77 forbids the OTel client). **A panel that displays a number it did not measure is the same defect as a pause that reports a boolean it did not observe.**

**3. Auth/scope:** binds to 127.0.0.1 only (same trust model as broker/pool today); no external exposure.

### Files

`edp-pool\src\edp_pool\service.py` (pause/resume/wind-down endpoints, /panel static, broker proxy, spawn_defaults.json), `edp-pool\src\edp_pool\proctree.py` (add `suspend_tree`/`resume_tree` next to the existing `kill_process_tree`), `edp-pool\static\panel.html` (new), `edp-pool\src\edp_pool\pty_launcher.py` (read spawn_defaults), `edp-contracts\broker.py` (`register_kind("review_comments")`), `tools\_tools.py` (neuron brief-writing convention lives in neuron.md; review_comments handling is just inbox messages), `.claude\commands\neuron.md` (briefs + review_comments protocol), `fsm\recipe_fsm.py` (gate events for notifications).

### Acceptance

- Pause on a live worker → its PTY log stops growing, no broker/API traffic, zero token spend for the paused interval (OTel-verified); Resume → next tick is a single short-circuit line.
- A load-bearing assumption fires a browser notification; answering from the panel unblocks dispatch (W8 E2E through the panel).
- A brief with 3 anchored comments arrives at the neuron as ONE structured message; the neuron records each as a user answer.
- Flipping the model-tier toggle changes the next spawn's `--model` and nothing about running shells.

**Size: M-L.** Depends on W7 (last_output_ts), W8/W3 (gates), W10 (cost_report), W11 (wind-down); panel skeleton + pause can land early with stubs.

---

## W13 — Compact/resume survival as a skill (self-serve grounding) — NEW

**Problem (user):** today the user has to message a compacted shell "ground yourself / fix your monitor". W2 makes the SERVER hand wiring back — but only when the shell calls `next_action`. The missing piece is the client half: making the shell reach for `next_action` immediately after a compact, without user prompting, and WITHOUT refetching the massive neuron/planner guides (9-12KB each) it already paid for pre-compact.

### Design

**1. `/reground` skill** (`.claude\commands\reground.md`, ~15 lines, in every role's toolset via `get_guide`): `whoami` → `next_action(ack_epoch=null)` → obey the returned digest + rewire block (re-observe, re-arm canonical cron) → continue. No file reads, no guide loads — the digest IS the grounding.

**2. Automatic invocation via SessionStart hook.** `claude\.claude\settings.json` gains a `SessionStart` hook with the `compact` matcher (fires when a session resumes after auto-compaction; also `resume` matcher for `claude --resume`). The hook script emits `additionalContext`: "Context was compacted. Run /reground now. Do NOT reload phase guides — the digest carries your phase checklist." The harness injects this the moment the compacted session continues — zero LLM memory dependence, zero user messaging. (Spawned shells inherit the hook via cwd=agent_home, same as the rtk hook.)

**3. Guide diet on resume.** Phase guides are load-bearing at phase ENTRY, wasteful on re-ground. `get_recipe_digest`/the epoch-mismatch push embed a **per-phase resume checklist** (3-5 lines, maintained as a static table in code next to PACING — data, not a guide fetch). This is consistent with the guides' own anti-preload + reload-on-phase-change rules (neuron.md:210-213, agentic-plan.md:122-124). **The `PHASE_CHECKLISTS` table MUST carry each phase's REFUSAL rules verbatim, not just its steps** — specifically: B's curiosity-convergence gate (record_outcome refuses until curiosity clear or signoff), C's spawn_planner rule, D's no-self-evaluate + train-specialist-in-turn (never reply "train it" to the planner — deadlock), E's PARTIAL-honesty + mark_outcome_met-before-succeeded refusal, drive's evidence + reviewer-pass gate (d30 dual-gate). A checklist that lists steps but drops refusals would let a resumed neuron close `succeeded` without `mark_outcome_met` — the exact failure phase-e prevents. Rule in the loop-and-heartbeat guide: "full phase guide on phase ENTRY only; after compact, the digest checklist is sufficient — reload the full guide only if you are entering a NEW phase."

### Files

New `.claude\commands\reground.md` (slash commands are available to all shells via the commands dir — `roles.py` gates MCP tool names only, no roles.py change needed; every role already has `get_guide`); `claude\.claude\settings.json` + hook script (`.claude\hooks\on-compact.*` — settings.json currently has ONLY the two PreToolUse hooks, guard-destructive + rtk, so SessionStart is a new section); `fsm\recipe_fsm.py` (PHASE_CHECKLISTS table, embedded in digest); `docs\guides\loop-and-heartbeat.md` (rule).

### Acceptance

- Force-compact a planner mid-step: the very next turn begins with /reground (hook-injected), receives digest + rewire, resumes work — zero user messages, zero guide fetches (transcript-verified).
- Token cost of a post-compact re-ground ≤ digest size (~5-10k), never the ~30k+ of guide reloads.

**Size: S.** Depends on W1 (digest), W2 (epoch/rewire). This is the client half of W2.

---

## W14 — Spawn resilience: claude.exe auto-update guard + environment doctor — NEW

**Problem (user, recurring):** Claude Code auto-update intermittently leaves `bin\claude.exe` as a ~500-byte stub with unfinished npm shims (`.claude*-TEMP`), killing every subsequent pool spawn (FileNotFoundError/WinError 2). Today the NEURON notices, diagnoses, and repairs it — burning Opus tokens on ops work, repeatedly. The repair is fully known and mechanical: copy the platform binary (~219MB) from the versions cache into bin and rename the TEMP shims; no pool restart needed.

### Design

**1. Pre-spawn health check + auto-repair in the POOL (code, not LLM).** Before every spawn, `pty_launcher` validates the resolved claude binary: size below threshold (e.g. <1MB) or `.claude*-TEMP` shims present alongside → run `repair_claude_install()` — the known procedure encoded as a pool function — then proceed. Repair failure → spawn refused with a `_precondition`-style error naming the fix ("claude.exe stub detected, auto-repair failed: <reason>. Run the doctor from the panel or `python -m edp_pool.doctor`"). The neuron NEVER fixes the environment — it relays the refusal to the user (or the panel notification does).

**2. Prevent, not just repair:** stamp `DISABLE_AUTOUPDATER=1` in `build_env` for every spawned shell so a mid-flight auto-update can't break running planners/workers. Updates then happen only when the user updates their own foreground installation (a deliberate act), and the pre-spawn check catches any residue.

**3. `doctor` entrypoint:** `python -m edp_pool.doctor` (also a panel button) — runs the binary check/repair, broker/pool health pings, Phoenix reachability, stale-lock sweep. One command replaces the neuron's ad-hoc ops archaeology.

**4. Zombie base shell:** with W11 (suspend/wind-down) + W12 (wind-down button), the long-lived neuron base shell no longer needs to be kept alive "on fumes" — closing it is safe (durable state + resume), and winding it down is one click instead of a prompt fight across N compacts.

### Files

`edp-pool\src\edp_pool\pty_launcher.py` (health check, DISABLE_AUTOUPDATER), new `edp-pool\src\edp_pool\doctor.py` (repair + checks), `edp-pool\src\edp_pool\service.py` (doctor endpoint for the panel).

### Acceptance

- Simulate the stub (truncate a copy of claude.exe in a test bin dir): spawn triggers auto-repair and succeeds; with repair sabotaged, spawn refuses with the self-healing message and the neuron performs NO Bash repair (transcript-verified).
- Spawned shells carry `DISABLE_AUTOUPDATER=1`.
- `doctor` completes all checks on a healthy stack in <10s.

**Size: S.** No dependencies — land in Phase 1.

---

## W15 — Memory untangle: one hierarchy, four fixes — NEW

**Problem (user + audit, all verified on disk):**

1. **Two divergent Claude auto-memory stores.** The pool's `build_env` never sets `CLAUDE_CONFIG_DIR`, so spawned shells inherit the default `~/.claude` — which has silently accumulated `~/.claude\projects\C--Projects-Learning-eda-base3-claude\memory\` with a **35,638-byte MEMORY.md + ~85 topic files** of harness lore (duplicate-planner-after-mcp-reconnect, branch-specialist-not-brief-instruction, …). The foreground `.claude-personal` store (4.5KB + 17 files) is a SECOND, disjoint store that also mixes harness mechanics (broker addressing, restart model, os.kill trap) with project facts. Neither sees the other; both steer behavior invisibly and inflate every session's context.
2. **spec-orchestrator has decayed from launch contract to incident ledger.** 80,667 bytes, v59, 63 entries (46 anti_patterns), mostly dated recipe scars ("the spring-time-service .gitignore-overwrite incident, 2026-05-22", "KILLED A WARM PLANNER, 2026-06-09 GeoGuessr"), ALL loaded into the neuron at every `/neuron` launch via `ensure_orchestrator` + `get_specialization`. It grows one save per recipe day and nothing curates it.
3. **No retrieval into recipe/plan memory.** `query_objects` is field-equality only with NO decision/assumption type (decisions collapse to `{id,title}`); `recall` is a substring scan over `.memory` only; `neuron_search` embeds ONLY the neuron registry. Recipe context is load-all-or-nothing — the retrieval half of the mess.
4. **No actor attribution on spec writes.** Spec worklogs record only `{ts, kind, version, entries}` — whether the neuron or a specialist shell performed an update is unrecoverable (and the neuron HAS been doing specialist updates itself — fixed structurally by W4's SPECIALIST_ONLY carve-out).

### Design

**1. The memory hierarchy (the untangle — one home per knowledge class, stated as a table in `architecture-vocabulary.md` and enforced where code can):**

| Knowledge class | Canonical home | Written by | Read path |
|---|---|---|---|
| Static environment + role contract | `CLAUDE.md` + `docs\guides\` | HUMAN only (hand-edited, versioned) | loaded per session (cwd) |
| Launch discipline (orchestrator/universal) | protected specs (below) | specialist shell, gated | distilled digest at launch |
| Durable stack craft | tech specs via W3 flowback | specialist shell (W4 carve-out) | overlaid compiled.md |
| Recipe-scoped context | recipe decisions/assumptions (W1 typed) | `record_context` | digest + `search_context` (below) |
| Ephemera (scheduling, acks, "user away") | `record_context(kind=note)` → WORKLOG | any role | worklog tail; NEVER in digest/epoch |
| Cross-recipe facts | scoped `.memory` (W4) | `record_context(kind=fact)` | `recall` |
| Claude auto-memory (MEMORY.md) | RESERVED for the human's foreground assistant | Claude Code itself | foreground only — never a harness surface |

**2. Kill the shadow store; migrate the lore.**

- Pool `build_env` pins `CLAUDE_CONFIG_DIR` to a dedicated **`.claude-pool`** config dir (new, checked into ops docs) so spawned shells stop reading/writing the user's default `~/.claude` store. Its `projects\...\memory\` starts EMPTY and stays curated (spawned shells are disposable; their durable learnings belong in specs/worklogs via the framework verbs, not auto-memory).
- **One-shot migration** (a checklist in the design, executed once during Phase 2): triage the ~85 `~/.claude` topic files + the harness-mechanics entries of `.claude-personal` → each becomes (a) obsolete once a v6 guard lands (most of them: autoupdate breakage → W14; monitor re-arm → W2/W7; addressing → whoami/rewire already hand it back) — delete with a pointer note; (b) a guide line (loop-and-heartbeat / environment-discovery); or (c) a protected-spec entry. Project-fact entries stay in the foreground store — that's what auto-memory is FOR.

**3. Protected specs + distillation + budget (spec-orchestrator/universal).**

- `Spec.protected: bool` (true for spec-orchestrator, spec-universal). Guard in the spec-write path: writes to a protected spec require `unlock=true` AND are attributed (below); W2's constraint machinery applies (`applies_to=["spec_doc"]` constraints can ban patterns in protected specs too).
- **One-time distillation** (human-gated, like a W3 batch accept): compress the 63 entries → a launch CONTRACT of generalized rules (~15-20 entries). Each incident scar either (a) generalizes to a rule, (b) is SUPERSEDED BY A v6 CODE GUARD (the majority: premature-hung-worker → W7 `last_output_ts`; killed-warm-planner → W2 duplicate-dispatch guard; plan_closed-marks-step-done → FSM fix; heartbeat discipline → W7 canonical prompt) — retired with a `superseded_by: "W<n> guard"` note; or (c) is recipe residue — dropped.
- **Growth budget:** protected specs cap at N entries (default 25); an add beyond the cap is refused with "consolidate first" (`_precondition`). At neuron launch, `ensure_orchestrator` loads the distilled contract — never an unbounded ledger again.

**4. `search_context` — retrieval into recipe/plan memory.** New tool `search_context(query, recipe_id=None, kinds=["decision","assumption","rejected_option","north_star"], top_k=8)`: embeds the query (existing `http_embed` client, same as neuron_search) and cosine-ranks over decision `title+subject+body` embeddings, computed at `record_context` write time and stored in a sidecar (`context\embeddings.jsonl`); lazy backfill for legacy decisions on first search; token-overlap fallback when the embed backend is down (same degrade path as neuron_search). `recall` becomes the ONE query verb an agent needs — and Phase 1 already did half of this: `FileMemory.recall` now fans out over the scoped trails (global + recipe + domain, file_memory.py:63-101, with legacy-flat fallback) and the Recall tool resolves caller lineage (_tools.py:2365-2373). W15 adds ONLY the `search_context` arm to that existing fan-out, results provenance-tagged. Registered per-role via W4 (workers/reviewers/planners get it — they can finally ASK the recipe instead of loading it).

**5. Actor attribution everywhere.** Spec worklog + recipe worklog writes gain `by: {role, handle}` resolved in code from `EDP_ROLE`/`EDP_HANDLE` (never LLM-supplied). Retroactively cheap, forensically priceless: the next "who mutated the orchestrator spec" question is a grep, not an archaeology session.

### Migration

Lazy throughout: `.claude-pool` starts fresh (no migration needed for spawned shells); the lore triage is one supervised session; protected-spec distillation is one human-gated batch; legacy decisions embed on first search.

### Files

`edp-pool\src\edp_pool\pty_launcher.py` (CLAUDE_CONFIG_DIR pin), `store\spec_store.py` (protected flag, cap, actor attribution), `tools\_tools.py` (SearchContext, recall fan-out, record_context kind=note→worklog routing, protected-write guard), `schemas\` (Spec.protected), `store\recipe_store.py`/`plan_store.py` (worklog `by`), `docs\guides\architecture-vocabulary.md` (hierarchy table), `.claude\commands\neuron.md`/`specialist.md`.

### Acceptance

- A fresh pool spawn reads/writes NO files under `~/.claude\projects\...` (ProcMon or before/after diff); its config dir is `.claude-pool`.
- `ensure_orchestrator` post-distillation loads ≤25 entries; an `add_spec_entry` to spec-orchestrator without `unlock=true` is refused; the 26th entry is refused with the consolidation message.
- `search_context("gemma serialization")` on the 0e7ca8 fixture returns the CONTENT-IS-RAW decisions in top-3 without loading recipe.json.
- `record_context(kind=note, body="user away till Monday")` lands in the worklog, never in the digest or epoch.
- Every new spec/worklog write carries `by: {role, handle}`.

**Size: M-L.** Depends on W4 (record_context, roles), W1 (typed decisions); the config-dir pin and actor attribution are day-one S items.

---

## THE FINDING: this design names capabilities the runtime does not provide

*Added 2026-07-11 (s29/a3b). It is ONE finding with five instances, not five findings — and the shape is what matters.*

Five times, DESIGN-v6 specified a mechanism **that could not be honoured on the system it describes.** Each was written in good faith, passed review as prose, and was discovered **only by someone trying to USE it.** None was caught by reading.

| # | The design said | The runtime says |
|---|---|---|
| 1 | The panel's gate-answer box mints an ack shaped like a recorded user answer — the neuron treats an anchored comment as **a structured user answer** | **No channel here certifies authorship.** `broker_send` takes `from_` as a parameter; the panel is loopback+no-auth and a shell can POST to it. The stamp certifies the PATH, never the author |
| 2 | The Shells view lists **`last_output_ts`** as a liveness column | It is **`None` for every monitor-mode shell** — i.e. for every shell we actually run |
| 3 | The panel shows a **Cost** view via `cost_report` | `cost_report` was **deliberately never built** (d77). The view had no data source from the day it was written |
| 4 | **W9 direction reviews**: the FSM instructs the neuron to `branch_reviewer(scope='direction')` | The neuron **does not own a reviewer** (d128), and the tool **crashed on this host anyway** (`harvest_artifact_paths` fed an absolute Windows path into pathlib's relative-only glob). It shipped green in s27 and **ran zero times in 147 actions** |
| 5 | **`neuron ≤ 45` registered tools** (§W6, targets) | **Unachievable BY CONSTRUCTION.** `_NEURON` is DERIVED — `registry − SPECIALIST_ONLY − RETIRED` = 87−4−8 = **75** — and **no test ever asserted a neuron ceiling.** The bound was never implemented, so nothing was relaxed to miss it |

**Instances 1-4 are DYNAMIC** (found by executing the thing) and **instance 5 is STATIC** — a design stating a bound *its own derivation rule forbids reaching*, guarded by no test. That the static one hid just as long as the dynamic ones is the point: **prose review does not catch this class, in either direction.**

**Why it is one finding.** Every instance is the same defect as the **accepts-a-directive-it-does-not-consume** family that runs through this project — a surface that ACCEPTS something it does not honour, and **stays silent about it**: `record_context` accepts a `constraint` and drops it; `MODEL_TIERS` declared `thinking`/`effort` that no production code read; the user's `effort=medium` directive sat inert for two days; `pool_spawn_worker` accepts `role="reviewer"` and spawns a shell that can never receive an action brief; a kind-filter drops the `alert` telling you about the kind-filter. **The framework has no general defence against this class.** Say that plainly rather than listing the bugs.

**The rule this buys, and it is the cheapest one in the document:** **a capability is not real until something has USED it.** A feature that is built, unit-tested green, and never exercised end-to-end is a *green suite guarding nothing* at workstream scale. Before you claim a capability exists, **drive it** — and if you cannot drive it, say so in the acceptance rather than inferring it from the tests.

---

## Implementation phases

Each phase is independently shippable and ends with a coordinated broker+pool restart where pool-side changes landed. Every workstream keeps its own acceptance criteria; the 0e7ca8 recipe is the legacy fixture throughout.

**Phase 1 — Seams & safety (no behavior change to running recipes):**
- W4 role-scoped tools + `record_context` + scoped facts (the seam everything else registers into)
- W10a generic model param — one-file client change in http_pool.py (edp-pool /v1/spawn already generic)
- W14 auto-update guard + doctor + `DISABLE_AUTOUPDATER=1`
- W6.1 rtk hook (independent; verify Windows binary)

**Phase 2 — Grounding & enforcement (the compaction/hallucination core):**
- W1 tiering-composed diet + north_star + digest
- W7 self-paced cadence (wait_hint, reconcile short-circuit, canonical prompt, **per-source rate limit** — NOT a debounce; see §W7.4, amended 2026-07-11)
- W8 assumption gate
- W2 epochs + constraint guards + monitor rewire hand-back
- W13 /reground skill + SessionStart(compact) hook + phase-checklist diet
- W15 memory untangle (config-dir pin + actor attribution early; lore triage + orchestrator distillation + search_context after W1/W4)

**Phase 3 — Flow (learning + human channels):**
- ENTRY PRECONDITIONS: W1's `get_recipe_digest` landed (W5/W9/W11 acceptance all ground through it — untestable before); Phoenix :6006 restored (W7/W12/W6.5 measure through it)
- W3 automated spec flowback + overlay
- W5 consult delivery (kinds on the recipe inbox) + convened consult shell
- W11 suspend/resume + session registry (step zero: pin claude_session on planner spawns)

**Phase 4 — Oversight, cost & control:**
- ~~W9 direction reviews (reviewer scope=direction — no new role)~~ **REMOVED (s29/a2).** The neuron-facing direction-review surface is gone: the neuron never branches a reviewer (it does not own one), and its direction integrity is **curiosity + signoff**. `branch_reviewer(scope='direction')` is refused at input validation so a stale caller fails LOUDLY. See the capability-gap finding below — this feature shipped green and **never once ran.**
- W10b MODEL_TIERS + stuck-escalation (**no `cost_report`** — withdrawn by d77)
- W12 control panel + token-free pause + inline plan review + gate notifications

**Phase 5 — Optimization & cleanup:**
- W6.4 tool consolidation (retire superseded verbs from toolsets)
- W6.5 guide condensation (canonical loop-and-heartbeat guide, measured)
- Archive the role-clarity meta-specs after W4 verification

Dependency notes: W2 needs W1 (constraints/digest), W7 (canonical prompt), W8 (pending-set in epoch). W13 needs W1+W2. W5/W9/W11 need W1's digest; W5+W9 need W10a. W12 needs W7/W8/W3/W10b/W11 pieces but its skeleton + pause endpoints can land in Phase 3 if wanted.

## External preconditions

1. ~~**rtk Windows binary** — verify availability/behavior before wiring the hook (W6.1); the hook must no-op cleanly if absent.~~ **RESOLVED (s30, 2026-07-12).** rtk **installs cleanly** on this host (official binary, SHA-256 verified; `rtk 0.43.0`), and it is **the reason rtk was inert before that: THE BINARY WAS SIMPLY ABSENT** (d4) — one reason, not two. The "hook never loaded for pool shells" half of that diagnosis is **FALSE** (d166, §W6.1c). The hook is live and safe; its payoff bound and its measured error-text cost are in the §W6 table.
2. **`EDP_TIER_WRITE=1` + coordinated restart** — pool-side changes (W10a, W14, W7 liveness, W5 inject, W11 registry, W12 endpoints) and env flips reach shells only after bouncing broker+pool (the only persistent processes) — once per phase, not per workstream.
3. **MODEL-TIERING-BENCHMARK.md entries** — required before any candidate tier (incl. `claude-sonnet-5` coding workers) is promoted to default (W10).

## Verification (cross-workstream)

All testable on the 0e7ca8 legacy fixture:

- < 10k-token digest re-ground (W1); recipe.json < 30KB after one save.
- Refused: banned-pattern completion, contradicting-doc spawn, done-action re-spawn, unacked-assumption dispatch (W2/W8).
- Stranded-learning E2E: emit → auto-propose → one accept → overlaid doc supersedes the banned mandate (W3).
- Heads-down hour of planner ticks collapses to no_change one-liners (W7, order-of-magnitude token drop via OTel).
- Seeded gratuitous-artifact fixture → off_track verdict → blocking constraint; `scope="spec"` reviews byte-identical to today (W9).
- Candidate tier never selected without the explicit flag (W10).
- Suspend → fresh-shell `/neuron resume` round-trip continues work with a forked planner session; manifest-less crash-resume recovers via reconcile alone (W11).
- Panel pause = zero token spend for the paused interval (OTel); gate notification → panel answer unblocks dispatch; 3 anchored comments arrive as one structured message (W12).
- Forced compact → hook-injected /reground → digest-only re-ground, no guide reloads (W13).
- Simulated claude.exe stub → pool auto-repair → spawn succeeds with no neuron Bash involvement (W14).
- Fresh spawn touches nothing under `~/.claude`; distilled orchestrator ≤25 entries at launch; `search_context` finds the CONTENT-IS-RAW decisions on 0e7ca8 without loading recipe.json; kind=note never reaches the digest (W15).
- Per-role activation token cost measured before/after guide condensation; smoke recipe passes (W6.5).
