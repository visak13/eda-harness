# S23-T5: Astra usability re-audit at a150e28

The tool layer still has usability gaps: F1–F4 are closed, but six newly ranked findings survive independent reproduction.

- The unchanged cold audit exits 1: 18/19 tasks pass; its Codex harvest fixture fails.
- The contract, no-loss, descriptions, S20 and guide-kind suite passes 633 tests.
- Real successful calls expose an unreachable research tail, write-body echo and an over-cap participant page that the green matrix misses.
- No product code was edited; no fleet service was restarted. This is one findings-only usability round.

## Scope, method and evidence

Seat: adversary.t-91393f0b57, gpt-6-astra, high effort. Code baseline: a150e28. Grounding: assemble_ruleset(t-91393f0b57), design-e963c656f5 v42 R23, report-e517e9e87e v4, report-b57e59187b v2, report-6971109e05 v2 and report-9ad8c27146 v1.

Standards: S1 advertisement; S2 idempotency; S3 clear output; S4 clear schema; S5 describe coverage; S6 token efficiency; C completeness; L no-loss.

The cold audit used a read-only SQLite backup, a fresh private temp home, private fixture credentials, board port 19400 and fake pool port 19301. It invokes the unchanged audit, including its normal lifecycle fixtures; this seat added no security/authentication/bypass/exploit probes. No real source was fetched for the independent research probe: its network boundary supplies a deterministic ordinary-prose page. All other tool, client, route and persistence code runs normally on an isolated in-memory board. Library/help tickets are seeded fixture state; no real seats are spawned or fix proposals approved.

Committed evidence is under docs/evidence/s23-t5/:

| File | Evidence |
|---|---|
| audit.json | The untouched cold-run ledger contains all 350 calls, all 19 tasks and the matrix. |
| repro.py and repro-results.json | The independent bounded pass reproduces findings and F1/F2/F4 closures on real endpoints. |
| harvest_repro.py and harvest-results.json | Read-only discovery comparison shows that the Codex log exists outside the audit's configured roots. |
| report.md | This review, including the ranked owner-pick list, is mirrored locally. |

Commands actually run:

```text
.venv/Scripts/python.exe scripts/tool_audit.py --out docs/evidence/s23-t5/audit.json --home <TEMP>/edp-s23-t5-private
  exit 1; 18/19 tasks pass; 350 calls; 545,776 response bytes.
.venv/Scripts/python.exe -m pytest tests/test_tool_contract.py tests/test_tool_info_parity.py tests/test_tool_descriptions.py tests/test_s20_token_cost.py tests/test_agent_home_kinds.py -q
  exit 0; 633 passed in 31.65s.
.venv/Scripts/python.exe docs/evidence/s23-t5/repro.py
  exit 0; all reproduction and closure assertions hold.
.venv/Scripts/python.exe docs/evidence/s23-t5/harvest_repro.py
  exit 0; Claude-only roots miss the log; Codex root finds it; compute succeeds.
```

The full repository test suite was not run; focused verification is sufficient for a findings-only review. Current fixture results are not a claim about every possible input.

## Ranked surviving findings

Token estimates use UTF-8 compact JSON bytes / 4, as in T1, not a tokenizer or a bill. Missing facts and blocked workflows cannot be priced as simple token savings.

