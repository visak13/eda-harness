# Architecture & Vocabulary (shared by every shell)

Load this once via `get_guide("architecture-vocabulary")`. Every shell —
**neuron**, **planner**, **worker**, and every spawned helper — speaks
this one vocabulary. The **highlighted** words below are the system
nouns; when you read them in a brief, a tool result, or a `next_action`
recap, they mean exactly what's defined here.

## The shells (who does what)

- **neuron** — the user's main shell (`/neuron <goal>`). Owns the
  **recipe** across the whole goal. ROUTER, not the brain: it does not
  comprehend, code, or verify — it routes each part to the right shell
  and routes the result back. **Its direction integrity is CURIOSITY +
  SIGNOFF** (a `consult_curiosity` when bias-risk is high, the decision is
  large, or the recipe is fresh; a mutually-agreed decision may be signed off
  without a consult). It does NOT own a reviewer.
- **planner** — `/agentic-plan`, one per **recipe step**. Owns Phase A
  (clarify → research → plan → sign-off) and Phase B (DAG-aware wave
  dispatch of **actions**). **The reviewer leg is the planner's subagent.**
- **worker** — one **action** per shell. Does the work, records status.
- helpers — **curiosity** (comprehension / per-decision interrogation),
  **specialist** (research / advice), **reviewer**. (goal-keeper and
  pattern-observer were DEAD roles — deleted by owner ruling 2026-08-04.)

> **The FSM/recipe is a MEMORY LAYER for the neuron, not a dictator.** It
> advises; the model decides. When `next_action` surfaces a prompt, that is the
> recipe REMEMBERING something for you — it is not an order, and it can never
> hand you a subagent you do not own. Where you are tempted to build a procedure
> to constrain a shell's fine-grained choices, write the sentence that makes the
> next reader think instead.

> **"REVIEWER" NAMES TWO DIFFERENT THINGS. Keep them apart — fusing them is how
> three shells in a row reasoned from a word-match instead of a capability.**
>
> 1. **The reviewer LEG — the d29/d30 objective gate, and THE PLANNER'S
>    SUBAGENT.** It is an **action** in the planner's plan, dispatched with
>    `pool_spawn_worker(...)` — a verb the planner holds. When d128 says *"the
>    reviewer is the planner's subagent"*, **this** is what it means.
>
>    **DISPATCH IT `role="reviewer"`.** This corrects a bolded instruction that
>    stood here until 2026-07-25 saying to use `role="worker"` and *never*
>    `role="reviewer"`, on the ground that a reviewer shell boots into an empty
>    inbox and reviews nothing. **That was true, and v7 P4.1 fixed it** — the
>    DISPATCHER now composes the review brief in code and sends it *before* the
>    shell exists, so a reviewer can no longer boot into silence. The composed
>    brief carries, for every reviewed action: its full description, acceptance
>    kind, expected, the first 1500 characters of its evidence, and its spec ids
>    — plus the standing re-run criteria, the spec ids, and the **grounding
>    brief path**. A failed send REFUSES the dispatch rather than launching a
>    blind reviewer.
>
>    **WHY `role="worker"` IS NOT MERELY THE WRONG FLAVOUR — IT CANNOT DO THE
>    JOB.** `record_branch_verdict` is on `_REVIEWER` and **not** on `_WORKER`
>    (`roles.py`). A worker-role review leg therefore **cannot stamp its
>    verdict at all**: the review is unrecordable, not differently-flavoured.
>    That is a capability limit, and it is the first reason the guard exists.
>    The second is d67 — the builder reviewing its own work.
>
>    Two things worth knowing before you author one.
>    **The dispatcher REFUSES `role="worker"` for any action whose id matches
>    `review` at a word boundary OR the `r<n>` convention** (`r1`, `r4`, `r12`),
>    rolls the dispatch back, and names both reasons. The `r<n>` arm was added
>    2026-07-25 after the original name-only guard **missed every review leg in
>    a live recipe**, whose planners had named them `r1`..`r4` — the convention
>    the planner guides' own worked examples teach. **`v<n>` is deliberately NOT
>    matched**: a VERIFY leg re-runs recorded acceptance commands verbatim and
>    judges nothing, so `role="worker"` is CORRECT for it (v7 P4.2).
>    The guard is still NAME-BASED, so an arbitrarily-named review leg (`a7`)
>    slips past. **Name review legs `review-something` or `r<n>`** so the
>    protection applies; a false positive is a loud refusal you fix by renaming,
>    a false negative is a shell that cannot record what it was sent to do.
>    **The composed brief carries the descriptions of the actions BEING
>    REVIEWED, not the review leg's OWN description.** Judgement that cannot be
>    reconstructed from acceptance criteria — invariants that hold across a set,
>    why one pass is insufficient, what must NOT be raised as a defect — belongs
>    in the **grounding brief** as well as the action text, because the grounding
>    brief is the half that is delivered.
 2. **`branch_reviewer` — DELETED (owner ruling 2026-08-04).** d128's absolute
