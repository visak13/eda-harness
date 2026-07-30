# DESIGN-v4 — Skills + Masked-LLM tools (2026-05-16)

**Status:** DRAFT. Replaces DESIGN-v3.md. v1/v2/v3 kept on disk as record.
**Inputs:** all prior baseline + audit docs; user's 2026-05-16 second round; my fresh read of `evolving-deep-agent/.claude/commands/agentic-plan.md`, `.claude/commands/agentic-plan-execute.md`, `mcp-service/src/mcp_service/recipe_schema.py`, and the mcp-service CLAUDE.md surface.

This doc is verbose on purpose. The user called me out for not stating the problem, my thinking, and the solution. Every section here does all three.

---

## 0. The problems I'm trying to solve (stated plainly)

Six problems are now concrete enough to design against:

**P1. Operational complexity leaks into LLM prose.**
The current `agentic-plan.md` body has the LLM remember: arm two Monitors, do init-ack on the pool, read protocol doc, then handle inbox events, bi-directional steering, retry caps with escalation, parallelism caps, acceptance review rendering. It's a thousand-line protocol. The LLM forgets steps under context pressure. That's audit item 1 — and it's the visible symptom of the whole "system is a llm" critique.

**P2. Plans are big (30–40 actions) and planners lose context.**
This is why the worker pattern exists. The planner offloads execution to fresh worker shells. But the planner *still* has to track which actions are in flight, which have returned, what the dependency graph looks like, what's blocked on what. A 30-action DAG plus per-action acceptance review plus mid-flight steering exhausts the context window before the plan terminates. You named this directly.

**P3. Helper agents (OCAK leaves, goal-keeper, critic, pattern-observer) currently live as separate Claude shells.**
Each shell is one more thing the system has to spawn, sleep, wake, route messages to, and reconcile session-id maps for. The cluster machinery is expensive. And the helpers' work is small — usually a single LLM judgement call. Spawning a shell for that is overkill. You said: "instead of spawning shells, just add these as skills."

**P4. Cross-session continuity is broken because the recipe doesn't carry enough context.**
The stateless-auth trilogy proved it: recipes 1 and 2 had no worklog and no fields capturing why the user reformulated. Recipe 3 succeeded only because the user pre-loaded the answer in their phrasing. The recipe needs to be a self-sufficient continuation surface, not just a state file.

**P5. Plans fail by abandonment, not by error.**
93 pending + 5 in_progress orphans across 41 plans, vs only 3 failed. The system has no mechanism that says "this plan has been idle 4 hours with a pending action and no live worker; either resume or close." The next_action tool needs to detect this without making the LLM remember to check.

**P6. KG and ML may not even fit the new shape.**
The current system spawns embeddings, vector search, graph traversal, anti-pattern recall, outcome prediction. You're asking: do we need any of that, or could a plain text file serve? I don't have an answer yet, but my v3 was assuming "yes, keep all of it" without examining. Honest position: defer KG/ML; reserve a slot, build the system without depending on either, see if a text file actually suffices.

---

## 1. The two architectural primitives you handed me

Both of these are mine to lean on, not invent. They're load-bearing.

### 1.1 Skills, not shells, for cognition that fits in one LLM turn

A **skill** in Claude Code is a slash-command-shaped prompt fragment loaded *on demand* into the *current* shell. It steers the LLM's reasoning for a few turns and unloads. Skills are cheap, composable, and don't require session-id mapping, broker routing, or sleep/wake protocol.

**Where it changes the design:**
- OCAK comprehension becomes a *skill* the neuron invokes in its own shell when it needs to walk feasibility / role / actors / etc. The neuron temporarily *becomes* OCAK, walks the checks, and exits the skill. No fan-out, no leaf shells.
- `goal-keeper`, `pattern-observer`, `critic` become skills. When the neuron needs a drift check, it invokes `goal-keeper-check`. When the planner is about to ship a plan, it invokes `critic-review`. The skill loads → does its thinking in the host shell's context → emits a verdict → unloads.
- The cluster of separate shells dissolves. The only shells we spawn are: neuron (main), planner (when a recipe step needs a 30-action plan), worker (per plan action).

**Risk:** loading a skill into a shell pollutes that shell's context with the skill's prompt. The mitigation you suggested: a cron-like `/loop` skill that periodically re-establishes the shell's role to push out skill pollution. The host shell's role survives; the skill's transient context fades.

### 1.2 Masked-LLM-microservice for "smart" MCP tools

When an MCP tool's logic is too nuanced for a deterministic Python implementation but doesn't deserve a long-running session-neuron, hide a Claude shell behind it. The MCP tool routes the call (via broker + pool) to a dedicated Claude shell that has its own skills loaded and its own repo. Periodic `/clear` + skill-reload keeps the masked-LLM's chat compressed while preserving its capabilities.

