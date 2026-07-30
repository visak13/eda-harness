# Guide: neuron protocol reference

The mechanical details of being a neuron. The `neuron.md` brief
focuses on *how to think*; this is *how to operate*. Load on demand
when troubleshooting or when you've forgotten a specific mechanism.

## Instruction kinds you will get from `next_action`

| kind | what to do |
|---|---|
| `reason` | Free-reasoning phase. Generate options, hunt for the real goal, consult specialists if you recognise gaps. When ready, declare outcome via `record_outcome`. |
| `consult_specialist` | The agent named a specific gap; the FSM is suggesting consulting a specialist. You can also initiate this yourself anytime via `consult_specialist(...)`. |
| `run_audit` | Audit gate. Call `run_ocak_audit(scope, handle)`, reason through the 4 questions, then `record_audit_verdict(...)`. |
| `await_user` | The audit or your own reasoning surfaced something needing user input. Surface via `AskUserQuestion`. |
| `declare_outcome` | (legacy path — new flow emits `reason` instead.) Call `record_outcome(recipe_id, description, verification)`. |
| `declare_step` | Call `add_step(recipe_id, description, execution)`. Use `spawn_planner` for real work; `inline` only for a one-liner. |
| `ask_user` | Surface verbatim, then `record_user_answer(recipe_id, branch_id, answer)`. |
| `run_inline` | Do the step's work yourself, then `record_step_result(recipe_id, step_id, result)`. |
| `spawn_planner` | Call `pool_spawn_planner(recipe_id, step_id)`. You never track session ids. |
| `wait` | A planner is in flight. See **Heartbeat (wait pattern)** below. |
| `done` | Close the recipe. See **Closing the recipe** below. |

There is no direction-review instruction. Direction integrity is
`comprehension_recheck` → a curiosity consult (when bias-risk is high, the
decision is large, or the recipe is fresh) → the recorded signoff; a
mutually-agreed decision may be signed off without a consult. The reviewer is
the planner's subagent, never yours.

## Context block (pushed every call)

Every `next_action` reply carries a `context` block:
- `recap` — one-line summary of where the recipe is (state, outcomes,
  steps done, specialists consulted, audit status)
- `prior` — decisions, assumptions, rejected options carried forward
- `anti_patterns` — patterns to avoid for this goal class

You never fetch this. The tool pushes it. Read it every time — it is
how a fresh/compacted session re-grounds without you doing extra work.

## Pull-based re-ground (`get_recipe_digest`)

The pushed `context` block above is the cheap default. When you need to re-ground harder — a cold shell after a compaction — PULL `get_recipe_digest(recipe_id=<rid>)`: a <10k-token, code-assembled (no-LLM) packet carrying the immutable **north star**, recap, outcomes, active decisions, open steps and recent events. It stands in for the ~220k-token raw re-read of `recipe.json` + `events.jsonl`. Load-bearing decisions come back digest-form; fetch full text on demand via `read_object('recipe')`.

**The north star is the immutable goal.** `user_goal_verbatim` is fixed once set and `active_constraints` are auto-derived (never hand-written). The goal EVOLVES only through an append-only evolution log, patched with `record_context(kind='north_star_update')` — neuron-only and LIVE as of W1. Workers/planners cannot touch it; the north star is yours.

## Heartbeat (wait pattern)

When `next_action` returns `wait`, a planner is in flight and the
recipe cannot advance until its `plan_closed` lands on disk/broker.

You are the user's main shell, but you still self-pace with a **durable
recurring `CronCreate`** — NOT one-shot `ScheduleWakeup`, NOT `/loop`
(s27 Item 5 / s17 heartbeat-unification). Mechanics:
- The heartbeat is armed the instant you own the recipe (`neuron.md`
  Step 0). Its prompt is the lean **"call `reconcile` then `next_action`
  and obey what it returns"** — **NEVER** re-run `/neuron <goal>` (that
  re-expands the full dispatcher command AND re-dumps the decisions
  every tick: the ~5-6×/idle over-firing + context-pollution bug).
  One-shot `ScheduleWakeup` is out too — a single missed re-arm or a
  context compact drops the only future wake and the loop silently
  stalls.
- **On every `wait`, idempotently re-confirm the cron is live**
  (`CronList` → `CronCreate` if missing) before ending the turn — do
  NOT arm a second wake. Cadence is **adaptive**: consume the FSM's
  `heartbeat_secs` hint — sparse when idle/blocked (your `Monitor`
  subscription is the real wake; the cron is only the backstop), tighter
  only when actively dispatching. Skipping it — or handing the poll
  back to the user (the 2026-05-21 babysitting HITL) — stalls the recipe.
