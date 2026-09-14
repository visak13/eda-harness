"""PiSpawner unit surface (epic-6a8a6020fd S2): env overlay, argv hygiene, lifecycle."""

import os
import sys
import time

import edp_pool.pi_launcher as pl


def test_env_overlay_is_the_pool_contract_minus_claude(monkeypatch, tmp_path):
    monkeypatch.setenv("EDP8_TOKEN", "sekret")
    monkeypatch.setenv("VIRTUAL_ENV", "/pool/venv")
    monkeypatch.setenv("UV_PROJECT", "x")
    env = pl.build_env_pi("sid-1", "reviewer", "reviewer.s-1", "http://127.0.0.1:9300",
                          resume=True, activation="reground and continue")
    assert env["EDP_HARNESS"] == "pi" and env["EDP_ROLE"] == "reviewer" and env["EDP_HANDLE"] == "reviewer.s-1"
    assert env["EDP_SPAWN_SESSION_ID"] == "sid-1" and env["EDP_PI_RESUME"] == "1"
    assert env["EDP_ACTIVATION"] == "reground and continue"
    assert "CLAUDE_CONFIG_DIR" not in env and "DISABLE_AUTOUPDATER" not in env
    assert "VIRTUAL_ENV" not in env and "UV_PROJECT" not in env
    env2 = pl.build_env_pi("sid-2", "qa", "qa.s-1", None)
    assert env2["EDP_PI_RESUME"] == "0" and "EDP_ACTIVATION" not in env2


def test_argv_never_carries_the_token(monkeypatch, tmp_path):
    monkeypatch.setenv("EDP8_TOKEN", "sekret-token")
    argv = pl.build_argv_pi(str(tmp_path))
    assert argv[1:] == ["-m", "edp8.pi_seat.run"] and not any("sekret" in a for a in argv)
    monkeypatch.setenv("EDP_PI_SEAT_PYTHON", "C:/x/python.exe")
    assert pl.build_argv_pi(str(tmp_path))[0] == "C:/x/python.exe"


def test_lifecycle_with_a_stand_in_process(monkeypatch, tmp_path):
    # the runner is replaced by a python sleeper so launch/alive/pid/kill/exit_code are exercised for real
    monkeypatch.setattr(pl, "build_argv_pi", lambda _h: [sys.executable, "-c", "import time; time.sleep(30)"])
    sp = pl.PiSpawner(log_dir=str(tmp_path / "logs"), agent_home=str(tmp_path))
    sp.launch("sid-x", "reviewer", "reviewer.x", model="openai/gpt-6-astra")
    assert sp.knows("sid-x") and sp.alive("sid-x") and sp.pid("sid-x")
    assert sp.exit_code("sid-x") is None and sp.session_token("sid-x") is None
    assert sp.viewport_died("sid-x") is False
    sp.kill("sid-x")
    for _ in range(50):
        if not sp.alive("sid-x"):
            break
        time.sleep(0.1)
    assert not sp.alive("sid-x") and sp.pid("sid-x") is None and sp.exit_code("sid-x") is not None
    assert not sp.knows("nope")
