"""The project site's reference is generated at build (S15 s-6d5fdf783a, design-e963c656f5 §4.15): a setting added
to the registry and a flag added to the CLI command table appear in the built reference with no hand edit.

The generator tests run everywhere. The full-build test needs the site's build tools (docs/site/requirements.txt);
the site workflow runs it with them, and it is skipped when mkdocs is not installed."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from edp8 import cli
from edp_contracts.settings import _core

REPO = Path(__file__).resolve().parents[2]
SITE = REPO / "docs" / "site"
DUMMY_ENV = "HERONRY_SITE_DUMMY_KNOB"
DUMMY_FLAG = "--site-dummy-flag"


@pytest.fixture
def sitegen():
    sys.path.insert(0, str(SITE / "hooks"))
    try:
        yield importlib.import_module("sitegen")
    finally:
        sys.path.remove(str(SITE / "hooks"))


@pytest.fixture
def dummies(monkeypatch):
    """One extra setting in the registry and one extra flag on `status`, removed afterwards."""
    s = _core.declare("site.dummy_knob", DUMMY_ENV, "int", 7, "Limits/tuning",
                      "A dummy knob the site test declares.", tier="advanced", label="Dummy knob",
                      help="Only the site test uses it.")
    rows = tuple(c._replace(flags=c.flags + ((DUMMY_FLAG, "a dummy flag the site test adds"),))
                 if c.name == "status" else c for c in cli.COMMANDS)
    monkeypatch.setattr(cli, "COMMANDS", rows)
    try:
        yield s
    finally:
        _core.REGISTRY.pop(DUMMY_ENV, None)
        _core._BY_KEY.pop("site.dummy_knob", None)


def test_generators_pick_up_new_declarations(sitegen, dummies):
    assert DUMMY_ENV in sitegen.settings_md() and "site.dummy_knob" in sitegen.settings_md()
    assert DUMMY_FLAG in sitegen.cli_md()


def test_every_command_and_setting_is_in_the_reference(sitegen):
    cli_page, settings_page = sitegen.cli_md(), sitegen.settings_md()
    for c in cli.COMMANDS:
        assert f"heronry {c.usage}" in cli_page
        for flag, _ in c.flags:
            assert flag in cli_page
    for s in _core.all_settings():
        # the brand values are not user settings: no brand table (owner m-da9a2ae62f)
        omitted = s.group in sitegen.SETTINGS_OMIT_GROUPS
        assert (f"`{s.env}`" in settings_page) is not omitted
    assert "## brand" not in settings_page and "(#brand)" not in settings_page


def test_downloads_come_from_the_release_and_the_one_slug(sitegen):
    from edp8 import brand
    rel = sitegen.load_release(str(SITE / "fixtures" / "release-latest.json"))
    d = sitegen.downloads(rel)
    assert [i["key"] for i in d["installers"]] == ["windows", "macos", "linux"]  # no AppImage (design §4.9)
    assert [i["file"].rsplit(".", 1)[1] for i in d["installers"]] == ["msi", "dmg", "deb"]
    assert all(i["url"].startswith(brand.REPO_URL + "/releases/download/v0.9.0/") for i in d["installers"])
    assert d["ps1"].endswith("/install.ps1") and d["sh"].endswith("/install.sh") and d["sums"]
    # one primary button per OS carrying the file type and size; the rest are quiet links (owner m-da9a2ae62f)
    page = sitegen.downloads_md(rel)
    assert page.count("md-button--primary") == 3 and page.count('class="hy-dl-card"') == 3
    assert "MSI installer · 58.4 MB" in page and "SHA256SUMS</a>" in page and "/attestations" in page
    # no release yet (or GitHub unreachable): every button still resolves, to the releases page
    none = sitegen.downloads(None)
    assert all(i["url"] == brand.RELEASES_URL for i in none["installers"])
    assert none["ps1"] == f"{brand.RELEASES_URL}/download/install.ps1"


def test_pii_scan_flags_a_user_path_and_an_email(tmp_path):
    sys.path.insert(0, str(SITE / "hooks"))
    try:
        pii_scan = importlib.import_module("pii_scan")
    finally:
        sys.path.remove(str(SITE / "hooks"))
    (tmp_path / "ok.html").write_text("<p>C:\\Users\\&lt;you&gt; and someone@example.com</p>", encoding="utf-8")
    assert pii_scan.scan(tmp_path) == []
    (tmp_path / "bad.html").write_text("<p>C:\\Users\\jdoe\\x and jdoe@corp.io</p>", encoding="utf-8")
    labels = sorted(h.split(": ")[1] for h in pii_scan.scan(tmp_path))
    assert labels == ["email", "windows user path"]


def test_the_built_site_carries_the_new_declarations(sitegen, dummies, tmp_path, monkeypatch):
    pytest.importorskip("mkdocs")
    pytest.importorskip("material")
    from mkdocs.commands.build import build
    from mkdocs.config import load_config
    monkeypatch.setenv("HERONRY_SITE_RELEASE_JSON", str(SITE / "fixtures" / "release-latest.json"))
    out = tmp_path / "site"
    build(load_config(str(SITE / "mkdocs.yml"), site_dir=str(out), strict=True))
    settings_html = (out / "reference" / "settings" / "index.html").read_text(encoding="utf-8")
    cli_html = (out / "reference" / "cli" / "index.html").read_text(encoding="utf-8")
    assert DUMMY_ENV in settings_html and "A dummy knob the site test declares." in settings_html
    assert DUMMY_FLAG in cli_html
    download = (out / "download" / "index.html").read_text(encoding="utf-8")
    assert "Heronry.Desktop-0.9.0.msi" in download and ".deb" in download and "AppImage" not in download.split(
        "There is no AppImage")[0]
