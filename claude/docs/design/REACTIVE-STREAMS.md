# Reactive streams (RxJS-style) — compatibility analysis

Status: **IMPLEMENTED** (2026-05-29). v1 (full scope) is built + tested.
This doc is both the fit assessment and the as-built reference.

As-built map:
- broker live SSE — `edp-broker/src/edp_broker/service.py` (`StreamHub`
  push notifier + `/v1/events?since_ts=&max_seconds=` live stream).
- RxPY runtime + driver — `claude/src/edp_claude/reactive/`
  (`runtime.py`: `RxRuntime` sources/operators + `compile_spec`;
  `driver.py`: NDJSON `run()`, `RealSources` threaded I/O, CLI
  `python -m edp_claude.reactive.driver`).
- `observe` MCP tool — `claude/src/edp_claude/tools/_tools.py`
  (`ObserveStream`) → returns `{subscription_id, bound_to, monitor_cmd}`.
- next_action pure-protocol — same file (`_refresh_comprehension`
  replaces inbox delivery; `check_inbox` is the pull surface; rx push is
  primary in live shells).
- crash reset — `RecordActionStatus` worklogs `action_reset` on
  `in_progress→pending` (the FSM re-dispatches).
- briefs + allowlist — `claude/.claude/commands/{neuron,agentic-plan,
  worker}.md` + `claude/.claude/settings.json`.
- tests — `test_reactive.py`, `test_observe_tool.py`, `test_crash_reset.py`,
  broker live-push test; comms tests migrated to `check_inbox` delivery.

## 1. The reframe (why this is bigger than messaging)

`next_action` was meant to be ONE thing: the **protocol pacer** — the
next legal move in the recipe/plan lifecycle (reason → outcome →
spawn → wait → close). It quietly grew a SECOND job: **delivering
messages** (`_poll_inbox` → `HANDLE_MESSAGES`), because agents don't
voluntarily check their inbox. Two unrelated jobs in one tool.

It also has a structural ceiling: it is **deterministic and happy-path
only**. It cannot react to events it can't enumerate. The clearest
case is a worker crash: `plan_fsm` (DISPATCHING, an `in_progress`
action present) returns `WAIT` — forever. There is no event that wakes
the planner to notice the crash and re-dispatch. The FSM is "dumb" to
the async/failure dimension by construction.

The fix is a **third plane**, orthogonal to the other two:

| plane | question it answers | shape | substrate |
|---|---|---|---|
| **FSM / next_action** | "what's the next legal move?" | sync, deterministic | recipe/plan state machine |
| **reactive (rx)** | "what just happened that I should react to?" | async, push | broker / worklog / plan / pool events |
| **object / CRUD** | "what is actually true now?" (+ mutate) | sync, encapsulated | recipe/plan/action/… |

Composition: an **rx** event wakes the shell → it reads **object**
truth → **next_action** gives the next legal move (or, on a failure
event, the agent reacts directly via **CRUD**: reap + reset +
re-dispatch) → act. The three compose; none replaces another.

This de-overloads `next_action` (messages move to rx; it goes back to
pure protocol driving) AND gives the agent the flexibility the FSM
lacks (it can wake on a crash, not sit in `WAIT`).

## 2. RxJS mapping

### Sources (Observables in this domain)

Each source is **control-plane** (low-rate, every emission is wake-worthy)
or **data-plane** (high-rate; must be reduced to a control signal before
any `.subscribe(wake)` — see §3a).

| source | substrate | plane | what it tells you | subscribers |
|---|---|---|---|---|
| `broker(recipient, kinds)` | broker SSE | control | inter-shell **messages** | all shells |
| `worklog(plan_id\|recipe_id)` | `tail -F` of the shared-FS jsonl | control* | progress: where the worker/planner *is* | planner, neuron |
| `plan(plan_id)` | file-watch / derived from worklog kinds | control | **action** status transitions made by workers | planner |
| `recipe(recipe_id)` | `tail -F` events.jsonl | control | **step** transitions, `outcome.met` flips | neuron |
| `pool(handle?)` | pool event endpoint (NEW) or polled-as-stream | control | session/lock **liveness** → crash | planner, neuron |
| `timer(ms)` | local | control | the heartbeat as a stream (cron floor, merged in) | all |
| `external(url, mode)` | third-party SSE/poll, pre-wrapped retry/backoff/timeout | data | satellite / market / gov-DB feeds — the resilience boundary for systems we don't own | domain workers |

