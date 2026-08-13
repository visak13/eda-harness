"""ShellShadow unit tests (WS7, SHADOW.md) — fakes only, no real shell."""

import json
import time

from edp_pool.shadow import ShadowConfig, ShellShadow, safe_name


class FakeShell:
    def __init__(self):
        self.lines: list[str] = []
        self._alive = False

    def spawn(self):
        self._alive = True

    def wait_ready(self):
        return True

    def send_line(self, line):
        self.lines.append(line)

    def is_alive(self):
        return self._alive

    def terminate(self):
        self._alive = False


class FakeDriver:
    def __init__(self, on_event):
        self.on_event = on_event
        self._alive = False

    def start(self):
        self._alive = True

    def stop(self):
        self._alive = False

    def is_alive(self):
        return self._alive

    def emit(self, event):
        self.on_event(event)


def _mk(tmp_path, **over):
    cfg = ShadowConfig(handle="plan-x:a3", role="worker",
                       ledger_dir=tmp_path / ".shadows",
                       spec="rx.broker(me)", brief="do action a3",
                       activation="/worker", heartbeat_s=9999,
                       **over)
    shell = FakeShell()
    drivers: list[FakeDriver] = []

    def driver_factory(on_event):
        d = FakeDriver(on_event)
        drivers.append(d)
        return d

    published: list[tuple] = []
    released: list[bool] = []
    sh = ShellShadow(
        cfg, shell_factory=lambda: shell, driver_factory=driver_factory,
        terminal_check=lambda: False,
        publish=lambda k, b: published.append((k, b)),
        release=lambda: released.append(True))
    return sh, shell, drivers, published, released


def test_spawn_types_activation_brief_and_nonced_wiring_line(tmp_path):
    sh, shell, drivers, published, _ = _mk(tmp_path)
    sh.start(run_loop=False)
    sh.stop()
    first = shell.lines[0]
    assert first.startswith("/worker")
    assert "YOUR BRIEF" in first and "do action a3" in first
    assert f":{sh.cfg.nonce} " in first and "wiring live" in first
    assert ("ready", {"handle": "plan-x:a3", "inbox": "plan-x:a3"}) in published
    ledger = json.loads(
        (tmp_path / ".shadows" / f"{safe_name('plan-x:a3')}.json")
        .read_text("utf-8"))
    assert ledger["shell"]["state"] == "ready"
    assert ledger["driver"]["alive"] is False   # stop() shut it down


def test_wakes_are_framed_sequenced_and_sensory_only(tmp_path):
    sh, shell, drivers, _, _ = _mk(tmp_path)
    sh.start(run_loop=False)
    drivers[0].emit({"kind": "mail", "body": {"from": "planner", "q": 1}})
    # WP3 (2026-08-12): broker kinds pass through with their REAL names now
    # (`steer` used to degrade to a contentless "mail" — the empty-tick
    # defect); a kind outside the grammar still degrades.
    drivers[0].emit({"kind": "steer", "body": {}})
    drivers[0].emit({"kind": "made-up-kind", "body": {}})   # unknown → mail
    sh.stop()
    w1, w2, w3 = shell.lines[1], shell.lines[2], shell.lines[3]
    # P3 (2026-08-13): the frame names itself machine sense data — console
    # wakes render exactly like typed user messages otherwise.
    mark = "| sense, not operator]"
    assert w1.startswith(f"[shadow plan-x:a3 #1 :{sh.cfg.nonce} {mark} mail:")
    assert w2.startswith(f"[shadow plan-x:a3 #2 :{sh.cfg.nonce} {mark} steer:")
    assert w3.startswith(f"[shadow plan-x:a3 #3 :{sh.cfg.nonce} {mark} mail:")
    ledger = json.loads(
        (sh.cfg.ledger_dir / f"{safe_name('plan-x:a3')}.json").read_text())
    assert ledger["wakes_seq"] == 3
    assert all(w["delivered"] for w in ledger["wakes"])


class DeferringShell(FakeShell):
    """send_line returns False (delivery deferred/failed) until unblocked —
    the console adapter's behavior while the operator is typing (P4)."""

    def __init__(self):
        super().__init__()
        self.blocked = True

    def send_line(self, line):
        if self.blocked:
            return False
        self.lines.append(line)
        return True


