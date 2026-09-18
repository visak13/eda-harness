# S3 follow-up: full thread totals and older history

Owner finding m-72f03fad37; architect bounded-fix steer m-731304198b. This supplements `s3-implementation-report.md` / report-d9cc90d322, specifically criterion c-7c8401b473. No new story/task, extra consult, shared restart or deployment.

## Reproduction and cause
Isolated 235-message fixture reproduced the missing full count: `views.epic_page`/`ticket_page` returned the newest100 rows, and both UI labels used `thread.length`. There was no older-message control. The new test failed first with missing `thread_total` and missing pagination helper, before production edits.

## Fix
- Shared `views.thread_page` supplies full direct-source SQL COUNT, at most100 ordinary rows, and a strictly-before storage-sequence cursor. Optional deep-linked old message remains readable but **does not move the pagination cursor past unseen rows**. A lookahead row determines exhaustion. Count/window share a read transaction.
- Epic/Ticket pages embed the same metadata. Additive authenticated `GET /v1/tickets/{id}/thread?before=<seq>` uses the same registered actor dependency as the existing page routes; validates cursor integer/SQLite range. No service.py or Usage changes; only api_views.py route addition.
- Shared UI hook merges pages by message ID and sorts by server sequence, preserves source/composer instances and order controls, restores the visible list anchor after older-page insertion, and retains data/draft on failure with retry. A changed head cursor reopens pagination from the new head so a >100-message arrival burst cannot skip the intervening gap. Totals come from server metadata, not loaded array length. Deep-link scroll runs on initial readiness/hash changes rather than repeatedly jumping after every older-page append.
- No new dependencies, thread store, unsafe auth URLs, or unbounded body fetch. Existing consumers can ignore additive response fields.

## Final serial verification
- `.venv/Scripts/python.exe -m pytest tests/test_thread_pagination.py tests/test_store.py tests/test_api_views.py tests/test_views.py -q --tb=short`: **56 passed**. Tests cover235/601-message totals, every bounded older page, a concurrent arrival, old included message not skipping the middle, another-source exclusion, token-required HTTP401, cursor validation, API and legacy-view regressions. After adding oversized-cursor validation, the focused four pagination tests passed again.
- `npm --prefix web run test -- --run --maxWorkers=1 src/components/useThreadHistory.test.tsx src/pages/Epic.test.tsx src/pages/Ticket.test.tsx`: **56 passed / 3 files**. Populated235-message Epic reports235 before loading, reaches all235 without duplicates, toggles ordering and keeps the exact textarea node/draft/scrollTop; Ticket101 preserves rows/draft on failure and retry. Separate hook regression covers pinned-row deduplication plus235→400 arrival burst with gap recovery.
- `node web/node_modules/typescript/bin/tsc --noEmit -p web/tsconfig.json`: PASS.
- `npm --prefix web run build`: PASS; existing >500KB chunk advisory (~568KB combined current JS) remains. Build includes already committed sibling S5/S6 code; no sibling files changed.
- `git diff --check`: PASS.

## Limits and rollout
No browser started for this follow-up: preflight showed877MB free, so only small serial Python/TypeScript/unit/build runs were used. DOM/jsdom scrollTop preservation is not browser geometry proof. Canonical epic QA must verify actual populated >100 conversation scroll anchoring/reflow and draft behavior in the built browser, along with its existing zoom/acceptance matrix. Prior browser evidence does not prove this new pagination control. New backend metadata/route require the owner's normal coordinated rollout; old running service was not restarted and is not claimed fixed in production. No extra consult per explicit architect instruction for this mechanical bounded follow-up. Previous single completed S3 consult remains recorded in the main report.
