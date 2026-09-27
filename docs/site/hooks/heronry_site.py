"""The Heronry site's mkdocs hook (design-e963c656f5 §4.15).

- on_config: names, URLs and the version come from the product (`edp8.brand`, the installed edp8), never from
  this file; the latest release is read once (fixture or GitHub Releases API).
- on_files: the generated pages (reference, changelog) and the assets copied from their tracked homes (brand
  art from S7, stills from the README storefront, S17's player build when present) are added as generated
  files, so nothing generated is committed and nothing can drift.
- on_page_markdown: fills the `<!-- heronry:... -->` markers and `{{ brand.<key> }}` values.
- on_post_build: the PII scan over the built site; a finding fails the build.
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any

from mkdocs.exceptions import PluginError
from mkdocs.structure.files import File, Files

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pii_scan  # noqa: E402
import sitegen  # noqa: E402

ROOT = HERE.parents[2]          # the repository root (docs/site/hooks -> repo)
V8 = ROOT / "v8"
log = logging.getLogger("mkdocs.hooks.heronry_site")

_state: dict[str, Any] = {}

#: generated reference pages: site path -> generator
REFERENCE = {
    "reference/cli.md": sitegen.cli_md,
    "reference/settings.md": sitegen.settings_md,
    "reference/rest-api.md": lambda: sitegen.rest_md(_openapi()),
    "reference/mcp-tools.md": sitegen.mcp_md,
    "reference/workflow-schema.md": sitegen.workflow_md,
    "reference/models.md": sitegen.models_md,
}


def _openapi() -> dict[str, Any]:
    if "openapi" not in _state:
        _state["openapi"] = sitegen.openapi()
    return _state["openapi"]


def on_config(config: Any) -> Any:
    b = sitegen.brand()
    _state["brand"] = b
    _state["release"] = sitegen.load_release()
    config["site_name"] = b["product_name"]
    config["site_description"] = b["tagline"]
    config["site_url"] = b["site_url"]
    config["repo_url"] = b["repo_url"]
    config["repo_name"] = b["repo_slug"]
    config["copyright"] = f"{b['product_name']} contributors · Apache-2.0"
    config["extra"]["brand"] = b
    config["extra"]["heronry_version"] = sitegen.version()
    rel = _state["release"]
    log.info("heronry site: release %s", rel.get("tag_name") if rel else "none (links go to the releases page)")
    return config


def _asset(config: Any, uri: str, src: Path) -> File:
    return File.generated(config, uri, abs_src_path=str(src))


def _assets(config: Any) -> list[File]:
    out: list[File] = []
    brand_dir = V8 / sitegen.brand()["asset_dir"]
    for name, src in (("heronry-logo.png", brand_dir / "heronry-logo.png"),
                      ("heronry-splash.png", brand_dir / "heronry-splash.png"),
                      ("favicon-32.png", brand_dir / "icons" / "favicon-32.png"),
                      ("favicon.ico", brand_dir / "icons" / "favicon.ico"),
                      ("apple-touch-icon.png", brand_dir / "icons" / "apple-touch-icon.png")):
        if not src.is_file():
            raise PluginError(f"brand asset missing: {src.relative_to(ROOT).as_posix()}")
        out.append(_asset(config, f"assets/brand/{name}", src))
    for src in sorted((ROOT / "docs" / "readme" / "storefront").glob("*")):
        if src.suffix.lower() in {".png", ".webp", ".gif", ".jpg"}:
            out.append(_asset(config, f"assets/storefront/{src.name}", src))
    player = V8 / "docs" / "video" / "player" / "dist"
    _state["player"] = (player / "index.html").is_file()
    if _state["player"]:
        for src in sorted(p for p in player.rglob("*") if p.is_file()):
            out.append(_asset(config, f"watch/player/{src.relative_to(player).as_posix()}", src))
    return out


def _changelog() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.sub(r"\]\((?!https?://|#)([^)]+)\)", lambda m: f"]({sitegen.brand()['repo_url']}/blob/main/{m.group(1)})",
                  text)


def on_files(files: Files, config: Any) -> Files:
    for uri, gen in REFERENCE.items():  # wide tables: the page drops the left nav (the tabs and the index remain)
        files.append(File.generated(config, uri, content="---\nhide:\n  - navigation\n---\n\n" + gen()))
    files.append(File.generated(config, "reference/openapi.json",
                                content=__import__("json").dumps(_openapi(), indent=2) + "\n"))
    files.append(File.generated(config, "reference/workflow.schema.json", content=sitegen.workflow_schema_json()))
    files.append(File.generated(config, "changelog.md", content=_changelog()))
    for f in _assets(config):
        files.append(f)
    return files


def _watch_block() -> str:
    b = _state["brand"]
    if _state.get("player"):
        return ('<div class="hy-player"><iframe src="player/" title="The Heronry product video, playing live" '
                'loading="lazy" allow="autoplay; fullscreen"></iframe></div>')
    return (f'<p><a class="md-button md-button--primary" href="{b["video_url"]}">Watch the video (MP4)</a></p>')


_BRAND_RX = re.compile(r"\{\{\s*brand\.(\w+)\s*\}\}")


def on_page_markdown(markdown: str, page: Any, config: Any, files: Files) -> str:
    b = _state["brand"]
    markdown = markdown.replace("<!-- heronry:downloads -->", sitegen.downloads_md(_state["release"]))
    markdown = markdown.replace("<!-- heronry:watch -->", _watch_block())
    markdown = markdown.replace("{{ heronry.version }}", sitegen.version())

    def brand_value(m: re.Match[str]) -> str:
        if m.group(1) not in b:
            raise PluginError(f"{page.file.src_uri}: unknown brand value {m.group(0)}")
        return b[m.group(1)]
    return _BRAND_RX.sub(brand_value, markdown)


def on_post_build(config: Any) -> None:
    site = Path(config["site_dir"])
    hits = pii_scan.scan(site)
    if hits:
        for h in hits[:50]:
            log.error("pii: %s", h)
        raise PluginError(f"PII scan: {len(hits)} finding(s) in the built site")
    log.info("heronry site: PII scan clean (%s)", site.name)
