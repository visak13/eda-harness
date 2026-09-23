"""edp8.codex_seat — fix round for qa's adversary consult m-4a7dbc8c0d (architect steer m-5571aa7918).

One test (or more) per finding, each failing on fecef9d and passing after the fix:
  1 Monitor honours the role sandbox          6 parallel native tools, flush on completion
  2 secrets never reach the task output/stderr 7 live MCP set == required set, board forced on
  3 cron: no catch-up replay of missed slots   8 7-day expiry at the deadline, not the next slot
  4 stable message ids, unknown steer/start    9 EDP_CODEX_RESUME=1 without state is a hard failure
  5 a runner-only crash leaves no Monitor child (10 lives in tests/test_parity_oracle.py)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

from edp8.codex_seat import seat as seat_mod
from edp8.codex_seat import tools as tools_mod
from edp8.codex_seat.tools import CRON_EXPIRE_MS, Clock, Delivery, SeatTools, wrap

V8 = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent / "codex_seat"
FAKE = HERE / "fake_app_server.py"
DESC = V8 / "guides" / "harness-parity" / "descriptions.ours.json"
REAL_CODEX = shutil.which("codex")


def wait_for(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


class Host:
    """start/steer recorder with scriptable outcomes and the message ids Delivery sends."""

    def __init__(self, start_ok=True, steer_ok=True):
        self.turns: list[tuple[str, str]] = []
        self.steers: list[tuple[str, str]] = []
        self.start_ok, self.steer_ok = start_ok, steer_ok
        self.d = Delivery(self.start, self.steer)

    def start(self, text, mid):
        self.turns.append((text, mid))
        ok = self.start_ok(len(self.turns)) if callable(self.start_ok) else self.start_ok
        if ok:
            self.d.turn_started(f"t{len(self.turns)}")
        return ok

    def steer(self, text, _tid, mid):
        self.steers.append((text, mid))
        return self.steer_ok(len(self.steers)) if callable(self.steer_ok) else self.steer_ok


def tools_for(tmp_path, host, **kw):
    env = {**os.environ, "EDP_PARITY_SEED": "fix", **kw.pop("env", {})}
    return SeatTools(host.d, cwd=kw.pop("cwd", V8), tasks_dir=tmp_path / "tasks", desc_path=DESC, env=env, **kw)


class Wall:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


# ------------------------------------------------------------------ 1 · Monitor honours the role sandbox
@pytest.mark.skipif(not REAL_CODEX or os.name != "nt", reason="needs codex-cli's Windows sandbox")
def test_1_readonly_seat_monitor_cannot_write_outside_its_sandbox(tmp_path):
    probe = Path("C:/Temp") / f"seat-sandbox-probe-{uuid.uuid4().hex[:8]}"
    probe.parent.mkdir(exist_ok=True)
    h = Host()
    t = tools_for(tmp_path, h, sandbox_prefix=seat_mod.monitor_sandbox_prefix(REAL_CODEX, "read-only"))
    h.d.turn_started("busy")  # everything goes to pending
    res, _ = t.call("Monitor", {"command": f"printf probe > /c/Temp/{probe.name}; echo rc=$?", "description": "probe",
                       "persistent": False, "timeout_ms": 60000}, "c1")
    assert "<status>" in res or wait_for(lambda: any("<status>" in n for n in h.d.pending), 60)
    events = res + "\n".join(h.d.pending)
    assert "rc=1" in events and not probe.exists(), events
    t.shutdown()


@pytest.mark.skipif(not REAL_CODEX or os.name != "nt", reason="needs codex-cli's Windows sandbox")
def test_1_workspace_write_seat_writes_its_workspace_only(tmp_path):
    probe = Path("C:/Temp") / f"seat-sandbox-probe-{uuid.uuid4().hex[:8]}"
    ws = tmp_path / "ws"
    ws.mkdir()
    h = Host()
    t = tools_for(tmp_path, h, cwd=ws, sandbox_prefix=seat_mod.monitor_sandbox_prefix(REAL_CODEX, "workspace-write"))
    h.d.turn_started("busy")
    res, _ = t.call("Monitor", {"command": f"printf p > /c/Temp/{probe.name}; echo out=$?; printf p > inside && echo in=ok",
                       "description": "ww", "persistent": False, "timeout_ms": 60000}, "c1")
    assert "<status>" in res or wait_for(lambda: any("<status>" in n for n in h.d.pending), 60)
    events = res + "\n".join(h.d.pending)
    assert "out=1" in events and "in=ok" in events and not probe.exists() and (ws / "inside").exists(), events
    t.shutdown()


def test_1_seat_wraps_every_monitor_in_its_role_sandbox(tmp_path, monkeypatch):
    sb_log = tmp_path / "sandbox.jsonl"
    monkeypatch.setenv("FAKE_APPSERVER_LOG", str(tmp_path / "fake.jsonl"))
    monkeypatch.setenv("FAKE_SANDBOX_LOG", str(sb_log))
    s = seat_mod.CodexSeat(cwd=V8, role="reviewer", handle="reviewer.sbx", log_dir=tmp_path, codex_bin=str(FAKE),
                           board=False, env={"EDP_PARITY_DESCRIPTIONS": str(DESC)}, discover=lambda _c: ([], None))
    s.start()
    try:
        s.enqueue_turn('CALL Monitor {"command": "echo wrapped", "description": "w", "persistent": false, "timeout_ms": 30000}\nSAY ok')
        assert wait_for(lambda: sb_log.exists() and sb_log.read_text(encoding="utf-8").strip(), 10)
    finally:
        s.stop()
    for line in sb_log.read_text(encoding="utf-8").splitlines():  # warm shells and any cold start alike
        argv = json.loads(line)
        assert argv[:3] == ["sandbox", "-c", "sandbox_mode=read-only"] and argv[-2] == "-c"
        assert argv[-1] in (tools_mod.SANDBOX_STUB, tools_mod.WARM_STUB)
    events = (tmp_path / "fake.jsonl").read_text(encoding="utf-8")
    assert "wrapped" in events  # the command itself (carried in env) ran and its line reached the model


SLOW_SANDBOX = [sys.executable, "-c", "import subprocess, sys, time; time.sleep(1.5); "
                "sys.exit(subprocess.call(sys.argv[sys.argv.index('--') + 1:]))", "--"]


def test_1_sandbox_startup_does_not_eat_the_monitor_attach_window(tmp_path):
    """oracle r3 regression: `codex sandbox` takes ≈1 s to start the command, so a short Monitor's lines
    missed its own result (Claude attaches them) and went standalone. The grace counts from the command."""
    h = Host()
    t = tools_for(tmp_path, h, sandbox_prefix=SLOW_SANDBOX)
    h.d.turn_started("busy")
    text, ok = t.call("Monitor", {"command": "echo first-line; echo second-line", "description": "slow",
                                  "persistent": False, "timeout_ms": 30000}, "c1")
    assert ok and "first-line" in text and "second-line" in text and "<status>completed" in text, text
    assert "edp8-monitor-ready" not in text
    out = next((tmp_path / "tasks").glob("*.output")).read_text(encoding="utf-8")
    assert "first-line" in out and "edp8-monitor-ready" not in out, out
    t.shutdown()


def test_1_sandboxed_running_commands_first_line_stays_out_of_its_result(tmp_path):
    """oracle r4 (monitor_idle_line): Claude sends a still-running watch's first line standalone, after its
    batch window; a grace that outlasts BATCH_MS from the command's start would attach it."""
    h = Host()
    t = tools_for(tmp_path, h, sandbox_prefix=SLOW_SANDBOX)
    h.d.turn_started("busy")
    text, ok = t.call("Monitor", {"command": "echo one; sleep 2; echo two", "description": "idle",
                                  "persistent": False, "timeout_ms": 30000}, "c1")
    assert ok and "<event>one" not in text, text
    assert wait_for(lambda: any("<event>one</event>" in n for n in h.d.pending), 5), h.d.pending
    t.shutdown()


