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
    assert s.live_mcp_servers() == ["edp8"]
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