def test_deferred_wake_is_requeued_and_redelivered_on_tick(tmp_path):
    """P4 (2026-08-13 live repro): wake lines spliced INTO the operator's
    half-typed steer, truncating it mid-word. The console helper now defers
    while the operator types; the shadow must (1) record the wake as NOT
    delivered, (2) keep the frame, (3) re-deliver in order on a later tick
    once the console is free — never silently drop mail."""
    cfg = ShadowConfig(handle="plan-x:a3", role="worker",
                       ledger_dir=tmp_path / ".shadows",
                       spec="rx.broker(me)", brief="do action a3",
                       activation="/worker", heartbeat_s=9999)
    shell = DeferringShell()
    shell.blocked = False          # activation line goes through
    drivers = []

    def driver_factory(on_event):
        d = FakeDriver(on_event)
        drivers.append(d)
        return d

    sh = ShellShadow(cfg, shell_factory=lambda: shell,
                     driver_factory=driver_factory,
                     terminal_check=lambda: False)
    sh.start(run_loop=False)
    shell.blocked = True           # operator starts typing
    drivers[0].emit({"kind": "mail", "body": {"n": 1}})
    drivers[0].emit({"kind": "steer", "body": {"n": 2}})
    ledger = json.loads(
        (cfg.ledger_dir / f"{safe_name('plan-x:a3')}.json").read_text())
    assert [w["delivered"] for w in ledger["wakes"]] == [False, False]
    assert ledger["wakes_pending"] == 2
    assert len(shell.lines) == 1   # nothing spliced into the operator's input

    sh._tick()                     # console still busy → still queued
    assert len(shell.lines) == 1

    shell.blocked = False          # operator done
    sh._tick()
    sh.stop()
    assert [ln for ln in shell.lines[1:] if "#1 " in ln], shell.lines
    assert "mail:" in shell.lines[1] and "steer:" in shell.lines[2], (
        "redelivery must preserve order")
    ledger = json.loads(
        (cfg.ledger_dir / f"{safe_name('plan-x:a3')}.json").read_text())
    assert ledger["wakes_pending"] == 0


def test_broker_done_event_survives_the_unwrap_with_its_kind(tmp_path):
    """WP3 regression pin: a driver-envelope `{"event": {done…}}` NDJSON line
    reaches the shell as a `done:` wake carrying the body — never as `mail:`
    with the stringified wrapper (the df971d empty-tick defect)."""
    import io
    import subprocess as sp
    from unittest.mock import patch

    from edp_pool.shadow_spawner import _RxDriverAdapter

    seen = []
    ad = _RxDriverAdapter(
        python="py", agent_home=str(tmp_path), broker_url="", pool_url="",
        spec="rx.broker(me)", bindings={}, spec_dir=tmp_path / "specs",
        name="t", on_event=seen.append, owner="plan-x:a3")
    assert "--owner" in ad._argv and "plan-x:a3" in ad._argv

    lines = [
        json.dumps({"event": {"kind": "done", "from": "plan-x:a3",
                              "body": {"action_id": "a3", "status": "done"}}}),
        json.dumps({"error": "boom"}),
    ]
    fake = type("P", (), {"stdout": io.StringIO("\n".join(lines) + "\n")})()
    with patch.object(ad, "_proc", fake):
        ad._pump()
    assert seen[0]["kind"] == "done"
    assert seen[0]["body"] == {"action_id": "a3", "status": "done"}
    assert seen[1]["kind"] == "alert" and seen[1]["body"] == {"error": "boom"}


def test_dead_driver_rearmed_and_counted(tmp_path):
    sh, shell, drivers, _, _ = _mk(tmp_path)
    sh.start(run_loop=False)
    drivers[0]._alive = False          # simulate driver death
    sh._tick()
    assert len(drivers) == 2 and drivers[1].is_alive()
    ledger = json.loads(
        (sh.cfg.ledger_dir / f"{safe_name('plan-x:a3')}.json").read_text())
    assert ledger["driver"]["restarts"] == 1
    sh.stop()


