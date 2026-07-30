# Reactive streams — worked exercises

Status: design exercise (2026-05-29). Companion to `REACTIVE-STREAMS.md`.
Three goals driven through **recipe → plan → rx**, each with invented
failure scenarios and rx-based recovery. Findings feed back into the
main doc (§ "Findings", bottom).

Convention for rx snippets: `observe(spec=...)` is the single MCP tool
whose lambda composes read-only sources + operators + a wake sink. Sources:
`rx.broker(me,kinds)`, `rx.worklog(plan_id)`, `rx.plan(plan_id)`,
`rx.recipe(rid)`, `rx.pool(handle?)`, `rx.timer(ms)`, `rx.external(url)`.
The sink (`.subscribe`) only wakes the shell + delivers the emission;
mutation happens AFTER the wake via `update_object`/CRUD.

A note used throughout: **data-plane vs control-plane.** A source like
buoy telemetry or a market tick feed emits thousands of values; an agent
must never `subscribe(wake)` to that raw — it would wake-storm. rx
*reduces* a data-plane stream (sample / debounce / scan-to-threshold /
distinctUntilChanged) into a control-plane signal ("threshold crossed",
"source went silent") before any wake. This distinction recurs in all
three exercises.

---

## Exercise 1 — Abstract: Antarctic ice-melt early-warning system

### Stack decision
Not geoengineering sci-fi. A pragmatic **monitoring + early-warning +
intervention-recommendation** system:
- in-situ **ocean buoys** (temp / salinity / under-ice sonar thickness),
- **satellite SAR** ingestion (Sentinel-1 passes),
- a **melt-rate ML model** + a data pipeline,
- an **alerting** surface + a **fleet deployment / procurement spec**
  (hardware has multi-month lead time — that part is a *spec*, not a
  buildable worker task).

### Recipe (high level)
Expected outcomes (each verifiable):
- **O1** melt-rate model — backtest RMSE < threshold on historical SAR.
- **O2** telemetry ingestion pipeline — a sample buoy feed lands rows.
- **O3** early-warning rule — a synthetic spike fires an alert.
- **O4** fleet deployment / procurement spec — reviewed doc.

Steps: `research+feasibility → ingestion pipeline → model → alerting →
deployment spec`. `feasibility` consults specialists (can buoys survive
under-ice? is SAR cadence enough?); the spec step is doc-only.

### Plan shape (for the "ingestion pipeline" step)
modular-build: parallel actions `buoy-adapter`, `sar-adapter`,
`schema+store`, then `merge+normalize` (depends_on the three).

### Where rx helps
The *running* system is intensely data-plane; the *build* uses rx for
crash/stall resilience. Monitoring-ops, after build, is the textbook
data→control reduction:

```
observe(spec="""
  rx.merge(*[
    rx.external(buoy_url(b)).pipe(
      rx.sample_ms(60_000),               # 1 reading/min, not every packet
      rx.map(lambda r: melt_rate(r)),
      rx.scan(ewma),                       # smooth
      rx.distinct_until_changed(band=0.05),# only real moves
    ) for b in buoys
  ]).pipe(
    rx.filter(lambda m: m.rate > ALARM),   # control-plane: only alarms wake
  )
""")
```

### Failure scenarios + recovery
- **F1 — a buoy goes silent.** Per-buoy stream stops emitting.
  `rx.timeout(15*60_000)` on each leg → emits `buoy_silent(id)` as a
  *value* (failure-as-value, not a stream error that would tear down the
  merge). Agent wakes → marks the buoy degraded (CRUD) + dispatches a
  diagnostic. Without rx: a polling agent only notices on its next tick,
  and "no data" looks the same as "no alarm."
- **F2 — satellite API flaky / 429.** `rx.external(sar_url).pipe(
  rx.retry_backoff(base=2s, jitter=True), rx.timeout(30s),
  rx.catch(lambda e: rx.of(last_cached_pass)))` → transport failure is
  absorbed in rx, pipeline degrades to cached + raises a degraded-mode
  notice; it never crashes.
- **F3 — model-training worker OOM-crashes mid-run.** Build-time.
  `rx.merge(rx.worklog(pid), rx.pool())` → the crash arrives as a
  `pool` liveness event → planner wakes, reaps the dead session, resets
  the action, re-dispatches with a smaller batch. Today's FSM would sit
  in `WAIT` forever.
