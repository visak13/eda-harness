# S1 inventory before generation

Source snapshot: Icon.tsx, AppShell.tsx, Composer.tsx, Drawer.tsx, DocDrawer.tsx, ArtifactLink.tsx, CriterionCard.tsx, StatusControl.tsx, Epic/Ticket/Doc/Artifact/Seats/Decisions pages; src/edp8/avatars.py. Runtime integration belongs to S2/S3, not this directory.

## Functional keys and consumers
- Compatibility ten: decisions (Needs you / Decisions), epics, seats, library (archive compatibility), find, add, close, chevron, copy, external.
- Navigation: back (Doc/Artifact/Ticket breadcrumb, DocDrawer stack); forward (Seats/detail/history links); history, files, design, work (context links per v7).
- Composer/thread: reply, expand, collapse, attach, mention, help, send; close also removes an attachment or cancels reply with contextual accessible label.
- Account/actions: preferences, usage, refresh, filter, sort, edit, check, warning, more, download, link, play (existing spawn/resume ONLY). Text-only authorized operations may stay text; icons must not imply new permissions/actions.
- Existing Unicode control arrows in Doc/Artifact/Ticket breadcrumbs, CriterionCard/RulingDrawer external links, DocDrawer version disclosure, Epic history/link calls and Seats detail link become glyphs. CSS summary chevrons in Epic/ui/DocView become the chevron with rotation. Arrows in prose/test explanations/status-history sentences remain meaningful text, not globally replaced.
- Native select controls keep platform arrows. Principal action targets >=44px independent of glyph size.

## Ticket state keys (all ten; label always accompanies glyph)
|State|Visible label|Distinct silhouette|
|---|---|---|
|drafted|Drafted|paper and pencil|
|designed|Designed|set square|
|signed_off|Signed off|seal and check|
|ready|Ready|flag|
|in_progress|In progress|clock hand|
|in_review|In review|eye|
|blocked|Blocked|octagon with bar|
|done|Done|circle and check|
|partial|Partial|half-filled circle|
|dropped|Dropped|square and diagonal cross|

Presence is separate (Alive/Parked/Stalled/Closed/Availability unknown); do not substitute ticket state icons as progress. Unknown runtime names must not silently fall back to Decisions.

## Identity keys and preservation
Agent roles: owner, coordinator, architect, engineer, reviewer, adversary, qa, sme, consultant; plus system and unknown. Preserve backend dispatch rule consultant OR model containing gpt -> consultant illustration, with actual role/model text retained alongside. Artwork never supplies identity/model inference. Existing other roles stay distinct through motif/shape, not just color.
Human IDs human-01..human-08 and names Rowan/Mira/Dev/June/Sam/Noor/Eli/Aya unchanged. Keep preference storage, deterministic fallback and existing human SVG functions byte-for-byte. No human selections migrated. System/unknown are not people.

## Visual adaptation contract
24px control grid; 2px rounded currentColor strokes, safe simple SVG geometry without scripts/resources/filters/gradients. Inspect at 16/18/24. Quiet flat panels, no cloudy shading, garden imagery, provider logos or giant mascot. Bot motifs adapt generated source into compact illustrations rather than cropping tiny cells from a sheet. SVG source and explicit mapping are deliverables; generated contact sheet is provenance/reference only. Built-app inspection and actual color pairs are downstream S2/QA obligations, not proven by a specimen.