**Where it changes the design:**
- `next_action(handle)` is the canonical case. The deterministic part (read JSON, walk DAG, return first pending action) lives in plain Python in the MCP tool. The nuanced part (detect stale action, suggest replan because acceptance is met-but-unmarked, decide if the plan deserves to be marked partial) is shipped to the masked-LLM as a single short prompt — "here's the recipe and a snippet of worklog; what should the neuron do next?"
- The masked-LLM lives in its own microservice repo (e.g. `eda-base/edp-fsm/`) but appears to all callers as a single MCP tool. No caller needs to know there's an LLM behind it.
- The pattern generalizes: any future "smart tool" (e.g. an acceptance-comparer that decides ACCEPT/EDIT/REJECT) can use the same primitive.

**Risk:** every masked-LLM tool call costs a Claude turn. If `next_action` is called dozens of times per recipe, the cost adds up. Mitigation: the deterministic Python path handles the common case (90%+); the LLM is invoked only when the deterministic path can't decide.

These two primitives are the spine of v4.

---

## 2. The artifacts (recipe / plan / action) — with transitions made explicit

This is what I owe you from v3: when a recipe state changes, what triggers it, who does it, what gets emitted.

### 2.1 Recipe — the neuron's continuation surface

A recipe is JSON at `.recipes/<recipe_id>/recipe.json` plus `snapshots/v<N>.json` on every mutation. It is the **single artifact a fresh LLM reads to resume work** — passes the /clear test by construction.

**Schema (refined from v3, lighter than current v2):**
```jsonc
{
  "recipe_id": "stateless-auth-2026-05-16",
  "user_goal_verbatim": "...",                 // never paraphrased
  "user_goal_distilled": "...",                // OCAK's clean rewrite
  "domain": "software_engineering",            // free-text string, not enum (user point 5)
  "state": "executing",                        // see state-machine below

  "comprehension": {                           // OCAK's output; persisted not re-derived
    "branches": [
      { "id": "b1", "question": "...", "status": "resolved",
        "verdict": "...", "rationale": "..." },
      { "id": "b4", "question": "...", "status": "needs_user_input",
        "verdict": null }
    ],
    "expected_outcomes": [
      { "id": "o1", "description": "...", "verification": "..." }
    ],
    "rejected_options": [...]
  },

  "steps": [                                    // free-form; no enum on `kind` (user point 5)
    { "step_id": "s1", "kind": "research",
      "description": "Survey stateless auth schemes",
      "status": "done", "depends_on": [],
      "execution": "inline",                    // see §3.2
      "outputs": ["docs/SURVEY.md"],
      "rationale_for_next": "..." },
    { "step_id": "s2", "kind": "poc-and-mvp-in-one-go",
      "description": "Build the candidate as Spring filter with tests",
      "status": "in_progress", "depends_on": ["s1"],
      "execution": "spawn_planner",
      "plan_ref": "2026-05-16-cdi-hct-spring" }
  ],

  "context": {                                  // the /clear-test surface
    "assumptions":     [{ "id": "...", "text": "...", "by": "user|neuron|critic", "at": "..." }],
    "decisions":       [{ "id": "...", "text": "...", "rationale": "...", "by": "...", "at": "..." }],
    "open_questions":  [{ "id": "...", "for_branch": "b4", "question": "...", "asked_at": "..." }]
  },

  "version": 7,
  "snapshots_ref": ".recipes/.../snapshots/",
  "events_ref":    ".recipes/.../events.jsonl"  // append-only audit trail
}
```

**Recipe state machine (the transitions I owed you):**

```
created ──▶ comprehending ──▶ planning ──▶ executing ──▶ reviewing ──▶ closed
                                  ▲                          │
                                  └──────────(more steps)────┘
                                  ▲                          │
                              (drift-detected: ─reopen──── back to comprehending)
```

| From | To | Trigger | Who | Side effects |
|---|---|---|---|---|
| created | comprehending | recipe just persisted | neuron | OCAK skill invoked |
| comprehending | planning | all `branches[].status` ∈ {resolved, deferred} AND ≥1 step defined | neuron (next_action says so) | record_recipe(state="planning") |
| comprehending | comprehending | any branch is `needs_user_input` | neuron | open_question emitted; neuron asks user |
| planning | executing | a step's `execution == spawn_planner` AND `pool.spawn_planner` returned ok | neuron | recipe step status → in_progress; broker subscription armed |
| planning | executing | a step's `execution == inline` AND inline work runs | neuron | step status → in_progress in same turn |
| executing | reviewing | step's terminal event (plan_closed for spawn_planner, or inline_done for inline) AND no more pending steps | next_action tool detects | step status → done |
| executing | planning | step terminal AND more steps pending | next_action tool | loop back to dispatch next step |
| reviewing | comprehending | goal-keeper skill verdict says drift | neuron after invoking skill | new branch added; state reopens |
| reviewing | closed | all expected_outcomes verified | neuron after invoking critic skill (optional) | final_outcome written |
| any non-terminal | closed | user explicitly aborts | neuron | final_outcome.status="abandoned" |

