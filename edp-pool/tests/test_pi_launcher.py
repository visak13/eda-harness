import json
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


def test_visible_mode_opens_pi_tui_with_role_card(monkeypatch, tmp_path):
    """owner steer m-0259072d19: the default (monitor) mode is Pi's interactive TUI in its own
    console, extension loaded, role card first, session file for resume — not the headless runner."""
    (tmp_path / ".claude" / "commands").mkdir(parents=True)
    (tmp_path / ".claude" / "commands" / "reviewer.md").write_text("# /reviewer card", encoding="utf-8")
    monkeypatch.setenv("EDP_PI_BIN", "C:/pi/dist/cli.js")
    monkeypatch.setenv("EDP8_TOKEN", "sekret-token")
    seen = {}

    class FakeProc:
        pid = 4242

        def poll(self):
            return None

    def fake_popen(argv, **kw):
        seen["argv"] = argv
        seen["kw"] = kw
        return FakeProc()

    monkeypatch.setattr(pl.subprocess, "Popen", fake_popen)
    sp = pl.PiSpawner(log_dir=str(tmp_path / "logs"), agent_home=str(tmp_path))
    sp.launch("sid-v", "reviewer", "reviewer.v", mode="monitor")
    argv = seen["argv"]
    assert argv[:2] == ["node", "C:/pi/dist/cli.js"] and "-e" in argv and "--session" in argv
    assert argv[-1] == "# /reviewer card" and argv[-2] == "--"
    assert "edp8.pi_seat.run" not in argv and not any("sekret" in a for a in argv)
    assert seen["kw"].get("creationflags") == getattr(pl.subprocess, "CREATE_NEW_CONSOLE", 0)
    assert seen["kw"]["env"]["EDP_PI_MODEL"] == "openai-codex/gpt-6-astra"
    # resume with an existing session file and no activation → no first message (Pi resumes the file)
    sess = tmp_path / "logs" / "pi-sessions" / "reviewer.v.jsonl"
    sess.write_text("{}", encoding="utf-8")
    sp.launch("sid-r", "reviewer", "reviewer.v", mode="monitor", resume_session="x")
    assert "--" not in seen["argv"]
    # headless stays the RPC runner
    sp.launch("sid-h", "reviewer", "reviewer.h", mode="headless")
    assert seen["argv"][1:] == ["-m", "edp8.pi_seat.run"]


def test_openai_column_binds_model_and_thinking_at_the_spawn_seam(monkeypatch, tmp_path):
    """owner m-96cbd61919: every role → gpt-6-astra, thinking medium, from models.json's
    roles_openai column; an explicit openai model per spawn still overrides."""
    import json
    (tmp_path / "models.json").write_text(json.dumps({
        "seats": {"astra": {"model": "openai-codex/gpt-6-astra", "harness": "pi", "thinking": "medium"}},
        "roles": {}, "roles_openai": {"reviewer": "astra"}}), encoding="utf-8")
    monkeypatch.delenv("EDP_PI_MODEL", raising=False)
    monkeypatch.delenv("EDP_PI_THINKING", raising=False)
    monkeypatch.setattr(pl, "build_argv_pi", lambda _h: [sys.executable, "-c", "import time; time.sleep(30)"])
    seen = {}

    class FakeProc:
        pid = 1

        def poll(self):
            return None

    monkeypatch.setattr(pl.subprocess, "Popen", lambda argv, **kw: seen.update(argv=argv, kw=kw) or FakeProc())
    sp = pl.PiSpawner(log_dir=str(tmp_path / "logs"), agent_home=str(tmp_path))
    sp.launch("s1", "reviewer", "reviewer.1", mode="headless")
    assert seen["kw"]["env"]["EDP_PI_MODEL"] == "openai-codex/gpt-6-astra"
    assert seen["kw"]["env"]["EDP_PI_THINKING"] == "medium"
    sp.launch("s2", "reviewer", "reviewer.2", mode="headless", model="openai/gpt-6-astra-fast")
    assert seen["kw"]["env"]["EDP_PI_MODEL"] == "openai/gpt-6-astra-fast"
    sp.launch("s3", "qa", "qa.1", mode="headless")  # unmapped in the openai column → launcher default
    assert seen["kw"]["env"]["EDP_PI_MODEL"] == "openai-codex/gpt-6-astra"


