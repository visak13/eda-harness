# S1 final contextual candidate — S2 integration package

**Only this `final/` directory is the current candidate. Parent icons/bots/runtime mapping are owner-rejected history. Internal direction approved m-61dd21edf0; owner/QA acceptance is not implied.**

## Read the board context first
- packet-epic.png: primary conversation/full composer, metadata, contextual document/folder/history/task-list controls and refined existing agent emblem.
- packet-review.png and packet-dark-review.png: document-local actions/feedback, labelled Expand, source/version context; flat dark surfaces.
- packet-work.png / packet-dark-work.png: optional Work-linked-record sample to inspect all ten states at16px beside task words and actual role labels. Not a new default home or fabricated progress dashboard. Full-page capture exceeds900px because ten rows plus composer are shown; no overlapping or clipping is claimed as a900px fit.
- packet-narrow.png:390px static composition, wrapping instead of icon-only nav/metadata; composer remains in natural flow. Not keyboard/real zoom/interactive proof.
- sizes-light/dark/hc.png: secondary16/18/24 appendix, NOT the main design pitch.
- generated-reference/: exact genuine revised image_gen source and limitations. provenance.md distinguishes source/refinement/manual geometry/history.

## Integration assets
- icon-paths.ts: finite `IconName`, ICON_PATHS, exhaustive ten STATUS_ICONS and STATUS_LABELS. Copy/adapt under runtime-owned path; no arbitrary string union/default Decisions. Runtime should `satisfies Record<TicketStatus, IconName>` against actual API type. Validate dynamic unknown input explicitly, render neutral unknown or omit decorative mark, not false Decisions.
- icons/*.svg: trusted local 24-grid geometry,1.8px rounded currentColor strokes, aria-hidden/focusable=false. All paths unfilled including Partial checklist. No scripts/resources/filters/gradients/raster fragments. Instantiate as trusted static React geometry, not uploaded SVG markup. Keep button/label text; icon-only actions require purpose-specific accessible name. Targets>=44px independent of glyph size.
- bot-templates.json / bots/*.svg:36-grid continuity-first identities. Existing spark/orbit vocabulary, no arbitrary costumes. Copy template BODY into existing backend `_svg` wrapper so size/decorative/current API semantics remain. Existing human branch/IDs/names/preferences/deterministic fallback untouched. Actual role/model text mandatory; same-spark roles distinguish through text, never hue alone.
- Dispatch remains human first; nonhuman consultant OR model contains gpt -> consultant/orbit; known role -> its role template; unknown -> unknown system fallback. Do not infer provider/role from artwork. Unknown retains existing `Board system` SVG label for compatibility; visible context must state Unknown when appropriate, not claim known identity.
- Authenticate avatar content via fetch/blob URL, preserve cache/lifecycle/revoke; no raw unauthenticated endpoint img. Source packet uses file assets only as STATIC specimens, not application auth pattern.
- SME amber adjusted #C88719 -> #AC7215 preserving hue family: original spark contrast2.75 failed3:1, revised3.69 passes. Other role colors unchanged. All spark/background pairs>=3; surface/focus boundaries and every actual theme/control pair still tested by S2. Images containing text labels never substitute actual DOM labels.
- status-in_progress is static activity, not progress fraction, playback action or shell state. ready is unfilled circle. signed_off document-check differs from done circle-check. in_review document/comment differs from review-request attention bubble. partial is mixed checklist, dropped is discontinued slash, not delete. Never infer states/counts from shell liveness.
- Compatibility: original ten names plus navigation/actions listed in ../inventory.md. library stays for archive/backlinks, not primary nav. play ONLY actual authorized spawn/resume control, not new Pause/Retry. Replace arrow-like CONTROLS only, not prose/history/document content; native select arrows remain native.

## Re-run from v8
```
.venv/Scripts/python.exe docs/ui-redesign-concepts/s1-assets/final/build_final.py
.venv/Scripts/python.exe docs/ui-redesign-concepts/s1-assets/final/build_packet.py
.venv/Scripts/python.exe docs/ui-redesign-concepts/s1-assets/final/check_final.py
node docs/ui-redesign-concepts/s1-assets/final/render.cjs
```
Existing installed Playwright Chromium required for renderer. One owned browser with finally-close; local files only, no board/server or full e2e. Renderer checks 171 instances at 16/18/24px in each theme, all referenced avatar images loaded, Work/composer non-overlap,390px no horizontal overflow. render-evidence.json records screenshot hashes. Human-preservation.json pins ASTs for human functions/constants, not unrelated backend code. DO NOT auto-bless fingerprints if a human behavior changes.

## Actual verification to date
All commands above passed. Read all nine PNGs. Designed detail and Partial checked/open rows remain differentiated at16px with labels; same-family spark roles intentionally rely on real role text rather than arbitrary pictures. SVG XML allowlist/exhaustive state map/human AST checks passed. Specimen ink/ground13.90(light),14.94(dark),21(HC); spark/background3.38–5.17. Not proof of all eight actual runtime theme pairs.

## Reference scope carried forward
../integration.md specifies conversation-first, contextual design/history/files, compact Usage immediately above Find (Fable within Claude), narrow layout, true-black Obsidian, no garden/shading/invented operations. Its old asset-specific45/11 and half-circle instructions are SUPERSEDED by this README/runtime mapping. Exact prior clean reference images remain composition anchors, not implementation proof.

## Adherence / remaining acceptance
Required independent second_opinion run 20260918T102902Z-d8c9e746 completed and read. Both verification gaps fixed and rerun; see adherence.md for findings and explicit evidence limits (earlier Usage reference, written History, unrendered narrow review). Architect inspection of coherent final packet and coordinated owner publication/reaction remain. QA owns verdicts. S2 owns built integration and actual theme, identity/auth, accessibility/interaction/zoom checks. S1 touches no runtime files, shared services or dependencies. No assertion of production delivery.
