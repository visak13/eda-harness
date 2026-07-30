# DESIGN-CORE-v2 — re-derived from first principles (2026-05-15)

**Status:** DRAFT for user review. **Replaces** `DESIGN-CORE.md` (v1 kept on disk as record-of-what-not-to-build).
**Inputs:** `docs/baseline/USER_PROMPT_2026-05-15.md`, `docs/baseline/AUDIT-OF-MY-OWN-WORK.md` (the 14 items I missed in v1).
**Scope:** the orchestration core — eda-base/claude, edp-broker, edp-pool, plus the shape of every agent role (neuron, OCAK, planner, worker, session-neurons).
**Out of scope:** memory/KG (DESIGN-DATA-v2), ML capabilities (DESIGN-ML-v2).

---

## 0. The animating principle

**The LLM is the animator. The harness is the system.**

Every slash command is short — it establishes a role and tells the LLM how to ask "what now?" The actual logic — what makes a recipe transition states, when to spawn OCAK, when to surface to the user, when a plan is `succeeded` vs `superseded` — lives in code, inside MCP tools and a small state-machine module. The LLM never holds the protocol. It executes one instruction at a time and asks for the next.

If you can't pass a `/clear` test (drop the LLM's working memory mid-recipe; can a fresh LLM read state-on-disk and continue?), the design is wrong.

---

## 1. The load-bearing primitive: `next_instruction()`

Every agent role — neuron, planner, worker, OCAK, critic, goal-keeper, pattern-observer — runs the same outer loop:

```
1. activate (slash command body):
     "you are <role>. your scope is <handle>. call next_instruction(handle)."
2. loop:
     instruction = mcp.next_instruction(handle)
     if instruction.kind == "done":
         exit
     execute(instruction)
     # the act of executing usually calls a recording tool
     # (update_action, ask_user, post_event, ...)
     # which mutates state and unblocks the next instruction.
```

That is the **entire protocol the LLM holds.** Every other behaviour lives in the state machine that backs `next_instruction()`.

### 1.1 What `next_instruction` returns (instruction shapes)
```jsonc
// "ask the user" — surfaced because some state needs human input
{ "kind": "ask_user", "question": "...", "context": "...", "branch_id": "b4" }

// "spawn a child agent" — neuron asking pool to start an OCAK/planner/worker
{ "kind": "spawn", "role": "ocak", "handle": "...", "task_body": {...} }

// "do work" — a worker being told its single action
{ "kind": "do_action", "plan_id": "...", "action_id": "...", "brief": "..." }

// "record" — instruct the agent to record a fact/decision
{ "kind": "record_decision", "branch_id": "...", "fields": ["verdict","rationale"] }

// "wait" — nothing to do; the harness will event-wake this shell
{ "kind": "wait", "reason": "OCAK in progress; will be notified on completion" }

// "done" — terminal; agent exits
{ "kind": "done", "summary": "..." }
```

**Notice what isn't in the list:** "acquire_lock," "release_lock," "validate_schema," "check_if_other_neurons_should_be_woken." Those are harness-internal.

### 1.2 Why this dissolves the v1 protocol burden

| v1 protocol burden | v2 replacement |
|---|---|
| "neuron Phase A–F" | One loop. The phase the recipe is in lives in the recipe's state field; `next_instruction` reads it. |
| "OCAK runs 7-step checklist sequentially" | OCAK is one role. Each call to `next_instruction(ocak_handle)` returns one branch to evaluate. After all branches resolved, returns `done`. |
| "needs_research blocks and fires event" | `next_instruction` simply returns `ask_user` for that branch. |
| "Phase A3 recall: open recipes" | On `/neuron <goal>` activation, the slash command's first call to `next_instruction` returns either "resume recipe X" or "create recipe with these candidates." Surfaced as instructions, not a step the LLM remembers. |
| "executor acquires action lock then …" | Worker's `next_instruction` returns `do_action`. Harness locks under the hood; if contention, harness returns `wait`. The LLM never sees a lock. |
| "mandatory user-smoke at plan end" | Plan's terminal-status logic refuses to mark `succeeded` until acceptance is recorded. `next_instruction` returns `ask_user(do this smoke test)`. |