Notice what's *not* in the recipe: lock state, session IDs, planner inbox refs, worker counts. Those are operational and live elsewhere.

### 2.2 Plan — the planner's materialization of one recipe step

A plan exists only when a recipe step's `execution == spawn_planner`. Smaller steps are inline in the neuron — no plan, no planner, no worker spawn. This is your point: not all recipe steps need a planner.

**Schema (light):**
```jsonc
{
  "plan_id": "2026-05-16-cdi-hct-spring",
  "recipe_id": "stateless-auth-2026-05-16",
  "recipe_step_id": "s2",
  "domain": "software_engineering",
  "shape": "modular-build",
  "goal": "...",
  "actions": [
    { "action_id": "a1", "description": "...", "depends_on": [],
      "status": "done", "executor_mode": "subagent",
      "acceptance": { "kind": "tests_pass", "expected": "...", "actual": "..." },
      "result_ref": "...", "attempt": 1 },
    { "action_id": "a2", "description": "...", "depends_on": ["a1"],
      "status": "in_progress", "executor_mode": "subagent",
      "acceptance": { "kind": "tests_pass", "expected": "..." }, "attempt": 1 }
  ],
  "context": {
    "carried_from_recipe": ["d1"],
    "assumptions_made_by_planner": [...],
    "rejected_approaches": [...]
  },
  "terminal_status": null,                       // succeeded|superseded|aborted|partial
  "version": 4
}
```

**Plan state machine:**

```
drafted ──▶ dispatching ──▶ acceptance_review ──▶ terminal
              ▲                    │
              └──(replan)──────────┘
```

| From | To | Trigger | Who | Side effects |
|---|---|---|---|---|
| drafted | dispatching | record_plan() called with ≥1 action | planner | first wave's runnable actions visible to next_action |
| dispatching | dispatching | a worker emits result | broker → planner | mark action done/failed; next wave evaluated |
| dispatching | acceptance_review | all actions terminal | next_action detects | planner invokes acceptance review (inline if unambiguous; ask_neuron if not) |
| acceptance_review | dispatching | one or more actions need replanning | planner | replanned actions appear as new wave |
| acceptance_review | terminal | all actions accepted | planner | compute terminal_status via domain × shape success_criteria; emit plan_closed event |
| dispatching | terminal | retry cap hit on N=3 across attempts AND critic skill (optional) verdict says abort | planner | terminal_status=aborted |

### 2.3 Action — the worker's task

Just a sub-object of a plan; no separate state machine beyond its `status` field. Worker spawned with `{plan_id, action_id}`. The pool's spawn IS the lock; lock lifetime == worker lifetime.

---

## 3. The roles, what each does, what each delegates

### 3.1 Neuron (the user's main shell)

**Activator slash body (target ~30 lines):**
```markdown
# /neuron — recipe owner

You own a recipe. The recipe is the durable continuation surface.

## On activation
Call `next_action(recipe_id?, user_input)`. If no recipe_id, the tool will either resume
a similar open recipe or instruct you to author a fresh one.

## Outer loop
Call `next_action(recipe_id)`. Execute the returned instruction. Repeat.

Common returned instruction kinds:
- `invoke_skill(name)` — load and run a skill (OCAK, goal-keeper-check, critic-review, ...).
- `ask_user(question, branch_id?)` — surface verbatim, then `record_user_answer(branch_id, answer)`.
- `record_step(step)` — author a recipe step's JSON; tool validates.
- `spawn_planner(step_id)` — `pool.spawn_planner(recipe_id, step_id)`; you don't track session ids.
- `run_inline(step_id)` — do the step's work yourself in this shell; then `record_step_result(...)`.
- `wait` — end turn; broker will event-wake you when work returns.
- `done` — close the recipe; final_outcome already written.

You don't track session IDs, locks, or operational state. Those live in tools.
```

**What the neuron does in-shell:**
- OCAK comprehension (skill).
- Asking the user open questions and recording answers.
- Inline recipe steps that don't need a planner (e.g. "ask user to confirm direction", small research recalls).
- Calling helper skills (goal-keeper, critic) when next_action returns invoke_skill.

**What the neuron delegates:**
- Plan materialization for big steps → spawn_planner (separate shell).
- Action execution → planner spawns workers (further separate shells).
- Anything operational → the MCP tool surface.

### 3.2 Planner (spawned only when needed)

Spawned when a recipe step's `execution == spawn_planner`. Activator body ~30 lines, same shape: outer next_action loop. Differences from neuron:
- Its handle is `plan_id`.
- Its returned instructions include `dispatch_action(action_id)`, `wait_for_worker(action_id)`, `record_acceptance(action_id, verdict)`, `ask_neuron(question)`.
- It does *not* hold the recipe context — it gets the relevant carry-over via `context.carried_from_recipe` written into the plan at draft time.

