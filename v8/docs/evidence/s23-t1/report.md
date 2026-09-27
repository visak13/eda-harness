# S23-T1: MCP tool usability and completeness audit

## Scope and reproducibility

- Baseline: committed `scripts/tool_audit.py`, before T2 fixes. Run `.venv/Scripts/python.exe scripts/tool_audit.py --out docs/evidence/s23-t1/audit.json` from `v8/`. The script writes one JSON line per task and a machine-readable calls/tool-score ledger.
- Private board: a SQLite **read-only online backup** of `.data/edp8.db` into a new temp home; private token file and board-minted seat tokens; board/pool bound to spare loopback 19400/19301 (or free alternatives). No fleet service restart, token-file read, or product-code edit.
- Coverage: 265 / 265 role/tool pairs; 63 exposed tool names across seven roles, plus 2 registry tools in no role bundle (`withdraw_claim`, `dense_search`). 301 recorded calls across 19 tasks.
- Six-standard scoring is in the complete matrix below: 1 advertisement; 2 idempotency; 3 clear output; 4 clear schema; 5 describe coverage; 6 token efficiency. `?` means not measured, `N/A` not applicable; these are explicit audit limits, not passes.

## Realistic tasks and calls-to-goal

| Task | Tool calls | Argument misses | Output bytes | Tool-only result | Workaround needed |
|---|---:|---:|---:|---|---|
| `file_story` | 8 | 0 | 4,495 | Pass | None |
| `thread` | 4 | 0 | 1,699 | Pass | None |
| `image` | 4 | 0 | 2,909 | Fail | HTTP GET /v1/artifacts/{id}/content is required to read image bytes |
| `edit_design` | 3 | 0 | 1,017 | Pass | None |
| `decision` | 2 | 0 | 4,136 | Pass | None |
| `spawn_reap` | 3 | 0 | 608 | Fail | direct pool reap is required for custom participant_id |
| `verdict` | 5 | 0 | 2,248 | Pass | None |
| `restart_cursor` | 3 | 0 | 72,463 | Pass | None |
| `participants` | 1 | 0 | 87,129 | Pass | None |
| `file_pain` | 0 | 0 | 0 | Fail | scripts/pain.py file/list is required |
| `harvest_cost` | 0 | 0 | 0 | Fail | scripts/harvest_cost.py is required |
| `teammate_access` | 0 | 0 | 0 | Fail | manual participants REST and tokens.json edits are required by tailnet-public-mode guide |
| `workflow_edit` | 0 | 0 | 0 | Fail | workflow management currently needs the Design UI or direct /v1/workflows REST |
| `service_status` | 0 | 0 | 0 | Fail | edp.ps1 status or direct service health REST is required |
| `coverage` | 239 | 0 | 5,977,859 | Pass | None |
| `arg_guidance` | 6 | 4 | 7,595 | Fail | None |
| `describe_objects` | 17 | 0 | 28,751 | Pass | None |
| `idempotency` | 6 | 0 | 2,340 | Fail | None |
| `coverage_grep` | 0 | 0 | 0 | Pass | None |

`coverage` invokes every advertised tool with that role's private participant through `bundles.invoke`; the realistic tasks use the same path. A failing task is a measured tool-layer or completeness finding, not a harness crash. The image task verifies actual PNG bytes after the tool returns only metadata. The restart task succeeds with a second `context()` call after `context_delta` refuses the old cursor.

## Ranked waste

