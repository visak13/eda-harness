# S3 engineering handoff — 2026-09-18

Story `s-4983df7e94`, governing `design-f716d0d138` v7 and approved revision-3 visual addendum. Engineering evidence, **not QA verdicts or owner acceptance**. No shared service restart/deployment or full web e2e performed.

## Delivered
- Explicit trimmed Title / exact raw request words, bounded focus-trapped/inert creation modal, failure draft preservation, pending guards and same-ID spawn retry. Legacy title-only API callers and model/effort tags retained.
- Conversation-first Epic/Ticket with visible status/owner/requester/assignee/attention, collapsed secondary work, contextual Design/Files/History and dedicated records view. Existing Find/Browse-all and legacy archive routes retained.
- Shared contextual/dedicated document review: explicit source selection, pinned doc/version/source actions, local full Composer feedback, optional new tab retaining source/request/version. Typed server approval/request_changes and comments validate authority/source/version/current request; atomic persisted idempotent receipts and exact-version audit. Legacy gate_answer still acceptance-only.
- Shared Composer retains types, mentions, recipients/wake preview, help, attachments/paste/drop, reply, expand and authenticated media; tab-local source/reply and review drafts, saved delivery fields, pending-work guards. Stored artifact bytes distinguished from external/repo references (including image/file records without stored content); internal links stay in SPA.
- Contextual records directly scope documents/artifacts/history to the source, categorize outcomes, expose technical data secondarily and refresh via targeted events. No scope-based authorization inferred from a doc's scope string.

## One awaited adherence consult
`20260918T125609Z-a0181a8e`, purpose second_opinion, brief `docs/s3-adherence-brief.md`; returned `ok_concurrent_writes`. Read the completed answer, did not launch a second consult. Consultant metadata did not expose provider_model; do not infer it from requested model. Fixed its eight findings:
1. Store post-commit callbacks now execute outside Store lock (two-lock inversion regression for both immediate/deferred callbacks).
2. Typed review requires the resolved matching human epic owner, including denying ownerless epics.
3. Feedback retry key/signature survives closing/reopening/reload, preserving uncertain-result replay identity.
4. Pending upload/send/approval blocks destructive route/version/source/expand/dismiss transitions; held navigation cancels rather than firing after completion.
5. Composer instance identity keyed by source/reply context; sent reply draft clears synchronously before unmount.
6. Kind/recipient/user-selection state persists with the draft across expand/remount.
7. Files-to-doc transition uses one URL update; no stacked files/doc modals; source retained on records routes.
8. A nested readable document remains readable when a proposed source cannot authorize review; review controls are withheld and explicit source selection offered.
Additional fixes from own reruns: footer wrap at 320px, auto-cleared pending-close status, existing-epic navigation after partial spawn success, authenticated stored-content capability, and artifact insertion at caret.

## Final reruns
- `node web/node_modules/typescript/bin/tsc --noEmit -p web/tsconfig.json`: PASS.
- `npm --prefix web run build`: PASS; existing >500KB bundle advisory remains (final JS about 554KB, gzip about 170KB).
- `npm --prefix web run test -- --run --maxWorkers=1 src/components/ComposerDrafts.test.tsx src/components/ContextualWork.test.tsx src/components/DesignReview.test.tsx src/components/Composer.test.tsx src/components/DocView.test.tsx src/components/DocDrawer.test.tsx src/components/ArtifactLink.test.tsx src/components/NewEpicDialog.test.tsx src/components/AppShell.test.tsx src/pages/Epic.test.tsx src/pages/Ticket.test.tsx src/pages/Artifact.test.tsx src/pages/Doc.test.tsx src/api/endpoints.test.ts src/live`: **145 passed, 17 files**. Listed nonexistent test globs add no tests; Vitest's actual total is authoritative.
- `.venv/Scripts/python.exe -m pytest tests/test_design_review.py tests/test_title_words.py tests/test_board.py tests/test_store.py tests/test_service.py tests/test_epic_phase.py tests/test_uploads.py -q --tb=short`: **123 passed, 1 skipped**; two existing Pydantic enum serializer warnings. Earlier test-only tuple/seat-ID fixture mistakes were corrected and rerun green.
- `EDP8_BOARD_CMD='C:\Projects\Learning\eda-base3\v8\.venv\Scripts\edp8-board.exe' npm --prefix web run e2e -- e2e/s3-review.spec.ts e2e/s3-workflow.spec.ts --workers=1 --max-failures=1`: **5 passed**, isolated fixture service, no shared DB/process. Internal loops check all eight themes at 1440×900, 320×568 and 844×390 for creation/review; axe WCAG2A/AA serious/critical violations zero. Reachable Create/Send trial clicks, bounded/inert creation, focus/Tab/Escape/body-scroll restoration, real create/raw words, reset on success, local request-changes attachment finalization and exact-v2 approval, pending route/version/dismiss blocking and source draft/history preservation.

## Criterion evidence map
- `c-1a55d4469b`: NewEpicDialog unit tests + s3-workflow browser geometry/focus/inert/Escape/body restore/real success reset; creation-failure retention tested separately.
- `c-748939618f`: test_title_words.py + real-browser HTTP creation compare separate explicit title with exact whitespace/newlines. Blank/capped fields and legacy callers covered; existing UI effort/capability tests retained.
- `c-156f3fc7ca`: built screenshots `web/e2e/evidence/s3-new-epic-{1440,320,844}-{folio,obsidian,folio-hc}.png`, with matching `-controls.png` after internally scrolling to Effort; all-eight-theme geometry/axe loop and build above. Engineer inspected representative light, dark and HC images; QA must inspect independently.
- `c-bb74091ea1`: NewEpicDialog tests cover unchecked spawn, capability gating, Claude effort cap, pending duplicate/dismiss guards, preserved created ID and single ticket POST across spawn retries.
- `c-ea24775b1d`: test_design_review.py validates source/gate/doc/version, matching owner, stale/duplicate/concurrent decisions, rollback/no phantom publication, forbidden attachments, source architect recipient, exact audit and legacy compatibility. DesignReview tests include uncertain-response retry after unmount and readable nested doc fallback. Browser deep link and dedicated-tab context plus real feedback/approval exercise complete workflow.
- `c-7c8401b473`: `s3-conversation.png`, `s3-review.png`, contextual API/Files-to-doc/targeted cache tests, Composer draft/semantic/reply tests, retained Composer and routing/auth unit suites; source draft survives opening/closing History in browser. Engineer inspected built source/review screenshots; final look/parity verdict belongs to QA.

## Remaining independent acceptance work
QA owns criterion evidence attachments/verdicts, final visual fidelity judgment against approved references, comprehensive populated Epic/Ticket histories, every legacy workflow and actual browser 200% zoom. Small viewport testing is **not claimed as actual zoom**. The source fixture screenshot is an empty conversation with a draft, not proof of a long populated production thread. Eight-theme automatic axe checks are not a complete accessibility audit. No live deployment was attempted. Owner has received an early inline demo; owner approval remains outstanding.

All implementation/report/screenshots are in the story's repo-reference commit. No tasks created; no open product questions. Unrelated shared-tree scratch files were neither edited nor staged. The engineering seat releases browser/consult resources before handoff.