**Why a separate shell:** plans have 30–40 actions. The planner's job is bookkeeping (which action ran, which result came back, whether to replan). Keeping that out of the neuron's context is what makes recipe-level reasoning survive across long plans.

### 3.3 Worker (spawned per action)

Already proven; carry the pattern forward. Activator body ~15 lines: read brief, do work, record_result, exit. Pool owns the lock for the worker's lifetime; worker never sees a lock.

### 3.4 Helpers — now skills, not shells

`OCAK`, `goal-keeper`, `pattern-observer`, `critic`, plus the 11 leaf checkers (feasibility, actor-id, etc.) all become **skills loaded into the host shell on demand**. The neuron and planner invoke them via `Skill('<name>')` when next_action says so.

**Why skills, not shells:**
- Helper's actual work is 1–3 LLM turns. A whole shell-lifecycle (spawn, init-ack, send task, wait, post result, sleep) is overhead for that.
- Skills compose: OCAK is itself a skill that internally invokes the leaf skills (feasibility-checker, actor-id, role-clarity, etc.) sequentially in the same shell.
- Session-id mapping, broker routing, sleep/wake protocol all dissolve. The cluster ceases to be a multi-shell concept.

**Cron-loop hygiene (your suggestion):** the host shell can pollute as multiple skills load. The neuron's slash body declares a periodic `/loop` reminder that re-establishes role: "you are the neuron, your handle is recipe X, call next_action." Re-establishment pushes out transient skill context. Skills themselves write their findings to the recipe / plan before unloading, so the durable signal survives.

---

## 4. The MCP tool surface (what the LLM ever sees)

Smaller and more focused than v3. Many tools have a masked-LLM backing where complexity demands it.

| Tool | Used by | Backed by | What it does |
|---|---|---|---|
| `next_action(handle, hint?)` | every role | hybrid: Python first, masked-LLM if nuance | Returns the next instruction. May include `updates_suggested`. |
| `record_recipe(recipe)` / `record_plan(plan)` | neuron / planner | Python (validate + atomic write + snapshot) | Authors-or-updates the artifact; returns instruction-shaped errors. |
| `record_step(recipe_id, step)` | neuron | Python | Append or update a recipe step. |
| `record_step_result(recipe_id, step_id, result)` | neuron | Python | Mark inline step done with evidence. |
| `record_action_status(plan_id, action_id, status, evidence?)` | planner | Python | Update action; refuses terminal without evidence. |
| `record_user_answer(branch_or_question_id, answer)` | neuron | Python | Resolve an open question. |
| `record_decision/assumption/rejected_option(handle, ...)` | neuron, planner | Python | Append to context. |
| `pool.spawn_planner(recipe_id, step_id)` | neuron | pool microservice | Spawns planner shell, takes implicit lock on (recipe_id, step_id). |
| `pool.spawn_worker(plan_id, action_id)` | planner | pool microservice | Same shape; lock per action. |
| `broker.send(to, kind, body)` | every role | broker microservice | Route a message; `to` may be a relative ref like "my-planner". |
| `recall(query, scope?)` | every role | memory-svc (or text file in v0) | KG search OR plain-file grep; returns list[dict]. |
| `remember(fact, domain, scope?)` | every role | memory-svc (or text file in v0) | Persist a fact; curation filter applies. |

**That's 12 tools.** Less than v3. Skills carry the role-specific cognitive verbs (OCAK, drift-check, critic-review) so the MCP surface stays clean.

---

## 5. Microservices — what we build, what we defer

**Launch set (four microservices):**
1. `eda-base/claude/` — this repo. MCP tools, slash-command activators, skills, domain/shape registries, recipes/plans/actions on disk.
2. `eda-base/edp-broker/` — dumb message bus. Append-only JSONL inboxes. SSE replay. Relative-ref resolution via the spawn-tree shared with pool.
3. `eda-base/edp-pool/` — shell spawner. Owns session↔role↔handle map. Lock-by-spawn-lifetime. Crash detection + worker-liveness heartbeat that `next_action` consults to detect stale actions (P5).
4. `eda-base/edp-fsm/` — the masked-LLM microservice for `next_action`. One long-running Claude shell with `fsm-recipe-next`, `fsm-plan-next`, `fsm-stale-detect` skills loaded on demand. Periodic /clear + skill-reload to stay sharp. Routed via broker.

