# S2 foundation delivery — s-ec85b2827f

Implementation handoff, **not acceptance**. Source commit `7606f28`; characterization `40ccb62`; first image evidence `91217ae`. Design `design-f716d0d138` v7, approved S1 final assets, plan `note-3ca603a42f`.

## Delivered
- Eight authoritative palettes/generated tokens/prepaint whitelist, including page `#000000` Obsidian. Existing IDs/default precedence retained. Strengthened original muted/control tokens against panel/rail/wash surfaces.
- Typed 46-name approved S1 icon inventory; exhaustive ticket-status map, no Decisions fallback. Functional back/external/close/version/expand controls adapted without removing labels. Approved bot templates integrate into Python; human constants/functions AST fingerprints unchanged.
- `AnchoredPanel` body portal, viewport/visualViewport placement, resize/scroll/content observation, bounded scrolling, nonmodal outside focus/pointer dismissal, Escape/Close focus return. Preferences persist themes/avatar IDs; keyboard radios preserved.
- 192px desktop shell; Epics/Seats/Needs you; `shell-usage-slot` immediately above Find for S6. Find now exposes Browse all records. Legacy routes remain; no Usage telemetry placeholder or duplicate Library primary destination.
- Intrinsic grids, wrapping tags/selects/tabs, keyboard-focusable local tables, contained doc columns. No body horizontal-overflow hiding.
- One authenticated feed; sequence replay dedup; 250ms affected-key coalescing, related ancestor/document scope handling, per-draft subject isolation and independent release. Explicit flush does not clear drafts. Composer send invalidation scoped. Avatars share authenticated bytes/object URLs, release last-owner resources, evict failures with bounded retry; saves update canonical ID and login alias.

## Exact verification receipts (final source)
2026-09-18, Windows, existing pinned packages/browser. No dependency updates, fleet restart, live DB/config changes, or full e2e. QA seat confirmed it had no concurrent browser/test work. Final unit/browser runs serialized one worker.

```bash
npm --prefix web run test -- --run --maxWorkers=1 src/theme src/live src/components/AppShell.test.tsx src/components/Avatar.test.tsx src/components/Icon.test.tsx src/components/Composer.test.tsx src/components/DocDrawer.test.tsx src/components/Drawer.test.tsx src/components/CriterionCard.test.tsx src/components/CommandPalette.test.tsx src/components/GlossaryPanel.test.tsx src/components/RulingDrawer.test.tsx src/components/GateForm.test.tsx src/pages/Ticket.test.tsx src/pages/Epic.test.tsx src/pages/Decisions.test.tsx src/pages/Seats.test.tsx src/pages/Library.test.tsx src/pages/Artifact.test.tsx
# 23 files, 508 tests passed, 48.38s
node web/node_modules/typescript/bin/tsc --noEmit -p web/tsconfig.json
# exit 0
.venv/Scripts/python.exe -m pytest tests/test_s2_avatars.py tests/test_api_views.py -k avatar -q
# 5 passed, 19 deselected, 1.22s
npm --prefix web run build
# exit 0; existing >500KB chunk advisory remains, not a build error
```

PowerShell browser command (Git Bash equivalent uses a quoted Windows-backslash environment assignment):
```powershell
$env:EDP8_BOARD_CMD = 'C:\Projects\Learning\eda-base3\v8\.venv\Scripts\edp8-board.exe'
npm --prefix web run e2e -- e2e/s2-foundations.spec.ts e2e/s2-live.spec.ts e2e/s2-reflow.spec.ts --workers=1 --max-failures=1
# 25 passed, 55.1s
```
Fixture starts/cleans its own process tree on an allocated port, temporary home/DB and fleet integration stripped. Do not run via `uv` while the shared executable is in use. A first launcher attempt with forward-slash relative `.venv/Scripts/...` failed under Windows cmd before browser checks; the command above fixes it.

