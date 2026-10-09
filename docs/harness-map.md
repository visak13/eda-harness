# Heronry harness map

One file that explains each piece of the harness: what it is, why it exists and how it works, with file:line
anchors. It is for the owner and for agents working on this harness. It is not a product feature, and other
epics and apps do not use it (owner m-7c7f040b0c). When you change a piece, update its entry here in the same
commit and add a line to "Changes to this map" at the end.

Anchors are as of main on 2026-10-08. If one has drifted, trust the code and fix the anchor.

**Contents:** [What the framework is](#what-the-framework-is-and-isnt) · [Board core](#the-board-core) ·
[Runtime and seats](#runtime-seats-and-operations) · [Pool, broker, contracts](#pool-broker-and-contracts) ·
[Agent home, UI, CI](#everything-that-is-not-python-service-code) · [Runs on its own](#what-runs-on-its-own) ·
[Code guards](#code-guards) · [Wakes](#how-seats-are-woken) · [Doc writes](#what-a-doc-write-costs)

## What the framework is, and isn't

The owner's own words, collected from the epic thread (m-6f53271ba1, m-ed4df632ca, m-7c7f040b0c). Every change to
the harness is checked against them.

- **/goal on steroids.** The owner states a goal in their own words. Seats (Claude or Codex, any harness) plan it,
  build it, check it and keep going until it is done, overnight if the owner goes to bed. In the morning the
  owner asks for a summary.
- **Nothing waits on the owner.** "Paused for you" at 2 am is a failure. HITL means the owner can step in from any
  chat at any time; it never means work stops until they answer. A "Needs you" queue or a dropdown to reply from
  is not the way: every ticket has its own chat.
- **The record is the board and git.** Anything held only in one seat's session memory is lost to the framework,
  because a Codex seat cannot see it.
- **The board keeps ticket states consistent and gives hints.** Agents make the judgement calls: spawning a role,
  opening a gate, deciding what a message means. When every story is in_review, the epic moves to in_review; when
  a new requirement arrives, it moves back to in_progress. Beyond state transitions, the board gives the
  architect a hint and does not act on its own.
- **Code guards are static code with no judgement, and they run the same way every time.** They remove bad
  judgement calls from LLMs and keep agents out of ticket bookkeeping. Too many of them turn the harness into a
  maze.
- **This map is for the owner and for agents working on this harness.** It is not a product feature, and other
  epics and apps don't use it.

## The board core

All paths below are relative to `v8/src/edp8/`.

**How a request flows.** A seat calls an MCP tool, for example `message_send`. The shared MCP server (`mcp_server.py`) serves one endpoint per role at `/mcp/<role>`. It reads the caller's identity from the `X-Participant`/`X-Session` headers, checks the tool against the caller's role and workflow bundle, and binds a request-scoped `BoardClient` (`mcp_server.py:186`). `bundles.invoke` validates the arguments against the tool's pydantic model, then calls the handler (`bundles.py:412`). The handler makes an HTTP call through `client.BoardClient._request` (`client.py:66`) to a FastAPI route in `service.py`. That route resolves the `actor` dependency (token check plus the guest guard, `service.py:634`) and calls one `Board` method, here `Board.message_send` (`board.py:2298`).

Inside a `store.transaction()`, the Board checks the invariants and writes typed rows (`Store.put`, `store.py:337`). It also records an `Event` (`Board._emit`, `board.py:436`). After the commit, `_fanout` pushes the event onto every SSE queue whose participant `relevant()` says it wakes (`board.py:4154`). Back in the route, `delivery.after_message` mirrors the message into the broker wake plane and revives self-closed seats (`service.py:1349`). Seats read the stream from `GET /v1/feed`, and each frame carries a `why` (`service.py:2138`). A `BoardError(code, message, hint)` becomes HTTP 409/403/404/422/400 through one handler (`service.py:796`).

### `board.py` (~4350 lines)
- **What:** The `Board` class. It is the only place board rules are enforced, and every mutating method takes an `actor: Participant`.
- **Why:** It carries the "six invariants" (schema, identity/scope, transitions, human gates, capacity, continuity) of FRAMEWORK-V8-DRAFT-v2 §2 (docstring `board.py:1`).
- **How:** The construction and plumbing are below. The logical areas follow as sub-entries.
  - `__init__` builds the `WorkflowRegistry` and the subscriber maps, then re-derives held pairings on boot (`board.py:242`).
  - `_emit` stores an `Event` and schedules `_fanout` after the commit (`board.py:436`).
  - `_index`/`_index_doc` defer search-index updates until after the commit, and never on the critical path (`board.py:444`).
- **Talks to:** `store`, `schemas`, `workflow`, `asks`, `records`, `knowledge`, `lesson_scope`, `guest_scope`, `secret_screen` (through `_screen`, `board.py:399`), `delivery` (for the plan and `resolve`), `context_delta`, `search.Index`, `pool_adapter`. It is called by `service.py`, `ui.py`, `views.py`, `api_*.py` and the helper modules that take `board`.

#### Board · tickets and status transitions
- `ticket_create` pins an epic to a workflow (Standard@1 by default), and a child inherits its epic's pin (`board.py:519`). The story and task caps are `_enforce_story_cap` and `_enforce_task_cap` (`board.py:703`, `board.py:709`).
- `ticket_update` → `_ticket_update` covers status, assignee, title, tags and retyping. Guests are refused, and topics are special-cased (`board.py:873`).
- `_guard_transition` checks two things: the edge must be in the epic's workflow (`wf.legal`), and every precondition the edge declares must pass through `workflow.Workflow.check` (`board.py:1041`). `legal_transitions` exposes the same check (`board.py:1061`).
- `_after_status` runs after a move:
  - A terminal ticket closes its open gates.
  - `in_review` requeues checkers.
  - A released ticket releases its successors.
  - When every story is released, the epic auto-advances to acceptance (`board.py:1127`).
  - Epic phase is carried by the machine (`_advance_epic_phase`, `board.py:667`).

#### Board · criteria and verdicts
- `checker_for` derives the checker role per workflow (`board.py:1459`). `criterion_create` lets authors add criteria. The owner may override the checker with a reason (`board.py:1483`).
- `_criterion_update` handles a reword (which clears an ask-stale flag), evidence, and a verdict with a stale-version guard (`board.py:1555`).
- `_criterion_after_commit` runs isolated post-commit steps: the event, the auto-claim (`records.claim_from_verdict`), the quick reopen and the auto-advance. A failure there is returned as a warning and never raised (`board.py:1705`).
- `stuck_cause`, `architect_fallback` and `requeue_checkers` explain and repair criteria that no live seat can clear (owner R3) (`board.py:2927`, `board.py:2988`).

#### Board · docs, links and artifacts
- `doc_create` checks `DOC_AUTHORS`. A topic's sme may only file `proposed` docs, and the text is screened for secrets (`board.py:1775`). `doc_update`/`doc_edit` → `_doc_update_locked` versions the body (`board.py:1906`).
- `_link_create` requires both ends to exist (a ticket, doc or artifact). Staged artifacts are refused, and `extends` must join two docs (`board.py:1951`). `_reconcile_blocks` keeps `blocks` links and readiness in sync (`board.py:1976`).
- Artifacts are staged on upload and become visible only when finalised with a message (`artifact_finalise`, `board.py:2056`). `sweep_staged_artifacts` removes leftovers (`board.py:2121`).

#### Board · messages
- `message_send` runs these steps in order:
  1. Applies the guest post rule and the secret screen.
  2. Resolves the recipient (by role, handle or id; `resolve_recipient`, `board.py:2238`).
  3. Stores the `Message` and settles asks it resolves.
  4. Records an ask-ledger row.
  5. Emits `message_sent` with mentions.

  (`board.py:2298`)
- `resolve` previews who a message would wake, using the same `delivery.delivery_plan` that does the delivery (`board.py:2262`, `board.py:2283`).

#### Board · gates
- `gate_open` checks the gate's open-phase workflow preconditions. For `design_signoff` it also auto-carries and runs the sign-off lint, so that a gate is never offered whose answer would be refused (pain p-77ab1bf1) (`board.py:2404`).
- `gate_answer` → `_record_gate_answer` writes a ledger-free message and an auto-decision (`records.decision_from_gate`) (`board.py:2502`, `board.py:2556`). `gate_refusal`/`gate_answer_refusal` return the reason before anything is written (`board.py:2512`).

#### Board · pairings and seats
- Automatic checker pairing (design §24 rule 3) works as follows. `_enqueue_pairing` queues a seat (`board.py:1226`). `run_pending_pairings` drains the queue under one lock, spawns when RAM headroom allows (`SEAT_FLOOR_MB`), and otherwise keeps the seat queued with one note. On boot the queue is HELD and needs an explicit spawn (owner m-e2edc8d256) (`board.py:1271`).
- `_spawn_seat` mints a seat token and calls the pool (`board.py:1344`). `sme_spawn_refusal` consults `epic_policy` (`board.py:1425`). `session_upsert` records sessions (`board.py:2600`).

#### Board · asks
- The ledger methods `asks`, `ask_triage` and `ask_verdict` delegate to `asks.py` (`board.py:2899`).
- Inline ask settling (`_settle_asks`, `board.py:3090`): a reply, a quote, `resolves=[...]` or a passed phase settles questions and steers (`_settle_phase_past`, called from `_emit`).
- The board no longer staffs qa or opens the acceptance gate (s-3c858b31b4): when the last story reaches in_review the epic moves to in_review and `_hint_qa_available` emits one `board_hint` the architect's listener prints.

#### Board · inbox, context and feed relevance
- `inbox` lists unanswered questions and steers to a participant, queried by recipient. A human also counts blocked, failed or deferred statuses and deviations (v34, m-8aa6439a77) (`board.py:2737`).
- `context`/`context_delta` give a bounded snapshot plus `records.recall`, and signed delta cursors (`board.py:2686`, `board.py:2716`).
- `_reason_for` is the per-(event, participant) wake predicate, and it never parses text (`board.py:3863`). `relevant`/`why` wrap it (`board.py:3802`). `listening(role)` is the per-role wake contract shown at subscribe (`board.py:3820`).
- `subscribe` returns a bounded asyncio queue. A wake subscription is filtered; a `watch` subscription gets every event. `_offer` drops the oldest event when the queue is full and marks it for resync (`board.py:4113`, `board.py:4135`). `iter_replay`/`replay` handle `since=` replay (`board.py:4192`).
- `find` fuses FTS5 exact hits with semantic hits using RRF (`board.py:4239`).

#### Board · records and status recording
- `record_decision` writes the decision and flips the decisions it `replaces` in one transaction. Binding is inherited by successors (m-db71577ddc) (`board.py:3376`). `record_claim` and `record_lesson` sit at `board.py:3443` and `board.py:3462`. `withdraw_*`, `set_binding` and `retire_lesson` follow. `lookup` wires `knowledge.wired_lookup` (`board.py:3693`).
- `record_status` stores a seat's outcome as a status message and a `status_recorded` event, and returns who to tell: the epic architect, the owner and `to`. The route then calls `delivery.after_status` (`board.py:3293`, `service.py:1369`).

### `store.py` (~570 lines)
- **What:** SQLite persistence for every object type. Each type gets one table holding a JSON body and indexed columns.
- **Why:** The service is the single writer. A global `seq` gives every reader "what's new since" (docstring `store.py:1`).
- **How:**
  - `_INDEXED` lists the queryable columns per type (`store.py:29`). Tables are created from `OBJECT_TYPES`, plus `doc_versions`, `seq`, `idem` and `store_meta` (`store.py:116`).
  - `transaction(immediate=)` nests writes, commits once, and only then runs `after_commit` callbacks. That is how events reach the feed after a durable commit (`store.py:81`, `store.py:108`).
  - `put` stamps the next global seq (`store.py:337`). `query`/`query_seq`/`events_since` page by seq (`store.py:371`, `store.py:508`). `fts_search` is the FTS5 leg (`store.py:295`).
  - Open-time migrations retire roles and migrate the reviewer role and doc layout (`store.py:183`).
- **Talks to:** `schemas`. It is used by `board`, `idempotency` (the `idem` table), `workflow.WorkflowRegistry`, `knowledge`, `records` and `pains`.

### `schemas.py` (~1075 lines)
- **What:** The typed object model: enums (`Role`, `TicketStatus`, `EventKind`, `Reason`, `Gate`, …) and pydantic `Obj` subclasses for the core objects and later ones (Ask, Pain, Decision, …).
- **Why:** Invariant 1, that every write is typed (FRAMEWORK-V8-DRAFT-v2 §3, docstring `schemas.py:1`).
- **How:**
  - The `Obj` base and the object classes start at `schemas.py:348` (`Ticket` at `schemas.py:371`, `Message` at `schemas.py:605`, `Ask` at `schemas.py:825`).
  - `OBJECT_TYPES` is the registry the store builds its tables from (`schemas.py:844`).
  - `TRANSITIONS`, `TICKET_CREATORS` and `DOC_AUTHORS` are the legacy rule tables that Standard workflow is built from (`schemas.py:976`, `schemas.py:995`, `schemas.py:1007`). `DESCRIBE` provides the text behind `describe()` (`schemas.py:1018`).
- **Talks to:** Imported almost everywhere.

### `workflow.py` (~1660 lines)
- **What:** The workflow engine as versioned data: roles, kinds, the transition table with preconditions, the checker map, caps, gates, permissions and hooks.
- **Why:** design-e963c656f5 §4.14(b), S13 s-461403ebd1. Each epic pins one workflow, and Standard reproduces the old constants exactly (docstring `workflow.py:1`).
- **How:**
  - Preconditions name predicates from `PREDICATES` (`workflow.py:367`), for example `_p_design_signed` and `_p_story_cap` (`workflow.py:280`, `workflow.py:328`). No user code runs.
  - `Workflow` exposes `legal`, `edge`, `bundle`, `allowed`, `hook`, `checker_for` and `check` (`workflow.py:454`, `workflow.py:568`).
  - The builtins are `build_standard`, `build_lean` and `build_solo` (`workflow.py:709`, `workflow.py:834`). `validate` lints a definition (`workflow.py:957`).
  - `WorkflowRegistry` handles save, publish, duplicate, pin, snapshot and upstream merge (`workflow.py:1213`, `workflow.py:1504`).
- **Talks to:** `board` (through `workflow_of` and `_wf_check`), the `/v1/workflows*` routes (`service.py:1880`), `bundles` (for role bundles) and `mcp_server` (through `allowed_tool_names`).

### `asks.py` (~450 lines)
- **What:** The asks ledger. Every human message with text on an epic's tree becomes an `Ask` row, which the architect triages and qa judges.
- **Why:** e0cec S4, design-edca9590d7 §5, approved in m-9f2b933578. The acceptance gate waits on the ledger (docstring `asks.py:1`).
- **How:**
  - `record_message` creates the row (`asks.py:58`).
  - `triage` marks covering criteria, which are always qa-checked (`asks.py:128`, `asks.py:166`).
  - `_amend` makes covering criteria stale when the owner amends an ask (`asks.py:210`). `verdict` lets qa rule (`asks.py:235`).
  - `blockers`/`blocked_reason` gate acceptance (`asks.py:267`).
- **Talks to:** It is called by Board methods, and Board stays the enforcer.

### `records.py` (~280 lines)
- **What:** Implicit read and record. The board reads recall for a seat and writes records itself, without being asked.
- **Why:** S-IMPLICIT, design-34bf11cc07 §4.5. It makes no model call, starts no child process and touches no network (docstring `records.py:1`).
- **How:**
  - `recall(store, ticket_id)` builds a capped recall section through `knowledge.wired_lookup` with no semantic index (`records.py:68`).
  - Auto-records:
    - A verdict with a note becomes a claim (`claim_from_verdict`, `records.py:169`).
    - An accepted deviation becomes a decision (`decision_from_deviation`, `records.py:189`).
    - A gate answer becomes a decision (`decision_from_gate`, `records.py:209`).
    - A pain file becomes lessons (`lessons_from_pains`, `records.py:230`).
  - Auto-records are deduped per epic and capped (`_admit`, `records.py:157`). `safely` wraps a hook so that it never breaks a write (`records.py:275`).
- **Talks to:** `board`, `knowledge`, `store`.

### `delivery.py` (~330 lines)
- **What:** The single place where board writes fan out to the broker wake plane, and the one decider of who an event wakes.
- **Why:** Both entry surfaces, the HTTP service and the `/ui/me` forms, behave the same way. Broker publishing is best-effort, and the board record stays the truth (docstring `delivery.py:1`).
- **How:**
  - `delivery_plan` runs `Board._reason_for` over every participant and returns a list of (recipient, reasons). If a question or deviation would otherwise reach nobody, it falls back to the epic owner ("no silent drop") (`delivery.py:25`).
  - `after_message` publishes to the addressee and to @mentions. A message to a closed seat revives nothing: `hint_architect` emits one `board_hint` naming the seat and the message (s-3c858b31b4).
  - `after_status`, `after_gate_open` and `after_gate_answer` handle the other writes (`delivery.py:298`, `delivery.py:314`, `delivery.py:324`).
- **Talks to:** `broker_adapter`, `pool_adapter`, and `board` (relevance). It is called by `service.py` (`service.py:1349`, `service.py:1572`) and `ui.py` (`ui.py:412`).

### `service.py` (~2385 lines)
- **What:** The FastAPI HTTP API over `Board`. Every reply is the envelope `{ok, value|error, hint}`.
- **Why:** It is the only writer process. Identity comes from `X-Participant` (plus `X-Token`), and admin routes use `X-Admin` (docstring `service.py:1`).
- **How:**
  - `create_app` opens the `Store`, the search `Index` (with a `.vec` cache) and the `Board`, then runs the boot backfills (`service.py:426`).
  - The `actor` dependency verifies the token and touches last-seen. For a guest it calls `guest_scope.guard_route`, which fails closed (`service.py:634`, `service.py:602`). `BoardError` is mapped to HTTP status (`service.py:796`).
  - Middleware: guest redaction (`service.py:498`), `IdempotencyMiddleware` as the innermost layer (`service.py:2250`), and `timing.TimingMiddleware` when enabled (`service.py:2270`).
  - The routes are grouped by area in the table below.

| Area | Routes (anchor) |
|---|---|
| identity and context | `/v1/whoami` 860, `/v1/describe` 870, `/v1/context` 878, `/v1/context_delta` 882, `/v1/inbox` 887, `/v1/close_check` 892, `/v1/participants` 897 |
| tickets and criteria | `/v1/tickets` 944/994, `/v1/tickets/{id}` 982/1010, epic members 968, `/v1/criteria` 1022/1044 |
| asks | `/v1/epics/{id}/asks` 1056, triage 1074, verdict 1080 |
| docs and library | `/v1/docs` 1086, read 1106, approve/reject 1142, diff 1154, patch 1172, edit 1183, `/v1/knowledge` 1158, `/v1/library/import` 1163, doc sources/comments/context 1528 |
| links and artifacts | `/v1/links` 1187, `/v1/artifacts` 1200, upload 1214, finalize 1262, search 1271, content 1280 |
| messages and status | `/v1/messages` 1328 (calls delivery), `/v1/status` 1366, `/v1/messages` query 1492, resolve preview 1514 |
| knowledge records | decisions/claims/lessons 1381-1436, `/v1/recall` 1445, `/v1/lookup` 1453, `/v1/index/*` 1438-1476 |
| gates and review | `/v1/gates/decide` 1549, `/v1/docs/comments` 1560, gate open 1568, answer 1576, list 1582 |
| board, events and search | `/v1/board/{epic}` 1587, `/v1/events` 1591, `/v1/find` 1602 |
| sessions and pool | `/v1/sessions` 1612/1640, seat-token 1668, spawn 1694, quick-tasks 1769, resume 1809, reap 1833, close 1846, `/v1/pool/capabilities` 2118 |
| workflows | `/v1/workflows*` 1880-2071 |
| models and harness | `/v1/models` 2083, `/v1/harness` 2094 |
| feed | `/v1/listening` 2133, `/v1/feed` SSE 2138 |
| included routers | views 829, settings 833, topics 834, usage 836, admin 840, doctor 847, tools 850, code 856, ui 2283, webhooks 2297 |

- **Talks to:** `board`, `delivery`, `guest_scope`, `secret_screen`, `quotes`, `design_review`, `contextual_work`, `idempotency`, `timing`, `records`, and every `api_*` router.

### `bundles.py` (~3010 lines)
- **What:** The tool registry. Each `ToolDef(name, description, args_model, handler)` turns tool arguments into a `BoardClient` call. It also holds the per-role bundles.
- **Why:** FRAMEWORK-V8-DRAFT-v2 §8. `ROLE_BUNDLES` is the source of Standard's bundles, and a seat's real bundle comes from its epic's pinned workflow (S13) (docstring `bundles.py:1`).
- **How:**
  - A contextvar-scoped client is set through `set_client` and `bind_request` (`bundles.py:85`, `bundles.py:100`). `invoke` does argument aliasing, then validation (an enum-naming envelope on failure), dispatch, a deprecation hint, and a per-seat failure tripwire (`bundles.py:412`).
  - Tool groups: `IDENTITY_TOOLS` 1021, `TICKET_TOOLS` 1310, `ASK_TOOLS` 1348, `DOC_TOOLS` 1480, `THREAD_TOOLS` 1631, `BOARD_TOOLS` 1733, `POOL_TOOLS` 2184, `SEARCH_TOOLS` 2236, `TOPIC_TOOLS` 2383, `DOCTOR_TOOLS` 2430, `KNOWLEDGE_TOOLS` 2462, `ARTIFACT_TOOLS` 2593, `FRAMEWORK_TOOLS` 2780. They are merged into `ALL_TOOLS` (`bundles.py:2845`).
  - `ROLE_BUNDLES` (`bundles.py:2866`) and `tools_for_role` (`bundles.py:3007`). A custom role gets the identity and kernel tools.
  - `_context` bounds the context snapshot to about 16 KB (`bundles.py:781`). Creates go through `_once` to `tool_idem` (`bundles.py:1137`).
- **Talks to:** `client`, `tool_contracts`, `tool_idem`, `tool_paging`, `doc_tools`. It is used by `mcp_server` and `exam`.

### `mcp_server.py` (~460 lines)
- **What:** One shared, stateless streamable-HTTP MCP server for the whole fleet, with one endpoint per role (`/mcp/<role>`). It falls back to stdio.
- **Why:** Since 2026-09-06 a fleet runs one server process instead of two per shell, and a restart is invisible to the shells (docstring `mcp_server.py:1`).
- **How:**
  - `_identity_from` reads the identity headers (`mcp_server.py:68`). `allowed_tool_names` intersects the path role with the caller's role and workflow bundle (`mcp_server.py:128`).
  - `_wrap` flattens the args model into an SDK signature, binds `BoardClient`, and calls `bundles.invoke` (`mcp_server.py:186`). `_wrap_browser` handles the browser tools (`mcp_server.py:235`).
  - `build_role_server` and `build_http_app` mount the per-role servers (`mcp_server.py:308`, `mcp_server.py:351`).
- **Talks to:** `bundles`, `client`, `workflow`, and the board's whoami.

### Tool-layer helpers: `tool_contracts.py` (180), `tool_idem.py` (70), `tool_paging.py` (190), `idempotency.py` (145)
- **What:** Shared rules every tool follows: what each tool is linked to, idempotent creates, and bounded paging.
- **Why:** S23 owner standards 1, 2 and 5 (s-da61d38c5e). T3 F2 (report-6971109e05) added board-side idempotency keys.
- **How:**
  - `TOOL_OBJECTS`/`link_clause` compose the "linked objects/skills" clause of each tool description, and `tests/test_tool_contract.py` enforces it (`tool_contracts.py:14`, `tool_contracts.py:75`).
  - `tool_idem.once` handles a create in one of two ways. With a key, it forwards the `Idempotency-Key` header. Without one, an identical create within a 10-minute in-process window is replayed (`tool_idem.py:38`).
  - `idempotency.IdempotencyMiddleware` replays the first successful reply per (caller, path, key) for 24 hours from the `idem` table. A different body returns 409. Authorisation is re-run on replay (`idempotency.py:56`).
  - `tool_paging.offset_page` and `seq_page` produce opaque cursors bound to the filters, with a page of about 8 KB (`tool_paging.py:137`, `tool_paging.py:159`).
- **Talks to:** `bundles`, `client` (`client.py:30`), `service`, `store`.

### Docs and quotes: `doc_tools.py` (390), `quotes.py` (320), `design_review.py` (135)
- **What:** Document edits and bounded reads, quotes attached to messages, and source-bound design review.
- **Why:**
  - `doc_tools` is shared by HTTP and the tools.
  - `quotes` follows C18 (design-10b21760d9 §14.5): the board is the trust point, so it re-derives a quote's heading and sha.
  - `design_review` gives review actions that are separate from the legacy acceptance gate answer.
- **How:**
  - `edited_body` applies `old_text` to `new_text` edits. Each must match exactly once, and edits must not overlap (`doc_tools.py:18`).
  - `bounded_read`/`head_read` page by section and offset (`doc_tools.py:259`, `doc_tools.py:225`). `ReadLedger` skips spans an agent has already read (`doc_tools.py:315`).
  - `quotes.quotes_in` checks each quote against its source version (`quotes.py:217`, `quotes.py:146`). `render_quotes` renders them for agents (`quotes.py:287`).
  - `design_review.decide` and `comment` post approve, request_changes or a comment, bound to a gate event and a doc version (`design_review.py:93`, `design_review.py:125`).
- **Talks to:** `board` (docs, messages, gates), and `service` (`/v1/messages`, `/v1/gates/decide`, `/v1/docs/comments`).

### Search and retrieval: `search.py` (685), `artifact_search.py` (150), `knowledge.py` (955), `lesson_scope.py` (150)
- **What:** Lexical and semantic search, the `$` artifact picker, deterministic `lookup` over decisions, claims and lessons, and the gate on where a lesson may reach.
- **Why:**
  - `knowledge` ports poc/kg/walk.py (design-d2c4f39fc6 §4.2). Binding decisions are never cut, and epics are kept isolated.
  - `lesson_scope` comes from e0cec S6 (design-b6a55eed13 §4.C).
  - `artifact_search` comes from epic-0cec8d1c31 S16 (owner m-45367b2531).
- **How:**
  - `search.Index` combines BM25 with optional dense vectors (fastembed or ollama, chosen by a free-RAM floor) and fuses them with RRF. Vectors are cached in `VectorCache` (`search.py:324`, `search.py:597`, `search.py:279`, `search.py:78`).
  - `knowledge.lookup` always includes binding decisions in scope and adds a scored, capped 2-hop remainder. `wired_lookup` adds the index and git heads (`knowledge.py:568`, `knowledge.py:926`).
  - `lesson_scope.visible` is the one lesson gate: a framework lesson reaches framework epics, and a project lesson reaches epics of the same `project:` (`lesson_scope.py:59`). `backfill` classifies older lessons (`lesson_scope.py:127`).
  - `artifact_search.search` returns finalised artifacts the caller may read, with the current epic's artifacts first (`artifact_search.py:129`).
- **Talks to:** `board.find`/`lookup`, `records.recall`, `store.fts_search`, `guest_scope`.

### Context reads: `context_contracts.py` (36), `context_delta.py` (280), `contextual_work.py` (68)
- **What:** The shapes for snapshots and deltas, signed caller-owned delta cursors, and direct-ticket history with linked records.
- **Why:** S23 (report-e517e9e87e). The signing key lives beside the DB, so cursors survive a board restart (docstring `context_delta.py:1`). `contextual_work` never silently substitutes an epic subtree.
- **How:**
  - `cursor_key` is the key stored beside the DB (`context_delta.py:37`). `ContextReader.delta` checks that the cursor still matches the participant, role and scope, then returns events as references only, capped by bytes (`context_delta.py:144`).
  - `ContextSnapshot`/`ContextDelta` are the pydantic shapes (`context_contracts.py:19`).
  - `contextual_work` groups linked docs and artifacts and filters the event history by category (`contextual_work.py:15`).
- **Talks to:** `board.context_delta` (`board.py:2680`), and `service` (`/v1/tickets/{id}/contextual`).

### Guests and secrets: `guest_scope.py` (560), `secret_screen.py` (200)
- **What:** One module answers what a `guest` may do and read. A second refuses secrets on threads a guest can read.
- **Why:** epic-0cec8d1c31 S5 and design-b6a55eed13 §4.B. Both fail closed. A refused read answers 404, the same as a missing id, so it gives away no existence information.
- **How:**
  - `treatment`/`guard_route` classify each REST operation. An unclassified operation gets 403 (`guest_scope.py:198`, `guest_scope.py:220`).
  - `scope_for` computes an `EpicScope`: the member epics plus a one-hop closure, cached per store seq (`guest_scope.py:338`). `visible`, `filter_visible` and `redact_ids` apply it (`guest_scope.py:393`, `guest_scope.py:513`).
  - `secret_screen.check` matches key and token patterns and live secret values from the token, secret and `.env` files, and refuses rather than redacts (`secret_screen.py:192`, `secret_screen.py:95`). `withhold` screens guest feed frames (`secret_screen.py:173`).
- **Talks to:** `service` (the actor dependency, the redaction middleware and the feed), `board` (`_screen`, `_refuse_guest`, `subscribe`), and `idempotency` replay.

### Library, topics and help: `topics.py` (685), `library.py` (245), `help.py` (140), `guides.py` (80), `operator_docs.py` (40)
- **What:** Library topics with a resident sme seat, skills.sh import and the knowledge tab, doctor help threads, the `get_guide` allowlist, and operator documentation.
- **Why:**
  - `topics`: S-SME-SURFACE (s-698224fca8; owner m-de07c37d0c, m-bdfb407429).
  - `library`: S-LIBRARY (design-34bf11cc07 §4.3).
  - `help`: S19 (architect m-ec43dddf3e).
  - `guides`/`operator_docs`: epic-0cec8d1c31 S9.
- **How:**
  - A topic is a parentless `topic` ticket. `topics.create` and `ensure_seat` handle creation and the seat (`topics.py:135`, `topics.py:172`). `research` fetches only from allowed hosts and leaves a receipt (`topics.py:608`). `propose` files a proposed doc only for a URL that was fetched (`topics.py:664`).
  - `library.import_skill` resolves skills.sh or GitHub to a raw SKILL.md and versions it by `source_url` (`library.py:163`). `autolink` links Library docs to a ticket (`library.py:213`).
  - `help.ask` opens or resumes the caller's help thread with a `doctor.<topic>` seat (`help.py:60`).
  - `guides.read` checks the name against the folder listing and never joins a path (`guides.py:76`). `operator_docs.read` checks the agent home and then the shipped directories (`operator_docs.py:27`).
- **Talks to:** `board` (tickets, docs, the pairing queue), `api_topics`, `api_doctor`, `bundles` (`get_guide`).

### Pains: `pains.py` (365), `pain_dispositions.py` (70), `pain_git.py` (75)
- **What:** The pain log as board `pain` rows. Legacy jsonl files are imported, S14 routing is applied, and a read-only check asks whether a commit is on main.
- **Why:** e0cec S6 (design-b6a55eed13 §4.C) made the board database the one store. The dispositions follow note-5df2381eb1.
- **How:**
  - `sync`/`import_files` import the repo and installed jsonl files, deduped by id (`pains.py:196`, `pains.py:160`). `file` adds a pain (`pains.py:276`).
  - `resolve`: the owner, the doctor and admins may set any status. An architect may set only `fixed`, citing a sha reachable from main (`pains.py:309`, `pain_git.py:28`).
  - `pain_dispositions.apply` touches only imported pains that are still open (`pain_dispositions.py:47`).
- **Talks to:** `api_tools` (`/v1/pains`), `records.lessons_from_pains`, and git.

### Doctor fixes: `fixes.py` (185), `fix_actions.py` (75)
- **What:** Approval-gated fixes. The Help or doctor seat proposes one action from a closed set, and an admin approves it.
- **Why:** S19 (design-e963c656f5 §4.14(e).5, ruling m-ec43dddf3e). Nothing runs before Approve, and a workflow pin is never changed.
- **How:**
  - The `fix_actions` classes form the discriminated union shared with the MCP schema (`fix_actions.py:21`).
  - `fixes.propose` stores a `FixProposal` (`fixes.py:90`). `approve` claims it under the lock and runs the exact admin route once, with the admin's own credentials, then posts the redacted result to the thread (`fixes.py:148`, `fixes.py:115`).
- **Talks to:** `api_doctor` (`in_process_runner`, `api_doctor.py:51`) and `attention`.

### Policy and attention: `epic_policy.py` (46), `attention.py` (225)
- **What:** Epic tags (`sme:on|off`, `project:<key>`), and the one derivation of what is waiting on a person.
- **Why:**
  - `epic_policy`: e0cec S6. SMEs are opt-in per epic.
  - `attention`: S20 (design-e963c656f5 §4.18, owner m-8d061abf32). Every surface renders the same list. "Needs you" is owner-only and limited to items no seat can act on (e0cec S3).
- **How:**
  - `epic_policy.sme_refusal` is the one check every spawn path calls (`epic_policy.py:36`).
  - `attention.items` merges asks, gates, sign-offs, fixes and access requests, each with a location path and a `why` (`attention.py:164`). `attention` adds a rollup (`attention.py:221`).
- **Talks to:** `board` (`sme_spawn_refusal`, `inbox`), `views`, and `api_views` (`/v1/me/attention`).

### Views and UI: `views.py` (1075), `api_views.py` (240), `ui.py` (710)
- **What:** Pure view derivations over the Board and a viewer, the JSON API over them, and the legacy dependency-free HTML views.
- **Why:** Each view is computed once for both renderers (design §4.1 "Backend views"). It was extracted from `ui.py` with characterisation tests (`tests/test_views.py`).
- **How:**
  - `views` contains `epic_page`, `ticket_page`, `thread_page`, `pending_signoffs`, `decisions_for` and `render_markdown`, which is sanitised (`views.py:865`, `views.py:920`, `views.py:839`, `views.py:264`, `views.py:594`, `views.py:144`).
  - `api_views.views_router` exposes `/v1/me/*`, `/v1/epics/{id}/page`, `/v1/tickets/table` and others. It is included ahead of the dynamic routes so that static sub-paths win (`api_views.py:69`).
  - `ui.router` serves `/ui/*` pages and forms. A form post calls `delivery.after_message` exactly like the API does (`ui.py:135`, `ui.py:412`).
- **Talks to:** `board`, `attention`, `guest_scope`, `delivery`.

### Other routers: `api_code.py` (255), `api_doctor.py` (170), `api_settings.py` (60), `api_tools.py` (145), `api_topics.py` (175), `api_usage.py` (19)
- **What:** Each is a FastAPI router mounted by `create_app`.
- **Why:** Each module's docstring names its story:
  - `api_code`: epic-91fcd3b370 S3/S8 (dec-ea925a2d30).
  - `api_doctor`: S19.
  - `api_settings`: epic-44a0576511 s-7f663c6322.
  - `api_tools`: S23 report-e517e9e87e.
  - `api_topics`: S-SME-SURFACE.
- **How:**
  - `api_code`: `/v1/code` status and the owner-only one-time session mint for the code-server guard (`api_code.py:194`, `api_code.py:216`).
  - `api_doctor`: `/v1/help`, the read-only `/v1/doctor/*` routes (doctor role and admins only), and fix propose, approve and reject (`api_doctor.py:85`, `api_doctor.py:98`, `api_doctor.py:148`).
  - `api_tools`: `/v1/pains`, `/v1/services/status`, `/v1/harvest/cost` (`api_tools.py:70`, `api_tools.py:107`, `api_tools.py:119`). `api_topics`: the topic CRUD, experts, research and proposals. An expert's token reaches only these routes (`api_topics.py:92`).
  - `api_settings`: `/v1/me/settings` for humans only (`api_settings.py:21`). `api_usage`: `/v1/me/usage`.
- **Talks to:** `board`, `help`, `fixes`, `pains`, `topics`, `run_state`, `doctor`.

### Operational helpers: `admission.py` (170), `orphans.py` (185), `timing.py` (100)
- **What:**
  - `admission`: a cross-process inference lane for the OpenAI login, used by codex and Pi seats.
  - `orphans`: finds orphaned test runners.
  - `timing`: logs per-request timing.
- **Why:**
  - `admission`: design-97ca02e989 §8 S8. A seat acquires the lane per turn, not for its lifetime.
  - `orphans`: S22 host hygiene. On 2026-09-27 a stray vitest ran for 2 hours.
  - `timing`: S22 performance pass.
- **How:**
  - `Lane.acquire` locks with an atomic `mkdir` on a lock directory and keeps a queue of tickets that waiters must touch. Stale tickets and leases are reclaimed (`admission.py:73`, `admission.py:128`).
  - `orphans.find` walks up each runner's launcher chain to decide whether its seat is gone. `stop` kills by process identity (`orphans.py:148`, `orphans.py:178`).
  - `TimingMiddleware` is pure ASGI and writes the route template, status, ms and bytes to `timing.jsonl`, off by default. `summarise` computes p50 and p95 (`timing.py:29`, `timing.py:83`).
- **Talks to:** The codex and Pi seats (`admission`), `heronry doctor` (`orphans`), and `service` (`timing`).

### Offline tools: `exam.py` (215), `importer.py` (370)
- **What:**
  - `exam`: an exam harness that measures retrieval changes.
  - `importer`: `heronry import --from <v8 dir>` copies a source checkout's state into an install.
- **Why:**
  - `exam`: steer m-3f96079aa8 item 1, "make every curation or retrieval change MEASURED".
  - `importer`: design-e963c656f5 §4.13, S3 s-870e401942.
- **How:**
  - `exam.run_packs` runs one lookup per question through the tool layer (`bundles.invoke`) and writes packs plus a grading template. `score` totals the results against a baseline (`exam.py:124`, `exam.py:159`).
  - `importer.plan` is a dry run by default. `_copy_db` uses SQLite's online backup from a read-only connection. `apply` copies (`importer.py:132`, `importer.py:265`, `importer.py:300`).
- **Talks to:** `bundles` and `client` (`exam`). The `importer` only touches files and the database.

## Runtime, seats and operations

Paths are relative to `v8/src/edp8/` unless they start with `v8/`.

**How a seat is born and woken.** A spawn (MCP `spawn`, `POST /v1/sessions/spawn`, or auto-pairing) resolves model and effort (`seat_choice.resolve`), refuses an un-acknowledged Fable adversary (`harness`), reuses the seat's secret, and calls `pool_adapter.spawn` with `EDP8_TOKEN` in `env` (service.py:1751-1759). The edp-pool service starts the shell in the agent home with `EDP_ROLE`/`EDP_HANDLE`/`EDP_SPAWN_SESSION_ID`/`EDP8_TOKEN`. For Claude it is a Claude Code shell running `/<role>`. For codex it runs `python -m edp8.codex_seat.run`, and for Pi it runs `python -m edp8.pi_seat.run`. The shell reaches the board only through the `edp8` MCP server (v8/.mcp.json: `/mcp/<role>` with X-Participant/X-Session/X-Token headers). Its role card calls `subscribe`, which returns a Monitor command `python -m edp8.feed_driver --participant … --board … [--broker …]` (bundles.py:618). The seat runs that command under Monitor. Every NDJSON line it prints wakes the seat and becomes a turn. Line types are `listening`, `event` (board SSE), `broker_msg` (broker inbox), `heartbeat` and `error`. Board writes addressed to a participant are also mirrored to the broker (`broker_adapter`), so the pool's watchdog can resume a parked shell.

**How services run.** `heronry start` (`cli`) goes through `launcher`, the single code path for all starts. It starts board, broker, pool, mcp and bridge (plus the optional `code`) as detached processes in named jobs, writes their pid records (`run_state`), then starts `supervisor`. The supervisor probes each service every 15 s, restarts it after 3 misses, and serves a loopback control port (`control`) for the CLI, Admin → Services and the desktop tray. `heronry update` (`updater`) checks compatibility, backs up the DB, parks seats, stops everything and hands off to a detached stdlib `update_helper`. That helper installs, health-checks, rolls back if needed and resumes. While it runs, `update_lock` blocks every start.

### Seat wake path

### `feed_driver.py` (~380)
- **What:** A CLI meant to run under Monitor. It merges the board SSE feed, the broker inbox SSE and its own heartbeat into one NDJSON stream on stdout.
- **Why:** Every printed line wakes the seat for one turn. The heartbeat replaced the model-run cron because each idle cron turn cost a model call (S8). Lines are byte-capped because each one becomes turn input word for word (S20 token-cost rework).
- **How:**
  - `cap_line` (feed_driver.py:68) clips the longest strings once a line passes `EDP8_FEED_EVENT_B` (default 2000) and adds an `omitted` fetch hint.
  - `_stream_board_once` (:272) GETs `/v1/feed?since=` and moves its cursor on the `: ready N` and `: resync N` marks. `run` (:339) prints the `listening` contract line first, then reconnects with 1→30 s backoff.
  - `_broker_loop` (:322) starts at "now" (the inbox is append-only history) and reads `/v1/events?recipient=`.
  - `Heartbeat.tick` (:184) polls `/v1/context_delta`. It wakes only for changes the feed did not deliver, for a resync, or with a liveness ping for a doing seat whose ticket is in_progress (`_LISTENING_ROLES` :119 exempts architect and owner).
- **Talks to:** Board `/v1/feed`, `/v1/listening` and `/v1/context_delta`; broker `/v1/events`. Launched from the `subscribe` tool (bundles.py:612) and the console script `edp8-feed`.

### `pool_adapter.py` (~318)
- **What:** An HTTP client for the edp-pool service that spawns, resumes, closes, parks, reaps and syncs sessions.
- **Why:** The pool owns shell processes and the board owns state. The handle is the participant id, so a shell's MCP identity comes from `EDP_HANDLE`.
- **How:**
  - `spawn` (pool_adapter.py:105) POSTs `/v1/spawn {role, handle, model, effort, capacity_class, max_concurrent, env}`. It refuses with `foreign_board` when this board is not the fleet board (`foreign_board_reason` :83).
  - `resume` / `resume_closed` (:144, :150) pass a fresh `EDP8_TOKEN` (p-451a2390). `close` (:157) is a graceful release and `reap` (:188) a forced kill.
  - `sync_sessions` (:259) mirrors pool sessions into board sessions over one keep-alive client. An unknown answer keeps the previous state and stamps `presence_stale_since`, so silence is never shown as Closed (c-1a82925acb). `SPAWN_TICKET_ENV` (:25) carries the ticket on the session (p-a05affa0).
- **Talks to:** edp-pool `/v1/*`. Called by service.py (spawn :1759, resume :1822, sync :2204), bundles.py, delivery.py, admin/capacity, doctor.

### `broker_adapter.py` (~69)
- **What:** A best-effort republisher of addressed board messages and gates onto the edp-broker inbox of the recipient's handle.
- **Why:** The board is the system of record and the broker is the delivery plane. A broker inbox that grows is what wakes a parked shell. A broker outage never fails a board write.
- **How:** `KIND_MAP` (broker_adapter.py:30) maps board kinds to broker CORE kinds, and unregistered kinds fall back to `fyi`. `publish` (:46) POSTs `/v1/publish` with a 5 s timeout, logs on failure and never raises.
- **Talks to:** Called by delivery.py (:147, :247, :308, :320, :328) and service.py:1634 (shell-death notices).

### `client.py` (~465)
- **What:** `BoardClient`, a thin synchronous httpx wrapper with one method per board REST route. It returns the `{ok,value,hint}` envelope unchanged.
- **Why:** MCP tool handlers and CLIs need a single typed caller. 4xx/409 responses are treated as data. Only a connection failure raises `BoardUnreachable` (client.py:20).
- **How:**
  - `_headers` / `_request` (:55, :66) add X-Participant, X-Token and, for admin calls, X-Admin.
  - `idempotency_key` (:30) is a contextvar that sends `Idempotency-Key` on a create tool's first POST only (T3 F2).
  - `artifact_upload` (:260) opens the file through `local_upload.workspace_file`.
- **Talks to:** Used by bundles.py / mcp_server tools and feed-side helpers. Calls the board HTTP API.

### Seat harnesses

### `codex_seat/` (run 210, seat 444, rpc 348, tools 1092, ws 129, containment 104, jobobj 63)
- **What:** Runs a GPT/Astra fleet seat on `codex app-server`. The runner hosts Claude-parity `Monitor`/`TaskStop`/`Cron*` tools as `dynamicTools`.
- **Why:** Codex seats must behave like Claude seats: the same tools, wake rules and envelopes (s-10a2b1f9ec, epic-6a8a6020fd; approval m-c50e181c7f of deviation m-6768770bc5). Codex is the adversary harness when it is selected (R4/R5).
- **How:**
  - `run.main` (codex_seat/run.py:100) reads the pool's env contract (`EDP_CODEX_MODEL`, `EDP_CODEX_RESUME`, `EDP_CODEX_CONSOLE` …). It boots with the role card plus the edp-terse style and a resident contract (:63, :84). `run_tui` (:175) attaches the native TUI over a loopback websocket (`ws.py`, ruling m-0e7b8fdd7f).
  - `CodexSeat.start` (seat.py:210) launches the app-server with every MCP server disabled except `edp8`. Disabling is discover-and-disable and fails closed (`containment.discover_mcp_servers` containment.py:38). Identity comes from env by name (`board_args` seat.py:106), and the sandbox is per role (`sandbox_for` :122).
  - `AppServer` (rpc.py:81) runs stdio JSON-RPC with a reader thread, a dispatcher thread and worker threads. It mirrors every message to `codex-seat.<handle>.jsonl` and asserts that no secret appears on argv (`SECRET_KEYS` :35).
  - `Delivery.deliver` (tools.py:279) turns a Monitor line or cron fire into `turn/start` when the seat is idle, using a 20 ms coalesce. It attaches the line to the next seat-tool result, or `turn/steer`s it after an in-flight native tool. `SeatTools._on_line` (:709) batches lines, truncates them and rate-gates them per parity §5. `jobobj.bind_to_kill_job` (jobobj.py:18) makes sure no Monitor outlives the runner.
- **Talks to:** Spawned by edp-pool `codex_launcher.py`; the codex CLI; the board through MCP.

### `pi_seat/` (driver 215, run 102)
- **What:** Drives a Pi coding agent (`pi --mode rpc`, JSONL on stdio) as a fleet seat.
- **Why:** This is the third harness (design-97ca02e989 §6). The `.pi/extensions/edp8.ts` extension supplies Monitor/Cron and the MCP bridge, and this package owns the process.
- **How:** `PiSeat.start` (pi_seat/driver.py:112) spawns Pi with the token in env only and mirrors stdout to `pi-seat.<handle>.jsonl`. `steer` (:168) and `stop` (:203) handle control (clear_queue → abort → kill). `run.main` (pi_seat/run.py:46) sends the role card as the first prompt, then stays resident until Pi exits.
- **Talks to:** Spawned by edp-pool `pi_launcher.py`.

### `seat_choice.py` (~361)
- **What:** Decides which model and effort each seat of an epic runs on, from tags on the epic and story tickets.
- **Why:** Owner ruling m-2d7ef9243d / m-3238155d2e: the owner picks model and effort when creating an epic, before any launch. Per-role picks follow design-34bf11cc07 §4.1 and m-bba708e10e. Tags are used so no schema migration is needed.
- **How:** Tag grammar is `model:<role>=<id>[@effort]|…`, `seat:<role>=` on a story, and the legacy `seat-model:` / `seat-effort:` (seat_choice.py:55-63). `resolve` (:334) applies this order: explicit spawn model, then story pick, then epic role option, then legacy tag, then role catalog default, then global default. Effort is clamped to the model's cap. `unknown_model` (:270) validates the choice against the catalog.
- **Talks to:** bundles.py:2012, service spawn route, board, views, admin/harnesses. Reads `model_catalog`.

### `model_catalog.py` (~377)
- **What:** The editable model catalog (models, `role_models`, `default_model`) stored in the data directory.
- **Why:** Admins edit models without touching the shipped agent home. Shipped updates are merged in against a `_shipped` snapshot.
- **How:** `merge` / `sync` / `ensure` (model_catalog.py:131, :192, :218) run at board boot (service.py:441). `codex_windows` (:297) probes codex for real context windows and caches the result (`OK_TTL` 600 s). `validate` (:334) checks rows.
- **Talks to:** seat_choice, admin/models, doctor, setup, service.

### `harness.py` (~110)
- **What:** Records which harnesses are selected (claude/codex/pi) and holds the Fable adversary fallback gate.
- **Why:** Owner rulings R4/R5 (design §4.11). Without codex, the adversary runs on Fable (`claude-fable-5-1`). Fable may soften reviews, so a human must acknowledge that risk once.
- **How:** `selected` / `validate` (harness.py:40, :57) require at least one of claude or codex. `filter_catalog` (:64) is also defined here. `fable_refusal` (:106) refuses a Fable adversary spawn until `fable-risk-ack.json` exists, which `write_ack` (:97) creates.
- **Talks to:** board, service, seat_choice, setup, admin/harnesses and admin/models.

### `harvest_cost.py` (~324)
- **What:** Measures the tokens one `/harvest` cost from the seat's own log, and lists the self-improvement records written in that window.
- **Why:** s-043eb90ccc. S23 moved it into the package so the board can serve it as the `harvest_cost` tool.
- **How:** `find_log` (harvest_cost.py:126) finds the Claude transcript or the codex mirror. `claude_window` / `codex_window` (:172, :213) find the window from the trigger to close_self. `compute` (:291) sums usage.
- **Talks to:** api_tools; the tool defined at bundles.py:2803.

### Services: start, supervise, control

### `cli.py` (~593)
- **What:** The product CLI `heronry` (alias `edp8`). Commands: init, start/stop/restart, status, doctor, prereqs, update, import, gui, workflows, version.
- **Why:** One command layer sits over the single launcher (design-e963c656f5 §4.4, S3 s-870e401942). The legacy `edp.ps1`/`.bat` wrappers only call it.
- **How:**
  - `main` (cli.py:553) dispatches the `--heronry-service <svc>` bundle re-entry before any other import (`_run_service` :32, strategyhl-5af811e7bd §3). It then runs `settings.home_guard` and the `_COMMANDS` table (:538). Subcommand modules load lazily (`_lazy` :437).
  - `start` (:205) starts services through the launcher and supervisor, and opens first-run setup (`_first_run_setup` :270). `stop` has a seat guard (`_pool_guard` :313). `_via_control` (:194) prefers the supervisor's control port.
- **Talks to:** launcher, control, code_service, setup, updater, prereqs_cmd, desktop, workflows_cli, importer.

### `launcher.py` (~955)
- **What:** The single code path that starts, stops, adopts and reports every service.
- **Why:** design-e963c656f5 §4.4 / S3: one argv builder and one process identity model. There is no taskkill, WMI or shell (epic criterion 3).
- **How:**
  - `SPECS` / `ORDER` (launcher.py:35-60) list board→`edp8.service`, broker, pool, mcp→`edp8.mcp_server`, bridge→`edp8.slack_bridge`, and supervisor.
  - `service_argv` (:140) returns `python -m <module>`, or `heronry.exe --heronry-service <svc>` inside a bundle. `child_env` (:169) supplies the home, run dir and peer URLs from ports, and pool defaults (`EDP_SKIP_PERMISSIONS`, `DISABLE_AUTOUPDATER`, `EDP_UPDATE_LOCK`).
  - `start` (:391) is idempotent. It checks `home_guard`, then `update_block`. It adopts this home's live listener, refuses a foreign one, and recovers leftovers from an interrupted start. Otherwise it detaches into a named job, waits for health, and writes a `run_state` record. Starting the board also runs `register_defaults` (:498).
  - `stop` (:790) refuses while seats are live unless forced (`live_seats` :758) and uses kill_tree plus terminate_job. `ensure_supervisor` (:841) and `status_rows` (:898) are also here.
- **Talks to:** `edp_contracts.proc`, run_state, update_lock, code_service. Called by cli, supervisor, desktop (via the CLI), updater.

### `supervisor.py` (~337)
- **What:** A detached process that probes each service and restarts it after 3 consecutive failures. It also hosts the control port.
- **Why:** Services belong to the launcher, never to a seat (design §22). Probes use one connection every 15 s so they cannot cause the §18.3 ephemeral-port flood. Control port per strategyll-3b8f4033e0 §3.3/§5.
- **How:**
  - `Supervisor.tick` (supervisor.py:59) skips paused and failed services and names the failure "process alive without its listener" where that applies. More than 5 restarts in 10 minutes marks the service `crash_loop` and failed. Each restart emits `service_restarted` (`make_emit` :181).
  - `make_dispatch` (:242) routes `/services/<svc>/{start,stop,restart}`, `/status`, `/update` (`start_update` :196) and `/shutdown`.
  - `main` (:295) supervises only the bridge this fleet itself started (S17 c-c0f2ceea9b) and records `control_port` in its run record.
- **Talks to:** launcher (`relaunch` :160), run_state, control, board events API.

### `control.py` (~162)
- **What:** The supervisor's loopback HTTP control port and its client.
- **Why:** Lets the CLI and Admin → Services act on processes without the board killing anything itself. It must never be reachable from a browser or from public mode.
- **How:** `make_handler` (control.py:59) accepts only POST from a loopback peer. Host must be 127.0.0.1 or localhost, any request with `Origin` is refused, and `X-EDP-Control` must match the secret (`hmac.compare_digest`). `rotate_secret` (:42) writes `<run>/control.secret` on each supervisor start. `endpoint` / `call` (:130, :156) read the port from the supervisor run record.
- **Talks to:** supervisor (server); cli, launcher, setup, admin/services, admin/updates (clients).

### `run_state.py` (~431)
- **What:** One JSON pid record per service under the run dir, plus process and listener probes.
- **Why:** Design §22 rule 4: seats can see infrastructure state (via preflight) without touching it.
- **How:** `write` / `adopt` / `update` / `mark_probe` / `mark_restart` (run_state.py:126-185). `snapshot` (:218) feeds status. `listener_pid` / `one_socket_scan` (:263, :284) do a single psutil sweep. `record_alive` (:121) matches pid together with create_time. `git_rev` (:46).
- **Talks to:** Used by launcher, supervisor, control, mcp_server, service, bundles (preflight), admin/services, code_service.

### `settings.py` (6)
- **What:** Re-exports `edp_contracts.settings`, the one registry of paths, ports and knobs (design §4.2).
- **Talks to:** Everything in this section.

### `slack_bridge.py` (~258)
- **What:** The "doorbell" service. Each new broker message for a person becomes one Slack ping. No LLM is involved.
- **Why:** Humans get notified off-board at zero token cost.
- **How:** `run` (slack_bridge.py:217) takes a single-instance lock (`_lock_or_exit` :157). It merges `slack_map.json` with each person's UI settings (`_merge_people` :179) and starts one `_watch` thread per person (:119), each tailing broker SSE from "now". Quiet hours are handled by `_in_quiet` (:48). Messages go out by webhook or bot DM (`_post` :55).
- **Talks to:** broker, user_settings, admin/integrations (`send_test_ping` :89). Started by launcher as `bridge`.

### `code_service.py` (~1062) + `code_guard.py` (~477)
- **What:** The optional `code` service: a pinned code-server on a random inner loopback port, behind a host-allowlist guard that owns the public port.
- **Why:** DNS rebinding can reach any loopback port (s-03c7e9168b, design-628b968271; S21 s-0cfebd3862). The code-server environment has every `EDP*` variable removed so terminals never inherit seat secrets (dec-ea925a2d30). Login tokens are sent only by POST (m-e26cf15b4f).
- **How:**
  - `ensure_pinned` (code_service.py:309) downloads and verifies the release from `code_server.lock.json`. `start` (:885) runs the guard plus the server with a per-start password and mint key, and writes `<run>/code.json`. `stop` (:1008) acts only on the recorded (pid, create_time). `server_env` (:452) does the scrubbing.
  - `check_head` (code_guard.py:132) enforces origin-form target (400), exact Host (421) and WS Origin (403). The guard also requires its own cookie, set by `POST /__edp/login` with a board-minted HMAC token (`mint_token` / `verify_token` :94, :101). `Guard` (:300) relays traffic and adds the code-server session cookie.
- **Talks to:** cli, supervisor (`_code_action` supervisor.py:226), desktop, api_code (mints login tokens), launcher.

### Install, update, desktop

### `updater.py` (~1077) + `update_helper.py` (~1300) + `update_lock.py` (~177)
- **What:** `heronry update` checks for a release and applies it, either by uv tool or MSI. A detached helper does the install and rolls back on failure.
- **Why:** `uv tool install --force` cannot replace a venv that a live process has loaded (os error 32). So the helper imports only the stdlib and runs from a copy outside the install folder (strategyhl-86b4805322 §4, S3). Owner AV ruling m-631a9ad2a7: the installed app never launches uv itself; only the helper does. The compat check comes from S13 / m-3ab493d55b.
- **How:**
  - `check` (updater.py:408) asks GitHub at most daily, ETag-cached; `HERONRY_NO_UPDATE_CHECK` turns it off. `_apply` (:935) runs in order: fetch the release, verify sha256, `_compat_gate` (:353, runs `heronry workflows check`), secure a rollback, `backup_db` (:376, keeps 5), park seats, `_stop_all`, stage the helper. `apply_msi` (:742) is the bundle path.
  - `update_helper.main` / `_steps` (update_helper.py:304, :337) follow a JSON plan: wait for the caller to exit, install, start, health-check. On failure they stop, reinstall the previous version, restore the DB backup, and start again. `update-result.json` is written on every path. `_msi_steps` (:748) is the MSI path. `_park_all` / `_resume` (:518, :563) park and resume seats. `untracked_seats` (:1160) refuses while seats the pool does not track are running.
  - `update_lock.acquire` / `guard` (update_lock.py:81, :169) hold `<home>/update/update.lock` from parking to the result. While it is held, `launcher.update_block` refuses every start. A lock whose pids are all dead is cleared.
- **Talks to:** launcher, pool `/v1/park` and `/v1/resume`, supervisor `/update` (called from admin/updates), the desktop tray.

### `setup.py` (~595) + `prereqs_cmd.py` (~183) + `bootstrap.py` (38)
- **What:** `heronry init`, `heronry doctor`, `heronry prereqs [install]`, and seeding of the default participants.
- **Why:** design §4.2/§4.4/§4.11. An untrusted seat home stops at a Claude trust dialog that the pool never answers (m-33f96d11c9). Prerequisites have a single installer step (t-08612be1b0).
- **How:**
  - `init_cmd` (setup.py:291) creates the directories, config.toml, the admin token and the first human's token. It materialises the agent home, records the harness choice, and writes the folder-trust entry (`write_trust` :212). `choose_ports` (:133) picks a free port block. `doctor_cmd` (:428) exits 1 on any FAIL.
  - `prereqs_cmd.install` (prereqs_cmd.py:120) asks one yes/no question; `--yes` and `--only` skip it.
  - `bootstrap.main` (bootstrap.py:20) registers owner, architect, sme, engineer, adversary and qa. `launcher.register_defaults` (launcher.py:498) does the same on board start.
- **Talks to:** materialise, harness, model_catalog, diagnostics, `edp_contracts.prereqs`, admin/prereqs_api.

### `materialise.py` (~216)
- **What:** Copies the shipped agent home into the seat home: role cards, skills, guides, `.mcp.json`, models.json and CLAUDE.md.
- **Why:** The wheel ships the agent home as package data (design §4.2). User edits must survive upgrades, following the dpkg-conffile rule (strategyhl-86b4805322 §2).
- **How:** `materialise` (materialise.py:126) keeps a `.manifest.json` of shipped sha256 hashes. A file the user never edited is overwritten. An edited file is kept and the new version is written beside it as `<file>.new`. A file the user deleted stays deleted. `PAYLOAD` (:27) must match the pyproject force-include. In a dev checkout it is a no-op (`source_root` :85). `refresh` (:190) runs at board boot (service.py:433).
- **Talks to:** setup, updater, service.

### `desktop.py` (~875)
- **What:** Heronry Desktop: a pywebview window plus a tray icon. Every action runs the same `edp8.cli` command the terminal would.
- **Why:** design §4.9 / S8. It keeps one code path (strategyhl-5af811e7bd §4); the GUI owns no service.
- **How:**
  - `run_cli` (desktop.py:45) runs those CLI commands.
  - `Desktop.boot` (:667): on first run, init and then `/ui/setup` with a one-time code; on later runs, `/ui/join`.
  - `ensure_webview2` (:194) checks WebView2, and `navigation_decision` (:234) keeps the window on the board origin.
  - `Bridge.notify` (:275) shows rate-limited toasts. `actions` (:562) is the tray menu.
- **Talks to:** cli, code_service, updater.

### `diagnostics.py` (~285) + `doctor.py` (~392)
- **What:** `diagnostics` holds the redaction `Scrubber` and builds `heronry doctor --bundle`. `doctor` holds the read-only diagnoses used by the Help/doctor seat.
- **Why:** S19 (design §4.14(e).5). A support zip must never leak secrets, paths, usernames or emails.
- **How:** `Scrubber` (diagnostics.py:113) redacts the values from `known_secrets` (:69) plus anything token-shaped. `write_bundle` (:253) writes the zip. Each of `doctor.health`, `pool_view`, `feed_lag`, `dead_mail` and `why_stuck` (doctor.py:80, :140, :167, :205, :238) returns facts plus named `causes`.
- **Talks to:** setup, api_doctor, bundles (the doctor tools), pool_adapter, run_state.

### Background services and integrations

### `rsi.py` (~661)
- **What:** RSI phase 1. A tripwire that re-runs the tracked retrieval exam through `knowledge.wired_lookup` whenever the corpus or the retrieval code changes.
- **Why:** report-9a85d0418e §9 / S18. It checks that the expected evidence is still found, not that answers are correct. It fails closed.
- **How:** `tick` (rsi.py:456) fires when 20 or more rows differ, when the last run is older than 24 h, or when the code hash changes (`CODE_MODULES` :54). A run holds a 15-minute lease and needs a RAM floor. `regressions` (:382) finds lost record ids, and `post_finding` (:427) sends one finding to the architect. `start_thread` (:590) runs only while `EDP8_RSI=1` (service.py:2345).
- **Talks to:** store, knowledge, exam, board.

### `plane_adapter.py` (~311)
- **What:** A one-way mirror from the board to Plane CE, plus a webhook that turns comments made in Plane into `note` messages.
- **Why:** The board stays the source of truth and Plane only mirrors it (FRAMEWORK-V8-DRAFT-v2 §4).
- **How:** `PlaneMirror` and `PlaneSync` (plane_adapter.py:117, :198) poll `events_since` and track ticket-to-issue ids in a `plane_map` table. `webhook_router` (:254) receives the comments.
- **Talks to:** service.py:2295-2298 (only when Plane is configured in env), admin/integrations.

### `tailnet.py` (~317)
- **What:** Tailnet public mode: a readiness classifier, plus apply and remove for `tailscale serve`.
- **Why:** design §4.8 Remote access. The board stays on 127.0.0.1, TLS ends on the tailnet, and `EDP8_PUBLIC_URL` turns on fail-closed token rules.
- **How:** `classify` (tailnet.py:63) is pure. `gather` (:246) collects the facts. `apply` and `remove` (:275, :306) edit config.toml and never restart anything.
- **Talks to:** admin/remote, `edp.ps1 tailnet check`.

### Browser, uploads, usage, UI helpers

- **`browser_proxy.py` (~431) + `browser_tools.json` (872).** Runs one shared Playwright MCP service as a child of the mcp server. Each seat session gets its own upstream session (t-732cf1dd92, m-bb6902256d, rulings m-b61ec43737). The core class is `BrowserProxy` (browser_proxy.py:234).
  - `signin_function` (:115) injects the calling seat's token only when the page origin exactly matches the board's.
  - `scrub` (:142) redacts the token from results.
  - An idle reaper (`IDLE_S` :42) and `notify_session_end` (:417, called at service.py:1621) close sessions.
  - The JSON file is the pinned tool snapshot. Wired in at mcp_server.py:151, :257 and :408.
- **`uploads.py` (~155).** Sniffs the real file type from magic bytes against an allowlist. SVG is always served as a download. The size cap is 25 MB, or 100 MB for video (design §18.1, t-f01372d361). Key functions are `sniff_upload` (uploads.py:122) and `limit_for` (:57). Used by board, service and views.
- **`http_upload.py` (~212).** Defines the upload roots for single-host MCP: an operator policy, or by default the agent home (S15 p-a3ae2179, RC2 F3 m-1f09a47214). See `HttpUploadPolicy` (http_upload.py:110). `_forbidden` (:68) blocks secret files and folders. Used by mcp_server.
- **`local_upload.py` (~121).** The upload boundary for a seat's local files. `workspace_file` (local_upload.py:68) verifies the opened file handle, so a symlink swapped in mid-check is caught. Used by `client.artifact_upload`.
- **`usage.py` (~201) + `usage_sources.py` (~305).** Private telemetry on subscription quota. `UsageCache` (usage.py:135) reads only allowlisted receipt files. The collectors `capture_claude` and `collect_codex` (usage_sources.py:78, :204) run only when an operator starts them; HTTP never does. Used by api_usage.
- **`notifications.py` (~46).** Privacy-minimal notification selectors over S20 `attention.items` (notifications.py:20). Used by api_views.
- **`user_settings.py` (~237).** Per-person UI settings in `ui-settings.json` (epic-44a0576511 · s-7f663c6322). `public` (:200) masks the webhook before it reaches the SPA. `bridge_people` (:216) feeds the Slack bridge.
- **`avatars.py` (98), `avatar_preferences.py` (58), `avatar_templates.py` (75), `icons.py` (90).** Dependency-free inline SVG avatars and icons. Entry points are `avatar_svg` (avatars.py:78) and `icon` (icons.py:74). Used by ui, views and api_views.
- **`brand.py` (36).** User-facing product names and URLs, re-exported from the settings `brand` group (design §4.12, m-56ede7a5e3). `BRAND` (brand.py:31) is mirrored by `web/src/brand.ts`.
- **`webapp/serve.py` (119).** `mount_spa` (webapp/serve.py:70) serves `dist/` under `/ui`. Assets get an immutable cache, and other paths fall back to the SPA. A missing build returns a 503 page and never fails `create_app` (m-f0a5330767). Mounted at service.py:2287.
- **`workflow_design.py` (~440) + `workflows_cli.py` (18).** Support for the Design tab (S14 s-42a72db3dd). `dry_run` (workflow_design.py:415) walks a draft on a scratch in-memory board. `diff` (:91) and `merge3` (:105) compare and merge drafts. `heronry workflows check` (workflows_cli.py:11) is the compat check the updater runs (S13).
- **`__init__.py`.** Holds `__version__`, one version shared by all packages and kept in sync by tests/test_version_sync.py.

### Admin console backend: `admin/` (~2,100 lines)
- **What:** Every `/v1/admin/*` route behind the Admin UI, plus the public join, sign-out and access-request routes.
- **Why:** design §4.8/§4.10/§4.11 (S5). An admin is a human with the admin flag or the init human; a machine token never counts (dec-9c292f88a4).
- **How:**
  - `admin_router` (admin/__init__.py:19) mounts the sub-routers at service.py:840.
  - `make_admin_actor` (admin/auth.py:33) requires X-Participant plus that human's own X-Token and answers 403 otherwise. `AdminContext` (admin/context.py:69) is the shared context.
  - Each panel module:

    | Module | Panel | Notes |
    |---|---|---|
    | `services.py` | start, stop, restart | Through the control port; a board restart answers 202 (admin/services.py:118) |
    | `capacity.py` | pool caps | Through pool `/v1/limits` (:64) |
    | `harnesses.py` | detect, update-when-idle, selection | `Updater` :138 |
    | `models.py` | catalog editor | |
    | `integrations.py` | Slack map, Plane, code-server | `merge_slack` :126 |
    | `teammates.py` | invites and tokens | Hashed one-time codes, `redeem_invite` :211 |
    | `access.py` | sign-out and request access | t-882e4d2eeb |
    | `remote.py` | tailnet and Tailscale auth keys | |
    | `updates.py` | update apply | Via supervisor `/update` |
    | `release.py` | cut a release | Owner only (R8 m-45367b2531) |
    | `settings_api.py` | registry editor | Env-sourced values are read-only, secrets write-only |
    | `setup_api.py` | wizard `setup.json` | |
    | `prereqs_api.py` | Install button | Runs `heronry prereqs install --only` |
    | `net.py` | the one outbound httpx seam | |

- **Talks to:** control, launcher, run_state, pool_adapter, tailnet, user_settings, model_catalog, harness, updater.

### Packaging: `v8/pyproject.toml` (112) + `v8/hatch_build.py` (81)
- **What:** The `edp8` wheel (version 0.10.4, pinned with `edp-contracts==0.10.4`), its console scripts, and the force-include list that ships non-Python data.
- **Why:**
  - The SPA `dist/` is gitignored but must ship. A stale bundle once shipped silently (adversary/qa finding #15, 2026-09-10), so a build hook checks freshness.
  - The agent home ships as package data so that `materialise` can install it (design §4.2).
- **How:**
  - Scripts: `heronry` / `edp8` → `edp8.cli:main`, plus `edp8-board`, `edp8-mcp`, `edp8-feed` and `edp8-supervisor` (v8/pyproject.toml:31-37). Extras are `embed` and `desktop` (:25-29).
  - Wheel force-include (v8/pyproject.toml:56-81):
    - `webapp/dist`
    - `.claude/{commands,skills,output-styles,hooks}`, `guides`, `.mcp.json`, `models.json` and `CLAUDE.md`, all under `edp8/agent_home/`. These must stay in step with `materialise.PAYLOAD`.
    - operator docs
    - `code_server.lock.json`
    - the vscode-ext extension list and its lock
    - the desktop splash and icons
  - The sdist uses `only-include` plus `artifacts` so dist survives the sdist→wheel round-trip (:92-106).
  - `WebBundleFreshness.initialize` (v8/hatch_build.py:41):
    - It skips the check for editable installs.
    - It rebuilds dist with npm when dist is missing or older than `web/src`, and fails without npm (`EDP8_WEB_AUTOBUILD=0` turns off the rebuild, leaving only the check).
    - `_include_vsix` (:73) adds the EDP Chat `.vsix`. It is required when `EDP8_REQUIRE_VSIX=1`.
- **Talks to:** materialise (PAYLOAD), code_service (lock files), desktop (assets), webapp/serve (dist).

## Pool, broker and contracts

### Process topology (overview)
- **Board** `edp8.service` on :19400 (installed; code default 9400): the record (tickets, messages, participants). It asks the pool for seats through `v8/src/edp8/pool_adapter.py` (`POST /v1/spawn`, `/v1/resume/{h}`, `/v1/resume_closed/{h}`, `/v1/park/{h}`, `/v1/release/{sid}`).
- **Broker** `edp_broker.main` on :19300 (default 9300): durable per-recipient JSONL inboxes, aliases, channels, SSE push. Seats' feed drivers stream `GET /v1/events` from it (`v8/src/edp8/feed_driver.py:306`).
- **Pool** `edp_pool.main` on :19301 (default 9301): launches, parks, resumes, reaps and caps seat shells (Claude, Pi, Codex). It owns the session rows and the handle locks.
- **MCP proxy** `edp8.mcp_server` on :19402 (default 9402): one shared, stateless streamable-HTTP MCP server. Each seat connects to `/mcp/<role>` with `X-Participant`/`X-Session` headers. It lives in `v8/`, not in the pool (`v8/src/edp8/mcp_server.py:1`).
- **Ports and URLs** are declared once in `edp-contracts/src/edp_contracts/settings/keys_common.py`: `EDP8_PORT` :132, `EDP8_MCP_PORT` :143, `EDP_POOL_PORT` :150, `EDP_BROKER_PORT` :157, plus `EDP8_BOARD_URL`/`EDP8_MCP_URL`/`EDP_BROKER_URL`/`EDP_POOL_URL` at :67-83. The code defaults are 94xx/93xx; an install's `config.toml` moves them to the 19xxx block (`docs/runbook-cutover.md:112`). The launcher's service table is `v8/src/edp8/launcher.py:52-57`.
- **Seat row lifecycle** (`PoolService.sessions`, persisted to `EDP_POOL_STATE`):
  - `spawn()` reserves a row as `starting` (`service.py:1272`), and `_launch_reserved` moves it to `active` (`service.py:1441`).
  - `park_session()` moves `active` to `parked` (`service.py:1928`) and keeps the shell alive.
  - `resume()` moves `parked` to `active` if the shell is alive (`:2038`); otherwise it goes `resuming` (`:2070`), then `active` (`:2144`), or back to `parked` if the launch fails (`:2130`).
  - `release()`/`reap()`/`reconcile_sessions()` move a row to `done` (`:1513`, `:2548`, `:1026`).
  - `sweep_crashed()` (`:1747`) and `mark_interrupted()` at pool start (`:783`) move a row to `dead`.
  - `resume_closed()` takes a `done` row through `resuming` to `active` (`:2210`, `:2254`).
  - Callers: the board via the pool adapter, the shell's own hooks (`/v1/session_end`), the resume watchdog thread and the panel.

### Top-level layout (one line each)
- `.github/`: CI and release workflows (`ci.yml`, `install.yml`, `installers.yml`, `process-layer.yml`, `release.yml`, `site.yml`).
- `.logs/`: dev-mode service and shell logs (not source).
- `archive/root-v7/`: retired v7-era root files (old launch scripts and harness notes).
- `claude/`: the old v7 Claude agent home plus debug dumps, screenshots and scratch text (historical).
- `design-templates-mcp/`: a standalone MCP server that exposes the eda-designs design system to an agent.
- `docs/`: README assets, release notes, the cutover runbook and the docs website source (`docs/site`).
- `edp-broker/`: the message broker service (see below).
- `edp-contracts/`: shared contracts for the other packages: settings registry, envelopes, error codes and process helpers.
- `edp-pool/`: the seat pool service and its shell launchers (see below).
- `integration/`: cross-package seam tests (`tests/test_integration_seams.py`).
- `neuron-sol/`: an `AGENTS.md` workspace for an external (codex/Sol) neuron.
- `opencode-fleet/`: the retired opencode-harness experiment (HARNESS.md, probes, policy).
- `review-package/`: review images and HTML for a product review.
- `scripts/`: release build (`build_release.ps1`) and the installer shim.
- `v8/`: the product: board, MCP server, CLI, desktop app, VS Code extension, guides and `models.json`.
- `vault/`: generated plans and recipes (`plans/`, `recipes/`).
- Root files:
  - `edp.ps1`, `start-v8.bat`/`stop-v8.bat`: dev stack control.
  - `install.ps1`/`install.sh`/`setup.ps1`: installers.
  - `.sol-run-*.jsonl` and `.sol-last-message-*`: stray outputs from Sol runs.

### `edp-pool/src/edp_pool/service.py` (~3140 lines)
- **What:** `PoolService` holds the in-memory and persisted seat registry: session rows, handle locks, neuron drivers and cap overrides. The FastAPI app that serves it is defined in the same file.
- **Why:** One always-on process owns every shell's lifecycle, so capacity, locks and resume survive seat crashes and pool restarts.
  - Persisting state was the cross-restart-recovery fix of 2026-05-21.
  - Visible-by-default spawns are a user ruling of 2026-07-12.
- **How:**
  - **Spawn and capacity:**
    - `spawn()` refuses person roles first (owner m-da9a2ae62f, `service.py:1157`).
    - It then checks, under `_transition_lock`: the per-role cap, the builder cap (`EDP_MAX_WORKERS`), the planner cap (`EDP_MAX_PLANNERS`), the total cap (`EDP_MAX_TOTAL_SHELLS`), and a live-process ceiling that also counts parked shells (`service.py:1172-1245`). Each refusal is a `POOL_CAPACITY_EXCEEDED` envelope that names the knob to raise.
    - It reserves a `starting` row and the handle lock. Each row records `spawn_settings` and a minted `claude_session_id`, so the seat can later be resumed from closed (S20; owner m-8b70f4afb6) (`service.py:1251-1286`).
    - The slow launch runs outside the lock in `_launch_reserved` (`service.py:1371`). That function calls `spawner.launch` (`:1404`) and records the process fingerprint and the harness.
  - **Park, resume and close:**
    - Park is a state change only. The shell stays alive because cron and Monitor live inside the session (operator ruling 2026-07-25, `service.py:1852`). Park records per-handle inbox watermarks and the size of each rx file (`:1900-1934`).
    - `resume()` restores a live parked shell to `active` with no relaunch (`:2037`). A dead one is fork-resumed with `--resume base --session-id fork --fork-session`. `_resuming_inflight` blocks a double spawn when the watchdog and the backstop fire together (S11 finding 15, `:2005`).
    - `resume_closed()` re-takes the lock on the newest `done` row (S20, owner m-6ffe756cf7, `:2172`).
    - `release()` (`:1481`) records a close that arrives mid-spawn as `_release_requested`. A clean close kills the process tree only after checking its fingerprint (`_kill_session`, `:968`), then closes the console window.
  - **Startup:**
    - `startup()` (`service.py:746`) first marks rows whose process died as `dead`/`interrupted` (owner m-e2edc8d256, `:769`). It never auto-relaunches them.
    - It then starts the resume watchdog and seeds the Claude `settings.json`.
    - After that it fork-resumes rows the updater parked with `park_for_update` (`:792`), and respawns the external neuron drivers (`:761`).
  - **Approvals and recipes:**
    - Panel approvals are an in-memory queue. A PreToolUse hook long-polls `/v1/approvals/{id}/wait`, and a timeout falls back to the shell's own permission prompt (`service.py:558-611`).
    - Recipe pause/resume fans out over the registry's live rows (`:2425-2454`). Suspend and durable resume shell out to `recipe_ctl.py` (`:2636`).
- **Talks to:**
  - Called by the board's `pool_adapter.py`, by shell hooks (`/v1/turn_ping`, `/v1/session_end`, `service.py:2796-2820`) and by the panel (`/panel`, `/v1/limits`, `/v1/approvals`).
  - Calls the spawner stack, the broker (inbox depth for watermarks, channel registry) and `proctree`.
  - `/v1/broker/publish` is the panel's only route to the broker, and it stamps every message (`service.py:3112`).

### State file and session rows
- **What:** `EDP_POOL_STATE` (`keys_pool.py:30`) is one JSON file of `{sessions, locks, neuron_drivers, limit_overrides}`.
- **Why:** Locks and rows survive a pool restart. A lost lock means an infinite wait, which is worse than a possible double execution (`service.py:395-404`).
- **How:**
  - Writes are atomic: a temp file, then `os.replace`, under `_persist_lock` (F47#2, `service.py:720-744`). `_reload()` reads the file back (`:613`).
  - Row keys: `session_id`, `role`, `handle`, `capacity_class`, `parent`, `state`, `proc` (pid+create_time fingerprint), `claude_session_id`, `recipe_id`, `spawn_settings`, `harness`, `parked{watermarks,file_baselines}`, `dead_reason`, `interrupted`, `park_for_update` (`service.py:1268-1278`, `:1928-1935`).
  - `liveness(handle)` answers `alive`/`dead`/`unknown`, or the name of a `parked`/`resuming` state (`:2282`). Liveness checks use the fingerprint, so a process orphaned by a pool restart still reads correctly.
- **Talks to:** `doctor.py` reads locks for the stale-lock check. Panel views read rows through `/v1/sessions` and `/v1/panel/shells`.

### `edp-pool/src/edp_pool/resume_watchdog.py` (~470 lines)
- **What:** A daemon thread in the pool that polls about every 5 s. It wakes parked seats, publishes crash notices and runs channel dispatch.
- **Why:** The pool is the one durable process that can both watch inboxes and spawn shells. Polling survives broker restarts better than an SSE subscription, and wakes take seconds instead of the 30-minute heartbeat (DESIGN-v7 1.5.3).
- **How:**
  - `tick()` (`resume_watchdog.py:323`) first runs `svc.sweep_crashed()` and publishes the `crashed` kind to each parent (`:347-348`, `_publish_crashed` `:297`). It then runs `channels_tick()` (`:352`).
  - For each parked row, inbox depth above the watermark triggers `svc.resume(handle)`. A watermark of `None` fires on any traffic, on purpose: an over-eager wake is better than a stranded seat (`:383-391`).
  - `channels_tick()` (`:257`) uses the broker channel registry. It wakes parked members named in `for:`, and treats a mention of a handle that is not live as a spawn signal.
  - It is gated by `EDP_RESUME_WATCHDOG` (`service.py:857`). Double-fire safety lives in `service.resume`, not here.
  - Caveat: the module docstring still says "a parked shell is a dead process". That predates the 2026-07-25 ruling: parked shells now stay alive, and resume is usually just a state flip.
- **Talks to:** `PoolService` (`sessions`, `_inbox_depth`, `resume`, `sweep_crashed`) and the broker (`/v1/inbox`, `/v1/channels`, `/v1/publish`).

### `edp-pool/src/edp_pool/pause_watchdog.py` (~230 lines) and `proctree.py` (~535 lines)
- **What:** `proctree` provides process-tree kill, suspend and resume scoped to one pid. `pause_watchdog` is a detached process outside that tree that un-freezes a suspended seat if the pool dies.
- **Why:**
  - The 2026-06-02 incident ("198 shells froze the machine") came from killing only the root pid (`proctree.py:1-17`).
  - A suspend nobody can undo is a leak, so `suspend_tree` refuses to freeze unless the watchdog is armed (`pause_watchdog.py:1-41`).
- **How:**
  - `PoolService.pause_shell` (`service.py:2394`) calls `suspend_tree` (`proctree.py:242`), which arms `pause_watchdog.arm` (`pause_watchdog.py:150`).
  - The watchdog is launched with `edp_contracts.proc.detach` (`proc.py:357`) and is checked to be no descendant of the pool.
  - A run-token file decides whether it fires: missing means stand down, a different run id means stand down, its own run id means fire (`should_fire`, `pause_watchdog.py:88`).
  - `resume_tree` (`proctree.py:348`) releases the token last.
- **Talks to:** psutil and the OS. It is not wired to the broker.

### Harness launchers (`spawner.py` ~440, `composite_spawner.py` ~145, `pty_launcher.py` ~920, `console_launcher.py` ~55, `pi_launcher.py` ~335, `codex_launcher.py` ~230, `shadow_spawner.py`/`shadow.py` ~570/~380, `console_input.py` ~230, `lean_boot.py` ~115)
- **What:** The `Spawner` seam and its backends. Each backend turns `launch(sid, role, handle, mode, …)` into a real Claude, Pi or Codex process.
- **Why:**
  - Shells are visible consoles by default (owner steer m-0259072d19 for GPT seats).
  - A row records the harness that launched it, so a resume never opens the wrong CLI (t-f42af1ca59, owner m-ccbf57c574, `service.py:1562`).
- **How:**
  - **Spawner stack:**
    - `Spawner` is the abstract base, with `harness = "claude"` (`spawner.py:21`). `FakeSpawner` (`:87`) serves tests.
    - `SubprocessSpawner` (`:179`) picks `ConsoleLaunch` for monitor mode (a visible console) or `PtyLaunch` for headless mode (ConPTY drained to a log, `pty_launcher.py:744`). On POSIX, monitor mode falls back to headless (`spawner.py:224`).
  - **Claude argv and env:**
    - `pty_launcher.build_argv`/`build_env`/`build_session_args` assemble the Claude argv and env (`pty_launcher.py:354`, `:589`, `:428`), including `--resume/--session-id/--fork-session` for forks (`:433-446`).
    - `lean_boot.lean_args` trims connectors, skills and tools at boot (S8, `lean_boot.py:109`).
  - **Mixed fleet:**
    - `main.py` stacks `CompositeSpawner` twice: Claude, then Pi, then Codex (`main.py:61`, `:82`).
    - Routing is by `EDP_PI_ROLES`/`EDP_CODEX_ROLES` or by the `models.json` harness (`composite_spawner.py:37`, `catalog_routes_pi` `pi_launcher.py:120`, `catalog_routes_codex` `codex_launcher.py:57`).
    - Pi and Codex seats are resident `edp8.pi_seat.run`/`edp8.codex_seat.run` runners. Identity reaches the board in headers, never in argv.
  - **Shadow wrapper:**
    - When `EDP_SHADOW` is on, `ShadowSpawner` wraps the Claude backend (`main.py:105`, `shadow_spawner.py:256`).
    - Each shadow is a per-shell sidecar. It hosts the rx driver and types framed, nonced wakes into the console through `console_input.inject_line`, a helper process that runs AttachConsole + WriteConsoleInputW (`console_input.py:195`).
- **Talks to:**
  - Called only by `PoolService` (`spawner.launch/alive/kill/pid/exit_code/viewport_died`, plus optional `getattr` hooks).
  - Launches `claude`, `pi` and `codex`, resolved through `edp_contracts.toolpath`.

### Pool support modules
- `main.py` (~150): the uvicorn entry. It builds the spawner stack, then `create_app(spawner, EDP_BROKER_URL, EDP_POOL_STATE)` (`main.py:109`), and binds `EDP_POOL_HOST:EDP_POOL_PORT` (`:121`).
- `doctor.py` (~380): `python -m edp_pool.doctor` and `GET /v1/doctor`. It checks the Claude binary (with repair), broker and pool health, Phoenix, stale locks, seat registry, foreground model and config parity (`doctor.py:309`).
- `pool_config.py` (~165): seeds and upgrades the pool config dir's `settings.json` (hooks, outputStyle) from the shipped template. It never overwrites owner edits (S12, owner m-07507eb2cb; `pool_config.py:47`, `:123`).
- `spawn_defaults.py` (~95): panel-editable spawn defaults that apply to fresh spawns only. Setting `EDP_SKIP_PERMISSIONS` from the panel is deliberately refused (`spawn_defaults.py:67`).
- `http_pool.py` (~70): `HttpPool`, the PoolPort client for older edp-claude consumers. It passes capacity errors through verbatim with `Tool.from_upstream`.

### MCP proxy: `v8/src/edp8/mcp_server.py` (~460 lines; not in edp-pool)
- **What:** The one shared edp8 MCP server on `EDP8_MCP_PORT`. It serves every seat's board tools over stateless streamable HTTP.
- **Why:** One process for the whole fleet instead of two stdio processes per shell (2026-09-06). Restarts are invisible to seats, and a tool fix reaches every seat on its next call.
- **How:**
  - Routes (`mcp_server.py:351-400`):
    - one `/mcp/<role>` per built-in role (`:368`);
    - a catch-all `/mcp/{role}` for custom workflow roles, served the kernel bundle (`:384`);
    - `/healthz` (`:385`);
    - `/browser/release/{session}` (`:400`).
  - Identity comes from the `X-Participant`/`X-Session` headers (`_identity_from`, `:68`). `allowed_tool_names` scopes the tool list by caller role, workflow bundle and path role, and adds the proxied `browser_*` tools for agents (`:128`).
  - `run_http()` binds `EDP8_MCP_HOST:EDP8_MCP_PORT` (`:417`). `--stdio` or `EDP8_MCP_TRANSPORT=stdio` selects the old per-shell mode (`:451`).
- **Talks to:** Called by every seat's `.mcp.json`, by Pi/Codex headers and by the board's browser release. It calls the board HTTP API through a per-request `BoardClient`, and the shared Playwright MCP (`edp8.browser_proxy`).

### `edp-broker/src/edp_broker/` (`service.py` ~300, `store.py` ~315, `main.py` ~57)
- **What:** The message broker. Every message is appended to a durable JSONL inbox for its recipient. The broker also serves inbox reads, queries, aliases, channels and a live SSE stream.
- **Why:** One envelope and one durable store for all traffic between shells (DESIGN-v4 §13.3), so a parked or crashed reader loses nothing.
- **How:**
  - **Publish:** `POST /v1/publish` validates a `BrokerMessage`. An unregistered kind returns 409 `broker_unregistered_kind`; an unroutable recipient returns 409 `broker_no_route`. The store IO runs off the event loop (F36 R4#10), and the publish then wakes the `StreamHub` (`service.py:101-131`, hub `:53`).
  - **Append:** `InboxStore.append` resolves aliases. It stamps `ts` forward under a lock, so each inbox file is strictly ordered and a `ts > cursor` reader never misses a message (F34 R2 #6, `store.py:198`). On disk, `:` in a recipient becomes `_` (Windows ADS, `store.py:20`).
  - **Read:** `GET /v1/inbox/{recipient}?since_ts=` (`service.py:133`). `read()` skips torn lines and filters each message by its resolved destination (F34 R2 #7/#11, `store.py:218`).
  - **SSE and other routes:** `GET /v1/events?recipient=&since_ts=&max_seconds=` replays the backlog, then pushes new messages as `data:` frames with keep-alives (`service.py:236`).
  - Other routes: `/v1/messages` and `/v1/message/{id}` (`:204`, `:226`), channels PUT/PATCH/GET/DELETE (`:152-201`, `ChannelStore` `store.py:85`) and `/v1/alias` (s16, `service.py:283`).
  - Startup: `main.py` creates the app on `EDP_BROKER_DATA` and binds `EDP_BROKER_HOST:EDP_BROKER_PORT` (`main.py:15`, `:21-24`).
- **Talks to:**
  - Called by: the pool (watchdog inbox depth, crash publish, panel publish), seat feed drivers (`v8/src/edp8/feed_driver.py:306`), the Slack bridge (`v8/src/edp8/slack_bridge.py:126`) and the board.
  - It calls nothing.

### `edp-contracts/src/edp_contracts/` (shared contracts)
- **What:** A package that depends only on pydantic and the standard library. It holds the contracts the board, pool and broker all import: settings, envelopes, error codes, broker kinds, process helpers and the service base.
- **Why:** Every shared contract has exactly one source, so the protocol cannot fork (HLD §5). Only `__init__` re-exports are public.
- **How:**
  - **Settings registry (`settings/`):**
    - `declare(key, env, type, default, …)` registers each setting (`settings/_core.py:70`). `get()` resolves env, then `config.toml`, then the default, live on every call (`:239`).
    - Settings are the only reader of `os.environ` in the four packages' source trees (design-e963c656f5 §4.2).
    - Keys are split by owner: `keys_common` (dirs, identity `EDP_HANDLE`/`EDP8_TOKEN` `:50-56`, URLs and ports `:67-157`), `keys_pool` (state path `:30`, caps `:119-129`, `EDP_RESUME_WATCHDOG` `:147`), `keys_broker` (`EDP_BROKER_DATA` `:6`), `keys_board` and `keys_seats`.
    - `secrets.py` creates and checks private token files.
  - **Error envelope and codes:**
    - `ToolOk` / `ToolError{ok:false, source, code, message, retryable}` (`tool.py:21`, `:30`).
    - `Tool.propagate` (`:91`) and `Tool.from_upstream` are the only ways to build an error, and both keep the upstream text verbatim (DESIGN-v4 §13.2).
    - `ErrorCode` enum: tool, pool (`pool_capacity_exceeded`, `pool_spawn_failed`, `pool_unknown_handle`, `pool_role_refused`), broker, fsm (`errors.py:17`). Only capacity errors are retryable (`:45`).
    - Pool and broker both return the envelope with HTTP 409.
  - **Broker kinds:** `BrokerMessage{msg_id, ts, from, to, kind, body, corr_id}` rejects unregistered kinds (`broker.py:117`, `:135`). `CORE_KINDS` (spawned, ready, done, crashed, question, answer, steer, …) are registered at import (`broker.py:46`, `:113`).
  - **Service base:** `Microservice` + `mount()` give each service the same `/v1/health`, startup/shutdown wiring and catch-all envelope (`service.py:46`, `:67`). `identity.py` adds a `home_id` to health, so the launcher never adopts another home's service (t-596660619c).
  - **Processes and the rest:**
    - `proc.py`: `ProcId{pid, create_time, name}` (`:40`), `kill_tree` (`:192`) and `detach` (`:357`). Every stop and pause uses them (S2 strategyll-3b8f4033e0).
    - `roles.py`: `non_agent_refusal`, owner m-da9a2ae62f (`roles.py:30`).
    - `seats.py`: the `models.json` seat catalog and effort caps (`seats.py:232`, `:101`).
    - `toolpath.py`: external binary resolution.
    - `prereqs.py`: the install manifest.
    - `logging.py`: the JSON line schema.
    - `skill.py`: skill front-matter checks.
    - `browser_tool.py`: install of the shared Playwright MCP.
- **Talks to:** Imported by edp-pool, edp-broker and `v8/src/edp8` (board, MCP server, CLI). It makes no network calls of its own.

## Everything that is not Python service code

### v8/.claude/commands/*.md (role cards)
- **What:** the slash-command card each seat boots with (`/architect`, `/engineer` …). Shared boot line on six of them: `get_guide('shared-host-rules')` § Seat basics; when resumed, `resume_self()`; heartbeat `context_delta(cursor=…)`, plus `get_guide('context-refresh')`.
  - `adversary.md` (1747 B): one bounded hostile review round on the codex model, or Fable `claude-fable-5-1` when no codex seat is picked. Names each probe it could not run. Writes a findings report and an adversarial gate.
  - `architect.md` (3341 B): writes the design on the board (owner m-b0a7f9cda9: no EnterPlanMode). Reads lessons first with `lookup`, then `doc_create(design)` from `get_guide('design-template')`, then tickets, criteria and gates. Rules on /deviation reports.
  - `doctor.md` (2402 B): the Help seat, resident on a `help` topic. Read-only plus `propose_fix`. Its boot is different: `whoami → subscribe → monitor → context`, and `resume_self()` first when resumed.
  - `engineer-quick.md` (1979 B): the owner's single quick task (owner m-b13c61ddea). Writes a design note with 1–2 criteria; `in_progress` is refused until the owner signs off; then it builds.
  - `engineer.md` (2081 B): one story end to end. Reads the design head and linked strategy heads, writes a plan doc, works, records evidence, hands off.
  - `qa.md` (2511 B): the cold, last, only checker of an epic. Uses `asks(epic)`, runs the thing, judges the epic's words, ends with /harvest.
  - `sme.md` (3760 B): craft author (hl-craft or ll-craft). Reuses or extends strategy and domain docs before writing new ones.
- **Why:** the card is the seat's whole protocol. `v8/tests/test_s9_card_byte_budget.py` holds cards and skills to a byte budget (c-fad33cf7c2), and `v8/tests/test_skill_tool_scope.py` checks that every tool a card names is in that role's bundle.
- **How:** the pool launches the harness with the card as its command. Board-pinned workflow versions can write their own card copies through `Board.materialise_card` / `materialise_pinned_cards` (`v8/src/edp8/board.py:178,306`).

### v8/.claude/skills/*/SKILL.md
- **What:** one file per skill, triggered by its `description:` line.
  - `demo` (389 B): show an artifact to the owner as soon as it exists, and record their reaction.
  - `deviation` (603 B): the design or a strategy cannot be followed as written.
  - `doc-read` (1647 B): read a doc head-first (summary, heading map), then only the sections needed.
  - `doc-write` (4109 B): summary-first doc writing, for any doc type.
  - `doubt` (437 B): name who owns the decision and ask one question with options; never guess.
  - `epic` (2506 B): the epic walk on `standard@1`; for another pin, use `ticket_read(include='lifecycle')`.
  - `handoff` (380 B): status, what is done and what is next, before the shell closes or compacts.
  - `harvest` (2097 B, qa only): qa's last step, including `harvest_cost`.
  - `learn` (1209 B): propose a reusable lesson.
  - `methodology` (530 B): read the strategy_hl docs for the work_type before writing code.
  - `ocak` (988 B): a completeness audit of a design draft after the reasoning is done.
  - `pain` (1557 B): report when a tool or guide disagrees with reality.
  - `ticket` (3613 B): one ticket's walk, story or quick.
  - `verify` (880 B): run each criterion's check yourself and record the actual result.
- **Why:** behaviour that every role shares lives in one place and is loaded only when it applies.
- **How:** `<!-- roles: a, b -->` at the top of a skill or guide narrows which roles it applies to. Only `test_skill_tool_scope.py` reads this marker.

### v8/.claude/output-styles/edp-terse.md (1948 B)
- **What/Why:** a pyramid-shaped style with no ritual, because no human reads the shell. It is the single source for this style.
- **How:** set by `"outputStyle": "edp-terse"` in the pool's settings template (`edp-pool/src/edp_pool/claude_pool_template/settings.json`).

### v8/.claude/hooks/*.py
- **What/When:** all four are registered in the pool settings template above, not in `v8/.claude/settings.json`. Each runs as `${CLAUDE_PROJECT_DIR}/.venv/Scripts/python.exe …/.claude/hooks/<x>.py`.
  - `guard-destructive.py` (3133 B), **PreToolUse** on Bash and on PowerShell. Denies kills by name or image of python, node, claude, uvicorn or conhost, and allows kills by PID. Cause: on 2026-05-31 a `taskkill /F /IM python.exe` took down the whole stack.
  - `rtk-pretooluse.py` (13285 B), **PreToolUse** on Bash only. Lets `rtk` compress command output (DESIGN-v6 W6). Three gates must all pass, the last being `rtk rewrite` as the authority, and `EDP_RTK=1` is required. Otherwise the command passes through unchanged. Why: an older version dropped a leading `cd` or assignment (measured s30/a2b).
  - `pool-ping.py` (1571 B), **PostToolUse + Stop**: `POST /v1/turn_ping/<sid>` (busy heartbeat). **SessionEnd** (`end` arg): `POST /v1/session_end/<sid>`. It exits at once when `EDP_SPAWN_SESSION_ID` is unset. This is the pool's only reliable signal of busy or exit.
  - `notify-user.py` (5601 B), **Notification** (`permission_prompt|agent_needs_input|idle_prompt|elicitation_dialog`). Raises a WinRT toast, rate-limited, gated by `EDP_TOASTS`. For a seat stopped at an interactive prompt it also posts a `question` to the owner on its ticket (pain p-73d192bf, owner m-705c0a47f6). It never blocks: any failure lets the shell continue.
  - The template also has an inline **SessionStart(compact)** hook that tells the seat to call `resume_self()` and then `context()`.

### v8/.claude/settings.json (1046 B)
- **What:** settings for a seat that runs in the dev checkout: read-only `mcp__edp8__*` tools and npm/node allowed, artifact skills turned off.
- **Note:** materialise does not ship this file (it is not in PAYLOAD). Installed seats get their settings from the pool template.

### v8/guides/*.md
- **What:** on-demand guides served by `get_guide(name)`. `v8/src/edp8/guides.py` reads them from an allowlist (epic-0cec8d1c31 S9): names are matched against the folder listing and never joined into a path.
  - `agent-tools.md`: `describe` / `describe_objects` workflows and enums.
  - `codex-images.md`: asking a codex seat for images (architect, engineer, adversary).
  - `context-refresh.md`: when to call `context()` and when `context_delta`.
  - `design-template.md`: the architect's design template, per work_type.
  - `resume.md`: what a resumed seat does (owner ruling m-268fc869f5).
  - `shared-host-rules.md` (9744 B, the largest): git tree, services and `edp.ps1`, capacity, codex seats, idle wakes.
  - `strategy-creative-reference-then-build.md`: the strategy_hl for creative and UI work.
  - Nine `troubleshooting-*.md` files for the doctor: broker-dead-mail, caps-saturated, feed-lag, harness-login, mcp-401, pool-port-exhaustion, service-down, stuck-ticket, update-failed.
- **Why:** detail a seat needs only sometimes stays out of the card's byte budget.

### v8/.mcp.json (304 B)
- **What/How:** a single HTTP MCP server `edp8` at `${EDP8_MCP_URL:-http://127.0.0.1:9402}/mcp/${EDP_ROLE}`. It sends the headers `X-Participant=$EDP_HANDLE`, `X-Session=$EDP_SPAWN_SESSION_ID` and `X-Token=$EDP8_TOKEN`. The role in the URL picks the tool bundle.

### v8/models.json (6161 B)
- **What:** the seat and model registry.
  - `seats`: exact model ids, effort, `context_window`, `auto_compact` (350k on every seat, owner ruling 2026-08-06).
  - `roles`, `role_models`: per-role catalogs, where the first entry is the default (S-ROLES design-34bf11cc07 §4.1).
  - `roles_openai`: the Pi/codex option.
  - `default_model`: `claude-opus-5-5`.
  - `models`: harness, provider and effort_cap for each model.
- **Why:** one file changes the whole fleet with no code edits. The `_*_note` keys in the file record each ruling.
- **How:** the copy in the data dir is merged with newly shipped rows at init and at every board start, and owner edits are kept (`model_catalog.materialise`).

### v8/CLAUDE.md (884 B)
- **What:** the environment preamble for every seat: Windows/uv, the agent-home layout, identity from `EDP_HANDLE`, and the no-shell-prose rule (owner m-45f5a9e954).

### How the agent home gets installed: v8/src/edp8/materialise.py
- **What:** `PAYLOAD` (`materialise.py:27`) lists `.claude/commands`, `.claude/skills`, `.claude/output-styles`, `.claude/hooks`, `guides`, `.mcp.json`, `models.json` and `CLAUDE.md`.
  - These ship in the wheel as `edp8/agent_home/…`, through hatch force-include in `v8/pyproject.toml:58-70`. That list must be kept in step with `PAYLOAD` by hand.
- **How:** `materialise(target)` (`:126`) copies the files under the dpkg-conffile rule table (strategyhl-86b4805322 §2), using a `.manifest.json` of sha256 hashes:
  - files the user has not edited are overwritten;
  - files the user edited are kept and reported as conflicts, with the new shipped version written beside them as `<file>.new`;
  - files the user deleted stay deleted;
  - every write is atomic.
- **Callers:**
  - `heronry init` → `setup.py:353`.
  - Every board start → `materialise.refresh()` from `service.create_app` (`service.py:433`, RC2 t-e338298d88), so an MSI upgrade also refreshes the cards.
- **Dev mode:** a source checkout is the live agent home, so nothing is copied there.
- **Tests:** `v8/tests/test_agent_home.py`, `test_agent_home_kinds.py`, `test_e2e_agent_home.py`.

### v8/web (the SPA, "Folio")
- **What:** React 19, react-router 8 and TanStack Query 5, built with Vite 8 (`v8/web/package.json`). Tests use vitest + msw for units and Playwright for e2e.
  - Build output: `v8/src/edp8/webapp/dist`, which is gitignored and force-included in the wheel (`vite.config.ts:51`).
  - The board serves it under `/ui/` (`viteBase.ts`, `EDP8_WEB_BASE`).
  - `vite dev` proxies `/v1`, `/ui/poll` and `/healthz` to the board.
- **Why:** the owner's whole surface: epics, tickets, docs, gates and seats. No shell is needed.
- **How (entry):**
  - `src/main.tsx`: the router basename comes from `BASE_URL`. It preloads the chunk of the route matched at boot (S22).
  - `src/routes.tsx:50`: the single route table, under one `AppShell` layout with a `PageError` boundary (t-b2f8859d30). `src/test/deadControls.test.tsx` walks this same table.
  - Guarding the build stamp against the running board: `src/live/boardVersion.ts` with `components/BoardVersionBanner.tsx`.

#### v8/web/src/api — talking to the board
- `client.ts`: the only envelope unwrap. Every response is `{ok, value, hint, error}`. `api()` reads; `apiEnvelope`/`postJson` writes return the board's `hint` verbatim, and a failure throws a typed `BoardApiError`. Auth headers come from `src/auth/identity.ts` (`X-Participant`, `X-Token`).
- `endpoints.ts` / `types.ts`: typed wrappers and payloads.
- Domain files: `admin.ts`, `seats.ts`, `workflows.ts`, `prereqs.ts`, `access.ts`, `review.ts`, `notifications.ts`.
- `attention.ts`: `GET /v1/me/attention`, the one list of what waits on the viewer (S20, design-e963c656f5 §4.18). Each item carries its path: scope → tab → section → ticket → item.
- `asksLedger.ts`: `GET /v1/epics/{id}/asks?criteria=text` (S16/e0cec). It returns six ask states and the board's `blocked_reason`.

#### v8/web/src/live — the live feed
- `feed.ts`: `subscribeFeed` reads `/v1/feed` (SSE) with fetch and a stream reader. EventSource is not used because it cannot send the auth headers.
  - On reconnect it resumes from the last `seq`.
  - A 45 s read watchdog runs against the board's 15 s pings.
  - After two failures in a row it falls back to polling `/v1/events`.
  - `: resync` triggers an immediate reconnect.
  - `watch=true` (S19) gives the page's view feed.
- `useDraftGuard.tsx`: one view feed per app. Each event invalidates only the queries `affectedQueries.ts` maps it to, coalesced in a 250 ms window. It also keeps dirty drafts from being clobbered or navigated away from.

#### v8/web/src/pages — by route
- `Epics.tsx` (`/epics`, also the landing page): the portfolio. The `status`/`q` filters are in the URL.
- `Epic.tsx` (`/epic/:id`) and `Ticket.tsx` (`/ticket/:id`): both use the shared `WorkHeader` over `Conversation` and `Composer`. Controls are under "Actions ▾" (design-a2e5369133).
- `Doc.tsx`, `Records.tsx`, `Artifact.tsx`: single-object pages.
- `Library.tsx` (`/library/:section`): Knowledge (S-LIBRARY design-34bf11cc07 §4.3), Documents, Artifacts, Links, Tickets and History.
  - Related files: `Knowledge*.tsx`, `LessonDetail.tsx`, `Topics.tsx`, `TopicPage.tsx`, `Pains.tsx`.
- `Seats.tsx` and `Settings.tsx`.
- `Code.tsx` (`/code`, `/code/faq`): an iframe to code-server, with the port taken from `GET /v1/code` (epic-91fcd3b370 S3).
- `admin/` (`/admin`, `/join`, `/setup`): Services, Teammates, Models/SeatsModels, Integrations, Remote, CutRelease, SetupTools and the Join/Setup wizard.
- `design/` (`/design`): the workflow designer. Files: `PipelineView`, `pipelineLayout`, `RolePanel`, `PolicyPanels`, `CheckPanels`, `WorkflowList`.

#### v8/web/src/components — main pieces
- `AppShell.tsx`: the left rail with brand, Epics, Seats, the current-epic block, Find and the account row. Epics and Library carry attention-dot counts.
- **"Needs you":** the `/me` page was removed in S20 and now redirects to `/epics` (`routes.tsx:57-60`). What waits on the viewer is shown as a trail of dots, each hop reading `api/attention.ts`:
  - `AttentionDot.tsx`: a glyph plus count plus aria-label, never colour alone.
  - `AttentionAsks.tsx`: a clickable "N unanswered" badge that jumps to the message (owner m-ec5a9b86c5).
  - `NotificationCenter.tsx`: a headless poll plus native or desktop toasts (S10/S11).
- **Asks ledger:** `AsksLedger.tsx` sits on the epic page.
  - Each row shows its state as a word, quotes the owner's words (clamped) and links the covering criterion.
  - The acceptance gate's caption shows the board's `blocked_reason` verbatim.
  - `TicketAsks.tsx` is the per-ticket view.
- **Composer:** `Composer.tsx` (31 KB), plus `ExpandableComposer`, `MentionInput`, `draftStorage`, `useDropUpload`.
  - It carries kind, `to` and text, and it never fans out.
  - The wake preview comes from `POST /v1/messages/resolve`.
  - After sending, it shows the board's resolution `hint` verbatim (design §13).
- **Work drawer:** `WorkHeader.tsx` shows a status/owner/assigned/needs-attention grid and a links row: Design, Files & evidence, History, Work.
  - `?view=files|history|work` opens the right `Drawer.tsx` (1112 px, focus-trapped).
  - `ContextualWork.tsx` reads `GET /v1/tickets/{id}/contextual`.
  - The Work view shows stories, kanban, criteria and process for an epic, and criteria and docs for a ticket.
  - `DocDrawer.tsx`: `?doc=<id>` opens docs in place, with a back-stack of depth 3.
  - `RulingDrawer.tsx` is in the same family.
- Others:
  - `ProcessStrip` (stage plus next action).
  - `GateForm`, `GateOpenControl`, `SignoffPane`, `DesignReview`, `CriterionCard`.
  - `CommandPalette` (Ctrl-K over `GET /v1/find`).
  - `SpawnSeatForm`, `SeatPicks`, `ModelsControl`.
  - `QuoteLayer` / `QuoteCard`.
- Elsewhere in `src/`:
  - `src/desktop/shell.ts`: the pywebview bridge (desktop toasts, external links).
  - `src/theme/`: tokens and contrast tests.
  - `src/copy/`: glossary and page copy.
  - `src/auth/guest.tsx`: guest scope (e0cec S5).

### v8/vscode-ext/edp-code (the "Heronry Chat" / EDP Chat extension)
- **What:** a VS Code extension (name `edp-code`, publisher `edp`, v0.10.4) for the Code tab's code-server (design-449b628cdd §4, epic-91fcd3b370 S5).
  - A secondary-sidebar webview `edp.chat` that shows ticket and epic threads.
  - "Tag selection on board" (Ctrl+Alt+M) posts a message with `code_context`.
  - Doc reader and design approve/reject, quotes into chat, change cards from git, a live-seats status bar, guarded checkout/merge/pull, and an external terminal.
- **Why:** humans talk to seats from the code beside them, and the board stays the record.
- **How:**
  - Settings: `edp.boardUrl` (default `http://127.0.0.1:9400`, machine-scoped; credentials go only to loopback or https), `edp.sharedTreePaths`, `edp.chat.commitWindow`, `edp.externalTerminal`.
  - Sign-in stores the participant id and token in VS Code secret storage.
  - `src/core/` is pure logic, tested by vitest with no VS Code: `api.ts`, `sse.ts` (a WHATWG SSE parser), `feed.ts`, `inbox.ts`, `reader.ts`, `quotes.ts` and others.
  - `src/vscode/` is the host glue, with `extension.ts` as the entry; activation is `onStartupFinished`/`onUri`.
  - `webview/` holds the chat UI.
- **Packaging:** `npm run package` runs tsc, then esbuild to `dist/extension.js`, then `vsce` to produce `edp-code.vsix` (gitignored).
  - `v8/hatch_build.py:73` puts the vsix into the wheel. A missing vsix only warns, unless `EDP8_REQUIRE_VSIX=1`.
  - `heronry start code` installs it (`edp8/code_service.py`).
- **Related pins:** `v8/vscode-ext/code-server.lock.json`, `extensions.txt` and `extensions.lock.json`. `edp-chat-spike/` is the earlier spike.

### v8/desktop (Heronry Desktop, Briefcase)
- **What:** native installers made with BeeWare Briefcase (design-e963c656f5 §4.9, S8 s-6dcf78f803): a per-user Windows `.msi`, a macOS arm64 `.dmg` and a Linux `.deb` for ubuntu noble. There is no AppImage or Flatpak (strategyhl-5af811e7bd §3).
- **How:**
  - `desktop/pyproject.toml` bundles the four wheels from `./wheels` plus fastembed, pywebview and pystray.
  - `src/heronry/__main__.py` is the single entry point:
    - `--heronry-service <svc>` re-enters a service before any GUI import;
    - a CLI verb runs `heronry`;
    - no argument opens the GUI (`edp8/desktop.py`: a pywebview window plus tray). The GUI calls the same `edp8.cli` commands and owns no service.
- **Scripts:**
  - `scripts/build_windows.ps1`: builds the MSI.
  - `scripts/patch_wxs.ps1`: an idempotent patch of the release `.wxs` (S10).
  - `scripts/drill_bundle_{windows.ps1,posix.sh}`: a clean-profile service re-entry drill (c-eb38e8c949).
  - `scripts/drill_remote_code_port_windows.ps1`: t-cd13d98674.
  - `scripts/heronry.cmd`.
- **Other installers:** repo-root `install.ps1` and `install.sh` (S3 s-870e401942):
  - check uv's sha256;
  - verify the four wheels against `SHA256SUMS`;
  - run `uv tool install --force "edp8[embed] @ <wheel>" --with …`.

### .github/workflows/*.yml
- `ci.yml`
  - Triggers: push, pull_request, dispatch.
  - `pii-gate`: gitleaks plus `pii_gate.py`. It blocks.
  - `test`: windows, macos and ubuntu. pytest for edp-contracts, edp-pool, edp-broker and v8; vitest for web and edp-code.
  - `security`: bandit, semgrep and pip-audit (`.github/security/`).
  - `install-smoke`: calls `install.yml`.
- `install.yml`
  - Triggers: workflow_call, dispatch.
  - `wheels`, `posix`, `windows`: run the one-line installers into a clean home, then init → start → `/v1/health` + `/ui` → a stub seat → stop (`v8/scripts/drill_install_*`).
- `installers.yml`
  - Triggers: workflow_call, dispatch, and pull_request on desktop, launcher or edp-code paths.
  - `wheels`, `windows` (.msi), `macos` (arm64 .dmg), `linux` (.deb), `vscode` (.vsix). Each runs the bundle re-entry drill.
- `process-layer.yml`
  - Triggers: push and PR on process-layer paths, dispatch.
  - `contracts-and-pool`, `supervisor`: PTY, tree-kill and supervisor tests on all three OSes (S2 s-b7ec13d748).
- `release.yml`
  - Triggers: a `v*` tag push, or dispatch (Admin → Cut release; `dry_run` defaults to true).
  - `prepare` → `python-dist` → `installers` → `assets` (SHA256SUMS, PII gate) → `attest` → `draft`.
  - `publish` runs only on dispatch with `publish: true`. A tag push stops at the draft; GitHub Releases only, no PyPI (S9/S10).
- `site.yml`
  - Triggers: PR and push on site or src paths, release published, dispatch.
  - `check`: `mkdocs build --strict`, the site tests and the PII scan.
  - `deploy`: mike to gh-pages.
- Also: `.github/dependabot.yml` keeps the action SHA pins current.

### .github/scripts
- `pii_gate.py`: a byte-level PII scan of tracked files and release artifacts. The needles come from the `PII_NEEDLES` secret or a gitignored `.pii-needles.toml`, never from the tree.
- `check_dist.py`: the release manifest guard. It enforces excluded prefixes and size ceilings (tested in `v8/tests/test_check_dist.py`).
- `security_inputs.py`: writes the dependency `.in` files for pip-audit.

### docs/site (MkDocs Material site)
- **What:** the public Heronry site:
  - Home, Download, Video;
  - `docs/setup/`;
  - the product guide in `docs/guide/*.md` (index, conversation, work, vscode, anywhere);
  - `docs/docs/*.md` (concepts, design-tab, troubleshooting, updates);
  - the generated `docs/reference/`.
  - Versions are published with mike (design-e963c656f5 §4.15).
- **How:**
  - `mkdocs.yml` registers `hooks/heronry_site.py`. That hook fills names and URLs from `edp8.brand`, fills Download from the latest release (`fixtures/release-latest.json` offline), copies the brand art and runs `hooks/pii_scan.py` in `on_post_build`.
  - `hooks/sitegen.py` generates the reference from the code, so it is never edited by hand: the CLI from `edp8.cli.COMMANDS`, settings, the REST API from OpenAPI, MCP tools from `edp8.bundles`, the workflow schema and `MODEL_FIELD_DOCS`.
  - `tool-docs.yml` holds docs-only tool explanations; a test fails when it drifts from `bundles.py`.
  - `tool-examples.json` is captured by `tools/capture_tool_examples.py`.
- **Guide screenshots:** `v8/web/playwright.guide.config.ts` runs `v8/web/guide/*.spec.ts` (s-bcc0c06de7, owner m-67c4136530).
  - Each run uses a throwaway board seeded with the made-up Tidewater project (`guide/demo.seed.ts`).
  - `guide.spec.ts` writes PNGs to `docs/site/docs/assets/guide/`.
  - `tools.spec.ts` drives the tool-examples capture (s-bd0cf6288c).
  - `vscode.spec.ts` shoots the EDP Chat panel in a real code-server.
- **Tests:** `v8/tests/test_site_reference.py`, `test_site_guide.py`, `test_site_tool_docs.py`.

### v8/tests (pytest, `testpaths = ["tests"]`, asyncio auto)
- **Layout:** flat, about 238 `test_*.py` files. Names show where each test came from:
  - `test_s<N>_*`: an epic story, e.g. `test_s16_lifecycle_guards.py`, `test_s22_bounded_feed.py`.
  - `test_e0cec_s<N>_*`: stories of epic e0cec.
  - `test_rc2_*`, `test_v091_*`: release candidates.
  - Otherwise named by subsystem: `test_admin_*`, `test_codex_*`, `test_update_*`, `test_code_*`, `test_tool_*`, `test_workflow_*`, `test_pool_*`, `test_mcp_*`, `test_launcher_*`.
- **Agent-home guards:**
  - `test_agent_home*.py`, `test_e2e_agent_home.py`;
  - `test_s9_card_byte_budget.py`, `test_skill_tool_scope.py`, `test_guides_s9.py`;
  - `test_s16_lifecycle_skills.py`, `test_codex_seat_skills.py`.
- **Packaging and installer guards:** `test_code_vsix_in_wheel.py`, `test_desktop*.py`, `test_msi_wxs_patch.py`, `test_install_scripts.py`, `test_check_dist.py`, `test_pii_gate.py`.
- **Rigs:**
  - `conftest.py`: autouse `ui_prefix` (legacy vs folio `/ui` mount, c-a8c1be7137), autouse `isolated_tokens` (never reads the host's tokens.json), and `DEAD_PORT`.
  - `admin_support.py`: an in-process token-mode board with owner, bob and eng.x.
  - `asks_support.py`.
  - `fixtures/`: `briefcase_heronry.wxs`, `code_server_stub.py`, `models_pre_s12.json`, ref and mention cases.
  - `codex_seat/` (`fake_app_server.py`), `pi_ext/` (fake Pi harness, oracle traces), `rsi/`, `data/`.

### v8/web tests
- **Unit:** vitest under jsdom; files are `src/**/*.test.ts(x)`, set up in `src/test/setup.ts`.
  - msw handlers in `src/test/handlers.ts` return the board's envelope.
  - Run it with `npm test` (watch is off, S22).
- **e2e:** about 79 specs in `v8/web/e2e/*.spec.ts`, run with Playwright, win32 only, `workers: 1`, 1440×900, on a pinned chromium-1234 (`playwright.config.ts`). Specs are named by story or round: `g2-*`, `g3a-*`, `s16-asks-ledger`, `qa-*`, `code-*`, `axe.spec.ts`, `fidelity.spec.ts`.
  - `globalSetup.ts` checks that the `/ui` bundle is fresh.
  - `fixtures.ts` gives a private board for each file.
  - `hermeticEnv.ts` uses a private EDP_HOME and seeds the agent home.
  - Seeds: `g2.seed.ts`, `g3a.seed.ts`, `g3b.seed.ts`.
  - Baselines are in `e2e/__screenshots__`; `web/tests/fidelity/README.md` gives the visual thresholds (c-80b50710a6).
  - Firefox variants: `playwright.s6-firefox.config.ts`, `playwright.s8-firefox.config.ts`.
- **edp-code:** vitest over `src/core`, in `v8/vscode-ext/edp-code/test/*.test.ts`.

## What runs on its own

Everything the system does without a seat or a person calling for it: 70 items across the board, pool, feed
driver, supervisor and desktop app. The kinds are:

| Kind | Meaning |
|---|---|
| A | Ticket or epic status transition |
| B | Starts, resumes, revives or stops a seat or process |
| C | Creates work for the owner |
| D | Posts a message or page |
| E | Infrastructure self-healing |
| F | Other |

Each verdict is the architect's proposal. Nothing is changed until the owner agrees.

| Verdict | Count | Meaning |
|---|---|---|
| keep | 45 | State transitions, infrastructure and records; fine as they are |
| hint | 10 | The board stops starting seats or staffing qa, and instead tells the architect what is due |
| remove | 4 | Owner-facing noise: held-pairing questions, the board opening the acceptance gate, owner feed paging, the 30-minute resume of every parked shell |
| fix | 4 | Crash and closed-seat pages go to the architect first; broker status copies respect the feed filter; the feed heartbeat never fires |
| replace | 3 | The asks ledger: see below |
| change | 1 | Quick-task lines are checked by qa, not the owner |
| review | 3 | Measure before deciding |

The verbatim code for every kind B and C item is in [harness-map/runs-on-its-own.md](harness-map/runs-on-its-own.md). The table below
gives the file:line references to read.

| # | Kind | What happens | Trigger | Code | Verdict | Note |
|---|---|---|---|---|---|---|
| 1 | B/F | Board pool-watch thread: mirror sessions + drain pairing queue every 10 s | Board start if EDP_POOL_URL or EDP8_POOL_WATCH | `v8/src/edp8/service.py:2193-2220` | hint | keep the session mirror; the pairing drain goes (see 6) |
| 2 | F | Pool sessions mirrored to board as alive/dead | Pool-watch tick | `v8/src/edp8/pool_adapter.py:259-318` | keep |  |
| 3 | D/B | shell_dead/stalled event; epic checkers requeued | Mirrored death/stall | `board.py:2600-2632` | hint | keep the event; the checker requeue becomes a hint to the architect |
| 4 | D/C | "crashed"/"fyi" broker page to recovery seat (epic owner first) | PUT /v1/sessions death | `v8/src/edp8/service.py:1622-1634` | fix | architect first, never the owner first |
| 5 | F | Dead seat's browser session closed | Same | `v8/src/edp8/service.py:1617-1621` | keep |  |
| 6 | B/D | run_pending_pairings: spawn/resume seat; "queued"/"spawn failed" notes | Pool-watch tick | `board.py:1271-1317` | hint | board says 'qa is due on <epic>'; the architect spawns |
| 7 | B | _spawn_seat/_resume_saved_seat: participant, token, resume or spawn | From #6 | `board.py:1344-1423` | hint | called only by the architect's spawn |
| 8 | C/D | Boot rebuilds owed pairings as held; one question to architect, else owner | Board constructor | `board.py:269-270, 1294-1298, 1319-1342` | remove | goes with 6 |
| 9 | B | stage_qa queues qa.<epic> when qa_ready and qa owes a verdict | #15, #11, #12, boot rebuild | `board.py:2865-2870` | hint | hint, not a queue |
| 10 | C | open_acceptance: board opens acceptance gate (by="board") when ledger clear | _stage_acceptance | `board.py:2872-2881` | remove | the architect posts the acceptance summary in chat; you answer there |
| 11 | C/B | after_ledger_change retries #9 + #10 | ask_triage, ask_verdict, criterion reword | `board.py:2883-2893; asks.py:162, 262` | hint | follows 9/10 |
| 12 | B/A | gate_open staffs qa (acceptance) / auto-carries epic (design_signoff) | Any gate_open | `board.py:2413-2416, 2433-2438` | hint | keep the design_signoff carry; drop the qa staffing |
| 13 | A | _advance_epic_phase: forward-only epic move, by board | #14, #15, #18, #23 | `board.py:667-686` | keep |  |
| 14 | A | auto_carry drafted→designed | design_ref set; criterion added; design_signoff opened | `board.py:1017-1039, 985, 1542, 2416` | keep |  |
| 15 | A/C | Epic → in_review when all stories released (stages qa, opens acceptance) | Child/epic status change | `board.py:1140-1149, 1194-1199` | hint | keep the epic → in_review move; drop staging and the gate |
| 16 | A | Parent ready/signed_off → in_progress when a child is active | Child status change | `board.py:1164-1169` | keep |  |
| 17 | A | Epic in_review → in_progress on story reopen | Child in_progress/blocked | `board.py:1170-1176` | keep |  |
| 18 | A | Epic drafted/designed → in_progress when a child starts | Child status change | `board.py:1177-1186` | keep |  |
| 19 | D | Note event "all tasks done; hand the story to review" | Last task released | `board.py:1200-1201` | keep |  |
| 20 | A | Successors signed_off → ready when all blockers released | Ticket released | `board.py:1102-1125` | keep |  |
| 21 | A | Own signed_off → ready | Own status change | `board.py:1150-1156` | keep |  |
| 22 | A | ready → signed_off on new unreleased blocker | link_create(blocks) | `board.py:1976-1993` | keep |  |
| 23 | A | Design sign-off answer → epic signed_off; descendants released | Owner answers design_signoff | `board.py:2556-2571` | keep |  |
| 24 | A | _auto_advance in_review → done when all criteria passed | Criterion update; hand-off; message on active non-epic; epic in_review | `board.py:1753-1772, 1724, 975-981, 2343-2347` | keep |  |
| 25 | A | Quick task in_review → in_progress | Owner fails its criterion | `board.py:1740-1751` | keep |  |
| 26 | A/C | Terminal ticket's open gates closed, by board | Status → done/partial/dropped | `board.py:1132-1133, 2592-2597` | keep |  |
| 27 | B/D | requeue_checkers: queue fresh checker for stuck criteria (cap 3) + note | in_review; record_status done/handed_off/reviewed; seat death | `board.py:2988-3031, 1134-1135, 3325-3326, 2630` | hint | hint the architect that a criterion is stuck |
| 28 | F | architect_fallback: resident architect may verdict stuck criterion; owner not asked | Architect criterion_update | `board.py:2960-2969, 1598-1605` | keep |  |
| 29 | C | Every human message with text on an epic tree becomes an Ask | message_send (ledger=True) | `asks.py:58-69; board.py:2321-2322` | replace | see the asks redesign |
| 30 | F/A | Ask amend: criteria stale, verdicts reset to pending, checker → qa | ask_triage amends | `asks.py:195-232` | replace | follows 29 |
| 31 | F | Asks auto-settled: reply/resolves/owner message; phase past (by board); author seat dead | message_send; status emit; read time | `board.py:3090-3111, 3117-3127, 2796-2801` | replace | follows 29 |
| 32 | F | Auto-claim from verdict note (created_by board) | criterion_update with note | `records.py:169-186; board.py:1721-1722` | keep |  |
| 33 | F | Auto-decision from accepted deviation | Answer to a deviation | `records.py:189-206; board.py:2341-2342` | keep |  |
| 34 | F | Auto-decision from answered gate | gate_answer | `records.py:209-219; board.py:2506-2507` | keep |  |
| 35 | F | Open pains turned into lessons | Every context() read | `board.py:2686-2688; records.py:230-272` | review | lessons from pains on every context() read: measure before keeping |
| 36 | F/D | Library auto-link + board note | Quick task create; design_signoff | `library.py:213-243; board.py:618-619, 2508-2509` | keep |  |
| 37 | B/A | topics.ensure_seat: resident seat assigned and queued | Topic create; non-assignee message on topic; help thread | `topics.py:172-191; board.py:2338-2340; help.py:71` | keep |  |
| 38 | C | Criteria checked_by owner (quick tasks, Library topics, Lean/Solo) | criterion_create derivation | `board.py:1459-1476, 1515; workflow.py:450, 812-831` | change | quick-task lines checked by qa; you can still fail one in chat |
| 39 | B/D | Revive self-closed seat addressed by a message; refusal as fyi | after_message | `delivery.py:184-228, 262-267` | hint | tell the architect the seat is closed; it decides |
| 40 | D/C | Other closed seats: fyi to recovery seat (owner first) | after_message | `delivery.py:268-276` | fix | architect first |
| 41 | C | Question/deviation with no recipients falls back to epic owner | Every delivery plan | `delivery.py:38-45` | keep |  |
| 42 | D | Status recipients auto-chosen (architect, owner, spawner), published | record_status | `board.py:3327-3335; delivery.py:298-311` | fix | respect the feed's status filter (wake RCA RC3) |
| 43 | D | Gate broker wake only on route path; board-opened gates reach owner via feed only | POST gate open | `delivery.py:314-321; service.py:1572` | keep |  |
| 44 | D | Owner feed paged by board-authored gate/status/shell events | Every emit | `board.py:3981-4035` | remove | board-authored events stop paging the owner |
| 45 | E | Supervisor restarts service after 3 failed probes (15 s); >5 in 10 min = crash_loop | Supervisor loop | `v8/src/edp8/supervisor.py:59-89, 160-191` | keep |  |
| 46 | D | service_restarted event on board | Supervisor POST | `v8/src/edp8/service.py:1482-1490` | keep |  |
| 47 | F | Startup migrations, pins, epic_id backfill, index rebuild, upload sweep, hourly DB optimize | Start; timers | `store.py:163-218; board.py:264; service.py:465-474, 2300-2339` | keep |  |
| 48 | D | RSI tripwire finding (off by default) | Timer | `v8/src/edp8/rsi.py:590-613` | keep |  |
| 49 | F | Plane mirror + webhook notes (off by default) | Timer; webhook | `v8/src/edp8/plane_adapter.py:205-246, 274-291` | keep |  |
| 50 | F | Browser sessions idle 30 min released (every 60 s) | Timer | `v8/src/edp8/browser_proxy.py:355-378` | keep |  |
| 51 | D | Slack ping per broker message (if bridge runs) | Per-person SSE thread | `v8/src/edp8/slack_bridge.py:119-140, 231` | keep |  |
| 52 | B | Feed-driver heartbeat (1800 s) wakes doing seat with in_progress ticket, or on unseen changes | Seat-side timer | `v8/src/edp8/feed_driver.py:134-232, 361-365` | fix | its first tick never lands inside the 30-min Monitor |
| 53 | F/B | Codex seat cron ticker (seat-created jobs) + delivery retry | Seat-side timers | `v8/src/edp8/codex_seat/tools.py:677-680, 1036-1040, 383-392` | keep |  |
| 54 | F | Harness update waits (≤12 h) until no live seats, then installs | Admin "update when idle" | `v8/src/edp8/admin/harnesses.py:169-184` | keep |  |
| 55 | F/E | Desktop app starts services if down | Opening the app | `v8/src/edp8/desktop.py:698-720` | keep |  |
| 56 | B/E | Update helper resumes parked seats; on failure rolls back and resumes | heronry update runner | `v8/src/edp8/update_helper.py:347-377` | keep |  |
| 57 | A/F | Pool start marks previously-live seats dead ("interrupted") | Pool startup | `pool/service.py:745-790` | keep |  |
| 58 | B | Pool start resumes park_for_update rows | Pool startup thread | `pool/service.py:757, 792-819` | keep |  |
| 59 | B | Pool start re-spawns neuron heartbeat drivers | Pool startup | `pool/service.py:522-556` | keep |  |
| 60 | B | Resume watchdog thread (5 s) runs 60a-60f | Pool startup (default on) | `pool/service.py:857-867; pool/resume_watchdog.py:177-205` | review | keep the thread; see a-f |
| 60a | B | Kill turn running past 2400 s | Watchdog tick | `pool/resume_watchdog.py:332-346` | review | a 40-min turn kill can cut legit work; check the cap |
| 60b | D/F | Crash sweep marks rows dead; publishes `crashed` to parent handle | Watchdog tick | `pool/service.py:1711-1756; pool/resume_watchdog.py:297-348` | keep |  |
| 60c | B | Resume parked channel member addressed by `for:`/`@all` | Watchdog tick | `pool/resume_watchdog.py:257-287` | keep |  |
| 60d | B | Resume parked shell whose inbox grew past watermark | Watchdog tick | `pool/resume_watchdog.py:356-400` | keep |  |
| 60e | B | Resume parked shell on rx file growth | Watchdog tick | `pool/resume_watchdog.py:403-451` | keep |  |
| 60f | B | Resume any shell parked >1800 s, no traffic needed | Watchdog tick | `pool/resume_watchdog.py:454-471` | remove | resumes every parked shell each 30 min with no traffic: tokens for nothing |
| 61 | F | reconcile_sessions marks active rows with dead process as done | Usage/capacity reads | `pool/service.py:1004-1036` | keep |  |
| 62 | F | Phantom handle lock of dead holder reaped | Spawn admission | `pool/service.py:1347-1369` | keep |  |
| 63 | B | Out-of-tree pause watchdog resumes suspended tree if observer died | Detached process | `pool/pause_watchdog.py:205-229` | keep |  |
| 64 | B | Quick task create spawns engineer.<story> | Owner opens a quick task | `v8/src/edp8/service.py:1770-1806` | keep |  |

### The asks ledger, replaced (proposal)

Today every human message with text on an epic tree becomes an Ask (`asks.py:58-69`). The architect must then triage
it, and the acceptance gate waits until all of them are triaged (`board.py:2428`). The owner rejected both the name
("asks ledger" means nothing to a non-native speaker) and the idea of an opt-in toggle (it is a UX gap).

Proposal: no automatic objects. When an owner message carries a requirement, the architect writes or rewords a
criterion and replies in the chat, quoting the message: "Added as c-…". The epic's criteria list becomes the
**Requirements** list, and each line links to the message it came from. Nothing to toggle, nothing to triage, and
nothing that blocks acceptance.

## Code guards

A code guard is code that refuses an agent's request (`raise BoardError`, an error envelope or an HTTP 4xx) or
silently rewrites it. Counted on main, 2026-10-08:
- 225 `raise BoardError(` sites: board.py 130, topics.py 27, service.py 24, fixes.py 10, api_tools.py 9, and the
  rest in smaller modules.
- 23 more in asks.py, 23 workflow preconditions, 22 MCP-layer error envelopes and the pool's refusals.
- About 130 `HTTPException` sites, mostly admin plumbing.

The full inventory, with verbatim code, is [harness-map/code-guards.md](harness-map/code-guards.md).

| Kind | board.py sites | What it guards | Verdict |
|---|---|---|---|
| T. State transitions | 7, plus about 14 workflow preconditions | Legal status edges, evidence before in_review, passes before done | **keep.** This is what guards are for. |
| S. Safety | 4, plus secret screen, guest scope and private-host checks | Guests, secrets, SSRF | **keep** |
| R. Role and scope | 37 | Who may create, assign, verdict or decide | **keep the core** (create, assign, verdict, binding decisions); fold the rest into hints |
| E. Evidence | 10 | evidence_ref before a verdict, doc version, screenshot for look checks, sources for sme | **keep** evidence_ref and the version check; **hint** the screenshot and sources rules |
| Q. Capacity | 5, plus pool caps | 8 open stories, 5 tasks, 6 criteria, total shells | **keep** the shell cap; **hint** the ticket caps |
| P. Process policing | 15, plus about 8 elsewhere | Fixed-at-create fields, inbox-before-status, tasks naming asks, one qa per epic, signoff lint | **hint**, except "the doer cannot verdict its own ticket", which keeps checking honest |
| A. Silent rewrites | about 10 | checked_by ignored, a story auto-tagged quick, titles derived, effort clamped | **say so in the reply**, never silently |

Guards in Python versus guards as workflow data: status edges, permissions (`wf.allowed`) and hooks are data in
`workflow.py`. The P and E guards are hard-coded, and no workflow setting can turn them off.

Note: the retype added on 2026-10-08 (41e3ec75) brought two new P guards: "a task's or a topic's work_type is
fixed at create" and "a review story is review from create to close". They are on the hint list too.

## How seats are woken

A seat's Claude Code Monitor runs `edp8.feed_driver`, and every line the driver prints becomes a model turn. The
driver prints five kinds of line: the listening banner, board events, broker messages, heartbeats and connection
errors.

Measured over the transcripts: 46% of monitor turns before 10-01 ended with no action, and 56% after. The root
causes are in [v8/docs/evidence/e0cec-s8/after/wake_rca.md](../v8/docs/evidence/e0cec-s8/after/wake_rca.md):
- The Monitor stops after 30 minutes, and the re-armed driver prints the same banner again. That is 64% of the
  no-action turns after the upgrade.
- An addressed message arrives twice, once as a board event and once as a broker copy, with no dedupe.
- The broker status path skips the feed's filter.
- Every reconnect retry prints a line.
- The heartbeat never fires inside the Monitor's lifetime.

Fixing the first four removes about 45–69% of no-action wakes.

## What a doc write costs

- `doc_create`, `doc_update` and `doc_edit` all point at `/doc-write`. That skill is 4.1 KB, about 1,000 tokens per
  seat session, and it asks for the summary-first shape (Purpose, key slot, Keywords, Outline, Topics) on a doc of
  any type and any size.
- A doc of 8,192 chars or less is returned whole by `doc_read` (`doc_tools.py:211-212`), so the shape gives its
  readers nothing. 13 of the 15 summary_first notes are that small.
- On a 1.7 KB note the scaffold was about 35% of the bytes, written once by the author and read by every reader.
- sme seats cannot use `doc_edit` (`bundles.py:2945`), so every revision resends the whole body.
- `/verify` points at `doc_update`, which also resends the whole body.
- The board itself never checks layout, so nothing on the board has to change if short docs are exempt.
- **Proposal:** below about 8 KB, write plain prose with one key slot. Let sme seats use `doc_edit`. Point `/verify`
  at `doc_edit`.

## Changes to this map

| Date | Change |
|---|---|
| 2026-10-08 | First version: modules, what runs on its own, code guards, wakes and doc writes (epic-0cec8d1c31) |
