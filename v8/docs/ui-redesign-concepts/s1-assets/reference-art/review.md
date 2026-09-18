# Board family reference — creative review

**Accept as a coherent source for manual adaptation; do not approve as finished assets.** The generated sheet carries the approved screen's warm neutral base and quiet charcoal line language. Its useful personality comes from compact bot silhouettes. It does not redraw the screen or replace human avatars.

## Delivered evidence

- `board-family-contact-sheet.png`: unedited image_gen result, 1122 x 1402 pixels, 1,446,936 bytes.
- `prompt.txt` and `tool-request.json`: exact prompt and complete submitted arguments.
- `provenance.json`: one built-in generation, zero retries, original location, copy hash and verification limits.
- `mapping.json`: all 35 controls, ten ticket states and eleven identities, with row/column positions and adaptation notes.
- `image-measurements.json`: dimensions, SHA-256 and measured background samples.

## What succeeded

Visual inspection finds all 56 requested labeled drawings, with no missing or duplicated keys. Controls occupy five rows of seven; states two rows of five; identities six then five. Labels are readable at sheet scale.

All ten required state silhouettes are present. Signed off uses a scalloped seal while Done uses a circle. In progress has clock hands while Partial uses a filled half-circle. States communicate through shape without semantic color.

Bot roles share rounded dark outlines and compact optical eyes while varying their silhouettes. Architect, engineer, adversary, SME and consultant have especially clear shape differences. System and unknown are devices without faces. The generic seats control includes person outlines as requested; there are no human-avatar replacements. No visible provider logos, plants, scenery or full UI chrome appear.

## What failed or needs correction

1. **The solid-background requirement failed.** The cream field has subtle generated texture. A blank left-margin strip (x=3..18, y=50..1351) contains 30 RGB values; channel ranges are R 245–248, G 239–242, B 228–231. It is not a single-color background. Some bot fills also appear mottled/shaded. Use exact solid fills in adaptation; do not sample/crop the raster as assets.
2. **Requested pixel dimensions were not delivered.** The prompt asked for 2048 x 2560; the tool returned 1122 x 1402. The aspect ratio is close, but this is a smaller reference image.
3. **Collapse is overbuilt.** It has four inward arrows against Expand's two outward arrows. Redraw Collapse as the paired two-arrow inverse of Expand.
4. **Owner lost its key motif.** The antenna became a generic circle on a stem. Add a clear key tooth; remove Reviewer's unnecessary top antenna so those two do not converge.
5. **Engineer needs a clearer wrench contour.** The generated U-shaped crown can read as a socket or power motif. Clarify its open jaws without adding detail.
6. **Small-size clarity is unproven.** QA's check attachment, SME's spine, the gear teeth, Drafted's pencil and the state eye highlight need simplification review. Drop the eye highlight. Raster stroke weights and the exact 2px grid contract are not certified by this enlarged sheet.
7. **Hierarchy needs restraint during adoption.** The sheet's large headings and relatively heavy enlarged outlines are presentation devices. Do not carry their weight or scale into the board. Retain the approved screen's text-first hierarchy.

No second generation or cleanup pass was made, as requested.

## Measurable acceptance bars for manual source adaptation

| Area | Required bar | Evidence on this sheet |
|---|---|---|
| Inventory | 35 explicit control keys, 10 state keys, 11 identity keys; 0 silent Decisions fallbacks | 56 labels visually counted; explicit reference mapping delivered |
| Control/state grid | SVG viewBox 0 0 24 24; nominal 2px currentColor strokes; round caps/joins; artwork including stroke stays within x/y=2..22 | Target only; raster cannot certify |
| Geometry | Open gaps and critical internal separation >=2 source units on 24px grid; use optical adjustments to preserve them | Not measured on vectors |
| Actual display sizes | Inspect every control/state at 16, 18 and 24 CSS px at 1x and 2x; 0 clipped strokes, closed critical gaps or missing critical features | Downstream check, not performed |
| Shape recognition | At 24px, at least 4 of 5 reviewers match each state to its label in <=3 seconds in monochrome; no recurring confusion between seal/circle, clock/partial or square-X/close | Recognition test not performed |
| Bot construction | 32px base grid; 2px rounded outline; one dominant role motif, <=1 muted accent hue per bot; no body or peripheral scene; review at 24/32/40px | Family direction met; geometry and small-size bars unproven |
| Bot differentiation | At 32px monochrome, at least 4 of 5 reviewers distinguish every role using a labeled legend; identity text remains visible regardless | Shape differences visible large; grayscale recognition untested |
| Flatness | One exact neutral background RGB; each intentional fill uses one exact RGB; 0 gradients, textures, shadows or filters (antialiasing excluded at boundaries) | Background fails; fills need cleanup |
| Contrast | Final essential glyph/background pairs >=3:1; normal labels >=4.5:1 in every shipped theme/state | Actual app color-pair verification deferred |
| Targets and semantics | Principal action targets >=44 x 44 CSS px; state glyph always accompanied by its label; accessible contextual labels on icon actions | Runtime obligation |
| Safe source | SVG uses simple paths/basic shapes; 0 scripts, external resources, filters or gradients; controls inherit currentColor | Source adaptation obligation |
| Identity preservation | 8 existing human IDs/names retained; 0 human selection migrations; human SVG functions, fallback and preference storage unchanged | No human/runtime files edited |

## Mapping and integration boundaries

Use `mapping.json` with `../inventory.md`; sheet labels are annotations, not a dispatch mechanism. Consultant role OR a model containing gpt continues to select the consultant illustration under existing backend semantics. Always display actual role/model text. Other supported roles retain their distinct motifs. System and unknown are not people.

Presence (Alive/Parked/Stalled/Closed/Availability unknown) stays separate from ticket states. Native selects retain platform arrows. Use the chevron with rotation for custom disclosures. Replace control arrows only in the inventory's named UI contexts; keep meaningful prose/test/status-history arrows. Play only represents existing spawn/resume operations.

The user requested generated reference art for later manual vector adaptation. Accordingly, no purported final SVGs, cropped runtime avatars, application integration or built-app proof are included.

