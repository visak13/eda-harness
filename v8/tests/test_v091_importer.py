"""v0.9.1 importer fixes (s-dbe96f11cd, found in the owner's live cutover):

* the live `.data/models.json` wins over the root `models.json` template (both mapped to one target);
* a stale `edp8.db-wal`/`-shm` beside the target is removed with the DB it belonged to (the import
  reported 0 epics because SQLite replayed the old WAL over the imported file);
* the pool's claude transcripts move to the new claude config dir under the agent home's cwd key, so a
  resumed seat finds its conversation;
* the report never says "into None" on an installed (no EDP_HOME) layout.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from edp8 import importer, settings


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "installed-home"
    h.mkdir()
    for name in ("EDP_HOME", "EDP_DEV", "EDP8_DATA", "EDP8_DB", "EDP_CONFIG_DIR", "EDP_AGENT_HOME",
                 "EDP_CLAUDE_CONFIG_DIR", "EDP_MODELS_CONFIG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EDP8_HOME", str(h))
    assert not settings.dev_mode()
    return h


def _src(tmp_path: Path) -> Path:
    src = tmp_path / "repo" / "v8"
    (src / ".data").mkdir(parents=True)
    return src


def _board_db(p: Path, epics: int) -> None:
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE ticket (id TEXT, kind TEXT)")
    c.execute("CREATE TABLE participant (id TEXT)")
    c.executemany("INSERT INTO ticket VALUES (?, 'epic')", [(f"e{i}",) for i in range(epics)])
    c.commit()
    c.close()


def test_live_models_catalog_wins_over_the_root_template(home, tmp_path):
    src = _src(tmp_path)
    (src / ".data" / "models.json").write_text('{"live": true}', encoding="utf-8")
    (src / "models.json").write_text('{"template": true}', encoding="utf-8")
    items = importer.plan(src)
    target = settings.data_dir() / "models.json"
    assert [it.src for it in items if it.dst == target] == [src / ".data" / "models.json"]
    importer.apply(items, ({}, {}, []))
    assert target.read_text(encoding="utf-8") == '{"live": true}'


def test_stale_wal_beside_the_target_is_removed_before_the_db_lands(home, tmp_path):
    src = _src(tmp_path)
    _board_db(src / ".data" / "edp8.db", epics=3)
    dst = Path(settings.get("EDP8_DB"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    # a target left by an earlier board: WAL mode, the last writes still in its -wal
    c = sqlite3.connect(dst)
    c.execute("PRAGMA journal_mode=wal")
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("CREATE TABLE ticket (id TEXT, kind TEXT)")
    c.execute("CREATE TABLE participant (id TEXT)")
    c.execute("CREATE TABLE junk (x)")
    c.executemany("INSERT INTO junk VALUES (?)", [(i,) for i in range(500)])
    c.commit()
    wal = dst.with_name(dst.name + "-wal")
    stale = tmp_path / "stale-wal"
    shutil.copyfile(wal, stale)
    c.close()
    shutil.copyfile(stale, wal)
    dst.with_name(dst.name + "-shm").write_bytes(b"\0" * 32768)

    importer.apply(importer.plan(src), ({}, {}, []))
    assert not wal.exists() and not dst.with_name(dst.name + "-shm").exists()
    assert importer.db_counts(dst) == {"epics": 3, "tickets": 3, "participants": 0}
    assert (settings.data_dir() / "backups" / "edp8-pre-import.db").is_file()


def test_claude_transcripts_move_under_the_agent_home_key(home, tmp_path):
    src = _src(tmp_path)
    old = tmp_path / "repo" / "edp-pool" / ".claude-pool" / "projects" / importer.cwd_key(src)
    (old / "memory").mkdir(parents=True)
    (old / "90821211-e7ad.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
    (old / "memory" / "MEMORY.md").write_text("- note\n", encoding="utf-8")
    importer.apply(importer.plan(src), ({}, {}, []))
    new = (Path(settings.get("EDP_CLAUDE_CONFIG_DIR")) / "projects" /
           importer.cwd_key(settings.agent_home()))
    assert new.parent.parent == settings.data_dir() / "claude-pool"
    new = importer._long(new)  # the key of a pytest tmp agent home runs past MAX_PATH
    assert (new / "90821211-e7ad.jsonl").read_text(encoding="utf-8") == '{"type":"user"}\n'
    assert (new / "memory" / "MEMORY.md").is_file()


def test_claude_transcripts_follow_the_source_env_config_dir(home, tmp_path):
    src = _src(tmp_path)
    cfg = tmp_path / "elsewhere" / "claude-cfg"
    (cfg / "projects" / importer.cwd_key(src)).mkdir(parents=True)
    (cfg / "projects" / importer.cwd_key(src) / "s1.jsonl").write_text("{}\n", encoding="utf-8")
    (src / ".env").write_text(f"EDP_CLAUDE_CONFIG_DIR={cfg}\n", encoding="utf-8")
    items = importer.plan(src)
    assert any(it.what == "claude transcripts" and it.src == cfg / "projects" / importer.cwd_key(src)
               for it in items)


def test_report_names_the_install_not_none(tmp_path, monkeypatch, capsys):
    for name in ("EDP_HOME", "EDP8_HOME", "EDP_DEV", "EDP8_DATA", "EDP_CONFIG_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EDP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("EDP8_DATA", str(tmp_path / "data"))
    importer.report(tmp_path, [], ({}, {}, []))
    out = capsys.readouterr().out
    assert "None" not in out
    assert str(tmp_path / "cfg") in out
