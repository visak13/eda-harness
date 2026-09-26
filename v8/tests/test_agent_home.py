"""Agent home materialisation (S1, criterion c-6d8e6fe660): package data → a target dir with a hash
manifest, by the dpkg-conffile table of strategyhl-86b4805322 §2; a re-run keeps user-edited files and
reports them as conflicts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from edp8 import materialise as agent_home
from edp8.materialise import MANIFEST, materialise

V8 = Path(__file__).resolve().parents[1]
NL = "\n"


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text + NL, encoding="utf-8")


def _r(p: Path) -> str:
    return p.read_text(encoding="utf-8").rstrip(NL)


def _fake_source(root: Path) -> Path:
    _w(root / ".claude" / "commands" / "engineer.md", "card v1")
    _w(root / ".claude" / "skills" / "verify" / "SKILL.md", "skill v1")
    _w(root / ".claude" / "output-styles" / "edp-terse.md", "style v1")
    _w(root / "guides" / "resume.md", "guide v1")
    _w(root / ".mcp.json", "{}")
    _w(root / "models.json", '{"seats": {}}')
    return root


def test_the_real_agent_home_materialises_every_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDP8_HOME", str(V8))  # dev mode: the checkout is the source
    rep = materialise(tmp_path / "home")
    t = tmp_path / "home"
    for rel in (".claude/commands/engineer.md", ".claude/commands/qa.md", ".claude/skills/verify/SKILL.md",
                ".claude/output-styles/edp-terse.md", "guides/shared-host-rules.md", ".mcp.json", "models.json"):
        assert (t / rel).is_file(), rel
    style = ".claude/output-styles/edp-terse.md"
    assert (t / style).read_bytes() == (V8 / style).read_bytes()
    manifest = json.loads((t / MANIFEST).read_text(encoding="utf-8"))
    assert set(manifest) == set(rep.written) and len(rep.written) > 20
    assert rep.conflicts == [] and rep.updated == []


def test_rerun_keeps_user_edits_and_reports_them(tmp_path: Path) -> None:
    src = _fake_source(tmp_path / "src")
    tgt = tmp_path / "home"
    card = ".claude/commands/engineer.md"
    assert card in materialise(tgt, src).written
    # the user edits one card; a re-run with nothing new shipped keeps it and reports it
    _w(tgt / card, "my own card")
    again = materialise(tgt, src)
    assert again.conflicts == [card] and again.new_written == []
    # the release changes that card AND an unedited guide
    _w(src / card, "card v2")
    _w(src / "guides/resume.md", "guide v2")
    second = materialise(tgt, src)
    assert second.conflicts == [card] and _r(tgt / card) == "my own card"
    assert second.new_written == [card + ".new"] and _r(tgt / (card + ".new")) == "card v2"
    assert second.updated == ["guides/resume.md"] and _r(tgt / "guides/resume.md") == "guide v2"
    # still reported next time, but no second .new for the same shipped version
    third = materialise(tgt, src)
    assert third.conflicts == [card] and third.new_written == []


def test_dry_run_reports_without_writing(tmp_path: Path) -> None:
    src = _fake_source(tmp_path / "src")
    tgt = tmp_path / "home"
    rep = materialise(tgt, src, dry_run=True)
    assert rep.dry_run and ".mcp.json" in rep.written
    assert not tgt.exists()


def test_a_user_deleted_file_stays_deleted(tmp_path: Path) -> None:
    src = _fake_source(tmp_path / "src")
    tgt = tmp_path / "home"
    materialise(tgt, src)
    (tgt / "guides" / "resume.md").unlink()
    rep = materialise(tgt, src)
    assert rep.user_deleted == ["guides/resume.md"] and not (tgt / "guides" / "resume.md").exists()


def test_a_retired_file_is_left_and_dropped_from_the_manifest(tmp_path: Path) -> None:
    src = _fake_source(tmp_path / "src")
    tgt = tmp_path / "home"
    _w(src / "guides" / "old.md", "old")
    materialise(tgt, src)
    (src / "guides" / "old.md").unlink()
    rep = materialise(tgt, src)
    assert rep.retired == ["guides/old.md"] and (tgt / "guides" / "old.md").exists()
    assert "guides/old.md" not in json.loads((tgt / MANIFEST).read_text(encoding="utf-8"))


def test_a_preexisting_foreign_file_is_a_conflict_not_overwritten(tmp_path: Path) -> None:
    src = _fake_source(tmp_path / "src")
    tgt = tmp_path / "home"
    _w(tgt / "guides" / "resume.md", "theirs")
    rep = materialise(tgt, src)
    assert rep.conflicts == ["guides/resume.md"] and rep.new_written == ["guides/resume.md.new"]
    assert _r(tgt / "guides" / "resume.md") == "theirs"


def test_no_source_outside_dev_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDP8_HOME", str(tmp_path))
    monkeypatch.delenv("EDP_DEV", raising=False)
    with pytest.raises(FileNotFoundError):
        agent_home.source_root()