\* worklog can burst (a chatty worker), so it often wants `debounceTime`/
`bufferTime` even though it's nominally control-plane.

Note: worklog/plan/recipe sources are **cheap** — workers and planners
share the repo filesystem, so `Monitor` on `tail -F .plans/<id>/worklog.jsonl`
needs no service change. The broker and pool sources need real
streaming endpoints (see §5). `external` is the only source that touches
systems outside our control, so it carries the retry/backoff/timeout
wrapper by default.

### Operators (RxJS → agent meaning)

| RxJS | agent use |
|---|---|
| `merge(...)` | wake on ANY plane: a message ∪ a progress entry ∪ a crash. The unified idle subscription. |
| `forkJoin(...)` | proceed when **all** workers in a parallel wave complete (Promise.all). The wave gate. |
| `race(event, timer)` | event-or-timeout → escalation / deadline handling. |
| `combineLatest(...)` | react to the latest (plan-state, liveness) combination. |
| `takeUntil(plan_closed\|step_done)` | auto-dispose the subscription at the lifecycle boundary. |
| `debounceTime` / `bufferTime` | coalesce bursty worklog appends into one wake (no wake-storm). |
| `distinctUntilChanged` | only wake on a real state change. |
| `retry` / `catchError` / `timeout` | SSE reconnect with `since_ts` replay; deadline on a wait. `timeout` on a *progress* stream = stall detection. |
| `switchMap` | on a `steer`/replan, cancel the in-flight subscription and switch to the new one — reactive supersession (`mark_action_superseded`). |
| `sample` / `debounceTime` / `bufferTime` | reduce a data-plane source to a control signal (§3a). |
| `scan` + `filter` | stateful thresholds, e.g. the **3-strikes** rule: `scan(count)` + `filter(>=3)` → escalate. |
| `share` / `shareReplay` | one SSE connection per source per shell, shared across composed operators; replay recent so late operators see context. |
| `filter` / `map` | shape the event stream. |
| `.subscribe(wake)` | the **only** sink: end the turn, wake on emit, deliver the emission. No mutation here. |

## 3. The lambda mechanism (and the hard boundary)

Tool discovery is flat JSON — you cannot express
`merge(a, b).pipe(filter(...), takeUntil(c)).subscribe(...)` as a
parameter schema. The composition is higher-order. So we expose the rx
runtime through a **single tool whose argument is a lambda** over an
`rx` handle:

```
observe(spec="""
  rx.merge(
    rx.broker(me, kinds=['answer','steer']),
    rx.worklog(plan_id),
    rx.pool(),                         # crash events
  ).pipe(
    rx.take_until(rx.plan_closed(plan_id)),
    rx.debounce_ms(500),
  )
""")
```

The tool compiles the lambda to a long-running rx **driver** process,
attaches a `Monitor`, ends the turn, and wakes the model on each emit.