def test_observed_terminal_closes_and_releases(tmp_path):
    sh, shell, drivers, _, released = _mk(tmp_path)
    terminal = {"v": False}
    sh._terminal_check = lambda: terminal["v"]
    sh.start(run_loop=False)
    sh._tick()
    assert not released
    terminal["v"] = True
    sh._tick()
    assert released == [True]
    ledger = json.loads(
        (sh.cfg.ledger_dir / f"{safe_name('plan-x:a3')}.json").read_text())
    assert ledger["shell"]["state"] == "closed"


def test_silence_stops_delivery_resume_auto_restores(tmp_path):
    sh, shell, drivers, _, _ = _mk(tmp_path)
    sh.start(run_loop=False)
    (sh.cfg.ledger_dir / f"{safe_name('plan-x:a3')}.cmd.jsonl").write_text(
        json.dumps({"verb": "silence"}) + "\n", encoding="utf-8")
    sh._tick()
    n = len(shell.lines)
    sh._on_event({"kind": "mail", "body": {}})     # logged, not delivered
    assert len(shell.lines) == n
    ledger = json.loads(
        (sh.cfg.ledger_dir / f"{safe_name('plan-x:a3')}.json").read_text())
    assert ledger["mode"] == "silenced"
    assert ledger["wakes"][-1]["delivered"] is False
    with (sh.cfg.ledger_dir / f"{safe_name('plan-x:a3')}.cmd.jsonl").open(
            "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"verb": "resume_auto"}) + "\n")
    sh._tick()
    sh._on_event({"kind": "mail", "body": {}})
    assert len(shell.lines) == n + 1
    sh.stop()


def test_crash_publishes_flowback_once(tmp_path):
    sh, shell, drivers, published, _ = _mk(tmp_path)
    sh.start(run_loop=False)
    shell._alive = False
    sh._tick()
    sh._tick()
    crashed = [p for p in published if p[0] == "crashed"]
    assert crashed == [("crashed", {"handle": "plan-x:a3"})]
    sh.stop()


def test_reattach_continues_seq_and_keeps_nonce(tmp_path):
    sh, shell, drivers, _, _ = _mk(tmp_path)
    sh.start(run_loop=False)
    drivers[0].emit({"kind": "mail", "body": {}})
    nonce = sh.cfg.nonce
    sh.stop()                          # shadow dies; shell untouched
    sh2, shell2, d2, _, _ = _mk(tmp_path)
    assert sh2.cfg.nonce == nonce      # provenance survives rebirth
    sh2.start(run_loop=False)
    d2[0].emit({"kind": "mail", "body": {}})
    assert f"#2 :{nonce} " in shell2.lines[-1]   # seq continued, not reset
    sh2.stop()


def test_heartbeat_ticks_on_interval(tmp_path):
    fake_now = {"t": 0.0}
    cfg = ShadowConfig(handle="r1:s2", role="planner",
                       ledger_dir=tmp_path / ".shadows",
                       activation="/agentic-plan", heartbeat_s=10)
    shell = FakeShell()
    sh = ShellShadow(cfg, shell_factory=lambda: shell,
                     driver_factory=None,
                     clock=lambda: fake_now["t"])
    sh.start(run_loop=False)
    base = len(shell.lines)
    sh._tick()
    assert len(shell.lines) == base            # not due yet
    fake_now["t"] = 11.0
    sh._tick()
    assert len(shell.lines) == base + 1
    assert "] tick:" in shell.lines[-1]
    sh.stop()


def test_pacing_read_adjusts_heartbeat(tmp_path):
    cfg = ShadowConfig(handle="r1:s3", role="planner",
                       ledger_dir=tmp_path / ".shadows",
                       activation="/agentic-plan", heartbeat_s=300)
    shell = FakeShell()
    pace = {"v": 60.0}
    sh = ShellShadow(cfg, shell_factory=lambda: shell, driver_factory=None,
                     pacing_read=lambda: pace["v"])
    sh.start(run_loop=False)
    sh._tick()
    assert sh.cfg.heartbeat_s == 60.0
    sh.stop()
