"""SUB-1..6 — the testable launch logic (real spawn is manual-HITL #9).

`winpty` is mocked: we assert argv/env/bin-resolution/ready/terminate
WITHOUT a real claude process.
"""

import sys
import types

import pytest

from edp_pool import pty_launcher as pl
from edp_pool.spawner import SubprocessSpawner


# ── phase 5: snapshot/branch CLI flags (proven live 2026-05-22) ───────────
def test_build_session_args_branch_and_pin():
    # fresh, pinned id
    assert pl.build_session_args("fork-1", None) == ["--session-id", "fork-1"]
    # branch a base into a KNOWN fork id (all three flags — the CLI
    # rejects --session-id + --resume without --fork-session)
    assert pl.build_session_args("fork-1", "base-9") == [
        "--resume", "base-9", "--session-id", "fork-1", "--fork-session"
    ]
    # branch with auto id
    assert pl.build_session_args(None, "base-9") == [
        "--resume", "base-9", "--fork-session"
    ]
    # neither = vanilla
    assert pl.build_session_args(None, None) == []


def test_service_threads_branch_flags_to_spawner():
    from edp_pool.service import PoolService
    from edp_pool.spawner import FakeSpawner
    sp = FakeSpawner()
    svc = PoolService(sp)
    svc.spawn("worker", "branch-h", "parent", "headless",
              claude_session="fork-x", resume_session="base-y")
    rec = sp.launched[-1]
    assert rec["claude_session"] == "fork-x"
    assert rec["resume_session"] == "base-y"


# ── SUB-1 bin resolution priority ─────────────────────────────────────────
def test_sub_1_bin_resolution(monkeypatch, tmp_path):
    monkeypatch.delenv("EDP_CLAUDE_BIN", raising=False)
    assert pl.resolve_claude_bin("X:/explicit.exe") == "X:/explicit.exe"
    monkeypatch.setenv("EDP_CLAUDE_BIN", "env.exe")
    assert pl.resolve_claude_bin() == "env.exe"
    monkeypatch.delenv("EDP_CLAUDE_BIN")
    monkeypatch.setattr(pl.shutil, "which", lambda _: None)
    assert pl.resolve_claude_bin() == "claude"
    # .cmd shim → underlying claude.exe if present
    shim = tmp_path / "claude.cmd"
    shim.write_text("@echo")
    exe = (
        tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "bin"
    )
    exe.mkdir(parents=True)
    (exe / "claude.exe").write_text("")
    monkeypatch.setattr(pl.shutil, "which", lambda _: str(shim))
    assert pl.resolve_claude_bin().endswith("claude.exe")


# ── SUB-2 argv / SUB-3 env contract / activation ──────────────────────────
def test_sub_2_argv_skip_permissions_is_opt_in():
    # default: NO bypass — visible shells prompt and the operator approves.
    assert pl.build_argv("c.exe", extra=["--x"]) == ["c.exe", "--x"]
    # opt-in (required for headless): the bypass flag goes first.
    assert pl.build_argv("c.exe", extra=["--x"], skip_permissions=True) == [
        "c.exe", "--dangerously-skip-permissions", "--x"]


def test_sub_3_env_contract():
    e = pl.build_env("sid", "worker", "p:a1", "http://b:9100")
    assert e["EDP_SPAWN_SESSION_ID"] == "sid"
    assert e["EDP_ROLE"] == "worker"
    assert e["EDP_HANDLE"] == "p:a1"
    assert e["EDP_BROKER_URL"] == "http://b:9100"


def test_sub_3b_build_env_pins_whole_stack(monkeypatch):
    # 2026-05-28 wiring fix: a clone's pool must pin the spawned shell's
    # ENTIRE stack (pool/agent_home/log_dir), not inherit strays. Set
    # stray eda-base values in the parent env and confirm build_env
    # OVERRIDES them with the explicit pool-stack values.
    monkeypatch.setenv("EDP_POOL_URL", "http://127.0.0.1:9200")     # stray old
    monkeypatch.setenv("EDP_AGENT_HOME", "C:/Projects/Learning/eda-base/claude")
    monkeypatch.setenv("EDP_LOG_DIR", "C:/Projects/Learning/eda-base/.logs")
    e = pl.build_env(
        "sid", "curiosity", "curiosity-x", "http://127.0.0.1:9300",
        pool_url="http://127.0.0.1:9301",
        agent_home="C:/Projects/Learning/eda-base3/claude",
        log_dir="C:/Projects/Learning/eda-base3/.logs",
    )
    assert e["EDP_BROKER_URL"] == "http://127.0.0.1:9300"
    assert e["EDP_POOL_URL"] == "http://127.0.0.1:9301"     # overrode stray
    assert e["EDP_AGENT_HOME"].endswith("eda-base3\\claude") \
        or e["EDP_AGENT_HOME"].endswith("eda-base3/claude")
    assert "eda-base3" in e["EDP_LOG_DIR"]


