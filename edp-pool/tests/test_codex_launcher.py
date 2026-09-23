"""CodexSpawner unit surface (s-10a2b1f9ec): env overlay, argv hygiene, modes, routing, lifecycle,
and the main.py wiring guard (EDP_CODEX_ROLES empty ⇒ the spawner stack is untouched)."""

import importlib
import json
import sys
import time

import edp_pool.codex_launcher as cl


def test_env_overlay_is_the_pool_contract_minus_claude(monkeypatch):
    monkeypatch.setenv("EDP8_TOKEN", "sekret")
    monkeypatch.setenv("VIRTUAL_ENV", "/pool/venv")
    monkeypatch.setenv("UV_PROJECT", "x")
    monkeypatch.setenv("EDP_CODEX_BIN", "C:/codex/codex.exe")
    env = cl.build_env_codex("sid-1", "qa", "qa.s-1", "http://127.0.0.1:9300",
                             resume=True, activation="reground and continue", console=True)
    assert env["EDP_HARNESS"] == "codex" and env["EDP_ROLE"] == "qa" and env["EDP_HANDLE"] == "qa.s-1"
    assert env["EDP_SPAWN_SESSION_ID"] == "sid-1" and env["EDP_CODEX_RESUME"] == "1" and env["EDP_CODEX_CONSOLE"] == "1"
    assert env["EDP_ACTIVATION"] == "reground and continue" and env["EDP_CODEX_BIN"] == "C:/codex/codex.exe"
    assert env["EDP_CODEX_MODEL"] == "gpt-6-astra"
    assert "CLAUDE_CONFIG_DIR" not in env and "VIRTUAL_ENV" not in env and "UV_PROJECT" not in env
    env2 = cl.build_env_codex("sid-2", "qa", "qa.s-1", None)
    assert env2["EDP_CODEX_RESUME"] == "0" and env2["EDP_CODEX_CONSOLE"] == "0" and "EDP_ACTIVATION" not in env2


def test_argv_never_carries_the_token(monkeypatch, tmp_path):
    monkeypatch.setenv("EDP8_TOKEN", "sekret-token")
    argv = cl.build_argv_codex(str(tmp_path))
    assert argv[1:] == ["-m", "edp8.codex_seat.run"] and not any("sekret" in a for a in argv)


class _FakeProc:
    pid = 4343

    def poll(self):
        return None


