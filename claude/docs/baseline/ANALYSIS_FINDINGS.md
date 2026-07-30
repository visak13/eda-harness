# Analysis Findings — Old System (evolving-deep-agent)

**Purpose:** Catalog *what we learned* from auditing the old repo, plans, recipes, and microservices. Source of truth for the rewrite.

**Discipline:**
- One finding per section.
- Each finding states: **What** (the observation), **Where** (file/plan/recipe path or commit), **Why-it-failed** / **Implication** (what the rewrite must do differently).
- No speculation. If we don't know, write "UNKNOWN — needs deeper read."

---

# Phase 1 — Wide Inventory

## F1 — Microservice landscape (as of 2026-05-15)

### F1.a — `evolving-deep-agent/` (the monorepo, to be retired)

This monorepo currently bundles two services + plugins + a guides folder. **All future microservices live as sibling repos in `eda-base/`; this monorepo is reference-only.**

| Service | Path | Purpose (from module docstrings) | Last touched | Verdict |
|---|---|---|---|---|
| **mcp-service** | `evolving-deep-agent/mcp-service/src/mcp_service/` | The fat MCP tool host. ~18 top-level modules covering broker, pool, plan/recipe schema+IO, memory client, overlay registry, neurons, aggregator, guides, judge_loop. | 2026-05-15 | **SPLIT.** Each subsystem becomes its own microservice (see F1.c). |
| **agent-service** | `evolving-deep-agent/agent-service/src/agent_service/` | FastAPI agent (`POST /query`). In-memory chat history. Originally Phase 1 of the roadmap. | 2026-05-12 | **DROP for now.** Not part of the neuron/loop core that the rewrite targets. Re-introduce later if needed. |

### F1.b — `mcp-service` internal modules (will split into dedicated services)

Top-level `mcp-service/src/mcp_service/`:
- `main.py` — entry, transport switch (stdio/SSE). KEEP as harness boilerplate.
- `server.py` — `FastMCP` server, tool registration. KEEP shape.
- `broker_server.py` — **edp-broker / Plan W / ADR-016** standalone FastAPI message broker. **→ becomes its own repo `eda-base/edp-broker/`.** User explicitly wants "single reliable event broker that only transmits events."
- `pool_server.py` — **edp-pool / ADR-022** spawn-on-demand subagent orchestrator. **→ own repo `eda-base/edp-pool/`.** User explicitly says "the pool is a working server… use this pattern."
- `graphiti_server.py` — wraps Graphiti + FalkorDB over HTTP so mcp-service doesn't pay the graphiti_core import cost (>1 s). **→ already conceptually separate; lives near edp-memory (see F1.c).**
- `memory.py` — HTTP client TO graphiti_server. Used by `recall/remember/forget/purge`. KEEP shape (thin client).
- `recipe.py` + `recipe_schema.py` — recipe v2 IO + pydantic models. **CORE behavior** to preserve; recipe is the cross-session state vehicle the user said *worked partially*.
- `plan_schema.py` — pydantic models for v2 hierarchical plan. **CORE behavior** to preserve; plan json was the working context-saver.
- `worklog.py` — append-only per-plan trail. **CORE.**
- `active_plans.py` — session→plan/action lookup (for pre-tool hook). LIKELY DROP — hooks crept in, user wants them removed.
- `aggregator.py` — meta-cognition fan-out loop (Plan 2026-05-10 Phase 2). **REPLACE with OCAK neuron** per user instruction ("simplify the aggregator neuron to take all tasks up in a single shell").
- `guides.py` — on-demand `docs/guides/*.md` loader (ADR-025). KEEP shape.
- `judge_loop.py` — agentic-plan Step 7.5 judge helpers. KEEP behaviorally, fold into agentic-plan.
- `neuron_verdict.py` — brain message schemas (Plan 2026-05-04 / ADR-019, then superseded by ADR-022). LIKELY DROP — brain peer pattern was retired.
- `overlay_registry.py` — field-level invariant tracking. KEEP — used by hardened multi-overlay deploys.
- `browser_session.py` — headed-browser state. SEPARATE concern; could remain a plugin.

