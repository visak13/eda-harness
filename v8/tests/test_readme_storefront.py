"""S18 (design-e963c656f5 §4.17, criterion c-65f93e58a6): the root README is the storefront.

Every relative link and image in README.md resolves to a file in the repo, and every public URL (Releases,
the video, the install one-liners, the site, badges) derives from the one repo slug in `edp8.brand`. The
README carries no user-profile path, e-mail address or board id.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from edp8 import brand

V8 = Path(__file__).resolve().parents[1]
REPO = V8.parent
README = (REPO / "README.md").read_text(encoding="utf-8")

MD_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HTML_REF = re.compile(r"""\b(?:href|src|srcset)\s*=\s*["']([^"']+)["']""")
ABS_URL = re.compile(r"https?://[^\s)\"'<>`]+")


def _targets() -> list[str]:
    return MD_LINK.findall(README) + HTML_REF.findall(README)


def _relative() -> list[str]:
    return [t for t in _targets() if not re.match(r"^[a-z][a-z0-9+.-]*:", t) and not t.startswith("#")]


def test_every_relative_link_target_exists() -> None:
    rel = _relative()
    assert len(rel) >= 15, rel  # the hero, 3 stills, 4 why-graphics, docs, changelog, contributing, licence
    missing = [t for t in rel if not (REPO / unquote(t.split("#")[0])).exists()]
    assert not missing, f"README links to files that do not exist: {missing}"


def test_repo_docs_the_readme_links_exist() -> None:
    for name in ("LICENSE", "NOTICE", "CHANGELOG.md", "CONTRIBUTING.md"):
        assert name in _relative(), f"README does not link {name}"
    assert "README.md#install" in (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "## Install" in README


def test_urls_derive_from_the_one_repo_slug() -> None:
    assert brand.REPO_SLUG.count("/") == 1
    owner, repo = brand.REPO_SLUG.split("/")
    assert brand.REPO_URL == f"https://github.com/{brand.REPO_SLUG}"
    assert brand.RELEASES_URL == f"{brand.REPO_URL}/releases/latest"
    assert brand.VIDEO_URL == f"{brand.RELEASES_URL}/download/heronry-demo.mp4"
    assert brand.SITE_URL == f"https://{owner.lower()}.github.io/{repo}/"
    # the storefront's named links are exactly the derived ones
    assert f'<a href="{brand.RELEASES_URL}"><strong>Download</strong></a>' in README
    assert f'<a href="{brand.SITE_URL}"><strong>Website</strong></a>' in README
    assert f'<a href="{brand.VIDEO_URL}"' in README.split("</picture>")[0], "the hero must link the video"
    assert f"irm {brand.DOWNLOAD_URL}/install.ps1 | iex" in README
    assert f"curl -LsSf {brand.DOWNLOAD_URL}/install.sh | sh" in README
    assert f"-R {brand.REPO_SLUG}" in README  # gh attestation verify


def test_no_url_names_the_repo_outside_the_constant() -> None:
    owner = brand.REPO_SLUG.split("/")[0].lower()
    shields = f"https://img.shields.io/github/"
    allowed = (brand.REPO_URL + "/", brand.REPO_URL, brand.SITE_URL)
    stray = []
    for url in ABS_URL.findall(README):
        if owner not in url.lower():
            continue
        if url.startswith(shields):
            ok = f"/{brand.REPO_SLUG}" in url
        else:
            ok = url == brand.REPO_URL or url.startswith(allowed)
        if not ok:
            stray.append(url)
    assert not stray, f"URLs not derived from brand.REPO_SLUG/SITE_URL: {stray}"
    # and nothing mentions the owner outside those URLs (no hardcoded paths or handles)
    rest = ABS_URL.sub("", README).replace(f"-R {brand.REPO_SLUG}", "")
    assert owner not in rest.lower()


def test_hero_badges_and_stills() -> None:
    top = README[:2500]
    assert "docs/readme/storefront/hero.webp" in top and "docs/readme/storefront/hero.gif" in top
    for badge in ("Latest release", "CI", "Licence"):
        assert f'alt="{badge}' in top, badge
    assert brand.TAGLINE in top
    for still in ("still-1-pool.png", "still-2-context.png", "still-3-board.png"):
        assert f"docs/readme/storefront/{still}" in README
    # no host captures: the storefront shows only generated frames
    for capture in ("docs/readme/needs-you.png", "docs/readme/seats.png", "docs/readme/epic-expanded.png"):
        assert capture not in README


def _section(title: str) -> str:
    m = re.search(rf"^### {re.escape(title)}[^\n]*\n(.*?)(?=^### |^## )", README, re.S | re.M)
    assert m, f"no install section {title!r}"
    return m.group(1)


def test_install_per_os_gui_and_cmd_at_most_five_steps() -> None:
    for os_name in ("Windows", "macOS", "Linux"):
        body = _section(os_name)
        blocks = re.split(r"^\*\*(GUI|cmd)\*\*[^\n]*\n", body, flags=re.M)
        kinds = dict(zip(blocks[1::2], blocks[2::2]))
        assert set(kinds) == {"GUI", "cmd"}, (os_name, list(kinds))
        for kind, text in kinds.items():
            steps = re.findall(r"^(\d+)\. ", text, re.M)
            assert 1 <= len(steps) <= 5, (os_name, kind, steps)
    assert "More info → Run anyway" in _section("Windows")
    mac = _section("macOS")
    assert "Privacy & Security" in mac and "Open Anyway" in mac
    assert "apt install ./" in _section("Linux")
    assert "sha256sum -c SHA256SUMS" in README and "gh attestation verify" in README


def test_first_run_and_harness_choice() -> None:
    assert "## First run" in README
    harness = README.split("## Choose your harnesses", 1)[1].split("\n## ", 1)[0]
    for needle in ("Claude Code", "Codex", "at least one", "v8/guides/pi-seat.md", "Fable", "claude-fable-5-1"):
        assert needle in harness, needle


def test_no_personal_data() -> None:
    patterns = {
        "windows user profile": r"[A-Za-z]:[\\/]+Users[\\/]",
        "posix home": r"(?<![\w.])/(?:home|Users)/[A-Za-z]",
        "git-bash profile": r"/c/Users/",
        "e-mail address": r"[\w.+-]+@[\w-]+\.[\w.-]+",
        "board id": r"\b(?:t|s|m|c|p|art|note|epic|design|report)-[0-9a-f]{10}\b",
    }
    hits = {name: re.findall(rx, README) for name, rx in patterns.items()}
    assert not any(hits.values()), hits
