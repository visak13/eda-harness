# v8 delivery plan (started 2026-08-23)

Spec: `FRAMEWORK-V8-DRAFT-v2.md` (+ §12). Rulings taken as defaults: engineer/reviewer merged roles;
own typed store with a Plane adapter behind it (portal in phase B); ten objects; embedder pluggable
(fastembed nomic → ollama nomic → none) with BM25 always on; architect in plan mode = sign-off.

Location: `C:\Projects\Learning\eda-base3\v8\` — new uv project `edp8`. Old framework under `claude/`
untouched until cutover. `edp-pool` reused as the pool-runner via an adapter.

## Phase A — core (no LLM, fully testable)
A1 `edp8/schemas.py`      ten objects (pydantic), enums, transition table, design template names
A2 `edp8/store.py`        sqlite: objects, doc versions, events, messages; atomic writes
A3 `edp8/board.py`        guards (6 invariants), derived status, readiness, gates, board(epic) render, context()
A4 `edp8/search.py`       BM25 + pluggable embedder + RRF, scoped
A5 `edp8/service.py`      FastAPI: /v1/{participants,tickets,criteria,docs,links,messages,events,artifacts,sessions},
                          /v1/board/{epic}, /v1/context/{participant}, /v1/feed/{participant} (SSE), /v1/find
A6 `edp8/mcp_server.py`   role-scoped bundles (ToolDef pattern), thin HTTP client; `{ok,value|error,hint}` outputs
A7 `edp8/feed_driver.py`  `subscribe()` monitor command: tails SSE → NDJSON lines
A8 `v8/.claude/commands/` 8 cards · `v8/.claude/skills/` 9 skills · `v8/guides/` design template, strategy_hl seeds
A9 tests: unit per module + one scripted end-to-end epic (owner→architect→sme→engineer→reviewer→qa→close)
   exercising every invariant through the MCP tools in-process.

## Phase B — runtime
B1 `edp8/pool_adapter.py` spawn/resume/park/reap via edp-pool; role→command activation; env (EDP8_PARTICIPANT, token)
B2 docker compose: board service (+sqlite volume), optional Plane CE + adapter sync, artifact dir
B3 Plane adapter: tickets mirrored as issues/comments; webhooks → events; guard violations → message

## Phase C — live
C1 one small feature epic end-to-end with real shells (architect in plan mode, engineer, reviewer, qa)
C2 bug + rnd + creative epics; learnings folded by sme
C3 cutover: retire claude/.claude/commands/* and edp_claude MCP

Each phase ends with its tests green and a commit. Status log below.

## Status
- 2026-08-23 plan written; starting A1–A3.