- **F4 — storm spikes all buoys at once (wake-storm).**
  `rx.buffer_time(30s)` + aggregate → ONE "regional anomaly" wake
  carrying the buoy set, not thousands of single-buoy wakes.

---

## Exercise 2 — Concrete: Java algo-trading service

### Stack decision
Java 21 + Spring Boot. Modules: **market-data adapter** (FIX or
websocket), **strategy engine**, **OMS** (order-management → broker
sandbox gateway), **risk-limit module**, **backtest harness**.

### Recipe (high level)
- **O1** market-data adapter ingests live ticks (sandbox feed → ticks land).
- **O2** strategy engine backtests (P&L produced on historical data).
- **O3** OMS round-trips an order in sandbox (place → ack → cancel).
- **O4** risk limits enforced (a breach order is rejected).
- **O5** test suite green + `mvn verify` passes.

Steps: `clarify+design → modules (parallel) → integration → harden`.

### Plan shape (the "modules" step)
modular-build, one action per module, all `pending` with no deps →
dispatched as one parallel **wave** of 4 workers; `integration` action
`depends_on` all four.

### Where rx helps
Trading is reactive by nature, and so is the *orchestration* of a
parallel wave:

```
# wave gate: integration fires only when ALL four modules complete.
# each leg is completion-shaped (take(1)) so forkJoin can terminate,
# and the gate is races against a deadline + crash detection.
observe(spec="""
  rx.race(
    rx.fork_join(*[
      rx.broker(me, kinds=['done']).pipe(
        rx.filter(lambda m: m.body['action_id']==a), rx.take(1)
      ) for a in ['adapter','strategy','oms','risk']
    ]),
    rx.timer(20*60_000).pipe(rx.map(lambda _: 'WAVE_TIMEOUT')),
    rx.pool().pipe(rx.filter(lambda e: e.liveness=='dead'),
                   rx.map(lambda e: ('CRASH', e.handle))),
  )
""")
```

### Failure scenarios + recovery
- **F1 — one leg crashes; `forkJoin` would hang.** `forkJoin` never
  fires if a leg's stream never completes. The `race` above means the
  `pool` crash leg wins → planner reaps + re-dispatches ONLY the failed
  module, then re-arms the gate. Pattern: **forkJoin + crash-leg +
  deadline**, never a bare forkJoin.
- **F2 — OMS worker fails the verify gate 3× (compile loop).**
  `rx.worklog(pid).pipe(rx.filter(kind=='verify_pending'),
  rx.scan(count), rx.filter(lambda n: n>=3))` → escalate to critic /
  surface pivot-vs-patch to the user. The "3-strikes" rule becomes a
  stream operator instead of agent bookkeeping.
- **F3 — user re-steers mid-build ("FIX → websocket adapter").**
  `rx.broker(me, kinds=['steer']).pipe(rx.switch_map(lambda s:
  new_adapter_wave(s)))` → `switchMap` cancels the in-flight adapter
  subscription and switches to the new one. Reactive supersession; maps
  to the existing `mark_action_superseded`.
- **F4 (runtime, modeled in the system) — order ack times out.**
  `rx.race(order_ack, rx.timer(2000))` → cancel + retry. Modeled both as
  the trading system's own logic and as the agent's pattern for any
  request/response with an SLA.

---

## Exercise 3 — RAG for legal systems (docs in government databases)

### Stack decision
Connectors to **heterogeneous gov DBs** (flaky, rate-limited, some
form/captcha-gated), an **ingest → chunk → embed** pipeline, a **vector
store**, a **retriever + reranker**, an **answer synthesizer with
citations**, an **eval harness** (recall@k + citation-faithfulness).

### Recipe (high level)
- **O1** connectors pull from ≥2 gov sources (N docs ingested).
- **O2** ingest pipeline chunks+embeds (vector count > 0, sample query returns).
- **O3** retriever+reranker (eval recall@k > threshold).
- **O4** answers cite *real* retrieved source IDs (zero hallucinated cites).
- **O5** eval harness + faithfulness metric.

Steps: `source-survey+feasibility → connectors → ingest pipeline →
retriever → synthesis → eval`.

### Where rx helps
Gov-DB ingestion is a low-reliability data-plane — the resilience
operators earn their keep:

```
observe(spec="""
  rx.merge(*[
    rx.external(src.url).pipe(
      rx.retry_backoff(base=2s, jitter=True, max=6),
      rx.timeout(30s),
      rx.map(parse),
      rx.catch(lambda e: rx.of(ParseFail(src, e))),  # failure-as-value
    ) for src in gov_sources
  ]).pipe(
    rx.buffer_time(5_000),                  # batch for the embed worker
  )
""")
# a separate change-feed: re-embed only changed docs
observe(spec="""
  rx.external(gov_changefeed).pipe(
    rx.debounce_ms(2000),
    rx.distinct_until_changed(key=lambda d: d.content_hash),  # dedup
  )
""")
```

### Failure scenarios + recovery
- **F1 — gov DB rate-limits (429) mid-crawl.** `rx.retry_backoff` with
  jitter + per-request `rx.timeout`; on exhaustion `rx.catch` emits
  `source_degraded(src)` → agent narrows scope + notifies the user.
  Pure rx transport-resilience.
- **F2 — a source changes its HTML/schema; parse errors flood.**
  Per-source error stream: `rx.buffer_time(60s) + count`; if the
  error-rate spikes, `rx.filter` → `connector_broken(src)` → agent
  quarantines that source (CRUD: mark step degraded) and the other
  sources keep flowing. Critically, the parse error is a **value**
  (`ParseFail`), not a stream `error` — so it rides through `merge`
  instead of tearing the whole ingestion down.
- **F3 — embedding worker silently stalls (Ollama hang).**
  `rx.worklog(pid).pipe(rx.timeout_no_progress(5*60_000))` (no new
  `chunk_embedded` entry in 5 min) → `worker_stalled` → reap +
  re-dispatch. Directly kills the silent-forever case.
- **F4 — eval finds hallucinated citations after "done".** The eval is
  an outcome-verify gate; the synth action claiming `done` parks in
  `verify` until the eval job emits. rx wakes the agent on the eval
  result: `rx.broker(me, kinds=['done']).pipe(rx.filter(
  action=='eval'), rx.take(1))`. In the *running* system,
  `rx.combine_latest(answer, retrieved_set)` flags any answer whose
  cites aren't in the retrieved set → block before it reaches a user.

---

## Findings (feed back into REACTIVE-STREAMS.md)

1. **Data-plane vs control-plane is load-bearing.** Every source is one
   or the other. An agent may only `subscribe(wake)` to a control-plane
   signal; a data-plane source MUST pass a reducing operator
   (sample/debounce/buffer/scan-to-threshold/distinctUntilChanged)
   first. The rx layer's primary job at high frequency is *reduction*,
   not transport.
2. **Completion-shaping.** Agent event sources are hot/infinite, but
   `forkJoin`/`last`/`toArray` need completion. Each leg must be
   `take(1)`/`first()`/`takeUntil()` or the combinator never fires.
3. **Failure-as-value vs error-as-transport.** Domain failures (crash,
   parse error, rate-limit-exhausted, silent buoy) must be `next`
   *values* so they survive a `merge`. Reserve stream `error` for
   transport drops (SSE lost), handled by `retry`/`catch`. Otherwise one
   leg's failure tears down the whole subscription.
4. **forkJoin + crash-leg + deadline** is the canonical parallel-wave
   gate — never a bare `forkJoin`. `race(forkJoin(legs), timer(sla),
   pool_crash)`.
5. **switchMap-on-steer/replan.** A `steer`/replan supersedes in-flight
   work; `switchMap` cancels and switches. Maps to `mark_action_superseded`.
6. **3-strikes as an operator.** `scan(count) + filter(>=3)` on the
   failure stream encodes pivot-vs-patch as rx, not agent memory.
7. **`rx.external(url)` is a distinct source class** — the resilience
   boundary for third-party systems (satellite/market/gov feeds),
   pre-wrapped with retry/backoff/timeout. Separate from the internal
   broker/worklog/plan/pool sources.
8. **`timeout`/SLA is mandatory on every wait.** Racing every wait
   against a deadline kills the FSM "WAIT-forever" defect at the rx
   layer — silence is impossible by construction.
9. **share/shareReplay.** One SSE connection per source per shell,
   shared across composed operators; replay recent emissions so a
   late-composed operator still sees context.
