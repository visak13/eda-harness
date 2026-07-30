# HLD+LLD — wake (cron-heartbeat). Change to built #2 + #4.

**§5.5 impact = this doc (before code).** Design settled in the
2026-05-19 discussion + `FINDINGS-cross-shell-liveness.md`.

## Principle
Liveness via **deterministic periodic re-check**, never LLM judgement,
never event-delivery the system can miss. A waiting parent shell is
re-invoked by a protocol-forced session cron; the FSM (disk state)
decides; the LLM only executes one `next_action` per fire.

## Roles (settled)
- **Worker** = single-shot leaf. No heartbeat. **Close-on-done**: after
  `record_action_status`, call `pool_close_self` then stop.
- **Planner** = waiting parent. On `wait`: arm/keep a `CronCreate`
  heartbeat for its handle, `/clear` (compact), end turn. Cron re-fires
  → `next_action(plan)` → act / re-wait / on terminal: `broker_send`
  `plan_closed` to `my-neuron`, `CronDelete`, `pool_close_self`.
- **Neuron** = user shell. Heartbeat = the existing `/loop` (no spawned
  cron). On `wait`: ensure `/loop` active, end turn.

## Changes
### A. `next_action` WAIT enrichment (FSM stays pure; tool enriches)
`NextAction._run`: if `instr.kind == WAIT`, set
`instr.args = {**instr.args, "handle": m.handle,
"handle_type": m.handle_type, "heartbeat_secs":
int(os.environ.get("EDP_HEARTBEAT_SECS","60"))}`. The FSM keeps
returning bare WAIT; the tool (which knows the handle + env) injects the
directive — same pattern as the existing context injection.

### B. `pool_close_self` tool + `PoolPort.release`
- `PoolPort.release(session_id) -> ToolResult` added to the ABC.
  `StubPool.release` (drop from `_alive`/locks), `HttpPool.release`
  (`POST /v1/release/{sid}` — endpoint already exists in edp-pool),
  edp-pool's own duck-typed `http_pool` gets it too.
- New tool `pool_close_self`: reads `EDP_SPAWN_SESSION_ID` from env,
  calls `ctx.pool.release(sid)`. Returns ok / verbatim upstream error.
  Registry 20→21.

### C. Activators
- `agentic-plan.md`: **(c1)** brief-from-disk fix (the chicken-and-egg:
  `next_action(plan)` precondition-fails pre-`record_plan`) — Step 1.5:
  read `.recipes/<recipe_id>/recipe.json`, find step `<step_id>` from
  `EDP_HANDLE`; that text is your plan goal; author the plan; *then*
  loop. **(c2)** heartbeat protocol: on `wait` args carry
  `{handle, handle_type, heartbeat_secs}` — `CronCreate(cron=from secs,
  prompt="call next_action(handle,handle_type) and obey it")` if not
  already armed, `/clear`, end turn. On `done`/terminal for your handle:
  `broker_send(to=<recipe_id>,kind="plan_closed",body={plan_id})` —
  recipient is the `recipe_id` (prefix of `EDP_HANDLE` before the last
  `:`), the inbox `_advance_executing` polls; verbatim match, no alias
  (the 2026-05-20 HITL wedge was `to="my-neuron"` dead-lettering) —
  then `CronDelete(job)`, `pool_close_self`, stop.

### D. Recipe reconcile = disk backstop (DESIGN-v5, 2026-05-20)
`_advance_executing` no longer trusts ONLY the broker. After the
`broker.poll(recipe_id)` fast path, if the in-flight `spawn_planner`
step has not advanced it loads `plan_id = f"{recipe_id}-{step_id}"`
from disk; `plan.state == TERMINAL` → advance step + recipe → PLANNING.
Control flow rests on durable disk state, not a miss-able event. See
`IMPACT-recipe-reconcile-fix.md`.
- `worker.md`: after `record_action_status` → `pool_close_self` → stop
  (close-on-done; no heartbeat — workers never wait).
- `neuron.md`: on `wait` → ensure the `/loop` reminder is active; end
  turn (its heartbeat is `/loop`, not a spawned cron). Never self-close.

## Load-bearing risk (SPIKE FIRST — HITL)
Does Claude Code session-`CronCreate` fire in a **pool-spawned,
non-interactive shell that has ended its turn**? Cannot be unit-tested
(needs a real spawned shell). `spike-cron-in-spawned-shell.md` is a
~30-min user probe; if it fails the mechanism changes (fallback:
pool-daemon timer + a minimal re-poke channel — re-open the fork).

## Blast radius
- claude: `_tools.py` (+wait enrichment, +`pool_close_self`),
  `ports.py`/`stubs`/`clients` (+`release`), 3 activator md. Registry
  20→21. FSM untouched (bare WAIT preserved).
- pool: `/v1/release` already exists; `http_pool` duck-copy +`release`.
- contracts/broker: untouched.
- Tests: WAIT-args, `pool_close_self`, `release` (stub+http), activator
  prose assertions. WALK-1 wait-step updated for new args.

## Verdict
Deterministic, can't-miss, no PTY injection, no new broker subsystem.
The cron-fires-post-turn assumption is gated by a spike before reliance.
Proceed to code; HITL = spike, then full re-run.