>    wording (*"the neuron must never call `branch_reviewer`"*) was confirmed by
>    the owner and the verb removed outright: the reviewer LEG above is the ONE
>    review mechanism, and domain/spec review reaches it through the planner's
>    dispatch. The neuron convenes no reviewer of its own.

## The infrastructure

- **broker** — HTTP service for inter-shell **messages**. Recipient-
  addressed; cross-inbox inspection via GET `/v1/messages`.
- **pool** — HTTP service that spawns/tracks shells. Owns the truth about
  which **sessions** are alive and which **locks** are held.

## How it all connects — ONE object graph, THREE planes

Every shell is a node in one connected graph, operated through three planes:

```
recipe ──owns──▶ step ──spawns──▶ plan ──owns──▶ action ──spawns──▶ worker
  │ (neuron)              (planner)                          (session+lock)
  └─ outcomes        every shell ⇄ every shell via broker MESSAGES
                     every shell writes the WORKLOG trail
```

- **CRUD plane = state.** Inspect or change any node:
  `read_object` / `query_objects` / `create_object` / `update_object`.
  A planner reads its plan's **actions**; a neuron queries its
  **sessions** to see what's alive; anyone reaps a dead **lock**.
- **rx plane = events.** *React* to the graph changing in real time:
  a **message** arrives, an **action** status flips, a **session** dies.
  You `observe(...)` a stream and a `Monitor` wakes you the instant it
  fires — no polling. **Every shell sets up at least a message
  subscription** (see below). Full operator reference:
  `get_guide("reactive-streams")`.
- **flow plane = protocol.** `next_action` is a PURE phase pacer — it
  reads stored state and returns the next legal move; it does no IO.
  `reconcile` syncs the record to broker/pool/disk reality (a child
  closed/crashed) BEFORE you decide. The loop is **react (rx) →
  `reconcile` (sync) → `next_action` (decide)**.

CRUD = *"what is true now?"* · rx = *"what just changed?"* · `reconcile` =
*make the record match it* · `next_action` = *"my next legal move?"*

> **The cadence contract — the canonical cron prompt, the `reconcile_changed`
> threading, `wait_hint` pacing, and the Monitor re-arm rule — lives in exactly
> ONE guide: `get_guide("loop-and-heartbeat")`** (neuron + planner drive it;
> worker + curiosity keep their `check_inbox` reflex). It is not restated here.

## Event plane — subscribe FIRST (every shell)

Before you start working, **subscribe to your message plane** —
`observe(spec="rx.broker(me, kinds=[...])", ...)` and run the returned
`monitor_cmd` under the `Monitor` tool (one Monitor per `observe`). Without it a
reply/steer only reaches you on your next cron wake; with it, it lands the
instant it's sent. The heartbeat is the **backstop**, never your primary wake.

Two traps, both paid for: a spec with **no live driver is DEAF** and looks
exactly like a quiet channel, so verify the driver is live after arming and after
any restart/compaction; and a **kind-filter silently drops every directed message
whose kind you did not list** — a shell can stop hearing messages addressed to it
and nothing tells it. Composition (and richer subscriptions — worklog + scoped
pool for crash-wake): `get_guide("reactive-streams")`.

## The objects (the CRUD plane)

Inspect or mutate any node through five verbs — `describe_objects` /
`read_object` / `query_objects` (read) and `create_object` / `update_object`
(write). Invariants live INSIDE each object's update logic; you never
re-implement a rule. Start from `describe_objects()` (index) or
`describe_objects(name="<obj>")` (fields, examples, **and `ops`**).

> **NEVER read or write the recipe/plan/action/step/outcome/worklog via a
> raw file path.** Do NOT `Read`/`cat`/`Get-Content`/`ConvertFrom-Json`/
> `python json.load` a `.recipes/…` or `.plans/…` file, and do NOT improvise
> PowerShell/python to parse or build one. The on-disk location and format are
> implementation details — guessing the path (e.g. `edp-pool/.edp_state/…`) and
> hand-parsing JSON (quoting, uuids/hyphens) is the single most common
> wasted-token failure. `read_object`/`query_objects` know the path and return a
> clean dict; `create_object`/`update_object` generate correct ids and enforce the
> invariants. If the MCP tools are unreachable,
> **that is a BLOCKED state to surface — never a cue to reach for files.**