| Tool | Problem | Standard | Est. tokens wasted per use | Proposed fix | Effort |
|---|---|---|---:|---|---|
| `ticket_query` | 472,133 B max, 6 calls >8 KB; one-line overflow | 3, 6 | ~115,985 | Page with cursor/limit and a compact summary; return count + next_cursor, not unbounded arrays. | M |
| `doc_query` | 270,175 B max, 6 calls >8 KB; one-line overflow | 3, 6 | ~65,495 | Page with cursor/limit and a compact summary; return count + next_cursor, not unbounded arrays. | M |
| `session_query` | 122,733 B max, 1 call >8 KB; one-line overflow | 3, 6 | ~28,635 | Page with cursor/limit and a compact summary; return count + next_cursor, not unbounded arrays. | M |
| `link_query` | 90,630 B max, 4 calls >8 KB; one-line overflow | 3, 6 | ~20,609 | Page with cursor/limit and a compact summary; return count + next_cursor, not unbounded arrays. | M |
| `participants` | 87,425 B max, 7 calls >8 KB; one-line overflow | 3, 6 | ~19,808 | Page with cursor/limit and a compact summary; return count + next_cursor, not unbounded arrays. | M |
| `message_query` | 44,700 B max, 6 calls >8 KB; one-line overflow | 3, 6 | ~9,127 | Page with cursor/limit and a compact summary; return count + next_cursor, not unbounded arrays. | M |
| `context_delta` | Cursor is rejected after private-board restart; `context()` recovery used 36,146 B twice in one task. | 3, 6 | ~9,000 for extra snapshot | Persist/rebase cursor stream or return a compact recoverable cursor. | M |
| `context` | 36,146 B max, 2 calls >8 KB; one-line overflow | 3, 6 | ~6,988 | Keep the bounded default and make restart cursors recover without a full snapshot. | M |
| `events_query` | 8,672 B max, 1 call >8 KB; one-line overflow | 3, 6 | ~120 | Page with cursor/limit and a compact summary; return count + next_cursor, not unbounded arrays. | M |
| `doc_create`, `artifact_create`, `ticket_create` | Same-input duplicates returned new IDs in 3/3 paired probes. | 2 | ~100-300 plus duplicate cleanup | Support idempotency keys or deterministic deduplication with conflict semantics. | M |
| `message_query` (and most models) | Unknown optional `limt` was accepted and ignored; the first-try call did not signal the typo. | 3, 4, 6 | ~1,500 for the unbounded result plus retry | Forbid extras across argument models; name nearest accepted field in validation error. | S |
| `ticket_create`, `criterion_*`, `doc_*`, `spawn`, etc. | 31/65 tools have at least one required field without a field description; 7/65 omit a linked skill/object advertisement. | 1, 4 | ~50-200 during discovery | Compose descriptions from object/enum/skill metadata; complete required-field descriptions; contract test. | M |
| `gate_*`, `topic_*`, `workflow_check` | Their linked object is missing from the 16-object `describe()` index (5 tools). | 5 | ~100-300 or source lookup | Add gate/topic/workflow object contracts and link from tool descriptions. | S |
| `reap` | Custom participant ID spawned on this epic cannot be reaped: scope derives the target from the ID suffix, not the session's ticket. | 3, 6 | ~200-500 plus REST/pool workaround | Resolve seat scope from the session/ticket recorded at spawn. | M |

**Measurement basis:** UTF-8 JSON-envelope bytes from `bundles.invoke`, using ~4 bytes/token only as a ranking approximation. Max output is a private copy of the real fleet DB, not an average workload. All oversized replies were single-line JSON; no content is omitted from the measured bytes.

## Ranked coverage gaps: framework work requiring non-MCP means

| Rank | Workaround and where it appears | Framework task | Missing tool or argument | Proposed tool/fix |
|---:|---|---|---|---|
| 1 | `scripts/pain.py list/file` - `.claude/skills/pain/SKILL.md:19-26`; seven role cards list `/pain`. | File, deduplicate, inspect and resolve a framework pain record. | No pain tool in any role bundle. | Add `pain_query`, `pain_file`, `pain_read`, `pain_resolve` (or an equivalent typed board API); preserve append-only history. |
| 2 | `GET /v1/artifacts/{id}/content` - private image task; `artifact_read` returns only metadata. | Read an uploaded image or text attachment as an agent. | No content-bearing MCP result; `artifact_read` has no inline/range option. | Return size-capped image/text content from `artifact_read`, with a continuation for larger files. |
| 3 | Direct pool reap - private custom-ID spawn/reap task. | Reap a seat the architect spawned with `participant_id` not derived from ticket ID. | `reap` scope resolution ignores spawn-session ticket mapping. | Fix `reap` target lookup; no bypass or wider authority. |
| 4 | `Invoke-RestMethod` and edits to `tokens.json` - `guides/tailnet-public-mode.md:107-123`. | Register, mint and revoke a human teammate credential. | Owner has only read-only `participants`; no typed credential lifecycle. | Owner-only `participant_create`, `token_mint`, `token_revoke` with one-time secret return. |
| 5 | Design UI or `/v1/workflows` REST - design doc `design-e963c656f5` section 4.14(c); owner/architect bundles contain no workflow editor. | Create/edit/publish a workflow definition. | No MCP workflow CRUD/publish tools. | Add versioned `workflow_create/edit/publish` with board preconditions. |
| 6 | `edp.ps1 status` or `/healthz` REST - `shared-host-rules` service section; recent health-check transcripts. | Read service health and status from an owner seat. | No owner service-status tool; shared-host rules reserve restart to human. | Add read-only `service_status` first; any mutating service-control tool must keep the owner/human boundary. |
| 7 | `scripts/harvest_cost.py --participant` - `.claude/skills/harvest/SKILL.md:39`. | Calculate a seat's framework token cost at epic acceptance. | No harvest/cost MCP tool in qa bundle. | Add `harvest_cost(participant_id)` returning bounded totals and evidence refs. |
| 8 | Raw SQLite/`.data` and direct `/v1/` reads in recent seat transcripts (audit scan pointers in JSON ledger). | Debug framework records or inspect state not exposed by a typed read tool. | Some needed diagnostics have no bounded board representation; others are developer/test scaffolding, not gaps. | Triage by task, add narrowly scoped diagnostic reads; do not expose arbitrary SQL or tokens. |
| 9 | `curl` upload instruction - `guides/agent-tools.md:22-23`. | Attach a workspace file. | Not a missing tool: `artifact_upload` already exists; the guide is stale. | Update the guide to use `artifact_upload` and `message_send(artifacts=[id])`. |