**Hard boundary vs the retired `work_via_lambda`.** We deleted that
lambda because it was an un-encapsulated grab-bag for *state mutation*.
This lambda is categorically different: `rx` exposes **read-only event
sources + combinators + a wake sink — and NO setters**. If the agent
needs to mutate in response to an event, it wakes and then calls
`update_object` / a CRUD verb. The rx lambda never writes. This is the
invariant that keeps the reactive surface from regrowing the deleted
one. (Stated as a rule so a future change can't quietly blur it.)

## 3a. Semantics + canonical patterns (from the worked exercises)

See `REACTIVE-STREAMS-exercises.md` for the three goals these were
derived from (Antarctic monitoring / Java algo-trading / legal RAG).
Four rules are load-bearing — get them wrong and the whole subscription
misbehaves:

1. **Data-plane vs control-plane.** Every source is one or the other.
   An agent may only `subscribe(wake)` to a **control-plane** signal. A
   **data-plane** source (buoy telemetry, market ticks, gov-DB crawl)
   MUST first pass a reducing operator — `sample` / `debounceTime` /
   `bufferTime` / `scan`-to-threshold / `distinctUntilChanged` — so the
   agent wakes on *"threshold crossed"* / *"source silent"*, never on
   every tick. The rx layer's primary job at high frequency is
   **reduction**, not transport. (Without this, the first storm or tick
   burst wake-storms the shell.)

   **As-built (2026-05-29, after a live run flooded the s6 planner):**
   the internal snapshot-poll sources are reduced AT THE SOURCE so a
   naive `rx.pool()` / `rx.plan()` is safe by default —
   - `pool` / `plan` emit ONLY on change (the driver diffs the last
     snapshot; an identical poll is dropped). A `pool` wake therefore
     means a real liveness change (a crash); a `plan` wake means a real
     action-status transition.
   - `pool` takes a `scope=` handle-prefix (a plan_id or recipe_id) so a
     planner sees only ITS shells, not every recipe's locks. Briefs
     mandate `rx.pool(scope=…)`.
   - `worklog` / `recipe` default to **follow-only** (`replay=False`):
     a fresh subscription wakes only on NEW appends, not the historical
     `plan_saved` lines. `replay=True` opts into full history; catch-up
     after a gap is via `read_worklog` + the heartbeat.
   - `external` dedups consecutive identical payloads.
   The broker source is NOT reduced — each message is genuinely new and
   actionable (server-side `since_ts` already prevents re-delivery).

2. **Failure-as-value vs error-as-transport.** Domain failures — a
   worker crash, a parse error, rate-limit-exhausted, a silent buoy —
   must be `next` **values** so they ride through `merge`. Reserve a
   stream `error` for transport drops (SSE lost), handled by
   `retry`/`catchError`. If a domain failure is modeled as a stream
   `error` it terminates the whole merged subscription — one worker's
   crash would tear down the planner's entire wake stream.

3. **Completion-shaping.** Agent event sources are hot/infinite, but
   `forkJoin`/`last`/`toArray` only fire on completion. Each leg must be
   `take(1)`/`first()`/`takeUntil()` or the combinator never fires.

4. **Every wait races a deadline.** `timeout`/`race(..., timer(sla))` on
   every wait makes "silent forever" impossible by construction — this
   is the rx-layer cure for the FSM `WAIT`-forever defect.

Canonical patterns:

- **Unified idle wake:** `merge(broker(me), worklog(pid), pool())` — wake
  on a message ∪ progress ∪ a crash, all in one subscription.
- **Parallel-wave gate (never a bare forkJoin):**
  `race(forkJoin(legs.each(take(1))), timer(sla), pool_crash)`. A crashed
  or timed-out leg wins the race → reap + re-dispatch just that leg →
  re-arm the gate.
- **3-strikes / pivot-vs-patch:** `worklog(pid).filter(verify_pending)
  .scan(count).filter(>=3)` → escalate to critic / surface to user.
- **Supersession:** `broker(me, kinds=['steer']).switchMap(new_wave)` —
  cancel in-flight, switch to the re-steered work.
- **Stall detection:** `worklog(pid).timeout_no_progress(N)` → reap +
  re-dispatch a silently-hung worker.

## 4. Compatibility matrix (how it fits the existing system)

| existing piece | interaction | change required |
|---|---|---|
| **next_action** | **pure protocol pacer** (resolved §6): drives the agent through the recipe/plan lifecycle and keeps it grounded in its role — nothing else. The message-pump job moves *entirely* to rx. | drop `HANDLE_MESSAGES` from `next_action`. Message reliability now rests on rx's `since_ts` replay-on-reconnect (the broker re-delivers from the last cursor when the SSE reconnects), not a `next_action` drain. |
| **FSM (plan/recipe)** | unchanged for the happy path. Must additionally *accept* a crash-driven correction so the crash wake is actionable. | add a legal `in_progress →(reset)→ pending` re-dispatch (or a `verify`-style parked state) for a crashed action. Today = infinite `WAIT`. |
| **object / CRUD** | the mutation arm of every reactive reaction (reap session, reset action). | none — already the mutation surface. |
| **broker** | the primary hot source. | `/v1/events` must become a real long-lived stream (§5). |
| **pool** | the crash source. | needs an event/stream endpoint or a stream-the-poll wrapper (§5). |
| **cron heartbeat** | becomes just `rx.timer(...)` merged into the subscription — the robustness floor, not the primary path. | keep as fallback; reactive is first-preference. |
| **Monitor** | the wake transport: **one Monitor per `observe()` call** = one composed Observable = one Subscription. `merge`/`forkJoin` happen *inside* the RxPY driver, which emits ONE unified NDJSON line stream that the single Monitor watches. A shell may hold several subscriptions (→ several Monitors). | teardown = stop that Monitor / kill that driver (= `unsubscribe`). |

**Verdict:** complementary and additive, not a replacement. It
resolves two real defects (overloaded `next_action`; FSM crash-blindness)
and does not reintroduce the retired-lambda problem provided the
read-only-source / wake-only-sink boundary holds.

## 5. Foundational gaps (must be resolved before any junction works)

1. **broker `/v1/events` is drains-once.** `_gen()` reads the current
   backlog, yields one keep-alive, and the generator ENDS — the
   connection closes. For reactive wake it must hold the connection open
   and push messages as they arrive, honoring `since_ts` replay on
   reconnect. **This is the blocker for the messaging junctions.**
2. **pool has no event source.** Liveness is GET-poll only. A crash
   source needs either a pool event endpoint or a small "stream the
   poll" wrapper inside the rx driver.
3. **FSM crash transition.** A reactive crash wake is only useful if the
   agent can then legally re-dispatch. Add the transition (ties into the
   `verify`-state precedent: non-happy-path states are allowed).
4. **rx runtime = RxPY** (resolved §6). Don't invent operators — wrap
   RxPY behind the driver so we get the exact RxJS semantics
   (`merge/forkJoin/race/combineLatest/takeUntil/debounce/scan/retry/…`)
   for free.

## 6. Resolved decisions (2026-05-29)

- **v1 scope: FULL.** All junctions (worker⟵planner, planner⟵worker/neuron,
  neuron⟵planner, curiosity⟵user) AND all source classes
  (broker/worklog/plan/recipe/pool/timer/external) from the start — not a
  messaging-only slice.
- **next_action = pure protocol pacer.** It drives the agent through
  the recipe/plan lifecycle and keeps it grounded in its role — that's
  all. It no longer delivers messages (that moves entirely to rx push).
  This is the proven, reliable framework; we're just removing the
  message-pump overload it grew. (Supersedes the prior turn's
  "push primary / pull fallback" — message reliability is now rx's
  `since_ts` replay-on-reconnect, not a `next_action` drain.)
- **Self-pacing cron per role.** Because `next_action` will reach a quiet
  point (e.g. right after a recipe is created, or any `WAIT`), and the
  agent no longer sits in a tight poll loop, each agent shell arms a
  **self-pacing cron** that periodically re-invokes `next_action` to
  re-ground itself and keep progressing — crucially, to come back and
  **close the recipe/plan at the end** rather than going silent. This is
  the same heartbeat pattern the worker/planner briefs already use, now
  generalized to every role and paired explicitly with the pure-protocol
  `next_action`.
- **`next_action` in the allowlist for every agent role** (neuron,
  worker, planner, specialist, curiosity, …). Spawned shells run
  autonomously/headless — a permission prompt on `next_action` would
  hang them. Auto-approving it (alongside the self-pacing cron) is what
  keeps the protocol loop unblocked. The `observe()` tool and the
  self-pacing `CronCreate`/`CronList` calls belong in the same allowlist
  for the same reason.
- **rx runtime: RxPY** (see gap #4) — no hand-rolled operators.
- **Monitor: one Monitor per `observe()` call** = one Subscription. The
  RxPY driver does the `merge`/`forkJoin` internally and emits one
  unified NDJSON stream; the Monitor watches that. A shell may hold
  several subscriptions. Teardown = stop the Monitor/driver.

## 7. Tool-result contract (applies to every MCP tool, incl. `observe`)

Standing rule (carried from the object-model work): **every MCP tool
returns a structured, consumable status** — never a bare ok/void. The
caller acts on the returned value, nothing is implicit:

- `create_plan` → `{plan_id, domain, version}`; `update_object` →
  `{result}`; `record_action_status` → `{status, detail}` (e.g.
  `status="verify"` when the gate parked it).
- The reactive `observe(spec=...)` tool follows suit → returns
  `{subscription_id, bound_to: [sources...], monitor_id}` so the agent
  can later reference, inspect, or tear down the subscription, and so a
  failed compile of the lambda returns a consumable error, not a silent
  no-op.

This is what lets the rx layer compose with the rest: a subscription is
itself an addressable thing with an id, the same way a plan or an action
is.