def test_1_warm_sandbox_shell_starts_the_command_without_the_sandbox_startup(tmp_path):
    """oracle r4 timing: the ≈1 s sandbox start-up delayed a watch's events (to=bash +6.4 s vs Claude +1.2 s).
    A started seat keeps one sandboxed shell warm; each Monitor takes it and the next one is re-warmed."""
    h = Host()
    t = tools_for(tmp_path, h, sandbox_prefix=SLOW_SANDBOX)
    t.start()
    try:
        for n in (1, 2):
            assert wait_for(lambda: t._warm is not None, 10)
            time.sleep(1.8)  # past SLOW_SANDBOX's 1.5 s start-up
            h.d.turn_started(f"busy{n}")
            t0 = time.time()
            text, ok = t.call("Monitor", {"command": f"echo warm-{n}\necho line-{n}", "description": f"w{n}",
                                          "persistent": False, "timeout_ms": 30000}, f"c{n}")
            took = time.time() - t0
            assert ok and f"warm-{n}" in text and f"line-{n}" in text and "<status>completed" in text, text
            assert took < 1.0, took  # a cold SLOW_SANDBOX start alone is 1.5 s
            h.d.turn_completed(f"busy{n}")
    finally:
        t.shutdown()
    assert t._warm is None


@pytest.mark.skipif(not REAL_CODEX or os.name != "nt", reason="needs codex-cli's Windows sandbox")
def test_1_warm_real_sandbox_still_denies_writes(tmp_path):
    probe = Path("C:/Temp") / f"seat-sandbox-probe-{uuid.uuid4().hex[:8]}"
    h = Host()
    t = tools_for(tmp_path, h, sandbox_prefix=seat_mod.monitor_sandbox_prefix(REAL_CODEX, "read-only"))
    t.start()
    try:
        assert wait_for(lambda: t._warm is not None, 10)
        time.sleep(3)
        h.d.turn_started("busy")
        t0 = time.time()
        res, _ = t.call("Monitor", {"command": f"printf probe > /c/Temp/{probe.name}; echo rc=$?", "description": "wp",
                                    "persistent": False, "timeout_ms": 60000}, "c1")
        took = time.time() - t0
        assert "<status>" in res or wait_for(lambda: any("<status>" in n for n in h.d.pending), 60)
        events = res + "\n".join(h.d.pending)
        assert "rc=1" in events and not probe.exists() and took < 0.8, (took, events)
    finally:
        t.shutdown()