`mcp-service/src/mcp_service/neurons/` (the cluster substrate):
- `registry.py` — SQLite-backed neuron routing table. KEEP.
- `crud.py` — neuron CRUD MCP tools. KEEP.
- `embeddings.py` + `kg_index.py` + `search.py` — local vector router (Ollama nomic-embed-text). KEEP.
- `cron_base.py` — cron-neuron base + daemon. KEEP per ADR-024-as-pruned (only plan-archiver survives).
- `plan_archiver.py` — only surviving cron-neuron. KEEP.
- `pattern_observer.py`, `goal_keeper.py`, `critic.py` — session-neuron helpers (ADR-024). KEEP behaviorally but rebuild against the simplified neuron architecture.
- `drift_response.py` — converts drift-check verdict to recipe mutation. KEEP.

`mcp-service/plugins/` — registered MCP tools. ~25 plugins. Most are thin wrappers over modules above. **Triage in F2** when we inventory slash commands (they invoke these).

### F1.c — Existing sibling repos under `C:\Projects\Learning\`

| Repo | Has src? | Purpose | Last touched | Verdict |
|---|---|---|---|---|
| `edp-debug` | No (just session-debug `.md` files + `hooks/`) | A scratchpad of session debugging notes 2026-04-22 .. 2026-05-13 (28 files). Hook scripts under `hooks/`. | 2026-05-13 | **REFERENCE.** Not a service; valuable archaeology for failure stories. The session-debug files are gold for the deep-read phase. |
| `edp-errors` | No (empty directory) | UNKNOWN — never populated. | 2026-05-08 | **DROP.** Was a placeholder. |
| `edp-memory` | No (just sub-dirs `falkordb/`, `ollama/`, `logs/`, `ml-capabilities/`, `pattern-recognition/`) | Orchestration / docker-compose container for the running stack (falkordb + ollama + ml-cap + pattern-recognition). | 2026-05-05 | **KEEP as the deployment overlay** for the running stack. Possibly rename to `eda-base/deploy/` or `eda-base/edp-stack/`. |
| `edp-ml-capabilities` | Yes (src + tests + Dockerfile + docker-compose) | "ML capabilities for the evolving-deep-agent — the nervous system layer." Outcome-prediction service. | 2026-04-26 | **KEEP, on hold.** Behavior to preserve (`predict_outcome` MCP tool calls it). Re-evaluate after core rewrite. |
| `edp-pattern-recognition` | Yes (src + tests) | "Pattern-recognition service — sequence + structure miner over plan history (Phase 6 of plan 2026-05-04)." | 2026-05-05 | **KEEP, on hold.** |
| `edp-problem-solving` | No (datasets, domains, pipelines, shared, CLAUDE.md, TAXONOMY.md) | "A multi-domain knowledge repository for problem-solving artefacts: patterns, prompts, evaluators, benchmark traces." | 2026-05-02 | **REFERENCE.** Data repo, not a service. KEEP. |
| `edp-proxy` | Yes (src + tests + README + .env.example) | OpenAI `/v1/chat/completions` ↔ Ollama `/api/chat` translation + reasoning-disable injection. | 2026-05-09 | **KEEP, do not touch.** User explicitly named it: "a proxy was developed for reliably communicating between the knowledge graph and ollama. should be used as it adds fault tolerance." |

### F1.d — Inferred new microservice layout (proposal, NOT YET BUILT)

```
eda-base/
├── claude/                  ← this repo (mcp tools, slash commands, plans, recipes, state, docs)
├── edp-broker/              ← extracted from mcp-service/broker_server.py
├── edp-pool/                ← extracted from mcp-service/pool_server.py
├── edp-memory-svc/          ← graphiti_server.py + the in-process memory client; uses falkordb+ollama under edp-proxy
├── edp-proxy/               ← (existing, used as-is) OpenAI↔Ollama proxy
├── edp-ml-capabilities/     ← (existing, on hold)
├── edp-pattern-recognition/ ← (existing, on hold)
└── edp-stack/               ← docker-compose for falkordb+ollama+proxy+ml+pattern (renamed edp-memory)
```

The claude repo (`eda-base/claude/`) holds: `mcp_tools/`, `.claude/commands/`, `.plans/`, `.recipes/`, `.memory/`, `docs/`. The MCP tools become thin HTTP/gRPC clients to the dedicated microservices — no embedded business logic.

**Confidence:** medium. The split-shape will get refined after F4 deep-read shows which seams actually carry traffic.

