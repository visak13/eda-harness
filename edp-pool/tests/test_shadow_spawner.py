"""ShadowSpawner integration seams (WS7) — no real shells: monkeypatched
PtyLaunch/driver, real plan-JSON reads, real Spawner-ABC surface."""

import json

import pytest

from edp_pool.shadow_spawner import (
    ROLE_SPECS,
    ShadowSpawner,
    parent_of,
    shadow_enabled,
)
from edp_pool.spawner import SubprocessSpawner


def test_parent_addressing():
    assert parent_of("plan-x-s2:a3") == "plan-x-s2"
    assert parent_of("recipe-y:s4") == "recipe-y"
    assert parent_of("curiosity-abc") == "curiosity-abc"


def test_shadow_flag(monkeypatch):
    monkeypatch.delenv("EDP_SHADOW", raising=False)
    assert shadow_enabled()
    monkeypatch.setenv("EDP_SHADOW", "0")
    assert not shadow_enabled()


def test_role_specs_cover_every_pool_role():
    # ("consult" left this list 2026-08-12 — its ROLE_SPECS/ROLE_HEARTBEAT_S
    # rows were deleted with the retired consult shell role.)
    for role in ("worker", "planner", "reviewer", "specialist", "curiosity"):
        assert role in ROLE_SPECS
    assert "consult" not in ROLE_SPECS


@pytest.fixture
def sp(tmp_path):
    legacy = SubprocessSpawner(broker_url=None, cwd=str(tmp_path),
                               log_dir=tmp_path / "logs", pool_url=None)
    return ShadowSpawner(legacy, shadow_dir=tmp_path / ".shadows")


def _write_plan(tmp_path, plan_id="plan-x-s2", status="in_progress"):
    (tmp_path / ".plans").mkdir(exist_ok=True)
    (tmp_path / ".plans" / f"{plan_id}.json").write_text(json.dumps({
        "plan_id": plan_id,
        "actions": [{"action_id": "a3", "status": status,
                     "description": "build the CSV export",
                     "acceptance": {"expected": "rows land"},
                     "serves": ["o1"], "concerns": ["errors"],
                     "injected_context": {"decisions": ["d12 — digest"]}}],
    }), encoding="utf-8")


def test_brief_composed_from_own_action_record(sp, tmp_path):
    _write_plan(tmp_path)
    brief = sp._compose_brief("worker", "plan-x-s2:a3")
    assert "build the CSV export" in brief
    assert "acceptance: rows land" in brief
    assert "d12" in brief and "serves: ['o1']" in brief
    assert sp._compose_brief("worker", "plan-x-s2:zz") == ""
    assert sp._compose_brief("planner", "recipe-y:s2") == ""


def test_terminal_check_reads_action_status(sp, tmp_path):
    _write_plan(tmp_path, status="in_progress")
    check = sp._terminal_check("worker", "plan-x-s2:a3")
    assert check() is False
    _write_plan(tmp_path, status="done")
    assert check() is True
    # planner: terminal_status on the plan JSON
    (tmp_path / ".plans" / "recipe-y-s2.json").write_text(
        json.dumps({"plan_id": "recipe-y-s2",
                    "terminal_status": "succeeded"}), encoding="utf-8")
    assert sp._terminal_check("planner", "recipe-y:s2")() is True
    # advisory roles: never observed-terminal (they self-close on clear)
    assert sp._terminal_check("curiosity", "curiosity-1")() is False


def test_disabled_flag_delegates_to_legacy_both_modes(sp, monkeypatch):
    calls = []
    monkeypatch.setattr(sp.legacy, "launch",
                        lambda *a, **k: calls.append((a, k)))
    monkeypatch.setenv("EDP_SHADOW", "0")
    sp.launch("s1", "worker", "p:a", mode="monitor")
    sp.launch("s2", "worker", "p:a", mode="headless")
    assert len(calls) == 2