@pytest.mark.skipif(not REAL_CODEX or os.name != "nt", reason="needs codex-cli's Windows sandbox")
def test_1_sandboxed_multiline_command_runs_whole(tmp_path):
    """`codex sandbox` cuts an argv argument at its first newline (measured on 0.156.0): a multi-line
    Monitor command must still run every line, keep its quoting and its exit code."""
    h = Host()
    t = tools_for(tmp_path, h, sandbox_prefix=seat_mod.monitor_sandbox_prefix(REAL_CODEX, "read-only"))
    h.d.turn_started("busy")
    res, _ = t.call("Monitor", {"command": "echo one\necho two\nx='a b'; echo \"$x\"\nexit 3", "description": "ml",
                       "persistent": False, "timeout_ms": 60000}, "c1")
    assert "<status>" in res or wait_for(lambda: any("<status>" in n for n in h.d.pending), 60)
    events = res + "\n".join(h.d.pending)
    assert "one" in events and "two" in events and "a b" in events and "exit 3" in events, events
    t.shutdown()


# ------------------------------------------------------------------ 2 · secrets never reach disk
def test_2_monitor_output_file_is_redacted_but_the_model_sees_the_line(tmp_path):
    tok = "qa-canary-token-4711"
    h = Host()
    t = tools_for(tmp_path, h, env={"EDP8_TOKEN": tok})
    h.d.turn_started("busy")
    text, _ = t.call("Monitor", {"command": "printf '%s\\n' \"$EDP8_TOKEN\"; echo \"err $EDP8_TOKEN\" >&2",
                                 "description": "leak", "persistent": False, "timeout_ms": 30000}, "c")
    tid = text.split("task ")[1][:9]
    seen = lambda: text + "".join(h.d.pending)  # noqa: E731 — fast events ride the Monitor result itself
    assert wait_for(lambda: "<status>" in seen(), 10)
    assert f"<event>{tok}</event>" in seen()  # delivered to the model as Claude would
    out = (tmp_path / "tasks" / f"{tid}.output").read_text(encoding="utf-8")
    assert tok not in out and out.count("<redacted:EDP8_TOKEN>") == 2, out
    t.shutdown()


