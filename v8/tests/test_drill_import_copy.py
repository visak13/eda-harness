"""scripts/drill_import_copy.py cleanup (qa m-d125eafce3): the drill copies the fleet state, tokens included,
into %TEMP%; a silent `rmtree(ignore_errors=True)` left a 2.9 GB copy behind. The temp folder is now
removed on every exit path (pass, failed check, exception) and a removal that fails raises."""
from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "drill_import_copy.py"


@pytest.fixture
def drill(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("drill_import_copy_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    made: list[Path] = []

    def mkdtemp(prefix=""):
        d = tmp_path / f"{prefix}x{len(made)}"
        d.mkdir()
        (d / "v8copy").mkdir()
        (d / "v8copy" / "tokens.json").write_text("{}", encoding="utf-8")
        made.append(d)
        return str(d)

    monkeypatch.setattr(mod.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(sys, "argv", ["drill_import_copy.py"])
    mod.made = made
    return mod


def test_cleanup_removes_a_read_only_tree(drill, tmp_path):
    t = tmp_path / "s3-import-ro"
    (t / "a").mkdir(parents=True)
    f = t / "a" / "tokens.json"
    f.write_text("{}", encoding="utf-8")
    os.chmod(f, stat.S_IREAD)
    drill.cleanup(t)
    assert not t.exists()


def test_cleanup_raises_naming_the_folder_when_removal_fails(drill, tmp_path, monkeypatch):
    t = tmp_path / "s3-import-stuck"
    t.mkdir()
    monkeypatch.setattr(drill.shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(PermissionError("in use")))
    with pytest.raises(drill.CleanupError, match="s3-import-stuck"):
        drill.cleanup(t)
    assert t.exists()


@pytest.mark.parametrize("outcome", ["pass", "failed_check", "exception", "interrupt"])
def test_main_removes_the_copy_on_every_exit_path(drill, monkeypatch, outcome):
    def fake(t):
        assert (t / "v8copy" / "tokens.json").is_file()
        if outcome == "exception":
            raise RuntimeError("drill blew up")
        if outcome == "interrupt":
            raise KeyboardInterrupt
        return 0 if outcome == "pass" else 1

    monkeypatch.setattr(drill, "_drill", fake)
    if outcome in ("exception", "interrupt"):
        with pytest.raises((RuntimeError, KeyboardInterrupt)):
            drill.main()
    else:
        assert drill.main() == (0 if outcome == "pass" else 1)
    assert drill.made and not drill.made[0].exists()


def test_keep_leaves_the_copy(drill, monkeypatch):
    monkeypatch.setattr(drill, "_drill", lambda t: 0)
    monkeypatch.setattr(sys, "argv", ["drill_import_copy.py", "--keep"])
    assert drill.main() == 0
    assert drill.made[0].exists()


def test_a_failed_cleanup_is_loud_even_after_a_pass(drill, monkeypatch):
    monkeypatch.setattr(drill, "_drill", lambda t: 0)
    monkeypatch.setattr(drill.shutil, "rmtree", lambda *a, **k: None)
    with pytest.raises(drill.CleanupError):
        drill.main()