def _capture(monkeypatch):
    seen = {}

    def fake_popen(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return _FakeProc()
    monkeypatch.setattr(cl.subprocess, "Popen", fake_popen)
    return seen


def test_monitor_mode_opens_its_own_console_headless_is_silent(monkeypatch, tmp_path):
    """owner steer m-0259072d19: never headless-only — mode monitor = CREATE_NEW_CONSOLE + console echo."""
    monkeypatch.setenv("EDP8_TOKEN", "sekret-token")
    seen = _capture(monkeypatch)
    sp = cl.CodexSpawner(log_dir=str(tmp_path / "logs"), agent_home=str(tmp_path))
    sp.launch("sid-v", "qa", "qa.v", mode="monitor", extra_env={"EDP8_TOKEN": "per-seat-tok"})
    assert seen["argv"][1:] == ["-m", "edp8.codex_seat.run"]
    assert seen["kw"]["creationflags"] == getattr(cl.subprocess, "CREATE_NEW_CONSOLE", 0)
    assert seen["kw"]["env"]["EDP_CODEX_CONSOLE"] == "1" and seen["kw"]["env"]["EDP8_TOKEN"] == "per-seat-tok"
    assert not any("tok" in a for a in seen["argv"])
    sp.launch("sid-h", "qa", "qa.h", mode="headless")
    assert seen["kw"]["env"]["EDP_CODEX_CONSOLE"] == "0" and seen["kw"]["stdin"] == cl.subprocess.DEVNULL
    assert seen["kw"]["creationflags"] == getattr(cl.subprocess, "CREATE_NO_WINDOW", 0)


def test_model_and_effort_selection(monkeypatch, tmp_path):
    (tmp_path / "models.json").write_text(json.dumps({"seats": {
        "astra-codex": {"model": "gpt-6-astra", "harness": "codex", "thinking": "high", "effort": "medium"},
        "astra": {"model": "openai-codex/gpt-6-astra", "harness": "pi", "thinking": "medium", "effort": "medium"},
        "builder": {"model": "claude-opus-4-8", "effort": "medium"}}, "roles": {}}), encoding="utf-8")
    seen = _capture(monkeypatch)
    sp = cl.CodexSpawner(log_dir=str(tmp_path / "logs"), agent_home=str(tmp_path))
    assert cl.is_codex_model("astra-codex", str(tmp_path)) and cl.is_codex_model("codex/gpt-7", str(tmp_path))
    assert not cl.is_codex_model("astra", str(tmp_path)) and not cl.is_codex_model("builder", str(tmp_path))
    sp.launch("s1", "engineer", "engineer.1", model="astra-codex")
    assert seen["kw"]["env"]["EDP_CODEX_MODEL"] == "gpt-6-astra" and seen["kw"]["env"]["EDP_CODEX_EFFORT"] == "high"
    sp.launch("s2", "engineer", "engineer.2", model="codex/gpt-7", extra_env={"EDP_SEAT_EFFORT": "low"})
    assert seen["kw"]["env"]["EDP_CODEX_MODEL"] == "gpt-7" and seen["kw"]["env"]["EDP_CODEX_EFFORT"] == "low"


def test_lifecycle_with_a_stand_in_process(monkeypatch, tmp_path):
    monkeypatch.setattr(cl, "build_argv_codex", lambda _h: [sys.executable, "-c", "import time; time.sleep(30)"])
    sp = cl.CodexSpawner(log_dir=str(tmp_path / "logs"), agent_home=str(tmp_path))
    sp.launch("sid-x", "qa", "qa.x")
    assert sp.knows("sid-x") and sp.alive("sid-x") and sp.pid("sid-x")
    assert sp.exit_code("sid-x") is None and sp.session_token("sid-x") is None and sp.pins_session_id("sid-x") is False
    assert sp.viewport_died("sid-x") is False and sp.last_output_ts("sid-x") is not None  # the pool log exists
    sp.kill("sid-x")
    for _ in range(50):
        if not sp.alive("sid-x"):
            break
        time.sleep(0.1)
    assert not sp.alive("sid-x") and sp.pid("sid-x") is None and sp.exit_code("sid-x") is not None
    assert not sp.knows("nope")


def test_last_output_ts_ignores_an_earlier_incarnations_writes(monkeypatch, tmp_path):
    """second opinion 20260922T232513Z: the mirror is appended across respawns of one handle."""
    import os
    monkeypatch.setattr(cl, "build_argv_codex", lambda _h: [sys.executable, "-c", "import time; time.sleep(30)"])
    logs = tmp_path / "logs"
    logs.mkdir()
    old = logs / "codex-seat.qa.old.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    sp = cl.CodexSpawner(log_dir=str(logs), agent_home=str(tmp_path))
    sp.launch("sid-o", "qa", "qa.old", extra_env={"EDP_LOG_DIR": str(logs)})
    try:
        ts = sp.last_output_ts("sid-o")
        assert ts is None or ts >= time.time() - 60  # the stale mirror (1 h old) is not this seat's output
    finally:
        sp.kill("sid-o")


def test_closed_session_token_is_the_thread_state_file(tmp_path):
    sp = cl.CodexSpawner(log_dir=str(tmp_path), agent_home=str(tmp_path))
    assert sp.closed_session_token("sid", "qa.1") is None
    (tmp_path / "codex-sessions").mkdir()
    (tmp_path / "codex-sessions" / "qa.1.json").write_text('{"threadId": "t"}', encoding="utf-8")
    assert sp.closed_session_token("sid", "qa.1").endswith("qa.1.json")


def _reload_main(monkeypatch, tmp_path, **env):
    for k in ("EDP_CODEX_ROLES", "EDP_CODEX_BY_MODEL", "EDP_PI_ROLES", "EDP_OPENCODE_ROLES", "EDP_PI_BIN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EDP_POOL_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("EDP_POOL_LOG_DIR", str(tmp_path / "pool-logs"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import edp_pool.main as m
    return importlib.reload(m)


def test_main_wiring_unchanged_when_codex_roles_empty(monkeypatch, tmp_path):
    m = _reload_main(monkeypatch, tmp_path)
    assert not any(type(x).__name__ == "CodexSpawner" for x in _stack(m._spawner))
    m2 = _reload_main(monkeypatch, tmp_path, EDP_CODEX_ROLES="qa")
    codex = [x for x in _stack(m2._spawner) if type(x).__name__ == "CodexSpawner"]
    assert codex and "qa" in m2._spawner._oc_roles


def _stack(sp):
    out, todo = [], [sp]
    while todo:
        x = todo.pop()
        out.append(x)
        todo += [getattr(x, a) for a in ("_claude", "_oc", "_inner") if getattr(x, a, None) is not None]
    return out
