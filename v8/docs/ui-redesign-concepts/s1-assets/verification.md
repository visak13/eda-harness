# S1 verification record (asset scope)

## Commands actually run
- `.venv/Scripts/python.exe docs/ui-redesign-concepts/s1-assets/build_assets.py`: 45 icon/state vectors, 11 bot vectors, mapping/typed geometry/specimen generated.
- `.venv/Scripts/python.exe docs/ui-redesign-concepts/s1-assets/check_assets.py`: PASS exhaustive ten states + compatibility names + human-ID contract + XML safe geometry/currentColor/grid + deterministic source correspondence. PNG SHA256 a442519ba9666bbdebe1d89cc8e14a4e3c1dbb721ee1b41ad5b1440c59e43ed1.
- `node docs/ui-redesign-concepts/s1-assets/render-specimen.cjs`: PASS three light/dark/HC screenshots; 168 SVG instances per theme at exact 16/18/24; static specimen no horizontal overflow at 320px. Isolated headless browser, local file only, no server; browser closed in finally before next heavy job.
- `git diff -- src/edp8/avatars.py web/src/components/Icon.tsx`: empty during verification; runtime untouched by S1.

## Visual inspection
Read all three first renders. Functional glyphs distinct; initial More dots too weak and dark bot contours/antennas lost on dark backgrounds. Changed More to small circular strokes; added flat cream backing within each bot SVG, not CSS-dependent fallback, and regenerated/reran checks. Read all three revised PNGs. Dark motifs now remain visible, no texture/gradient. Tiny role details still need accompanying real role/model text; portraits are not a replacement identity system. Independent QA/owner review remains outstanding. Flat tiles are deliberate reference adaptation, not image-generated output.

## Owner publication
- Source image art-9a7798dabb on epic m-eef2a0045c (child m-a47e7b2a95); generated once in consult 20260918T092338Z-2fd0ecba. The manifest reports provider_model unavailable; actual image_gen call/output provenance is separately retained under reference-art, no model identity inferred from manifest.
- Revised light art-1d6cb37163, dark art-635873ab9f, HC art-1a4e7b5169 attached on epic m-a4d43f9a20. Requested reaction; no specific new-sheet approval claimed.
- Bounded BoardClient upload/attach used because this live tool schema lacks upload/attachment parity. Actual PNG bytes published, not a local path/repo Download presented as a visual demo.

## Limits / next checks
Not built-app evidence; no claim of actual theme contrast pairs, runtime typed-name guard, authenticated avatar integration, human preference regression, actual zoom/interaction or full responsive proof. S2 integrates; QA verifies at epic acceptance. See integration.md for exact obligations. No shared services changed, no dependencies added, no full e2e run.

Required second_opinion adherence consult is not yet run: architect temporarily held it for one owner-approved native Firefox repeat after local render completed. No concurrent browser/consult; resume on resource release. Criterion evidence/verdict handoff awaits that read.
