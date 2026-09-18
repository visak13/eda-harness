# S3 final compact hierarchy correction

Dispatch: m-87334969b2; architect visual disposition m-87397f33e2. Base 844260d, independently rechecked in 1e35dd1 / report-30e051dc55. This supplement addresses the remaining hierarchy failure; it does not replace earlier functional evidence or independently approve the story.

## Changes
- Below 768px, a 60px header and accessible Menu disclosure replace the always-expanded global shell. One mounted navigation/preferences/Usage/Find tree; Usage still immediately precedes Find. Menu exposes aria-expanded/controls, normal keyboard traversal, Escape/focus restoration, and closes on route changes. Nested Preferences/Usage Escape closes only that panel; Ctrl-K remains available while the menu is closed and returns focus to Menu. Desktop retains its rail.
- Removed the duplicate global Workspace/Epic breadcrumb on detail routes. Epic retains its real parent breadcrumb, id and status. Owner/requester/assignee/attention remain visible, compact inline metadata rather than hidden details.
- Removed Epic's Overview/Work/Documents/Thread tab system. Conversation and full composer stay mounted; total is now in the Conversation heading. Contextual Work opens the below-conversation work/acceptance/process disclosure, preserving overview pulse, criteria/evidence, brief/latest steer, filters/tree/kanban and existing secondary operations. Documents use Files & evidence (including truthful empty state), Design/History and dedicated viewers remain unchanged.
- Legacy `?tab=overview|work|documents|thread` and matching hash links resolve to these destinations. Documents canonicalizes to the source Files viewer; closing it does not reopen it. Message hashes take precedence over obsolete tab selection. Existing archive and dedicated viewer routes unchanged.
- No review, authorization, upload, notification protocol, message semantics, backend or identity changes. No capabilities removed.

## Direct built comparison
Inspected approved `docs/ui-redesign-concepts/s1-assets/final/packet-epic.png`, previous `evidence/s3-remediation/representative-{1440,320}.png`, and fresh matched three substantive messages plus real image attachment under `web/e2e/evidence/s3-final-layout/`.

| Measurement | Previous | Corrected |
|---|---:|---:|
| Narrow shell | ~390px | 60px |
| Narrow conversation start | ~1000px | 466px |
| Desktop first message | ~450px | 333px |
| Desktop representative composer top | 768px | 651px |
| 235-message stress textarea top | 837px | 720px |

At 320x568 the conversation begins within the initial viewport, metadata and context actions remain readable, no horizontal overflow. Desktop no longer presents duplicate navigation. The image/thread still uses an internal scrollbar; not all three long messages fit at once. Desktop composer bottom is 931px, so its footer still needs a small page scroll at height900. This is not a pixel-equality, all-content-above-fold, native notification, or actual browser200%-zoom claim. Canonical independent QA owns hierarchy acceptance.

`navigation-320.png` shows the deliberately expanded menu; the tall disclosure is user-requested, not initial chrome. Usage narrow captures are synthetic fixture demonstrations, not live account observations. Creation captures preserve three widths and light/dark/HC; preview bottom is reachable above the fixed actions at320/844. Original QA/red/reference captures remain unchanged. Updated samples were copied to this supplement before restoring test-written originals.

## Verification (serial; current build, isolated boards only)
- **121 Python passed**, existing two Pydantic enum warnings:
  `.venv/Scripts/python.exe -m pytest tests/test_design_review.py tests/test_views.py tests/test_board.py tests/test_human_plane.py tests/test_epic_phase.py tests/test_notifications.py tests/test_s22_rules.py tests/test_title_words.py -q`
- **137 UI passed** in10files, plus **6 NewEpicDialog passed**. Run from `web` with `npx vitest run --maxWorkers=1 --no-file-parallelism` and:
  `src/pages/Epic.test.tsx src/pages/Ticket.test.tsx src/pages/Decisions.test.tsx src/components/AppShell.test.tsx src/components/ContextualWork.test.tsx src/components/Composer.test.tsx src/components/DesignReview.test.tsx src/components/NotificationCenter.test.tsx src/components/UsageWidget.test.tsx src/test/deadControls.test.tsx`; separate `src/components/NewEpicDialog.test.tsx`.
- **41 focused browser cases passed**, single worker, no full e2e:
  `UV_NO_SYNC=1 npx playwright test e2e/qa-ui-integration.spec.ts e2e/s3-compact-layout.spec.ts e2e/s3-workflow.spec.ts e2e/s3-review.spec.ts e2e/qa-modal-reachability.spec.ts e2e/s2-foundations.spec.ts e2e/s6-usage.spec.ts --grep-invert 'built theme' --workers=1`
  Coverage:10 original QA regressions;12 compact navigation/legacy/hash cases;4 creation/conversation cases;1 source-review case;2 short-modal cases;8 preference sizes;4 Usage integration/all-theme cases. Includes expanded failed-File retry, reopen-gate idempotency, ordinary feedback, pending authorization open/dismiss/navigation races, exact negative ruling, full235 history/order/draft/relative-anchor (<2px), nested Escape/Find focus, retained DOM composer, and axe checks in compact layouts.
- `npx tsc --noEmit`, `npx vite build`, `git diff --check` pass. Existing >500KB build advisory remains.
- Logs: `.run/s3-final-layout-{python,unit-serial,creation,browser-final,tsc,build}.log`.

## Characterization / test changes
- Removed-tab selectors necessarily target the Conversation count, Work disclosure and contextual Files instead; count235/order/draft assertions unchanged. Status uniqueness now scopes the epic header (mounted child work rows have their own legitimate status chips). Added absence-of-tablist assertions.
- Existing narrow Preferences/Usage browser tests open Menu first; all old bounds/focus/theme/draft assertions retained.
- Dead-control fixture lacked `/contextual` and returned a catch-all array, causing a route error before controls rendered. Added the proper typed mock; no production defensive masking or weakened lint.
- Initial multi-file UI run hit a5s235-row timeout under concurrent Vitest files; serial run passes unchanged assertions/timeouts. Initial browser invocation without UV_NO_SYNC attempted to resync the shared venv and hit the locked board executable; retried with UV_NO_SYNC=1, never stopped a shared service. Initial new navigation test used an empty epic yet asserted work search; corrected fixture to create a real story. Failures and corrections retained in `.run/s3-final-layout-*` logs.

## Criterion map (QA verdicts remain QA-owned)
- c-1a55d4469b: focus/inert/Escape/draft and short-view creation41-case browser subset +6UI.
- c-748939618f: title/raw words17Python within121; exact real creation browser cases.
- c-156f3fc7ca: fresh built creation screenshots320/844/1440 light/dark/HC and short-modal bottom captures, inspected; independent look disposition remains QA's.
- c-bb74091ea1:6NewEpicDialog cases plus existing server121 and exact-create browsers preserve pending/capability/spawn behavior.
- c-ea24775b1d: source review/negative feedback/race/owner suites remain green; no protocol changes in this patch.
- c-7c8401b473: compact shell/context consolidation,12new routing/navigation cases, full composer/history QA regressions and fresh matched screenshots above. Prior QA FAIL is not self-overridden.

## Handoff limits
No deployment/shared restart/live database or ownership edits, no full web e2e, no new consult per explicit dispatch waiver. Previous adherence-consult provenance remains in base reports. No owner approval inferred from sending previews (art-6c00d6256a / art-05f866e28e). Native consent0/80, actual200%zoom and the new identity story remain separate. Canonical qa.epic-44a0576511 should independently inspect/recheck this correction before any final acceptance.
