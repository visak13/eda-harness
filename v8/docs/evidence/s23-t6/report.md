# S23-T6: T5 findings N1–N5 fixed; N6 recorded as UI-only

N1–N5 of report-36481f7a4e are fixed, each with a regression test that fails on the pre-fix source. N6 is a written exemption. The private-board tool_audit.py now passes 19/19 tasks with 0 workarounds; it exited 1 at 18/19 in T5.

## Delta against report-36481f7a4e

| Finding | T5 (a150e28) | T6 fix | Test (fails pre-fix) |
|---|---|---|---|
| N1 topic_research tail | A 15 KB page ends at 12,000 chars. No continuation. Reply 12,331 B. | The board keeps the fetched text (`<data>/topic_pages/<topic>/<sha(url)>.txt`). `url`+`offset` reads on without refetching. Every reply is bounded to the 8 KB page cap and carries `offset`/`next_offset`/`total_chars`. `next` names the exact call and says "read to the end before you distil". | `test_research_tail_is_readable_through_the_named_continuation` (pre-fix: 12,397 B, no tail), `test_research_offset_needs_a_kept_page`, `test_research_tool_advertises_offset` |
| N2 write echo | doc_create 14,444 B and message_send 14,386 B for a 13,750 B body | Every write tool returns a compact receipt. A body field over 240 chars is clipped (`… (+N chars)`), and `echo.bytes` plus `echo.read` give the exact read call. This covers doc_create, message_send, ticket_create/update, criterion_create, record_decision/claim/lesson and topic_propose. message_send now returns `seq`. doc_update defaults to `compact=true`; the flag is kept for compatibility, with no description, and its receipt carries `bytes`. **The opt-in is the named read, not an arg** (architect ruling m-44ae9118d1). | `test_write_tools_reply_with_a_compact_receipt[8 tools]` (pre-fix: 14.5–14.7 KB), `test_receipt_read_call_returns_the_whole_body`, `test_doc_update_defaults_to_a_receipt` |
| N3 participants over cap | limit=100: 10,871 B against cap_b 8000 | `tool_paging.offset_page(enrich=)` adds the reach string inside `_fit`, so the cap and `next_cursor` count the rows as finally shown. | `test_no_bounded_tool_reply_exceeds_its_cap[7 tools × default/limit=100]` (pre-fix participants-100: 10,744 B), `test_participants_cursor_resumes_after_the_rows_shown` |
| N4 harvest fixture | harvest_cost failed on a Codex seat (Claude-only root). The hint said "pass since" although since was passed. | The audit writes hermetic Claude AND Codex transcripts in its private home, points `EDP8_HARVEST_LOG_ROOTS` at both, and costs both seats (claude: 3 calls; codex: 2 calls). There is no EDP_HANDLE dependency. `harvest_cost` raises `NoLog` naming every root searched, with a hint that never says `since`; `NoWindow` keeps the since advice. | `test_harvest_no_log_names_the_roots_and_not_since`, `test_harvest_route_hint_for_a_missing_log_never_says_since`; audit task harvest_cost passes |
| N5 scoring | topic_research: 0 ok calls, yet "pass" off a 94 B error | Standards 3 and 6 pass only when there is ≥1 ok call. Otherwise they are `not_measured` with a written reason, listed in `matrix.not_measured`. topic_research now has a real success fixture: a local page served through a board wrapper that swaps `topics.FETCH`/`RESOLVE` (no network). Coverage reads that page to its tail through the continuation (5 ok calls, max 6,610 B). topic_propose is now idempotency-measured on the audit board, no longer exempt. | `test_zero_ok_calls_is_not_measured`; audit coverage note `research tail read=True` |
| N6 Library approval | No tool; scope question | Written exemption `COMPLETENESS_EXEMPT.library_doc_approval` in the audit ledger and matrix line. The topic_propose reply hint says "Library doc approval is human UI-only by design (owner uses the browser UI only, m-0213457e52): no tool approves it". No tool is added. | `test_topic_propose_reply_records_the_ui_only_exemption` |

## Audit before/after (T5 ledger vs T6 cold run)

The run used a private board on ports 19472/19372, a temp home, a read-only DB backup and hermetic transcripts. `scripts/tool_audit.py --out docs/evidence/s23-t6/audit.json` exited 0.

