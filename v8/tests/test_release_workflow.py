"""S9 release.yml (adversary R2-E): the draft release carries install.ps1 and install.sh pinned to its own tag,
and the asset guard fails when either is missing. The two workflow steps run as written, under bash."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WF = REPO / ".github" / "workflows" / "release.yml"
BASH = shutil.which("bash") or next((p for p in (r"C:\Program Files\Git\bin\bash.exe",) if Path(p).exists()), None)
pytestmark = [
    pytest.mark.skipif(not WF.exists(), reason="the workflow lives at the repo root, not in an installed wheel"),
    pytest.mark.skipif(BASH is None, reason="needs bash"),
]


def _step(name: str) -> str:
    steps = yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]["assets"]["steps"]
    return next(s["run"] for s in steps if s.get("name") == name)


def _bash(script: str, cwd: Path, tag: str = "v0.9.0") -> subprocess.CompletedProcess:
    return subprocess.run([BASH, "-e", "-c", script], cwd=cwd, env={"TAG": tag, "PATH": os.environ.get("PATH", "")}, capture_output=True,
                          text=True)


def _full_set(assets: Path) -> None:
    for name in ("edp8-0.9.0-py3-none-any.whl", "edp_pool-0.9.0-py3-none-any.whl", "edp_broker-0.9.0-py3-none-any.whl",
                 "edp_contracts-0.9.0-py3-none-any.whl", "edp8-0.9.0.tar.gz", "edp_pool-0.9.0.tar.gz",
                 "edp_broker-0.9.0.tar.gz", "edp_contracts-0.9.0.tar.gz", "edp-code-0.9.0.vsix",
                 "Heronry Desktop-0.9.0.msi", "Heronry Desktop-0.9.0.dmg", "heronry_0.9.0-1~ubuntu-noble_amd64.deb"):
        (assets / name).write_bytes(b"x")


def test_install_scripts_are_attached_and_pinned_to_the_tag(tmp_path):
    for f in ("install.ps1", "install.sh"):
        shutil.copyfile(REPO / f, tmp_path / f)
    (tmp_path / "assets").mkdir()
    r = _bash(_step("The install scripts, pinned to this tag"), tmp_path, tag="v9.8.7")
    assert r.returncode == 0, r.stdout + r.stderr
    ps1 = (tmp_path / "assets" / "install.ps1").read_text(encoding="utf-8")
    sh = (tmp_path / "assets" / "install.sh").read_text(encoding="utf-8")
    assert '  [string]$Version = "v9.8.7",' in ps1 and '$Version = "",' not in ps1
    assert 'VERSION="v9.8.7"; RELEASE_URL=""' in sh and 'VERSION=""' not in sh
    # nothing else changed: the pin is one line in each
    for f, text in (("install.ps1", ps1), ("install.sh", sh)):
        orig = (REPO / f).read_text(encoding="utf-8").splitlines()
        assert sum(a != b for a, b in zip(orig, text.splitlines())) == 1 and len(orig) == len(text.splitlines())


def test_the_asset_guard_requires_both_install_scripts(tmp_path):
    guard = _step("Require the full asset set")
    _full_set(tmp_path)
    assert _bash(guard, tmp_path).returncode == 1  # the R2-E shape: everything but the scripts
    (tmp_path / "install.ps1").write_text("x")
    assert _bash(guard, tmp_path).returncode == 1
    (tmp_path / "install.sh").write_text("x")
    r = _bash(guard, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