---

## 2. The state machine: where the actual logic lives

A small Python module — call it **`edp-fsm`** (its own microservice for testability, or a library shared via PyPI — TBD-2.1) — owns the transitions:

```
recipe states: created → comprehending → planning → executing → reviewing → closed
plan states:   drafted → executing → reviewing → terminal
action states: pending → in_progress → succeeded | failed | superseded
branch states: open → resolving → resolved | needs_user_input
```

The transition rules are *code*, not prose. Example (pseudocode):

```python
def recipe_next_instruction(recipe):
    if recipe.state == "comprehending":
        unresolved = [b for b in recipe.branches if b.state == "needs_user_input"]
        if unresolved:
            return AskUser(question=unresolved[0].question, branch_id=unresolved[0].id)
        if any(b.state != "resolved" for b in recipe.branches):
            return Spawn(role="ocak", handle=recipe.id)
        recipe.transition("planning")
        return recipe_next_instruction(recipe)  # recurse to new state
    if recipe.state == "planning":
        if not recipe.has_active_plan():
            return Spawn(role="agentic-plan", handle=recipe.id, shape=recipe.shape)
        return Wait(reason="plan in progress")
    # ... etc
```

That's it. The LLM never reads this file. It just calls the tool.

**Diagnosis benefit:** when something is wrong, you read `recipe.state`, run `recipe_next_instruction(recipe)` in a REPL, and see what the harness would say. No prompt archaeology.

---

## 3. Agentic-plan as the meta-pattern (factory of plans)

User: *"agentic-plan was working end-to-end with an abstract factory of plans (software, movie, robotic, etc), multiple shapes of plans … this structure needs to serve as baseline upon which other complex commands build upon."*

Refined understanding: agentic-plan is not a sibling of "neuron." Agentic-plan is **the template every other complex agent specializes**.

### 3.1 The template

```
agentic-plan(shape=<S>, domain=<D>):
   Phase A: comprehension     (shape-S-specific clarification pipeline)
   Phase B: research          (shape-S + domain-D-specific recall/web/...)
   Phase C: options           (generate option-set, judge, select)
   Phase D: plan              (emit actions according to shape S and domain D)
   Phase E: execute           (DAG-aware dispatch; per-action acceptance)
   Phase F: review            (terminal-status computation; pattern store)
```

Every other role is a specialization:

| Role | Specialization |
|---|---|
| **neuron** | `agentic-plan(shape=goal-pursuit, domain=<recipe.domain>)` — Phase D's actions are "spawn child plans"; Phase E orchestrates them. |
| **OCAK** | `agentic-plan(shape=comprehension, domain=<recipe.domain>)` — Phase D emits "resolve branch B1, …, B7"; Phase E runs them sequentially in this shell. |
| **planner** | `agentic-plan(shape=<recipe.shape>, domain=<recipe.domain>)` — the original use. |
| **worker** | `agentic-plan(shape=execute-one-action, domain=<recipe.domain>)` — degenerate case: Phase D has one action; Phase E runs it. |
| **critic** | `agentic-plan(shape=adversarial-review, domain=<recipe.domain>)` — Phase D emits red-team probes. |
| **goal-keeper** | `agentic-plan(shape=drift-check, domain=<recipe.domain>)` |
| **pattern-observer** | `agentic-plan(shape=anti-pattern-mining, domain=any)` |

**One implementation. Many shapes. The factory is real, not metaphorical.**

### 3.2 The domain factory

`domain` is a registered enum + a small module:

```
domains/
  software_coding/      # the existing strength
    capabilities.yaml   # what tools to call (lint, test, build, ...)
    success_criteria.py # what "succeeded" means for software
  movie_production/
    capabilities.yaml   # script, storyboard, render, edit, ...
    success_criteria.py # what "succeeded" means for movie
  robotic/
    capabilities.yaml   # simulate, calibrate, deploy-to-hardware, ...
    success_criteria.py
  generic/
    # fallback for unclassified
```

Each domain module declares:
- The capabilities (MCP tools, external commands) available.
- The shape default mapping (e.g., movie-production defaults to `creative-production` shape).
- The terminal-status logic for plans in this domain (addresses audit item 14).
- The KG ingestion filter for facts from this domain (addresses audit item 9 / DESIGN-DATA-v2).

