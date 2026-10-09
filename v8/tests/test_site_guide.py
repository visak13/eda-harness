"""The site's product guide (s-bcc0c06de7, owner m-67c4136530: "dont include my personal epics or sensitive data in
these screenshots"). The screenshots are taken on a throwaway board seeded with a made-up project
(v8/web/guide/demo.seed.ts); this keeps the seed, the specs and the guide pages free of anything real, and every
image the pages use present."""

from __future__ import annotations

import getpass
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDE_SRC = ROOT / "v8" / "web" / "guide"
PAGES = ROOT / "docs" / "site" / "docs" / "guide"
ASSETS = ROOT / "docs" / "site" / "docs" / "assets" / "guide"

# Real handles, ids, paths and hosts of the machine this was built on, plus the shapes they take.
NEEDLES = [
    re.compile(re.escape(getpass.getuser()), re.I),  # this host's user name, never spelled out in the tree
    re.compile(r"tail[0-9a-f]{4,}", re.I),  # a tailnet name
    re.compile(r"\.ts\.net\b", re.I),
    re.compile(r"[A-Za-z]:[\\/]+Users[\\/]", re.I),
    re.compile(r"[A-Za-z]:[\\/]+Projects[\\/]", re.I),
    re.compile(r"/home/[a-z]", re.I),
    re.compile(r"\b(?:epic|s|t|m|design|note|report)-[0-9a-f]{10}\b"),  # a real board id (the demo's are minted per run)
    re.compile(r"[\w.+-]+@(?!example\.invalid\b)[\w-]+\.[\w.]+"),  # an email (git's placeholder author aside)
    re.compile(r"\beda-base\d?\b", re.I),
]


def _files() -> list[Path]:
    return sorted([*GUIDE_SRC.glob("*.ts"), *PAGES.glob("*.md")])


def _content(p: Path) -> str:
    """What reaches a board or a page: a spec's `//` comment lines (which cite this repo's own tickets) are left out."""
    lines = p.read_text(encoding="utf-8").splitlines()
    return "\n".join(ln for ln in lines if not (p.suffix == ".ts" and ln.lstrip().startswith("//")))


def test_the_demo_and_the_pages_carry_nothing_real():
    assert _files(), "guide sources missing"
    hits = [f"{p.relative_to(ROOT)}: {m.group(0)!r}" for p in _files()
            for rx in NEEDLES for m in rx.finditer(_content(p))]
    assert not hits, "\n".join(hits)


def test_every_image_a_page_uses_is_generated_and_every_generated_image_is_used():
    used = {m for p in PAGES.glob("*.md") for m in re.findall(r"assets/guide/([\w-]+\.png)", p.read_text(encoding="utf-8"))}
    made = {p.name for p in ASSETS.glob("*.png")}
    assert used and used <= made, f"pages use images the guide specs did not make: {sorted(used - made)}"
    assert made <= used, f"generated but unused: {sorted(made - used)}"
    specs = "".join(p.read_text(encoding="utf-8") for p in GUIDE_SRC.glob("*.spec.ts"))
    shot_names = set(re.findall(r'[sS]hot\(.*"([\w-]+)"\);', specs))
    assert {n.removesuffix(".png") for n in used} <= shot_names, "every page image comes from a guide spec"
