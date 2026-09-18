# S3 QA remediation — engineering handoff

Scope: `s-4983df7e94`, design-f716d0d138 v7, plan note-2ecc1a7c8c; QA report-5b5c0af71c plus report-69be3f4e90 and report-85873ba59a. This is remediation evidence, not independent QA acceptance or deployment.

## Repairs / reproduction

1. Needs you design gates no longer expose an ambiguous acceptance textarea. GateForm links to source with gate event identity; source opens typed design review. Other gate forms unchanged. All gate-row projections include event_id. QA interaction adaptation authorized in m-5c3a21a678: retained final not-signed_off assertion, added no legacy POST, exact source/doc/version/gate, local feedback, gate still open and no gate_answered event assertions. Original red suite/evidence remains in cd84765/f0c73df and original qa-ui screenshots are unchanged.
2. Notification initial authorization validates a landing without replaying canonical navigation over its opened viewer, later dismissal or later destination. Existing service-worker/draft/identity boundaries retained. Three real delayed-response browser cases pass.
3. Ordinary comment success clears its draft and refetches context without setting the request-changes sent lock; approval becomes enabled again.
4. Approval idempotency signature includes the gate event, so a reopened gate on the same version is a new operation, while a retry on the same gate retains its key.
5. Epic Expand now opens the actual shared Drawer. Epic and Ticket share ExpandableComposer: one stable portal host moves the same mounted Composer between inline and drawer containers. No composer remount on expansion: kind/to/artifacts/failed File retries/focus/selection remain component state. Pending sends/uploads continue to block unsafe dismissal.
6. Failed upload Retry is retained on Ticket expansion (QA browser synthetic503 upload boundary test passes).
7. Contextual API derives directed unanswered question/steer attention with existing answer/lifecycle semantics; source-wide, not a viewer/wake-count invention. UI shows unresolved asks alongside gates and blockers. Authenticated Epic/Story unanswered→answered API tests plus UI regression. Legacy API responses without asks say No open gates, not the false No open requests. Current implementation shares existing contextual read's 100000-row safety bound; not a new unbounded archive query.
8. Hierarchy: combined breadcrumb/id/status, original request inside Actions, notifications in header disclosure, compact composer guidance/help and constrained selects (full option glossary/title retained), denser message bodies and right-side Reply at wide widths. Narrow widths retain stacked Reply and all controls. No theme/icon redesign or capability removal.

Additional authorized identity repair (m-ded8073309 / owner m-c0ff909b8f): legacy design_signoff now requires matching human epic owner before message/event/status side effects. Synthetic foreign-owner denial verifies no seq mutation, gate remains open/status designed; matching owner succeeds. Other gates unchanged. No ownership migration, aliases or live-data edits.

Decisions New conversation: reproduced 17/18 tests, failure at detached composer element. It mounted a composer for an empty ticket before conversation-list selection resolved, then keyed remount detached the element. Mount only once a selected ticket exists; focused suite now 18/18, no assertion weakened.

## Verification (serialized, isolated)

- `.venv/Scripts/python.exe -m pytest tests/test_design_review.py tests/test_views.py tests/test_board.py tests/test_human_plane.py tests/test_epic_phase.py tests/test_notifications.py tests/test_s22_rules.py -q`: **104 passed**; two existing Pydantic enum warnings.
- `.venv/Scripts/python.exe -m pytest tests/test_title_words.py -q`: **17 passed**.
- `npm --prefix web test -- --run src/components/ContextualWork.test.tsx src/components/Composer.test.tsx src/components/DesignReview.test.tsx src/components/NotificationCenter.test.tsx src/pages/Epic.test.tsx src/pages/Ticket.test.tsx src/pages/Decisions.test.tsx`: **100 passed**.
- `npm --prefix web test -- --run src/components/NewEpicDialog.test.tsx`: **6 passed**.
- `cd web && npx tsc --noEmit`: passed. `npm --prefix web run build`: passed, existing >500KB bundle advisory.
- `EDP8_BOARD_CMD='C:\Projects\Learning\eda-base3\v8\.venv\Scripts\edp8-board.exe' npm --prefix web run e2e -- e2e/qa-ui-integration.spec.ts e2e/s3-workflow.spec.ts --workers=1`: **14 passed**, isolated fixture board/process cleanup. Not full web e2e.
- Earlier focused `s3-review.spec.ts`: passed with seven original QA regression cases (8 total). Exact-version local feedback/attachment/dedicated-view case is unchanged.
- `git diff --check`: clean.

## Visual comparison / limits

Approved reference read: `docs/ui-redesign-concepts/s1-assets/final/packet-epic.png`. Built evidence: `web/e2e/evidence/s3-remediation/representative-1440.png` and `representative-320.png`. Three matching substantive messages, oldest-first, with a real authenticated image attachment (the approved plate used as the layout-sketch fixture), current design/gate context. Not a claim of pixel equality: app retains additional work tabs, real source IDs, source metadata and bounded scroll. The image makes the third message scrollable below the thread viewport. Representative composer top is y768; its footer needs page scroll at 900px height. This is materially less chrome, not a claim that the complete composer/history fit above the fold.

235-message stress case retains exact total/order, both older-page loads, unsent draft and relative viewport anchor (<2px). Its textarea is y837 versus QA's y1115 baseline; screenshot `populated-viewport.png` and full `populated-1440.png` in the remediation folder. No requirement that all235 rows fit.

Creation regression rerun includes real exact title/raw-words persistence, focus trap/return, body scrolling, all theme serious/critical axe checks and bounded desktop/320/844 geometry. Fresh selected creation screenshots copied into remediation folder; inspected light desktop, dark narrow and HC short screenshots. Short/narrow modal content scrolls under fixed actions, rather than all fields fitting at once. Canonical QA still owns comprehensive visual acceptance and any clipping assessment.

No new consult: dispatch explicitly waived an additional consultant for bounded repairs; prior completed adherence and QA consult provenance remains in prior reports. No shared service restart, deployment, native desktop notification claims, actual200% browser zoom claim, Google/Slack linking, live DB mutation or Usage-source activation.

## Criterion evidence map

- c-1a55d4469b: NewEpicDialog6 + workflow focus/scroll/draft/reset/geometry rerun; base report-d9cc90d322.
- c-748939618f: title_words17 + actual browser creation at3 viewports; explicit title and verbatim words maintained.
- c-156f3fc7ca: refreshed creation theme/viewport captures + axe/build; independent QA look pending.
- c-bb74091ea1: NewEpicDialog6 existing failure/duplicate/spawn-retry/capability assertions remain green; base implementation unchanged.
- c-ea24775b1d: typed review, reopened gate, ordinary comment, source authorization race, legacy owner boundary tests above; base review coverage retained.
- c-7c8401b473: real expand/failed-file retry, server-derived attention, source navigation,235-history preservation, representative comparison; final QA hierarchy/routing/wake/auth acceptance remains pending.

All code/screenshots are review candidates. QA fail verdicts are not self-overridden by the doing seat.