def test_spawn_model_astra_routes_to_the_pi_backend(monkeypatch, tmp_path):
    """owner m-8642d551fc: spawn(role=engineer, model="astra") lands on the GPT backend without EDP_PI_ROLES."""
    from edp_pool.opencode_launcher import CompositeSpawner
    from edp_pool.pi_launcher import is_pi_model
    home = tmp_path / "home"
    home.mkdir()
    (home / "models.json").write_text(json.dumps({
        "seats": {"astra": {"model": "openai-codex/gpt-6-astra", "effort": "medium", "harness": "pi", "thinking": "medium"},
                  "opus": {"model": "claude-opus-5", "effort": "medium"}},
        "roles": {"engineer": "opus"}, "roles_openai": {"engineer": "astra"}}), encoding="utf-8")
    calls = []

    class Fake:
        def __init__(self, name):
            self.name = name

        def launch(self, sid, role, handle, **kw):
            calls.append((self.name, role, kw.get("model"), kw.get("parent"), kw.get("extra_env")))

        def knows(self, sid):
            return False

    comp = CompositeSpawner(Fake("claude"), Fake("pi"), opencode_roles=set(), route_model=lambda m: is_pi_model(m, str(home)))
    comp.launch("s1", "engineer", "engineer.t1", model="astra", parent="architect:abc",
                extra_env={"EDP8_TOKEN": "tok-1"})  # the service passes parent= and extra_env= on every spawn
    comp.launch("s2", "engineer", "engineer.t2", model="openai/gpt-6-astra")
    comp.launch("s3", "engineer", "engineer.t3", model="opus")
    comp.launch("s4", "engineer", "engineer.t4", model=None)
    assert [c[0] for c in calls] == ["pi", "pi", "claude", "claude"]
    assert calls[0][3] == "architect:abc"  # lineage forwarded (the live pool raised TypeError without it)
    assert calls[0][4] == {"EDP8_TOKEN": "tok-1"}  # the seat token reaches the backend (second live TypeError)
    assert is_pi_model("astra", str(home)) and not is_pi_model("opus", str(home)) and not is_pi_model(None, str(home))


def test_launch_merges_the_seat_token_into_env_not_argv(monkeypatch, tmp_path):
    """S20: the service mints EDP8_TOKEN per seat and passes it as extra_env; it must reach the
    child's env (after build_env's *_TOKEN strip) and never its argv."""
    seen = {}

    class FakeProc:
        def poll(self):
            return None

    def fake_popen(argv, **kw):
        seen["argv"], seen["env"] = argv, kw["env"]
        return FakeProc()

    monkeypatch.setattr(pl.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(pl, "build_argv_pi", lambda _h: ["python", "-m", "edp8.pi_seat.run"])
    sp = pl.PiSpawner(log_dir=str(tmp_path / "logs"), agent_home=str(tmp_path))
    sp.launch("sid-t", "engineer", "engineer.t", extra_env={"EDP8_TOKEN": "sekret-seat"}, parent="architect:p")
    assert seen["env"]["EDP8_TOKEN"] == "sekret-seat" and seen["env"]["EDP_PARENT"] == "architect:p"
    assert not any("sekret" in a for a in seen["argv"])


def test_spawn_effort_selects_the_pi_thinking_level(monkeypatch, tmp_path):
    """epic-6a8a6020fd seat-choice (owner m-2d7ef9243d): the epic's effort reaches the Pi seat as
    EDP_SEAT_EFFORT (pool route → extra_env) and becomes the thinking level, beating the seat's
    models.json default (astra thinking=medium) in both headless env and the TUI argv."""
    (tmp_path / "models.json").write_text(json.dumps({
        "seats": {"astra": {"model": "openai-codex/gpt-6-astra", "harness": "pi", "thinking": "medium"}},
        "roles": {}, "roles_openai": {"engineer": "astra"}}), encoding="utf-8")
    monkeypatch.delenv("EDP_PI_MODEL", raising=False)
    monkeypatch.delenv("EDP_PI_THINKING", raising=False)
    monkeypatch.setenv("EDP_PI_BIN", "C:/pi/dist/cli.js")
    monkeypatch.setattr(pl, "build_argv_pi", lambda _h: [sys.executable, "-c", "import time; time.sleep(30)"])
    seen = {}

    class FakeProc:
        pid = 1

        def poll(self):
            return None

    monkeypatch.setattr(pl.subprocess, "Popen", lambda argv, **kw: seen.update(argv=argv, kw=kw) or FakeProc())
    sp = pl.PiSpawner(log_dir=str(tmp_path / "logs"), agent_home=str(tmp_path))
    sp.launch("s1", "engineer", "engineer.1", mode="headless", model="astra",
              extra_env={"EDP8_TOKEN": "tok", "EDP_SEAT_EFFORT": "high"})
    assert seen["kw"]["env"]["EDP_PI_MODEL"] == "openai-codex/gpt-6-astra"
    assert seen["kw"]["env"]["EDP_PI_THINKING"] == "high"
    sp.launch("s2", "engineer", "engineer.2", mode="monitor", model="astra", extra_env={"EDP_SEAT_EFFORT": "low"})
    argv = seen["argv"]
    assert argv[argv.index("--thinking") + 1] == "low"
    sp.launch("s3", "engineer", "engineer.3", mode="headless", model="astra", extra_env={"EDP_SEAT_EFFORT": "xhigh"})
    assert seen["kw"]["env"]["EDP_PI_THINKING"] == "medium"  # junk effort → the seat default stands
    sp.launch("s4", "engineer", "engineer.4", mode="headless", model="astra")
    assert seen["kw"]["env"]["EDP_PI_THINKING"] == "medium"