| Task | Calls T5 | Calls T6 | Bytes T5 | Bytes T6 | T5 | T6 |
|---|---:|---:|---:|---:|---|---|
| file_story | 8 | 8 | 4,495 | 4,495 | Pass | Pass |
| thread | 4 | 4 | 1,676 | 1,700 | Pass | Pass |
| image | 3 | 3 | 3,624 | 3,636 | Pass | Pass |
| edit_design | 3 | 3 | 1,017 | 1,028 | Pass | Pass |
| decision | 2 | 2 | 4,137 | 3,979 | Pass | Pass |
| spawn_reap | 3 | 3 | 572 | 572 | Pass | Pass |
| verdict | 5 | 5 | 2,248 | 2,248 | Pass | Pass |
| restart_cursor | 2 | 2 | 8,105 | 8,113 | Pass | Pass |
| participants | 1 | 1 | 5,383 | 5,383 | Pass | Pass |
| file_pain | 5 | 5 | 1,163 | 1,163 | Pass | Pass |
| harvest_cost | 2 | 3 | 333 | 1,482 | **FAIL (N4)** | Pass |
| teammate_access | 5 | 5 | 1,643 | 1,643 | Pass | Pass |
| workflow_edit | 5 | 5 | 41,416 | 41,416 | Pass | Pass |
| service_status | 1 | 1 | 607 | 607 | Pass | Pass |
| coverage | 247 | 251 | 418,827 | 447,877 | Pass | Pass |
| arg_guidance | 6 | 6 | 2,337 | 2,337 | Pass | Pass |
| describe_objects | 31 | 31 | 41,726 | 41,726 | Pass | Pass |
| idempotency | 17 | 19 | 6,467 | 8,591 | Pass | Pass |
| coverage_grep | 0 | 0 | 0 | 0 | Pass | Pass |
| **Total** | **350** | **357** | **545,776** | **577,996** | **18/19** | **19/19** |

- Bytes rose 32 KB. The cause is new coverage, not a regression: topic_research's successful path (+4 continuation calls, about 25 KB of real page text), the topic_propose success and its keyed idempotency pair, and the second transcript fixture.
- Matrix T5: pass 358, not_measured 2. Matrix T6: pass 345, not_applicable 60, not_measured 15, failing 0, unexplained 0.
  - The 13 new not_measured cells are the N5 honesty: tools whose every audit call failed, now shown instead of passed. They are gate_open/gate_answer/close (transition), assemble_ruleset (not_found: the audit story links no strategy doc) and propose_fix (no help thread).
  - withdraw_claim and dense_search are in no role bundle, so the audit never calls them. This contradicts the `_S20_UNUSED` comment "Every tool is still served to some role". It predates T6 and is not fixed here.
- The largest non-full/non-verbose reply is 7,987 B. workflow(read, full=true) is still the intentional 24,191 B opt-in.

## Verification

- `pytest tests/test_s23_t6_findings.py` → 34 passed. Against the pre-fix source (a HEAD worktree): 19 failed, 15 passed (`docs/evidence/s23-t6/prefix-fail.txt`).
- On the committed code: T6 findings plus contract, info-parity/no-loss, hint-parity (test_tool_contract::test_following_the_hint_…), descriptions, S20, agent-home kinds, topics, harvest, MCP tools, enums, context tools, parity oracle and library → **832 passed, 1 skipped** (0 failed).
- A full `pytest tests` run was stopped by the host's low-memory reaper at about 16% (1 F in about 430 tests). The F re-ran as `tests/test_admin_services_live.py::test_admin_update_check_and_apply_backup_stop_upgrade_start`: no update-result.json after 240 s, a live detached-update drill under RAM pressure that imports none of the changed modules. It was not re-run at HEAD, and the full suite was not re-run (host memory).
- Commit 1dc77a9.
- S20 surface headroom after T6: sme 34 B, owner 77 B, engineer 120 B, architect 138 B, adversary 139 B. No rebaseline was needed. topic_research's `url` field lost its description because the tool description already names its hosts.

## Deploy note
The change touches `bundles`, `tool_paging`, `topics`, `harvest_cost`, `api_tools`, `api_topics`, `service` and `client`. The board and MCP proxy need a restart to serve it, and every seat that uses a changed tool must respawn (the architect's call).