| Rank / class | Tool or surface | Reproduced problem | Standard | Tokens wasted per affected use | Repro | Proposed fix |
|---|---|---|---|---|---|---|
| N1 / high / obvious bug | topic_research | A 15,214-character page returns only 12,000 characters, with truncated=true but no way to read the tail; its next instruction says to distil/propose. | L, C, S3, S6 | A repeat costs approximately 3,083 tokens and still cannot reveal the tail; the initial reply exceeds 8,000 B by 4,331 B. | repro.py: research_tail | Cache/pin the fetched content and expose bounded offset/cursor reads or a readable artifact; make the next instruction fetch remaining content. |
| N2 / medium / obvious efficiency gap | doc_create, message_send | Both echo the complete 13,750-byte input body. Replies are 14,444 B and 14,386 B respectively; neither create/send offers a compact receipt option. | S6 | Approximately 3,438 redundant body tokens each, excluding JSON escaping/metadata. | repro.py: echo | Return an ID/version/sequence receipt by default, with an explicit full-response option; doc_read/message_read preserve full retrieval. |
| N3 / medium / obvious bug | participants | limit=100 with verbose omitted returns 10,871 B / 41 rows while its own receipt says cap_b=8000. Reach strings are appended after fitting. | S3, S6 | Approximately 718 tokens beyond the claimed page cap. | repro.py: participants | Enrich/project before the final byte fitting and compute the cursor from the final shown rows. |
| N4 / medium / obvious audit defect | tool_audit.py harvest_cost fixture | The mandated cold re-run fails on this Codex seat because start_board configures only the Claude transcript root, although its target is EDP_HANDLE (this Codex seat). | S3, verification reproducibility | The failed reply wastes approximately 43 tokens and 5.16 seconds; diagnosis cost varies. | audit.json harvest_cost plus harvest_repro.py | Use hermetic Claude and Codex transcript fixtures, or include both roots; distinguish missing-log remediation from missing-harvest-window remediation. |
| N5 / medium / obvious verification defect | tool_audit.py scores | topic_research has 0 successful calls but receives pass for clear output and efficiency, based solely on a 94-byte nonexistent-topic error. Its real successful path is N1. | S3, S6, verification completeness | The apparent 24-token probe substitutes for an unmeasured success path; follow-up effort is unmeasured. | audit.json tools.topic_research and calls; scripts/tool_audit.py scores | Require a successful representative fixture before these standards pass; otherwise mark not_measured with a reason and surface it. |
| N6 / low / scope question | Owner Library proposal approval | A legitimate topic_propose succeeds, but its reply sends the owner to the Library. No advertised owner tool or registry action approves/rejects proposed knowledge docs; the REST handlers exist. | C | At least one interface/context handoff; variable token cost, not measured. The redirect hint itself is about 16 tokens. | repro.py: approval_surface; service.py doc approval routes | Owner decides whether this is explicitly human-UI-only; otherwise expose the existing owner-authorized approval/rejection operation without broadening authority. |

### N1 detail: disclosure of truncation is not a continuation

The returned keys are receipt, text, truncated and next. The marker TAIL_FACT_7391 appears after the cut and is absent. Repeating the same request returns the same prefix. Adding offset=12000 is rejected as an unknown argument; the accepted schema contains only topic_id/query/url. The receipt holds the source byte count, not readable retained content. Source: src/edp8/topics.py:460 and :571; TopicResearchArgs in bundles.py.

This is newly detected here, not claimed as a T4 regression. The truncation path predates S23. The ranking applies the current completeness/no-loss requirement to the surviving implementation. The probe does not require an oversized or hostile web payload; it is approximately 15 KB of ordinary prose.

### N2–N3 detail: measure the final payload

N2 was suggested, but not measured, in the T3 harvest and explicitly left for this audit in T4. Both returned bodies are byte-for-byte equal to the input text. The field doc_update(compact=true) already demonstrates a compact alternative, but it is not present on either affected tool.

N3 is a non-verbose bounded call with a larger legal limit, not an opt-in full-row request. The same fixture's default limit=25 reply is 6,679 B; the human-only reply is 483 B. The bug is specifically fitting before reach enrichment, not the new type filter. Source: bundles.py:_participants and tool_paging.py:_fit.

### N4–N5 detail: do not relabel the audit green

N4's actual error is no session log found for adversary.t-91393f0b57. Its hint says to pass since even though since was already provided. The Codex mirror exists at the host's Codex log root; the read-only comparison finds it and the same compute implementation succeeds. This establishes a harness-root problem, not a production harvest-accounting failure. The original cold run remains failed in the ledger; no environment-adjusted rerun replaced it.

N5 is reproduced directly from the ledger: topic_research calls=1, ok_calls=0, max_bytes_out=94, with error ticket 'audit-topic' does not exist. Standards 3 and 6 still say pass. The independent successful topic fixture returns 12,331 B and loses access to the tail. Contract/description tests still pass because they do not measure this successful path.

## F1–F4 closure

| T3 finding | Verdict | Independent reproduction |
|---|---|---|
| F1: seq hint skips hidden messages | Closed. | Existing private-fleet parity tests pass. The independent fixture follows hints and cursors separately to the end: message_query covers the exact same 37 IDs in 3 pages; events_query covers the exact same 38 IDs in 2 pages. Each parsed hint equals value.last_seq. |
| F2: seven creates lack idempotency | Closed. | Every one of all ten keyed creates uses its actual route, then repeats after tool_idem.reset(): same ID and replay=true in 10/10 cases. This includes real topic_propose and propose_fix, not the contract suite's substituted message route. No proposed fix executes. The existing board-restart persistence test also passes. |
| F3: guides name a nonexistent message kind | Closed. | test_agent_home_kinds passes as part of the 633-test run; the fetched shared-host-rules guide uses record_status(blocked) plus message_send(question). |
| F4: participants cannot filter humans | Closed. | participants(type=human) on the independent fixture returns exactly its one human and no agents; the existing real-route filter tests also pass. N3 is a separate cap defect, not a reopened filter finding. |

