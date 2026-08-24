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
- 2026-08-23 Phase A committed (0d4f70e): board/service/search/MCP bundles/cards/skills/guides, 85 tests.
- 2026-08-23 Phase B in progress: consult bridge (Sol PONG live OK, codex resolved under ~/.codex/plugins/.plugin-appserver),
  pool pinned to v8 via EDP_POOL_AGENT_HOME (edp-pool/main.py, one-line opt-in), v8 trust entry in .claude-pool/.claude.json,
  scripts start/stop-board + start/stop-pool, feed driver verified live, MCP stdio verified per role.

## C1 live run — findings (2026-08-23/24, epic-f1b4f138e9 "hello CLI")
Worked end-to-end with real shells: coordinator → architect (design doc, /ocak, 2 stories, 8 criteria,
design_signoff gate, caught a `\v` artefact in the words and asked) → engineer (built+tested+committed in ~1 min,
evidence per criterion) → reviewer (independent re-run, verdicts, done) → adversarial pass → qa. Guards held every
time someone tried a shortcut (doer verdict, coordinator stamping verdicts). Coordinator escalated to owner via
/doubt instead of hacking. Architect filed a /learn to sme about the review-story rule.

Fixed during the run (commit 5432b19): `find(query)` arg name; reviewer/qa/owner bundles lacked `criterion_update`;
coordinator had criteria writes.

To fix next (design/tooling):
1. Review-type story: doer and `checked_by` role must differ — template rule (architect's /learn) + board guard at
   criterion_create (refuse checked_by == story's intended doer role) or default checked_by=qa for work_type=review.
2. One participant per role → parallelism and "who owns what" ambiguity (reviewer assigned S2 while reviewing S1;
   coordinator parked the reviewer thinking S2 blocked it). Spawn per-ticket participants (`engineer@s-xxx`) or
   let `spawn` create a participant bound to the ticket.
3. `blocks` links: the architect must create them at design time; board should refuse `ready` for work_type=review
   without a blocker, or derive "review story blocks on all sibling stories".
4. `context()` for qa/reviewer: include tickets with open gates/criteria checked_by my role, not only assignee.
5. Epic `assignee` is overloaded ("who is waiting") — drop it for epics or define it as "current owner of the gate".
6. Owner feed: also surface `kind=finding` and `status` notes from the coordinator (it did), but the coordinator
   should post one status line per state change of the board (it did well).
7. MCP server loads its registry at start: a bundle fix needs a shell recycle — document in coordinator card.
8. Shell/MCP observability: tail `%LOCALAPPDATA%\claude-cli-nodejs\Cache\<project>\mcp-logs-edp8` (done ad hoc);
   consider a board `events` entry per tool call for human watching (cheap).
- 2026-08-24 C1 DONE: epic-f1b4f138e9 closed (qa ACCEPT 4/4, owner answered acceptance gate). Shells reaped; board (:9400) + pool (:9301) left running (scripts/stop-board.ps1, stop-pool.ps1).
- 2026-08-24 C2-bug DONE: epic-b4a241e44f (blank-name fix d07e885) closed qa 3/3 + adversarial clean. Landed mid-run: per-ticket participants, implicit review blocker, coordinator open-epics context, spawner registration, never-reassign-to-checker card rule. LIFECYCLE added: finish self-park tool, coordinator park/reap duties, board pool-watcher (shell_dead/stalled now emitted). Dedupe of double ready-event pending.
- 2026-08-24 Sonnet-verification pass (owner request): personally reviewed plane_adapter.py — found and fixed an echo loop (own-comment filter never matched "<p>[" prefixed comments), missing webhook auth (added optional HMAC via EDP8_PLANE_WEBHOOK_SECRET), missing HTML escaping. finish semantics settled: park kills the process and keeps the Claude session id for --resume (architect only); every other role closes outright.
- 2026-08-24 C2-rnd DONE: epic-5ac8a33000 (--local POC 707f629; approach B ctypes GetUserDefaultUILanguage; owner decision: no productisation) qa PASS 5/5. Run exercised: finish self-close (engineer/reviewer/qa), architect park, coordinator replaced an unresponsive reviewer autonomously, subtree gate relevance fixed+regression-tested.