def test_2_app_server_stderr_sink_is_redacted(tmp_path, monkeypatch):
    tok = "qa-canary-stderr-4712"
    monkeypatch.setenv("FAKE_APPSERVER_LOG", str(tmp_path / "fake.jsonl"))
    monkeypatch.setenv("FAKE_STDERR_VAR", "EDP8_TOKEN")
    s = seat_mod.CodexSeat(cwd=V8, role="engineer", handle="engineer.err", log_dir=tmp_path, codex_bin=str(FAKE),
                           board=False, env={"EDP8_TOKEN": tok, "EDP_PARITY_DESCRIPTIONS": str(DESC)},
                           discover=lambda _c: ([], None))
    s.start()
    s.stop()
    sink = s.log_path.with_suffix(".stderr.log")
    assert wait_for(lambda: sink.exists() and "boot" in sink.read_text(encoding="utf-8"), 5)
    body = sink.read_text(encoding="utf-8")
    assert tok not in body and "<redacted:EDP8_TOKEN>" in body


# ------------------------------------------------------------------ 3 · no catch-up replay
def test_3_missed_busy_period_yields_one_fire_then_a_future_slot(tmp_path):
    wall = Wall(time.time())
    h = Host()
    t = tools_for(tmp_path, h, clock=Clock("s", 1.0, wall))
    t.call("CronCreate", {"cron": "* * * * *", "prompt": "HEARTBEAT"}, "c")
    h.d.turn_started("busy")
    wall.t += 30 * 60
    t.tick()
    h.d.turn_completed("busy")  # the deferred fire: ONE turn
    for _ in range(3):  # complete each resulting turn and tick again without advancing time
        if h.d.busy:
            h.d.turn_completed(h.d.turn_id)
        t.tick()
    fires = [x for x, _ in h.turns if x == "HEARTBEAT"]
    assert len(fires) == 1, fires
    j = next(iter(t.jobs.values()))
    assert j.next_fire > t.clock.now_ms()  # the next fire is in the future


# ------------------------------------------------------------------ 4 · ids, unknown outcomes, dedup
def test_4_timed_out_steer_stays_pending_and_is_retried():
    h = Host(steer_ok=lambda n: None if n == 1 else True)
    h.d.turn_started("t")
    h.d.native_started("bash", "i1")
    h.d.deliver("N")  # steer #1 times out
    assert h.d.pending == ["N"]
    h.d.native_completed("i1")  # the next delivery path retries it
    assert len(h.steers) == 2 and h.steers[1][0] == wrap("N") and h.d.pending == []


def test_4_timed_out_steer_is_never_lost_at_settle():
    h = Host(steer_ok=None)
    h.d.turn_started("t")
    h.d.native_started("bash", "i1")
    h.d.deliver("N")
    h.d.turn_completed("t")
    assert h.turns and h.turns[-1][0] == wrap("N")


def test_4_late_witness_withdraws_the_repended_copy():
    h = Host(steer_ok=None)
    h.d.turn_started("t")
    h.d.native_started("bash", "i1")
    h.d.deliver("N")
    mid = h.steers[0][1]
    h.d.message_seen(mid)  # codex did take it (userMessage clientId == our id)
    assert h.d.pending == []
    h.d.turn_completed("t")
    assert h.turns == []  # never delivered twice


