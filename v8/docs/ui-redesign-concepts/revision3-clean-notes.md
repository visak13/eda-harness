# Clean v7 review specimens

Owner review packet: board message `m-692e2a0afa`, design `design-f716d0d138` v7. No design approval or implementation dispatch has occurred.

## What these are

`revision3-clean-epic.png`, `revision3-clean-review.png` and `revision3-clean-usage.png` are authored static HTML/CSS specimens rendered at 1440×900 using isolated headless Chromium opening a local file. They are **not raw image_gen outputs, running application screenshots, working prototypes or acceptance evidence**. All content and usage values are synthetic. No board/server request is made by the specimen or renderer.

The actual generated revision2/revision3 images, prompts and provenance remain unchanged. Both epic generations had unacceptable cloudy shading, explicitly rejected. The clear revision2 review-view image is an interaction exploration, not the latest retro styling. No additional generation retry was made to conceal these failures.

The clean specimens use actual existing human-01 and architect avatar SVG exports from `src/edp8/avatars.py`. These are reference copies only, not modified runtime identities. Control glyphs are hand-authored placeholders. The in-message image preview is a CSS diagram, not a real artifact/image-generation result. Final generated control/status/bot family remains S1 work, with actual runtime integration in S2. Do not count these screenshots as final icon delivery.

## Reviewing the direction

1. Conversation-first epic: compact identity/status/attention metadata; prominent contextual links; complete composer with recipient/type/mentions/attachment/expand/help. Existing avatar personality and restrained outlined badges, not garden artwork.
2. Design review: source/version header and review actions travel with the viewer; feedback composer stays beside document and posts to the original epic thread. Dedicated tab uses same context. Normal comments remain distinct from changes requests.
3. Usage: bounded above-Find widget, no new destination or background dimming. The static widget is positioned above the composer; responsive placement requires implementation/tests.

No primary Library destination. Categorized History and Files & evidence are contextual viewers, with global/archive discovery retained through Find/Browse all records. Written v7 contract governs interactions and overrides old concept notes.

## Inspection and limitations

Inspected all three renders. Corrected wrapping in Needs you, removed invented sorting text, moved Usage above composer bounds and shortened the review feedback field so preserved-draft feedback is visible. No production code changed. No interactivity, keyboard, responsive, zoom, all-theme, provider, OS-notification or accessibility testing is claimed. Some static controls are smaller than the final 44px principal-target bar; images communicate hierarchy, not exact acceptance geometry. Final implementation must satisfy v7 rather than copy these specimen dimensions blindly.

`render-specimen.cjs` regenerates the three PNGs and their SHA-256 manifest via existing web Playwright dependency. It starts only its own browser and closes it in finally; no listening service or shared process is touched. Run from repo with `node docs/ui-redesign-concepts/render-specimen.cjs`.

## Published board artifacts

- Epic: `art-c4590ae91a`
- Design review: `art-41995ef69d`
- Usage: `art-e4c0dbade2`

All three were finalized onto the epic by `m-692e2a0afa`. Existing exposed tools lack upload/artifacts arguments, so bounded REST calls were used and disclosed. This is the S7 tool-parity gap, not the intended final agent workflow.
