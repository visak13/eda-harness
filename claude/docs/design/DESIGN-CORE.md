# DESIGN-CORE — claude repo + edp-broker + edp-pool

**Status:** DRAFT for user review. No code lands until you sign off.
**Inputs:** `docs/baseline/USER_PROMPT_2026-05-15.md`, `docs/baseline/ANALYSIS_FINDINGS.md` §F1–F4.
**Scope of this doc:** the *orchestration core* — the user's `/neuron` shell, the message broker, the subagent pool, and the neuron Phase A–F protocol.
**Out of scope:** memory/KG (see `DESIGN-DATA.md`), ML capabilities + pattern recognition (see `DESIGN-ML.md`).

---

## 1. Microservice boundaries (core trio)

```
┌─────────────────────────────────────────────────────────────┐
│  eda-base/claude/   (this repo)                             │
│   • .claude/commands/  ← slash command bodies               │
│   • mcp_tools/         ← thin MCP wrappers (one per tool)   │
│   • .plans/  .recipes/  .memory/  ← state on disk           │
│   • docs/baseline/  docs/design/  docs/guides/              │
│                                                             │
│   The MCP server in this repo carries NO business logic.    │
│   Every tool delegates to a microservice over HTTP.         │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTP
       ┌─────────────┼──────────────┐
       ▼             ▼              ▼
┌─────────────┐ ┌─────────────┐  (→ DESIGN-DATA.md, DESIGN-ML.md)
│ edp-broker  │ │  edp-pool   │
│             │ │             │
│ Event bus.  │ │ Spawns      │
│ Append-only │ │ Claude Code │
│ JSONL per   │ │ shells on   │
│ recipient.  │ │ demand. One │
│ /events SSE │ │ task per    │
│ stream for  │ │ shell.      │
│ subscribers.│ │             │
│ NO business │ │ Posts spawn │
│ logic.      │ │ events to   │
│             │ │ broker.     │
└─────────────┘ └─────────────┘
```

### 1.1 `eda-base/claude/` — the orchestration repo
- Holds slash command bodies, MCP tool wrappers, state directories (`.plans/`, `.recipes/`, `.memory/`), and docs.
- The MCP server is a **thin client** to the broker, pool, and other microservices. No state logic embedded.
- Recipe JSON, plan JSON, worklog JSONL — all live here on the user's disk. They are the durable cross-session state.

### 1.2 `eda-base/edp-broker/` — event broker
**Purpose** (per user instruction): "single event broker that is reliable and only transmits events." The broker has *no business logic.* It writes events to per-recipient JSONL inboxes and exposes:
- `POST /publish` — append an event to recipient inbox(es).
- `GET /events?since_ts=…&recipient=…` — SSE/long-poll for new events (replays from `since_ts` for reconnection durability).
- `GET /inbox/<recipient>?since_ts=…` — JSON pull for non-SSE consumers.

**What the broker is NOT:**
- Not a task queue. Tasks come via `pool /tasks`.
- Not a planner. No knowledge of recipes/plans.
- Not a session registry. (Sessions are tracked by the pool.)

**Rewrite scope:** fresh repo; port the working FastAPI shape from old `mcp-service/broker_server.py`. Single SSE event stream is the headline change (Plan W / ADR-021).

### 1.3 `eda-base/edp-pool/` — spawn-on-demand subagent pool
**Purpose** (per user): "the pool is a working server that spawns claude shells. use this pattern for activation + work assignment."
- `POST /spawn` — spawn a Claude Code shell with a role (`agentic-plan` / `worker` / `ocak` / `critic` / `pattern-observer` / `goal-keeper`) and a task body. Pool generates `session_id`, writes init, launches `edp-shell` wrapper (PTY-owned).
- `POST /tasks/<session_id>` — send a task body to a running session via its broker inbox.
- `GET /sessions` — enumerate active sessions (no business roll-up; observability only).
- `POST /sleep/<session_id>` / `POST /wake/<session_id>` — for session-neurons that resume via `claude --resume`.

**What the pool is NOT:**
- Not the broker (no event stream of its own; pool *publishes to* the broker).
- Not a planner.
- Not a lock manager — locks live with plans, in `claude/.plans/<id>/.locks/`.

**Rewrite scope:** fresh repo; port the working ideas from old `mcp-service/pool_server.py`. Drop the persistent worker fleet, keep spawn-on-demand + init-ack handshake (ADR-022). **Drop the plan-scoped executor lock defect** (see memory `project_edp_lock_scope_defect`); locks should be action-scoped (`.plans/<plan>/.locks/<action>.lock` per ADR-023).