### 3.3 The shape factory

Shapes are the workflow primitives that survived from the old system: `linear-build`, `modular-build`, `poc-iterate-build`, `creative-production`, `diagnose-fix-verify`, `gather-validate-submit`, `research-synthesize`. These are kept; each is a shape module that customizes Phase A–F prompts/criteria.

**New:** every shape declares its success criteria per goal-class (addresses audit item 14). `linear-build.succeeded` for software ≠ `linear-build.succeeded` for movie.

---

## 4. The recipe as self-sufficient context

A recipe must pass the **`/clear` test**: drop the LLM's memory; a fresh LLM reads the recipe (and the plans it links to) and can continue.

To pass that test the recipe carries — in code-enforced fields, not free-text:

```jsonc
{
  "recipe_id": "...",
  "user_goal_verbatim": "...",                // never paraphrase
  "user_goal_distilled": "...",               // what OCAK extracted
  "domain": "software_coding",                // factory key
  "shape": "linear-build",                    // factory key
  "state": "executing",
  "branches": [...],                          // OCAK output, with rationale per resolution
  "expected_outcomes": [...],                 // verifiable
  "constraints_discovered_mid_flight": [...], // things that were not in the initial goal but became binding
  "assumptions_made": [...],                  // with who decided + when
  "rejected_options": [...],                  // what we tried, why we backed off
  "plan_refs": [...],
  "knowledge_refs": [...],
  "open_questions_for_user": [...],           // exactly the surface the slash command consults
  "snapshots": [...],                         // ← see §7
  "events": [...]                             // append-only audit trail
}
```

The recipe is the **only thing** a fresh LLM needs to read. Everything the previous LLM "knew in its head" must be persisted here as an explicit field. The state machine *refuses* to advance a recipe whose required fields for the current state are empty.

---

## 5. Slash commands as activators (not protocol containers)

Every role's slash command body shrinks to roughly this shape:

```markdown
# /neuron — recipe owner activation

You are the **recipe owner** for a user goal.

## What you do
Call `mcp.next_instruction(handle=recipe_id)`. Execute the returned instruction. Repeat until `done`.

## Conventions
- Surface `ask_user` instructions to the user verbatim with the question and any context.
- Record any user answer via `mcp.record_user_answer(branch_id, answer)`.
- Treat `wait` as an end-of-turn — the harness will event-wake you.

You hold no protocol. The harness has it.
```

That's the whole body. Less than 30 lines. **Audit item 5 dissolved.**

Other roles have a similarly-short body, varying only in:
- Their `role=` value.
- Their `handle=` type (recipe_id / plan_id / action_handle).
- A short list of role-specific recording verbs.

---

## 6. The loop — correct placement (audit item 11)

User: *"the loop that we create in phase b is to remind the user neuron to just drive the recipe from start to finish and consult other neurons if needed."*

The neuron's `/loop` is armed **during the comprehension→planning transition** (the point user called "phase b"). The loop prompt is:

> "Re-read the GUIDELINES + the current recipe. Call `next_instruction(recipe_id)`. If it says `wait`, end the turn. If it says anything else, do it."

The loop is a **resume mechanism** for the case where a session compacts mid-recipe. It is not a heartbeat for "drive the recipe." Drive happens event-driven via the broker. The cron is a fallback.

### 6.1 Helper neurons get their own crons
- `goal-keeper`: own cron (e.g., every 2 h while a recipe is `executing`). Cron-fired prompt: "load this recipe's drift context; emit a drift-score event."
- `pattern-observer`: own cron (e.g., daily). Cron-fired prompt: "scan recent worklogs; emit anti-pattern events."
- `critic`: not a cron — event-driven on N=3 retry trigger or pre-sign-off. Fires from broker, not from a clock.

The neuron does not wake helpers. The cron does. The neuron *consumes* helper events when its `next_instruction` returns `apply_drift_verdict(...)` or `apply_critic_verdict(...)`.

---

## 7. Versioned state + snapshots (audit item 8)

