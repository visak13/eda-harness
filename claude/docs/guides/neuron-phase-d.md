# Neuron — Phase D (observe plan execution)

The planner is running in a separate shell. Your job is **operational
curiosity** — actively watching the execution, NOT busy-polling. You
end your turn when there's nothing to do; messages from the planner
reach you via the `next_action` loop you're already in.

This is the phase that was missing in the post-OCAK-sweep
consolidation and what the 2026-05-21 HITLs surfaced as the gap —
this guide carries the event-router table from the old design,
restored as a first-class brief.

## What Phase D looks like

While in Phase D, `next_action(recipe)` returns one of:

- `wait` — planner is in flight, nothing to do this tick. Your
  **durable self-pacing heartbeat is already armed** (you set it up the
  instant you owned the recipe — see `neuron.md` Step 0): a recurring
  **`CronCreate`** whose prompt is the lean **"call `reconcile` then
  `next_action` and obey what it returns"**. **NEVER** re-run `/neuron
  <goal>` as the heartbeat — that re-expands the entire dispatcher
  command AND re-triggers the full `next_action` decisions dump every
  tick (the ~5-6×/idle over-firing + context-pollution bug, s17). The
  one-shot `ScheduleWakeup` is out too (fragile — a single missed re-arm
  or a context compact drops the only future wake and the loop silently
  stalls). Before you end the turn, just **idempotently re-confirm the
  cron is live** (`CronList` → `CronCreate` if missing) — do NOT arm a
  second wake. Cadence is **adaptive**: consume the `wait` args'
  `heartbeat_secs` hint — **sparse when idle/blocked** (your `Monitor`
  subscription is the real wake; the cron is only the backstop) and
  **tighter only when actively dispatching**. Then end the turn.
  Skipping the heartbeat — or handing the poll back to the user — means
  the recipe stalls: that is the babysitting failure.
- `handle_messages` — pending messages from the planner; address
  each before the FSM advances. See the router table below.
- `child_crashed` — the planner died and the automatic re-dispatch
  was already spent. `args` carries `child`, `step_id`, `attempt`.
  This needs YOUR judgement — surface to the user via
  `AskUserQuestion`: re-dispatch again (`pool_spawn_planner`)? change
  the step? abort the recipe? Do NOT silently loop. The crash is
  already recorded in the recipe worklog.
- `done` — the plan closed; the recipe is now in Phase E.

**Dispatch newly-ready steps as they unblock (DESIGN-v7 1.5.1).** With
parallel planners, a step's deps can close WHILE other planners still run.
After any reconcile that marked a step done, fire the step-frontier wave —
`next_action(handle=<recipe_id>, handle_type="recipe", all_ready=true)` —
and **spawn EVERY returned step** (`pool_spawn_planner` per instruction, in
`dispatch_order`, up to `capacity`). The wave fires from `executing` too;
you never wait for the whole recipe to drain before dispatching the next
leg. An empty wave means nothing is ready — fall back to the normal loop.

**`reconcile` advisory `RESUME_PLANNER` (DESIGN-v7 1.5.3 backstop).** A
parked planner is normally resumed by the POOL's watchdog within seconds of
a message landing. If reconcile returns `advisory: {kind: "resume_planner",
args: {handle, plan_id, signal}}`, a parked planner shows a wake signal
(unread inbox since its park, or an aged park with non-terminal actions
when the inbox wasn't checkable — the rationale says which) and the
watchdog evidently hasn't acted: call `pool_resume_planner(handle=
<args.handle>)`. Advisory only (d76), latched per signal crossing; safe to
race the watchdog (the second caller is a truthful no-op). Never
`pool_spawn_planner` a parked handle — the pool refuses it, naming the
resume route.

**Direction integrity is YOURS, and it is curiosity + signoff — not a
reviewer.** The reviewer is the PLANNER's subagent; you do not own one.
So when direction is in doubt: `comprehension_recheck` → a **curiosity
consult** when bias-risk is high, the decision is large, or the recipe is
fresh → **record the signoff**. A mutually-agreed decision may be signed
off without a consult. The FSM will never instruct you to branch a
reviewer — it cannot hand you a subagent you do not own.

Your `Monitor` subscription (armed at `neuron.md` Step 0) is the
**primary** wake — it pushes a planner reply / child-crash /
`plan_closed` the instant it lands, so you react in seconds, not on the
next tick. The durable `reconcile`+`next_action` cron is the
**backstop** that guarantees you never go dark even if no event fires.
You do NOT busy-poll in a tight loop: between events you end the turn
and let the Monitor push (or, failing that, the backstop cron) re-fire
you.

## The event router (handle_messages)

Each message in `args.messages` carries `msg_id`, `from`, `kind`,
`body`, `at`. Route by `kind`:

| Message kind | Your action |
|---|---|
| `question` | The planner is stuck and needs a decision. **Do not self-evaluate.** If it's a *decision/ambiguity* (which approach, scope, cost, location), route it through the curiosity neuron / surface to the user — don't decide alone. If it's a *domain-correctness* question, reply telling the planner to route it through its own reviewer leg (a `role="reviewer"` dispatch against the specialist's compiled doc) — the neuron convenes no reviewer of its own (owner ruling 2026-08-04). Otherwise answer directly with `reply(msg_id=<msg_id>, body={"answer": "..."})`. |
| `question` — **"no specialist for X — train one?"** | The SPECIAL case (it hung a plan once). **(1) Ask the USER** via `AskUserQuestion` — train vs proceed-without; never decide training yourself. **(2) If train:** call `train_specialist(handle=<recipe_id>)` **in this same turn** — deciding "train" does nothing until you invoke the tool. **(3) Reply to the planner** only `"hold — I'm training the specialist; I'll signal when it's stable"`. **NEVER reply "train it"** — the planner CANNOT call `train_specialist`; that reply is the deadlock that hangs the plan forever. When the SME reports stable, signal the planner to proceed. |
| `progress` | One-way notification. No response required. Read it — if it reframes the goal, `append_revision` to the recipe. Otherwise absorb the signal. |
| `observation` | The planner surfaced a discovery (new tech, prior approach, side-finding). Read it — if KG-worthy, `record_context(kind="fact", …)` it; if it reframes the goal, `append_revision`. Otherwise absorb. |
| `alert` | The planner saw something unexpected and wants attention. Decide: does it need the user? `AskUserQuestion`. Does it need a pivot? Reply with a steering decision. Does it just need acknowledgement? Reply with "noted, continue." |
| `answer` | (Rare — the planner replying to a `question` *you* asked.) Update your understanding; continue. |

## Three rules that don't change

1. **Do NOT self-evaluate claims of novelty / correctness / security.**
   Domain correctness → the planner's reviewer leg (real expertise,
   against the specialist's compiled doc). Decisions/ambiguity → the
   curiosity neuron / the user. Do not answer the question yourself even
   if you could — the answer needs an external review.

2. **Use `reply`, not addressing.** The tool looks up the original
   message via the broker; you don't need to know the planner's
   plan_id or any other address. Just `reply(msg_id=<the one from
   the message>, body={...})`.

3. **End your turn between events.** Phase D is not a busy loop. If
   `next_action` returns `wait`, end the turn — the `Monitor` push
   re-fires you the instant something lands, and the durable
   `reconcile`+`next_action` cron is the backstop. NOT `/loop`, and
   NEVER a `/neuron` re-run. Burning ticks polling without information is exactly
   what the prior HITLs surfaced as wasted context.

## Recording knowledge as it surfaces

The recipe IS the journey. If the planner's messages reveal:

- A new tech / framework discovered → `record_context(kind="fact", fact={...}, domain=...)`
- A reframed goal → `append_revision` (or update outcomes)
- A new specialist gap → load the matching specialist guide via
  `consult_specialist` (yes, even mid-execution — recipe-level
  comprehension stays alive across the recipe's lifetime).

An empty knowledge_refs at recipe close means you ignored what was
discovered.

## Transition to Phase E

When the planner reports terminal status (the FSM picks it up via
`_advance_executing` on the next `next_action`), the FSM moves the
recipe to `reviewing`, your `context.phase` flips to `e`, and the
next instruction is `done`. Load `neuron-phase-e.md`.

## Anti-patterns

- **Self-evaluating "is this correct?" claims.** Route domain
  correctness through the planner's reviewer leg, or surface to the
  user. Never self-attest.
- **Auto-invoking `/review-plan` after plan close.** The user invokes
  `/review-plan` from their main shell when ready. Not here. Not
  auto.
- **Polling in tight loops** during `wait`. End the turn. The
  heartbeat is the wake mechanism.
- **Ignoring `handle_messages`.** They are the planner's voice. If
  you skip them, the planner stalls.
- **Manufacturing status messages back to the user** ("still in
  flight" 8 times in a row). If there is no new information, end
  your turn and let the heartbeat re-fire silently. Only surface
  when something material happened.

## Flowback wakes (P4, 2026-06-10) — workers/reviewers reach you directly

Your Step-0 subscription includes `rx.recipe_events(recipe_id, kinds=
['learning','discovery','blocker','spec_learning_proposed',
'review_finding'])` — the recipe-wide broadcast channel. Route each wake:

| event kind | your move |
|---|---|
| `learning` / `discovery` | judge: map-changing -> `record_context(kind="decision", load_bearing=…)` (load_bearing if it constrains future work) or `record_context(kind="fact", …)`; else consciously drop |
| `blocker` | intervene now: answer, steer the planner, or escalate to the user |
| `spec_learning_proposed` | queue for triage (`list_spec_learnings` -> `resolve_spec_learnings`, the BATCH gate); ALWAYS triage before close |
| `review_finding` | weigh in the recipe verdict; surface fails to the user |
| `status_ping` | ambient liveness — no action unless it contradicts what you believe |
| `advisory_override` | someone edited/deleted under warning — read the audit, sanity-check the map |

Also remember the recheck nag: if `next_action`'s context carries
`comprehension_recheck` (scope growth, repeated failures, or
LOAD-BEARING DECISION DRIFT), consult curiosity in a fresh shell about
the delta and present it to the user BEFORE the next dispatch — the nag
repeats every tick until a fresh curiosity clear or signoff re-grounds
the baseline.
