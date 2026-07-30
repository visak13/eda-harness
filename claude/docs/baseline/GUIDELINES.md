# Session Survival Guidelines — READ FIRST EVERY SESSION

**Purpose:** This file is the entry point after any session compact, clear, or restart.
It tells you (Claude) what is going on, where to look, and what *not* to do.

---

## 1. Where you are
- **Workspace root:** `C:\Projects\Learning\eda-base\` — parent workspace for the rewrite. Confirmed with user 2026-05-15.
- **Claude repo (this repo):** `C:\Projects\Learning\eda-base\claude\` — holds MCP tools, slash commands, plans, recipes, state, and these baseline docs. **This is where you operate.**
- **Microservice repos:** each microservice is its own repo, sibling-level inside `eda-base/` (e.g. `eda-base/edp-broker/`, `eda-base/edp-pool/`, ...). NO monorepo. **All microservices will be freshly written under `eda-base/` — including the existing `edp-proxy`, `edp-ml-capabilities`, `edp-pattern-recognition`, `edp-memory`, `edp-problem-solving`** (confirmed with user 2026-05-15). Behaviors are preserved; code is fresh.
- **Old repos (REFERENCE-ONLY — never edit):**
  - `C:\Projects\Learning\evolving-deep-agent\` — the failed claude repo + mcp-service + agent-service. Read for analysis only.
  - `C:\Projects\Learning\edp-*` (proxy, ml-capabilities, pattern-recognition, memory, problem-solving, debug, errors) — reference only. Will be re-implemented fresh under `eda-base/`.

## 2. Read order on a fresh session
1. `docs/baseline/USER_PROMPT_2026-05-15.md` — the load-bearing intent.
2. This file (`GUIDELINES.md`).
3. `docs/baseline/PROGRESS.md` — running log of what has been decided/done/discussed.
4. `docs/design/METHODOLOGY.md` — the BINDING staged plan + where we are + the gate log. Follow religiously; no gate skipping.
5. `docs/design/DESIGN-v4.md` — the authoritative rough design (S0).
6. `docs/baseline/AUDIT-OF-MY-OWN-WORK.md` — the 14-item record of v1/v2 mistakes; don't repeat them.
7. `docs/baseline/OPEN_QUESTIONS.md` / `ANALYSIS_FINDINGS.md` — supporting detail.

If any of those files are missing, ASK the user before acting — do not regenerate from memory.

**Memory rule:** all design/context lives on disk here. NEVER store design, schemas, or plans in the memory layer. Memory holds only durable collaboration rules.

## 3. Non-negotiable operating rules
- **Discuss before acting.** The user explicitly said this is a bi-directional channel. Any non-trivial step → propose, get confirmation, then act.
- **No assumptions.** If a doc, plan, recipe, or piece of state is ambiguous, ask.
- **Document as you go, not at the end.** Every meaningful decision or finding lands in `PROGRESS.md` *before* moving on. Late documentation was a named root cause of the prior failure.
- **No monorepo.** New microservices live in their own sibling repos. The claude repo only holds MCP tools, slash commands, plans, recipes, state, and these docs.
- **Don't pollute the knowledge graph.** Reuse the KG server (it is more fault-tolerant now) but start with a clean group; previous noise is to be discarded, not migrated.
- **Don't touch the ollama docker image.** It works. Leave it.
- **Use the edp-proxy** for KG↔ollama traffic. It adds fault tolerance.
- **Behaviors preserved, code rewritten.** Python microservices get a rewrite, but the behaviors (recipe-driven planning, pool-spawned shells, event broker, agentic-plan shapes/factory) are kept.

## 4. What the new system looks like (target shape — current working design is v3)
**Authoritative source:** `docs/design/DESIGN-v4.md` (system *shape*) + `docs/design/DESIGN-v5-awareness-injection.md` (what the tools are *for* — the project's actual center; agreed 2026-05-19). v5 governs direction; v4 governs structure; v1/v2/v3 are history. The tools exist to FORCE awareness the LLM lacks and RE-INJECT context it loses — not merely take/dispatch/gatekeep. If anything conflicts, v5 (purpose) then v4 (shape) win.

- **Two nested to-do lists with smart helpers.** Neuron writes a **recipe** (research → poc → mvp → hitl → done). For each recipe step a **planner** writes a **plan** (DAG of actions). A **worker** does one action.
- **Every role calls one tool: `next_action(handle)`.** The tool reads the artifact, walks dependencies, returns the next instruction. Everything operational (locks, session IDs, broker routing, snapshots) is hidden inside MCP tools and microservices.
- **Slash command bodies are ~20–30 lines** — activator + outer `next_action` loop + tiny convention list. No protocol prose.
- **agentic-plan is the planner role specifically** (not a meta-pattern for every role). Neuron, planner, worker share the `next_action` primitive but have role-specific implementations.
- **Helper neurons** (`goal-keeper`, `pattern-observer`, `critic`) are long-running shells that own a slice of knowledge and wake on broker events or their own crons.
- **Broker** = dumb message bus with `to=role-or-relative-ref` resolution. **Pool** = shell spawner with session↔role↔handle mapping; lock-by-spawn-lifetime. **Memory-svc** = KG façade with per-domain curation filter.
- **Per-domain × per-shape success criteria** live in `domains/<d>/success_criteria.py` and `shapes/<s>/` modules.
- **Versioned snapshots** on every `record_*` for operator diagnosis.
- **Logging everywhere**; visualization via `edp-trace-viewer` (second wave).

## 5. OFF-LIMITS until user signs off
- Writing any production code in `eda-base/claude/` or any new microservice repo.
- **Modifying ANY file in the old repos:** `evolving-deep-agent/` or `C:\Projects\Learning\edp-*`. They are frozen reference.
- Touching the knowledge graph data (forget/purge) — discuss first.
- Killing or restarting any running daemon (pool, broker, ollama, KG).
- Any git operations.

## 6. The loop reminder
A `/loop` at 30-minute intervals tells future-you to:
1. Re-read this file + `PROGRESS.md`.
2. Surface current status to the user.
3. Resume the active discussion thread, not invent a new one.

The loop is a **reminder**, not a tasker. It must not autonomously start work.

## 7. If you find yourself unsure
Stop. Ask. The user prefers a question over a wrong move.
