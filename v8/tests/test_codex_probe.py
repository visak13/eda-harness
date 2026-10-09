"""qa m-da89ef8294 item 9 (architect m-7d7910576b): Admin -> Seats & models must never hang on
`codex debug models`. A codex (here a stub) whose grandchild holds the inherited stdout and which itself
sleeps is killed, tree and all, at the probe's hard timeout; the failure is cached and named in the view."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from admin_support import ADMIN_H, make_env

from edp8 import model_catalog

HANG = r"""
import os, subprocess, sys, time
pidfile = sys.argv[1]
# the grandchild inherits stdout and outlives a plain kill of its parent; it records its own pid
subprocess.Popen([sys.executable, "-c",
                  "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(60)",
                  pidfile])
time.sleep(60)
"""

OK = r"""
import json
print(json.dumps({"models": [{"slug": "gpt-6-sol", "context_window": 272000, "max_context_window": 872000},
                             {"slug": "broken"}]}))
"""


def _stub(tmp_path: Path, body: str, *args: str) -> str:
    script = tmp_path / "codex_stub.py"
    script.write_text(body, encoding="utf-8")
    argv = " ".join(f'"{a}"' for a in args)
    if sys.platform == "win32":
        exe = tmp_path / "codex.cmd"
        exe.write_text(f'@"{sys.executable}" "{script}" {argv}\r\n', encoding="utf-8")
    else:
        exe = tmp_path / "codex"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" {argv}\n', encoding="utf-8")
        exe.chmod(0o755)
    return str(exe)


@pytest.fixture
def fresh_probe(monkeypatch):
    monkeypatch.setattr(model_catalog, "_probe_state", {"windows": None, "ok": None, "error": None, "at": 0.0},
                        raising=False)
    monkeypatch.setattr(model_catalog, "_probe_thread", None, raising=False)
    monkeypatch.setattr(model_catalog, "_codex_windows", None, raising=False)  # the pre-fix cache
    monkeypatch.setattr(model_catalog, "PROBE_TIMEOUT", 2.0, raising=False)


def _bounded(fn, limit: float):
    """fn() in a daemon thread: (finished, result, seconds). A hang fails the test instead of hanging it."""
    box: dict = {}
    t = threading.Thread(target=lambda: box.update(v=fn()), daemon=True)
    t0 = time.monotonic()
    t.start()
    t.join(limit)
    return not t.is_alive(), box.get("v"), time.monotonic() - t0


def _wait_gone(pid: int, limit: float = 5.0) -> bool:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.1)
    return False


def _kill(pid: int) -> None:
    try:
        psutil.Process(pid).kill()
    except psutil.Error:
        return


def test_hung_codex_is_killed_with_its_grandchild_and_the_failure_is_cached(tmp_path, monkeypatch, fresh_probe):
    pidfile = tmp_path / "grandchild.pid"
    monkeypatch.setenv("EDP_CODEX_BIN", _stub(tmp_path, HANG, str(pidfile)))
    try:
        done, got, took = _bounded(model_catalog.codex_windows, 20.0)
        assert done, "codex_windows() hung on a codex whose grandchild holds stdout"
        assert got == {} and took < 10.0, took
        assert model_catalog.codex_probe() == {"ok": False, "error": "codex debug models timed out after 2s"}
        assert pidfile.is_file(), "the stub's grandchild never started"
        assert _wait_gone(int(pidfile.read_text())), "the grandchild holding stdout survived the probe"
        # a cached failure: the next call answers at once, without another probe
        done, got, took = _bounded(model_catalog.codex_windows, 5.0)
        assert done and got == {} and took < 0.5, took
    finally:
        if pidfile.is_file():
            _kill(int(pidfile.read_text()))


def test_admin_view_answers_promptly_and_names_the_probe_failure(tmp_path, monkeypatch, fresh_probe):
    home = tmp_path / "home"
    home.mkdir()
    row = {"harness": "codex", "provider": "codex", "effort_cap": "high"}
    base = {"models": {"gpt-6-sol": row}, "role_models": {"engineer": ["gpt-6-sol"]}, "default_model": "gpt-6-sol"}
    (home / "models.json").write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(home))
    monkeypatch.setenv("EDP8_DATA", str(tmp_path / "data"))
    pidfile = tmp_path / "grandchild.pid"
    monkeypatch.setenv("EDP_CODEX_BIN", _stub(tmp_path, HANG, str(pidfile)))
    env = make_env(tmp_path, monkeypatch)
    try:
        done, r, took = _bounded(lambda: env.client.get("/v1/admin/models", headers=ADMIN_H), 20.0)
        assert done, "GET /v1/admin/models hung on codex debug models"
        assert r.status_code == 200, r.text
        view = r.json()["value"]
        assert view["models"] == base["models"] and view["harness_defaults"] == {}
        assert view["codex_probe"] == {"ok": False, "error": "codex debug models timed out after 2s"}
    finally:
        if pidfile.is_file():
            _kill(int(pidfile.read_text()))


def test_codex_windows_reads_codex_debug_models_and_retry_reprobes(tmp_path, monkeypatch, fresh_probe):
    monkeypatch.setenv("EDP_CODEX_BIN", _stub(tmp_path, OK))
    got = model_catalog.codex_windows()
    assert got == {"gpt-6-sol": {"context_window": 272000, "max_context_window": 872000, "auto_compact": 244800}}
    assert model_catalog.codex_probe() == {"ok": True, "error": None}
    # a later failure keeps the last good windows; the status names the failure
    monkeypatch.setenv("EDP_CODEX_BIN", _stub(tmp_path, "import sys; print('nope'); sys.exit(3)"))
    assert model_catalog.codex_windows(refresh=True) == got
    assert model_catalog.codex_probe() == {"ok": False, "error": "codex debug models exited 3 without a model list"}


def test_absent_codex_is_a_named_failure(monkeypatch, fresh_probe):
    monkeypatch.setattr("edp_contracts.toolpath.find_tool", lambda *a, **k: None)
    assert model_catalog.codex_windows() == {}
    assert model_catalog.codex_probe() == {"ok": False, "error": "codex is not installed"}
