# Self-Audit — Where the v1 Design Docs Faltered (2026-05-15)

**Purpose:** Preserve the record of what I (Claude) got wrong in the first pass of design docs, so future-me (after compaction) doesn't repeat the mistakes.
**Trigger:** User pushback on 2026-05-15: I copy-pasted patterns from the failed system into the rewrite instead of re-deriving from their original prompt principles.
**Status:** LOAD-BEARING. Read before revising any design doc.

---

## The unifying mistake

I read the user's prompt looking for *what to build* (broker, pool, OCAK, phases) and missed *how it should feel*:
- LLM as animator, not protocol-runner.
- Harness as system, not slash-command prose.
- Recipe as self-sufficient context, not just a state file.
- Tools as IoC injectors, not RPC verbs.

The result was "system 2.0" — recognizable-but-different from the old failed system — instead of an actually-different shape.

---

## The 14 specific items

### 1. IoC violations beyond locks
Anywhere a doc says "the X agent does A, then B, then C," I shifted protocol onto the LLM. The right shape: every agent calls `next_instruction()` in a loop; the harness returns one step at a time. Applies to: neuron Phase A–F, OCAK 7-step checklist, `needs_research` event-firing, Phase A3 resume-check, mandatory user-smoke, worker init-ack/wait/work choreography.

### 2. Agentic-plan-as-meta-pattern miss
User said agentic-plan "needs to serve as baseline upon which other complex commands build upon." I treated it as a peer to neuron/OCAK/worker. It should be the **template**: neuron = `agentic-plan(shape=goal-pursuit)`, OCAK = `agentic-plan(shape=comprehension)`, critic = `agentic-plan(shape=adversarial-review)`. One pattern, many shapes.

### 3. Factory of plans across domains barely landed
User named **software, movie, robotic** explicitly. My docs cover software-coding sub-cases only. The factory is what distinguishes this from "yet another coding assistant" and I underweighted it.

### 4. Recipe-as-self-sufficient-context miss
User: "user problem and llm solution/progress context needs to be preserved so that work can actually migrate across sessions without loss." My schema has fields but doesn't *enforce* self-sufficiency. Test: `/clear` mid-recipe; can a fresh LLM read recipe+plans and continue? In my v1 design, probably not.

### 5. "The system is a llm (which means its no system at all)" miss
The deepest critique. State machines, deterministic next-instruction logic, and lifecycle transitions should live in *code modules*, not in slash-command prose. I described recipe schema and service boundaries but left the actual state-machine logic scattered across multiple slash commands.

### 6. Logging as visualization, not just structured JSON
User: "proper logging … so that **we can visualize the data flow**." I delivered structured logs. The visualizer is a first-class deliverable — likely an `edp-trace-viewer` microservice — not an afterthought.

### 7. Schema validation hitting the LLM
User flagged validators as both pinch points (good) AND difficulty surfaces (bad). I said "validators stay." I didn't address the *but*: validation errors should return as **instruction-shaped guidance** ("call `record_acceptance(...)` first"), not pydantic stack traces.

### 8. Versioned state for diagnosis miss
User: "preseve states by version to help with diagnosis." I noted recipes have a `version` field. User wanted **snapshots** — replay-able state per version. My design has no snapshot store, no replay tool.

### 9. KG curation policy missing
"Purge and start fresh" solves current pollution. It doesn't solve **re-pollution**. No ingestion policy: what gets stored, what gets filtered, who decides. We'll re-pollute in three months without this.

### 10. Impact-analysis as workflow primitive missing
User: "each modification to the system does an impact analysis." I mentioned this once as a sentence. Should be a workflow primitive: every change-introducing plan has a mandatory impact-analysis action before implementation, and the planner refuses to advance without it.

### 11. Loop placement and purpose wrong
User: "the loop that we create in **phase b** is to remind the user neuron to just drive the recipe from start to finish and consult other neurons if needed" + "other neurons will be called at intervals using loop command to drift check and pattern observe." I put the loop in Phase A as a generic heartbeat. Correct: the loop fires in Phase B and helper neurons (critic, goal-keeper, pattern-observer) each get their OWN cron — the neuron doesn't wake them, the cron does.

### 12. Event-driven inter-comms vs RPC inconsistency
User: "rely on the event driven system to inter-communicate." My broker is event-driven, but I gave pool/memory-svc/ml-cap HTTP RPC surfaces that agents call directly. Mixed paradigm. Pure version: agent↔agent and agent↔state-machine through events; RPC only for human-facing edges.

### 13. Deployment independence not specified
User: "to avoid issues where updating one service required to shut others." Separate repos ≠ separate deployments. I didn't specify version-stable endpoints, contract tests, or independent-restart guarantees.

### 14. Universal plan terminal-status taxonomy is too generic
I proposed `{succeeded, superseded, aborted, partial}` for ALL plans. Factory-of-plans implies success criteria differ by domain (a movie-plan's "succeeded" ≠ a software-plan's). Terminal-status logic must be **per shape**, not universal.

---

## How to use this audit
- When revising a design doc, check every claim against this list.
- If a section reads like "the agent does X then Y," it's probably a violation of item 1.
- The v2 design docs (DESIGN-CORE-v2.md, etc.) re-derive from these corrections.
- The v1 docs stay on disk as a record of what NOT to build.
