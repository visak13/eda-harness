"""edp8.codex_seat — second opinion on the fix round (consult 20260923T133344Z-1c7e80e7, s-10a2b1f9ec).

One test per finding, each failing on b789d61 and passing after the fix:
  A P1 a secret split across two streamed deltas is recoverable from the RPC mirror
  B P1 a timed-out steer is resent under a new id while it may have landed → the wake arrives twice
  C P1 a timed-out steer's late witness withdraws a NEWER identical event (string equality)
  D P1 a failed Job Object bind still boots the runner (no kill-on-close for its children)
  E P2 the oracle times every recurring fire against the FIRST slot
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

from edp8.codex_seat import run as run_mod
from edp8.codex_seat.rpc import AppServer
from edp8.codex_seat.tools import Delivery, next_match, parse_cron, wrap

V8 = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("parity_oracle_so2", V8 / "scripts" / "parity_oracle.py")
po = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(po)  # type: ignore[union-attr]


class Host:
    def __init__(self, steer_ok):
        self.turns: list[tuple[str, str]] = []
        self.steers: list[tuple[str, str]] = []
        self.steer_ok = steer_ok
        self.d = Delivery(self.start, self.steer)

    def start(self, text, mid):
        self.turns.append((text, mid))
        self.d.turn_started(f"t{len(self.turns)}")
        return True

    def steer(self, text, _tid, mid):
        self.steers.append((text, mid))
        return self.steer_ok(len(self.steers))


# ------------------------------------------------------------------ A · split secret in streamed deltas
def test_a_secret_split_across_deltas_never_reaches_the_mirror(tmp_path):
    tok = "secret-abcdef123456"
    a = AppServer([], cwd=str(tmp_path), env={"EDP8_TOKEN": tok}, log_path=tmp_path / "m.jsonl")
    a._log_f = open(a.log_path, "a", encoding="utf-8")
    for part in ("secret-abc", "def123456"):
        a._mirror("in", {"method": "item/commandExecution/outputDelta",
                         "params": {"itemId": "i1", "delta": part}})
    a._log_f.close()
    rows = [json.loads(x) for x in a.log_path.read_text(encoding="utf-8").splitlines()]
    joined = "".join(str(r["msg"]["params"].get("delta", "")) for r in rows)
    assert tok not in joined and "secret-abc" not in joined and "def123456" not in joined, joined
    assert all(r["msg"]["method"] == "item/commandExecution/outputDelta" for r in rows)  # the event stays


# ------------------------------------------------------------------ B · no second copy of an open steer
def test_b_unknown_steer_is_not_resent_while_its_outcome_is_open():
    h = Host(lambda n: None if n == 1 else True)
    h.d.turn_started("t")
    h.d.native_started("bash", "i1")
    h.d.deliver("N")  # steer A: outcome unknown
    h.d.native_completed("i1")  # a delivery path that used to resend it as steer B
    assert len(h.steers) == 1, h.steers
    h.d.message_seen(h.steers[0][1])  # A did land
    h.d.turn_completed("t")
    assert h.turns == []  # exactly once


def test_b_unwitnessed_unknown_steer_is_delivered_once_at_settle():
    h = Host(lambda n: None)
    h.d.turn_started("t")
    h.d.native_started("bash", "i1")
    h.d.deliver("N")
    h.d.native_completed("i1")
    h.d.native_started("bash", "i2")
    h.d.native_completed("i2")
    assert len(h.steers) == 1
    h.d.turn_completed("t")
    assert [t for t, _ in h.turns] == [wrap("N")]


# ------------------------------------------------------------------ C · a late witness is keyed by id
def test_c_late_witness_never_withdraws_a_newer_identical_event():
    h = Host(lambda n: None if n == 1 else True)
    h.d.turn_started("t")
    h.d.native_started("bash", "i1")
    h.d.deliver("same")  # steer A: unknown
    h.d.native_completed("i1")
    h.d.deliver("same")  # a NEW, identical event while the turn runs (no native tool): pending
    h.d.message_seen(h.steers[0][1])  # A's late witness
    assert h.d.pending == ["same"]  # the newer event is not A's copy: it stays
    h.d.turn_completed("t")
    delivered = [t for t, _ in h.turns] + [s for s, _ in h.steers[1:]]
    assert delivered == [wrap("same")], delivered  # the newer event still arrives, once


# ------------------------------------------------------------------ D · the kill job is fail-closed
def test_d_failed_kill_job_bind_refuses_to_start(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    monkeypatch.setenv("EDP_HANDLE", "reviewer.jobfail")
    monkeypatch.setenv("EDP_AGENT_HOME", str(V8))
    monkeypatch.setenv("EDP_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("EDP_CODEX_RESUME", raising=False)
    monkeypatch.setattr(run_mod.os, "name", "nt")
    monkeypatch.setattr(run_mod, "bind_to_kill_job", lambda: False)

    def boom(*_a, **_k):
        raise AssertionError("seat constructed without its kill-on-close job")
    monkeypatch.setattr(run_mod, "CodexSeat", boom)
    assert run_mod.main([]) == 2


# ------------------------------------------------------------------ E · recurring fires vs their own slot
def test_e_recurring_fire_is_timed_against_its_own_slot():
    t0 = 1_790_000_000.0
    first = next_match(parse_cron("*/30 * * * *"), t0 * 1000) / 1000
    trace = [{"kind": "tool_use", "tool": "CronCreate", "ts": t0,
              "input": {"cron": "*/30 * * * *", "prompt": "BEAT", "recurring": True}},
             {"kind": "cron_fire", "text": "BEAT", "ts": first + 5},
             {"kind": "cron_fire", "text": "BEAT", "ts": first + 1800 + 5}]
    assert po._cron_slot_violations(trace, "harness") == []
    early = trace[:1] + [{"kind": "cron_fire", "text": "BEAT", "ts": first - 120}]  # before its first slot
    assert po._cron_slot_violations(early, "harness"), "a fire before any slot must still be flagged"
