# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10"]
# ///
"""Derive the Heronry icon set from the 1024 app icon (design-e963c656f5 §4.12, S7).

Run from anywhere:  uv run v8/assets/brand/heronry/make_icons.py
Writes next to this file, into icons/:
  heronry-{16,32,48,64,128,256,512}.png   plain PNG sizes (installers, docs site, extension)
  heronry.ico                             Windows icon, 16..256 in one file (MSI, desktop)
  heronry.icns                            macOS icon (DMG / .app bundle)
  favicon.ico                             16/32/48 for browsers
  favicon-32.png, apple-touch-icon.png    web <link> icons (180 px touch icon)
and copies the SPA's copies into v8/web/public/brand/ (favicons + the 64 px rail logo), so the
built board serves them at /ui/brand/.
The output is deterministic for a given source, so a re-run leaves git clean.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "heronry-logo.png"
OUT = HERE / "icons"
WEB_PUBLIC = HERE.parents[2] / "web" / "public" / "brand"
WEB_FILES = ("favicon.ico", "favicon-32.png", "apple-touch-icon.png", "heronry-64.png")

PNG_SIZES = (16, 32, 48, 64, 128, 256, 512)
ICO_SIZES = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
FAVICON_SIZES = [(s, s) for s in (16, 32, 48)]


def resized(src: Image.Image, size: int) -> Image.Image:
    # LANCZOS on the RGBA master; a fresh image drops PNG metadata (no timestamps → stable bytes).
    return src.resize((size, size), Image.Resampling.LANCZOS)


def main() -> int:
    src = Image.open(SOURCE).convert("RGBA")
    if src.size != (1024, 1024):
        raise SystemExit(f"{SOURCE.name} must be 1024x1024, is {src.size}")
    OUT.mkdir(exist_ok=True)
    for s in PNG_SIZES:
        resized(src, s).save(OUT / f"heronry-{s}.png", optimize=True)
    resized(src, 32).save(OUT / "favicon-32.png", optimize=True)
    resized(src, 180).save(OUT / "apple-touch-icon.png", optimize=True)
    src.save(OUT / "heronry.ico", sizes=ICO_SIZES)
    src.save(OUT / "favicon.ico", sizes=FAVICON_SIZES)
    src.save(OUT / "heronry.icns")  # Pillow writes the 16..1024 icns members from the master
    WEB_PUBLIC.mkdir(parents=True, exist_ok=True)
    for name in WEB_FILES:
        shutil.copyfile(OUT / name, WEB_PUBLIC / name)
    for p in sorted(OUT.iterdir()):
        print(f"{p.name:24} {p.stat().st_size:>8} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
