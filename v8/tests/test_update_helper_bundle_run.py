"""The update helper runs the way the desktop bundle starts it (owner m-8b37e6b58e).

The bundle's stub runs `<stub> update-helper.py …` through runpy.run_path, which does not put the script's folder on
sys.path the way `python script.py` does. 0.10.2's helper then died at `import update_lock` before it parked, stopped
or showed anything: `heronry update` printed "handed over" and nothing followed. Measured on the owner's install by
running the staged helper from a copy of the bundle runtime."""

from __future__ import annotations

import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "src" / "edp8" / "update_helper.py"
SHIM = ROOT / "desktop" / "src" / "heronry" / "__main__.py"


def _staged(tmp_path: Path) -> tuple[Path, Path]:
    """update-helper.py with update_lock.py beside it, as updater.stage_runner lays them out, and a progress file
    whose last step is the result."""
    stage = tmp_path / "stage"
    stage.mkdir()
    shutil.copyfile(HELPER, stage / "update-helper.py")
    shutil.copyfile(HELPER.with_name("update_lock.py"), stage / "update_lock.py")
    prog = stage / "update-progress.jsonl"
    prog.write_text(json.dumps({"elapsed": 3, "step": "verified", "detail": "0.10.2 -> 0.10.3"}) + "\n"
                    + json.dumps({"elapsed": 95, "step": "rolled back", "detail": "0.10.2 runs again",
                                  "final": True}) + "\n", encoding="utf-8")
    return stage, prog


def _run_as_bundle(code: str, cwd: Path) -> subprocess.CompletedProcess:
    # -I: no script folder, no cwd and no PYTHONPATH on sys.path, like the stub's runpy; edp8 itself stays
    # importable from the venv, but update_lock is not a top-level module there
    return subprocess.run([sys.executable, "-I", "-c", code], cwd=str(cwd), input="\n", capture_output=True,
                          text=True, timeout=60)


def test_the_staged_helper_runs_through_runpy_and_its_window_shows_the_result(tmp_path):
    stage, prog = _staged(tmp_path)
    h = stage / "update-helper.py"
    code = (f"import runpy, sys; sys.argv = [{str(h)!r}, '--view', {str(prog)!r}]; "
            f"runpy.run_path({str(h)!r}, run_name='__main__')")
    r = _run_as_bundle(code, tmp_path)
    assert "update_lock" not in r.stderr, r.stderr
    assert "[0:03] verified: 0.10.2 -> 0.10.3" in r.stdout and "[1:35] rolled back: 0.10.2 runs again" in r.stdout


def test_the_bundle_stub_puts_a_scripts_folder_first_on_the_path_as_python_does(tmp_path, monkeypatch):
    shim = runpy.run_path(str(SHIM), run_name="heronry_shim")
    script = tmp_path / "s" / "probe.py"
    script.parent.mkdir()
    (script.parent / "beside.py").write_text("VALUE = 7\n", encoding="utf-8")
    script.write_text("import beside, sys\nsys.modules['__probe_result__'] = beside\n", encoding="utf-8")
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "argv", list(sys.argv))
    monkeypatch.delitem(sys.modules, "beside", raising=False)
    assert shim["_as_interpreter"]([str(script)]) == 0
    assert sys.modules.pop("__probe_result__").VALUE == 7
    sys.modules.pop("beside", None)


class _Ident:
    def __init__(self, alive: bool):
        self.alive = alive

    def live(self):
        return object() if self.alive else None


def test_the_cli_says_so_when_the_helper_died_before_reporting(tmp_path):
    import pytest

    from edp8 import updater
    out = tmp_path / "update-helper.out"
    out.write_text("Traceback (most recent call last):\nModuleNotFoundError: No module named 'update_lock'\n",
                   encoding="utf-8")
    with pytest.raises(updater.UpdateError) as e:
        updater.confirm_started(_Ident(False), out, tmp_path / "update-result.json", seconds=1)
    assert "No module named 'update_lock'" in str(e.value) and "did not run" in str(e.value)


def test_a_helper_that_ended_with_a_result_prints_it_and_one_still_running_hands_over(tmp_path, capsys):
    from edp8 import updater
    res = tmp_path / "update-result.json"
    res.write_text(json.dumps({"state": "rolled_back", "from": "0.10.2", "reason": "msiexec exit 1603"}),
                   encoding="utf-8")
    updater.confirm_started(_Ident(False), tmp_path / "none.out", res, seconds=1)
    assert "Rolled back to 0.10.2: msiexec exit 1603" in capsys.readouterr().out
    updater.confirm_started(_Ident(True), tmp_path / "none.out", tmp_path / "missing.json", seconds=0.3)


def _progress(tmp_path: Path, final_detail: str | None) -> Path:
    prog = tmp_path / "update-progress.jsonl"
    rows = [{"elapsed": 3, "step": "stop", "detail": "the supervisor and services"}]
    if final_detail is not None:
        rows.append({"elapsed": 200, "step": "result", "detail": final_detail, "final": True})
    prog.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return prog


def test_the_shell_viewer_returns_0_when_installed_and_1_with_the_recovery_line_when_not(tmp_path, capsys):
    from edp8 import update_helper as h
    assert h.view(str(_progress(tmp_path, "ok")), inline=True) == 0
    out = capsys.readouterr().out
    assert "this shell returns when it is done" in out and "[3:20] result: ok" in out and "Updated." in out
    res = tmp_path / "update-result.json"
    res.write_text(json.dumps({"state": "failed", "recover_hint": "reinstall 0.10.2 from its cached installer"}),
                   encoding="utf-8")
    assert h.view(str(_progress(tmp_path, "failed: msiexec exit 1603")), inline=True, result_file=str(res)) == 1
    out = capsys.readouterr().out
    assert "The update did not install." in out and "reinstall 0.10.2 from its cached installer" in out


def test_the_shell_viewer_says_so_when_the_helper_ended_without_a_result(tmp_path, capsys):
    from edp8 import update_helper as h
    dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    pid = int(dead.stdout.strip())
    assert h.view(str(_progress(tmp_path, None)), pid=pid, inline=True) == 1
    out = capsys.readouterr().out
    assert "[0:03] stop: the supervisor and services" in out and "ended without a result" in out


def test_the_follow_script_runs_the_viewer_from_the_copy_outside_the_install(tmp_path):
    from edp8 import updater

    class _Id:
        pid, create_time = 4242, 1791115656.25
    f = tmp_path / "heronry-follow-1.cmd"
    updater.write_follow(f, Path(r"C:\h\update\runtime\heronry.exe"), Path(r"C:\h\update\update-helper.py"),
                         Path(r"C:\h\update\update-progress.jsonl"), _Id(), Path(r"C:\h\update\update-result.json"))
    raw = f.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    text = raw.decode("ascii")
    assert (r'"C:\h\update\runtime\heronry.exe" "C:\h\update\update-helper.py" --view '
            r'"C:\h\update\update-progress.jsonl" --pid 4242 --created 1791115656.250 '
            r'--result "C:\h\update\update-result.json" --inline') in text
    assert text.rstrip().endswith("exit /b %ERRORLEVEL%")
