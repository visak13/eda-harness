"""S7 (design-e963c656f5 §4.12, criterion c-71e31b277a): the brand is one constant, applied.

`edp8/brand.py` is the single source (S1's settings registry re-exports it). Every user-facing
surface is checked against it here: the CLI, the SPA mirror and page, the VS Code extension and the
README. A leftover "EDP" *product* name fails; env keys (EDP8_*), ids (edp-code, edp.*) and internal
module names are not product names and stay (R8b).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from edp8 import brand, cli

V8 = Path(__file__).resolve().parents[1]
REPO = V8.parent
# "EDP" as a word, not an env key (EDP8_, EDP_), a hyphenated id or an internal name like edp8.
PRODUCT_EDP = re.compile(r"\bEDP\b(?![_0-9-])")


def test_brand_values_are_the_ruling() -> None:
    assert brand.PRODUCT_NAME == "Heronry"
    assert brand.CLI_NAME == "heronry"
    assert brand.DESKTOP_APP_NAME == "Heronry Desktop"
    assert brand.TAGLINE == "your agent team, built on decisions, checked before delivery"


def test_spa_mirror_equals_the_constant() -> None:
    ts = (V8 / "web/src/brand.ts").read_text(encoding="utf-8")
    for name in ("PRODUCT_NAME", "CLI_NAME", "DESKTOP_APP_NAME", "TAGLINE"):
        m = re.search(rf'export const {name} = "([^"]*)";', ts)
        assert m, f"web/src/brand.ts lacks {name}"
        assert m.group(1) == getattr(brand, name), f"brand.ts {name} drifted from edp8/brand.py"


def test_cli_version_and_help_name_the_brand(capsys) -> None:
    for flag in ("--version", "version", "-V"):
        assert cli.main([flag]) == 0
        out = capsys.readouterr().out.strip()
        assert out.startswith(f"{brand.PRODUCT_NAME} "), out
    assert cli.main(["--help"]) == 0
    text = capsys.readouterr().out
    assert brand.PRODUCT_NAME in text and f"usage: {brand.CLI_NAME} " in text and brand.TAGLINE in text
    assert not PRODUCT_EDP.search(text), text


def test_cli_console_script_is_the_brand_name() -> None:
    scripts = tomllib.loads((V8 / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    assert scripts[brand.CLI_NAME] == "edp8.cli:main"


def test_cli_module_run_prints_brand() -> None:
    out = subprocess.run([sys.executable, "-m", "edp8.cli", "--version"], capture_output=True,
                         text=True, check=True).stdout
    assert out.startswith(brand.PRODUCT_NAME)


def test_spa_page_title_favicon_and_rail() -> None:
    html = (V8 / "web/index.html").read_text(encoding="utf-8")
    assert f"<title>{brand.PRODUCT_NAME}</title>" in html
    assert 'href="/brand/favicon.ico"' in html
    for icon in ("favicon.ico", "favicon-32.png", "apple-touch-icon.png", "heronry-64.png"):
        assert (V8 / "web/public/brand" / icon).is_file(), icon
    shell = (V8 / "web/src/components/AppShell.tsx").read_text(encoding="utf-8")
    assert "{PRODUCT_NAME}" in shell and "LOGO_URL" in shell
    assert not PRODUCT_EDP.search(re.sub(r"<!--.*?-->", "", html, flags=re.S))


def test_vscode_extension_display_name_and_icon() -> None:
    ext = V8 / "vscode-ext/edp-code"
    pkg = json.loads((ext / "package.json").read_text(encoding="utf-8"))
    assert pkg["displayName"] == brand.PRODUCT_NAME
    assert (ext / pkg["icon"]).is_file()
    assert pkg["name"] == "edp-code"  # the internal id stays (R8b)
    leftovers = [m.group(0) for m in PRODUCT_EDP.finditer(json.dumps(pkg))]
    assert leftovers == [], leftovers


def test_readme_hero_uses_the_brand() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert readme.splitlines()[0] == f"# {brand.PRODUCT_NAME}"
    assert brand.TAGLINE in readme[:600]
    assert "heronry-logo.png" in readme[:600] or "heronry-splash.png" in readme[:600]
    assert not PRODUCT_EDP.search(readme), PRODUCT_EDP.findall(readme)
    assert "EDA Harness" not in readme
