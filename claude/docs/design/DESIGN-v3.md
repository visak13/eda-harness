# DESIGN-v3 — the to-do-list-with-smart-helpers shape (2026-05-16)

**Status:** DRAFT. Replaces `DESIGN-CORE-v2.md`, `DESIGN-DATA-v2.md`, `DESIGN-ML-v2.md` (kept on disk as record).
**Inputs:** `docs/baseline/USER_PROMPT_2026-05-15.md`, `docs/baseline/AUDIT-OF-MY-OWN-WORK.md`, user's v3 framing 2026-05-16.

This doc is a single coherent design. The split-into-three was a v2 ergonomic; for v3 the model is small enough to fit in one document.

---

## 0. The mental model in plain language

The whole system is **two nested to-do lists** with **smart helpers** that hide the operational gunk.

- The **neuron** writes a **recipe** — a high-level to-do list for a user's goal. Steps look like `research → poc → mvp → hitl → mvp → done`. The recipe can revisit a step (multiple research steps are normal; the neuron decides).
- For each recipe step, the neuron asks a **planner** to materialize it as a **plan** — a DAG to-do list of concrete actions to accomplish that one step.
- Each plan action is dispatched to a **worker** — a fresh Claude shell that does the action and reports back.
- The neuron, planner, and worker all just call **`next_action()`** on their respective to-do list. The MCP tool tells them what to do next. Everything else (locks, session IDs, broker routing, snapshots) lives inside MCP tools and microservices — invisible to the LLM.

Three artifacts (recipe / plan / action). Three primary roles (neuron / planner / worker). Plus **helper neurons** — long-running Claude shells that own a slice of knowledge (e.g. `goal-keeper`, `pattern-observer`, `critic`) and wake up when their slice is relevant.

That's the whole shape. The rest of this doc is the contract details.

---

## 1. The three artifacts

### 1.1 Recipe — the neuron's to-do list

A recipe is a JSON file at `.recipes/<recipe_id>/recipe.json`. It's the durable record of "what is the user trying to do and how is it going."

```jsonc
{
  "recipe_id": "stateless-auth-2026-05-16",
  "user_goal_verbatim": "...",                  // never paraphrased
  "user_goal_distilled": "...",                 // OCAK-style summary
  "domain": "software_engineering",             // factory key — see §5
  "current_step_id": "s3",
  "steps": [
    {
      "step_id": "s1",
      "kind": "research",
      "description": "Survey stateless auth schemes; identify candidate methods",
      "status": "done",
      "depends_on": [],
      "plan_ref": "2026-05-16-survey-stateless-auth",
      "outputs": ["docs/SURVEY.md"]
    },
    {
      "step_id": "s2",
      "kind": "poc",
      "description": "Prototype the top candidate in isolation",
      "status": "done",
      "depends_on": ["s1"],
      "plan_ref": "2026-05-16-poc-cdi-hct",
      "outputs": ["src/poc/"]
    },
    {
      "step_id": "s3",
      "kind": "mvp",
      "description": "Productionize as Spring filter with tests",
      "status": "in_progress",
      "depends_on": ["s2"],
      "plan_ref": "2026-05-16-mvp-cdi-hct"
    },
    {
      "step_id": "s4",
      "kind": "hitl",
      "description": "User walkthrough + sign-off",
      "status": "pending",
      "depends_on": ["s3"]
    }
  ],
  "context": {
    "assumptions": [
      {"id": "a1", "text": "Learning POC; relaxed security gates accepted", "by": "user", "at": "..."}
    ],
    "decisions": [
      {"id": "d1", "text": "Chose CDI-HCT over PASETO/Macaroons because user wanted novel scheme", "by": "neuron+critic", "at": "..."}
    ],
    "rejected_options": [
      {"text": "Use JWT", "reason": "user explicitly excluded existing schemes"}
    ],
    "open_questions_for_user": []
  },
  "snapshots_ref": ".recipes/stateless-auth-2026-05-16/snapshots/",
  "created_at": "...", "updated_at": "...", "version": 7
}
```

