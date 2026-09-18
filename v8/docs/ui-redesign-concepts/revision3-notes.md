# Revision 3 — restrained retro Board

**Judgment: the generated finish fails.** `revision3-retro-epic.png` is the requested real image_gen result (1536 × 1024), but unwanted cloudy dark shading obscures the title, thread, metadata and lower Usage control. Do not copy that lighting or treat this as an approved screen. No retry or retouching was performed. This remains a proposed art direction, not approval, implementation or test proof.

## Direction to retain

Brand **Board**; neutral fictional epic **Board improvements**. Revision 2 supplies interaction exploration only. Retain a broad conversation, full composer, familiar compact portraits, ink-outlined status badges, drawn functional icons and one small creative image reply. Personality belongs in those small elements, not a themed scene or oversized illustration. Flat cream and cocoa ink replace sage/garden styling. The generated status shapes and outlined controls communicate this direction better than its failed background.

## Measurable style bars

- Solid paper `#FAF4E8`, ink `#29251F`, muted ink `#655E55`; butter `#F2D88A` for progress and soft coral `#E9A58D` for review requests. No texture, gradient, scrim, blur, vignette or avatar glow. Background fields are uniform fills; opacity 1, background-image none, filter none. A few controls may have a crisp 1px ink offset, never a blurred shadow.
- Readable sans body 16–17/24px; metadata at least 14/20px; modest characterful title 32–34/40px. No novelty long-message font. Controls at least 44 × 44px; ink-outline 1–1.5px; 6–8px corners; 2px visible focus ring.
- Target text contrast at least 4.5:1. Specified ink on cream calculates to 13.90:1, butter 10.85:1 and coral 7.42:1; muted ink on cream is 5.83:1. These are token calculations, not validation of generated pixels. Status also requires an icon/shape and a label.
- At 1536 × 1024: rail 192px; main content starts around x=248; 24–32px section gaps; compact header/metadata/links within the top 290px. Thread and full composer consume at least 65% of main content height. Composer remains visible, 200–220px high; earlier messages scroll above it.
- Human/bot portraits 32–36px in messages, 24–28px in metadata; functional icons 20px with coherent 1.75px round strokes. No full-screen decorations. Inline sketch approximately 256 × 112px, at most 4% of desktop area.

## Identity continuity from avatars.py

Read the actual local `src/edp8/avatars.py`; its path/hash are in provenance. Keep the eight existing human IDs `human-01` through `human-08`, their names, colors, silhouettes, selected preferences and deterministic fallback unchanged. The fictional Morgan shown here illustrates the existing human-01 vocabulary: peach `#F3B89A`, brown hair `#8B4A32`, teal shirt `#168B82`, tan face `#D9A07D`. Morgan is not a new avatar ID or a replacement for the user's choice.

Architect refinement must retain its indigo `#5865F2` rounded tile, cream `#FFF3D8` six-lobe spark and pale drafting marks. Improve silhouette/stroke clarity at small sizes; do not introduce a new robot face or identification scheme. Preserve other roles' colors/motifs, system identity, consultant/model override and accessible labels. The raster avatars are approximate concepts, not replacement identity assets. No SVG/icon set or application changes were made.

## Exact surface and retained interactions

Rail: **Epics**, **Seats**, compact **Needs you 2**. Lower rail: closed **Usage** button directly above **Find**, then account if space permits. No primary Library/Usage route. Usage still opens the small nonmodal widget defined in revision 2; this image intentionally shows none.

Header: **Board improvements**; purpose “Make everyday coordination clearer, warmer and easier to act on.” Strip: **Status — In progress** with half-filled progress-circle badge; **Owner — Morgan** with existing human portrait; **Assigned — architect** with existing role tile; **Needs attention — Review requested** with diamond/exclamation badge. Blockers use a distinct blocked icon plus plain reason.

Near-header controls: **Design v3 · review requested**, **Files & evidence**, **History**, **Work**. Use drawn document, files, clock and checklist icons. **Actions** holds only real existing uncommon operations; do not fabricate Pause/Retry. Preserve existing help and tooltips, including keyboard access. No Unicode arrow strings as control substitutes.

Composer preserves **To: architect**, selectable **Type: Message**, text, mentions, attachments, **Expand**, **Send** and help. Keep every existing supported message type/capability. Expanding or viewing attachments/documents retains recipient, selected type, text, mentions and attachment state. A friendly visual treatment must not reduce message functionality.

Design opens the contextual review viewer; popup and explicit dedicated tab share source epic/ticket, gate, document and reviewed version. Review actions travel with that context. Normal comments and change requests return to the source conversation, never a separate document chat. History remains a contextual popup with Conversation / Decisions / Status & assignments / Documents / Activity and optional Open in tab. Cross-epic archive discovery stays in Find.

## Inline creative image replies

Keep inline renders as first-class conversation content. The synthetic example is **board-layout-sketch.png · Concept sketch**, with a clear **View image** control. Suggested alt: “Board layout sketch showing navigation, a conversation thread and a message composer.” Caption provides filename and purpose; alt describes the image rather than inventing its details.

Fit the preview without cropping; reserve its dimensions to prevent layout shift. View image opens a full-size viewer with zoom, caption, Close and keyboard access; closing restores focus and the untouched epic draft. Explicit Open in tab is optional. Do not execute active content from attachments; show a filename/fallback when previewing is unavailable. This board-layout sketch is fictional illustration, not a screenshot proving behavior.

## Non-copyable generation inaccuracies

Severe cloudy shading is the principal failure and also makes Usage/Find insufficiently legible. Human and bot avatars are enlarged beyond the 32–36px bar. The architect tile gains a blue glow and altered corner marks; preserve the source motif and flat color instead. Human facial/hair shapes are approximations, not exact existing SVG paths. The rail is wider than specified; caption and timestamp contrast suffer. The sketch contains schematic marks, not implementable UI text. Main labels appear mostly spelled correctly, but this is visual inspection, not exhaustive glyph or accessibility testing.

One built-in call, zero retries; original PNG copied unchanged. All prior files preserved by SHA-256 comparison. Synthetic UI copy and summarized avatar shapes/colors only went to image_gen; no private board content or source file was uploaded. Exact prompt is in `revision3-prompts.md`; source/output paths, hashes and checks are in `revision3-provenance.json`.
