# Redesign: FSM-as-guide, pool-as-truth, intent-name + lambda toolset

> **RETIRED (DESIGN-v6 W2/a5, 2026-07-05).** Kept as a historical record of the
> failure analysis in §1 — NOT as live guidance. Its heartbeat prescription
> (one-shot `ScheduleWakeup`, mandatory-on-wait) is SUPERSEDED: the self-paced
> loop now arms a **durable recurring `CronCreate`** with the canonical
> reconcile-loop prompt, paced by `wait_hint` — never a one-shot wake and never
> the verbatim goal. For the live cadence contract see
> `get_guide("loop-and-heartbeat")`; for the shipped architecture see
> `docs/design/DESIGN-v6.md`. Do NOT follow the ScheduleWakeup guidance below.

**Status:** RETIRED — superseded by DESIGN-v6 (was: design awaiting sign-off).
**Date:** 2026-05-28.
**Origin:** the new-trends `/neuron` live run (debug at
`C:\Projects\Learning\new-trends\_debug\neuron-session-2026-05-28.md`)
surfaced that the FSM had become a decision-making *authority* whose
file-written state drifts from reality, and that the prior DSL rewrite
(eda-base2) was the old tool set in JSON clothes. This is the corrective
design. **Don't take shortcuts** (user directive) — fix the foundation,
not the symptoms.

This is built in **eda-base3** (a clean clone of eda-base). eda-base2
(the misbuilt see-then-act + 41-primitive DSL) is abandoned.

---

## 1. The failures this fixes (from the live transcript)

| # | Symptom | Root cause (visible in the transcript) |
|---|---|---|
| 1 | Neuron got stale FSM updates; re-surfaced already-answered curiosity messages (Turn 12, 15-16) | Two inbox read-paths: `next_action` advances an `inbox_cursor`; `check_inbox` reads everything; `reply()` doesn't consume the original → handled messages reappear. |
| 2 | Neuron stopped polling, asked the user to ping it (Turn 16) | The main `/neuron` shell has no auto-heartbeat; the neuron didn't `ScheduleWakeup` on wait → bi-directional loop died, became human-driven. |
| 3 | FSM tried to spawn a duplicate planner for a live step (Turn 15) | FSM decides from file-state (`status=in_progress` field) that drifts from the pool's actual process state. |
| 4 | `inspect_worker` returned `liveness="unknown"` (useless) | Process status is read from a file the FSM writes, not from the pool that owns the processes. |
| 5 | Repeated `ToolSearch` schema round-trips (Turns 1,5,8,12,15); planner/neuron tool-starved | Few coarse tools; no way to verify/modify arbitrary plan/recipe state in one call. |

These are not five bugs. They are **two design errors**:
- **(A) The FSM writes and owns process-state** → it drifts, and the
  FSM makes decisions on drifted state. Status must be *derived from
  the pool at read time*, not stored as an FSM-owned file field.
- **(B) The FSM commands the work** (`dispatch_action` / `wait` /
  `spawn_planner` verbs the agent obeys) → it became god, and when its
  view is wrong the agent is torn ("FSM says wait but the user asked to
  reap"). The FSM must *guide* (fetch prompts, remind discipline, push
  accurate state); the agent *decides the work*.

---

## 2. The four principles

### P1 — The FSM is a context-building GUIDE, not an authority

`next_action` stops being a verb-oracle. Its job:
- **Fetch the current phase's prompt** (so the agent loads the right
  guide without reasoning about which).
- **Remind discipline**: pace your polls, arm a wake before waiting,
  don't code, surface blocked states. (These are *reminders*, not
  commands about the work.)
- **Push accurate, pool-derived state** so a compacted/fresh session is
  re-grounded.

It does NOT say "dispatch a3" / "wait" / "spawn a planner." The agent
reads the state + reminders and decides. Determinism comes from the
agent only needing to *remember to call next_action* (zero reasoning) —
every call re-grounds and re-disciplines it. No-drift is a property of
"always re-ground," not "always obey."