def test_main_self_locates_sibling_claude_repo():
    # The pool computes agent_home/log_dir from its OWN path (parents[3]),
    # so a clone is self-consistent regardless of the launching shell.
    from pathlib import Path

    import edp_pool.main as m
    root = Path(m.__file__).resolve().parents[3]
    assert m._agent_home == str(root / "claude")
    assert m._shell_log_dir == str(root / ".logs")
    assert m._pool_url.startswith("http://127.0.0.1:")


def test_activation_text_role_maps_to_real_command():
    # The bug: pool role "planner" must activate /agentic-plan, NOT
    # /planner (no such command → shell idled → neuron deadlocked).
    assert pl.activation_text("planner") == "/agentic-plan"
    assert pl.activation_text("worker") == "/worker"
    assert pl.activation_text("neuron") == "/neuron"
    # unknown role: loud fallback (fails as "Unknown command", not silent)
    assert pl.activation_text("frobnicate") == "/frobnicate"


# ── OTel for spawned shells (2026-05-31) ──────────────────────────────────
def test_recipe_id_from_handle():
    # planner handle: <recipe_id>:<step_id>
    assert pl._recipe_id_from_handle("recipe-evolve-8d5805:s3") \
        == "recipe-evolve-8d5805"
    # worker handle: <plan_id>:<action_id>, plan_id = <recipe_id>-<step_id>
    assert pl._recipe_id_from_handle("recipe-evolve-8d5805-s3:a1_author") \
        == "recipe-evolve-8d5805"
    # non-recipe handle passes through
    assert pl._recipe_id_from_handle("curiosity-abc123") == "curiosity-abc123"


def test_build_env_otel_on_by_default(monkeypatch):
    # default ON: every shell gets telemetry + per-shell resource attrs.
    monkeypatch.delenv("EDP_SHELL_OTEL", raising=False)
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
    env = pl.build_env("worker:u1", "worker",
                       "recipe-x-8d5805-s3:a1", "http://b:9300")
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert env["CLAUDE_CODE_ENHANCED_TELEMETRY_BETA"] == "1"
    assert env["OTEL_TRACES_EXPORTER"] == "otlp"
    assert env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"].endswith(":6006/v1/traces")
    ra = env["OTEL_RESOURCE_ATTRIBUTES"]
    assert "openinference.project.name=edp-shells" in ra   # dedicated project
    assert "edp.role=worker" in ra
    assert "edp.recipe_id=recipe-x-8d5805" in ra
    assert "edp.handle=recipe-x-8d5805-s3_a1" in ra      # ':' sanitized


def test_build_env_otel_respects_override_and_toggle(monkeypatch):
    # d10 env-robustness: build_env does os.environ.copy(), so a spawned
    # shell that INHERITS the OTel toggle would leak CLAUDE_CODE_ENABLE_
    # TELEMETRY into the toggle-OFF result and falsify the assertion below.
    # Clear the inherited OTel vars this test's assertions depend on — never
    # rely on ambient state (same convention as test_build_env_rtk_gating).
    monkeypatch.delenv("CLAUDE_CODE_ENABLE_TELEMETRY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENHANCED_TELEMETRY_BETA", raising=False)
    # operator override of the endpoint wins
    monkeypatch.setenv("EDP_SHELL_OTEL", "1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                       "http://collector:4318/v1/traces")
    env = pl.build_env("planner:u1", "planner", "recipe-x-8d5805:s3",
                       "http://b:9300")
    assert env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] == \
        "http://collector:4318/v1/traces"
    # toggle OFF: no telemetry vars added
    monkeypatch.setenv("EDP_SHELL_OTEL", "0")
    env2 = pl.build_env("planner:u2", "planner", "recipe-x-8d5805:s3",
                        "http://b:9300")
    assert "CLAUDE_CODE_ENABLE_TELEMETRY" not in env2