Notice what's **not** in the recipe:
- No locks. No session IDs. No "which planner is currently spawned." No broker queue state. Those are invisible to the LLM that reads this file.

Notice what **is** in the recipe and is load-bearing:
- `user_goal_verbatim` — never paraphrased.
- `context` (assumptions / decisions / rejected_options / open_questions_for_user) — this is what makes the recipe pass the **`/clear` test**: a fresh LLM reading this file plus the plans it links to can continue without re-deriving anything from working memory.

### 1.2 Plan — the planner's to-do list

A plan is a JSON file at `.plans/<plan_id>.json` plus a directory `.plans/<plan_id>/` for worklog + snapshots. It materializes **one recipe step** as a DAG of concrete actions.

```jsonc
{
  "plan_id": "2026-05-16-mvp-cdi-hct",
  "recipe_id": "stateless-auth-2026-05-16",
  "recipe_step_id": "s3",
  "domain": "software_engineering",          // inherited from recipe
  "shape": "modular_build",                  // chosen by planner from {linear, modular, poc-iterate, ...}
  "goal": "Productionize CDI-HCT as Spring filter with tests",
  "actions": [
    {
      "action_id": "a1",
      "description": "Implement ManifestSigner using JDK Ed25519",
      "status": "done",
      "depends_on": [],
      "acceptance_signal": {"kind": "tests_pass", "test_targets": ["ManifestSignerTest"], "actual": "..."},
      "result_ref": ".plans/2026-05-16-mvp-cdi-hct/results/a1.json"
    },
    {
      "action_id": "a2",
      "description": "Implement ChainVerifier with replay window",
      "status": "in_progress",
      "depends_on": ["a1"],
      "acceptance_signal": {"kind": "tests_pass", "test_targets": ["ChainVerifierTest"]}
    },
    {
      "action_id": "a3",
      "description": "Wire as Spring Security filter",
      "status": "pending",
      "depends_on": ["a2"],
      "acceptance_signal": {"kind": "integration_test_pass", "test_targets": ["..."]}
    }
  ],
  "context": {
    "carried_from_recipe": ["d1"],                  // recipe decisions this plan is bound by
    "assumptions": [...],
    "rejected_approaches": [...]
  },
  "terminal_status": null,                          // "succeeded" | "superseded" | "aborted" | "partial"
  "snapshots_ref": ".plans/2026-05-16-mvp-cdi-hct/snapshots/",
  "version": 4
}
```

Same omissions as recipe: no locks, no session IDs, no scheduling state. The plan is a **to-do list with structure**, not a process record.

### 1.3 Action — the worker's task

An action is just a sub-object of a plan. The worker is spawned with `{plan_id, action_id}`, calls `next_action(plan_id)` to get the rich brief, does the work, calls `record_result(plan_id, action_id, result, evidence)`.