### P2 — Process-status is a POOL query, never a file write

The plan file holds the action **structure** (the intent):
`action_id`, `description`, `depends_on`, `acceptance`, `spec_id`,
`executor_mode`. It does **not** hold an authoritative `status` field
that the FSM stamps.

Effective status is **derived at read time** by joining three sources:

| Effective status | Derivation |
|---|---|
| `pending` | no live worker process AND no recorded terminal outcome |
| `launched` / `in_progress` | the pool reports a **live process** for `<plan_id>:<action_id>` |
| `done` | a **recorded terminal outcome** `done` with evidence (durable; survives the process exiting) |
| `failed` | a recorded terminal outcome `failed` with a reason |
| `crashed` | a worker WAS spawned, the process is now **dead**, and there is no terminal outcome and no deliverable |

So:
- **Process-state** (alive/dead/never-spawned) = pool query. Never a
  file field.
- **Outcome-state** (done/failed with evidence) = a durable recorded
  *judgment* (worklog/plan), because it must survive the process
  exiting. This is the one thing that IS written — but it's an
  *outcome*, not a *process state*.
- `pending` is the default when neither holds.

This kills phantom locks (a failed spawn leaves no live process and no
outcome → derives `pending`, re-dispatchable), kills stale
spawn_planner (a live planner → derives `in_progress` → FSM-guide
reports "running," doesn't suggest re-spawn), and makes `inspect_worker`
meaningful (it asks the pool, which actually knows).

**Pool contract change:** the pool must expose liveness keyed by
`<plan_id>:<action_id>` (and `<recipe_id>:<step_id>` for planners)
reliably — including across pool restarts (the `knows()` distinction:
"never launched here" = `unknown`, not `dead`). The status-derivation
layer consumes this.

### P3 — Intent-name + lambda toolset (the "free-flowing" surface)

The agent expresses **intent** and the framework decomposes it — Spring
Data's `findByNasaEmployeeName` mechanism, not a fixed primitive list.

Grammar (grounded in the domain model: recipe / plan / action / worker
/ neuron / spec / outcome / step / message):

```
<verb><Quantifier?><Target><Filter?><Qualifier?>(args, lambdas)
```

- **verbs**: get / set / verify / dispatch / reap / record / consult /
  branch / close / spawn
- **targets** (domain nouns): Recipe / Plan / Action(s) / Worker /
  Outcome(s) / Step(s) / Specialist / Message(s)
- **quantifiers**: All / First / Each
- **filters**: Ready / Pending / Done / Phantom / Alive / DepSatisfied
  / Where(λ)
- **lambdas**: parameterize Where / per-item bodies —
  `dispatchActionsWhere(a => a.gap_priority == "high")`

Examples the parser decomposes (no per-name registration):
- `verifyDeliverableForAction("a3")` → run a3's acceptance check, return
  pass/fail + detail.
- `dispatchAllReadyActions(maxConcurrent=3)` → for each pending action
  whose deps are done, up to 3, atomically launch (validate → spawn →
  the pool lock IS the launch).
- `getPlanActionsWherePhantom()` → derive status (P2), return the ones
  that derive `crashed`/lock-without-process.
- `setActionDone("a3", evidence=...)` → record the terminal outcome
  (gated by the verify).

Realization in MCP (which has fixed tool names): a small set of
**evaluator** tools — `intent(name, args, lambdas)` parses the
structured name against the domain grammar and dispatches; `query(...)`
for reads; lambdas passed as serialized expressions the evaluator
interprets. The vocabulary is OPEN (any grammar-valid combination
works); the safety boundary is the parser (rejects unknown
verbs/targets) + the domain operations (each still schema/FSM-validated
— e.g. `setActionDone` runs the verify gate; `dispatch` checks deps).

This is the part with real build risk; see §6 build phases. **The
acceptance bar: the agent can verify or modify any plan/recipe/action/
pool state in one call, without reading files, without `ToolSearch`
round-trips, and without us pre-registering each operation.**

### P4 — Schema-strong write helpers stay, as helpers not authority

The agent fumbles IDs (hyphens in plan ids, etc.), so the create/update
operations keep filling scaffolding (ids, timestamps, state). But they
are operations the AGENT invokes through the intent surface — not logic
the FSM owns and uses to seize the "how to work" decision.

---

## 3. What `next_action` returns after the redesign

```jsonc
{
  "phase": "d",                    // current phase (a..e)
  "phase_guide": "neuron-phase-d", // load this; the prompt for now
  "recap": "...",                  // re-grounding summary
  "state": {                       // POOL-DERIVED, accurate
    "steps":   [{step_id, derived_status, worker_alive, ...}],
    "messages_pending": 2,         // unconsumed inbox count (one cursor)
    "outcomes": [{id, met, ...}]
  },
  "reminders": [                   // discipline, NOT work commands
    "You are about to wait — confirm your durable heartbeat cron is armed (NOT one-shot ScheduleWakeup) or you stall.",
    "Pace polls to the work; a planner build can run 15-20 min.",
    "You are the orchestrator — do not edit files / run builds."
  ]
}
```

No `kind: "dispatch_action"`. No verb to obey. The agent reads `state`
+ `reminders`, loads `phase_guide`, and decides. The phase guides
(which already exist) carry the "what good looks like for this phase"
— they become the agent's playbook, the FSM just points at the right
one and keeps the state honest.

---

## 4. The inbox fix (failure #1)

One read path, one cursor. `next_action`'s `messages_pending` and an
explicit `read_messages(consume=true)` share the same cursor; `reply()`
marks the replied-to message consumed. `check_inbox`'s "reads
everything, no cursor" path is removed (or made cursor-aware). Handled
messages never re-surface.

## 5. The heartbeat fix (failure #2)

The FSM-guide's `reminders` includes an explicit "confirm your heartbeat"
when the derived state shows in-flight work and the agent is about to yield.
(SUPERSEDED wording — the original draft made one-shot `ScheduleWakeup`
mandatory-on-wait; that is NOT the shipped mechanism. The neuron brief now arms
a durable recurring `CronCreate` with the canonical reconcile-loop prompt paced
by `wait_hint`; see `get_guide("loop-and-heartbeat")`.) The main `/neuron`
shell self-wakes; it never hands polling to the human.

---

## 6. Build phases (each independently testable; checkpoint between)

1. **Pool-as-truth state derivation (P2).** Add the status-derivation
   layer (pool liveness + recorded outcomes → effective status). Pool
   liveness keyed correctly + restart-safe. Plan schema: `status`
   becomes a *recorded outcome* field (done/failed only), process-state
   never written. `get_plan_view` + `inspect_worker` derive. *This is
   the foundation — everything else sits on accurate state.*
2. **FSM-as-guide (P1).** `next_action` returns phase + guide + derived
   state + reminders, not verbs. Phase guides become the playbooks.
   Neuron + planner briefs rewritten to "call next_action to
   re-ground, then decide," not "obey the verb."
3. **Inbox single-cursor (failure #1) + heartbeat-on-wait (#2).**
4. **Intent-name + lambda surface (P3).** The parser + domain-operation
   dispatcher + lambda evaluator. Built last because it sits on the
   accurate state model and the guide reframe.

Tests at every phase; cross-package green before moving on.

---

## 7. Open questions (need sign-off before build)

- **Q-A:** Is the §2 status-derivation table right — specifically, is
  `done`/`failed` the only thing written to the plan (everything else
  derived), and is `crashed` = "spawned-then-dead-with-no-outcome"?
- **Q-B:** §3 — is "next_action returns phase + state + reminders, no
  verb" the right shape, or do you want it to still *offer* a suggested
  next move as long as it's advisory (the agent can override)?
- **Q-C:** §6 build order — foundation (pool-truth) first, intent+lambda
  last. Agree, or do you want the intent surface earlier so you can
  feel the "free-flowing" change sooner?
- **Q-D:** §2 pool contract — the pool must own process-truth. Are you
  OK with me extending the pool's liveness API (keyed by action/step
  handle, restart-safe) as part of phase 1?

---

## 8. SIGN-OFF CORRECTIONS (2026-05-28) — these override §1-7 where they conflict

The user's answers reshaped the design. Recorded verbatim-in-spirit:

**C1 — FSM STAYS god over the FLOW (corrects P1/§3/Q-B).** "When the
agent is allowed to choose the next step, 50% it chooses bad. That's why
we play god with the FSM and keep it in check." So `next_action` KEEPS
its prompting + guide + next-step + keeping-in-check. It is NOT reduced
to "state + reminders, no verb." The determinism over FLOW stays. I was
wrong to want to strip its verbs.

**C2 — Everything ELSE moves to two new MCP tools (the real ask).**
Expose the entire data/verify/modify surface via:
  - `get_lambda_guide(topic?)` — returns the documentation for the
    public agent-facing domain API: what objects exist (recipe, plan,
    action, worker, pool, neuron, spec, message — each holds MORE than
    just status), what methods each exposes, how to write a lambda
    against them, examples, safety rules. The agent reads this BEFORE
    writing a lambda. "Get method documentation before calling the
    method and writing its lambda."
  - `work_via_lambda(code)` — evaluates the agent's lambda against live
    system state and returns the result. The lambda can read any data,
    verify anything (deliverables, pool liveness, dep graphs),
    reconcile plan-rough-status against pool-truth, modify plan/recipe
    state, reap a worker — all in ONE call, no file reads, no
    ToolSearch round-trips. This is "abstract MCP tool calling."
  (Names are the user's; refinements may be suggested but keep them
  clear. The two-tool split — guide vs work — is the contract.)

**C3 — It's about DOCUMENTATION + FRAMING, not a status refactor
(corrects P2/§2).** Don't over-focus on "remove status from the plan."
The plan's status is a fine *rough* signal; the pool is the
running-shell truth; both objects hold far more data than status. The
fix is: (a) reframe the FSM as a HELPER in the docs/prompts (not god
over truth — only over flow), (b) write excellent docs on the public
methods so the agent uses plan + pool + the rest *intelligently*, (c)
give it the lambda surface so it can verify/reconcile/modify anything
itself. The agent corrects the FSM's rough view via lambda when it
matters — the FSM doesn't need a perfect pool-derived status model. The
"FSM says wait but the user asked to reap" tension dissolves: the FSM
still guides the flow, and the agent independently reaps/verifies via
work_via_lambda without fighting it.

**C4 — Pool liveness still gets fixed, to serve the lambda surface.**
Handle-keyed, restart-safe liveness — so `work_via_lambda` can query
*accurate* pool truth. (Phase-1-ish, but framed as "feed the lambda
surface good data," not "replace plan status.")

**C5 — Build it ALL in one go.** No per-phase checkpoints. Report back
only when everything is done OR on a roadblock/dead-end.

**C6 — New ports for the eda-base3 pool/broker.** The user runs the OLD
pool/broker (9100 broker / 9200 pool) in a separate session. eda-base3
gets its OWN stack on NEW ports so they don't collide:
  - **broker → 9300**, **pool → 9301** (the "v3 stack").
  - eda-base3 claude's `.mcp.json` (EDP_BROKER_URL / EDP_POOL_URL) +
    the pool's broker_url point at the new ports. Fully independent.

**Net architecture after corrections:**
- **FLOW**: FSM/`next_action` stays in command — keeps the agent on
  rails (it picks badly when free). Determinism.
- **EVERYTHING ELSE** (inspect/verify/reconcile/modify any state):
  `get_lambda_guide` + `work_via_lambda` — the agent reads the docs,
  writes a lambda, runs it. Agency + richness, abstract tool calling.
- The two coexist: FSM owns the next move; lambda owns the data work.
  The agent uses lambda to keep the FSM's rough view honest.
