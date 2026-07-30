"""Phase 2-A motor-nerve safety tests (T1-T10 from the approved Phase-0
safety spec §8). Every test injects deterministic observables / events
(`rx.of` / plain dicts) and a recording stub executor — NO live broker/pool.
Each test also writes a deterministic artifact under the eda-ml phase2_tests
dir so the property is independently file-verifiable (the host's file-based
gate), in addition to the pytest assertion.

Run: .venv/Scripts/python -m pytest tests/test_effects.py -v
"""

import json
from pathlib import Path

import reactivex as rx

from edp_claude.reactive import (
    EffectAllowlistError,
    EffectMutatingNotOptedIn,
    EffectSpec,
    SpecError,
    RxRuntime,
    compile_spec,
    subscribe_effect,
)
from edp_claude.reactive.effects import (
    _ALLOWLIST,
    DEFAULT_ON_ACTIONS,
    OPT_IN_ACTIONS,
    OUTCOME_ARG_UNRESOLVED,
    OUTCOME_DEDUPED,
    OUTCOME_DRY_RUN,
    OUTCOME_EXECUTED,
    OUTCOME_PRECONDITION_FAILED,
    OUTCOME_PROVENANCE_DROPPED,
    OUTCOME_RATE_LIMITED,
    EffectDispatcher,
)

# artifacts land here so each property is file-verifiable (file-based gate).
ART = Path("C:/Projects/Learning/eda-ml/docs/event_plane/phase2_tests")
FROZEN = (lambda: 0.0)  # frozen clock → no token refill within a test window


def _artifact(name: str, payload: dict) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    (ART / name).write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8")