**Deferred (build when needed):**
- `eda-base/edp-memory-svc/` — the KG façade. Defer. Until then, `recall` and `remember` are backed by a plain-text store (`/.memory/facts.jsonl`) with a per-domain filter file. Honestly answers P6: maybe a text file is enough; if it isn't, build the KG façade later.
- `eda-base/edp-proxy/` — the Ollama proxy. Defer unless `edp-memory-svc` lands.
- `eda-base/edp-trace-viewer/` — the visualization layer. Build after the first three microservices are emitting events worth visualizing.
- `eda-base/edp-ml-capabilities/`, `edp-pattern-recognition/` — deferred indefinitely. Your point P6: do we even need them? If we accumulate ≥20 fresh closed plans and there's a clear "we keep making mistake X" signal, revisit then.

**Microservice count at launch: four.** Each in its own repo, own venv, own Dockerfile, own deploy. Independent restart.

---

## 6. The masked-LLM-microservice pattern, in detail (because it's load-bearing)

`edp-fsm` is the first instance of this pattern; documenting it concretely so we know what to copy.

### 6.1 What lives in `edp-fsm`'s repo

```
eda-base/edp-fsm/
├── pyproject.toml           # own venv
├── src/edp_fsm/
│   ├── main.py              # FastAPI: POST /next_action → routes to LLM shell via broker
│   ├── llm_session.py       # manages the long-running Claude shell: spawn, /clear, skill reload
│   └── deterministic.py     # fast-path: read JSON, walk DAG, return common-case instructions
├── .claude/commands/
│   ├── fsm-recipe-next.md   # skill: "given recipe JSON + recent events, what's next?"
│   ├── fsm-plan-next.md     # skill: "given plan JSON + worker results, what's next?"
│   └── fsm-stale-detect.md  # skill: "is this action stale? should we replan?"
└── tests/
```

### 6.2 Flow when claude/ calls `next_action(recipe_id)`

1. The MCP tool in `claude/` receives the call.
2. It tries the **deterministic path**: read recipe JSON, look at state, walk straightforward rules. If a clear instruction emerges (e.g. "state=comprehending and a branch is unresolved → ask_user"), return immediately. No LLM call.
3. If the deterministic path is undecided (e.g. multiple actions terminal at the same time, ambiguous acceptance, suspected stale), the MCP tool POSTs to `edp-fsm:9300/next_action` with the recipe snippet + recent events.
4. `edp-fsm` routes that to its long-running Claude shell via broker (the shell is registered as session_id="edp-fsm-llm"). The shell has `fsm-recipe-next` skill ready; invokes it with the payload as Skill args.
5. The skill prompts the LLM: "you are the recipe FSM. Here is the recipe JSON and the last 5 events. Return one instruction in this shape: {kind, args, rationale, updates_suggested?}."
6. The LLM emits the JSON. The skill records it via `record_fsm_decision`. The FastAPI handler returns the JSON to `claude/`.
7. Periodically (every N calls or every X minutes), the FSM session does `/clear` + reload skills to compress its own chat.

### 6.3 Why this is better than putting the logic in Python

- The "is this action stale" question is genuinely fuzzy. Plain Python would need rules for "no events in 4h" → false positives on legitimate long-running actions. LLM judgement is more flexible.
- The "should we replan" decision needs to weigh worker outputs, acceptance fit, and recipe context. Encoding that in Python ossifies it; LLM can use evolving criteria.
- Updates are deploy-able as skill-file changes. No Python redeploy for behavior tweaks.

### 6.4 Why this isn't just "ask Claude in the same shell"

- Context isolation: the FSM shell's context is dedicated to FSM reasoning. It doesn't see user-goal context, plan implementation details, or worker results other than what the snippet contains. Fewer distractions.
- Survives caller restarts: when the user's neuron shell compacts, the FSM shell keeps running with its skills loaded.
- Generalizes: the same pattern serves future smart tools (acceptance comparer, ambiguity resolver, drift judge) without each needing its own Python implementation.

---

## 7. A real walkthrough with transitions

User types `/neuron design a stateless auth method`. Trace, with state transitions called out:

