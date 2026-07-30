# Reactive streams — vocabulary reference + worked compose examples

Companion to `get_guide("reactive-streams")`. Fetch this when you are actually
composing a non-trivial pipeline. The main guide teaches you *how to choose*;
this page is the full catalog plus worked examples of the decision map applied.
The examples are illustrations of composition — adapt them, don't paste blindly.

## Sources (read-only; `rx.<name>(...)`)

| source | emits | plane | notes |
|---|---|---|---|
| `rx.broker(me, kinds=[...])` | inter-shell **messages** to you | control | each message is new + actionable; filter by `kinds`; bind `me` to `whoami().self_address` (planner: dash `plan_id`; worker: `plan_id:action_id`; neuron: `recipe_id`). Senders may also reach a planner at its colon `EDP_HANDLE` — the s16 broker alias bridge reroutes it to the dash inbox — but you still BIND to the canonical `self_address` |
| `rx.worklog(plan_id=…/recipe_id=…)` | new **worklog** entries | control | **follow-only** by default (won't replay history); `replay=True` for full history |
| `rx.recipe_events(recipe_id, kinds=[...])` | the recipe's **FLOWBACK channel** — structured events any shell in the lineage broadcasts via `emit_recipe_event` (learning / discovery / progress / blocker / status_ping / spec_learning_proposed / review_finding), plus P3 `advisory_override` audit records | control | THE worker/reviewer→neuron live channel (no planner relay). Sugar over the recipe worklog tail, filtered to `channel="flowback"`; narrow with `kinds=[...]`; follow-only by default. The neuron's Step-0 merge should include it |
| `rx.plan(plan_id)` | the action-status map, **on change only** | control | wakes on a real action status transition |
| `rx.recipe(recipe_id)` | new recipe **events** | control | follow-only like worklog |
| `rx.pool(scope=<plan_id\|recipe_id>)` | held **locks** + liveness, **on change only** | control | **always pass `scope=`** (your handle prefix) or you get every recipe's locks; a change = a crash signal. Supports `states=['dead']` to filter to crash signals |
| `rx.orphaned(plan_id=…\|recipe_id=…, grace_secs=…)` | actions (or steps) recorded as **dispatched with no live worker behind them** | control | the DERIVED edge for a shell that exited WITHOUT recording — an absence no other plane can carry. JOINs plan/recipe state against pool liveness; for a batch member it checks the member's **OWN handle FIRST** and falls back to its HEAD only when the member has no live session (ordinarily only the head has a handle — but a member re-dispatched standalone has its own, and `batch_group` is immutable so the record still names the dead head). **Covers only work recorded as UNDERWAY:** an action that never started is `pending`, i.e. undispatched rather than orphaned, and this stream is correctly silent about it. Emits only when the orphan SET changes and suppresses the opening empty snapshot, so a healthy plan **never wakes you**. `grace_secs` (default 90, `EDP_ORPHAN_GRACE_SECS`) covers the legitimate gap between the `in_progress` stamp and the spawn. Pass `recipe_id=` for the neuron's half: steps left open with no live planner |
| `rx.topic(name)` | published **domain/UI events** on a named topic | data | sugar over broker recipient-addressing; the "tap a UI component event" path |
| `rx.timer(ms)` / `rx.interval(ms)` | a tick | control | the heartbeat-as-a-stream; merge for a deadline |
| `rx.external(url, mode='get'/'once')` | third-party payload (deduped) | data | satellite/market/gov feeds; pre-wrapped, failure-as-value |

`pool`/`plan` are reduced AT THE SOURCE (emit only on change) and `pool` takes
`scope=`, so a naive `rx.pool(scope=plan_id)` / `rx.plan(plan_id)` is already
quiet — a wake means something real happened.

## Operators (`.pipe(rx.<op>(...))`)

- `rx.filter(fn)` / `rx.map(fn)` — shape the stream
- `rx.take(n)` / `rx.take_until(other)` — completion-shape a leg (needed for
  `fork_join`) / dispose at a boundary
- `rx.debounce_ms(n)` / `rx.sample_ms(n)` / `rx.buffer_ms(n)` — coalesce bursts.
  **Apply these to the CHATTY SOURCE, never to a merged stream** — a reducing
  operator over a merge lets a poller win every window and DISCARD the once-only
  event you actually needed. `debounce` in particular waits for a silence a poller
  never gives you.
- `rx.distinct_until_changed(key?)` — drop unchanged
- `rx.scan(fn, seed)` — running accumulate (e.g. count)
- `rx.timeout_ms(n)` — error if no emission in n ms (stall/deadline)
- `rx.retry(n?)` / `rx.catch(handler)` — transport resilience
- `rx.switch_map(fn)` — supersede: cancel in-flight, switch to new
- `rx.with_latest_from(*others)` — combine with latest of others

## Combinators (return an Observable)

- `rx.merge(*srcs)` — wake on ANY source (the unified idle wake)
- `rx.fork_join(*srcs)` — fire when ALL complete (each leg must be
  `take(1)`/`take_until`) — the parallel-wave gate
- `rx.race(*srcs)` — first to emit wins (event-or-timeout)
- `rx.combine_latest(*srcs)` / `rx.concat(*srcs)` / `rx.zip(*srcs)`

## The rules that keep it quiet

1. **Data-plane vs control-plane.** Only `subscribe(wake)` to a control-plane
   signal. A data-plane source (`external`, `topic`, raw high-rate feeds) MUST
   pass a reducing op first (`sample`/`debounce`/`buffer`/
   `distinct_until_changed`/`scan`-to-threshold). The internal `pool`/`plan` are
   already reduced for you; `external` is deduped.
2. **Always `scope=` the pool** to your plan_id/recipe_id — unscoped floods you
   with every recipe's locks.
3. **Completion-shape fork_join legs** with `take(1)`/`take_until`, or it never
   fires.
4. **Race every long wait against a deadline** (`rx.timer`) so silence is
   impossible.
5. **One Monitor per `observe`.** Tear a subscription down by stopping its
   Monitor task; re-`observe` for a new shape.
6. **The lambda is read+react only.** Mutate via CRUD after you wake (or, for an
   actionable reflex, via a governed `effect=` — see the effects companion).

## Worked compose examples (illustrations, not canned recipes)

Each example is the decision map applied — pick a source/combinator, shape it,
choose the sink. Adapt to your situation.

> **The per-role kind-sets are NOT re-spelled here.** They live in exactly one
> table — `get_guide("loop-and-heartbeat")` → "Per-role observe subscriptions".
> This doc used to carry its own copy and it DRIFTED from both the other guide
> and the code. The shapes below show the COMPOSITION; take the kind-sets from
> that table.

**Planner** — worker results + questions + neuron steers + crash wake (merge of
three control sources):
```
rx.merge(
  rx.broker(me),          # NO kind filter on your own directed inbox
  rx.worklog(plan_id),
  rx.pool(scope=plan_id),
  rx.orphaned(plan_id),   # a worker that exited WITHOUT recording
)
```
bindings `{"me": "<plan_id>", "plan_id": "<plan_id>"}`.

**Neuron** — planner replies + escalations + crash wake:
```
rx.merge(
  rx.broker(me),          # NO kind filter — a filter silently drops `alert`
  rx.pool(scope=me),      # NOT states=['dead'] — see below
  rx.orphaned(recipe_id=me),
)
```
bindings `{"me": "<recipe_id>"}`.

> **The neuron's pool leg used to carry `states=['dead']`, and that filter WAS a
> blindness.** A planner that exits CLEANLY never passes through `dead` — its
> row simply disappears, so the filtered list is empty before and after and
> change-detection never fires. The neuron then waits forever on a `plan_closed`
> that will never be sent. Drop the filter so a vanishing lock is itself a
> change; quiet the plane with `min_interval_ms` instead, which is safe here
> because the pool is a LEVEL (newest supersedes) and never an edge.

**Worker** — the planner's answer to a question it asked:
```
rx.broker(me, kinds=['answer','steer'])
```
bindings `{"me": "<plan_id>:<action_id>"}`.

**Parallel-wave gate (never a bare fork_join — race it against a deadline + a
crash leg):**
```
rx.race(
  rx.fork_join(*[rx.broker(me, kinds=['done']).pipe(
      rx.filter(lambda m: m['body']['action_id']==a), rx.take(1))
      for a in action_ids]),
  rx.timer(sla_ms).pipe(rx.map(lambda _: 'WAVE_TIMEOUT')),
  rx.pool(scope=plan_id).pipe(rx.filter(lambda ls: any(
      l['liveness']=='dead' for l in ls)), rx.map(lambda _: 'CRASH')),
)
```

**3-strikes → escalate (count-to-threshold with scan+filter):**
```
rx.worklog(plan_id).pipe(
  rx.filter(lambda m: m['kind']=='dispatch_failed'),
  rx.scan(lambda n,_: n+1, 0), rx.filter(lambda n: n>=3))
```

## observe → act: the deterministic response table

The response to a sensory wake is always a deterministic op — reconcile, a CRUD
verb, or reply. Never a parallel state machine (see the FSM boundary in the main
guide).

| event you observe | the deterministic action |
|---|---|
| `broker` **plan_closed** / **step_done** | `reconcile(recipe)` → then `next_action` |
| `pool` lock goes **dead** (a child crashed) | `reconcile` — it auto-re-dispatches once, then returns an **`alert`**; if `alert` is set, surface it (`ask_above` / AskUserQuestion) |
| `worklog` **done** (planner watching a worker) | `reconcile(plan)` → then `next_action` |
| **`orphaned`** emits a non-empty list | `reconcile` — its phantom sweep already heals this correctly. **Check the deliverable on disk first**: if the artifact exists, re-dispatch to VERIFY AND RECORD, never to rebuild, or you destroy finished work |
| `broker` **question** | `reply(msg_id, body=…)` |
| `broker` **answer** / **steer** | absorb it; a steer that changes scope → `update_object`/`mark_action_superseded`, then `next_action` |
| `worklog` **dispatch_failed** ×3 (`scan`+`filter`) | escalate — `ask_above` / AskUserQuestion (pivot/abort) |
| `broker` **curiosity clear/done** (neuron) | `reconcile(recipe)` — converges the comprehension gate so `record_outcome` opens |
