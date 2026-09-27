"""S8 (s-6dcf78f803): the Briefcase bundle's service re-entry, unit level.

The hands-on proof is v8/desktop/scripts/drill_bundle_windows.ps1 (all four services + the supervisor start as
`heronry.exe --heronry-service <svc>` from a built bundle); these pin the pieces it relies on."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from edp8 import launcher

ENTRY = Path(__file__).resolve().parents[1] / "desktop" / "src" / "heronry" / "__main__.py"


def _entry():
    spec = importlib.util.spec_from_file_location("heronry_entry_under_test", ENTRY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("exe,expected", [
    ("C:/x/.venv/Scripts/python.exe", False), ("/usr/bin/python3.12", False), ("C:/Py/pythonw.exe", False),
    ("C:/Apps/Heronry Desktop/heronry.exe", True), ("C:/Apps/Heronry Desktop/Heronry Desktop.exe", True),
    ("/Applications/Heronry Desktop.app/Contents/MacOS/Heronry Desktop", True), ("/usr/bin/heronry", True),
])
def test_bundled_is_structural_because_briefcase_sets_no_frozen(monkeypatch, exe, expected):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", exe)
    assert launcher.bundled() is expected


def test_frozen_still_means_bundled(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:/x/python.exe")
    assert launcher.bundled() is True


def test_service_argv_in_a_windows_bundle_uses_the_console_stub(monkeypatch, tmp_path):
    gui = tmp_path / "Heronry Desktop.exe"
    gui.write_bytes(b"")
    (tmp_path / "heronry.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(gui))
    monkeypatch.setattr(sys, "platform", "win32")
    assert launcher.service_argv("board") == [str(tmp_path / "heronry.exe"), "--heronry-service", "board"]


def test_a_start_from_the_gui_stub_detaches_through_the_console_stub(monkeypatch, tmp_path):
    """Owner look, S8 step 6: a Start-menu launch runs Heronry Desktop.exe (GUI subsystem); detach's intermediate
    must run through heronry.exe, whose stdout carries the pid, or every start fails after spawning."""
    gui = tmp_path / "Heronry Desktop.exe"
    gui.write_bytes(b"")
    (tmp_path / "heronry.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(gui))
    monkeypatch.setattr(sys, "platform", "win32")
    assert launcher._detach_via() == str(tmp_path / "heronry.exe")
    monkeypatch.setattr(sys, "executable", "C:/x/.venv/Scripts/python.exe")
    assert launcher._detach_via() is None


def test_detach_names_an_intermediate_that_reports_no_pid(monkeypatch):
    from edp_contracts import proc
    monkeypatch.setattr(proc.subprocess, "run", lambda *a, **k: proc.subprocess.CompletedProcess(a, 0, "", ""))
    with pytest.raises(RuntimeError, match="reported no process id"):
        proc.detach(["heronry.exe", "--heronry-service", "board"], via="C:/Apps/Heronry Desktop.exe")


def test_service_argv_without_a_console_stub_re_enters_the_app_itself(monkeypatch, tmp_path):
    app = tmp_path / "Heronry Desktop"
    app.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(app))
    monkeypatch.setattr(sys, "platform", "darwin")
    assert launcher.service_argv("pool") == [str(app), "--heronry-service", "pool"]


def test_entry_dispatches_the_service_flag_before_any_gui_import(monkeypatch):
    entry = _entry()
    seen = {}
    import edp8.cli as cli
    monkeypatch.setattr(cli, "_run_service", lambda name, args=None: seen.update(svc=name, args=args) or 0)
    monkeypatch.setattr(sys, "argv", ["heronry.exe", "--heronry-service", "broker"])
    before = set(sys.modules)
    assert entry.main() == 0
    assert seen["svc"] == "broker" and seen["args"] == []
    # S21: the code guard re-enters with its own arguments (--port, --upstream ...)
    monkeypatch.setattr(sys, "argv", ["heronry.exe", "--heronry-service", "code-guard", "--port", "19410"])
    assert entry.main() == 0
    assert seen == {"svc": "code-guard", "args": ["--port", "19410"]}
    assert not {m for m in set(sys.modules) - before if m.startswith(("webview", "pystray", "edp8.desktop"))}


def test_entry_runs_c_code_like_python(monkeypatch, capsys):
    entry = _entry()
    monkeypatch.setattr(sys, "argv", ["heronry.exe", "-c", "import sys; print('ran', sys.argv)", "a"])
    assert entry.main() == 0
    assert "ran ['-c', 'a']" in capsys.readouterr().out


def test_entry_runs_a_module_like_python(monkeypatch, tmp_path, capsys):
    (tmp_path / "s8_probe_mod.py").write_text("import sys\nprint('mod', sys.argv[1:])\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    entry = _entry()
    monkeypatch.setattr(sys, "argv", ["heronry.exe", "-m", "s8_probe_mod", "x"])
    assert entry.main() == 0
    assert "mod ['x']" in capsys.readouterr().out


def test_entry_passes_a_cli_verb_to_the_heronry_cli(monkeypatch):
    entry = _entry()
    import edp8.cli as cli
    got = {}
    monkeypatch.setattr(cli, "main", lambda argv=None: got.setdefault("argv", argv) and 0)
    monkeypatch.setattr(sys, "argv", ["heronry.exe", "status", "--json"])
    assert entry.main() == 0
    assert got["argv"] == ["status", "--json"]


def test_entry_with_no_argument_opens_the_gui(monkeypatch):
    entry = _entry()
    import edp8.cli as cli
    got = {}
    monkeypatch.setattr(cli, "main", lambda argv=None: got.setdefault("argv", argv) and 0)
    monkeypatch.setattr(sys, "argv", ["Heronry Desktop.exe"])
    assert entry.main() == 0
    assert got["argv"] == ["gui"]
