"""RC2 item 4 (t-e338298d88): 0.9.x's updater refuses the desktop `.msi`, so the step to 0.10 is by hand, once. The
release notes (the CHANGELOG section the release workflow publishes), the README and the Pages download and updates
pages all give the same supported steps, and no page still says the Windows desktop app only opens a release page."""

from __future__ import annotations

import re
from pathlib import Path

import edp8
from edp8 import cli

ROOT = Path(__file__).resolve().parents[2]
STEPS = ("heronry stop all --force", ".msi", "heronry start")


def _release_notes(version: str) -> str:
    """What release.yml publishes: the CHANGELOG lines after `## [<version>]` up to the next `## [`."""
    out, on = [], False
    for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"## [{version}]"):
            on = True
            continue
        if on and line.startswith("## ["):
            break
        if on:
            out.append(line)
    return "\n".join(out)


def test_the_release_notes_give_the_one_supported_0_9_upgrade():
    notes = _release_notes(edp8.__version__)
    assert "### Upgrading" in notes  # 0.10.1 (architect m-4812de0b3c): every supported hop, one section
    section = notes.split("### Upgrading", 1)[1].split("\n### ", 1)[0]
    # the last public release is 0.9.x, so every release's notes keep its by-hand desktop step (CI run 37995840203)
    from_09 = section.split("- **From 0.9.x, desktop app", 1)[1].split("\n- **", 1)[0]
    for step in STEPS:
        assert step in from_09, step
    assert f'msiexec /i "Heronry Desktop-{edp8.__version__}.msi"' in from_09
    assert "command line (`install.ps1` / `install.sh`):** `heronry update`" in section
    assert "/mcp" in section  # RC2 item 6: the one action an open Claude Code session may need
    # the RC2 gate (architect m-0b95d8413e): kept codex seats lock the install folder, so the 0.9.x step stops
    # them; the "files in use" dialog's default is named as safe
    assert "--keep-seats" not in section and "Automatically close applications" in section


def test_the_pages_and_readme_give_the_same_steps():
    page = (ROOT / "docs/site/docs/download.md").read_text(encoding="utf-8")
    assert "## Upgrading from 0.9.x" in page
    section = page.split("## Upgrading from 0.9.x", 1)[1].split("\n## ", 1)[0]
    for step in ("{{ brand.cli_name }} stop all --force", 'msiexec /i "Heronry Desktop-<version>.msi"',
                 "{{ brand.cli_name }} start"):
        assert step in section, step
    updates = (ROOT / "docs/site/docs/docs/updates.md").read_text(encoding="utf-8")
    assert "../download.md#upgrading-from-09x" in updates
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "From 0.9.x, the desktop app upgrades once by hand" in readme and all(s in readme for s in STEPS)


def test_no_page_says_the_windows_desktop_app_only_opens_the_release_page():
    stale = re.compile(r"release page for the new `\.msi`|download the new `\.msi`")
    for rel in ("README.md", "docs/site/docs/docs/updates.md", "docs/site/docs/download.md"):
        assert not stale.search((ROOT / rel).read_text(encoding="utf-8")), rel


def test_the_documented_stop_flag_exists():
    assert '("--force", "stop the pool even with live seats")' in Path(cli.__file__).read_text(encoding="utf-8")
