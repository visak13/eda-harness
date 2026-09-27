"""S9 PII gate (.github/scripts/pii_gate.py): a planted hit fails, NOTICE keeps its copyright holder, and
archives are scanned inside. Needles are assembled from parts, like the gate itself."""
from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "pii_gate.py"
pytestmark = pytest.mark.skipif(not GATE.exists(), reason="gate lives at the repo root, not in an installed wheel")

USER = "a" + "ksou"
PROJ = "C:" + "\\" + "Proj" + "ects" + "\\x"


def _gate():
    spec = importlib.util.spec_from_file_location("pii_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("text, rule", [
    (f"home = r'C:\\Users\\{USER}\\x'", "owner username"),
    (f"mail {USER}lkar@gmail.com", "owner email"),
    (f"open {PROJ}", "projects root"),
    ("folder=C%3A%5C" + "Proj" + "ects%5Cv8", "projects root"),
    ("/c/" + "proj" + "ects/eda", "projects root"),
    ("by " + "Vis" + "hal", "owner name"),
])
def test_planted_hit_is_found(text, rule):
    hits = _gate().scan_text("src/x.py", text)
    assert [h for h in hits if f": {rule}:" in h], hits


def test_neutral_paths_pass():
    g = _gate()
    assert g.scan_text("src/x.py", r"C:\Work\eda-base3 C:\Users\user\x /home/user/projects-list") == []


def test_notice_keeps_the_copyright_holder_but_not_paths():
    g = _gate()
    assert g.scan_text("NOTICE", "Copyright 2026 " + "Vis" + "hal") == []
    assert g.scan_text("NOTICE", f"see {PROJ}")


def test_archives_are_scanned_inside():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pkg/data.txt", f"x {PROJ} y")
    hits = _gate().scan_bytes("dist/pkg-0.9.0-py3-none-any.whl", buf.getvalue())
    assert hits and "whl!pkg/data.txt" in hits[0]


def test_binary_files_are_scanned_as_bytes(tmp_path):
    import sqlite3
    db = tmp_path / ".coverage"
    with sqlite3.connect(db) as c:  # the shape S11 F9 found: a coverage DB holding checkout paths
        c.execute("create table file (path text)")
        c.execute("insert into file values (?)", (PROJ + "\\edp_pool\\main.py",))
    g = _gate()
    assert [h for h in g.scan_bytes(".coverage", db.read_bytes()) if ": projects root:" in h]
    utf16 = b"\x00\x01" + ("C:\\Users\\" + USER + "\\x").encode("utf-16-le")
    assert [h for h in g.scan_bytes("app.exe", utf16) if ": owner username:" in h]


def test_cli_exits_1_on_a_planted_file_and_0_when_clean(tmp_path):
    (tmp_path / "clean.txt").write_text("nothing here")
    def run():
        return subprocess.run([sys.executable, str(GATE), "--dir", str(tmp_path)], capture_output=True, text=True)
    assert run().returncode == 0
    (tmp_path / "planted.md").write_text(f"see {PROJ}")
    r = run()
    assert r.returncode == 1 and "planted.md:1: projects root" in r.stdout


def test_the_gate_passes_on_its_own_tracked_tree():
    # adversary m-66e0b46c22 / architect m-321f649a41: the gate, its config and its tests never hold a needle
    root = GATE.parents[2]
    r = subprocess.run([sys.executable, str(GATE), "--root", str(root)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:]
