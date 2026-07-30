# Object model: schema + CRUD (2026-05-28)

**Status:** agreed (user sign-off 2026-05-28). Implementation in progress.
**Supersedes:** the `work_via_lambda`/`get_lambda_guide` lens grab-bag
(REDESIGN-fsm-as-guide §8 C2) — that surface had no encapsulation, a
sprawling method list, and "more info in context = more confusion." This
replaces it with a small, encapsulated **object model** the agent drives
with uniform **CRUD**.

## The two surfaces (orthogonal — do not conflate)

1. **`next_action` (independent MCP tool — STAYS).** The context-drip +
   discipline pacer. It dribbles a small, current slice of state to the
   agent over time and enforces the rails: read your messages + reply,
   progress through recipe/plan, arm your cron, don't go silent, don't
   code. It is called, never reasoned about — that is the determinism
   that keeps every shell from drifting. It is NOT part of CRUD.

2. **Object + CRUD.** The inspect/mutate surface for when an agent needs
   to look at or change something *in depth*, beyond the slice
   `next_action` dripped. Invariants are **encapsulated inside each
   object's update logic** — not in the agent's head, not in a separate
   FSM oracle. The agent composes CRUD over a clean data model; the
   objects self-validate.

Both speak ONE **highlighted vocabulary** so neuron / planner / worker /
every spawned shell shares the same map of the architecture + tools.

## The object catalog

Two classes.

### Mutate objects (full CRUD; invariants encapsulated in `update`/`create`)

| object | backend | key fields | invariants in the object |
|---|---|---|---|
| `recipe` | RecipeStore (local) | recipe_id, state, comprehension{outcomes, curiosity_cleared, user_signoff}, context, steps, final_outcome | comprehension gate (outcomes need curiosity_cleared OR user_signoff); close needs all outcomes met |
| `plan` | PlanStore (local) | plan_id, recipe_id, state, shape, goal, actions[], context | state transitions; context snapshot from recipe at create |
| `action` | nested in plan | action_id, status, depends_on, acceptance{kind,expected,verify}, **spec_ids[]**, **specializations[]**, concerns[], attempt | **status: pending→in_progress→done / failed**; d30: `done` is a **PURE WRITE** — `record_action_status` records status + `evidence` as INERT DATA, runs NO acceptance check of any kind, spawns nothing (it still refuses a `done` with no evidence). A done-claim lands *worker-done-awaiting-review*: the `needs_review` + planner-enforced worker→reviewer chain is the gate before the step closes; the `acceptance.verify` file/glob criteria travel as DATA the worker (own shell) and reviewer (fresh shell) re-run — the dual-gate model. The legacy `verify` park-state is retained ONLY as a dormant/forward-compat W7-pacing state (no record-path writer). MULTI-SPEC (2026-06-03): an action may carry **N** specs — `spec_ids[]`/`specializations[]` are canonical, the legacy scalar `spec_id`/`specialization` folds into a 1-element list at load and re-emits in the old on-disk shape while N≤1; resolved at dispatch; no producer-command verify |
| `step` | nested in recipe | step_id, status, execution, depends_on, attempt | status transitions; crash re-dispatch |
| `outcome` | nested in recipe.comprehension | id, description, verification, met, met_evidence | `met` needs substantive evidence; declaring gated by comprehension convergence |
| `neuron` | NeuronStore | neuron_id, name, category, status, base_session_id, spec_id | lifecycle (trained→pending_review→stable→…); create via specialization flow |
| `spec` | SpecStore | spec_id, neuron_id, entries[], version | versioned append |

### Inspect-only objects (read/query only — GET-backed or append-only)

User directive 2026-05-28: **REST inspection exposes GET endpoints
only.** Lifecycle mutations stay in the purpose-built action tools
(`spawn`/`release`/`reap`/`publish`), never generic update/delete.

| object | backend | read/query surface |
|---|---|---|
| `session` | pool REST (9301) | `GET /v1/sessions` (all), `GET /v1/liveness/{handle}` — filter client-side by handle-prefix/role/state |
| `lock` | pool (derived) | derived from active sessions (handle→sid); add `GET /v1/locks` |
| `message` | broker REST (9300) | `GET /v1/inbox/{recipient}`, `GET /v1/message/{id}` — **needs** cross-query `GET /v1/messages?to=&from=&kind=&since=` + recipient list for depth |
| `worklog` | local jsonl, append-only | plan: `.plans/<id>/worklog.jsonl`; recipe: `.recipes/<id>/events.jsonl`. Written by tool side-effects; agent only reads/queries. |