# ── W6.1: EDP_RTK gated wiring (default OFF) ──────────────────────────────
def test_build_env_rtk_gating(monkeypatch):
    # W6.1 gated-wiring half: build_env stamps EDP_RTK from the pool's own
    # env/config surface, DEFAULT OFF, so a later on-flip reaches fresh
    # spawns with no code change. Env-robust per d7/d8: this suite runs both
    # in a bare foreground shell AND inside a spawned shell that inherits
    # EDP_* vars, so pin every var this assertion depends on — never rely on
    # ambient state and never use an `env` prefix.
    monkeypatch.delenv("EDP_RTK", raising=False)
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.delenv("EDP_SHELL_OTEL", raising=False)

    # default OFF: nothing stamped — a spawn is byte-identical to today.
    off = pl.build_env("sid", "worker", "recipe-x-8d5805-s3:a1",
                       "http://b:9300")
    assert off.get("EDP_RTK") in (None, "0")

    # explicit-off in the pool env normalizes to unset (still byte-identical).
    monkeypatch.setenv("EDP_RTK", "0")
    off2 = pl.build_env("sid", "worker", "recipe-x-8d5805-s3:a1",
                        "http://b:9300")
    assert off2.get("EDP_RTK") in (None, "0")

    # ON when the config/pool env requests it — reaches the fresh spawn with
    # no code change.
    monkeypatch.setenv("EDP_RTK", "1")
    on = pl.build_env("sid", "worker", "recipe-x-8d5805-s3:a1",
                      "http://b:9300")
    assert on["EDP_RTK"] == "1"

    # a truthy word (not just "1") also enables — value is normalized to "1".
    monkeypatch.setenv("EDP_RTK", "true")
    on2 = pl.build_env("sid", "worker", "recipe-x-8d5805-s3:a1",
                       "http://b:9300")
    assert on2["EDP_RTK"] == "1"


# ── fake winpty so PtyLaunch.spawn works headless ─────────────────────────
class _FakeProc:
    def __init__(self):
        self._alive = True
        self._reads = ["booting...\n", "ready ❯ \n"]
        self.written: list[str] = []

    def read(self, _n):
        return self._reads.pop(0) if self._reads else ""

    def isalive(self):
        return self._alive

    def write(self, s):
        self.written.append(s)

    def terminate(self, force=False):
        self._alive = False


@pytest.fixture
def fake_winpty(monkeypatch):
    proc = _FakeProc()
    mod = types.ModuleType("winpty")
    mod.PtyProcess = types.SimpleNamespace(spawn=lambda *a, **k: proc)
    monkeypatch.setitem(sys.modules, "winpty", mod)
    return proc


# ── SUB-4 ready detection / SUB-5 alive+kill ──────────────────────────────
def test_sub_4_ready_on_prompt_then_activation(fake_winpty):
    lp = pl.PtyLaunch(
        argv=["c"], env={}, cwd=".", ready_timeout=5.0
    )
    lp.spawn()
    assert lp.wait_ready() is True  # `❯` seen in drained output
    lp.send_activation("/worker")
    assert fake_winpty.written[:1] == ["/worker"]
    assert fake_winpty.written[-1] == "\r"  # submit


def test_sub_4b_ready_timeout_clean(monkeypatch):
    proc = _FakeProc()
    proc._reads = ["no prompt here\n"]
    mod = types.ModuleType("winpty")
    mod.PtyProcess = types.SimpleNamespace(spawn=lambda *a, **k: proc)
    monkeypatch.setitem(sys.modules, "winpty", mod)
    lp = pl.PtyLaunch(argv=["c"], env={}, ready_timeout=0.2)
    lp.spawn()
    assert lp.wait_ready() is False  # timed out, no exception
    lp.terminate()


def _fake_winpty_with_reads(monkeypatch, reads):
    proc = _FakeProc()
    proc._reads = list(reads)
    mod = types.ModuleType("winpty")
    mod.PtyProcess = types.SimpleNamespace(spawn=lambda *a, **k: proc)
    monkeypatch.setitem(sys.modules, "winpty", mod)
    return proc


def test_sub_4c_ready_on_v2_hint_line(monkeypatch):
    """DESIGN-v7 fix C (verified live): Claude Code v2.1.207's fullscreen
    TUI renders '>' not '❯', so the old single-glyph marker timed out on
    every healthy shell. The v2 boot screen's input-hint line is a marker."""
    _fake_winpty_with_reads(monkeypatch,
                            ["booting...\n", "? for shortcuts · "
                             "shift+tab to cycle modes\n"])
    lp = pl.PtyLaunch(argv=["c"], env={}, cwd=".", ready_timeout=5.0)
    lp.spawn()
    try:
        assert lp.wait_ready() is True
    finally:
        lp.terminate()   # stop the drain thread — a leaked one slows the suite


