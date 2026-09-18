# S5 engineering handoff — 2026-09-18

Story `s-bb3ab419d2`; approved `design-f716d0d138` v7 §4.9; plan `note-44da39746b`. Implementation commit **51d575c**. Engineering evidence only, not independent QA or native/owner acceptance. Not pushed or deployed; shared services untouched.

## Delivered

- `/v1/me/notifications` authenticates with existing actor/header policy. Baseline cursor suppresses backlog; bounded 200-event pages select only currently unanswered inbox **questions** and open gates belonging to the viewer. No arbitrary notes/status/steers or body/title snippets. Exact canonical source/event URL, message hash, and authenticated click revalidation; answered/foreign/missing requests return no selectors.
- Existing single SSE/poll feed fans out a lightweight signal. Page checks the minimal endpoint after feed changes and every 30 seconds (offline/reconnect fallback). No extra SSE subscription, global query invalidation or client-derived recipient authority.
- Explicit per-participant/origin Enable/Disable/Test with no mount-time permission prompt. Generic alerts only; no identifying snippet opt-in is exposed. Honest denied/insecure/offline/failed-feed states and Needs you link, which remains in the primary rail as well.
- Minimal `/ui/notifications-worker.js`, no-store JavaScript served separately from SPA fallback; Vite public files now participate in e2e build freshness. No fetch/cache/push handlers, credentials, message bodies or titles in worker payloads/URLs/IDB. Atomic bounded 1,000-entry/7-day participant+event IDB ledger, tag secondary, failed-display claim release.
- Live participant handshake on click; matching board client focus + postMessage, fresh page authorization + SPA router. Unknown identity fails closed; different-identity tab never selected. Recheck before opening a fresh selector-only shell if no eligible client exists. Focus refusal never retries by opening extra tabs. Rapid duplicate clicks coalesced for 5s in worker memory.
- Dirty draft/pending-work destination hold; explicit Open waiting request reauthorizes. No moving or overwriting another tab's draft. Existing S3 router/composer state retained.
- Runnable **integrated** native fixture/harness and matrix: `NATIVE-MATRIX.md`, `native_harness.py`. Harness cold-start smoke proves production worker route and question/approval emission from disposable temp-home/DB loopback board; broker publication disabled. It never opens a browser or requests permission.

## One awaited adherence consult

Run `20260918T135736Z-8546292a`, second_opinion, completed `ok_concurrent_writes`; recovered and read its full answer before handoff. Manifest `provider_model=unavailable`: actual provider identity is **unverified**, not inferred from the requested model; no retry loop. Consultant reported no edits. Three concrete P2 findings fixed with regression tests:

1. `{actor:null}`, empty or malformed identity reply now blocks fresh-window fallback (VM test reproduces original failure).
2. Authorization generation + enabled/permission/lifecycle recheck after server await invalidates in-flight authorizations across disable/re-enable. Deferred-response RTL test.
3. Active worker is reacquired on controller replacement/redundancy/failure while preserving delivery cursor. Replacement RTL test proves pending event is not baselined away.

No findings remain knowingly unfixed. This is not a post-fix consultant approval; fixes were independently rerun by the engineer.

## Final commands and actual results

- `node web/node_modules/typescript/bin/tsc --noEmit -p web/tsconfig.json`: **PASS**.
- `npm --prefix web run test -- --run --maxWorkers=1 src/components/NotificationCenter.test.tsx src/components/AppShell.test.tsx src/live`: **44 passed, 7 files**. Existing Node localstorage warning on node-environment test, no failures.
- `.venv/Scripts/python.exe -m pytest tests/test_notifications.py tests/test_notification_harness.py tests/test_api_views.py tests/test_webapp_serve.py -q --tb=short`: **33 passed**. Includes enforced token/401 test, scoped authorization, no backlog, answered/gate revalidation, pagination and worker MIME/no-store + isolated harness emission.
- `EDP8_BOARD_CMD='C:\Projects\Learning\eda-base3\v8\.venv\Scripts\edp8-board.exe' npm --prefix web run e2e -- e2e/s5-notifications.spec.ts --workers=1 --max-failures=1`: **1 passed**. Production authenticated feed, real service worker and IDB, two concurrent replay claims, privacy payload, actual two-tab draft retention/router reauthorization; axe zero serious/critical and 320px no body overflow. **Display, native focus and notificationclick are simulated inside the owned test worker.** No native acceptance claimed. Initial synthetic-focus trial was refused by the browser as expected; test now explicitly stubs that native-only seam.
- `npm --prefix web run build` (also run by focused browser freshness setup): **PASS**, ~561.5KB JS / ~172.4KB gzip. Existing >500KB chunk advisory retained; no dependencies changed.
- Initial Python fixture errors (gate signoff without design; nonexistent create_app tokens arg), test TS errors, and an unstable mocked draft-guard callback were corrected and rerun; no unreported product failure hidden by those changes.

Screenshots: `web/e2e/evidence/s5-notifications.png` and `s5-notifications-320.png`, inspected by engineer. Synthetic content. Native toast appearance is not captured/proven by these app screenshots. Owner demo artifact `art-e67cd58ce5`; owner reaction not received at handoff.

## Criterion map and remaining acceptance

- **c-b950658c10**: Python + RTL + worker VM + isolated Chromium checks above. Covers explicit gesture, authenticated selection/click reauthorization, IDB cross-tab replay, generic minimal data, honest fallback, draft guards and reviewer-reported races. Native permission revocation/focus behavior still requires matrix. Worker restart persistence uses IDB; concurrent actual transactions tested, a native Firefox worker restart scenario is not claimed.
- **c-62b9921733**: procedure/harness available; **0/80 integrated native trials executed**. Full stock owner Windows/Firefox 20 each foreground/background/minimized/multitab and rapid-click/disappearance/denied/revoked/identity cases remain mandatory QA/owner work. S0 single-click evidence does not pass this criterion. Fresh consent and exact canonical origin/profile must be recorded. No all-tabs/browser-closed delivery promise.

Evidence refs may be attached to both criteria with verdicts pending: report explicitly distinguishes completed command checks from unexecuted look checks. QA performs final consolidated verification per architect dispatch; engineering in_review is not acceptance.

## Rollout / rollback / hygiene

No shared restart, native profile launch, permission prompt, production DB write, paid prompt/login, full web e2e or QA spawn. Browser fixture and harness smoke owned processes exited before handoff. Only S5 paths staged; unrelated scratch files untouched. Deploying new Python route requires **owner-coordinated board rollout**; this engineer did not restart it. Existing deployment without the new endpoint reports unavailable rather than pretending success. Worker auto-update/replacement is handled; rollback scoped S5 commit and coordinate unregistering only this worker/origin if needed (never clear general browser data). No MCP/proxy bridge code changed.