- End your turn. The `Monitor` push re-fires you the instant a reply /
  crash / `plan_closed` lands; the cron backstop re-calls
  `reconcile`+`next_action` even if nothing pushes.
- The deterministic FSM advances the recipe once `plan_closed` reaches
  the recipe's broker inbox, the disk backstop reconciles a terminal
  plan, OR crash-recovery fires (a dead planner is auto-re-dispatched
  once, then surfaced as `child_crashed`).
- You **never** call `pool_close_self` — that's for spawned shells
  (planner, worker), not the main shell.

## Suspend & resume the recipe (W11)

Two verbs park and un-park a recipe. Both are **neuron-only** — no other
role's toolset names them. Neither touches the FSM `state`: suspension is
orthogonal to it, and to `close_recipe`.

- `suspend_recipe(recipe_id, reason="")` — steers planners to close cleanly,
  reaps whatever overran (workers are disposable; never steered, never marked
  failed), and writes `.recipes/<recipe_id>/suspension.json`.
- `resume_recipe(recipe_id)` — reconciles the record to reality, re-grounds
  off the digest, forks the planners of in-flight steps back into life, then
  clears `suspended_at`. Safe to re-run: a step whose planner is already live
  is skipped. Workers are NOT re-forked — reconcile trues their reaped actions
  back to `pending` and `next_action` re-dispatches them fresh. **Execute the
  returned `rewire` block verbatim** to re-arm your Monitor + heartbeat.

**Two ways back in.** `/neuron resume <recipe_id>` re-grounds a *fresh* shell
from the record. To recover the original transcript instead, resume the neuron's
own session with the `<launcher> --resume <neuron_session_id>` line
`suspend_recipe` returns as `resume_command` — e.g.
`claude-personal --resume <id>`. The launcher is DERIVED from the
`CLAUDE_CONFIG_DIR` the capture hook recorded, never guessed; when the session
id or the launcher can't be resolved the command is omitted with a reason. Do
not substitute the bare `claude` binary — its default config dir holds no
transcript for that session. (There is no `eda.bat` from-anywhere wrapper in
this repo today.)

## Closing the recipe

- `done` with `partial=False` and rationale containing `SUCCEEDED` →
  `final_outcome.status="succeeded"`.
- Any other `done` (including `partial=True` for "spine drove no
  work", "outcomes not yet verified", etc.) →
  `final_outcome.status="partial"`.

Always use the intent tool:
```
close_recipe(
  recipe_id=<rid>,
  final_outcome={"status": "succeeded" | "partial",
                 "summary": "<rationale + one-line evidence>"}
)
```

You do NOT hand-author the recipe object. The tool flips state + records
the outcome.

**At recipe close (and before signalling a coordinated restart), tear down
your reactive plumbing:** `CronDelete` your heartbeat job AND **`TaskStop`
your subscription's Monitor** (the task id from when you armed the
`monitor_cmd`). Stopping the Monitor stops the driver subprocess so it leaves
no orphaned driver PID dangling across a bounce (s17 FA2-F2). You still never
`pool_close_self` (that's for spawned shells) — but you DO reap your own
Monitor + cron.

**Never report a PARTIAL close to the user as success.** Say plainly
what was and wasn't proven.

## Broker addressing (when relevant)

If you need to send a broker message (rare for the neuron — usually
the planner sends `plan_closed` to you), the broker resolves the
recipient through its **alias map** before delivery: relative refs
(`owner/my-<role>`) and the s16 absolute `colon EDP_HANDLE → dash
plan_id` planner bridge both resolve, and an unmapped **concrete**
recipient falls back to itself. So address yourself by your concrete
`recipe_id`; an **invented** literal like `"my-neuron"` matches no alias
and still dead-letters. (Because of the s16 bridge, a planner's colon
`EDP_HANDLE` is now a first-class deliverable address — sending to it no
longer dead-letters.)

## Step pivot

If an inline step grows too big for one comfortable context, edit the
step's `execution` to `spawn_planner` and dispatch a planner instead.
This pivot is expected, not a failure.

## You hold no protocol

Locks, sessions, routing, persistence, wake, lock cycles — all live
in the tools and the FSM. Your job is to think and to be the
collaborator the user needs. Theirs is to track state correctly.
