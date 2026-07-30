# Environment discovery — what each role knows at cold start, and how to learn more

Every spawned shell wakes up knowing almost nothing. This table is the
canonical answer to "where am I, who do I talk to, what exists around
me" — so no role string-munges handles or guesses addresses.

## The one universal move

`whoami()` — your role, your canonical inbox (`self_address` — bind
`rx.broker(me)` to it), your parent's address, and your **`lineage`**:
the recipe you ultimately work under, its neuron's address
(== `recipe_id`), your plan/planner address, your action/step id. It is
strictly YOUR lineage — there is no global agent registry, by design.

## Per-role cold start

| role | env vars you see | what you know after whoami() | learn more via |
|---|---|---|---|
| **neuron** | none (main shell) | self = your `recipe_id` inbox once a recipe exists | `resolve_recipe` (open recipes), `describe_objects` (object model), `query_objects('session', scope={'recipe_id': …})` (your live shells) |
| **planner** | `EDP_HANDLE=<recipe_id>:<step_id>`, `EDP_ROLE=planner` | self = dash `plan_id` (NOT the colon handle), parent = recipe/neuron, lineage carries step_id | `read_object('recipe', detail='digest')` to ground; `status_ping('<plan_id>:<action_id>')` per child |
| **worker** | `EDP_HANDLE=<plan_id>:<action_id>`, `EDP_ROLE=worker` | self = the colon handle, parent = planner, lineage carries recipe_id + neuron_address | `read_object('action')` (your brief + injected grounding), `read_object('recipe', detail='digest')` (the why), `get_specialist_docs` (your craft) |
| **reviewer** | `EDP_HANDLE=review-…`, `EDP_ROLE=reviewer` | consult in inbox carries target/criteria/spec_id; lineage gives the recipe for flowback events | `get_specialist_docs` (the rubric), `read_object` on the deliverable's plan |
| **curiosity** | `EDP_HANDLE=curiosity-<uuid>` | consult in inbox; its `recipe_id` is your pointer to ground truth | `read_object('recipe', detail='digest')` then full decisions on demand — never settle for the caller's framing |
| **specialist** | `EDP_HANDLE`, spawned with session id | consult in inbox | `get_specialization`, `get_guide` |

## Who talks to whom (the routing map)

- **Directed, one level**: `ask_above` / `notify_above` → your parent
  (worker→planner, planner→neuron). Mechanics of YOUR work belong here.
- **Directed, decision-class**: `ask_above(audience='neuron')` — goal /
  scope / recorded-decision / user-preference questions go STRAIGHT to
  the neuron (your planner gets an `fyi` CC). The planner is not the
  decision-maker; don't let your question die in its inbox.
- **Broadcast**: `emit_recipe_event(kind=…)` — the recipe-wide flowback
  channel the neuron subscribes to (`rx.recipe_events`). Learnings,
  discoveries, blockers, review findings, status pings.
- **Replies**: `reply(msg_id, body)` routes to the sender automatically —
  you never type an address.
- **Downward**: the neuron addresses a worker only via its planner; the
  planner reaches its worker at the colon `<plan_id>:<action_id>` inbox.

## Addressing & broker-message gotchas (folded from foreground lore, W15/a6)

- **Message `body` is a dict, not a string.** `notify_above` /
  `broker_send` take `body={...}` (a JSON object) plus a REGISTERED kind; a
  bare string fails validation (wrapped as `{__unparsedToolInput}`).
  `emit_recipe_event` takes a `summary` string instead.
- **Reach the neuron by recipe_id, never `reply()` to a display name.** A
  neuron message carries `from="neuron"` (a display name, not a live
  inbox), so `reply(msg_id)` to it dead-letters. Use `ask_above` /
  `notify_above`, which auto-address the parent — for a planner that IS
  the `<recipe_id>`, so no address is ever typed. `reply()` is fine for
  worker-bound messages whose `from` is a real colon handle.
- **A planner's live inbox is its DASH `plan_id`, not the colon
  `EDP_HANDLE`.** Messages sent to a planner's colon handle
  (`<recipe>:<step>`) dead-letter — invisible to both its rx subscription
  and `check_inbox`. If a parent "has been trying to reach you,"
  `query_objects('message', where={'from':'neuron'})` and inspect `to` for
  colon-addressed steers; you can defensively subscribe to both forms.
- **Cross-process broker kinds must live in `CORE_KINDS`.** An in-process
  `register_kind` is accepted where built but rejected at the separate
  broker process; promote any kind that crosses a process boundary to
  `CORE_KINDS` (enforced by `tests/test_v6_docs.py`).

## Cheap looks before expensive ones

`read_object(..., detail='digest')` → orient; `detail='full'` → the
complete object. `read_worklog(kinds=[…], since=…, digest=true)` →
filtered trail lines. `check_inbox(summary=true)` → scan a big inbox,
then `read_object('message', ids={'msg_id': …})` for the few that
matter. `status_ping(handle)` → one-line child check;
`inspect_worker` only when the ping looks wrong.

**Evidence lives in EDP state, not the target repo.** A worker's
`acceptance.actual_ref` (e.g. `evidence/<action>-actual.md`) is relative to
`<EDP_AGENT_HOME>/.plans/<plan_id>/evidence/`, NOT the target codebase. When
surfacing a result for read-verify, give the ABSOLUTE `.plans/.../evidence/`
path or relay the content inline (best: also `emit_recipe_event(kind=discovery|
learning)` to the flowback) — else a reader globbing the target repo finds
nothing and blocks the gate.
