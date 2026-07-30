# HLD — edp-broker (component #3)

**Stage:** S1. **Depends on:** `edp-contracts==0.1.0`. **S4 shape:** case (a) automated (internal microservice — no manual HITL stop).
**Authority:** DESIGN-v4 §5/§7/§13, base-contracts (`Microservice` ABC, `BrokerMessage`, `ToolError` envelope), METHODOLOGY.

## 1. Responsibility
A dumb, durable message bus. It transmits events; it holds **no business logic** (no recipes/plans/FSM). One `BrokerMessage` envelope for all traffic (edp-contracts). Append-only per-recipient JSONL → survives restart; consumers replay via `since_ts`.

**Out of scope:** spawning shells (that's #4 pool), any knowledge of recipe/plan semantics.

## 2. Public interface (versioned `/v1`, Microservice ABC)
- `POST /v1/publish` — body = `BrokerMessage`. Appends to `<data>/<recipient>.jsonl`. Returns `{msg_id}`. Unregistered `kind` → `BrokerMessage` validation already raises → return `ToolError(code=broker_unregistered_kind)` verbatim.
- `GET /v1/inbox/{recipient}?since_ts=` — JSON list of messages (optionally `> since_ts`). The primary pull path used by `BrokerPort.poll`.
- `GET /v1/events?recipient=&since_ts=` — SSE: replay backlog since `since_ts`, then keep-alive tail. Reconnect-safe (replay is idempotent by `since_ts`).
- `POST /v1/alias` — `{owner_session, alias, target}`. Registers a relative-ref (`my-planner`→concrete recipient). Populated by the pool (#4) as it spawns; until then unused. Unresolved alias on publish → `ToolError(code=broker_no_route)` verbatim.
- `GET /v1/health` — `HealthStatus` (via `edp_contracts.mount`).

## 3. Data it owns
`<EDP_BROKER_DATA>/<recipient>.jsonl` append-only; `<data>/aliases.json` (alias→target). Nothing else. Recipient name is filesystem-safe (validated).

## 4. Failure modes addressed
| Concern | Mechanism |
|---|---|
| Audit #12 mixed comms | one `BrokerMessage` envelope; no other shape accepted |
| Prior broker SPOF | append-only file + `since_ts` replay → restart loses nothing; consumers reconnect |
| Audit #7 validators ambush | envelope/route errors returned as `ToolError`, not stack traces |
| #13 deploy independence | own repo, own Dockerfile, `/v1` versioned, `Microservice` ABC + contract test |

## 5. Consumer side
`HttpBroker(BrokerPort)` lives in `edp_claude/clients/` (the consumer owns the port impl; swap in `server.py` DI — zero call-site change vs `StubBroker`). Adds `httpx` to claude runtime deps (light).

## 6. S1 — no open questions
Simple service; boundaries are dictated by edp-contracts + DESIGN-v4. Proceeding to LLD (case-a; user directive: don't stop for routine gates).
