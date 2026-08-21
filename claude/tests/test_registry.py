"""Phase 3-C durable rule registry + supervisor tests.

Pure, hermetic unit coverage: a tmp registry root (no shared state), spec
validation against the NO-I/O provider, EffectSpec opt-in gate at register
time, the durable per-file round-trip, enable/disable, and a FAKE-Popen
supervisor so the spawn/track/teardown lifecycle is asserted with NO real
subprocess, broker, or pool.

Run: .venv/Scripts/python -m pytest tests/test_registry.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edp_claude.reactive import (
    EffectMutatingNotOptedIn,
    RuleExists,
    RuleNotFound,
    RuleRegistry,
    RuleSupervisor,
    SupervisorConfig,
    validate_spec,
)
from edp_claude.reactive.runtime import SpecError

ADVISORY_EFFECT = {
    "action": "broker_send",
    "args": {
        "to": {"const": "phase3-readback"},
        "kind": {"const": "observation"},
        "body": {"from_event": "body"},
    },
}


# ── spec validation (composition only, no I/O) ──────────────────────────────
def test_validate_spec_accepts_composed_observable():
    validate_spec("rx.broker(me, kinds=['observation'])", {"me": "x"})
    validate_spec(
        "rx.merge(rx.plan(p), rx.worklog(plan_id=p))", {"p": "plan-1"})


def test_validate_spec_rejects_non_observable():
    with pytest.raises(SpecError):
        validate_spec("1 + 1", {})


def test_validate_spec_keeps_sandbox_intact():
    # the registry must NOT widen compile_spec's restricted builtins.
    with pytest.raises(SpecError):
        validate_spec("__import__('os')", {})


# ── register: validation gates BEFORE persistence ───────────────────────────
def test_register_persists_one_json_file(tmp_path: Path):
    reg = RuleRegistry(tmp_path)
    rule = reg.register_rule(
        name="probe", spec="rx.broker(me)", effect=ADVISORY_EFFECT,
        owner="owner-inbox", bindings={"me": "owner-inbox"})
    assert rule.name == "probe"
    f = tmp_path / "probe.json"
    assert f.exists()
    on_disk = json.loads(f.read_text(encoding="utf-8"))
    assert on_disk["spec"] == "rx.broker(me)"
    assert on_disk["effect"]["rule_id"] == "probe"  # rule_id forced to name
    assert on_disk["enabled"] is True


def test_register_bad_spec_writes_nothing(tmp_path: Path):
    reg = RuleRegistry(tmp_path)
    with pytest.raises(SpecError):
        reg.register_rule(name="bad", spec="1+1", effect=None, owner="o")
    assert not (tmp_path / "bad.json").exists()


def test_register_mutating_effect_without_optin_rejected(tmp_path: Path):
    reg = RuleRegistry(tmp_path)
    bad_effect = {"action": "reconcile", "args": {"handle": {"const": "h"}}}
    with pytest.raises(EffectMutatingNotOptedIn):
        reg.register_rule(name="mut", spec="rx.broker(me)", effect=bad_effect,
                          owner="o", bindings={"me": "o"})
    assert not (tmp_path / "mut.json").exists()


def test_register_duplicate_rejected_unless_replace(tmp_path: Path):
    reg = RuleRegistry(tmp_path)
    reg.register_rule("r", "rx.broker(me)", None, "o", bindings={"me": "o"})
    with pytest.raises(RuleExists):
        reg.register_rule("r", "rx.broker(me)", None, "o", bindings={"me": "o"})
    # replace=True overwrites and preserves created_ts
    first = reg.get("r")
    again = reg.register_rule("r", "rx.worklog(plan_id=p)", None, "o",
                              bindings={"p": "plan-1"}, replace=True)
    assert again.created_ts == first.created_ts
    assert reg.get("r").spec == "rx.worklog(plan_id=p)"


def test_illegal_name_rejected(tmp_path: Path):
    reg = RuleRegistry(tmp_path)
    for bad in ("a/b", "..", ".hidden", "a\\b"):
        with pytest.raises(Exception):
            reg.register_rule(bad, "rx.broker(me)", None, "o",
                              bindings={"me": "o"})


# ── durability round-trip: a FRESH registry sees the persisted rule ─────────
def test_fresh_registry_reads_persisted_rules(tmp_path: Path):
    reg = RuleRegistry(tmp_path)
    reg.register_rule("a", "rx.broker(me)", ADVISORY_EFFECT, "o",
                      bindings={"me": "o"})
    reg.register_rule("b", "rx.broker(me)", None, "o", bindings={"me": "o"},
                      enabled=False)
    # a brand-new registry instance (simulates a process restart) over the
    # same root must reconstruct every rule from disk.
    fresh = RuleRegistry(tmp_path)
    names = {r.name for r in fresh.list_rules()}
    assert names == {"a", "b"}
    assert {r.name for r in fresh.enabled_rules()} == {"a"}


def test_enable_disable_remove(tmp_path: Path):
    reg = RuleRegistry(tmp_path)
    reg.register_rule("r", "rx.broker(me)", None, "o", bindings={"me": "o"})
    assert reg.disable("r").enabled is False
    assert reg.get("r").enabled is False
    assert reg.enable("r").enabled is True
    assert reg.remove("r") is True
    assert reg.remove("r") is False
    with pytest.raises(RuleNotFound):
        reg.get("r")


# ── supervisor lifecycle with a FAKE Popen (no real subprocess) ─────────────
class _FakePopen:
    """Records the command + emulates a long-lived child that terminates on
    request — so spawn/track/teardown is asserted with no real process."""

    _registry: list["_FakePopen"] = []
    _next_pid = 41000

    def __init__(self, cmd, **kw):
        self.cmd = cmd
        _FakePopen._next_pid += 1
        self.pid = _FakePopen._next_pid
        self._rc: int | None = None
        self.terminated = False
        self.killed = False
        _FakePopen._registry.append(self)

    def poll(self):
        return self._rc

    def terminate(self):
        self.terminated = True
        self._rc = -15

    def kill(self):
        self.killed = True
        self._rc = -9

    def wait(self, timeout=None):
        return self._rc


@pytest.fixture
def fake_popen(monkeypatch):
    _FakePopen._registry.clear()
    monkeypatch.setattr("edp_claude.reactive.registry.subprocess.Popen",
                        _FakePopen)
    return _FakePopen


def _cfg(tmp_path: Path) -> SupervisorConfig:
    return SupervisorConfig(agent_home=tmp_path, driver_python="python")


def test_supervisor_spawns_one_child_per_enabled_rule(tmp_path, fake_popen):
    reg = RuleRegistry(tmp_path / "reg")
    reg.register_rule("a", "rx.broker(me)", ADVISORY_EFFECT, "owner-a",
                      bindings={"me": "owner-a"})
    reg.register_rule("b", "rx.broker(me)", None, "owner-b",
                      bindings={"me": "owner-b"}, enabled=False)
    sup = RuleSupervisor(reg, _cfg(tmp_path))
    try:
        sup.start()
        # only the ENABLED rule "a" is subscribed.
        assert set(sup.tracked_pids()) == {"a"}
        child = fake_popen._registry[0]
        # the spawn reuses the driver CLI with the governed --effect-file path.
        assert "edp_claude.reactive.driver" in child.cmd
        assert "--effect-file" in child.cmd
        assert "--owner" in child.cmd
    finally:
        sup.shutdown()


def test_supervisor_teardown_terminates_tracked_children(tmp_path, fake_popen):
    reg = RuleRegistry(tmp_path / "reg")
    reg.register_rule("a", "rx.broker(me)", None, "o", bindings={"me": "o"})
    sup = RuleSupervisor(reg, _cfg(tmp_path))
    sup.start()
    child = fake_popen._registry[0]
    sup.shutdown()
    assert child.terminated is True       # graceful terminate, tracked PID only
    assert sup.tracked_pids() == {}       # nothing left tracked
    # F47#4: the singleton is a HELD OS lock; the file stays on disk
    # (never deleted — the ipc_lock unlock-race doctrine) but the lock is
    # RELEASED: a successor supervisor can acquire immediately.
    successor = RuleSupervisor(reg, _cfg(tmp_path))
    successor._acquire_singleton()        # would raise were it still held
    successor._release_singleton()


def test_supervisor_live_enable_disable(tmp_path, fake_popen):
    reg = RuleRegistry(tmp_path / "reg")
    reg.register_rule("a", "rx.broker(me)", None, "o", bindings={"me": "o"},
                      enabled=False)
    sup = RuleSupervisor(reg, _cfg(tmp_path))
    try:
        sup.start()
        assert sup.tracked_pids() == {}   # starts down (disabled)
        sup.enable("a")
        assert set(sup.tracked_pids()) == {"a"}
        assert reg.get("a").enabled is True
        child = fake_popen._registry[-1]
        sup.disable("a")
        assert sup.tracked_pids() == {}
        assert child.terminated is True
        assert reg.get("a").enabled is False
    finally:
        sup.shutdown()


def test_supervisor_restart_rereads_registry_from_disk(tmp_path, fake_popen):
    """The durability contract at the supervisor layer: a SECOND supervisor
    instance (a fresh process) over the same registry re-subscribes every
    enabled rule from disk with no carried-over memory."""
    root = tmp_path / "reg"
    reg = RuleRegistry(root)
    reg.register_rule("a", "rx.broker(me)", ADVISORY_EFFECT, "o",
                      bindings={"me": "o"})
    sup1 = RuleSupervisor(reg, _cfg(tmp_path))
    sup1.start()
    assert set(sup1.tracked_pids()) == {"a"}
    sup1.shutdown()  # first "process" exits — lock released, child torn down
    # fresh registry + supervisor reading the SAME on-disk root.
    sup2 = RuleSupervisor(RuleRegistry(root), _cfg(tmp_path))
    try:
        sup2.start()
        assert set(sup2.tracked_pids()) == {"a"}  # re-subscribed from disk
    finally:
        sup2.shutdown()


def test_supervisor_advances_since_cursor_on_resubscribe(tmp_path, fake_popen):
    """At-least-once replay guard: a rule that binds a broker `since` cursor gets
    that cursor ADVANCED to NOW in the regenerated driver-input bindings on each
    (re)subscribe — so a restart does not replay+re-fire a completed advisory.
    The DURABLE registry record keeps the original `since` (provenance)."""
    root = tmp_path / "reg"
    reg = RuleRegistry(root)
    original_since = "2026-01-01T00:00:00+00:00"
    reg.register_rule(
        "watcher", "rx.topic(name, since=since)", ADVISORY_EFFECT, "owner",
        bindings={"name": "candidates", "since": original_since})
    sup = RuleSupervisor(reg, _cfg(tmp_path))
    try:
        sup.start()
        # the regenerated driver-input bindings advanced `since` past the
        # registration value (no replay of pre-restart retained events).
        mat = json.loads(
            (root / "_active" / "watcher" / "bindings.json").read_text(
                encoding="utf-8"))
        assert mat["name"] == "candidates"        # other bindings untouched
        assert mat["since"] != original_since
        assert mat["since"] > original_since       # advanced forward
        # the durable record still carries the original for provenance.
        assert reg.get("watcher").bindings["since"] == original_since
    finally:
        sup.shutdown()


def test_supervisor_leaves_bindings_without_since_untouched(tmp_path,
                                                            fake_popen):
    """A rule that does NOT bind `since` is materialized verbatim — the advance
    is narrow (only the broker reconnect cursor), never a blanket rewrite."""
    root = tmp_path / "reg"
    reg = RuleRegistry(root)
    reg.register_rule("plain", "rx.broker(me)", None, "o", bindings={"me": "o"})
    sup = RuleSupervisor(reg, _cfg(tmp_path))
    try:
        sup.start()
        mat = json.loads(
            (root / "_active" / "plain" / "bindings.json").read_text(
                encoding="utf-8"))
        assert mat == {"me": "o"}
    finally:
        sup.shutdown()


def test_supervisor_single_instance_refused(tmp_path, fake_popen):
    reg = RuleRegistry(tmp_path / "reg")
    reg.register_rule("a", "rx.broker(me)", None, "o", bindings={"me": "o"})
    sup1 = RuleSupervisor(reg, _cfg(tmp_path))
    sup1.start()
    try:
        sup2 = RuleSupervisor(reg, _cfg(tmp_path))
        with pytest.raises(RuntimeError):
            sup2.start()  # same live pid holds the lock
    finally:
        sup1.shutdown()
