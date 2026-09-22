"""edp8.codex_seat — Claude-parity seat tools under codex app-server (s-10a2b1f9ec).

Byte parity with the reference implementation (`.pi/extensions/edp8.ts`, dumped by
tests/codex_seat/dump_pi_tools.ts), the delivery state machine (idle turn / attach / steer /
settle), monitor + cron behaviour, containment argv, and an end-to-end run against a scripted
fake app-server (tests/codex_seat/fake_app_server.py).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from edp8.codex_seat import seat as seat_mod
from edp8.codex_seat.tools import (CRON_EXPIRE_MS, LINE_MAX, PREAMBLE_IDLE, Clock, Delivery, SeatTools,
                                   next_match, parse_cron, wrap)

V8 = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent / "codex_seat"
JITI = V8.parent / "edp-pool" / ".pi-harness" / "node_modules" / "@earendil-works" / "pi-coding-agent" / "node_modules" / "jiti" / "lib" / "jiti-cli.mjs"
DESC = V8 / "guides" / "harness-parity" / "descriptions.ours.json"


class FakeHost:
    """start_turn / steer recorder standing in for the runner's JSON-RPC calls."""

    def __init__(self, steer_ok: bool = True):
        self.turns: list[str] = []
        self.steers: list[str] = []
        self.steer_ok = steer_ok
        self.d = Delivery(self.start, self.steer)

    def start(self, text: str) -> bool:
        self.turns.append(text)
        self.d.turn_started("t1")
        return True

    def steer(self, text: str, _tid: str) -> bool:
        if self.steer_ok:
            self.steers.append(text)
        return self.steer_ok


def make_tools(tmp_path, host=None, **kw):
    host = host or FakeHost()
    env = {**os.environ, "EDP_PARITY_SEED": kw.pop("seed", "oracle")}
    t = SeatTools(host.d, cwd=V8, tasks_dir=tmp_path / "tasks", desc_path=DESC, env=env, **kw)
    return host, t