def test_4_watchdog_resends_under_the_same_id_and_dedups_by_it(monkeypatch):
    monkeypatch.setattr(tools_mod, "UNKNOWN_START_S", 0.2)
    h = Host(start_ok=lambda n: None if n == 1 else True)
    h.d.enqueue_turn("A")
    assert wait_for(lambda: len(h.turns) == 2, 2)  # no witness at all → resent
    assert h.turns[0][1] == h.turns[1][1]  # ... under the SAME message id
    h2 = Host(start_ok=lambda n: None)
    h2.d.enqueue_turn("B")
    h2.d.message_seen(h2.turns[0][1])  # the userMessage echo arrived (turn notifications delayed)
    time.sleep(0.5)
    assert len(h2.turns) == 1  # the witnessed start is never resent


def test_4_seat_sends_stable_ids_and_feeds_the_witness(tmp_path, monkeypatch):
    log = tmp_path / "fake.jsonl"
    monkeypatch.setenv("FAKE_APPSERVER_LOG", str(log))
    s = seat_mod.CodexSeat(cwd=V8, role="engineer", handle="engineer.ids", log_dir=tmp_path, codex_bin=str(FAKE),
                           board=False, env={"EDP_PARITY_DESCRIPTIONS": str(DESC)}, discover=lambda _c: ([], None))
    seen: list[str] = []
    orig = s.delivery.message_seen
    s.delivery.message_seen = lambda m: (seen.append(m), orig(m))  # type: ignore[method-assign]
    s.start()
    try:
        s.enqueue_turn("SAY hi")
        assert wait_for(lambda: seen, 10)
    finally:
        s.stop()
    sent = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    cid = next(m["params"]["clientUserMessageId"] for m in sent if m.get("method") == "turn/start")
    assert seen[0] == cid and cid.startswith("edp8-")


