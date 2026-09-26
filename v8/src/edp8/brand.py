"""The product brand, declared once (design-e963c656f5 §4.12, owner ruling m-56ede7a5e3).

User-facing names only (R8b): the CLI, the UI title, the README hero, the installers, the desktop
app and the VS Code extension read these. Internal module and package names (edp8, edp_pool, …)
stay. S1's settings registry re-exports this module; the SPA's mirror is `web/src/brand.ts`,
held equal to these values by `tests/test_brand.py`. Assets: `v8/assets/brand/heronry/`.
"""

from __future__ import annotations

PRODUCT_NAME = "Heronry"
CLI_NAME = "heronry"
DESKTOP_APP_NAME = "Heronry Desktop"
TAGLINE = "your agent team, built on decisions, checked before delivery"
ASSET_DIR = "assets/brand/heronry"  # relative to the v8 source root

BRAND = {
    "product_name": PRODUCT_NAME,
    "cli_name": CLI_NAME,
    "desktop_app_name": DESKTOP_APP_NAME,
    "tagline": TAGLINE,
}