class _Recorder:
    """Recording stub executor: appends each (action, args) call. For T5 it can
    also write a marker file so 'tool was NOT called' is provable on disk."""

    def __init__(self, marker: Path | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.marker = marker

    def __call__(self, action, args):
        self.calls.append((action, args))
        if self.marker is not None:
            self.marker.write_text("CALLED", encoding="utf-8")
        return {"ok": True}


def _audit_collector():
    lines: list[dict] = []
    return lines, lines.append


def _ok(res):
    assert getattr(res, "ok", False), res
    return res.data


# ── T1 — allowlist rejects an unknown action at COMPILE time ────────────────
def test_T1_allowlist_rejects_unknown_action():
    raised = None
    try:
        EffectSpec.compile({"action": "rm_rf", "rule_id": "t1",
                            "args": {"path": {"const": "/"}}})
    except EffectAllowlistError as e:
        raised = str(e)
    assert raised is not None and "allowlist" in raised
    _artifact("T1_allowlist_reject.json",
              {"property": "unknown action rejected at compile",
               "spec_action": "rm_rf", "error": "EffectAllowlistError",
               "message": raised, "pass": True})


# ── T2 — observe-lambda guard still intact (compile_spec sandbox unweakened) ─
def test_T2_compile_spec_guard_intact_regression():
    runtime = RxRuntime(lambda *a, **k: rx.empty())
    blocked = []
    for hostile in ("__import__('os')", "open('x')", "eval('1')",
                    "getattr(rx,'x')"):
        try:
            compile_spec(hostile, runtime)
            blocked.append((hostile, False))
        except SpecError:
            blocked.append((hostile, True))
    # a legitimate composition still compiles (guard didn't over-restrict).
    ok = compile_spec("rx.of(1)", runtime)
    assert all(b for _, b in blocked) and ok is not None
    _artifact("T2_guard_intact.json",
              {"property": "compile_spec _SAFE_BUILTINS unchanged by the "
                           "EffectSpec work (no import/open/eval/getattr)",
               "hostile_blocked": blocked, "legit_compiles": True,
               "pass": True})


# ── T3 — idempotency: same event twice fires once ───────────────────────────
def test_T3_idempotency_dedupes_replay():
    spec = EffectSpec.compile({
        "action": "notify_above", "rule_id": "t3",
        "args": {"kind": {"const": "alert"}, "body": {"from_event": "body"}}})
    rec = _Recorder()
    lines, sink = _audit_collector()
    disp = EffectDispatcher(spec, owner="o", executor=rec, audit_sink=sink,
                            now=FROZEN)
    event = {"body": {"plan_id": "p1", "n": 7}}
    d1 = disp.handle(event)
    d2 = disp.handle(event)          # identical → replay
    assert d1.outcome == OUTCOME_EXECUTED
    assert d2.outcome == OUTCOME_DEDUPED
    assert len(rec.calls) == 1       # fired exactly once
    assert d1.idem_key == d2.idem_key
    _artifact("T3_idempotency.json",
              {"property": "identical emission deduped on replay",
               "outcomes": [d1.outcome, d2.outcome], "tool_calls": len(rec.calls),
               "idem_key": d1.idem_key, "pass": True})


# ── T4 — rate cap: N>capacity → capacity fires, rest rate_limited ───────────
def test_T4_rate_cap_bounds_action_storm():
    spec = EffectSpec.compile({
        "action": "notify_above", "rule_id": "t4",
        "args": {"kind": {"const": "alert"}, "body": {"from_event": "body"}},
        "rate": {"capacity": 5, "refill_per_min": 5}})
    rec = _Recorder()
    lines, sink = _audit_collector()
    disp = EffectDispatcher(spec, owner="o", executor=rec, audit_sink=sink,
                            now=FROZEN)   # frozen → no refill
    outcomes = [disp.handle({"body": {"i": i}}).outcome for i in range(8)]
    executed = outcomes.count(OUTCOME_EXECUTED)
    limited = outcomes.count(OUTCOME_RATE_LIMITED)
    assert executed == 5 and limited == 3
    assert len(rec.calls) == 5
    _artifact("T4_rate_cap.json",
              {"property": "stream storm cannot amplify into action storm",
               "capacity": 5, "emitted": 8, "executed": executed,
               "rate_limited": limited, "pass": True})


# ── T5 — dry-run: resolves + audits, does NOT call the tool ─────────────────
def test_T5_dry_run_no_tool_call(tmp_path):
    marker = tmp_path / "T5_marker.txt"
    spec = EffectSpec.compile({
        "action": "notify_above", "rule_id": "t5", "dry_run": True,
        "args": {"kind": {"const": "alert"}, "body": {"from_event": "body"}}})
    rec = _Recorder(marker=marker)
    lines, sink = _audit_collector()
    disp = EffectDispatcher(spec, owner="o", executor=rec, audit_sink=sink,
                            now=FROZEN)
    d = disp.handle({"body": {"plan_id": "p1"}})
    assert d.outcome == OUTCOME_DRY_RUN
    assert not marker.exists()        # tool NOT called → no marker on disk
    assert len(rec.calls) == 0
    _artifact("T5_dry_run.json",
              {"property": "dry_run resolves+audits but never calls the tool",
               "outcome": d.outcome, "marker_written": marker.exists(),
               "tool_calls": len(rec.calls), "pass": True})


# ── T6 — advisory-by-default: tier-2 without opt-in rejected at compile ──────
def test_T6_tier2_without_optin_rejected():
    raised = None
    try:
        EffectSpec.compile({"action": "pool_reap", "rule_id": "t6",
                            "args": {"handle": {"from_event": "handle"}}})
    except EffectMutatingNotOptedIn as e:
        raised = str(e)
    assert raised is not None
    # and record_context (advisory but opt-in per Q1) is ALSO gated
    rc_raised = None
    try:
        EffectSpec.compile({"action": "record_context", "rule_id": "t6b",
                            "args": {"kind": {"const": "decision"},
                                     "recipe_id": {"const": "r"},
                                     "text": {"const": "x"}}})
    except EffectMutatingNotOptedIn as e:
        rc_raised = str(e)
    assert rc_raised is not None
    _artifact("T6_advisory_by_default.json",
              {"property": "anything outside default-ON pair needs explicit "
                           "opt-in (mutating:true)",
               "pool_reap_error": raised, "record_context_error": rc_raised,
               "default_on": ["broker_send", "notify_above"], "pass": True})


# ── F5 — the retired verb is GONE from the effect plane (s29) ───────────────
# W6.4 retired record_decision from every ROLE surface, but the effect plane
# does not role-scope: its allowlist was the last live write-path to the verb,
# so "retired" silently meant "retired from roles". These two pin the move.

def test_F5_retired_record_decision_is_unreachable_from_the_effect_plane():
    # UNREACHABLE, not merely unused: the closed allowlist is the only door,
    # and the name is no longer a key — so it is rejected at COMPILE time,
    # exactly like any other verb the framework does not have.
    assert "record_decision" not in _ALLOWLIST
    assert "record_decision" not in (DEFAULT_ON_ACTIONS | OPT_IN_ACTIONS)
    raised = None
    try:
        EffectSpec.compile({"action": "record_decision", "rule_id": "f5",
                            "mutating": True,
                            "args": {"recipe_id": {"const": "r"},
                                     "text": {"const": "x"}}})
    except EffectAllowlistError as e:
        raised = str(e)
    assert raised is not None and "allowlist" in raised


async def test_F5_record_context_effect_fires_through_the_real_verb(
        env, tmp_path):
    """The successor is not just NAMED in the allowlist — it EXECUTES, through
    the production executor, into the real recipe store, via the same verb a
    shell calls. `handle` runs on a worker thread because that is where it runs
    in production (the rx sink), and the tool body needs a loop of its own."""
    import asyncio

    from edp_claude.reactive.driver import make_broker_executor

    rid = _ok(await env.call(
        "start_recipe", goal="g", domain="generic"))["recipe_id"]
    spec = EffectSpec.compile({
        "action": "record_context", "rule_id": "f5-fires", "mutating": True,
        "args": {"kind": {"const": "decision"},
                 "recipe_id": {"const": rid},
                 "text": {"from_event": "body.text"},
                 "by": {"const": "motor-nerve"}}})
    lines, sink = _audit_collector()
    dispatcher = EffectDispatcher(
        spec, owner="rule-owner",
        # the REAL production executor — the same factory driver.main() wires.
        executor=make_broker_executor("http://broker.unused",
                                      repo_root=tmp_path),
        audit_sink=sink, now=FROZEN)

    decision = await asyncio.to_thread(
        dispatcher.handle, {"body": {"text": "the effect recorded this"}})

    assert decision.outcome == OUTCOME_EXECUTED, decision.detail
    assert decision.action == "record_context"
    # the decision is IN the store, written by the real verb — not just audited
    stored = [d.text for d in env.ctx.recipes.load(rid).context.decisions]
    assert "the effect recorded this" in stored
    assert lines[-1]["action"] == "record_context"
    _artifact("F5_record_context_effect.json",
              {"property": "the retired record_decision is gone from the "
                           "allowlist; the effect fires through "
                           "record_context(kind=decision) into the store",
               "outcome": decision.outcome, "stored_decisions": stored,
               "pass": True})


# ── T7 — pool_reap dead-only: an ALIVE worker is never reaped ───────────────
def test_T7_pool_reap_dead_only():
    spec = EffectSpec.compile({
        "action": "pool_reap", "rule_id": "t7", "mutating": True,
        "args": {"handle": {"from_event": "handle"}}})
    rec = _Recorder()
    lines, sink = _audit_collector()
    # liveness probe says the handle is ALIVE → reap must be refused, even in
    # the Phase-3 execution path (precondition is checked BEFORE the tier gate).
    disp = EffectDispatcher(
        spec, owner="o", executor=rec, audit_sink=sink, now=FROZEN, phase=3,
        liveness_probe=lambda h: "alive")
    d = disp.handle({"handle": "plan:a1"})
    assert d.outcome == OUTCOME_PRECONDITION_FAILED
    assert len(rec.calls) == 0        # alive worker NOT reaped
    # cross-check: in Phase 2, even a DEAD worker is dark-gated (no execute).
    disp2 = EffectDispatcher(
        spec, owner="o", executor=_Recorder(), audit_sink=(lambda x: None),
        now=FROZEN, phase=2, liveness_probe=lambda h: "dead")
    d2 = disp2.handle({"handle": "plan:a1"})
    assert d2.outcome == "blocked_tier2_dark"
    _artifact("T7_pool_reap_dead_only.json",
              {"property": "scoped dead-only: alive worker never reaped; "
                           "tier-2 dark in Phase 2",
               "alive_outcome": d.outcome, "reap_calls": len(rec.calls),
               "phase2_dead_outcome": d2.outcome, "pass": True})


# ── T8 — provenance/echo: own output is filtered out (0 fires) ──────────────
def test_T8_provenance_echo_filtered():
    spec = EffectSpec.compile({
        "action": "broker_send", "rule_id": "sixth-sense.advisory",
        "args": {"to": {"const": "topic:adv"},
                 "kind": {"const": "observation"},
                 "body": {"from_event": "body"}}})
    rec = _Recorder()
    lines, sink = _audit_collector()
    disp = EffectDispatcher(spec, owner="o", executor=rec, audit_sink=sink,
                            now=FROZEN)
    # an event carrying THIS rule's own provenance (its own prior output)
    echo = {"body": {"x": 1, "_prov": {"rule_id": "sixth-sense.advisory",
                                       "owner": "o", "effect": True,
                                       "plane": "motor"}}}
    d = disp.handle(echo)
    assert d.outcome == OUTCOME_PROVENANCE_DROPPED
    assert len(rec.calls) == 0        # echo never re-fires the rule
    _artifact("T8_provenance_echo.json",
              {"property": "effect's own output is dropped (echo-loop defence)",
               "outcome": d.outcome, "fires": len(rec.calls), "pass": True})


# ── T9 — audit completeness: every decision writes exactly one line ─────────
def test_T9_audit_line_per_decision():
    spec = EffectSpec.compile({
        "action": "notify_above", "rule_id": "t9",
        "args": {"kind": {"const": "alert"}, "body": {"from_event": "body"}},
        "rate": {"capacity": 2, "refill_per_min": 2}})
    rec = _Recorder()
    lines, sink = _audit_collector()
    disp = EffectDispatcher(spec, owner="o", executor=rec, audit_sink=sink,
                            now=FROZEN)
    decisions = []
    decisions.append(disp.handle({"body": {"i": 1}}))   # executed
    decisions.append(disp.handle({"body": {"i": 1}}))   # deduped
    decisions.append(disp.handle({"body": {"i": 2}}))   # executed
    decisions.append(disp.handle({"body": {"i": 3}}))   # rate_limited (cap 2)
    decisions.append(disp.handle({"no_body": True}))    # arg_unresolved
    assert len(lines) == len(decisions)                 # one line per decision
    assert all("outcome" in ln for ln in lines)
    _artifact("T9_audit_completeness.json",
              {"property": "one audit line per effect decision",
               "decisions": len(decisions), "audit_lines": len(lines),
               "outcomes": [d.outcome for d in decisions], "pass": True})


# ── T10 — arg unresolved: missing from_event path → no fire ─────────────────
def test_T10_arg_unresolved_no_fire():
    spec = EffectSpec.compile({
        "action": "notify_above", "rule_id": "t10",
        "args": {"kind": {"const": "alert"},
                 "body": {"from_event": "body.missing"}}})
    rec = _Recorder()
    lines, sink = _audit_collector()
    disp = EffectDispatcher(spec, owner="o", executor=rec, audit_sink=sink,
                            now=FROZEN)
    d = disp.handle({"body": {"present": 1}})  # has body, lacks body.missing
    assert d.outcome == OUTCOME_ARG_UNRESOLVED
    assert len(rec.calls) == 0        # never fires on an unresolved arg
    _artifact("T10_arg_unresolved.json",
              {"property": "missing from_event path → audited, never fired "
                           "(no silent default)",
               "outcome": d.outcome, "fires": len(rec.calls), "pass": True})


# ── bonus — the subscribe_effect wiring fires through a real rx pipeline ─────
def test_subscribe_effect_end_to_end():
    spec = EffectSpec.compile({
        "action": "notify_above", "rule_id": "wire",
        "args": {"kind": {"const": "alert"}, "body": {"from_event": "body"}}})
    rec = _Recorder()
    lines, sink = _audit_collector()
    src = rx.of({"body": {"a": 1}}, {"body": {"a": 2}})
    sub, disp = subscribe_effect(src, spec, owner="o", executor=rec,
                                 audit_sink=sink, now=FROZEN)
    assert len(rec.calls) == 2 and len(lines) == 2
    sub.dispose()