# ------------------------------------------------------------------ 5 · runner-only crash leaves no orphan
_RUNNER = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
from edp8.codex_seat.jobobj import bind_to_kill_job
from edp8.codex_seat.tools import Delivery, SeatTools
prefix = __import__("json").loads(sys.argv[4])
print("jobbed", bind_to_kill_job(), flush=True)
d = Delivery(lambda t, m: True, lambda t, i, m: True)
t = SeatTools(d, cwd=sys.argv[2], tasks_dir=sys.argv[3], desc_path=sys.argv[5], sandbox_prefix=prefix)
t.call("Monitor", {"command": "sleep 600 # " + sys.argv[6], "description": "orphan", "persistent": True, "timeout_ms": 1}, "c")
print("armed", flush=True)
time.sleep(600)
'''


def _pids_with(marker: str) -> list[int]:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"Get-CimInstance Win32_Process | ? {{ $_.CommandLine -like '*{marker}*' -and $_.Name -ne 'powershell.exe' }}"
                          " | % { $_.ProcessId }"], capture_output=True, text=True, timeout=60)
    return [int(x) for x in out.stdout.split() if x.strip().isdigit()]


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object")
@pytest.mark.parametrize("sandboxed", [False, True])
def test_5_killing_only_the_runner_pid_takes_its_monitor_children(tmp_path, sandboxed):
    if sandboxed and not REAL_CODEX:
        pytest.skip("needs codex-cli")
    marker = f"orphan-{uuid.uuid4().hex[:10]}"
    prefix = seat_mod.monitor_sandbox_prefix(REAL_CODEX, "read-only") if sandboxed else []
    script = tmp_path / "runner.py"
    script.write_text(_RUNNER, encoding="utf-8")
    runner = subprocess.Popen([sys.executable, str(script), str(Path(tools_mod.__file__).parents[2]), str(V8), str(tmp_path / "tasks"),
                               json.dumps(prefix), str(DESC), marker], stdout=subprocess.PIPE, text=True)
    try:
        assert runner.stdout.readline().strip() == "jobbed True"
        assert runner.stdout.readline().strip() == "armed"
        assert wait_for(lambda: any(True for _ in _pids_with(marker)), 30), "monitor child never started"
        runner.kill()  # TerminateProcess on the runner pid ONLY (no /T)
        runner.wait(10)
        assert wait_for(lambda: not _pids_with(marker), 20), f"orphans: {_pids_with(marker)}"
    finally:
        for pid in _pids_with(marker):  # cleanup by pid if the fix regressed
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        if runner.poll() is None:
            runner.kill()


# ------------------------------------------------------------------ 6 · parallel native tools
def test_6_parallel_native_tools_are_tracked_per_item():
    h = Host()
    h.d.turn_started("t")
    h.d.native_started("bash", "A")
    h.d.native_started("bash", "B")
    h.d.native_completed("A")  # B still runs
    h.d.deliver("E")
    assert h.steers and h.steers[-1][0] == wrap("E") and h.d.pending == []


def test_6_pending_is_flushed_when_a_native_tool_completes():
    h = Host(steer_ok=lambda n: n > 1)  # the first steer is refused → pending
    h.d.turn_started("t")
    h.d.native_started("bash", "A")
    h.d.deliver("E")
    assert h.d.pending == ["E"]
    h.d.native_completed("A")
    assert h.d.pending == [] and h.steers[-1][0] == wrap("E")


# ------------------------------------------------------------------ 7 · live set equality
def test_7_a_board_seat_without_a_live_board_refuses_to_start(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_APPSERVER_LOG", str(tmp_path / "fake.jsonl"))
    monkeypatch.setenv("FAKE_NO_BOARD", "1")
    s = seat_mod.CodexSeat(cwd=V8, role="engineer", handle="engineer.nob", log_dir=tmp_path, codex_bin=str(FAKE),
                           board=True, env={"EDP_PARITY_DESCRIPTIONS": str(DESC), "EDP_HANDLE": "engineer.nob"},
                           discover=lambda _c: ([], None))
    with pytest.raises(RuntimeError, match=r"missing \['edp8'\]"):
        s.start()
    assert "mcp_servers.edp8.enabled=true" in s.argv()


# ------------------------------------------------------------------ 8 · 7-day expiry at the deadline
def test_8_sparse_recurring_job_expires_at_the_seven_day_deadline(tmp_path):
    wall = Wall(time.mktime((2027, 1, 2, 12, 0, 0, 0, 0, -1)))
    h = Host()
    t = tools_for(tmp_path, h, clock=Clock("s", 1.0, wall))
    t.call("CronCreate", {"cron": "0 0 1 1 *", "prompt": "NEW-YEAR"}, "c")
    wall.t += CRON_EXPIRE_MS / 1000 - 5
    t.tick()
    assert t.jobs and h.turns == []  # not yet
    wall.t += 6
    t.tick()
    assert not t.jobs and [x for x, _ in h.turns] == ["NEW-YEAR"]  # final fire at the deadline, then gone


# ------------------------------------------------------------------ 9 · resume without state is fatal
def test_9_resume_requested_without_state_never_starts_a_fresh_thread(tmp_path, monkeypatch):
    from edp8.codex_seat import run as run_mod
    log = tmp_path / "fake.jsonl"
    monkeypatch.setenv("FAKE_APPSERVER_LOG", str(log))
    monkeypatch.setattr("edp8.consult.discover_mcp_servers", lambda *_a, **_k: ([], None))
    for k, v in {"EDP_ROLE": "engineer", "EDP_HANDLE": "engineer.nostate", "EDP_AGENT_HOME": str(V8),
                 "EDP_LOG_DIR": str(tmp_path), "EDP_CODEX_BIN": str(FAKE), "EDP_CODEX_RESUME": "1",
                 "EDP_PARITY_DESCRIPTIONS": str(DESC)}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(run_mod, "bind_to_kill_job", lambda: False, raising=False)  # not the pytest process
    box: dict = {}
    th = threading.Thread(target=lambda: box.update(rc=run_mod.main()), daemon=True)
    th.start()
    th.join(20)
    sent = [json.loads(x).get("method") for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    assert box.get("rc") == 2 and "thread/start" not in sent, (box, sent)
