# Fidelity — how the Folio SPA is held to Astra's renders

Two independent checks guard visual fidelity. Both run inside the Playwright e2e suite
(`npm --prefix web run e2e`, win32, workers=1, 1440×900). This file is the **threshold of record**
cited by criterion `c-80b50710a6`.

## 1. Geometry (DOM measurement) — `e2e/fidelity.spec.ts`, `e2e/g3a-fidelity.spec.ts`

The shell and page geometry are measured live with `boundingBox()` and `getComputedStyle`, then
asserted against the design tokens in **`src/theme/geometry.ts`** (the single source of truth —
the same module the CSS-in-JS / module.css values derive from, so a token and its test never drift).
A failure reports **measured vs expected** via the `expectPx(actual, token, label)` helper, e.g.

```
sidebar width — expected 216 (token layout.sidebar), measured 200 (Δ16 > 1px)
```

The deliberately-changed-token check for `c-7c51c6b69b`: flip one token (e.g. `layout.sidebar`
216→200) and the geometry project fails with that measured-vs-expected line — proving the check
is load-bearing, not a rubber stamp.

Tolerance: **±1px** on every geometry token (sub-pixel rounding only).

## 2. Band pixelmatch (image diff) — `e2e/fidelity.spec.ts`

The rail and header **bands** — the two regions whose exact color/spacing Astra fixed — are
screenshotted and compared with [`pixelmatch`](https://github.com/mapbox/pixelmatch) against the
committed reference plates in `e2e/design-reference/` (`folio-home.png`, `folio-epic.png`,
`folio-ruling.png`, cropped to the band).

| knob | value | why |
|---|---|---|
| per-pixel `threshold` | **0.1** | pixelmatch's YIQ tolerance — ignores antialiasing/subpixel noise |
| band differing-pixel ratio | **≤ 5%** | the assertion: `diffPixels / bandPixels ≤ 0.05` |
| content area | **logged only, never asserted** | seeded copy/data differ from the render; only the chrome bands gate |

Rationale for a band (not full-page) diff: the reference plates carry Astra's mock copy and seeded
rows, which will never pixel-match a live board. Only the **rail + header chrome** is a fixed target;
the content area diff is written to the test output for a human to eyeball, but it does not fail the run.

## Updating a reference plate

A reference plate changes only when the design changes (a new Astra render the owner accepted at a
/demo). Replace the PNG under `e2e/design-reference/`, re-run the band check, and record the new
render's provenance (message id) in the commit. The visual **snapshot** baselines
(`e2e/__screenshots__/`, `e2e/visual.spec.ts`, `toHaveScreenshot`) are a separate, stricter check
(win32-only, `maxDiffPixelRatio 0.01`) regenerated with `--update-snapshots`.
