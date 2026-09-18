# Architect disposition: limited visual reference only

The generated plate is useful for board context, hierarchy and labelled control placement. It is **not acceptable as an authoritative icon or identity master**. Retain the original PNG unchanged as evidence of the one requested run. Carry the usable composition forward for architect inspection; reject the incorrect glyph details and shading from downstream adaptation. Owner publication has not happened and is not implied.

## What the image actually gets right

- The left epic occupies approximately 66% of the 1586 × 992 image. Sidebar, title, metadata, document links, conversation and composer remain recognizably anchored to the light reference.
- Exactly five task rows appear inside a compact Work section. Approximate conversation span is y=283–555 (272 px); Work is y=558–801 (243 px). The conversation stays visually larger.
- Ready at approximately (594, 642) is an outline circle with an empty center and no baseline. This is the authoritative requested change and a usable directional example.
- Epics reads as overlapping records; Work as one list; Design as a document; Files as a folder; Attach as a paperclip; History as a backward clock; Reply as a bent arrow. Labels are present. These are visual observations, not validated small-size SVG geometry.
- Morgan remains recognizably the peach/brown/teal human identity; architect remains a cream lobed spark on periwinkle; consultant remains an orbital family on navy. There are no robots, costumes, provider logos or garden scenes.
- The right side retains version context, approval/request actions, a document region and a feedback composer with Attach/Expand/Send feedback. It remains recognizably related to the supplied dark review.

## Failures and limits — do not copy these details

| Item | Observed result | Disposition |
|---|---|---|
| Partial | Approximately (594, 746): a single checked box, with no clearly separate open checklist row. It risks meaning Done. | Reject glyph. Require one checked row AND one open row. |
| Blocked | Approximately (594, 782): salmon-filled octagon, missing the required horizontal bar. | Reject glyph. Outline octagon plus clearly visible bar; label remains required. |
| In progress | Task row near (594, 676) uses a fully dotted ring; header has a different treatment. | Reject inconsistency. Use one static, mostly continuous unfilled ring with a short dotted gap. |
| In review | Small document mark near (594, 712); comment bubble is not unambiguous at this size. | Unverified/hold. Resolve document-plus-comment silhouette in manual geometry. |
| Consultant | Navy/gold identity survives, but gold orbital outlines dominate; required light-blue arcs and pale satellite are not faithfully reproduced. | Reject new geometry; retain existing source orbit. |
| Architect | Recognizable lobed spark, but source-accurate six-petal topology and consistent padding are not proven by this raster. | Keep original six-petal geometry as authority. Inspect at actual target sizes. |
| Human face | Recognizable Morgan but regenerated facial details/proportions drift. | Do not replace any human SVG with this raster or trace. Preserve all eight original IDs/assets. |
| Surface style | Visible tonal shading/vignetting and highlights on surfaces/buttons despite the flat-art request. | Reject shading; use flat CSS fills and quiet dividers. |
| Dark review composition | Feedback is stacked below the document instead of the original side-by-side modal. An unrequested large sketch preview was added. | Useful only as a secondary context study. Original review composition remains layout authority. Remove added preview unless separately justified. |
| Functional scope | Extra task-leading document icons and row ellipsis affordances were invented. | Do not infer new actions or interaction requirements from these. |
| Review meaning | Explicit “posts to original conversation / requests changes” explanation and comment-only alternative from the original reference are absent. | Preserve original behavior/copy in implementation; this plate is not a workflow replacement. |
| Coverage | Drafted, Designed, Signed off, Done and Dropped are not shown. | Unassessed by this image. Use the exact written semantics below, not claimed raster evidence. |
| Output resolution | Requested advisory 2400 × 1500; actual tool output 1586 × 992. | Record as delivered; no upscaling, patching or retry. |
| Runtime and accessibility | No interactive app, keyboard behavior, actual contrast test, all-size inspection or high-contrast rendering. | Not established. This image supplies no runtime proof. |

## Measurable bars for manual adaptation

These are proposed acceptance thresholds, not claims that the generated PNG passed them. Measure in CSS pixels or normalized SVG viewBox coordinates, not by tracing the image’s antialiasing.

