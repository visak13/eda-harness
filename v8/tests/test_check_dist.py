"""S9 release manifest guard (.github/scripts/check_dist.py, adversary F10): excluded prefixes and size ceilings.
Set HERONRY_DIST_DIR to a folder of real `uv build` outputs to check those too (the release workflow does)."""
from __future__ import annotations

import importlib.util
import io
import os
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "check_dist.py"
pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="the guard lives at the repo root")


def _mod():
    spec = importlib.util.spec_from_file_location("check_dist", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wheel(d: Path, names: list[str]) -> Path:
    p = d / "edp8-0.9.0-py3-none-any.whl"
    with zipfile.ZipFile(p, "w") as z:
        for n in names:
            z.writestr(n, "x")
    return p


def _sdist(d: Path, names: list[str], pad: int = 0) -> Path:
    p = d / "edp8-0.9.0.tar.gz"
    with tarfile.open(p, "w:gz") as t:
        for n in names:
            data = os.urandom(pad) if pad and n.endswith(".bin") else b"x"
            info = tarfile.TarInfo(f"edp8-0.9.0/{n}")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return p


def test_clean_archives_pass(tmp_path):
    m = _mod()
    _wheel(tmp_path, ["edp8/__init__.py", "edp8/webapp/dist/index.html", "edp8/agent_home/guides/x.md"])
    _sdist(tmp_path, ["pyproject.toml", "src/edp8/__init__.py", "LICENSE", "NOTICE", "CHANGELOG.md"])
    assert m.main([str(tmp_path)]) == 0


@pytest.mark.parametrize("bad", [
    "docs/evidence/s-adv/walk-log.txt", "docs/ui-redesign-concepts/a.png", "web/e2e/evidence/s12/x.py",
    "tests/test_x.py", "tests/fixtures/shot.png", ".data/edp8.db", "scratch_notes.md", "src/edp8/__pycache__/a.pyc",
])
def test_an_excluded_path_fails(tmp_path, bad):
    m = _mod()
    p = _sdist(tmp_path, ["pyproject.toml", bad])
    assert any("excluded path" in msg for msg in m.check(p))


def test_the_sdist_ceiling_fails(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setitem(m.CEILINGS, "sdist", 64 * 1024)
    p = _sdist(tmp_path, ["pyproject.toml", "src/big.bin"], pad=200 * 1024)
    assert any("exceeds the sdist ceiling" in msg for msg in m.check(p))


@pytest.mark.skipif(not os.environ.get("HERONRY_DIST_DIR"), reason="no real dist folder given")
def test_real_dist_folder_is_clean():
    assert _mod().main([os.environ["HERONRY_DIST_DIR"]]) == 0
