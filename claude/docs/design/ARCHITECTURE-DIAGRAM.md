# eda-base3 claude harness — live architecture

Regenerated 2026-08-12 from the running code (supersedes the 2026-05-18
eda-base sketch, which described a retired stack on :9100/:9200).

## Process topology

```
start-stack-claude.bat
 ├─ edp-broker  uvicorn :9300      per-recipient JSONL inboxes + SSE
 ├─ edp-pool    uvicorn :9301      shell pool + shadows (threads in-process)
 ├─ RuleSupervisor (optional)      python -m edp_claude.reactive.registry supervise
 └─ operator foreground shell      eda.bat → claude (CLAUDE_CONFIG_DIR=~/.claude-personal)

every spawned shell (pool):
 ┌────────────────────────────────────────────────────────────────────────┐
 │ ShellShadow (thread in pool)  ── supervises ──┐                        │
 │   ├─ shell: ConsoleLaunch (monitor, visible)  │  brief injection,      │
 │   │         or PtyLaunch (headless, ConPTY)   │  framed wakes, close   │
 │   ├─ rx driver: python -m edp_claude.reactive.driver                   │
 │   │         --spec … --owner <handle>   (CREATE_NO_WINDOW)             │
 │   └─ MCP server: python -m edp_claude.mcp_server (per shell,           │
 │             via claude/.mcp.json; toolset scoped by EDP_ROLE)          │
 └────────────────────────────────────────────────────────────────────────┘
```

## Object graph and drive loop

```
recipe ──owns──▶ step ──spawns──▶ plan ──owns──▶ action ──spawns──▶ worker/reviewer
   (neuron shell)      (planner shell)                      (worker shells)

drive loop per shell:  next_action (pure pacer, FSM)  →  do the instruction
                        →  reconcile (record ↔ reality sync)  →  repeat
FSMs: fsm/state_machines.py (data) + recipe_fsm.py / plan_fsm.py (drivers)
  recipe: created → comprehending → planning → {executing, reviewing} → closed
  plan:   drafted → dispatching → acceptance_review → terminal
  action: pending → {in_progress, skipped} ; in_progress → {verify, done, failed, pending}
```

## Event flow (the sensory nerve)

```
worker record_action_status(done)
  └─ broker.send(kind="done", to=<plan inbox>)          _tools.py _arm_close
       └─ broker SSE /v1/events ──▶ rx driver (drops self-echoes via --owner)
            └─ NDJSON {"event": …} ──▶ _RxDriverAdapter._pump (unwraps)
                 └─ ShellShadow._on_event  (KIND passthrough: done/plan_closed/…)
                      └─ console_input.inject_line (DETACHED helper)
                           └─ "[shadow <handle> #N :nonce] done: {…}"  → planner acts
```

Broker semantics: durable, at-least-once, non-consuming; client-side cursors
(`.inbox_cursors/`). A "channel" is an inbox with a membership record;
filtering is client-side. Registered kinds live in `edp_contracts/broker.py`.

## Roles and seats (models.json — the single model authority)

| role | shell activator | seat | model |
|---|---|---|---|
| neuron | /neuron | judgment | claude-opus-4-6 |
| planner | /agentic-plan | judgment | claude-opus-4-6 |
| specialist | /specialist | judgment | claude-opus-4-6 |
| worker | /worker | builder | claude-opus-4-6 |
| reviewer | /reviewer | checker | claude-opus-4-6 |
| curiosity | /curiosity | advisor | claude-fable-5 |
| (bridge, not a shell) | — | — | gpt-5.6 via .bridge.json (challenge, consult_external, delegate_generate) |

Resolution seam: `edp-pool spawner.seat_model_for` at `PoolService.spawn`,
recorded per session row (provenance). `edp_pool.doctor` warns when the
foreground pin (`CLAUDE_CONFIG_DIR/settings.json`) skews from the neuron seat.
NO Sonnet anywhere (user ruling 2026-08-12).

## Storage (all under claude/ unless noted)

```
.recipes/<id>/{recipe.json, events.jsonl, snapshots/, ack_ledger.json, context/}
.plans/<id>.json + .plans/<id>/{worklog.jsonl, grounding-brief.md, snapshots/, evidence/}
.specs/spec-<slug>[.json|/compiled.md|/learnings.jsonl]      per-project SME contracts
.neurons/registry.db (sqlite)      .graph/edges.db (sqlite, test lineage)
.bridge/audit-<recipe>_<step>.jsonl                          delegate spend ledger
.reactive/{sub-*.spec, handle_index.json, registry/}         rx subscriptions
edp-broker/.broker-data/<recipient>.jsonl                    inboxes
edp-pool/.pool-logs/pool-state.json                          session ledger (incl. model)
edp-pool/.shadows/<handle>.json                              shadow ledgers
```

## Operator surfaces

- Notifications: native Claude Code `Notification` hook →
  `.claude/hooks/notify-user.py` (WinRT toast, rate-limited, EDP_TOASTS gate),
  registered in both `.claude/settings.json` and `edp-pool/.claude-pool/settings.json`.
- Token/cost observability: spawned shells export OTel metrics via the console
  exporter into their PTY drain logs (`pty_launcher._shell_otel_env`);
  foreground gets the same env from `eda.bat`; `/usage` for the live session.
- Doctor: `python -m edp_pool.doctor` — binary, broker, pool, phoenix,
  seat registry, config parity, foreground model, stale locks.
```