## The `verify` Action state (first encapsulated invariant)

`Action.status`: `pending → in_progress → verify → done` (plus `failed`).

- Worker claims done → `update(action, status="done")` moves it to
  **`verify`** (work claimed, gate pending), NOT straight to `done`.
- The deterministic gate runs; a passing gate flips `verify → done`.
- A failing/broken gate leaves the action **visibly parked in `verify`**
  — not a deadlock, not a lying `failed`, not stuck-looking
  `in_progress`. The orchestrator sees "awaiting gate," fixes a broken
  verify (`update(action, verify=…)` — allowed because it's a
  correction, the gate still actually checks), and it re-confirms.
- This keeps the no-false-done invariant WITHOUT the deadlock from the
  friction notes (#3/#4/#5/#7), and makes partial-vs-clean visible in
  any status count (fixes O4: a `verify` action ≠ a `done` one).

## Worklog vocabulary (kind + agent_role taxonomy)

Every worklog/event entry: `ts` + `kind` + `agent_role` + kind-specific
fields. The agent recognizes these as meaningful events when reading the
trail (ground truth for "is this really done / what did the worker do").

- **kinds:** `plan_saved`, `recipe_saved`, `message_sent`,
  `message_received`, `acceptance_verified`, `crash_recovery`,
  `dispatch_failed`, `lambda_reset_action`, `comprehension_signoff`.
- **agent_role:** `planner`, `executor`, `worker`, `neuron`, `lambda`.

## Shared highlighted vocabulary (taught to every shell)

System objects, marked as first-class (not prose) in `next_action`
output + all guides + the schema docs, so every shell shares one map:

`broker` · `pool` · `recipe` · `plan` · `action` · `step` · `outcome` ·
`session` · `lock` · `message` · `worklog` · `neuron` · `spec`

## CRUD verb surface

Uniform, small — replaces the lens method sprawl:
- `describe_objects(name?)` — the object schema docs (read this first).
- `read_object(type, **ids)` — one object (or None).
- `query_objects(type, where={…})` — filtered list.
- `update_object(type, **ids, patch={…})` — applies the patch through
  the object's encapsulated validation. Refused for inspect-only objects.
- `create_object(type, fields={…})` — where supported.

The existing intent tools (`create_plan`, `add_action`, `record_outcome`,
`record_action_status`, …) are CRUD operations by another name; they
remain as ergonomic aliases that delegate to the SAME encapsulated
object logic, so invariants live in one place and both surfaces agree.

## Why `command` verify broke (and the shell fix)

The `command` verify ran `subprocess.run(shell=True)` *inside the
edp-claude MCP server* (Python) → host shell = cmd.exe on Windows → a
POSIX `grep|&&` one-liner failed though the work was correct (friction
#3). Direction: **command execution belongs in a shell built for it (the
worker has a uniform `/usr/bin/bash`), not the MCP server.** Cross-
platform *artifact* checks (`file_exists`/`glob`/byte-size, pure
`pathlib`) stay in the server; arbitrary `command` checks run in the
worker (records pass/fail as evidence) or, if unavoidable in the server,
through a resolved bundled bash — never cmd.exe.

## Build increments

1. **DONE:** this doc; the `verify` Action state; `create_plan`
   echoes `plan_id`; `describe_objects` + read-side CRUD
   (`read_object`/`query_objects`) over the full catalog.
2. **DONE:** write-side CRUD (`update_object`/`create_object`)
   DELEGATING to the intent tools so invariants live in ONE place (the
   object layer is a uniform façade, not a second rule copy); the
   `work_via_lambda`/`get_lambda_guide` surface removed (collapsed into
   CRUD); inspect-only objects refuse writes; `action.verify` is
   correctable mid-dispatch.
3. **DONE:** GET-only REST discovery — broker `GET /v1/messages`
   cross-inbox query (`to`/`from`/`kind`/`since`, all optional) + pool
   `GET /v1/locks` (held locks w/ per-lock `liveness`), wired into
   `query_objects('message'|'lock')`; the command-verify shell fix —
   verify `command` checks run in a uniform bash on every host
   (`_verify_argv`, override `EDP_VERIFY_SHELL`), never cmd.exe.
4. **DONE:** `next_action`/FSM guidance overhauled to the object+CRUD
   surface in every brief (neuron/planner/worker); the lambda DSL
   removed from all briefs; shared `docs/guides/architecture-vocabulary.md`
   loaded by every shell via `get_guide` (and linked from the
   orchestrator spec); system keywords highlighted consistently.