**Not every object takes every verb** — `describe_objects(name=…)` is the
source of truth, never assume "full CRUD." The edges:

| object | class | ops (what really works) |
|---|---|---|
| **recipe** | mutate | read, query, create, update |
| **plan** | mutate | read, create — **no query, no patch**; change it via its **actions**; list a recipe's plans via its **steps** |
| **action** | mutate | read, query, create, update, delete (P3 advisory) |
| **step** | mutate | read, query, create, update, delete — EDITABLE in place (P3 advisory FSM); edit/delete the step rather than piling on replacements; the audit trail keeps the honest history |
| **outcome** | mutate | read, query, create, update |
| **neuron** | mutate | read, query, create, update |
| **spec** | mutate | read, create, update (append entry); no query |
| **memory** | mutate | read, query (fuzzy recall), create — **append-only** durable facts; no update/delete; create runs a keep/reject gate |
| **session** | inspect | read, query — lifecycle is spawn/reap, not create/update |
| **lock** | inspect | read, query (`dead` liveness = phantom, reap it) |
| **message** | inspect | read, query (cross-inbox) |
| **worklog** | inspect | read, query (the durable trail) |

**Action `status` enum** = `pending | in_progress | verify | done | failed |
skipped | needs_review` — use `skipped` for an obviated/superseded action; there
is NO `cancelled` (an invalid status wedges every later plan load).

**Two of those seven are DECLARED-BUT-NEVER-WRITTEN, and knowing which matters.**
No code in `src/` ever assigns `verify` or `needs_review` — the only status the
engine writes is `in_progress` (at dispatch). `verify` is a vestige of the
framework acceptance gate that **d30 deleted** (`record_action_status` now runs
nothing), and `needs_review` is a state a PLANNER sets deliberately. Both remain
legal targets for a hand-written `update_object`, and the FSM still READS them
(a `verify` action counts as stuck) — so they are inert, not dead. Do not infer
from the enum that a gate parks work there: **nothing does.**

**Concurrency hazard — the Agent `fork`.** A `fork` subagent inherits the
parent's FULL context and may EXECUTE the parent's in-flight task, racing it on
the same files (lost-update risk). Don't launch noop/throwaway forks; for
delegated EXECUTION use a fresh general-purpose agent (no parent context), and
reserve `fork` for context-continuation, not independent work.

## next_action — the flow pacer (independent tool, always on)

`next_action` is NOT part of CRUD. It is the discipline pacer: it surfaces small
slices of state and keeps you on the **flow** rails — read your messages, progress
the recipe/plan, don't go silent, don't code when routing is your job. Call it
every loop: you pick the next move badly ~half the time when free.

But its view of **state** is ROUGH — a plan's `status` is a recorded hint, not
ground truth, and only the **pool** knows what is alive. **Flow is the FSM's;
state-truth is yours via the object surface.** Don't fight the FSM, and don't
blindly obey its state — `read_object` / `query_objects` when it matters.

## The acceptance gate — who actually runs it (d29/d30)

An **action** flows `pending → in_progress → done`. Claiming `done`
(`record_action_status`, or `update_object("action", …, patch={"status":"done"})`)
**RUNS NOTHING** (d30): no command, no file/glob check. It records status +
evidence and returns. **The framework executes no acceptance gate at all.**

Acceptance is DUAL-GATE, and both gates are SHELLS: every `acceptance.verify`
criterion (command AND file/glob alike) is run by the WORKER in its own shell and
reported as evidence, then **independently re-run by the REVIEWER leg in a fresh
shell — that re-run IS the objective gate.** A wrong criterion is corrected with
`patch={"verify":{...}}`, allowed even mid-dispatch.

**State the bound honestly, because the comfortable summary is false.** A
recorded `done` is a CLAIM and it **LANDS as `done`** — nothing parks it, and no
code moves an action to `needs_review`. So the gate is **PLANNER-ENFORCED BY
CONSTRUCTION** (every plan must carry a reviewer leg), not FSM-enforced: d29/d30
compel that leg as DISCIPLINE, and no code compels it. Therefore:

> **The gate catches when it runs. Nothing verifies that it ran.** Do not read
> "dual-gate" as "no false-done can survive" — a plan that omits the reviewer leg,
> or a reviewer that reviews nothing, produces a `done` no machinery questioned.
> The one time this nearly happened, a reviewer shell spawned into an empty inbox
> and said so instead of improvising; **honesty, not a mechanism, is what held.**

## REST inspection = GET only

The **broker** and **pool** expose GET endpoints for inspection (`/v1/sessions`,
`/v1/locks`, `/v1/messages`, `/v1/inbox/...`). **Mutations NEVER go through ad-hoc
REST** — they go through the action tools and `create_object`/`update_object`.