---

## 2. Neuron Phase A–F sketch (CONTRACTS-ONLY; TBDs flagged)

The neuron runs in the user's main shell. It is the **recipe owner**. It never edits code, runs tests, or greps the user's domain — those are planner/worker jobs.

### Phase A — Init (≤30 s)
**Goal:** establish operating context for this session.

| Step | Action | Tool | Notes |
|---|---|---|---|
| A1 | Read GUIDELINES + PROGRESS | `Read` | Survival on session restart. |
| A2 | Register self with broker | `broker.publish(kind=session_register)` | Pre-condition for cluster comms. |
| A3 | Recall: open recipes? | `recall("open recipes for goal-similar to <user goal>")` | **F4.f mode 5 remedy** — cross-session continuity check. If a substantively-similar recipe exists with `final_outcome=null`, surface it: "Resume or start fresh?" |
| A4 | Arm Monitor on broker inbox + plan worklogs | (Monitor tool) | Event-driven idle, not polling. |
| A5 | Arm `/loop` 30-min reminder | `/loop` | "Re-read guidelines, re-surface status." Already armed in the rewrite kickoff session. |

**TBD-A1:** Should `A3` also run on **partial-match** goals (e.g. user types "stateless auth" while a 2-day-old recipe exists for "design new auth method")? Default: yes, with similarity threshold; user confirms.

### Phase B — Comprehension via OCAK (single shell)
**Goal:** turn the goal into a fully-resolved recipe.

User wants the old branched aggregator collapsed: **OCAK runs as a single Claude shell** that walks through the comprehension checks sequentially (no leaf-worker spawning). The OCAK shell is spawned by the neuron via `pool.spawn(role=ocak, task=<goal>)`.

OCAK's checklist (sequential, single shell):
1. Feasibility — physical/sensor/irreversible blockers?
2. Role clarity — user is owner / observer / approver / unclear?
3. Actors — who/what is named or implied?
4. Concerns — ethical / sensitive / irreversible?
5. New tech — unknown to KG?
6. Estimation — duration plausibility?
7. Goal setter — verifiable success criteria?

OCAK writes verdicts to the recipe via `recipe.update(decision_branches=…)`. If ANY branch ends `needs_research`, OCAK publishes a `kind=needs_user_input` event to the neuron's broker inbox **and the recipe cannot advance to Phase C until the branch resolves.**

**F4.f mode 2 remedy** (needs_research silence): the broker event forces neuron to surface the question.
**F4.f mode 1 remedy** (orphan pendings): OCAK can mark itself done/abandoned/awaiting_user — never just hanging.

**TBD-B1:** Are the 3 `*-comprehension` drift-leaves part of OCAK, or part of Phase C? (User said "decide later.")
**TBD-B2:** Should OCAK's checklist be the same for every goal-class, or shape-dependent (e.g. creative-production goals get a "feasibility-of-tools" specialised step)?

### Phase C — Schedule drift/pattern checks via /loop
**Goal:** install dependency-injected oversight that fires on intervals, not in the neuron's critical path.

The neuron schedules:
- `goal-keeper` to fire on plan-creation and at /loop intervals (drift score 0–10).
- `pattern-observer` to fire end-of-plan and weekly.
- `critic` to fire on N=3 retry trigger or pre-sign-off (event-driven, not interval).

Each is **woken via `pool.wake(role=…)`** with its responsibility-key; the pool dispatches via the broker. The neuron does not poll for verdicts — the broker notifies.

**F4.f mode 3 remedy** (mid-plan pivots): `goal-keeper`'s drift score on every plan-creation cycle should catch "this plan is rebuilding something we already started" before the new plan ships actions.

**TBD-C1:** Loop cadences for goal-keeper/pattern-observer. Start at 30 min (matches the meta loop) but consider 2 h once mature.

### Phase D — Drive plan(s)
**Goal:** dispatch agentic-plan against the recipe.

The neuron calls `pool.spawn(role=agentic-plan, task={recipe_id, plan_goal, …})` and listens for plan lifecycle events from the broker. The plan layer itself is the proven `/agentic-plan` engine; **rebuild it under `eda-base/claude/.claude/commands/agentic-plan*.md`** as a port, not a redesign.