def test_sub_4d_ready_on_v2_try_placeholder(monkeypatch):
    _fake_winpty_with_reads(monkeypatch,
                            ['> Try "fix lint errors" \n'])
    lp = pl.PtyLaunch(argv=["c"], env={}, cwd=".", ready_timeout=5.0)
    lp.spawn()
    try:
        assert lp.wait_ready() is True
    finally:
        lp.terminate()


def test_sub_4e_marker_split_across_pty_reads(monkeypatch):
    """A multi-char marker can straddle a read boundary; the drain matches
    against a rolling tail, never a single chunk."""
    _fake_winpty_with_reads(monkeypatch,
                            ["... shift+tab t", "o cycle modes\n"])
    lp = pl.PtyLaunch(argv=["c"], env={}, cwd=".", ready_timeout=5.0)
    lp.spawn()
    try:
        assert lp.wait_ready() is True
    finally:
        lp.terminate()


def test_sub_4f_bypass_dialog_detected_not_answered(monkeypatch):
    """A fresh CLAUDE_CONFIG_DIR shows the Bypass Permissions acceptance
    dialog BEFORE the TUI. The pool must DETECT it (so a ready-timeout can
    name the cause) and must NOT auto-accept it — nothing is written."""
    proc = _fake_winpty_with_reads(monkeypatch, [
        "WARNING: Bypass Permissions mode\n",
        "  1. No, exit    2. Yes, I accept\n",
    ])
    lp = pl.PtyLaunch(argv=["c"], env={}, cwd=".", ready_timeout=0.3)
    lp.spawn()
    try:
        assert lp.wait_ready() is False      # the dialog is not readiness
        assert lp.bypass_dialog_seen is True
        assert proc.written == [], "the pool must never answer the dialog"
    finally:
        lp.terminate()


def test_sub_4g_spawner_logs_ready_timeout_with_bypass_hint(
        monkeypatch, caplog, tmp_path):
    """On ready-timeout the spawner's error names the drain log AND whether
    the bypass acceptance dialog is what the shell is stuck on."""
    import logging as _logging

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("EDP_READY_TIMEOUT_SECS", "0.2")
    _fake_winpty_with_reads(monkeypatch, [
        "Bypass Permissions mode — Yes, I accept?\n"])
    sp = SubprocessSpawner(log_dir=tmp_path)
    with caplog.at_level(_logging.ERROR, logger="edp_pool.spawner"):
        sp.launch("worker:rt1", "worker", "p:a1")
    msg = "\n".join(r.getMessage() for r in caplog.records)
    assert "ready-timeout" in msg
    assert "Bypass Permissions" in msg
    sp.kill("worker:rt1")


def test_sub_5_alive_and_kill(fake_winpty):
    lp = pl.PtyLaunch(argv=["c"], env={}, ready_timeout=2.0)
    lp.spawn()
    lp.wait_ready()
    assert lp.is_alive() is True
    lp.terminate()
    assert lp.is_alive() is False


# ── SUB-6 SubprocessSpawner platform guard + Windows delegate ─────────────
def test_sub_6_non_windows_clear_error(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="ConPTY"):
        SubprocessSpawner().launch("sid", "worker", "p:a1")


def test_sub_6b_windows_delegates(monkeypatch, fake_winpty):
    monkeypatch.setattr(sys, "platform", "win32")
    sp = SubprocessSpawner(broker_url="http://b:9100")
    sp.launch("sid", "worker", "p:a1")
    assert sp.alive("sid") is True
    sp.kill("sid")
    assert sp.alive("sid") is False


def test_sub_cwd_defaults_to_agent_home(monkeypatch):
    monkeypatch.setenv("EDP_AGENT_HOME", r"C:\agent\home")
    assert SubprocessSpawner().cwd == r"C:\agent\home"
    assert SubprocessSpawner(cwd="explicit").cwd == "explicit"


class _FakeConsoleProc:
    def __init__(self):
        self._returncode = None
        self.pid = 7777

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = 0


def _patch_console(monkeypatch):
    import edp_pool.console_launcher as clmod
    captured = {}

    def _fake_popen(argv, cwd=None, env=None, creationflags=0):
        captured.update(argv=argv, cwd=cwd, env=env, flags=creationflags)
        return _FakeConsoleProc()

    monkeypatch.setattr(clmod.subprocess, "Popen", _fake_popen)
    return captured, clmod