---

## F2 — Slash command inventory (54 commands in `.claude/commands/`)

Bucketed by role. **Verdict column** is a *proposal* for the rewrite — each one is open to discussion before any code lands.

### F2.a — Neuron core (6 commands)
| Command | Purpose | Last touched | Verdict |
|---|---|---|---|
| `neuron.md` | Entry dispatcher for `/neuron <goal>`; recipe owner; routes through phased cluster. | 2026-05-13 | **REBUILD.** Simplify per user instruction (Phase A=Monitor+loop arm; B=OCAK; C=loop-scheduled drift/pattern; D=drive plan; E=repeat decision; F=close). |
| `neuron-phase-a.md` | Init: register session, set up monitors. | 2026-05-14 | **REBUILD.** Per user: arm Monitor + set 30-min `/loop`. |
| `neuron-phase-b.md` | Comprehension via aggregator + leaves. | 2026-05-14 | **REBUILD.** Replace branched aggregator with single-shell OCAK neuron. |
| `neuron-phase-c.md` | Spawn the planner (after recipe is built). | 2026-05-13 | **REBUILD.** Re-purpose to "schedule drift/pattern checks via /loop". |
| `neuron-phase-d.md` | Observe plan execution. | 2026-05-14 | **KEEP** behaviorally; map to new Phase D (drive plan). |
| `neuron-phase-e.md` | Evaluate goal completion → next move. | 2026-05-14 | **KEEP** behaviorally; split into E (decide repeat) + F (close). |

### F2.b — Agentic-plan core + shapes (12 commands)
User explicitly said: *"agentic-plan was working end-to-end with an abstract factory of plans … this structure needs to serve as baseline."*

| Command | Purpose | Verdict |
|---|---|---|
| `agentic-plan.md` | Phase A (clarify → research → plan → sign-off). | **KEEP — gold-standard baseline.** |
| `agentic-plan-execute.md` | Phase B (DAG-aware wave dispatch). | **KEEP.** |
| `agentic-plan-executor.md` | Single-action executor subagent. | **KEEP.** |
| `generate-plan.md` | Implementation-level actions when shape is known. | **KEEP.** |
| `agentic-plan-creative-production.md` | Shape pipeline. | **KEEP.** |
| `agentic-plan-diagnose-fix-verify.md` | Shape. | **KEEP.** |
| `agentic-plan-gather-validate-submit.md` | Shape. | **KEEP.** |
| `agentic-plan-linear-build.md` | Shape. | **KEEP.** |
| `agentic-plan-modular-build.md` | Shape. | **KEEP.** |
| `agentic-plan-poc-iterate-build.md` | Shape. | **KEEP.** |
| `agentic-plan-research-synthesize.md` | Shape. | **KEEP.** |
| `coding-api-plan.md` / `coding-data-plan.md` | Domain templates fed by `generate-plan` G3. | **KEEP** — part of the abstract-factory pattern. |

### F2.c — OCAK candidates (aggregator + 11 leaves — to COLLAPSE)
User: *"simplify the aggregator neuron to take all tasks up in a single shell instead of branching workers and call it ocak neuron."*

| Command | Role | Verdict |
|---|---|---|
| `aggregator.md` | Orchestrates parallel leaf neurons; absorbs verdicts; mutates `recipe.decision_branches`. | **COLLAPSE INTO OCAK.** |
| `feasibility-checker.md` | Can this be done at all? | → OCAK step |
| `role-clarity-checker.md` | Is user's role clear? | → OCAK step |
| `actor-identifier.md` | Extract actors. | → OCAK step |
| `actor-clarity-checker.md` | Are actors ambiguous? | → OCAK step |
| `concern-validator.md` | Ethical / sensitive / irreversible? | → OCAK step |
| `new-tech-detector.md` | Unknown tech? | → OCAK step |
| `goal-setter.md` | Make goal verifiable. | → OCAK step |
| `estimation-checker.md` | Duration estimate; flag splits. | → OCAK step |
| `reply-comprehension.md` | Drift-check leaf — reply quality. | → OCAK step (or scheduled neuron, see F2.f) |
| `evaluation-comprehension.md` | Drift-check leaf — success criteria. | → OCAK step (or scheduled neuron) |
| `suggestion-comprehension.md` | Drift-check leaf — suggestion alignment. | → OCAK step (or scheduled neuron) |