Every state-mutating tool call appends a **snapshot** (full recipe JSON copy) to `recipe.snapshots[]` (or sidecar file `.recipes/<id>/snapshots/v<N>.json` if the inline list grows). Snapshot also records:
- `version`, `at`, `by` (which agent/tool), `kind` (what changed), `reason` (free-text from the caller).

Diagnostic tools:
- `recipe.diff(v_a, v_b)` — what changed between two versions.
- `recipe.replay(at=v_n) -> next_instruction` — what would the harness have done at snapshot N?

This is **for the operator**, not the LLM. The LLM doesn't read snapshots. Operators read snapshots to debug why a recipe went sideways.

Same pattern at the plan level (`plan.snapshots[]`).

---

## 8. Validators-as-instruction (audit item 7)

Every MCP tool that mutates state catches its validation errors internally and re-emits as instruction shapes:

```python
# raw pydantic surface (BAD)
ValidationError: 1 validation error for ActionDoneEvent
acceptance_signal
  field required (type=value_error.missing)

# what the LLM sees (GOOD)
{
  "kind": "instruction_needed_first",
  "what": "record_acceptance",
  "why": "this action's acceptance_signal is still null; cannot mark done",
  "how": "call mcp.record_acceptance(action_id=..., signal={...}) then retry"
}
```

Validators are still the guard rails the user wanted. They no longer ambush the LLM.

---

## 9. Impact-analysis as a workflow primitive (audit item 10)

Every plan whose `kind=change-to-the-system` (a meta-domain — modifications to eda-base itself) has, by template, a mandatory first phase action:

```
action: impact_analysis
  description: enumerate which services / files / contracts this change touches; identify upstream/downstream effects; flag breaking changes; write to plan.impact_analysis_ref
  acceptance: a non-empty plan.impact_analysis_ref pointing to a doc; user-acknowledged
  blocks: all other Phase D actions until done
```

The terminal-status logic for this plan class refuses `succeeded` if `impact_analysis_ref` is null. Built into the **eda-base meta-domain's success_criteria**.

---

## 10. Event-driven inter-comms; RPC only at human edges (audit item 12)

```
[user shell, dashboards]  ←──RPC──→  [broker, pool, fsm, memory-svc]
                                              │
                                              │ events only
                                              ▼
[neuron][planner][worker][ocak][critic]  ← agents
```

