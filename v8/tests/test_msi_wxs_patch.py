"""S10 (s-b431082892): the release MSI's WiX is patched by desktop/scripts/patch_wxs.ps1: the per-user scope pin, the
MajorUpgrade the in-place update relies on and the CLI-on-PATH component. Run on a template shaped like Briefcase's
generated heronry.wxs; the real MSI is built and installed by v8/scripts/drill_update_in_place.ps1."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "desktop" / "scripts" / "patch_wxs.ps1"
TEMPLATE = ROOT / "tests" / "fixtures" / "briefcase_heronry.wxs"
PS = shutil.which("powershell") or shutil.which("pwsh")

pytestmark = pytest.mark.skipif(PS is None, reason="PowerShell is not installed")


def patch(wxs: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-Wxs", str(wxs), *flags],
                          capture_output=True, text=True, timeout=120)


@pytest.fixture
def wxs(tmp_path):
    f = tmp_path / "heronry.wxs"
    shutil.copyfile(TEMPLATE, f)
    return f


def test_the_patched_wxs_pins_per_user_scope_keeps_the_major_upgrade_and_adds_the_cli_path(wxs):
    r = patch(wxs)
    assert r.returncode == 0, r.stderr
    text = wxs.read_text(encoding="utf-8")
    assert 'Scope="perUserOrMachine"' in text and "<MajorUpgrade" in text
    assert re.search(r'<Launch Condition="Installed OR NOT \(ALLUSERS = 1\)"', text)  # no per-machine copy beside a per-user one
    assert 'Id="HeronryScopePin"' in text
    assert text.count('<Component Id="HeronryCliOnPath"') == 1 and 'ComponentRef Id="HeronryCliOnPath"' in text
    assert 'Part="last"' in text and 'System="no"' in text  # the user PATH, not the machine's


def test_patching_twice_changes_nothing_more(wxs):
    assert patch(wxs).returncode == 0
    once = wxs.read_bytes()
    assert patch(wxs).returncode == 0
    assert wxs.read_bytes() == once


def test_a_spike_build_leaves_the_shared_path_component_out(wxs):
    assert patch(wxs, "-NoCliPath").returncode == 0
    text = wxs.read_text(encoding="utf-8")
    assert "HeronryCliOnPath" not in text and 'Id="HeronryScopePin"' in text


@pytest.mark.parametrize("old,new,why", [("<MajorUpgrade", "<!-- MajorUpgrade", "MajorUpgrade"),
                                         ('Scope="perUserOrMachine"', 'Scope="perMachine"', "perUserOrMachine")])
def test_a_template_that_would_install_side_by_side_or_per_machine_stops_the_build(wxs, old, new, why):
    wxs.write_text(wxs.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")
    r = patch(wxs)
    assert r.returncode != 0 and why in (r.stderr + r.stdout)