The three `*-comprehension.md` leaves are currently used by `/loop` drift checks, not comprehension-gate; they could either fold into OCAK or remain as small scheduled-neuron commands. **Open question for user.**

### F2.d — Session-neurons (3 commands)
| Command | Purpose | Verdict |
|---|---|---|
| `critic.md` | Adversarial reviewer; wakes on N=3 retry / pre-sign-off. | **KEEP behaviorally**, rebuild as event-driven scheduled neuron. |
| `goal-keeper.md` | Real-goal drift detector. | **KEEP behaviorally.** |
| `pattern-observer.md` | Failure-pattern aggregator. | **KEEP behaviorally.** |

### F2.e — Worker + review (2)
| Command | Verdict |
|---|---|
| `worker.md` — spawn-on-demand subagent per action. | **KEEP — proven pattern, user explicitly endorsed.** |
| `review-plan.md` — post-session HITL review, M3/M4/M5 metrics, pattern storage. | **KEEP.** |

### F2.f — Memory / KG ops (5)
| Command | Verdict |
|---|---|
| `remember.md`, `recall.md`, `forget.md`, `forget-my-data.md`, `train.md` | **KEEP** — these are the KG surface for the user. |
| `pii.md` — updates PII guard for `remember()`. | **DROP** per user: *"hooks like pii were supposed to be a poc but they crept into the system by adding hindrance."* |

### F2.g — Drop / superseded (5)
| Command | Reason |
|---|---|
| `brain.md` | ADR-019 retired; superseded by ADR-022 neuron-as-main-thread. |
| `subagent-plan.md` | Self-described "collapsed in Plan A.5"; pointer-only. |
| `test-crud-demo-2026-05-12.md` | Demo file for CRUD smoke test. Cosmetic. |
| `schedule.md` | Renamed to `/myschedule`; placeholder. |
| `pii.md` | (see F2.f) |

### F2.h — Utilities (kept, peripheral) (8)
`help.md`, `guide.md`, `add-command.md`, `add-skill.md`, `myschedule.md`, `sync-docs.md`, `export-debug.md`, `checklist.md`, `git-pull.md`, `git-push.md`, `git-stash.md`.
**KEEP** — these are the developer-ergonomics layer; orthogonal to the rewrite. Migrate as-is.

### F2.i — Summary counts
- KEEP unchanged: ~28 commands (agentic-plan core+shapes 11, worker, review-plan, memory 5, utilities 11)
- KEEP behaviorally / rebuild: 9 commands (6 neuron-phase + 3 session-neurons)
- COLLAPSE: 12 commands → 1 OCAK
- DROP: 5 commands

Net: **~54 → ~38** commands.