def test_monitor_launch_builds_console_shadow(sp, tmp_path, monkeypatch):
    """Monitor spawns are SHADOWED (2026-08-06 ruling): first line rides
    argv as claude's initial prompt; wakes go via console injection."""
    _write_plan(tmp_path)
    captured = {}

    class FakeConsole:
        def __init__(self, argv, env, cwd):
            captured["argv"] = argv
            captured["env"] = env
            self._alive = False
            self.pid = 777

        def spawn(self):
            self._alive = True

        def is_alive(self):
            return self._alive

        def terminate(self):
            self._alive = False

    injected = []
    import edp_pool.console_input as ci
    import edp_pool.console_launcher as cl
    import edp_pool.shadow_spawner as mod
    monkeypatch.setattr(cl, "ConsoleLaunch", FakeConsole)
    monkeypatch.setattr(ci, "inject_line",
                        lambda pid, text: injected.append((pid, text)))
    monkeypatch.setattr(
        "edp_pool.pty_launcher.resolve_claude_bin", lambda b: "claude.exe")
    monkeypatch.setattr(
        "edp_pool.pty_launcher.ensure_claude_healthy", lambda b: b)
    monkeypatch.setattr(mod.ShadowSpawner, "_agent_python",
                        lambda self: "python.exe")
    monkeypatch.setattr(
        mod, "_RxDriverAdapter",
        lambda **kw: type("D", (), {"start": lambda s: None,
                                    "stop": lambda s: None,
                                    "is_alive": lambda s: True})())
    monkeypatch.delenv("EDP_SHADOW", raising=False)

    sp.launch("worker:mon", "worker", "plan-x-s2:a3", mode="monitor")

    sh = sp._shadows["worker:mon"]
    sh.stop()
    # nonced env + shadow dir stamped, exactly like headless
    assert captured["env"]["EDP_SHADOW_NONCE"] == sh.cfg.nonce
    # first line rides argv (initial prompt), NOT send_line
    first = captured["argv"][-1]
    assert first.startswith("/worker")
    assert "build the CSV export" in first
    assert f":{sh.cfg.nonce}]" in first
    assert injected == []          # no injection at spawn time
    # a later wake IS injected into the console by pid
    sh._on_event({"kind": "mail", "body": {"x": 1}})
    assert injected and injected[0][0] == 777
    assert "mail:" in injected[0][1]
    # Spawner surface truthful for the console route
    assert sp.alive("worker:mon") and sp.pid("worker:mon") == 777
    assert sp.last_output_ts("worker:mon") is None   # no drain log
    sp.kill("worker:mon")
    assert not sp.alive("worker:mon")


def test_headless_launch_builds_shadow_with_nonced_env(
        sp, tmp_path, monkeypatch):
    _write_plan(tmp_path)
    captured = {}

    class FakePty:
        def __init__(self, argv, env, cwd, log_path):
            captured["env"] = env
            captured["argv"] = argv
            self.log_path = log_path
            self._alive = False
            self.sent = []
            self.pid = 4242

        def spawn(self):
            self._alive = True

        def wait_ready(self):
            return True

        def send_activation(self, text):
            self.sent.append(text)

        def is_alive(self):
            return self._alive

        def terminate(self):
            self._alive = False

    import edp_pool.shadow_spawner as mod
    monkeypatch.setattr(
        "edp_pool.pty_launcher.PtyLaunch", FakePty)
    monkeypatch.setattr(
        "edp_pool.pty_launcher.resolve_claude_bin", lambda b: "claude.exe")
    monkeypatch.setattr(
        "edp_pool.pty_launcher.ensure_claude_healthy", lambda b: b)
    # no driver subprocess in tests
    monkeypatch.setattr(mod.ShadowSpawner, "_agent_python",
                        lambda self: "python.exe")
    monkeypatch.setattr(
        mod, "_RxDriverAdapter",
        lambda **kw: type("D", (), {"start": lambda s: None,
                                    "stop": lambda s: None,
                                    "is_alive": lambda s: True})())
    monkeypatch.delenv("EDP_SHADOW", raising=False)

    sp.launch("worker:abc", "worker", "plan-x-s2:a3", mode="headless")

    sh = sp._shadows["worker:abc"]
    sh.stop()
    env = captured["env"]
    assert env["EDP_SHADOW_NONCE"] == sh.cfg.nonce
    assert env["EDP_SHADOW_DIR"] == str(sp.shadow_dir)
    first = sh.shell.launch.sent[0]
    assert first.startswith("/worker")
    assert "build the CSV export" in first          # brief injected
    assert f":{sh.cfg.nonce}]" in first             # provenance frame
    # Spawner surface truthful
    assert sp.alive("worker:abc") and sp.knows("worker:abc")
    assert sp.pid("worker:abc") == 4242
    ledger = json.loads(
        (sp.shadow_dir / "plan-x-s2_a3.json").read_text("utf-8"))
    assert ledger["role"] == "worker" and ledger["shell"]["state"] == "ready"
    sp.kill("worker:abc")
    assert not sp.alive("worker:abc")