- Agents communicate with each other and with state via **broker events**.
- Human-facing APIs (the user's terminal, any future dashboard) use HTTP RPC.
- Agents call **MCP tools** which internally translate to broker events / state mutations. The agent never has to choose "should this be an event or an RPC."

The pool's `/spawn` HTTP endpoint is fine — it's at the human edge (user shell tells pool to spawn). Agent→agent never crosses HTTP directly.

---

## 11. Deployment independence (audit item 13)

- Each microservice in its own repo + its own Dockerfile.
- Endpoints are versioned (`/v1/...`); breaking changes ship `/v2/...` while `/v1/` is kept for one transition cycle.
- Contract tests between services (one tiny test file per service-pair) run in CI. New service can't merge without contract tests for what it consumes.
- `docker compose restart edp-broker` does **not** require restarting pool, memory-svc, etc. The broker's event log is durable (append-only file); on broker restart, agents reconnect via the existing `since_ts` replay endpoint.

---

## 12. Microservice landscape (refined)

```
eda-base/
├── claude/                  ← orchestration repo
│   ├── .claude/commands/    ← short activator slash bodies
│   ├── mcp_tools/           ← thin MCP wrappers; ALL state mutation goes through these
│   ├── .plans/  .recipes/  .memory/  ← state on disk (recipe is self-sufficient)
│   └── docs/  baseline/  design/  guides/
│
├── edp-fsm/                 ← NEW. The state machine module. Owns next_instruction(),
│                              transition rules, snapshot mgmt, validator-as-instruction.
│                              Imported by mcp_tools/ in claude/, can also be a microservice.
│
├── edp-broker/              ← event bus. Dumb pipe. (unchanged from v1)
│
├── edp-pool/                ← spawn-on-demand shell launcher. (unchanged from v1 in shape)
│
├── edp-memory-svc/          ← KG façade. (DESIGN-DATA-v2)
├── edp-proxy/               ← OpenAI↔Ollama proxy. (DESIGN-DATA-v2)
│
├── edp-ml-capabilities/     ← outcome prediction. (DESIGN-ML-v2)
├── edp-pattern-recognition/ ← pattern miner. (DESIGN-ML-v2)
├── edp-problem-solving/     ← domain corpora. (DESIGN-ML-v2)
│
├── edp-trace-viewer/        ← NEW. Data-flow visualization over broker events + service
│                              logs. Renders sequence diagrams per recipe/plan. (audit item 6)
│
└── edp-stack/               ← docker-compose for the whole stack (renamed from edp-memory)
```

Two new microservices compared to v1: `edp-fsm` (the state machine) and `edp-trace-viewer` (the visualization).

---

## 13. How each audit item lands in v2

| Audit | Where addressed |
|---|---|
| 1. IoC violations | §1 — `next_instruction` dissolves them. |
| 2. agentic-plan as meta-pattern | §3 — every role specializes the template. |
| 3. Factory of domains | §3.2 — registered domain modules with capabilities + success criteria. |
| 4. Recipe self-sufficiency | §4 — `/clear` test; required fields enforced. |
| 5. System ≠ LLM | §1, §2, §5 — state machine owns logic; slash commands are short. |
| 6. Logging as visualization | §12 — `edp-trace-viewer` microservice. |
| 7. Validators-as-instruction | §8. |
| 8. Versioned state for diagnosis | §7 — snapshots + diff/replay tools. |
| 9. KG curation policy | DESIGN-DATA-v2 (per-domain filter declared in domain module). |
| 10. Impact-analysis as primitive | §9 — built into eda-base meta-domain's success criteria. |
| 11. Loop placement + helper crons | §6. |
| 12. Event-driven vs RPC | §10. |
| 13. Deployment independence | §11. |
| 14. Per-shape terminal status | §3.1, §3.3 — success criteria declared per shape × domain. |

---

## 14. Open design questions for v2

1. **`edp-fsm` shape:** standalone microservice (HTTP) or shared library (PyPI/uv path-dep)? Trade-off: microservice is testable in isolation and language-portable but adds a hop; library is simpler but tightly couples. **Recommendation: library, imported by mcp_tools in claude/ and by any other service that needs to project state.** Confirm.
2. **Domain enumeration scope at launch:** software-coding only at first, or scaffold software + movie + robotic + generic from day one? **Recommendation: software + generic at launch; movie and robotic when a real goal arrives in those domains.** Confirm.
3. **Snapshot retention:** keep all snapshots forever, or compact after N versions / closed-recipe? **Recommendation: keep all for closed recipes (audit value); compact mid-flight snapshots beyond v50.**
4. **`next_instruction` blocking vs polling:** does the agent call `next_instruction` synchronously and block, or does it call once + arm a Monitor on its broker inbox? **Recommendation: synchronous call returns immediately with one of {action, wait, done}; `wait` signals end-of-turn; broker event wakes the shell.** Confirm matches user's "event-driven" preference.
5. **OCAK as in-shell sequential vs tool-driven:** in v1 I described "single shell runs 7-step checklist sequentially" (user-preferred phrasing). In v2 §1.2 OCAK is one role with `next_instruction` returning one branch at a time — same single-shell behaviour, but the *logic* lives in the FSM. Confirm this is the right interpretation.
6. **Goal-similarity for resume (audit-item-1-derived):** embedding cosine vs LLM judgement vs both? **Recommendation: embedding cosine for the first cut; LLM judgement only when cosine returns ≥1 candidate that the user must disambiguate.**
7. **Per-shape × per-domain success_criteria authoring:** these are code modules (`shapes/linear_build/criteria_software.py`, etc.). Do we want a declarative YAML layer over them for non-coder authoring? Defer.

---

## 15. What this doc does NOT cover
- Memory + KG re-design with curation policy → `DESIGN-DATA-v2.md`
- ML capabilities + pattern recognition + domain corpora → `DESIGN-ML-v2.md`
- Migration order (which microservice to build first) → after all three v2 docs are agreed.
- Test strategy + contract tests → after migration order.