**Open questions for user before any deletion:**
1. Drop `pii.md` — confirm? (User signal: yes, but want explicit OK.)
2. The three `*-comprehension.md` drift-check leaves — fold into OCAK, or keep as small standalone neurons that the `/loop` calls?
3. `coding-api-plan` / `coding-data-plan` — keep as-is, or expand into a proper abstract factory of domain templates (software/movie/robotic per user's example)?


## F3 — Recipe & plan inventory

### F3.a — Recipes (5 total at `.recipes/<id>/recipe.json`)

| Recipe id | Created | `final_outcome` | `plan_refs` | Goal (truncated) |
|---|---|---|---|---|
| `add-headed-browser-screenshot-skills-2026-05-13` | 2026-05-12 | **succeeded** | 0* | Add MCP tooling for headed Chromium + screenshots |
| `aiml-poc-career-2026-05-14` | 2026-05-14 | empty | 0 | POC for AI/ML career at `C:\Projects\Learning\poc` |
| `stateless-auth-novel-2026-05-13` | 2026-05-13 | empty | 0 | Develop new auth in `C:\Projects\Learning\oauth` |
| `stateless-auth-novel-oauth` | 2026-05-13 | empty | 0 | Stateless auth design+implement |
| `stateless-auth-oauth-2026-05-13` | 2026-05-13 | empty | 0 | Stateless auth |

\* The headed-browser recipe shows `plan_refs=0` on the surface but its worklog confirms a v2→v3→v4→v5 lifecycle with `plans=[…in_progress→done…]` embedded; the PowerShell read truncated nested fields.

**Observation:** 1 of 5 recipes ran to a stamped `final_outcome`. 3 of the 5 are the *same goal restated three times in 24 hours* (stateless auth). This is the user's pain visible in the data: *the system kept restarting the same goal because cross-session continuity failed.*

### F3.b — Plans

| Bucket | Path | Count | Notes |
|---|---|---|---|
| Top-level active plans | `.plans/<id>.json` (+ accompanying `.plans/<id>/worklog.jsonl` for v2) | **41** | Body lives in the flat JSON; worklog + locks live in the same-named directory. |
| Archived | `.plans/.archive/YYYY-MM/<id>.json` | 6 | Moved by `plan-archiver` cron-neuron after 7d. Includes the big load-bearing plans (`pool-brain-event-driven` 187 kB, `neuron-architecture-replatform` 75 kB, `foundation-protocol-evolution` 76 kB). |
| Deferred | `.plans/deferred/<id>.json` | 4 | `multi-shell-ipc`, `synthetic-paraphrase-generator`, `plan-b-predict-risks`, `plan-a5-phase5-ml-rebuild`. Conscious "not now" decisions. |
| Pre-DAG backups | `.plans/.bak-pre-dag/<id>.json` | 13 | Pre-ADR-013 v1 schema. Reference only. |
| Per-session metadata | `.plans/.sessions/<uuid>/{init.json,result.json}` | 50+ session uuids | Subagent session tracking (ADR-015 / Plan A.7). High volume; mostly debug. |

### F3.c — Action-status distribution (across the 41 active top-level plans)

| Status | Count | % |
|---|---|---|
| `done` | **319** | 74% |
| `pending` | **93** | 22% |
| `skipped` | 22 | 5% |
| `in_progress` | 5 | 1% |
| `failed` | 3 | <1% |

### F3.d — The headline failure-mode finding

**Plans don't fail by `failed` status — they fail by *abandonment*.**

- Only **3 actions across 41 plans** are marked `failed`.
- **93 actions are stuck `pending`** — work that was queued but the driving session never returned to it.
- **5 actions are `in_progress`** — even more concerning: locked mid-work, never closed.
- Combined: ~25% of all queued work was orphaned, not errored.

This *directly* matches the user's diagnosis:
- "The system kept developing across multiple claude sessions with compacted sessions"
- "The system kept working on long plans but failed to retrieve context across the plans"
- The recipes survey corroborates: 3 of 5 recipes are *the same goal restarted three times in 24h*.

**Implication for the rewrite:**
- Resume-from-pending is more important than retry-on-failed.
- A new session entering `/neuron <goal>` MUST first recall: "is there an open recipe for a substantively-similar goal? Is there a plan with pending/in_progress actions? Should I continue or start fresh?"
- The recipe → plan_refs link must be checked for orphan recovery, not just appended-to.
- `in_progress` actions left over from a dead session need a sweeper (resurrection or explicit cancel) — the current `idle-worker-reaper` was deleted (per CLAUDE.md), so this gap currently exists.

### F3.e — Candidates for F4 deep-read

Three candidates, picked for high signal:
1. **`stateless-auth-*` (3 recipes, 24h)** — perfect case of cross-session re-start failure. Read all three recipes + any linked plan worklogs. Question: what specifically failed in session 1 such that session 2 couldn't pick up?
2. **`.plans/.archive/2026-05-04-pool-brain-event-driven.json` (187 kB)** — largest single plan in the archive. Likely the source of the deepest protocol complexity. Should illuminate "too many protocols for the LLM to follow."
3. **`.plans/.archive/2026-05-07-neuron-architecture-replatform.json` (75 kB)** — the *meta* plan: a plan to rebuild the neuron itself. If this plan succeeded mechanically but the *system* still failed, that's diagnostic of the gap between "plan-driven" and "actually-working."


## F4 — Deep-read of failure cases

### F4.a — Stateless-auth trilogy: comprehension stalls on `needs_research` branches

Read all three recipes + their worklog dirs.

| # | Recipe id | Created | Version | Decision branches | Plans | Final outcome | Worklog file? |
|---|---|---|---|---|---|---|---|
| 1 | `stateless-auth-novel-oauth` | 03:05 UTC | 1 | **[]** (none) | 0 | null | **absent** |
| 2 | `stateless-auth-oauth-2026-05-13` | 04:50 UTC | 2 | 6 (4 resolved, **2 `needs_research`**) | 0 | null | **absent** |
| 3 | `stateless-auth-novel-2026-05-13` | 07:33 UTC | 7 | 6 (all resolved, incl. user-provided clarification of b4) | **1 plan, 9/9 done, 45 tests pass** | null (but plan succeeded) | present |

**Story:** the user typed the goal three times within ~4.5 hours. Attempt 1 created an empty recipe shell and died before OCAK started. Attempt 2 ran OCAK partially — resolved 4 of 6 branches — but `b4` ("what does 'not existing methods' mean — a standard not yet wired in, or a novel custom protocol?") and `b6` ("which specific method to target?") were marked `needs_research` with `verdict: null` and **the system never surfaced these questions back to the user**. The recipe just sat at v2 with no worklog ever appended. The user, confused, re-typed the goal a third time, this time *pre-loading the b4 clarification in their phrasing*. Recipe 3 then ran OCAK to closure and the plan succeeded.

**Failure mode:** **"needs_research silence"** — decision branches needing user input have no notification → user. The recipe schema has the slot (`status: needs_research`), but the *protocol that surfaces them* either never fired or fired silently. The user's workaround was to start over with a clearer prompt.

**Implication for rewrite:**
- Any branch in `needs_research` status MUST produce an immediate user-facing notification, AND the recipe must not be advanceable until the branch resolves (or the user explicitly waives it).
- Recipes that sit at v1/v2 with no plans linked and no worklog activity after N minutes are abandonment-candidates — the new system should detect and surface, "Recipe X has been idle since 03:05, do you want to resume or close it?"
- Restarting a goal under a new recipe id loses lineage. Continuity should be by *goal-similarity match*, not by recipe id.

### F4.b — `pool-brain-event-driven` (52 actions): "completion" via mid-plan supersession

Read `.plans/.archive/.../2026-05-04-pool-brain-event-driven.json`. 187 kB. Linear-build shape. 7-part option:
> Pool daemon → /worker → Brain → Pivot detection → KG error awareness → Risk tiers → Cleanup

- 29 actions `done`, **23 actions `skipped`**. `completed_at` is stamped.
- Sampled action #5 (HITL acceptance gate). `status=skipped`, `result` field reads:
  > *"Superseded by 2026-05-07-neuron-architecture-replatform plan. Phase 1 HITL acceptance gate reframed: the persistent pool model that this gate validated is being replaced with on-demand spawn-and-close."*

This is **not** a successful plan with skipped optional work. It is **a plan that got mid-flight reframed** when the architecture pivoted from "persistent worker pool" (ADR-018) to "spawn-on-demand" (ADR-022). The remaining 23 actions were marked skipped-as-superseded and the plan was closed.

**Failure mode:** **the plan layer can't distinguish "succeeded" from "abandoned-via-pivot."** The archiver moves anything `completed_at != null` to `.archive/` after 7 days. Future cross-plan lookups (recall, capability_index) see this as a finished plan. The ML capabilities service trains on it.

**Implication for rewrite:**
- A plan needs a *terminal status* separate from action-status rollup: `succeeded` / `superseded` / `aborted` / `partial`. The current schema rolls action statuses into an implicit "done if no in-progress" — that's lossy.
- Mid-plan pivots should fork a successor plan with an explicit `superseded_by` link rather than re-using the same plan with mass-skipped tails.

### F4.c — `neuron-architecture-replatform` (20 actions): 20/20 done, system still failed

Read `.plans/.archive/.../2026-05-07-neuron-architecture-replatform.json`. 75 kB. Linear-build, "Sequenced 9-phase replatform with schema-first ordering."

- All 20 actions `done`. 0 skipped. Clean completion.
- The plan landed ADR-022 (neuron-as-main-thread, spawn-on-demand pool, plan schema v2 string IDs + DAG + executor_mode), the renamed `/brain → /neuron`, the new `/review-plan`.
- **And yet** — the user's testimony 8 days later (2026-05-15) is that the resulting system *failed*. The very things this plan shipped are the things being torn down in the rewrite.

**Failure mode:** **task-level success is not system-level success.** Every checkbox got ticked; the *thing built* didn't actually work end-to-end for the user. The plan had no behavioural acceptance test ("can the user run /neuron on a fresh goal and complete it across two compacted sessions?") — only artefact-existence tests ("file exists", "schema validates", "tests pass").

**Implication for rewrite:**
- Every plan must terminate with a **behavioural smoke test the user runs in-the-shell** — not a metric, not a test suite — a literal "do the thing the plan was for." If that smoke fails, the plan is `partial`, not `done`, regardless of action-status counts.
- The plan→acceptance_signal mapping is too granular (per-action) and not granular enough (no plan-level user-walkthrough gate). Add a plan-final-acceptance step.

### F4.d — `foundation-protocol-evolution` (24 actions): 8 done / 16 skipped, also superseded

Same archive. Plan goal was a 4-phase evolution (Foundation → Planning → Protocol → Cleanup, HITL-gated between phases). Only the Foundation phase (logging + hook JSONL + worklog reliability + state guard) actually ran. The other three phases were superseded by `pool-brain-event-driven` (which itself was then superseded by `neuron-architecture-replatform`).

This confirms F4.b as a **chronic pattern**, not a one-off:
- `foundation-protocol-evolution` (2026-05-03, 16 skipped) → superseded by
- `pool-brain-event-driven` (2026-05-04, 23 skipped) → superseded by
- `neuron-architecture-replatform` (2026-05-07, 20 done but system failed) → superseded by
- the current rewrite (2026-05-15).

**Three architectural pivots in 12 days.** Each pivot abandoned the majority of the prior plan's scope. This is the user's "the system kept making assumptions" in concrete form: the system kept adopting ambitious multi-phase plans, executing the first phase, then pivoting before the rest landed.

**Implication for rewrite:**
- Long multi-phase plans are a known anti-pattern. The new system should bias toward *one provable behavior at a time*, prove it works, then plan the next thing.
- Cross-plan supersession chains need explicit modeling, not implicit skip-flags.

### F4.e — LLM tool-call leakage into JSON evidence fields

While reading action #5 of `pool-brain-event-driven`, found `</evidence></invoke>` XML tags embedded inside the `result` string. The LLM was emitting tool-call structure into a free-text field, and the schema validator passed it because the field is a `str`.

**Failure mode:** the schema is too permissive at field-value level. Pydantic typed `str` but didn't catch malformed payloads.

**Implication for rewrite:**
- Free-text fields that carry agent output should be sanitized (strip `<tool_use>`, `</invoke>`, `</evidence>`, etc.) on write, not on read.
- This is a small, high-value hygiene rule for the new schema validators.

### F4.f — Aggregate failure-mode taxonomy

Synthesizing F3.d + F4.a–F4.e:

| # | Mode | Evidence | Frequency |
|---|---|---|---|
| 1 | **Abandonment-by-orphan-pending** | 93 pending + 5 in_progress across 41 plans | Chronic. Quarter of all queued work. |
| 2 | **Comprehension stalls on `needs_research`** | 2 of 3 stateless-auth recipes, no surfacing to user | Recurring; data thin (only 5 recipes total) but pattern matches user testimony |
| 3 | **Mid-plan architectural pivot ("skipped-as-superseded")** | 23 + 16 skipped actions in pool-brain & foundation | Chronic in big plans |
| 4 | **Task-level success masking system-level failure** | neuron-replatform 20/20 done but system failed | At least once on a load-bearing plan |
| 5 | **No cross-plan continuity** | Same goal re-typed 3× in 24h with no resume mechanism | Likely chronic; user testimony + data |
| 6 | **Schema-too-permissive (LLM tag bleed)** | `</invoke>` tags in evidence field | Hygiene, low-severity but present |

These six are the **load-bearing failure modes**. The rewrite design has to address each one explicitly or it will reproduce them.

---

# Methodology Notes

- Every microservice in F1.c was checked on disk (existence + top-level layout). Module purposes pulled from docstrings, not memory.
- `edp-errors` is listed as DROP based on observing an empty directory; will confirm with user before any deletion.
- `agent-service` DROP is **for the rewrite scope**, not for the existing repo — the existing FastAPI agent stays where it is; we just don't carry it into `eda-base/`.