| # | Actor | Action | Recipe state | Plan state |
|---|---|---|---|---|
| 1 | neuron | activates; `next_action()` returns "resume similar recipe or create fresh"; recall finds no near-match → create | (none) → created | — |
| 2 | neuron | `next_action()` returns `invoke_skill(OCAK)`; loads OCAK skill | created → comprehending | — |
| 3 | neuron | OCAK skill walks feasibility/role/actors/concerns/new-tech inline; one branch (b4 "novel vs not-yet-wired") needs user input | comprehending | — |
| 4 | neuron | `next_action()` returns `ask_user(b4)`; surfaces to user | comprehending | — |
| 5 | user | answers "design a brand-new scheme" | comprehending | — |
| 6 | neuron | `record_user_answer(b4, ...)`; `next_action()` returns `invoke_skill(OCAK)` again to finalize remaining branches + draft steps | comprehending | — |
| 7 | neuron | OCAK closes all branches, writes 3 steps to recipe: s1=research (inline), s2=poc-and-mvp (spawn_planner), s3=hitl (inline) | comprehending → planning | — |
| 8 | neuron | `next_action()` returns `run_inline(s1)` | planning → executing | — |
| 9 | neuron | does the research recall + writes summary, calls `record_step_result(s1, ...)` | executing → planning | — |
| 10 | neuron | `next_action()` returns `spawn_planner(s2)`; calls `pool.spawn_planner(recipe_id, s2)`; pool takes lock on (r, s2), spawns shell | planning → executing | (none) → drafted |
| 11 | neuron | `next_action()` returns `wait` | executing | drafted |
| 12 | planner | activates; `next_action(plan_id)` returns "draft plan: shape=modular-build, suggested actions: …"; writes plan via `record_plan` | executing | drafted → dispatching |
| 13 | planner | `next_action()` returns `dispatch_action(a1)`; `pool.spawn_worker(plan_id, a1)` | executing | dispatching |
| 14 | worker | does the work, `record_result`; pool emits worker_done to planner | executing | dispatching |
| 15 | planner | `next_action()` returns `dispatch_action(a2)` (a1's dep now met) | executing | dispatching |
| 16 | … | … (waves continue) | executing | dispatching |
| 17 | planner | last action terminal; `next_action()` returns `invoke_skill(acceptance-review)` | executing | dispatching → acceptance_review |
| 18 | planner | acceptance skill compares expected/actual for each action; all clear; calls `record_plan(terminal_status="succeeded")`; broker emits plan_closed | executing | acceptance_review → terminal |
| 19 | neuron | woken by plan_closed; `next_action()` returns `run_inline(s3)` (hitl) | executing → planning → executing | — |
| 20 | neuron | asks user "ready to ship?", records confirmation | executing | — |
| 21 | neuron | `next_action()` returns `invoke_skill(goal-keeper-check)`; verdict: all expected_outcomes met, no drift | executing → reviewing | — |
| 22 | neuron | `next_action()` returns `done`; writes final_outcome | reviewing → closed | — |

This is the level of detail I owed you in v3. Every transition has a trigger, an actor, and an effect. Nothing is "the system magically advances."

---

## 8. How your 7 answers landed

### Q1 — OCAK in the neuron's own shell vs spawned helper
**You said:** "instead of spawning shells, just add these as skills."
**Landed:** §1.1 + §3.4. OCAK is a skill the neuron invokes during the `created → comprehending` transition. No spawn. Leaf checkers (feasibility, role-clarity, etc.) are sub-skills OCAK loads. The aggregator concept dissolves into "OCAK loads each leaf skill in turn within the neuron's own shell."

### Q2 — Stale-action detection threshold
**You said:** "If this is getting complicated then just drive a generic llm behind the mask of mcp tools. … microservice in disguise."
**Landed:** §1.2 + §6. `next_action` is hybrid — fast deterministic path for common cases; routes to `edp-fsm` masked-LLM for nuance. Stale detection is one of the nuanced cases the LLM handles. Pool's worker-liveness heartbeat feeds the LLM as context.

### Q3 — `updates_suggested` policy
**You said:** "not sure what this means. does the above point 2 answer this?"
**Landed:** Yes — the masked-LLM owns the suggest-vs-auto-apply decision per situation. There's no static policy; the LLM weighs the call. If it returns `auto_applied`, the caller-side LLM is told what changed and why; if it returns `confirm_first`, the caller-side LLM gets a yes/no surface.

### Q4 — Helper-neuron lifecycle
**You said:** "helper neuron already exists as skill. can we just keep it in the same shell? the only caveat is that it pollutes the shell. the way to tackle it would be to keep the current shell's role in check via a cron like loop skill."
**Landed:** §3.4. Helpers ARE skills; the neuron's `/loop` skill periodically re-establishes role to push out skill-pollution. No separate session-neurons, no sleep/wake protocol.

### Q5 — Recipe step `kind` registry
**You said:** "dont know honestly. why force specific step types? just give it a schema to follow and some rough ideas and directions."
**Landed:** §2.1 — `kind` is a free-text string field with documentation that suggests common values (research, poc, mvp, hitl, refactor, …) but no enum. Domain modules can declare suggested kinds; the LLM is creative within that.

### Q6 — `record_*` atomicity
**You said:** "does point 2 answer help? if we disguise the mcp as llm?"
**Landed:** No — atomic writes still want to be Python (tmpfile + rename). Trivial discipline; doesn't need an LLM. Masked-LLM is reserved for *decisions*, not file I/O. So `record_*` tools are plain Python with atomicity.

### Q7 — Per-domain SLOs for ML deferred services
**You said:** "I wouldnt worry about it without knowing how it fits in my system. … do we need a knowledge graph and a machine learning module when the same can be stored on a text file?"
**Landed:** §5. KG + ML deferred. Recall/remember backed by a plain text file with per-domain filter at launch. If a text file is enough, we never build the KG. If it isn't, we add `edp-memory-svc` later behind the same MCP tool surface — callers don't change.

---

## 9. Where v4 still might be slop (self-review)

I'm going to be more critical of v4 than v3, because the bar is higher now.

### 9.1 The hybrid deterministic+LLM `next_action` may be the worst of both worlds
Two code paths to maintain (Python rules + skill prompts). Edge cases at the boundary ("the Python path returned X but the LLM would have returned Y") are real. **Mitigation:** start with deterministic-only (Python) and route to LLM *only* for cases the Python explicitly punts on (returns `Undecidable(reason)`). Boundary is sharp, not fuzzy.

### 9.2 Skills loaded into the neuron's shell will pollute context
Even with the /loop refresher. A long-running session that invokes OCAK + goal-keeper + critic + drift-check over hours accumulates prompt fragments. **Mitigation:** measure. If pollution exceeds tolerance, the masked-LLM pattern from §1.2 can move helpers behind tool boundaries (`invoke_skill_remote` instead of in-shell). I'm reserving this as a fallback, not building it now.

### 9.3 `edp-fsm` is a new microservice I just invented
It might be premature. We could build v4 *without* edp-fsm and only add it when the Python `next_action` actually proves insufficient. **Mitigation:** ship without `edp-fsm` in the first build; the `next_action` tool's call site is the same; we can swap in the masked-LLM later behind the same tool. The microservice in §5's launch set is conditional.

### 9.4 The hybrid-skill-vs-shell story has a real cost at the planner boundary
The planner runs in a separate shell. If skills work in the neuron, why not also in the planner? Then the answer to P2 (planners lose context with 30-40 actions) is "don't lose context — use a masked-LLM for the planner's bookkeeping too." But that changes the role of the planner significantly. **Open Q:** is the planner shell still worth its weight, or could the planner's bookkeeping (which actions are pending, which results returned) move into the FSM's masked-LLM? I lean: keep the planner shell, because plan authorship (choosing the shape, drafting the DAG) is creative work that benefits from a dedicated context. Dispatch+results-tracking is what could move. **Worth discussing.**

### 9.5 Free-form `kind` strings on recipe steps invite drift
"poc-and-mvp-in-one-go" is fine; "poc-pre-mvp-with-spike" is a smell. Free-form is right per your direction but should the system *suggest* canonical kinds when the LLM types something close? **Mitigation:** the OCAK skill's prompt includes a suggested-vocabulary list. The LLM is free to deviate; the suggestion biases convergence.

### 9.6 "Masked-LLM-microservice" is a clever name and might be over-applied
Once you have a hammer (one LLM behind a tool), every tool looks like a nail (every tool could have an LLM). **Mitigation:** explicit criterion — masked-LLM is justified only when (a) the logic genuinely needs LLM judgement, (b) a static rule produces too many false positives, and (c) the cost of a Claude turn is acceptable for the call frequency. Default is plain Python.

### 9.7 I'm still not specifying the failure semantics for the broker
Single message bus. If broker is down, everything stops. Same gap as v3. **Mitigation:** edp-broker uses append-only file log per recipient; restart loses no messages; consumers reconnect via `since_ts` replay. Consumers tolerate ≤ a few seconds of broker unavailability via Monitor's reconnect. I'll codify this in the broker's repo readme; not a design blocker.

### 9.8 I haven't said which microservice to build first
That's an implementation-order question. Hold for after design agreement. My instinct: `claude/` (skills + slash bodies + Python-only `next_action`) → `edp-broker/` → `edp-pool/` → (defer everything else). Walk through one full recipe with the minimum surface; add `edp-fsm` only if `next_action` proves insufficient.

### 9.9 The verbose problem-statement might itself be slop
You asked for verbose. I delivered verbose. Some of that verbosity might be filler — re-statement of the same idea in different words. **Honest assessment:** §0, §1, §2 are load-bearing because they state primitives and transitions; §6 is load-bearing because the masked-LLM pattern is new and needs explicit definition; §7 is load-bearing because it's the missing transition trace from v3. §3 and §4 are summarizing more than deriving — could be tighter. If you want shorter, those are the candidates.

---

## 10. Open questions — RESOLVED by user 2026-05-16

1. **Multi-recipe sessions.** → **OUT OF SCOPE. Will never happen.** One recipe per neuron session. No design effort spent here. The neuron's slash body can assume a single active recipe.
2. **Worker dispatch when more actions are runnable than capacity.** → **Max workers = 3.** When the planner asks the pool to spawn beyond capacity, the **pool microservice returns an error; the MCP tool propagates that error verbatim; the LLM reads it and acts** (e.g. waits, dispatches fewer, queues). **No MCP tool digests or swallows the error.** This is now a standardization principle — see §13.2.
3. **Inline step that turns out too big mid-flight → pivot to spawn_planner.** → **Yes.** The neuron's skill explicitly encourages this: if an inline step is growing beyond a single comfortable context, the skill instructs the neuron to convert the step's `execution` to `spawn_planner`, persist the recipe, and dispatch a planner. The pivot is a normal recipe edit, encouraged in the skill prose.
4. **Build `edp-fsm` at launch or defer?** → **Build at launch.** `next_action` is hybrid from day one: deterministic Python fast-path + masked-LLM (`edp-fsm`) for nuance. `edp-fsm` is in the launch microservice set, not deferred.

---

## 13. Standardization mandate (user directive 2026-05-16)

The user's directive: *"the micro-service + skills + mcp tools should all have an interface and abstract class and scale on that. the error patterns, communication protocols to be standardized."* This is binding. No component is written ad-hoc.

### 13.1 Three base contracts (abstract classes / interfaces)

Before any concrete component is built, these three ABCs are defined and unit-tested in `eda-base/claude/` (shared contract module) or a tiny shared package:

- **`Microservice` ABC** — every microservice (`edp-broker`, `edp-pool`, `edp-fsm`, future `edp-memory-svc`) implements: `health() -> HealthStatus`, `startup()/shutdown()` lifecycle, a versioned HTTP surface (`/v1/...`), structured-JSON logging with the mandatory field set, and a contract-test suite against its consumers. New microservice cannot merge without implementing the ABC + contract tests.
- **`Skill` contract** — every skill (`ocak`, `goal-keeper-check`, `critic-review`, leaf checkers, `fsm-*`) declares: a name, the host roles allowed to invoke it, its input contract (Skill args shape), its output contract (what it writes to the artifact before unloading), and a self-unload discipline. Skills never leave durable state only in chat — they persist findings to recipe/plan then unload.
- **`Tool` contract** — every MCP tool declares: input schema, output schema, the **error-propagation rule** (§13.2), whether it is Python-backed or masked-LLM-backed, and idempotency characteristics. `record_*` tools are atomic (tmpfile+rename) by contract.

### 13.2 Error-propagation rule (standardized)

**MCP tools never digest, swallow, or reinterpret a microservice error.** When `edp-pool` returns "capacity exceeded, max=3", the MCP tool returns that message to the LLM verbatim (wrapped in a stable envelope so the LLM can tell it's an upstream error, but the upstream text is preserved). The LLM is the actor that decides what to do about the error. Rationale: the old system buried errors inside tool logic and the LLM never learned to adapt; surfacing errors to the LLM is what makes the harness adaptive. This applies uniformly to every tool.

Error envelope (standard shape):
```jsonc
{ "ok": false,
  "source": "edp-pool",                 // which microservice (or "tool" for local validation)
  "code": "capacity_exceeded",          // stable machine code
  "message": "max workers = 3; 3 active; cannot spawn a 4th",  // verbatim upstream text
  "retryable": true }
```

### 13.3 Communication-protocol standardization

- All inter-shell messages use one **broker envelope**: `{ msg_id, ts, from, to, kind, body, corr_id }`. `to` accepts role names and relative refs; broker resolves. No component invents its own message shape.
- All artifact mutations go through `record_*` tools — never direct file writes by an LLM. The tool owns atomicity + snapshot + validation-as-instruction.
- All lifecycle signalling (spawned, ready, done, crashed) is a broker `kind`, not a side-channel.

### 13.4 The staged-expansion discipline

Per user directive, development expands slowly through gates. The authoritative stage tracker is **`docs/design/METHODOLOGY.md`**. No code is written until the rough design (this doc) is user-approved and HLD+LLD exist for the component being built. Each stage is user-gated; nothing skips ahead.

---

## 11. What this doc deliberately doesn't cover (and why)

- **Test strategy** — wait until we agree on the design and pick the first microservice to implement.
- **Specific Pydantic schemas for recipe/plan/action** — sketched in §2; full schema lands in the first implementation plan.
- **Trace-viewer detail** — deferred microservice; design when we actually need to visualize.
- **Migration order** — see §9.8.
- **Logging contract details** — keep the v2 sketch (structured JSON, mandatory fields); not a design blocker, codify per-service.
- **KG/ML revisits** — see §5; if a text file proves insufficient over 6 months, we revisit; until then, no design.

---

## 12. Honest closing assessment

This is a more thoughtful v4 than the others because:
1. The two primitives (skill-not-shell, masked-LLM-microservice) are concrete handles to lean on.
2. The transition tables in §2 are what I owed you and didn't deliver in v3.
3. The walkthrough in §7 makes every state change observable.
4. §9 self-criticism is harsher than prior versions because the bar is higher and I have more reason to be specific.

It still has gaps — §10 lists four real ones. And §9.9's worry that I've been verbose-for-show is real; if you find re-reads that just paraphrase, those are candidates for cut.

I expect another round of feedback. That's the loop.