def wait_for(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


# ------------------------------------------------------------------ byte parity with edp8.ts
SCRIPT = [
    ["CronCreate", {"cron": "*/5 * * * *", "prompt": "ORACLE-RECURRING"}],
    ["CronCreate", {"cron": "30 14 28 2 *", "prompt": "pinned one-shot", "recurring": False}],
    ["CronCreate", {"cron": "* * * * *", "prompt": "every minute once", "recurring": False}],
    ["CronCreate", {"cron": "61 * * * *", "prompt": "bad"}],
    ["CronCreate", {"cron": "* * *", "prompt": "bad"}],
    ["CronList", {}],
    ["CronDelete", {"id": "deadbeef"}],
    ["TaskStop", {"task_id": "nope12345"}],
    ["Monitor", {"description": "no command", "persistent": False, "timeout_ms": 1000}],
    ["Monitor", {"command": "exit 0", "ws": {"url": "ws://127.0.0.1:9"}, "description": "both", "persistent": False, "timeout_ms": 1000}],
    ["Monitor", {"command": "exit 0", "description": "quick", "persistent": False, "timeout_ms": 1000}],
    ["Monitor", {"command": "exit 0", "description": "forever", "persistent": True, "timeout_ms": 300000}],
]


@pytest.fixture(scope="module")
def pi_reference():
    if not JITI.is_file() or not shutil.which("node"):
        pytest.skip("Pi harness (jiti) or node not installed")
    env = {**os.environ, "EDP_PARITY_SEED": "oracle", "EDP_DUMP_SCRIPT": json.dumps(SCRIPT)}
    out = subprocess.run(["node", str(JITI), str(HERE / "dump_pi_tools.ts")], cwd=V8, env=env,
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_specs_byte_equal_edp8_ts(tmp_path, pi_reference):
    _h, t = make_tools(tmp_path)
    ours = [{"name": s["name"], "description": s["description"], "parameters": s["inputSchema"]} for s in t.specs()]
    for ref, mine in zip(pi_reference["specs"], ours, strict=True):
        assert mine["name"] == ref["name"]
        assert mine["description"] == ref["description"], mine["name"]
        assert json.dumps(mine["parameters"]) == json.dumps(ref["parameters"]), mine["name"]  # key order too


def test_results_byte_equal_edp8_ts(tmp_path, pi_reference):
    _h, t = make_tools(tmp_path)
    for (name, args), ref in zip(SCRIPT, pi_reference["results"], strict=True):
        text, ok = t.call(name, args, "toolu_ref")
        text = text.split("\n\n<system-reminder>")[0]  # the fake Pi never goes busy; ours attaches a prior Monitor's end
        assert (text, not ok) == (ref["text"], ref["isError"]), (name, args)
    t.shutdown()


def test_expiry_variant_schema_and_result(tmp_path):
    h = FakeHost()
    t = SeatTools(h.d, cwd=V8, tasks_dir=tmp_path, desc_path=DESC, variant="expiry",
                  env={**os.environ, "EDP_PARITY_SEED": "x"})
    sch = t.specs()[0]["inputSchema"]
    assert sch["required"] == ["description", "timeout_ms"] and "persistent" not in sch["properties"]
    text, ok = t.call("Monitor", {"command": "exit 0", "description": "d", "timeout_ms": 9_000_000}, "c")
    assert ok and "expires in 30m unless the source ends first" in text
    t.shutdown()


# ------------------------------------------------------------------ delivery state machine
def test_idle_notifications_coalesce_into_one_turn():
    h = FakeHost()
    h.d.deliver("N1")
    h.d.deliver("N2")
    assert wait_for(lambda: h.turns)
    assert h.turns == [wrap("N1") + "\n" + wrap("N2")]
    assert h.turns[0].startswith("<system-reminder>\n" + PREAMBLE_IDLE)


def test_busy_pending_attaches_to_next_seat_tool_result():
    h = FakeHost()
    h.d.turn_started("t1")
    h.d.deliver("N1")
    assert h.turns == [] and h.steers == []
    assert h.d.attach("result") == "result\n\n" + wrap("N1")
    assert h.d.attach("again") == "again"


def test_native_tool_in_flight_steers_immediately_and_pending_steers_on_start():
    h = FakeHost()
    h.d.turn_started("t1")
    h.d.deliver("EARLY")          # model generating: pending
    h.d.native_started("bash")    # a shell starts: pending rides after its output
    assert h.steers == [wrap("EARLY")]
    h.d.deliver("DURING")
    assert h.steers[-1] == wrap("DURING")
    h.d.native_completed()
    h.d.deliver("AFTER")
    assert h.d.pending == ["AFTER"]


def test_failed_steer_falls_back_to_settle_flush_with_deferred_cron_first():
    h = FakeHost(steer_ok=False)
    h.d.on_settle(lambda: "CRON-PROMPT")
    h.d.turn_started("t1")
    h.d.native_started("bash")
    h.d.deliver("N1")
    h.d.deliver("N2")
    assert h.d.pending == ["N1", "N2"]
    h.d.turn_completed()
    assert h.turns == ["CRON-PROMPT"]              # one turn at a time: the cron turn goes first
    h.d.turn_completed()
    assert h.turns[-1] == wrap("N1") + "\n" + wrap("N2")


def test_outbox_is_serial():
    h = FakeHost()
    h.d.enqueue_turn("A")
    h.d.enqueue_turn("B")
    assert h.turns == ["A"]
    h.d.turn_completed()
    assert h.turns == ["A", "B"]


# ------------------------------------------------------------------ monitor behaviour
def test_monitor_lines_batching_and_terminal_envelopes(tmp_path):
    h, t = make_tools(tmp_path)
    text, ok = t.call("Monitor", {"command": "echo one; sleep 1; echo two; echo three; exit 3",
                                  "description": "probe", "persistent": False, "timeout_ms": 60000}, "toolu_x")
    assert ok
    tid = text.split("task ")[1][:9]
    assert wait_for(lambda: len(h.turns) >= 1)
    assert h.turns[0] == wrap(f'<task-notification>\n<task-id>{tid}</task-id>\n<summary>Monitor event: "probe"</summary>\n<event>one</event>\n</task-notification>')
    h.d.turn_completed()
    assert wait_for(lambda: any("<event>two\nthree</event>" in x for x in h.turns), 5)
    h.d.turn_completed()
    assert wait_for(lambda: any("<status>failed</status>" in x for x in h.turns), 5)
    last = h.turns[-1]
    assert "<tool-use-id>toolu_x</tool-use-id>" in last and 'Watch "probe" ended: script failed (exit 3)' in last
    t.shutdown()


def test_monitor_truncation_and_taskstop_is_silent(tmp_path):
    h, t = make_tools(tmp_path)
    h.d.turn_started("t1")  # busy: everything goes to pending
    first, _ = t.call("Monitor", {"command": "sleep 0.5; s=$(printf '%*s' 700 ''); echo \"${s// /x}\"",
                                  "description": "trunc", "persistent": False, "timeout_ms": 60000}, "c1")
    assert wait_for(lambda: any("(truncated)" in n for n in h.d.pending), 5)
    ev = next(n for n in h.d.pending if "(truncated)" in n)
    assert "x" * LINE_MAX + "...(truncated)</event>" in ev
    h.d.pending.clear()
    text, _ = t.call("Monitor", {"command": "echo armed; sleep 600", "description": "stop me", "persistent": True,
                                 "timeout_ms": 300000}, "c2")
    tid = text.split("task ")[1][:9]
    stop, ok = t.call("TaskStop", {"task_id": tid}, "c3")
    assert ok and json.loads(stop.split("\n\n")[0])["message"] == f"Stopped task {tid} (echo armed; sleep 600)"
    time.sleep(1.0)
    assert not any("<status>" in n for n in h.d.pending), "TaskStop must leave no terminal notification"
    t.shutdown()


def test_monitor_timeout_notice(tmp_path):
    h, t = make_tools(tmp_path)
    h.d.turn_started("t1")
    t.call("Monitor", {"command": "sleep 30", "description": "slow", "persistent": False, "timeout_ms": 1000}, "c")
    assert wait_for(lambda: any("[Watch timed out; arm it again if you still need it.]" in n for n in h.d.pending), 8)
    t.shutdown()


def test_monitor_rate_gate_suppresses_and_accounts(tmp_path):
    h, t = make_tools(tmp_path)
    h.d.turn_started("t1")
    t.call("Monitor", {"command": "for i in $(seq 1 60); do echo L$i; done", "description": "flood",
                       "persistent": False, "timeout_ms": 60000}, "c")
    assert wait_for(lambda: any("events dropped" in n for n in h.d.pending), 5)
    lines = sum(n.count("\nL") + n.count(">L") for n in h.d.pending)
    assert lines < 60
    t.shutdown()


# ------------------------------------------------------------------ cron behaviour
class FakeWall:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_cron_oneshot_fires_when_idle_and_defers_when_busy(tmp_path):
    wall = FakeWall(time.time())
    h, t = make_tools(tmp_path, clock=Clock("s", 1.0, wall))
    t.call("CronCreate", {"cron": "* * * * *", "prompt": "ONESHOT", "recurring": False}, "c")
    t.call("CronCreate", {"cron": "* * * * *", "prompt": "SECOND", "recurring": False}, "c")
    h.d.turn_started("t1")
    wall.t += 61
    t.tick()
    assert h.turns == [] and all(j.deferred for j in t.jobs.values())
    h.d.turn_completed()
    assert h.turns == ["ONESHOT\nSECOND"] and not t.jobs  # one turn, creation order, jobs gone


def test_cron_recurring_jitter_and_seven_day_expiry(tmp_path):
    wall = FakeWall(time.time())
    clock = Clock("s", 1.0, wall)
    h, t = make_tools(tmp_path, clock=clock)
    t.call("CronCreate", {"cron": "*/5 * * * *", "prompt": "R"}, "c")
    j = next(iter(t.jobs.values()))
    assert 0 <= j.jitter_s < 900 and j.next_fire == j.slot + j.jitter_s * 1000
    wall.t += CRON_EXPIRE_MS / 1000 + 1
    t.tick()                      # 7 days: marked expiring and, being due, fires its final time
    assert not t.jobs and h.turns == ["R"]


def test_cron_parse_and_next_match():
    assert parse_cron("*/15 9-17 * * 1-5")[0] == [0, 15, 30, 45]
    assert parse_cron("0 0 * * 7")[4] == [0]
    with pytest.raises(ValueError):
        parse_cron("60 * * * *")
    base = time.mktime((2026, 9, 23, 10, 7, 30, 0, 0, -1)) * 1000
    nxt = next_match(parse_cron("*/5 * * * *"), base)
    assert time.localtime(nxt / 1000)[3:5] == (10, 10)


# ------------------------------------------------------------------ containment
FAKE_SERVERS = [{"name": "chrome-devtools", "transport": "stdio"}, {"name": "cua_repl", "transport": "stdio"},
                {"name": "node_repl", "transport": "stdio"}, {"name": "playwright", "transport": "stdio"},
                {"name": "codex_app", "transport": "stdio"}, {"name": "remote-x", "transport": "streamable_http"},
                {"name": "edp8", "transport": "streamable_http"}]


def test_containment_disables_every_discovered_server_and_tool_injecting_features():
    args, disabled = seat_mod.containment_args("codex", discover=lambda _c: (FAKE_SERVERS, None))
    joined = " ".join(args)
    for s in ("chrome-devtools", "cua_repl", "node_repl", "playwright", "codex_app", "remote-x"):
        assert f"mcp_servers.{s}.enabled=false" in joined and s in disabled
    assert "mcp_servers.edp8.enabled" not in joined  # ours is redefined, not disabled
    for f in ("apps", "plugins", "browser_use", "computer_use", "multi_agent"):
        assert f"features.{f}=false" in args


def test_containment_fails_closed_on_discovery_error():
    with pytest.raises(RuntimeError, match="refusing"):
        seat_mod.containment_args("codex", discover=lambda _c: ([], "boom"))


def test_token_never_on_argv_and_board_headers_by_env_name(tmp_path):
    s = seat_mod.CodexSeat(cwd=V8, role="reviewer", handle="reviewer.t", log_dir=tmp_path, codex_bin="codex",
                           env={"EDP8_TOKEN": "tok-SECRET-123", "EDP_HANDLE": "reviewer.t"},
                           discover=lambda _c: (FAKE_SERVERS, None))
    argv = s.argv()
    assert not any("tok-SECRET-123" in a for a in argv)
    assert 'mcp_servers.edp8.url="http://127.0.0.1:9402/mcp/reviewer"' in argv
    assert any(a.startswith("mcp_servers.edp8.env_http_headers=") and '"X-Token"="EDP8_TOKEN"' in a for a in argv)
    assert seat_mod.sandbox_for("reviewer", {}) == "read-only"
    assert seat_mod.sandbox_for("engineer", {}) == "workspace-write"


# ------------------------------------------------------------------ end to end on the fake app-server
@pytest.fixture
def fake_seat(tmp_path, monkeypatch):
    log = tmp_path / "fake.jsonl"
    monkeypatch.setenv("FAKE_APPSERVER_LOG", str(log))
    s = seat_mod.CodexSeat(cwd=V8, role="engineer", handle="engineer.fake", log_dir=tmp_path,
                           codex_bin=str(HERE / "fake_app_server.py"), board=False,
                           env={"EDP_PARITY_SEED": "e2e", "EDP_PARITY_DESCRIPTIONS": str(DESC)},
                           discover=lambda _c: ([], None))
    s.start()
    yield s, log
    s.stop()


def sent(log: Path, method: str) -> list[dict]:
    if not log.exists():
        return []
    return [m for m in map(json.loads, log.read_text(encoding="utf-8").splitlines()) if m.get("method") == method]


def test_e2e_thread_start_carries_dynamic_tools_and_live_set(fake_seat):
    s, log = fake_seat
    start = sent(log, "thread/start")[0]["params"]
    assert [t["name"] for t in start["dynamicTools"]] == ["Monitor", "TaskStop", "CronCreate", "CronList", "CronDelete"]
    assert start["sandbox"] == "workspace-write" and start["approvalPolicy"] == "never"
    assert s.live_mcp_servers() == [] == s.live_servers  # board=False: nothing live at all
    assert json.loads(s.state_path.read_text())["threadId"] == s.thread_id


def test_e2e_monitor_line_mid_command_is_steered_after_it(fake_seat):
    s, log = fake_seat
    s.enqueue_turn('CALL Monitor {"command": "sleep 0.6; echo mid", "description": "attach", "persistent": false, "timeout_ms": 30000}\nRUN 2.5\nSAY ok')
    assert wait_for(lambda: sent(log, "turn/steer"), 10)
    steer = sent(log, "turn/steer")[0]["params"]["input"][0]["text"]
    assert "<event>mid</event>" in steer and steer.startswith("<system-reminder>")
    assert wait_for(lambda: s.delivery.is_idle(), 10)


def test_e2e_idle_notification_becomes_turn_and_cron_fires(fake_seat):
    s, log = fake_seat
    s.enqueue_turn('CALL Monitor {"command": "sleep 1; echo later", "description": "idle", "persistent": false, "timeout_ms": 30000}\nSAY armed')
    assert wait_for(lambda: any("<event>later</event>" in m["params"]["input"][0]["text"] for m in sent(log, "turn/start")), 10)
    s.tools.clock.set_scale(600.0)  # the cron clock only: next minute in ~0.1 s wall
    s.enqueue_turn('CALL CronCreate {"cron": "* * * * *", "prompt": "CRON-WAKE", "recurring": false}')
    assert wait_for(lambda: any(m["params"]["input"][0]["text"] == "CRON-WAKE" for m in sent(log, "turn/start")), 15)


def test_e2e_seat_tool_result_carries_pending_notification(fake_seat):
    s, log = fake_seat
    # the Monitor emits at +0.05 s, inside its own 200 ms result grace → attached to its OWN result
    s.enqueue_turn('CALL Monitor {"command": "echo fast", "description": "own", "persistent": false, "timeout_ms": 30000}\nSAY ok')
    assert wait_for(lambda: [m for m in map(json.loads, log.read_text().splitlines()) if "result" in m and "contentItems" in (m["result"] or {})], 10)
    res = [m for m in map(json.loads, log.read_text().splitlines()) if "result" in m and "contentItems" in (m["result"] or {})][0]
    text = res["result"]["contentItems"][0]["text"]
    assert text.startswith("Watch armed (task ") and "\n\n<system-reminder>" in text and "<event>fast</event>" in text


def test_rpc_mirror_log_records_both_directions(fake_seat):
    s, _log = fake_seat
    dirs = {json.loads(line)["dir"] for line in s.log_path.read_text(encoding="utf-8").splitlines()}
    assert {"in", "out"} <= dirs


# ------------------------------------------------------------------ second-opinion regressions (run 20260922T232513Z-3201a4ac)
from edp8.codex_seat import tools as tools_mod  # noqa: E402
from edp8.codex_seat.rpc import redactor  # noqa: E402
from edp8.codex_seat.tools import js_len, js_round, js_slice, parse_field  # noqa: E402


def test_late_turn_start_response_never_revives_a_completed_turn():
    """#2: the dispatcher processed turn/started + turn/completed before the turn/start RESPONSE."""
    d = Delivery(lambda _t: True, lambda _t, _i: True)
    d.turn_started("T")
    d.turn_completed("T")
    d.turn_started("T")  # the late response
    assert d.is_idle() and d.turn_id is None


def test_unknown_start_outcome_is_reconciled_not_blindly_resent(monkeypatch):
    """#3: a timed-out turn/start is resent only when no turn notification ever witnessed it."""
    monkeypatch.setattr(tools_mod, "UNKNOWN_START_S", 0.2)
    calls: list[str] = []
    d = Delivery(lambda t: calls.append(t) or (None if len(calls) == 1 else True), lambda _t, _i: True)
    d.enqueue_turn("A")
    d.turn_started("x")  # the server did take it: a notification arrived
    time.sleep(0.4)
    assert calls == ["A"]
    d.turn_completed("x")
    calls.clear()
    d.enqueue_turn("B")  # first attempt unknown, and NO notification follows
    assert wait_for(lambda: calls == ["B", "B"], 2)


def test_unknown_steer_outcome_is_not_repended():
    d = Delivery(lambda _t: True, lambda _t, _i: None)
    d.turn_started("t")
    d.native_started("bash")
    d.deliver("N")
    assert d.pending == []  # counted as delivered: a resend could land twice


def test_exhausted_start_retries_rekick_on_their_own(monkeypatch):
    """#4: retries exhausted → the outbox is retried with backoff, not stranded until a settle."""
    monkeypatch.setattr(tools_mod, "SEND_RETRIES", 1)
    monkeypatch.setattr(tools_mod, "SEND_RETRY_S", 0)
    monkeypatch.setattr(tools_mod, "RETRY_BACKOFF_S", (0.1, 0.2))
    calls: list[str] = []
    d = Delivery(lambda t: calls.append(t) or len(calls) >= 3, lambda _t, _i: True)
    d.enqueue_turn("A")
    assert wait_for(lambda: len(calls) == 3, 2) and calls == ["A"] * 3


def test_cron_deferred_after_settle_hook_drains_on_the_next_idle_tick(tmp_path):
    """#5: a job marked deferred between the settle hook and busy=False still fires."""
    wall = FakeWall(time.time())
    h, t = make_tools(tmp_path, clock=Clock("s", 1.0, wall))
    t.call("CronCreate", {"cron": "* * * * *", "prompt": "LATE", "recurring": False}, "c")
    next(iter(t.jobs.values())).deferred = True  # the race's end state: idle, deferred, no settle coming
    t.tick()
    assert h.turns == ["LATE"] and not t.jobs


def test_idle_batch_keeps_intake_order_across_a_turn_start():
    """#7: A (idle, coalescing) then a turn starts, then B → A before B, pending and steered alike."""
    h = FakeHost()
    h.d.deliver("A")
    h.d.turn_started("t")
    h.d.deliver("B")
    assert h.d.pending == ["A", "B"]
    h2 = FakeHost()
    h2.d.deliver("A")
    h2.d.turn_started("t")
    h2.d.native_started("bash")
    h2.d.deliver("B")
    assert len(h2.steers) == 1 and h2.steers[0].index("\nA\n") < h2.steers[0].index("\nB\n")
    time.sleep(0.05)  # the cancelled coalesce timer never re-delivers A
    assert h2.turns == [] and h2.d.pending == []


def test_monitor_terminal_notice_never_overtakes_its_final_batch(tmp_path):
    """#8: a flush holding the watch's order lock finishes before the terminal sequence runs."""
    import threading
    h, t = make_tools(tmp_path)
    got: list[str] = []
    h.d.deliver = lambda n: got.append("terminal" if "<status>" in n else "line")  # type: ignore[method-assign]
    m = t._new_mon("call-1", "order", "true", False)
    held, release = threading.Event(), threading.Event()

    def flushing() -> None:  # between batch extraction and deliver, the order lock held
        with m.order:
            held.set()
            release.wait(2)
            h.d.deliver("line")
    th = threading.Thread(target=flushing)
    th.start()
    held.wait(2)
    end = threading.Thread(target=t._end_monitor, args=(m, "[exited with code 0]", "completed", "done"))
    end.start()
    time.sleep(0.2)
    assert got == []  # the terminal is blocked behind the in-flight batch
    release.set()
    th.join(2)
    end.join(2)
    assert got == ["line", "terminal"]


def test_secrets_never_reach_the_persisted_logs(tmp_path, monkeypatch):
    """#1: a Monitor that echoes EDP8_TOKEN still delivers it to the model, but no file keeps it."""
    tok = "sekret-token-4711"
    r = redactor({"EDP8_TOKEN": tok})
    assert r(f"a {tok} b") == "a <redacted:EDP8_TOKEN> b" and redactor({})("x") == "x"
    log = tmp_path / "fake.jsonl"
    monkeypatch.setenv("FAKE_APPSERVER_LOG", str(log))
    s = seat_mod.CodexSeat(cwd=V8, role="engineer", handle="engineer.redact", log_dir=tmp_path,
                           codex_bin=str(HERE / "fake_app_server.py"), board=False,
                           env={"EDP8_TOKEN": tok, "EDP_PARITY_DESCRIPTIONS": str(DESC)}, discover=lambda _c: ([], None))
    s.start()
    try:
        s.enqueue_turn('CALL Monitor {"command": "echo $EDP8_TOKEN", "description": "leak", "persistent": false, "timeout_ms": 30000}\nSAY ok')
        assert wait_for(lambda: tok in log.read_text(encoding="utf-8"), 10)  # the model side did receive it
        assert wait_for(lambda: "<redacted:EDP8_TOKEN>" in s.log_path.read_text(encoding="utf-8"), 10)
    finally:
        s.stop()
    for f in tmp_path.rglob("*"):
        if f.is_file() and f != log and not f.name.endswith(".output"):
            assert tok not in f.read_text(encoding="utf-8", errors="replace"), f


def test_uncontained_live_server_fails_the_boot_before_any_turn(tmp_path, monkeypatch):
    """#6: a server discovery never saw (another CODEX_HOME / project config) stops the seat at start."""
    log = tmp_path / "fake.jsonl"
    monkeypatch.setenv("FAKE_APPSERVER_LOG", str(log))
    monkeypatch.setenv("FAKE_EXTRA_LIVE", "sneaky")
    s = seat_mod.CodexSeat(cwd=V8, role="engineer", handle="engineer.leak", log_dir=tmp_path,
                           codex_bin=str(HERE / "fake_app_server.py"), board=False,
                           env={"EDP_PARITY_DESCRIPTIONS": str(DESC)}, discover=lambda _c: ([], None))
    with pytest.raises(RuntimeError, match="sneaky"):
        s.start()
    assert not sent(log, "turn/start") and not s.state_path.exists()


def test_discovery_runs_in_the_launch_context(monkeypatch):
    seen = {}

    def fake_discover(codex, timeout_s=30, *, env=None, cwd=None):
        seen.update(env=env, cwd=cwd)
        return [], None
    monkeypatch.setattr("edp8.consult.discover_mcp_servers", fake_discover)
    seat_mod.containment_args("codex", env={"CODEX_HOME": "X:/other"}, cwd="X:/proj")
    assert seen == {"env": {"CODEX_HOME": "X:/other"}, "cwd": "X:/proj"}


def test_resume_with_invalid_state_fails_instead_of_a_fresh_thread(tmp_path, monkeypatch):
    """#10: a torn state file never turns 'You were resumed' into a silent new thread; writes are atomic."""
    monkeypatch.setenv("FAKE_APPSERVER_LOG", str(tmp_path / "fake.jsonl"))
    kw = dict(cwd=V8, role="engineer", handle="engineer.st", log_dir=tmp_path, codex_bin=str(HERE / "fake_app_server.py"),
              board=False, env={"EDP_PARITY_DESCRIPTIONS": str(DESC)}, discover=lambda _c: ([], None))
    s = seat_mod.CodexSeat(**kw)
    s.state_path.parent.mkdir(parents=True)
    s.state_path.write_text('{"threadId": "abc', encoding="utf-8")  # torn write
    with pytest.raises(RuntimeError, match="no valid threadId"):
        s.start(resume=True)
    s2 = seat_mod.CodexSeat(**kw)
    s2.start()
    try:
        assert json.loads(s2.state_path.read_text(encoding="utf-8"))["threadId"] == s2.thread_id
        assert not list(s2.state_path.parent.glob("*.tmp"))
    finally:
        s2.stop()


def test_js_string_number_and_nullish_semantics(tmp_path):
    """#11: UTF-16 lengths, Math.round, `??` and parseField exactly as edp8.ts (checked against node)."""
    emoji = "\U0001F600" * 300  # 600 UTF-16 units, 300 code points
    assert js_len(emoji) == 600 and js_len(js_slice(emoji, LINE_MAX)) == LINE_MAX
    assert js_round(0.5) == 1 and js_round(2.5) == 3 and js_round(-0.5) == 0
    h, t = make_tools(tmp_path)
    text, ok = t.call("TaskStop", {"task_id": "", "shell_id": "whatever1"}, "c")
    assert (text, ok) == ("No such task: ", False)
    for bad in ("1/", "\u0661", "*/", "1-"):
        with pytest.raises(ValueError):
            parse_field(bad, 0, 59)
    assert parse_field("1/2/3", 0, 59) == list(range(1, 60, 2))  # the third piece is ignored, as split() in JS
    text, _ = t.call("Monitor", {"command": "exit 0", "description": "r", "timeout_ms": 30000}, "c")
    assert "stops after 30000ms" in text
    ht, te = make_tools(tmp_path, variant="expiry")
    text, _ = te.call("Monitor", {"command": "exit 0", "description": "r", "timeout_ms": 30000}, "c")
    assert "expires in 1m" in text  # Math.round(0.5) = 1, Python round() would say 0m


