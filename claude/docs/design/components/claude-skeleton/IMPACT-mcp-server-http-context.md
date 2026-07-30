# IMPACT — MCP server on real broker/pool (change to built #2)

**Trigger:** HITL #4 passed the isolated worker loop; the only blocker to
the full `/neuron` spine is that `edp_claude.mcp_server` builds its tool
context with `make_context` = **stub** broker/pool. Cross-shell
signalling (neuron↔planner↔worker via the real edp-broker; real pool
spawns) cannot fire until it uses `make_http_context`. §5.5 note first.

## What changes
- **New `edp_claude/clients/http_pool.py` — `HttpPool(PoolPort)`.** The
  consumer owns its port impl (exactly as `HttpBroker` already lives in
  `edp_claude/clients/`). edp-claude must **not** depend on the edp-pool
  package (repo independence), so it carries its own `HttpPool` against
  the `edp_claude.ports.PoolPort` ABC. (edp-pool keeps its own copy for
  its integration test; minor duplication, justified — a shared client
  lib is a later optional extraction, not now.)
- **`mcp_server._build_context(root)`** picks the backend:
  - default **http**: one `httpx.AsyncClient`; `HttpBroker(EDP_BROKER_URL
    or http://127.0.0.1:9100)`, `HttpPool(EDP_POOL_URL or
    http://127.0.0.1:9200)`; `make_http_context(root, broker=, pool=)`.
  - `EDP_MCP_BACKEND=stub` → `make_context(root)` (offline/tests).
  `build_mcp` calls `_build_context` instead of `make_context`.
- `clients/__init__.py` exports `HttpPool`.

## Blast radius
- edp-claude only. `make_context`/`make_http_context` already exist
  (server.py) — no new context plumbing. The 15-tool surface, schemas,
  FSM, slash bodies: untouched. `httpx` already a dep.
- The stub path is preserved verbatim → WALK-1, /clear-test, all 27
  existing tests stay green (they use `make_context` directly or
  `EDP_MCP_BACKEND=stub`).
- No `edp-contracts` change. No broker/pool code change (their HTTP
  surfaces already exist and are tested).

## Risk + mitigation
- Constructing `httpx.AsyncClient` at build time outside a running loop:
  safe (lazy transport; no network until a call). `build_mcp` only
  registers tools — zero network at construction, so the existing
  `test_mcp_1b` (build_mcp registers 15) stays green in http mode.
- A spawned shell with broker/pool *down* → tool calls return the
  standard `ToolError` envelope verbatim (HttpBroker/HttpPool use
  `Tool.from_upstream`); the LLM sees a real error and can act — by
  design, not a crash.
- Routing correctness (relative-ref `my-planner` alias resolution across
  shells) is a **full-spine HITL concern**, exercised next — NOT
  redesigned here. This change only swaps stub→http behind the same
  ports.

## Test plan (S3c delta)
- `HttpPool` unit (fake httpx): spawn ok → `ToolOk{session_id}`; upstream
  409 → `ToolError` verbatim (capacity); liveness parses state.
- `_build_context`: `EDP_MCP_BACKEND=stub` → `StubPool` type;
  default/http → `HttpPool`/`HttpBroker` types, no network.
- Regression: full edp-claude suite green (stub path unchanged).

## Verdict
Swap behind existing ports; stub path preserved & regression-guarded;
the last wiring before the full `/neuron` HITL. Proceed.