**F4.f mode 4 remedy** (task success ≠ system success): every plan terminates with a *user behavioural smoke test* step (`acceptance_signal.kind=user_smoke`), and the plan only graduates from `executing` to `succeeded` if the user explicitly accepts. Otherwise → `partial`.
**F4.f mode 3 remedy** (skipped-as-superseded): plan terminal status is one of `{succeeded, superseded, aborted, partial}`. Action-status rollup is informational, not the verdict.

**TBD-D1:** How does mid-plan supersession propagate? Proposal: when neuron decides to fork, it calls `plan.supersede(plan_id, by=new_plan_id)`. The old plan keeps its action statuses; only its terminal status changes. Worklog of the new plan includes a `kind=supersedes` entry.

### Phase E — Decide whether to repeat B→D
**Goal:** after a plan terminates, decide *recipe-level* next move.

Inputs:
- Plan terminal status (D).
- `expected_outcomes[]` from the recipe — which are met, which aren't.
- goal-keeper drift score.
- pattern-observer current verdict.

Decisions:
- All outcomes met + drift low → advance to F.
- Outcomes partial → another plan; back to D.
- Drift high or critic abort → re-aggregate via B (new comprehension cycle).
- User-abort signal → F as `abandoned`.

**TBD-E1:** Who actually decides? The neuron via heuristic vs the critic via a structured verdict. Default: the neuron, with critic as a consultant when ambiguous.

### Phase F — Close
**Goal:** terminal state on the recipe.

- Call `recipe.close(final_outcome=…)` with one of `{succeeded, partial, abandoned}` + evidence summary.
- Publish `kind=recipe_closed` event.
- Surface a *closing summary* to the user with what shipped, what didn't, and anti-patterns to recall on the next similar goal.
- Notify session-neurons to sleep (pool.sleep).

**F4.f mode 6 remedy** (LLM tag bleed): the schema validator for `final_outcome.description` and `final_outcome.evidence` strips `<…>` XML on write.

---

## 3. How each failure mode is addressed

| # | Failure mode (from §F4.f) | Phase remedy | Notes |
|---|---|---|---|
| 1 | Abandonment-by-orphan-pending | A3 (resume check) + Phase F mandatory close | Orphans get either resumed or closed; no silent rot. |
| 2 | Comprehension stalls on needs_research | B (OCAK forces user-surface event); D blocks on unresolved branches | Cannot advance to plan if any branch is `needs_research`. |
| 3 | Mid-plan architectural pivot (skipped-as-superseded) | C (goal-keeper drift) + D (explicit `supersede` + terminal status) | Distinguishes succeeded vs superseded vs partial vs aborted. |
| 4 | Task success ≠ system success | D (mandatory user-smoke acceptance step) | Plan stays `partial` unless user accepts the behaviour. |
| 5 | No cross-session continuity | A3 (recall-on-init + resume prompt) | Recipe lineage by goal-similarity, not by recipe id. |
| 6 | Schema-too-permissive (LLM tag bleed) | Validator: strip `<…>` on write | Single-line fix at write-time in pydantic validators. |

---

## 4. Open design questions (need user before code)

1. **OCAK's checklist:** confirm the 7 items (feasibility, role-clarity, actors, concerns, new-tech, estimation, goal-setter) are right. Anything to add/remove?
2. **Goal-similarity matching for A3 resume check:** what defines "substantively similar"? Embedding cosine, simple keyword overlap, or LLM judgement?
3. **Plan terminal status taxonomy:** confirm `{succeeded, superseded, aborted, partial}` is the right set. (Old system had `done` only.)
4. **User-smoke acceptance step:** is this a single mandatory action at the end of every plan, or only on certain shapes (e.g. linear-build yes, research-synthesize no)?
5. **Drift cadences (TBD-C1):** 30 min is the neuron loop; should goal-keeper match or be coarser?
6. **OCAK shape:** single Claude shell running the 7-step checklist sequentially is the user's request — confirmed.
7. **Plan-execution UX:** does the *user's* shell stay free to chat with the neuron during plan execution, or do we want a "monitor mode" that pauses chat until plan terminates?

---

## 5. What this doc does NOT cover
- Memory + KG architecture → `DESIGN-DATA.md`
- ML capabilities + pattern recognition → `DESIGN-ML.md`
- Logging contract across services → cross-cuts; one section in `DESIGN-DATA.md` (logging sink) + per-service rules in each doc.
- Test strategy → after the three design docs are agreed.
- Migration order (which microservice to rewrite first) → after all three docs.
