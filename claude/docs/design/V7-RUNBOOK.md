# V7 RUNBOOK — drills (WS5) and the end-to-end proof (WS6)

Everything code-side for v7 is BUILT and suite-green (see the git diff /
task history). What remains runs LIVE — it spends real quota over hours
to days, so it is operator-started by design. This file is the start
button and the evidence checklist.

## WS5 — behavior drills (one supervised evening)

Bring the stack up, then run a tiny drill recipe and tick rows as
evidence lands. Every row's evidence is a FILE — paste paths, not
impressions.

    start-stack-claude.bat          (broker :9300, pool :9301, doctor must
                                     show seat_registry + config_parity OK)
    eda.bat                         then:  /neuron <drill goal below>

Drill goal (small on purpose): "build a two-command CLI note-taker
(add, list) with tests, in a scratch dir" — with
`budget={"delegate_usd": 1.0}` declared at start.

| # | drill | evidence of pass |
|---|---|---|
| 1 | boot diet | the spawned planner/worker transcripts show ONE boot read (the compiled command), zero get_guide fan-out at boot |
| 2 | serves gate | `add_step` without `serves` REFUSES (EDP_V7_WRITE_GATES=1 is stamped); with serves → edge index shows the step→outcome edge |
| 3 | scoped invalidation | `record_context(decision, affects=[s1])` → `.broker-data/<handle>.jsonl` holds ONE `ground_delta`; unaffected handles hold none |
| 4 | silent-unless-gate | heartbeat wakes end with ≤`OK w=…` (read `.logs/verbosity-gate.jsonl` — `over:false` on wake turns) |
| 5 | verbosity probe → arm | after ~20 wakes, read the gate log; if the budget holds, set `EDP_VERBOSITY_GATE=1` in start-stack-claude.bat |
| 6 | open/close symmetry | after recipe close: `CronList` empty, no Monitor tasks alive, pool `/v1/locks` empty — no leaked driver/cron/lock |
| 7 | delegation reflex | a routed worker task calls `delegate_generate` (audit row in `.bridge/audit-*.jsonl`); an unrouted one gets the "yours to do" refusal |
| 8 | test lineage | worker registers tests (`test_edges` rows); reviewer's `test_lineage_report(files=…)` returns the impacted set only |
| 9 | review policy | an unjustified `leg_kind="review"` add_action REFUSES; the justified one dispatches |
| 10 | adversary | planner runs `adversarial_challenge` pre-ratification; findings adjudicated in the worklog (accepted → fix; rejected → reason) |
| 11 | G6 rung | drive delegate spend past the $1 cap → reconcile returns `budget_advisory` naming the numbers |
| 12 | park/resume | planner parks between waves; flowback resumes it; first act is reconcile(reground=true) |
| 13 | steward split (OBSERVE) | watch whether judgment-seat wakes stay judgment-only; if heartbeat noise reaches it, promote the steward split from boot-doc discipline to a second seat spawn |
| 14 | ergonomics audit | sample 10 tool outputs against §2.9's terse/verbose table; file gaps as learnings |

Close WS5 by writing the ticked table + evidence paths into
`docs/design/PARITY-V7.md`.

## WS6 — the end-to-end proof (multi-day, supervised)

Proposed goal (substantial, moderately complex — confirm or replace):

    /neuron build "TaskBoard" — a multi-user task board: FastAPI backend
    with JWT auth + role-based access (admin/member), SQLite persistence
    with migrations, a React SPA (board CRUD, drag-drop), pytest +
    integration tests on the API seams, one e2e golden path. budget:
    {"claude_tokens": 3000000, "delegate_usd": 10, "wall_clock_hours": 30}

Measurement is already plumbed — no manual bookkeeping:
- Claude side: enable telemetry (claude-neuron.ps1 wires OTLP→Phoenix
  :6006) BEFORE starting; per-role tokens come from Phoenix.
- Delegate side: `.bridge/audit-*.jsonl` (cost, tokens, per caller).
- Progress/burn: `budget_status(recipe_id)` any time; verbosity logs
  show the narration diet held.
- WS2 route calibration: `tests/bench/ws2_results.jsonl` (the sol matrix)
  + this run's real acceptance-gate outcomes decide the final
  DELEGATION_ROUTES.

Success = the §2.8 targets, measured not assumed:
- recipe closed, every outcome met with evidence, tests green, e2e path
  demonstrably works;
- neuron ≤1M Claude tokens/wk-equivalent · planner ≤0.4M/step · worker
  ≤120k Claude/task · reviewer ≤60k (compare Phoenix per-role sums);
- zero leaked resources at close (drill 6 re-run);
- a comparison table vs the old baselines (4-5M / 1-2M / 100-350k /
  50-100k) goes into PARITY-V7.md — that table IS the proof.
