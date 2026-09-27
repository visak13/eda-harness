"""S9 PII gate (.github/scripts/pii_gate.py): a planted hit fails, no file is exempt from the name rule, and
archives are scanned inside. The owner needles live outside the tracked tree (qa report-bcef24a36a): the
PII_NEEDLES env var (CI secret) or the gitignored .pii-needles.toml. These tests plant SYNTHETIC needles, so no
tracked file names the maintainer; the last test runs the real gate, with the machine's needles, over the tree."""
from __future__ import annotations

import importlib.util
import io
import os
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "pii_gate.py"
ROOT = GATE.parents[2]
pytestmark = pytest.mark.skipif(not GATE.exists(), reason="gate lives at the repo root, not in an installed wheel")

USER = "zqxowner"
EMAIL = "zqx.owner-mail@example.net"
NAMES = ["Quillonby", "Marravelt"]
NEEDLES_TOML = f'usernames = ["{USER}"]\nemails = ["{EMAIL}"]\nnames = {NAMES!r}\n'.replace("'", '"')
PROJ = "C:" + "\\" + "Proj" + "ects" + "\\x"


def _gate(needles: dict | None = None):
    spec = importlib.util.spec_from_file_location("pii_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if needles is None:
        needles = tomllib.loads(NEEDLES_TOML)
    mod.RULES[:] = [*mod.owner_rules({k: needles.get(k, []) for k in mod.KINDS}), mod.PROJECTS_RULE]
    return mod


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PII_NEEDLES"}
    env.update(extra)
    return env


@pytest.mark.parametrize("text, rule", [
    (f"home = r'C:\\Users\\{USER}\\x'", "owner username"),
    (f"mail {EMAIL.upper()}", "owner email"),
    (f"open {PROJ}", "projects root"),
    ("folder=C%3A%5C" + "Proj" + "ects%5Cv8", "projects root"),
    ("/c/" + "proj" + "ects/eda", "projects root"),
    (f"by {NAMES[0]}", "owner name"),
    (f"{NAMES[1].lower()} wrote it", "owner name"),
])
def test_planted_hit_is_found(text, rule):
    hits = _gate().scan_text("src/x.py", text)
    assert [h for h in hits if f": {rule}:" in h], hits


def test_neutral_paths_pass():
    g = _gate()
    assert g.scan_text("src/x.py", rf"C:\Work\eda-base3 C:\Users\user\x /home/user/projects-list {USER}s_x") == []


def test_notice_is_not_exempt():
    # NOTICE names "Heronry contributors" (owner m-c486b47c54), so no file may carry the owner's name
    g = _gate()
    assert g.scan_text("NOTICE", f"Copyright 2026 {NAMES[0]}")
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


@pytest.mark.parametrize("enc", ["utf-16-le", "utf-16-be"])
@pytest.mark.parametrize("lead", [0, 8192, 1 << 20])
def test_utf16_needles_are_found_anywhere_in_the_stream(enc, lead):
    # adversary R2-D: the NUL-drop pass ran only when a NUL sat in the first 8 KiB
    data = b"A" * lead + ("C:\\Users\\" + USER + "\\x").encode(enc) + b"B" * 64
    assert [h for h in _gate().scan_bytes("late.bin", data) if ": owner username:" in h], (enc, lead)


@pytest.mark.parametrize("enc", ["utf-16-le", "utf-16-be"])
def test_a_bare_utf16_needle_after_ascii_padding_is_found(enc):
    # the adversary's shape (.data/s11-r2/probes.py): 8 KiB of b"A", then only the needle
    assert _gate().scan_bytes("late.bin", b"A" * 8192 + USER.encode(enc))


# ── where the needles come from ─────────────────────────────────────────────────────────────────

def test_needles_come_from_the_env_before_the_local_file(tmp_path, monkeypatch):
    g = _gate()
    monkeypatch.delenv("PII_NEEDLES", raising=False)
    assert g.load_needles(tmp_path) is None
    (tmp_path / ".pii-needles.toml").write_text('names = ["Fromfile"]\n', encoding="utf-8")
    assert g.load_needles(tmp_path)["names"] == ["Fromfile"]
    monkeypatch.setenv("PII_NEEDLES", NEEDLES_TOML)
    assert g.load_needles(tmp_path) == {"usernames": [USER], "emails": [EMAIL], "names": NAMES}
    monkeypatch.setenv("PII_NEEDLES", 'nmaes = ["typo"]\n')
    with pytest.raises(ValueError, match="nmaes"):
        g.load_needles(tmp_path)


def test_cli_exits_1_on_a_planted_file_and_0_when_clean(tmp_path):
    scan = tmp_path / "dist"
    scan.mkdir()
    (scan / "clean.txt").write_text("nothing here")

    def run(*extra, **env):
        return subprocess.run([sys.executable, str(GATE), "--dir", str(scan), "--root", str(tmp_path), *extra],
                              capture_output=True, text=True, env=_env(**env))
    assert run().returncode == 0
    (scan / "planted.md").write_text(f"see {PROJ}")
    r = run()
    assert r.returncode == 1 and "planted.md:1: projects root" in r.stdout
    (scan / "planted.md").write_text(f"by {NAMES[0]}")
    off = run()
    assert off.returncode == 0 and "owner rules are OFF" in off.stderr, "no needles: said, not silently passed"
    assert run("--require-needles").returncode == 2
    on = run(PII_NEEDLES=NEEDLES_TOML)
    assert on.returncode == 1 and "planted.md:1: owner name" in on.stdout
    (tmp_path / ".pii-needles.toml").write_text(NEEDLES_TOML, encoding="utf-8")
    assert run().returncode == 1, "the local gitignored file is read when the env is unset"


def test_gitleaks_config_inlines_the_tracked_config_with_re2_owner_rules(tmp_path):
    # inlined, not [extend] path=: gitleaks 8.30.1 drops an extended file's [[allowlists]] (CI run 36323612069)
    (tmp_path / ".gitleaks.toml").write_bytes((ROOT / ".gitleaks.toml").read_bytes())
    tracked = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    out = tmp_path / ".gitleaks.pii.toml"
    r = subprocess.run([sys.executable, str(GATE), "--root", str(tmp_path), "--gitleaks-config", str(out)],
                       capture_output=True, text=True, env=_env(PII_NEEDLES=NEEDLES_TOML))
    assert r.returncode == 0, r.stderr
    cfg = tomllib.loads(out.read_text(encoding="utf-8"))
    assert cfg["extend"] == {"useDefault": True} and cfg["allowlists"] == tracked["allowlists"]
    rules = {x["id"]: x["regex"] for x in cfg["rules"]}
    assert set(rules) == {"pii-projects-root", "pii-owner-username", "pii-owner-email", "pii-owner-name"}
    for rid, planted in (("pii-owner-username", f"C:/Users/{USER}/x"), ("pii-owner-email", EMAIL.upper()),
                         ("pii-owner-name", f"by {NAMES[1]}.")):
        assert "(?<" not in rules[rid] and "(?=" not in rules[rid] and "(?!" not in rules[rid], "RE2 has no lookaround"
        assert re.search(rules[rid], planted), (rid, rules[rid])
    assert not re.search(rules["pii-owner-username"], f"{USER}s")
    # no needles: the config is the tracked rules alone
    out.unlink()
    subprocess.run([sys.executable, str(GATE), "--root", str(tmp_path), "--gitleaks-config", str(out)], env=_env(),
                   check=True, capture_output=True)
    assert tomllib.loads(out.read_text(encoding="utf-8")) == tracked


def test_tracked_gitleaks_config_holds_no_owner_rule():
    cfg = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    assert [r["id"] for r in cfg.get("rules", [])] == ["pii-projects-root"]
    local = ROOT / ".pii-needles.toml"
    if local.is_file():  # the maintainer's machine: prove the tracked config spells none of them, in any case
        needles = [n for vals in tomllib.loads(local.read_text(encoding="utf-8")).values() for n in vals]
        for f in (ROOT / ".gitleaks.toml", GATE, Path(__file__)):
            text = f.read_text(encoding="utf-8").lower()
            assert not [n for n in needles if n.lower() in text], f


def test_the_gate_passes_on_its_own_tracked_tree():
    # adversary m-66e0b46c22 / architect m-321f649a41: the gate, its config and its tests never hold a needle;
    # run with this machine's needles (PII_NEEDLES or the local .pii-needles.toml) when there are any
    r = subprocess.run([sys.executable, str(GATE), "--root", str(ROOT)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:]