No worker-side artifact beyond `result_ref` (the worker's structured output).

---

## 2. The three primary roles

Each role has a **slash command body of roughly 20–30 lines**. The body's job is to *activate the role*, tell the LLM the one tool it loops on, and give a tiny convention list. It does **not** describe a protocol.

### 2.1 Neuron (the user's main shell)

```markdown
# /neuron — recipe owner

You are the recipe owner for a user goal.

## On activation
The harness's first `next_action(recipe_id)` call returns either:
- "Resume recipe R" — if you have an open recipe similar to this goal, or
- "Create recipe for: <goal>" — otherwise.
Follow that instruction.

## Outer loop
Call `next_action(recipe_id)`. Execute the instruction it returns. Repeat.
Common instructions you will get back:
- `ask_user` — surface the question verbatim, then `record_user_answer(...)`.
- `spawn_planner` — call `pool.spawn_planner(recipe_id, step_id)`. Don't worry about session IDs.
- `wait` — end your turn; the broker will event-wake you when something changes.
- `consult_helper` — `broker.send(to=helper_role, kind=consult, ...)`.
- `done` — recipe closed; exit.

## You do NOT
- Acquire locks. Track sessions. Decide when to wake helpers. Hold the phase model in your head.
```

### 2.2 Planner

```markdown
# /agentic-plan — plan owner

You are the planner for one recipe step.

## On activation
You receive `{recipe_id, step_id}`. The harness's first `next_action(plan_id)` call returns
"Create plan for: <step goal>; suggested shape: <shape>; domain: <domain>". Build the plan JSON
(actions as a DAG; each action has acceptance_signal) and call `record_plan(plan_id, plan_json)`.

## Outer loop
Call `next_action(plan_id)`. Execute. Repeat.
Common instructions:
- `dispatch_action` — `pool.spawn_worker(plan_id, action_id)`. Pool handles lock + worker spawn + monitor.
- `record_result` — a worker emitted a result; the harness already wrote it; you confirm acceptance.
- `replan` — the plan needs a structural change (new action, action split, ordering). Update plan JSON, call `record_plan(...)` again.
- `ask_neuron` — `broker.send(to=neuron, kind=question, ...)`.
- `wait`, `done` — as for the neuron.

## You do NOT
- Track which session is the worker. Acquire locks. Spawn monitors. Compute terminal status.
```

### 2.3 Worker

```markdown
# /worker — action executor

You are a worker for one action.

## On activation
You receive `{plan_id, action_id}`. Call `next_action(plan_id, action_id)` for the rich brief.

## Outer loop (degenerate: usually one cycle)
1. Read the brief.
2. Do the work using normal Claude tools (Read/Edit/Bash/etc).
3. Call `record_result(plan_id, action_id, result, evidence)`.
4. The harness emits completion to the planner via broker; you exit.

## You do NOT
- Acquire/release locks. Talk to the neuron. Update plan structure. Decide acceptance.
```

That's three slash command bodies, ~75 lines total. **Everything else is in the tools.**

---

## 3. Helper neurons — knowledge layers that step in when relevant

A helper neuron is a long-running Claude shell that *owns a slice of knowledge* and wakes up when its slice is relevant. Examples:

| Helper | Owns | Wakes on |
|---|---|---|
| `goal-keeper` | "is the active plan still aligned with the recipe's goal?" | broker event `plan_created` or `plan_replanned`; own cron every 2h while a recipe is executing |
| `pattern-observer` | "what failure patterns are recurring across recent plans?" | broker event `plan_closed`; own cron daily |
| `critic` | "is this draft about to ship something bad?" | broker event `pre_signoff` (raised by planner before plan-final ack) |

Each helper has a slash command body **of the same shape** as the primary roles: short activator + outer `next_action` loop + tiny convention list. The helper's `next_action` returns instructions like `read_state(refs)`, `emit_verdict(kind, fields)`, `sleep_until_woken`.

**Key insight:** the neuron does not need to know which helper exists. It says `broker.send(to="goal-keeper", kind=consult, plan_id=...)` when its own `next_action` returns `consult_helper(goal-keeper)`. The broker routes; if the helper is asleep, the broker tells the pool to wake it (`pool.wake(role=goal-keeper)`). The neuron is none the wiser.

---

## 4. The MCP tool surface (what the LLM sees)

This is the **complete** list of tools any of the four roles call. The full count is small on purpose.

| Tool | Used by | What it does |
|---|---|---|
| `next_action(handle)` | all roles | Returns the next instruction for this role's artifact (recipe / plan / action handle). May also return `updates_suggested` (see §4.1). |
| `record_recipe(recipe_id, recipe_json)` | neuron | Persist or update the recipe; tool validates against schema and emits instruction-shaped errors. |
| `record_plan(plan_id, plan_json)` | planner | Same for plan. |
| `record_result(plan_id, action_id, result, evidence)` | worker | Persist action result. Triggers a broker event to the planner. |
| `record_user_answer(branch_or_question_id, answer)` | neuron | Persist a user response to an open question. |
| `record_decision(handle, decision)` | neuron, planner | Append a decision to `context.decisions[]`. |
| `record_assumption(handle, assumption)` | neuron, planner | Append to `context.assumptions[]`. |
| `record_rejected_option(handle, opt)` | neuron, planner | Append. |
| `pool.spawn_planner(recipe_id, step_id)` | neuron | Pool spawns a planner shell; returns nothing useful to the LLM. The planner's first event will arrive on the neuron's broker inbox. |
| `pool.spawn_worker(plan_id, action_id)` | planner | Same shape. |
| `broker.send(to, kind, body)` | all | Send a message. `to` can be a role name (`"goal-keeper"`) or a relative reference (`"my-planner"`, `"my-neuron"`). Broker resolves. |
| `broker.poll(since_ts?)` | all | Pull messages from this shell's inbox. (Usually invoked via Monitor; rarely directly.) |
| `recall(query, scope?)` | all | Search KG / recipe-local context. Returns `list[dict]`, not a string. |

That is **13 tools**. Anything more belongs in the harness, not in the LLM's surface.

### 4.1 `next_action` semantics in one paragraph

Given a handle (recipe_id, plan_id, or (plan_id, action_id)), `next_action` reads the artifact, walks its dependency graph + status fields, and returns:

```jsonc
{
  "next": {
    "kind": "ask_user" | "spawn_planner" | "dispatch_action" | "record_result" |
            "consult_helper" | "replan" | "wait" | "done" | ...,
    "args": { ... },                 // role-specific
    "rationale": "human-readable why"
  },
  "updates_suggested": [             // optional — see below
    { "patch": {...}, "reason": "..." }
  ] | null
}
```

The `updates_suggested` field is the **"smart" part the user asked for**: when the tool notices something stale (an action `in_progress` for 4 h with no events; a recipe step whose acceptance is met but not marked done), it returns a suggested patch and asks the LLM to confirm before applying. The LLM is the safety check; the tool is the eyes.

---

## 5. The domain factory and the shape factory

Recipes have a `domain` (chosen at recipe creation from a registry). Plans have a `shape` (chosen by the planner per recipe step). Both are factory keys.

### 5.1 Domain registry
```
eda-base/claude/domains/
  software_engineering/
    success_criteria.py   # what "succeeded" means for plans in this domain
    capabilities.yaml     # which tools (Bash, Edit, npm/uv/pytest, ...) are routine
    kg_filter.py          # what facts from this domain are memory-worthy
    default_shapes.yaml   # which shape to suggest for each recipe step kind
  movie_production/
  robotic/
  geography/                # user's example
  generic/                  # fallback
```

At launch we scaffold `software_engineering` + `generic`. Others land when a real goal in that domain arrives. Domain modules are **plain Python and YAML**; no LLM authors them at runtime.

### 5.2 Shape registry
```
eda-base/claude/shapes/
  linear_build/      pipeline.md
  modular_build/     pipeline.md
  poc_iterate/       pipeline.md
  research/          pipeline.md
  creative_production/ pipeline.md
  diagnose_fix_verify/ pipeline.md
  gather_validate_submit/ pipeline.md
```

Each shape's `pipeline.md` is a planner prompt fragment — included by the planner's slash body when `shape=X`. The shapes are carried forward from the working old system (we know they work).

### 5.3 Why this matters
- **Per-domain × per-shape success criteria** (audit item 14): `success_criteria.py` in each domain decides whether a plan with `shape=linear_build` and certain action outcomes counts as `succeeded`. The terminal-status logic lives here, not as a universal taxonomy.
- **KG curation is per-domain** (audit item 9): `kg_filter.py` decides what `remember()` actually stores.

---

## 6. What's hidden inside the MCP tools and microservices

The LLM doesn't see these. They exist because somebody has to do them.

### 6.1 Inside `next_action`
- Read the artifact JSON.
- Resolve the DAG / dependency graph.
- Detect stale `in_progress` (heartbeat from pool says no worker is alive for this action → returns `replan` suggesting `failed`).
- Detect met-but-unmarked acceptance (peek at result files; suggest `mark_done`).
- Detect blocked-on-user-input (some action's `acceptance_signal` is `manual_review` and no answer recorded → returns `ask_user`).
- Decide when to transition recipe step from `in_progress` to `done` (when all its plan's actions are `done` and acceptance is met).
- Decide when the recipe is fully closed (last step's `done` event → recipe `done`).

### 6.2 Inside `pool.spawn_planner` / `pool.spawn_worker`
- Acquire a lock on the artifact handle (`recipe_id:step_id` for planner; `plan_id:action_id` for worker).
- Spawn a fresh Claude shell with the right role.
- Record `(parent_session_id, child_session_id, handle)` in the pool's mapping table.
- Wire the child's broker inbox.
- On child's exit/crash, release the lock and emit a broker event (`worker_done` or `worker_crashed`).

The lock pattern **still exists** — but only as an implementation detail of the pool. The planner never says "acquire lock" because the **act of spawning a worker IS the act of acquiring the action's lock**. Lock and worker have the same lifetime. (Audit item 1 resolved by collapsing two concepts into one.)

### 6.3 Inside `broker.send`
- Resolve relative refs (`"my-planner"`, `"my-neuron"`) using the pool's session-tree.
- Resolve role refs (`"goal-keeper"`) — if the helper is awake, route to its inbox; if asleep, call `pool.wake(role)` first.
- Append the message to the recipient's inbox JSONL.
- (Recipient's own Monitor on its inbox file wakes its shell.)

### 6.4 Snapshots & versioning (audit item 8)
- Every `record_*` tool appends a snapshot of the post-mutation artifact to `<artifact>/snapshots/v<N>.json`.
- Operator tools (CLI, not LLM-facing): `recipe diff v_a v_b`, `recipe replay at=v_n` to see what `next_action` would have returned at version N.

### 6.5 Validators-as-instruction (audit item 7)
- All schema-validation paths in `record_*` tools catch pydantic errors and re-emit:
  `{ kind: "instruction_needed_first", what, why, how }`.

---

## 7. Microservices and what they own

**At launch we need exactly four:**

| Microservice | Owns | Knows nothing about |
|---|---|---|
| `eda-base/claude/` (this repo) | MCP tool implementations; slash command bodies; recipes/plans/actions on disk; domain & shape registries. | How shells are spawned, how messages are routed, how the KG stores facts. |
| `eda-base/edp-broker/` | Append-only inbox JSONL per recipient; SSE event stream; relative-ref resolution. | Recipes, plans, business logic, KG schema. |
| `eda-base/edp-pool/` | Spawning Claude shells; mapping session_id ↔ role ↔ artifact handle; lock-by-spawn-lifetime; crash detection + worker liveness heartbeat. | Plans, recipes, KG. |
| `eda-base/edp-memory-svc/` | KG façade; per-domain ingestion filter; embeddings (via edp-proxy → ollama). | Plans, recipes, pool/broker. |

**Existing infrastructure REUSED unchanged:**
- KG container (Graphiti + FalkorDB) — running docker, fresh group_id, no migration.
- Ollama docker image — untouched.

**Reused but rewritten under eda-base/:**
- `edp-proxy` — OpenAI↔Ollama translation, retry-on-transient. Fresh code, same behaviour.

**Deferred (build when needed, not in launch set):**
- `edp-trace-viewer` — sequence-diagram visualization across broker events + tool logs. User asked for "visualize data flow." We'll build this after the first three microservices are running and producing events to visualize.
- `edp-ml-capabilities`, `edp-pattern-recognition`, `edp-problem-solving` — user said these "may not fit directly" with the MCP solution and can be revised. They're out of the v3 launch set. When we accumulate ~20 fresh plans we revisit. Until then `predict_outcome` and `recognize_pattern` are unregistered tools (not stubs — just not present).

**Microservice count:** four at launch, optionally five with the viewer. The v2 design grew this to nine. v3 cuts back to what's load-bearing.

---

## 8. Concrete data-flow walkthrough

User types `/neuron design and implement a stateless auth method`:

1. **`/neuron` slash body activates.** It calls `next_action(recipe_id=<this-session-default>)`.
2. **`next_action`** sees no recipe yet; runs the OCAK-style comprehension internally (sequentially, in the neuron's own shell — no fan-out): goal-distill, domain-detect, feasibility, role-clarity, etc. Returns one of:
   - `{ next: { kind: "ask_user", question: "Should this be a brand-new protocol or an existing-but-not-yet-wired scheme?" }}` if a comprehension branch is unresolved, OR
   - `{ next: { kind: "create_recipe", suggested_steps: [research, poc, mvp, hitl], domain: "software_engineering" }}` if all clear.
3. **Neuron** records user answers via `record_user_answer`, then calls `record_recipe(recipe_id, recipe_json)` (the LLM authors the JSON; the tool validates).
4. **Neuron** calls `next_action(recipe_id)` → `{ next: { kind: "spawn_planner", step_id: "s1" }}`.
5. **Neuron** calls `pool.spawn_planner(recipe_id, "s1")`. Pool spawns a planner shell, takes a lock on `(recipe_id, s1)`, wires the broker, returns. Neuron calls `next_action` again → `{ next: { kind: "wait", reason: "planner for s1 in progress" }}`. Neuron ends its turn; Monitor on broker inbox is armed.
6. **Planner shell** activates with `{recipe_id, step_id: "s1"}`. Calls `next_action(plan_id=…)` — gets `{ next: { kind: "create_plan", suggested_shape: "research" }}`. Authors plan JSON; calls `record_plan`.
7. **Planner** loops `next_action` → `dispatch_action(a1)` → `pool.spawn_worker(plan_id, a1)` → `wait`.
8. **Worker** activates, reads brief, does work (Bash/Edit/Read), calls `record_result`.
9. **Broker** emits `worker_done` to planner's inbox. **Planner** Monitor wakes it. `next_action` returns `record_result_confirmation` or `dispatch_action(a2)`.
10. … repeats until plan terminal-status computed by `next_action`. Planner calls `record_plan` with `terminal_status = "succeeded"`. Broker emits `plan_closed` to neuron.
11. **Neuron** wakes, `next_action` returns `spawn_planner(s2)`. And so on.
12. Eventually `next_action(recipe_id)` returns `{ next: { kind: "done", summary: "..." }}`. Neuron closes the recipe and exits the loop.

At no point in this walkthrough did the LLM in any role:
- Acquire or release a lock.
- Look up a session_id.
- Decide when to wake a helper.
- Hold a phase model in working memory.
- Manage a Monitor manually (the role's slash body declares its inbox file; harness arms the Monitor on activation).

That is the v3 shape.

---

## 9. How the 14 audit items land in v3

| # | Audit item | Where addressed |
|---|---|---|
| 1 | IoC violations | §0, §2, §4.1, §6 — LLM holds one tool (`next_action`); operational gunk hidden. |
| 2 | agentic-plan as meta-pattern | **REVISED understanding.** agentic-plan is the planner role specifically (goal → DAG-of-actions). It is NOT the meta-pattern for every role. The neuron has its own shape (recipe-driver); workers have their own (single-action). One *primitive* (`next_action`) is shared; one *implementation* per role. v2 over-abstracted. |
| 3 | Factory of plans (software/movie/robotic/geography) | §5.1 — domain registry. User added "geography" as a hint; included. |
| 4 | Recipe-as-self-sufficient-context | §1.1 + the `/clear` test. Context fields are first-class. |
| 5 | "System ≠ LLM" | §0, §6. State machine is `next_action`'s internal logic; no slash-command prose holds it. |
| 6 | Logging as visualization | `edp-trace-viewer` deferred to second wave; logging contract still mandatory at launch. |
| 7 | Validators-as-instruction | §6.5. |
| 8 | Versioned snapshots | §6.4. |
| 9 | KG curation policy | §5.1 — `kg_filter.py` per domain. Note: user said KG/ML may be revised; we keep the slot, defer the implementation. |
| 10 | Impact-analysis as primitive | Recipe step `kind=impact_analysis` is a first-class step kind, mandatory in recipes whose domain is `eda_base_meta` (changes to the system itself). |
| 11 | /loop placement (Phase B) + helper crons | The loop arms when the neuron's `next_action` returns `arm_loop_reminder` (typically after the recipe's first plan is dispatched, i.e. when the neuron will be waiting on broker events for a while). Helper neurons each run their own cron via the same `/loop` mechanism, set up at helper creation. No central scheduler. |
| 12 | Event-driven inter-comms | §6.3, §7. Broker is the single message bus. RPC only at human edges (the user shell calls MCP tools; pool's `/spawn` HTTP is also a human-edge API used by `claude`'s MCP tool). |
| 13 | Deployment independence | §7 — each microservice in its own repo, own Dockerfile, versioned endpoints. Broker uses an append-only file log, so it can restart without losing messages; consumers reconnect via `since_ts`. |
| 14 | Per-shape × per-domain success criteria | §5.3 — `success_criteria.py` per domain. |

**Audit item 2 is the one whose v3 reading differs from v2.** v2 said "agentic-plan is the meta-pattern for every role." User's v3 framing implies agentic-plan is the *plan-creation* mechanism (OCAK + difficulty/shape + domain → plan JSON). Other roles share the `next_action` primitive but they are not specializations of agentic-plan. I've corrected this above.

---

## 10. Open design questions

1. **OCAK in the neuron's own shell vs spawned helper:** v3 walkthrough puts OCAK *inside the neuron's own next_action* (a sequential function call inside the tool, no fan-out). Confirm — user said "single shell, no branched workers" which fits, but also said "phase b consults other neurons." Possibly: the neuron itself IS the OCAK shell during comprehension, then becomes the recipe driver after.
2. **Stale-action detection threshold in `next_action`:** what counts as "stale"? Worker shell crashed? Worker shell alive but action in_progress > N minutes with no events? Suggestion: rely on pool's worker-liveness heartbeat (which the pool already needs for crash detection); `next_action` reads pool state.
3. **`updates_suggested` policy:** does the LLM auto-apply suggested updates, or always confirm? Recommendation: always confirm, surface as `{kind: confirm_update, patch, reason}`. The LLM acks or rejects; tool then applies.
4. **Helper-neuron lifecycle:** when does a helper *retire* (be deleted)? Recommendation: never auto-retire; user retires via slash command. Helpers consume one Claude shell each so the bound is small.
5. **Recipe step `kind` registry:** start with `{research, poc, mvp, hitl, impact_analysis, done}` — are these enough? Or should the registry be open-ended (each domain declares its own kinds)?
6. **`record_*` atomicity:** all `record_*` tools should be filesystem-atomic (tmpfile + rename). Confirm we want this discipline from day one.
7. **Per-domain SLOs for ML deferred services:** when is `predict_outcome` worth registering? Recommend ≥20 fresh closed plans in the domain.

---

## 11. Self-review — where v3 might still be AI slop

Honest critique of my own draft. If any of these land, we revise.

### 11.1 The `next_action` god-tool risk
`next_action` is doing a lot: read artifact, walk DAG, detect stale, detect met-unmarked, decide transitions, return polymorphic instructions. There's a real risk this becomes a god-function that's hard to test and harder to evolve. **Mitigation:** the tool is the *facade*; internally it dispatches to small per-role logic modules (`recipe_next_action.py`, `plan_next_action.py`, `worker_next_action.py`) and per-state-transition rules. Public surface stays small; internals are decomposable. We should write `next_action` as a thin dispatcher with the actual logic in unit-testable functions.

### 11.2 "Suggested updates" is a slippery surface
The `updates_suggested` field is appealing but could become the place where every weird heuristic accretes ("if x and y and z, suggest renaming the action"). **Mitigation:** explicit allow-list of suggestion kinds (`mark_stale_action_failed`, `mark_met_action_done`, `propose_replan_due_to_blocker`). New kinds require a separate impact-analysis. No free-form heuristics.

### 11.3 Domain factory enumeration may be premature
We have one real domain (`software_engineering`). Scaffolding `movie_production`, `robotic`, `geography` slots invites under-specified abstractions. **Mitigation:** launch with `software_engineering` + `generic` only. The factory *contract* exists (the directory structure, the registry mechanism) but only two domains are populated. Future domains land when a real goal in that domain arrives.

### 11.4 Snapshot every record_* may be expensive at scale
Every `record_*` writes a snapshot. For a long plan with 100 actions, that's hundreds of snapshots. **Mitigation:** compact snapshots beyond v50 (keep every 10th); always keep terminal snapshots; document the policy. This is a real concern only at scale; we can ship without compaction and add it when needed.

### 11.5 Recipe step `kind` may be doing two jobs
`kind: research | poc | mvp | hitl | impact_analysis | done` is *both* a workflow primitive (what the step does) and a success-criteria hint (when it's done). Mixing these can rot. **Mitigation:** explicit: `kind` is the workflow primitive; `acceptance_signal` on the step (mirroring plan actions) is the success criteria. Add `acceptance_signal` to recipe steps in §1.1. *(Updating the schema in §1.1 in a follow-up edit.)*

### 11.6 The walkthrough hides multi-recipe / multi-neuron interaction
§8 shows one user, one recipe, one neuron. What if the user types `/neuron` for a second goal while the first recipe is still executing? The slash body has to handle "you have an existing recipe context; this is a new goal — start a fresh recipe? Or sub-plan?". I don't cover this. **Mitigation:** add a section "Multi-recipe sessions" before launch. Not a blocker for design agreement; is a blocker for implementation.

### 11.7 The "neuron-as-knowledge-layer" framing for helpers may collide with the simple recipe owner
User said *"A neuron is just a logical layer that owns some knowledge and steps in when necessary."* That suggests the primary recipe-driving "neuron" might be misnamed — it's not really a knowledge-layer, it's the recipe driver. Helpers (goal-keeper, etc.) are the knowledge-layers. **Mitigation:** consider renaming the recipe driver from "neuron" to "driver" or "navigator" and reserve "neuron" for the knowledge-layer helpers. User decides; non-trivial rename downstream. Surfacing as Q in §10.

### 11.8 No explicit failure-isolation story for the broker
The broker is the single message bus. If broker is down, everything stops. v3 implicitly relies on append-only file log + replay-on-reconnect, which the old system had. **Mitigation:** call this out explicitly in §7: broker durability is via append-only file + `since_ts` replay; broker process restart loses no messages; consumers tolerate broker brief unavailability via Monitor's reconnect.

### 11.9 The slop-meta-question
Most of v3 collapses to: "make the LLM call `next_action()` and put the smarts in the tool." That's a single architectural move. The 11-section doc may itself be slop — over-elaborating one idea. **Mitigation:** I think the elaboration is load-bearing because §1 (artifact schemas), §5 (factories), §6 (tool internals), §7 (microservice boundaries) all have to be explicit before code can be written. If user disagrees, we trim.

---

## 12. What this doc does NOT cover (deliberately deferred)
- Multi-recipe sessions (§11.6) — design before implementation.
- Helper-neuron full lifecycle (creation, sleep semantics, retirement) — sketch is in §3; details after primary roles are agreed.
- Trace-viewer detailed design — second-wave service.
- ML services — out of v3 launch set; user said revisable.
- Test strategy + contract tests — after design agreement.
- Migration order (which microservice to build first) — after design agreement; my guess is `claude` (mcp tools, slash bodies, `next_action`) → `edp-broker` → `edp-pool` → `edp-memory-svc`.

---

## 13. The v1/v2 docs still on disk

`DESIGN-CORE.md`, `DESIGN-DATA.md`, `DESIGN-ML.md`, `DESIGN-CORE-v2.md`, `DESIGN-DATA-v2.md`, `DESIGN-ML-v2.md` are kept. They are the record of how I got here. **Anything in them that conflicts with this v3 is wrong; v3 is the working design.**