| Area | Acceptance bar |
|---|---|
| Functional icon box | 20 × 20 default, also inspected at 16 and 24 px at 100% zoom; nominal 1.75 px stroke at 20 px, 1.5 at 16, 2 at 24; consistent round caps/joins. |
| Padding/alignment | At least 2 px safe inset in the 20 px icon box. Icon-to-label gap 8 px ± 2 px. Optical center within 1 px of control center. |
| Labelled controls | 100% of specified controls retain visible names. Minimum 32 px control height in the desktop specimen; glyph must never determine the whole hit target. |
| Small details | Distinct strokes and interior gaps remain at least 1 px apart at 16 px. If semantic details merge, simplify detail while retaining words; do not invent a replacement metaphor. |
| Ready | Exactly one closed circular outline, zero internal marks and zero attached strokes. Empty interior at 16/20/24 px. No baseline. |
| In progress | Ring interior stays empty; 270–300 degrees of continuous perimeter, remaining 60–90 degrees a short gap with 2–3 dots. Static; zero animation, hands, triangles or filled sectors. Same shape in metadata and rows. |
| Partial | Exactly two legible checklist rows, one checked and one open; minimum 2 px vertical separation at 20 px; no filled fraction or percent. |
| Blocked | Eight discernible corners and one centered horizontal bar spanning 35–50% of octagon width. Bar remains visible at 16 px in light/dark/HC. |
| Identity sizing | Inspect original human and abstract identities at 24/28/36 px. Preserve 36-unit base geometry and 8-unit tile corner radius. Spark center within 0.75 base units; six petals visibly present; minimum 3 base units clear tile padding. |
| Human preservation | All eight IDs, SVG drawing data, preferences, names and fallback behavior unchanged. Zero new human identities. This generated face cannot satisfy source preservation. |
| Orbit preservation | Keep navy #172554 tile, gold #FBBF24 center, two #93C5FD arcs and pale upper-right satellite from existing source. No orbit-to-speech-balloon substitution. Role/model text remains explicit. |
| Flatness | Zero gradients, grain, inner shading, decorative texture or newly added role props inside avatars or functional glyphs. |
| Contrast | Proposed gate: text ≥4.5:1, required icon strokes/control outlines ≥3:1 against actual adjacent surfaces. Measure actual tokens in light and dark; inspect forced-colors separately. No pass is claimed here. |
| Context hierarchy | In a comparable desktop specimen, title → metadata → links → conversation → compact work → composer. Work sample ≤5 rows and ≤28% of content height; conversation allocated height ≥Work height. |
| Original review relationship | Preserve original modal document/feedback relationship at its reference viewport, visible version and review actions. Any narrow stacked view requires separate responsive inspection. |
| Color independence | Every status has words; every required semantic distinction remains visible with all status hues replaced by one ink color. |
| Recognition check | Architect checks Epics vs Work, Files vs Attach, Signed off vs Done, Ready vs In progress and Partial vs Done at 16/20/24 px. Any conflated pair is a fail, even if the larger art looks attractive. |

## Exact semantic contract

| Meaning | Required form |
|---|---|
| Epics | Two overlapping work records. |
| Work | One task-list rectangle with rows. |
| Design | Folded-corner document. |
| Files & evidence | Tabbed folder. |
| Attach | Paperclip. |
| History | Backward/counterclockwise clock. |
| Reply | Bent return arrow. |
| Drafted | Paper plus a small pencil. |
| Designed | Plan document with two linked nodes at small sizes. |
| Signed off | Document-check; approval of plan, distinct from completed work. |
| Ready | PLAIN EMPTY CIRCLE. User override supersedes the baseline in remaining-semantics.md. |
| In progress | Static unfilled activity ring with short dotted gap. No play/fraction/clock. |
| In review | Document with compact comment bubble. |
| Blocked | Octagon with horizontal bar. |
| Done | Circle-check. |
| Partial | Mixed checklist: one checked row, one open row. No half-fill or percent. |
| Dropped | Circle-slash. |

Literal words remain primary. These statuses do not represent shell presence, heartbeat or availability. Review requested is attention from an actual request, not automatically inferred from In review. The five generated task names and assignments are illustrative mock content, not live board data.

## Lineage and next review

The two supplied contextual PNGs and the existing identity source predate this run. Existing candidate SVGs also predate it; none were created, derived, traced or retrospectively validated by this later generation. No candidate vectors or runtime files were modified.

Use the original attached references for hierarchy and review composition; use existing avatars.py for identity; use the user’s semantic requirements and bars above for manual glyphs. This image contributes only an additional contextual comparison source. It is not a substitute for those authorities.

Architect inspection should record acceptance or rejection of the usable composition, then verify corrected manual assets in labelled controls at 16/20/24 px, identities at 24/28/36 px, light/dark/HC surfaces, and the built app if implementation follows. Those checks are outstanding and outside this image-reference packet. No owner approval is claimed.

One tool run completed successfully. Zero retries. No CLI fallback. Quality failures remain visible in the unaltered PNG and are recorded above.