## Criterion evidence map (all verdicts remain QA-pending)
- **c-7eb6adcd2f look:** `web/e2e/evidence/s2-{folio,dusk,ember,folio-hc,sage,slate,midnight,obsidian}.png`, theme contact sheet and `s2-reflow-320.png`. Engineer inspected the eight-theme contact sheet, full Obsidian and narrow screenshot: distinct quiet palettes, bounded readable preferences, labels retained, human faces unchanged. No screenshot baseline bulk acceptance. Runtime Icon tests cover 46 names/10 statuses; Python hashes/dispatch cover human preservation. **Actual 200% browser zoom and consolidated full visual/control-clipping inspection pending**.
- **c-258154a915 preferences:** `s2-foundations.spec.ts` first eight cases: all required viewport bounds; theme/avatar persist after reload; last avatar reachable; native theme arrow navigation; resize; Escape focus return; nonmodal Tab departure and outside pointer. Placement scroll listeners are implemented; explicit scroll-position stress remains a final QA check.
- **c-402dbfb5fc palettes/contrast:** `contrast.test.ts` expanded six-surface text/boundary/focus pairs, `s2-theme.test.ts` eight complete tables, emitted CSS parity, prepaint every stored choice/invalid OS defaults, exact black. Built theme browser cases inspect actual visible form boundary colors >=3 and axe serious/critical zero on Epic/preferences, Needs you, Epics and Seats (32 combinations). This is not a proof of every future S3/S6 component pair.
- **c-3787b40ce0 reflow:** `s2-reflow.spec.ts` 11 route destinations at all eight required sizes: Needs you, Epics, Epic Thread, Ticket, Seats, archive tickets/docs/artifacts/activity, Doc and Artifact. Real fixture includes long prose, 300-character tokens/tags/URLs and mention-like handles. No document horizontal overflow; tables locally scroll. Not a complete assertion of all hidden/expanded action clipping or every possible user name.
- **c-0c6a4ea21a regression:** 508 focused unit tests, 25 browser tests, tsc, build and five Python checks above. Existing auth/composer/route/drawer cases retained. New S3/S6 views must extend rather than replace this coverage.
- **c-31348ca75c live:** pre-change test commit records 20 global invalidations/20 events. `s2-live.spec.ts` real built app plus controlled delivered SSE fixtures: unrelated ticket page/avatars unchanged; relevant 20-event burst held; replay does not add duplicates; explicit flush one page refetch; same composer/avatar nodes and draft, caret/focus/scroll preserved before flush; text/node retained after flush; clean relevant message visible within2s; one relevant page refetch per delivered burst. Unit regressions cover nested task/doc scope, unrelated scoped archive/table, independent draft release. Existing feed fallback tests pass. This is a controlled local-response timing proof, not network/SSE availability SLA.

## Independent adherence read
Exactly one consult: `20260918T115216Z-f1e0bcde`, completed and read before handoff. Source-only. Manifest reports provider_model unavailable; actual answer recovered, no model identity invented. It found six concrete defects, all corrected and regression-checked:
1. Nested creations/new scoped docs could miss ancestor refresh -> parent containment and scope mapping.
2. Subjectless gate/criterion drafts and all-drafts release -> ticket scopes and independent clean-key release.
3. Unrelated scoped archive/table refetch -> event-family and scope filtering.
4. Essential inputs still used decorative line -> contrast-audited actual form boundary rule plus browser measurements.
5. Handle login failed canonical avatar bump -> bump canonical viewer ID and alias.
6. Rejected shared avatar promise poisoned cache -> evict failure, bounded retry, guard old-owner cleanup; added failure/partial-release/alias tests.
No second consult used for mechanical fixes. No sibling scratch files touched.

## Pending acceptance / handoff to S3, S6 and sole final QA
Architect accepted evidence limitation in **m-53743ca9d8**, expressly **not an acceptance waiver**. Criteria unchanged and pending.
- On isolated headed owner-supported browser, set browser menu zoom to **200%**; verify actual browser zoom indicator (not deviceScaleFactor/CSS zoom). Walk all routes listed above in Folio, Ember/Obsidian, Folio HC, then all themes for new S3/S6 surfaces. Open preferences, scroll to final theme/avatar, resize/scroll while open, close/reopen, Tab/Shift+Tab/Escape. Record screenshots and accessible control reachability, local table/code scrolling, no overlap/clipping, no draft loss. Reset zoom after test. Repeat reduced-height viewport/virtual keyboard cases where available.
- Inspect all route tabs/expanded folds, long real handles and action groups, source+viewer/composer combinations; existing reflow spec measures document width, not every clipping condition.
- S3 owns conversation-first layout/review/history/new epic and retains these tokens/Icon/portal/live APIs. Some legacy **explicit user mutation** handlers outside Composer still perform global invalidation; event-driven feed is scoped. S3 should narrow those when restructuring their workflows.
- S6 uses `AnchoredPanel` and mounts its independent Usage trigger at `shell-usage-slot`; no S2 fabricated data.
- Python bot changes need owner-managed deployment/reload; no shared service was restarted. Built assets generated locally are not a deployment or owner acceptance assertion.
- First owner demo uploaded as `art-f0167589c3` because this seat's exposed message tool lacks artifact attachment arguments; bounded multipart `/v1/artifacts/upload` and `/v1/messages` were used for the screenshot only. Original repo-only reference `art-bb57519b35` is superseded for inline viewing.
