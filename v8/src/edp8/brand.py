"""The product brand, declared once (design-e963c656f5 §4.12, owner ruling m-56ede7a5e3).

User-facing names only (R8b): the CLI, the UI title, the README hero, the installers, the desktop
app and the VS Code extension read these. Internal module and package names (edp8, edp_pool, …)
stay. The values are declared once in S1's settings registry (group `brand`, edp_contracts.settings)
and re-exported here; the SPA's mirror is `web/src/brand.ts`,
held equal to these values by `tests/test_brand.py`. Assets: `v8/assets/brand/heronry/`.
"""

from __future__ import annotations

from edp8 import settings

PRODUCT_NAME: str = settings.get("EDP_PRODUCT_NAME")
CLI_NAME: str = settings.get("EDP_CLI_NAME")
DESKTOP_APP_NAME: str = settings.get("EDP_DESKTOP_APP_NAME")
TAGLINE: str = settings.get("EDP_TAGLINE")
ASSET_DIR = "assets/brand/heronry"  # relative to the v8 source root

BRAND = {
    "product_name": PRODUCT_NAME,
    "cli_name": CLI_NAME,
    "desktop_app_name": DESKTOP_APP_NAME,
    "tagline": TAGLINE,
}
