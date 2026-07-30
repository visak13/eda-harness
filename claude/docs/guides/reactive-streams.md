# Reactive streams — the event plane (how to CHOOSE a subscription)

Load via `get_guide("reactive-streams")`. The **event plane**: how you *react* to
the object graph changing in real time instead of polling. It is a **decision
map** for composing a subscription, not recipes to paste.

> **Read progressively.** This page is the lean core (mental model, FSM boundary,
> decision map, durable-rule loop). Fetch the heavy material only when you need it:
> **composing a non-trivial pipeline** → `get_guide("reactive-streams-reference")`;
> **wiring an effect or a durable rule** → `get_guide("reactive-streams-effects")`.

## The one mental model

Compose read-only event **sources** with RxPY **operators** inside a single
`observe(spec=...)` lambda. The tool returns a `monitor_cmd` you run under the
harness `Monitor` — **one Monitor per `observe` = one subscription.** Each
emission wakes you. Two kinds:

- **Sensory (default):** the sink only WAKES you + delivers the event. You then
  act through the deterministic surface (CRUD / `reconcile` / `next_action` /
  `reply`). **The lambda never mutates.**
- **Motor (opt-in, governed):** `observe(effect=<EffectSpec>)` *also* fires ONE
  allowlisted, idempotent, rate-capped, audited, **advisory-by-default** action
  per emission — through a narrow sanctioned valve, not open mutation. See the
  effects companion.

The reflex loop for a sensory wake is always **deterministic**:

```
react (an rx Monitor line wakes you)
  → reconcile (sync the record to broker/pool/disk reality — the FSM cannot
               see a plan_closed/crash until you reconcile)
  → next_action (decide the next phase off the synced record)
```

`next_action` is a PURE phase pacer — it does NOT poll the broker/pool. rx tells
you *when* to reconcile; `reconcile` makes the correct encapsulated update;
`next_action` decides. The heartbeat runs both as the BACKSTOP: cadence contract
in `get_guide("loop-and-heartbeat")`, not restated here.

> **rtk output compression — NOT ACTIVE TODAY (measured 2026-07-11; s30 owns the
> fix).** The rule, *when* it applies: with `EDP_RTK=1` Bash output is
> `rtk`-compressed to save context, and if a compressed view is insufficient you
> re-run the raw command — rtk keeps errors/failures verbatim, so the raw re-run
> recovers the dropped detail. **It does not apply now.** rtk is inert for two
> independent reasons: the `rtk` binary is not installed (the hook checks
> `shutil.which` and passes through), and pool-spawned shells pin
> `CLAUDE_CONFIG_DIR` to `.claude-pool`, whose settings carry no `hooks` block at
> all — so they would not fire the hook even if the binary existed. **Setting the
> flag today changes nothing.** Do not assume your Bash output is compressed.

## The FSM boundary — do NOT reinvent what the FSM owns

The load-bearing rule. **The FSM owns the deterministic recipe / plan / action
lifecycle** — step ordering, marking an action done, advancing the recipe,
re-dispatching a crashed child once. **Never re-derive a state transition in your
head or in an effect:** two writers of the same transition is how you get phantom
dispatch and duplicate planners.

The event plane is for **situational reflexes only** — *noticing* something
happened and routing it to the right deterministic op:

| the event plane is FOR | the FSM owns (don't reinvent) |
|---|---|
| noticing a `plan_closed` / crash / new message *as it happens* | what the resulting recipe/plan transition IS |
| coalescing/counting signals to decide *when* to act (e.g. 3-strikes) | marking actions done, advancing steps, dispatching |
| advisory nudges (observation / notify) into a live shell | committing outcomes, gating comprehension |

So: **observe (rx, notice) → reconcile (FSM syncs) → next_action (FSM decides)**,
or **observe → a single direct CRUD verb**. Never a parallel state machine.

## The decision map — NEED → SOURCE / OPERATOR / EFFECT

Compose a subscription by answering three questions in order.

### 1. What do I need to wake on? → pick a SOURCE (and a combinator)

| your need | source |
|---|---|
| messages sent to me (answer / steer / question / done …) | `rx.broker(me, kinds=[...])` |
| a plan's action statuses changed | `rx.plan(plan_id)` (emits on change only) |
| a worker's worklog entries (progress / done) | `rx.worklog(plan_id=… / recipe_id=…)` (follow-only; `replay=True` for history) |
| worker/reviewer learnings, blockers, review findings — the FLOWBACK broadcast (worker→neuron, no planner relay) | `rx.recipe_events(recipe_id, kinds=['learning','discovery','blocker','spec_learning_proposed','review_finding'])` |
| recipe-level events | `rx.recipe(recipe_id)` |
| a child crashed / lock liveness | `rx.pool(scope=<plan_id\|recipe_id>)` — **always `scope=`** |
| a child **vanished without recording** (the silent stall — see below) | `rx.orphaned(plan_id=…)` / `rx.orphaned(recipe_id=…)` — **ARM THIS ALONE. NEVER `rx.merge` IT WITH YOUR INBOX.** See ONE FATE PER SUBSCRIPTION below; two planners have now merged it anyway, the second having read that passage first. Give it its own `observe()` + Monitor and a `min_interval_ms` floor. |
| a periodic tick / a deadline | `rx.timer(ms)` / `rx.interval(ms)` |
| a third-party feed, or a UI/domain event | `rx.external(url, …)` / `rx.topic(name)` |

| your need across sources | combinator |
|---|---|
| wake on ANY of several | `rx.merge(*srcs)` |
| fire only when ALL complete | `rx.fork_join(*srcs)` — each leg `take(1)`/`take_until` |
| first to emit wins (event-OR-timeout) | `rx.race(*srcs)` |
| latest-of-each / in-order / pairwise | `rx.combine_latest` / `rx.concat` / `rx.zip` |

### 2. How do I shape it so it's quiet + precise? → pick OPERATORS (`.pipe(...)`)

| your need | operator |
|---|---|
| keep only some events | `rx.filter(fn)` |
| reshape the payload | `rx.map(fn)` |
| it's too chatty / bursty | `rx.sample_ms` / `rx.buffer_ms` / `rx.debounce_ms` — **apply to the CHATTY SOURCE, never to a merged stream** (see the quiet rules) |
| drop unchanged repeats | `rx.distinct_until_changed(key?)` |
| count up to a threshold (e.g. 3-strikes) | `rx.scan(fn, seed)` + `rx.filter` |
| treat silence as a stall/deadline | `rx.timeout_ms(n)` |
| supersede an in-flight unit | `rx.switch_map(fn)` |
| combine with the latest of other streams | `rx.with_latest_from(*others)` |
| stop the leg at a boundary | `rx.take(n)` / `rx.take_until(other)` |
| survive a transport drop | `rx.retry(n?)` / `rx.catch(handler)` |

**The quiet rules** (a wake should always mean *something real happened*):
`pool`/`plan` are already reduced at the source — a wake = a real transition.
A *data-plane* source (`external`, raw high-rate feeds) MUST pass a reducing op
first (`sample`/`debounce`/`buffer`/`distinct_until_changed`/`scan`-to-threshold)
**on that SOURCE, before any `rx.merge`.** Always `scope=` the pool.
Completion-shape `fork_join` legs or they never fire. Race every long wait against
an `rx.timer` deadline.

> **NEVER reduce a MERGED stream — that is how you starve the event you cannot
> afford to miss.** Reducing operators are per-source tools. Put `debounce` (or
> any wait-for-quiet operator) in front of a merged pipeline that has a poller in
> it and the quiet NEVER COMES: the poller resets the window forever and wins the
> collapse, so a worker's once-only `done` is not delayed — **it is DISCARDED**,
> and an empty poll snapshot is delivered in its place. Swapping debounce for
> throttle does not save you; on a merged stream the poller still wins. This
> shipped, and a planner went deaf to its worker for four minutes with a live
> Monitor and a correct filter. **Levels (pool/plan snapshots — newest supersedes)
> can be dropped safely. Edges (a `done`, a message) cannot.**

> **THE COROLLARY, and it cost a stall on 2026-07-25: an EDGE that is only
> represented as a LEVEL is invisible.** A worker that finishes and exits
> WITHOUT recording status produces no crash, no message, no `dead` liveness —
> its row just stops appearing in the pool snapshot. **A level that stops
> arriving looks exactly like a quiet channel**, so the most important event on
> the plane was the one event structurally incapable of being delivered. The
> planner waited on something that could no longer happen; the finished work sat
> on disk untouched. You cannot subscribe to the absence of a thing — so the
> fix is a source that JOINS state against liveness and emits the *derived*
> condition as a real edge: **`rx.orphaned`**. When you find yourself reasoning
> "it must still be working, nothing told me otherwise," check whether anything
> *could* have told you.

### 3. What happens on each emission? → pick a SINK

| your need | sink |
|---|---|
| just wake me; I'll act via reconcile/CRUD | `observe(spec=…)` — **no effect** (sensory; the default, safest) |
| auto-emit an advisory per event (a nudge) | `observe(spec=…, effect=…)` with a **default-ON** action (`broker_send` observation / `notify_above`) |
| make that reflex survive a restart | `register_rule(name, spec, effect, owner)` (durable) |
| auto-mutate FSM state | **Tier-2 — DARK / not available.** Don't. Deep judgment belongs in a bespoke source the rule subscribes to (see "honest limit") |

A worked example of all three steps composed (planner / neuron / parallel-wave /
3-strikes) lives in `get_guide("reactive-streams-reference")` — read it when you
compose, don't memorise it.

## Subscription lifecycle — arm once, tear down at close (s17 FA2-F2)

A subscription is a real driver subprocess (the `monitor_cmd` you run under the
harness `Monitor`). Keep it 1:1 with your shell:

- **Arm ONCE.** One `observe()` → one Monitor → one driver. Don't re-`observe()`
  the same plane mid-life "to be safe" — that spawns a *second* driver to the
  same inbox and every event is then delivered twice (the RC2 multiplier).
- **ONE FATE PER SUBSCRIPTION — never merge a chatty or newly-landed source into
  the driver carrying your INBOX.** Arming once (above) forbids duplicating the
  *same* plane; it does not oblige you to put every *different* plane in one
  driver, and doing so is a trap. A merge binds every leg to one fate: a monitor
  emitting too many events is stopped automatically, so a fault in the new source
  takes your MAIL with it, and going deaf is silent. Paid for on 2026-07-25 — a
  planner merged `rx.orphaned` with `rx.broker(me)`; a detector bug then repeated
  an identical false verdict every two seconds, and staying reachable meant
  tearing the whole subscription down and re-arming without it. Give a source you
  are still learning to trust its own `observe()` + Monitor, so it can fail
  alone.
- **`observe()` is idempotent on `subscription_id`.** Re-arming with the SAME id
  and an identical spec returns `reused: true` and the same `monitor_cmd` without
  minting a duplicate — **do NOT start a second Monitor** (the existing one is
  live). A *changed* spec under that id is a genuine re-spec (`reused: false`):
  stop the old Monitor first.
- **Tear it down at close.** `TaskStop` the Monitor (alongside `CronDelete`)
  **before** `pool_close_self`, so the driver leaves no orphaned PID. Verify with
  a tracked-PID scan — never a name-wide `python` kill.
- **Stale artifacts self-clean.** `observe()` sweeps abandoned `.reactive/sub-*`
  triplets past the TTL (`EDP_REACTIVE_SPEC_TTL_SECS`, default 24h); a live
  subscription refreshes its own mtime and is never swept. No manual cleanup.
- **The driver is NOT consumed on fire — do NOT re-run the `monitor_cmd`.** It
  subscribes and BLOCKS; its sources never complete, so it streams one NDJSON line
  per event until you `TaskStop` it. Re-running it after a wake starts a SECOND
  driver (a planner reached FOUR, every event arriving 4×) — the exact duplicate
  "arm once" forbids. Full rule: `get_guide("loop-and-heartbeat")`.
- **Verify the driver is LIVE — a dead or starving subscription looks EXACTLY
  like a quiet channel.** Absence of wakes is not evidence of absence of events.
  Confirm after arming and after any restart / compaction / re-spec. Nothing tells
  a shell it has stopped hearing: that check is yours.

## Per-role kind-sets

**Not re-spelled here — one table, in `get_guide("loop-and-heartbeat")`.** This
guide used to carry its own copy and it drifted from both the other guide and the
code. Two rules travel with it: the two DRIVING roles (neuron, planner) subscribe
`rx.broker(me)` with **NO kind filter** — a filter on your own directed inbox
silently drops messages addressed to you, `alert` included — and if you filter
anything, never drop `plan_closed` / `done` / `question`.

### `observe()` writes a spec — it does not listen

`observe()` PERSISTS a subscription and hands you a `monitor_cmd`. The listening
is done by the DRIVER that command starts, under `Monitor`. A spec with no live
driver is DEAF, and looks identical to a quiet plane. Run the `monitor_cmd`.

### The rate-limit knob (`min_interval_ms`) — per-source, and why

Quiet a chatty plane with the per-spec `min_interval_ms` knob (default 0 = every
emission wakes you). It rate-limits **only the POLLED SNAPSHOT sources**
(`rx.pool` / `rx.plan` / `rx.external`) — capping each at one wake per window,
keeping the newest snapshot — and it applies **per-source, before your
`rx.merge`**. Your CRITICAL planes (`rx.worklog`, `rx.broker`,
`rx.recipe_events`) are **never** limited, at any setting.

That split is not decoration; it is the fix for a real event-loss:

> **Never put a wait-for-quiet operator in front of an event you must not miss,
> and never rate-limit a MERGED stream.** The knob used to compile to
> `ops.debounce` applied to the whole merged pipeline. Debounce is not
> rate-limiting: it emits only after the stream falls SILENT for the window and
> keeps only the LAST item of the burst. Merge a 2-second poller in and the
> quiet never comes — so a worker's `done` was not delayed, it was **discarded**,
> and the pool snapshot that beat it was delivered in its place. A planner went
> deaf to its worker for four minutes with a live Monitor and a correct filter.
> Swapping debounce for throttle does NOT fix it: on a merged stream a poller
> still wins the window. Only the per-source shape makes a critical event
> unstarvable — which is why the knob is wired where it is.

The neuron/planner reconcile-loop cadence + the canonical cron prompt live in
`get_guide("loop-and-heartbeat")`.

## The consult channel — user → a live shell (W5)

The user's foreground session (or any second shell) can steer a *running*
neuron/planner without waiting for a heartbeat. Delivery is to the recipe's
OWN inbox (recipient = `<recipe_id>`) carrying `kind="consult"` (a question) or
`kind="steer"` (a directive). It is NOT a separate `consult:<recipe_id>`
recipient — the broker's SSE is per-recipient, so only a message on the
`recipe_id` inbox the neuron already observes will wake it. Because the
neuron/planner subscribe to their inbox with **no kind filter**, an inbound
`consult`/`steer` wakes the live shell on its EXISTING subscription (no second
Monitor) — and cannot be silently dropped by a filter that forgot to list it.
`reconcile` is the poll backstop, and an unacked `steer` re-surfaces each tick
until a `record_context` decision references it.

Send it via `broker_send(to=<recipe_id>, kind="consult", body={...})`, or from
outside the MCP with a curl to the broker at `:9300` (`curl.exe` on Windows):

```
curl.exe -s -X POST http://127.0.0.1:9300/v1/publish -H "Content-Type: application/json" -d "{\"msg_id\":\"11111111-1111-1111-1111-111111111111\",\"ts\":\"2026-07-08T00:00:00Z\",\"from\":\"user\",\"to\":\"<recipe_id>\",\"kind\":\"consult\",\"body\":{\"question\":\"...\"}}"
```

Two load-bearing caveats: **(1)** a full envelope is required — `msg_id` (unique
UUID) AND a tz-aware UTC `ts` — or the broker rejects it `409`; reuse the same
`msg_id` and the post is idempotent. **(2)** `to` is the bare `<recipe_id>`, the
neuron's inbox — not `consult:<recipe_id>`. PowerShell auto-fill:
`$m=[guid]::NewGuid();$t=(Get-Date).ToUniversalTime().ToString('o'); curl.exe -s -X POST http://127.0.0.1:9300/v1/publish -H "Content-Type: application/json" -d (@{msg_id="$m";ts="$t";from="user";to="<recipe_id>";kind="consult";body=@{question="..."}}|ConvertTo-Json -Compress)`.

## The durable-intelligence loop (compose → register → survive → rediscover)

A bare `observe()` subscription dies with the session that created it. To make a
reflex **standing**, register it:

```
compose an observe spec (+ optional governed effect)
  → register_rule(name, spec, effect, owner)   # validated, persisted to disk
  → a running RuleSupervisor re-subscribes every ENABLED rule on startup
    (so the rule SURVIVES a shell / broker / pool restart)
  → a fresh no-context shell rediscovers standing reflexes via list_rules()
```

The 6th-sense watcher is exactly this: one registered rule, not a bespoke daemon.

**The honest limit.** A rule persists **wiring + ONE governed, declarative
effect** — never arbitrary reasoning. There is no "and then think about it" step:
the EffectSpec argument language is only `{"const": …}` and `{"from_event":
"dotted.path"}` — no expressions, no model calls. So when a reflex needs real
JUDGMENT (an ML brain, an LLM call, a scoring model), that judgment lives in a
**bespoke source** that thinks and *publishes its conclusion as an event*; the
rule subscribes to that source and applies a trivial effect. **Keep the
intelligence in the source; keep the rule dumb, governed, and durable.**

**Mutating reflexes (Tier-2) are DARK.** `reconcile` / `next_action` /
`pool_reap` / `record_outcome` can mutate FSM state. They are validate-only and
require an explicit per-rule `mutating:true` even to validate — **do not reach for
them.** Two hard preconditions keep them dark (idempotency-across-restart, the
HARD BLOCKER; and heartbeat coexistence).

## Load on demand

- `get_guide("reactive-streams-reference")` — full source/operator/combinator
  catalog + worked compose examples (planner, neuron, parallel-wave, 3-strikes).
- `get_guide("reactive-streams-effects")` — **fetch before you pass `effect=` or
  register a rule.** observe(effect=) / register_rule /
  list_rules full signatures + the EffectSpec schema + the governed-effect safety
  model + the mutating-reflex idempotency-across-restart detail.
