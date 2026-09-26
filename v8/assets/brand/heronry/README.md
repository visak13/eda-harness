# Heronry brand assets

The chosen brand (design-e963c656f5 §4.12, owner ruling m-56ede7a5e3). A heronry is a tree where
many herons nest together: one home for many specialists.

- Product: **Heronry** · CLI: `heronry` · desktop app: **Heronry Desktop**
- Tagline: *your agent team, built on decisions, checked before delivery*
- Single source of these names: `edp8.brand` (S1's settings registry re-exports it) (the web mirror is `v8/web/src/brand.ts`, kept equal by a test).

| File | What it is |
|---|---|
| `heronry-logo.png` | 1024×1024 RGBA app icon, the master for every derived size |
| `heronry-splash.png` | 1600×900 splash (desktop app, installers, site hero) |
| `heronry-theme.png` | 1600×900 theme card: dark and light UI samples |
| `brand-tokens.css` | the dark/light tokens as CSS custom properties |
| `palettes.json` | the same tokens as data; the web theme test checks the shipped theme equals it |
| `contrast-report.json` | WCAG 2.2 ratios computed when the art was made |
| `source-art/*.webp` | lossless image_gen sources (codex run 20260926T150125Z-f279786e) |
| `make_icons.py` | derives `icons/` from the 1024 icon: `uv run v8/assets/brand/heronry/make_icons.py` |
| `icons/` | png 16–512, `heronry.ico`, `heronry.icns`, `favicon.ico`, `favicon-32.png`, `apple-touch-icon.png` |

For S8 (installers, desktop): use `icons/heronry.ico` (Windows), `icons/heronry.icns` (macOS),
`icons/heronry-512.png` (Linux AppImage/deb), and `heronry-splash.png` for the startup splash; the
app and installer names come from `edp8.brand` (`DESKTOP_APP_NAME`, `PRODUCT_NAME`).

The Paperwasp and Tallybone candidates are not shipped.