def test_con_1_monitor_uses_visible_console_and_PROMPTS(monkeypatch):
    """CON-1 (2026-05-31) — monitor mode spawns a real VISIBLE console
    (Popen + CREATE_NEW_CONSOLE), argv carries the role activation as the
    initial prompt, and by DEFAULT does NOT add --dangerously-skip-
    permissions — the operator click-approves in the window."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("EDP_SKIP_PERMISSIONS", raising=False)
    captured, clmod = _patch_console(monkeypatch)
    sp = SubprocessSpawner(
        broker_url="http://b:9100", cwd=r"C:\agent\home",
        claude_bin="claude.exe",
    )
    sp.launch("worker:c1", "worker", "p:a1", mode="monitor")

    assert captured["argv"] == ["claude.exe", "/worker"]   # no bypass flag
    assert captured["cwd"] == r"C:\agent\home"
    assert captured["env"]["EDP_HANDLE"] == "p:a1"
    assert captured["flags"] == getattr(
        clmod.subprocess, "CREATE_NEW_CONSOLE", 0)
    assert sp.alive("worker:c1") is True
    assert sp.pid("worker:c1") == 7777          # for the liveness fingerprint


def test_con_1b_monitor_opt_in_autonomy(monkeypatch):
    # EDP_SKIP_PERMISSIONS=1 → monitor shell runs autonomously (bypass).
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("EDP_SKIP_PERMISSIONS", "1")
    captured, _ = _patch_console(monkeypatch)
    SubprocessSpawner(claude_bin="claude.exe").launch(
        "worker:c1b", "worker", "p:a1", mode="monitor")
    assert captured["argv"] == [
        "claude.exe", "--dangerously-skip-permissions", "/worker"]


def test_con_2_monitor_alive_and_terminate(monkeypatch):
    """CON-2 — alive via poll(); terminate stops the visible console."""
    monkeypatch.setattr(sys, "platform", "win32")
    import edp_pool.console_launcher as clmod

    monkeypatch.setattr(
        clmod.subprocess, "Popen", lambda *a, **k: _FakeConsoleProc())
    sp = SubprocessSpawner()
    sp.launch("worker:c2", "worker", "p:a2", mode="monitor")
    assert sp.alive("worker:c2") is True
    sp.kill("worker:c2")
    assert sp.alive("worker:c2") is False


def test_con_3_headless_uses_pty_with_drain_log(monkeypatch, fake_winpty,
                                                tmp_path):
    """CON-3 — headless (default) goes through PtyLaunch: readiness-gated
    activation + a per-session forensic drain log."""
    monkeypatch.setattr(sys, "platform", "win32")
    sp = SubprocessSpawner(log_dir=tmp_path)
    sp.launch("worker:h1", "worker", "p:a1")    # default headless
    import time

    time.sleep(0.2)
    assert fake_winpty.written[:1] == ["/worker"]   # activation after ready
    sp.kill("worker:h1")
    assert (tmp_path / "worker_h1.log").exists()    # PTY drain happened


def test_sub_8_drain_log_has_utf8_bom(monkeypatch, fake_winpty, tmp_path):
    """Drain log must start with a UTF-8 BOM so PowerShell 5.1
    Get-Content renders box-drawing instead of mojibake."""
    import time

    monkeypatch.setattr(sys, "platform", "win32")
    sp = SubprocessSpawner(log_dir=tmp_path)
    sp.launch("worker:bom1", "worker", "p:a1")
    time.sleep(0.3)  # let the drain thread flush
    sp.kill("worker:bom1")
    log = tmp_path / "worker_bom1.log"
    assert log.exists()
    assert log.read_bytes()[:3] == b"\xef\xbb\xbf"


def test_sub_7_log_filename_sanitized(monkeypatch, fake_winpty, tmp_path):
    """':' in session_id must not become an NTFS ADS / illegal filename."""
    captured = {}
    import edp_pool.pty_launcher as plmod

    real = plmod.PtyLaunch

    def _spy(*a, **k):
        captured["log_path"] = k.get("log_path")
        return real(*a, **k)

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(plmod, "PtyLaunch", _spy)
    sp = SubprocessSpawner(log_dir=tmp_path)
    sp.launch("worker:42da278e-ab11", "worker", "p:a1")
    name = captured["log_path"].name
    assert ":" not in name
    assert name == "worker_42da278e-ab11.log"