## Before/after per task

T1 and T2 are the committed ledgers, not re-invented measurements. T5 is this cold run. T3 report-6971109e05 had 339 calls / 540,665 B; T4 report-9ad8c27146 claimed 350 calls / 545,997 B. T5 has the same 350 calls but a changed live DB snapshot and the N4 failure.

| Task | Calls T1 | Calls T2 | Calls T5 | Bytes T1 | Bytes T2 | Bytes T5 | T5 outcome |
|---|---:|---:|---:|---:|---:|---:|---|
| file_story | 8 | 8 | 8 | 4,495 | 4,495 | 4,495 | Pass |
| thread | 4 | 4 | 4 | 1,699 | 1,654 | 1,676 | Pass |
| image | 4 | 3 | 3 | 2,909 | 3,624 | 3,624 | Pass |
| edit_design | 3 | 3 | 3 | 1,017 | 1,017 | 1,017 | Pass |
| decision | 2 | 2 | 2 | 4,136 | 4,137 | 4,137 | Pass |
| spawn_reap | 3 | 3 | 3 | 608 | 572 | 572 | Pass |
| verdict | 5 | 5 | 5 | 2,248 | 2,248 | 2,248 | Pass |
| restart_cursor | 3 | 2 | 2 | 72,463 | 8,113 | 8,105 | Pass |
| participants | 1 | 1 | 1 | 87,129 | 5,383 | 5,383 | Pass |
| file_pain | 0 | 5 | 5 | 0 | 1,163 | 1,163 | Pass |
| harvest_cost | 0 | 2 | 2 | 0 | 608 | 333 | FAIL (N4) |
| teammate_access | 0 | 5 | 5 | 0 | 1,643 | 1,643 | Pass |
| workflow_edit | 0 | 5 | 5 | 0 | 41,416 | 41,416 | Pass |
| service_status | 0 | 1 | 1 | 0 | 564 | 607 | Pass |
| coverage | 239 | 247 | 247 | 5,977,859 | 417,572 | 418,827 | Pass |
| arg_guidance | 6 | 6 | 6 | 7,595 | 2,319 | 2,337 | Pass |
| describe_objects | 17 | 31 | 31 | 28,751 | 41,708 | 41,726 | Pass |
| idempotency | 6 | 6 | 17 | 2,340 | 2,435 | 6,467 | Pass |
| coverage_grep | 0 | 0 | 0 | 0 | 0 | 0 | Pass |
| **Total** | **301** | **339** | **350** | **6,193,249** | **540,671** | **545,776** | **18/19 pass** |

The measured total is much smaller than T1, but not an equal-outcome 19/19 claim because harvest_cost fails. Literal calls increased 301 to 350 because later audits add formerly unreachable tasks, more described objects and idempotency coverage. The original unchanged 11 task goals still use 45 versus 43 calls.

The ledger reports zero workarounds for its 19 fixed tasks, 280 advertised role/tool pairs covered, 70 registered tools, 358 pass cells, 60 N/A and 2 explained not_measured idempotency cells. Those last two are independently covered here. N5 means the other green cells cannot be read as successful-path coverage. N1 and N6 are omitted lifecycle goals, so the ledger's zero does not establish universal completeness.

The ledger's largest non-full/non-verbose response remains 7,987 B. The larger independent repros disprove applying that observed maximum as a universal tool-layer bound. workflow(read, full=true) remains an intentional 24,191-byte opt-in response.

## Hand-off and owner decision

Criterion c-5ef2758466 is supported by this report and its reproducible evidence; its assigned engineer checker signs the verdict, not this doer seat. No code fixes are proposed as already applied.

Recommend picking N1–N5 for a scoped follow-up; N6 needs an explicit UI-only ruling or an approved tool addition. The adversarial gate remains for the owner to answer/close. No second round or fixes begin without a fresh owner message.

- p-59f06ccc — the unreachable research tail is recorded as framework pain.
- les-a5b22ca20d — successful representative paths must anchor usability scoring.