## Advisories — the FSM warns, it does not refuse (P3)

Mutation guards on steps/actions are ADVISORY: a risky-but-legal edit or delete
PROCEEDS and the result carries an `advisories` list (`{code, severity, message,
audit}`), with an `advisory_override` record appended to the owning trail where
the neuron's flowback subscription sees it. **Heed the warning; the choice is
yours.** HARD blocks remain only for the genuinely unsafe: mutating a terminal
recipe/plan, deleting an in_progress step/action whose shell is LIVE (steer or
`pool_reap` first), deleting a recipe's last step past comprehension. `add_action`
on an acceptance_review plan REOPENS it to dispatching.

## Tiered storage — digest inline, full text in sidecars (P2)

Long texts (decision bodies, step descriptions, `acceptance.actual` evidence, the
plan's injected-context map) live in SIDECAR files (`.recipes/<id>/context/*.md`,
`.plans/<id>/evidence/*.md`); the JSON holds a one-line digest + a `*_ref`
pointer. The stores HYDRATE on load, so every tool view still carries the complete
text — only the on-disk shape shrank. **You never resolve a ref by hand.** A
replaced decision is ARCHIVED, not deleted (`supersede_decision`): it leaves the
active index and stops being stamped into new workers, but stays in history.
`detail='digest'` for a cheap view; `detail='full'` (default) for everything.

## The flowback channel — recipe-wide broadcast (P4)

`emit_recipe_event(kind=learning|discovery|progress|blocker|status_ping|
spec_learning_proposed|review_finding, body=...)` appends to the recipe's
`events.jsonl`; the neuron subscribes via `rx.recipe_events(...)` and is woken
LIVE — **workers and reviewers reach the neuron without the planner relaying.**
recipe_id resolves from your lineage. This is the BROADCAST plane; the broker
stays the DIRECTED plane (`ask_above`/`notify_above`/`reply`).

## Lineage + routing — who answers what (P5)

`whoami().lineage` gives any shell the recipe/planner/neuron it works under (own
lineage only). **ROUTING RULE:** mechanics of YOUR work (deps, gates, environment)
→ `ask_above` to your parent; **DECISION-CLASS** questions (goal, scope, recorded
decisions, user preferences) → `ask_above(audience='neuron')`, straight to the
decision-maker (your planner gets an `fyi` CC). Planners TRIAGE: answer only what
you authored; forward decision-class questions up, **never guess.** Full table:
`get_guide("environment-discovery")`.

## The memory hierarchy — one home per knowledge class (W15)

Every piece of knowledge has ONE canonical home. Do NOT smear a fact across stores
or inflate a durable surface with ephemera.

| Knowledge class | Canonical home | Written by | Read path |
|---|---|---|---|
| Static environment + role contract | `CLAUDE.md` + `docs/guides/` | HUMAN only (hand-edited, versioned) | loaded per session (cwd) |
| Orchestrator launch discipline | `docs/guides/orchestrator-launch.md` (GUIDE) | edited directly (human-overseen) | `get_guide("orchestrator-launch")` at launch |
| Universal + specialist stack rules | protected specs (`spec-universal` + specialist specs) | specialist shell, gated (unlock + cap) | overlaid `compiled.md` / distilled at launch |
| Durable stack craft | tech specs via W3 flowback | specialist shell (W4 carve-out) | overlaid `compiled.md` |
| Recipe-scoped context | recipe decisions/assumptions (W1 typed) | `record_context` | digest + `search_context` |
| Ephemera (scheduling, acks, "user away") | `record_context(kind=note)` → WORKLOG | any role | worklog tail; NEVER in digest/epoch |
| Cross-recipe facts | scoped `.memory` (W4) | `record_context(kind=fact)` | `recall` |
| Claude auto-memory (`MEMORY.md`) | RESERVED for the human's foreground assistant | Claude Code itself | foreground only — never a harness surface |

**Retrieval — `search_context`.** `search_context(query, recipe_id=None,
kinds=[…], top_k=8)` semantically ranks a recipe's context memory so you can **ASK
the recipe instead of loading it whole.** It cosine-ranks over embeddings written
at `record_context` time into a sidecar; a legacy recipe is lazily backfilled on
first search, and it degrades to token-overlap when the embed backend is down. It
reads the sidecar and **NEVER mutates `recipe.json`.** Available to workers,
reviewers, planners and the neuron.

**Ephemera — `record_context(kind=note)`.** A note ("user away till Monday",
"acked d42") lands in the WORKLOG and is deliberately EXCLUDED from the recipe
digest and the grounding epoch. Use it for what must be visible on the trail but
must NOT become durable recipe ground.