The coverage grep scanned `.claude/commands`, `.claude/skills`, `guides/*.md`, and the 60 newest pool seat transcripts. Candidate counts (not distinct missing-tool claims): `artifact_disk` 47, `board_rest` 79, `database_file` 37, `framework_script` 28, `harvest_cli` 1, `pain_cli` 23, `token_file` 74. The ledger stores only source paths/line numbers and categories, never transcript command bodies or token contents. Normal product coding, tests, and external package/network probes were not counted as missing board tools.

## Complete per-tool six-standard matrix

Legend: P=pass, F=fail, ?=not measured, N/A=not applicable. Columns 1-6 map to the six standards above. `max B` is the largest one-call UTF-8 envelope. A roleless registry tool is marked `none`.

| Tool | Roles | Calls | Max B | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---:|---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `artifact_create` | architect,engineer,adversary | 5 | 249 | F | F | P | F | P | P |
| `artifact_read` | engineer,qa,adversary | 3 | 292 | F | N/A | P | F | P | P |
| `artifact_upload` | architect,engineer,adversary | 3 | 381 | F | N/A | P | P | P | P |
| `assemble_ruleset` | engineer,qa,adversary,sme | 4 | 175 | P | N/A | P | P | P | P |
| `board` | owner,architect,qa,doctor | 4 | 928 | P | N/A | P | P | P | P |
| `close` | owner | 1 | 165 | P | N/A | P | F | P | P |
| `close_self` | engineer,qa,adversary,sme,doctor | 5 | 164 | P | N/A | P | P | P | P |
| `context` | owner,architect,engineer,qa,adversary,sme,doctor | 8 | 36,146 | P | N/A | F | P | P | F |
| `context_delta` | owner,architect,engineer,qa,adversary,sme,doctor | 7 | 171 | P | N/A | P | P | P | P |
| `criterion_create` | architect,engineer,adversary | 4 | 304 | F | ? | P | F | P | P |
| `criterion_query` | owner,architect,engineer,qa,adversary,sme,doctor | 7 | 315 | F | N/A | P | F | P | P |
| `criterion_update` | owner,architect,engineer,qa,adversary,sme | 6 | 378 | F | N/A | P | F | P | P |
| `dense_search` | none | 0 | 0 | P | N/A | P | F | P | P |
| `describe` | owner,architect,engineer,qa,adversary,sme,doctor | 23 | 5,874 | P | N/A | P | P | P | F |
| `describe_objects` | owner,architect,engineer,qa,adversary,sme,doctor | 8 | 669 | P | N/A | P | P | P | P |
| `doc_create` | architect,engineer,qa,adversary,sme | 7 | 500 | P | F | P | F | P | P |
| `doc_edit` | architect,engineer,qa,adversary | 5 | 212 | F | N/A | P | F | P | P |
| `doc_query` | owner,architect,engineer,adversary,sme,doctor | 6 | 270,175 | P | N/A | F | P | P | F |
| `doc_read` | owner,architect,engineer,qa,adversary,sme,doctor | 8 | 406 | P | N/A | P | F | P | P |
| `doc_update` | architect,engineer,qa,adversary,sme | 5 | 389 | P | N/A | P | F | P | P |
| `doctor_dead_mail` | doctor | 1 | 74 | P | N/A | P | P | P | P |
| `doctor_feed_lag` | doctor | 1 | 2,153 | P | N/A | P | P | P | P |
| `doctor_health` | doctor | 1 | 4,738 | P | N/A | P | P | P | P |
| `doctor_logs` | doctor | 1 | 109 | P | N/A | P | P | P | P |
| `doctor_pains` | doctor | 1 | 51 | P | N/A | P | P | P | P |
| `doctor_pool` | doctor | 1 | 439 | P | N/A | P | P | P | P |
| `events_query` | owner,architect,doctor | 3 | 8,672 | P | N/A | F | P | P | F |
| `find` | owner,architect,engineer,qa,adversary,doctor | 6 | 2,105 | P | N/A | P | P | P | P |
| `gate_answer` | owner | 1 | 98 | P | N/A | P | F | F | P |
| `gate_open` | architect,engineer,adversary | 3 | 152 | P | N/A | P | F | F | P |
| `gates` | owner,architect,qa,adversary,doctor | 5 | 32 | P | N/A | P | F | P | P |
| `get_guide` | owner,architect,engineer,qa,adversary,sme,doctor | 7 | 7,271 | P | N/A | P | P | P | P |
| `inbox` | architect,engineer,qa,adversary,sme,doctor | 6 | 89 | P | N/A | P | P | P | P |
| `link_create` | architect,engineer,qa,adversary,sme | 5 | 211 | P | N/A | P | F | P | P |
| `link_delete` | architect | 1 | 47 | P | N/A | P | F | P | P |
| `link_query` | architect,engineer,adversary,sme | 4 | 90,630 | P | N/A | F | P | P | F |
| `lookup` | owner,architect,engineer,qa,adversary,sme,doctor | 8 | 3,715 | P | N/A | P | P | P | P |
| `message_query` | owner,architect,engineer,qa,adversary,sme,doctor | 8 | 44,700 | P | N/A | F | P | P | F |
| `message_read` | owner,architect,engineer,qa,adversary,sme,doctor | 8 | 675 | P | N/A | P | F | P | P |
| `message_send` | owner,architect,engineer,qa,adversary,sme,doctor | 8 | 455 | P | ? | P | F | P | P |
| `participants` | owner,architect,engineer,qa,adversary,sme,doctor | 7 | 87,425 | P | N/A | F | P | P | F |
| `preflight` | owner,architect,engineer,qa,adversary,sme,doctor | 7 | 1,546 | P | N/A | P | P | P | P |
| `propose_fix` | doctor | 1 | 168 | P | ? | P | P | P | P |
| `reap` | owner,architect | 2 | 198 | P | N/A | P | F | P | P |
| `record_claim` | owner,architect,engineer,qa,adversary,sme | 6 | 303 | P | ? | P | P | P | P |
| `record_decision` | owner,architect,engineer,qa,adversary,sme | 6 | 421 | P | ? | P | P | P | P |
| `record_lesson` | architect,engineer,qa,adversary,sme | 5 | 334 | P | ? | P | F | P | P |
| `record_status` | architect,engineer,qa,adversary,sme,doctor | 6 | 443 | P | N/A | P | F | P | P |
| `resume` | owner,architect | 2 | 88 | P | N/A | P | F | P | P |
| `resume_self` | owner,architect,engineer,qa,adversary,sme,doctor | 7 | 3,412 | P | N/A | P | P | P | P |
| `session_query` | owner,architect | 2 | 122,733 | P | N/A | F | P | P | F |
| `set_binding` | architect | 1 | 445 | P | N/A | P | F | P | P |
| `spawn` | owner,architect | 2 | 378 | P | N/A | P | F | P | P |
| `subscribe` | owner,architect,engineer,qa,adversary,sme,doctor | 7 | 1,796 | P | N/A | P | P | P | P |
| `ticket_create` | owner,architect,engineer,adversary | 7 | 466 | P | F | P | F | P | P |
| `ticket_query` | owner,architect,engineer,adversary,sme,doctor | 6 | 472,133 | P | N/A | F | P | P | F |
| `ticket_read` | owner,architect,engineer,qa,adversary,sme,doctor | 7 | 7,987 | P | N/A | P | F | P | P |
| `ticket_update` | owner,architect,engineer,qa,adversary,sme | 9 | 584 | P | N/A | P | F | P | P |
| `topic_propose` | sme | 1 | 94 | P | ? | P | F | F | P |
| `topic_research` | sme | 1 | 94 | P | N/A | P | F | F | P |
| `whoami` | owner,architect,engineer,qa,adversary,sme,doctor | 7 | 1,233 | P | N/A | P | P | P | P |
| `why_stuck` | doctor | 1 | 215 | P | N/A | P | P | P | P |
| `withdraw_claim` | none | 0 | 0 | P | N/A | P | F | P | P |
| `withdraw_decision` | engineer | 1 | 466 | P | N/A | P | F | P | P |
| `workflow_check` | doctor | 1 | 6,455 | P | N/A | P | P | F | P |

## Verification and limits

- The cold script run returned exit 0 because its **coverage invariant** passed: all 265 advertised role/tool pairs were invoked. Intentional product deficits correctly remain failing task rows, and T2 is expected to improve those results rather than edit the baseline audit.
- `message_read(message_id=...)` is now an accepted alias, and `artifact_read` exists, correcting two older observations. The latter still cannot deliver image bytes through MCP. The four other first-try probes returned clear field/enum guidance; the optional `limt` probe was silently dropped.
- This is a usability/completeness audit only. No security probes, auth bypasses, fleet writes, or product-code changes were performed. The private fake pool was used for spawn/reap only.
