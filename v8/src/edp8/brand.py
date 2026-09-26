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

# Where the product is published (S18, design §4.17). The slug is the registry default of `update.repo`:
# EDP_UPDATE_REPO moves only the update source (a fork's own build), never these public links. Every URL in
# the root README derives from these; tests/test_readme_storefront.py holds it there.
REPO_SLUG: str = settings.setting("EDP_UPDATE_REPO").default_value()
_OWNER, _REPO = REPO_SLUG.split("/")
REPO_URL = f"https://github.com/{REPO_SLUG}"
RELEASES_URL = f"{REPO_URL}/releases/latest"
DOWNLOAD_URL = f"{RELEASES_URL}/download"  # + an asset name: install.ps1, install.sh, heronry-demo.mp4
VIDEO_URL = f"{DOWNLOAD_URL}/heronry-demo.mp4"
SITE_URL = f"https://{_OWNER.lower()}.github.io/{_REPO}/"  # GitHub Pages project site (S15)

BRAND = {
    "product_name": PRODUCT_NAME,
    "cli_name": CLI_NAME,
    "desktop_app_name": DESKTOP_APP_NAME,
    "tagline": TAGLINE,
}
