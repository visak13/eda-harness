# SPIKE — does session-`CronCreate` fire in a pool-spawned shell?

**Status:** OPEN — must pass before the wake mechanism is relied on.
**Owner:** user (needs a real spawned shell; cannot be unit-tested).
**Time-box:** ~30 min.

## The load-bearing assumption
The wake design (HLD-LLD.md) makes a waiting planner arm a recurring
`CronCreate` job, `/clear`, and **end its turn**. The whole mechanism
depends on:

> A Claude Code **session cron**, created inside a **pool-spawned,
> non-interactive shell** (launched via `pty_launcher.py`, no human at
> the keyboard), still **fires and re-invokes that shell after the
> turn has ended**.

If this is false, a planner that arms a heartbeat and ends its turn is
**dead, not waiting** — exactly the HITL #8 deadlock, just moved.

## Procedure
1. Start broker + pool (`uv run --extra dev edp-broker` /
   `... edp-pool`).
2. Spawn a planner against a trivial recipe step whose plan has one
   worker action (the existing seed_demo flow is fine).
3. Watch the spawned planner's log
   (`<edp-debug>/...planner....log`). Confirm it:
   a. reaches a `wait` instruction,
   b. calls `CronCreate` (recurring, `heartbeat_secs`),
   c. `/clear`s and the turn ENDS (no further output).
4. Spawn/let-run the worker; it `record_action_status` → `pool_close_self`.
5. **Key observation:** within ~`heartbeat_secs`, does the planner log
   show a NEW turn — a `next_action(plan)` call it did not type — i.e.
   did the cron fire post-turn in the headless shell?

## Pass / Fail
- **PASS:** planner re-invokes itself via cron after the worker
  finished, emits `plan_closed` to `my-neuron`, `CronDelete`s,
  `pool_close_self`. → wake is sound; proceed to full /neuron re-run.
- **FAIL (cron silent in headless/ended-turn shell):** the design's
  fallback (HLD-LLD §"Load-bearing risk") activates — **pool-daemon
  timer + a minimal re-poke channel** (the pool, which already owns the
  PTY and liveness, periodically writes a one-line "call next_action"
  prompt to the waiting shell's stdin). Re-open the wake fork; do NOT
  ship the cron path.

## Why this is gated, not assumed
Per DESIGN-v5: control flow (incl. liveness/wake) must never rest on an
unverified capability. The cron-post-turn behaviour in a non-interactive
spawned shell is exactly such a capability — observed once here, then
trusted, or replaced. No code downstream relies on wake until this
records **PASS** with a log excerpt below.

## Result log
_(append: date | PASS/FAIL | log excerpt | follow-up)_

- **2026-05-20 | PASS (user observation)** | Second live HITL
  (`scratch/project-ideas/`). User: "the crons work in both neuron and
  planner. I observed it, they spawn the respective shells and start a
  cron and idle till the cron triggers." Planner debug confirms a
  CronCreate (`6f1de27b`) armed for the idle wait. Follow-up: the cron
  was *armed by LLM inference* this run (next_action never returned
  `wait` for the plan — see `IMPACT-post-hitl-sweep-2026-05-20.md` A);
  with the FSM-mirror fix landed the same day, the cron arm-on-wait
  path is now tool-forced. The mechanism itself (cron fires in a
  pool-spawned ended-turn shell) is proven; this doc closes.
