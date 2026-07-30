"""DESIGN-v6 W7 item 1 — computed wait_hint (MINUTES) + wait_reason from a
shared PACING policy table, surfaced on next_action, reconcile AND status_ping.

The bar: (1) PACING exists as a plain DATA table (no logic) beside the other
FSM data tables; (2) the pacing-state classifiers in the FSMs map inputs already
available in code (action statuses, last worklog ts, pool liveness) to a pacing
state; (3) every pacing state maps to the right (minutes, reason) across all
three outputs. No LLM anywhere (principle 6) — deterministic table lookup.

d7 discipline: this suite exercises tools that pass through the role-scoping
seam, and the runner may itself be a spawned worker whose EDP_ROLE/EDP_HANDLE
leak into pytest — so we CLEAR them (and the pacing env knob) up front, per the
lineage-env-leak lesson.
"""

from datetime import datetime, timedelta, timezone

import pytest
from edp_contracts import ToolOk

from edp_claude.fsm import (
    PACING,
    handle_pacing_state,
    pacing_hint,
    plan_pacing_state,
    recipe_pacing_state,
)
from edp_claude.fsm import state_machines as sm
from edp_claude.schemas import Plan, Recipe


# ── d7: pin/clear env that would otherwise skew these tests ─────────────────
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.delenv("EDP_STALE_OUTPUT_SECS", raising=False)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


# The five canonical pacing states and their (minutes, reason) per DESIGN-v6.
EXPECTED_PACING = {
    "child_in_progress_recent_output": (10, "heads-down; leave alone"),
    "child_in_progress_stale_output": (2, "probe: status_ping -> inspect_worker"),
    "verify_pending": (1, "acceptance imminent"),
    "awaiting_user": (30, "nothing moves without the user"),
    "idle_or_done": (30, "wrap-up cadence"),
}


# ── 1. the PACING table is DATA, beside the other FSM data tables ───────────
def test_pacing_table_is_data_with_exact_bands():
    # lives in fsm.state_machines beside STATE_MACHINES / RECIPE_STATES (data),
    # re-exported from the fsm package.
    assert PACING is sm.PACING
    assert isinstance(PACING, dict)
    assert PACING == EXPECTED_PACING
    # hint is MINUTES (int), reason is a string — for every state.
    for mins, reason in PACING.values():
        assert isinstance(mins, int) and isinstance(reason, str) and reason


def test_pacing_hint_maps_every_state_and_falls_back():
    for state, (mins, reason) in EXPECTED_PACING.items():
        assert pacing_hint(state) == (mins, reason)
    # an unrecognised state degrades to the idle wrap-up cadence, never crashes.
    assert pacing_hint("no-such-state") == PACING["idle_or_done"]


# ── 2. the pure classifiers (computation lives in the FSMs) ─────────────────
def _plan(actions, state="dispatching"):
    return Plan.model_validate(dict(
        plan_id="p", recipe_id="r", recipe_step_id="s1", domain="generic",
        shape="x", goal="g", state=state,
        actions=[dict(action_id=a["id"], description="d", status=a["status"],
                      depends_on=[], executor_mode="subagent",
                      acceptance={"kind": "tests_pass"})
                 for a in actions],
    ))


def test_plan_pacing_state_covers_every_band():
    # awaiting_user has top precedence
    assert plan_pacing_state(_plan([{"id": "a1", "status": "in_progress"}]),
                             awaiting_user=True) == "awaiting_user"
    # a verify action → acceptance imminent (beats an in_progress sibling)
    assert plan_pacing_state(_plan([{"id": "a1", "status": "verify"},
                                    {"id": "a2", "status": "in_progress"}])) \
        == "verify_pending"
    # in_progress, fresh output → heads-down
    assert plan_pacing_state(_plan([{"id": "a1", "status": "in_progress"}]),
                             output_stale=False) \
        == "child_in_progress_recent_output"
    # in_progress, stale output → probe
    assert plan_pacing_state(_plan([{"id": "a1", "status": "in_progress"}]),
                             output_stale=True) \
        == "child_in_progress_stale_output"
    # nothing in flight → wrap-up
    assert plan_pacing_state(_plan([{"id": "a1", "status": "done"}])) \
        == "idle_or_done"


def _recipe(state, *, outcomes=True, step_status=None, signoff=False):
    comp = {"branches": [], "expected_outcomes":
            [{"id": "o1", "description": "d", "verification": "v"}]
            if outcomes else []}
    if signoff:
        comp["user_signoff"] = "approved"
    steps = ([{"step_id": "s1", "kind": "work", "description": "d",
               "status": step_status, "depends_on": [],
               "execution": "spawn_planner"}]
             if step_status else [])
    return Recipe.model_validate(dict(
        recipe_id="r", user_goal_verbatim="g", domain="generic", state=state,
        comprehension=comp, steps=steps, context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))


def test_recipe_pacing_state_covers_every_band():
    assert recipe_pacing_state(_recipe("planning", step_status="pending"),
                               awaiting_user=True) == "awaiting_user"
    # EXECUTING = a planner (child) in flight
    assert recipe_pacing_state(_recipe("executing", step_status="in_progress"),
                               output_stale=False) \
        == "child_in_progress_recent_output"
    assert recipe_pacing_state(_recipe("executing", step_status="in_progress"),
                               output_stale=True) \
        == "child_in_progress_stale_output"
    # reviewing / closed = wrap-up
    assert recipe_pacing_state(_recipe("reviewing", step_status="done")) \
        == "idle_or_done"


def test_handle_pacing_state_covers_every_band():
    assert handle_pacing_state("alive", "verify") == "verify_pending"
    assert handle_pacing_state("alive", "in_progress", output_stale=False) \
        == "child_in_progress_recent_output"
    assert handle_pacing_state("alive", "in_progress", output_stale=True) \
        == "child_in_progress_stale_output"
    # a dead / unknown child is idle from the pacer's view
    assert handle_pacing_state("dead", "in_progress") == "idle_or_done"
    assert handle_pacing_state("unknown", None) == "idle_or_done"


# ── 3. the three surfaces carry integer-minutes wait_hint + wait_reason ─────
def _band(state):
    return EXPECTED_PACING[state]


def _save_plan(env, pid, actions, state="dispatching"):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id="r", recipe_step_id="s1", domain="generic",
        shape="x", goal="g", state=state,
        actions=[dict(action_id=a["id"], description="d", status=a["status"],
                      depends_on=[], executor_mode="subagent",
                      acceptance={"kind": "tests_pass"})
                 for a in actions],
    )))


def _worklog(env, pid, *, age_secs):
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_secs)).isoformat()
    env.ctx.plans.append_worklog(pid, {"ts": ts, "kind": "progress"})


# --- next_action (IO-free: heads-down / verify / awaiting_user bands) --------
async def test_next_action_plan_verify_band(env):
    _save_plan(env, "p-v", [{"id": "a1", "status": "verify"}])
    d = _ok(await env.call("next_action", handle="p-v", handle_type="plan"))
    mins, reason = _band("verify_pending")
    assert d["args"]["wait_hint"] == mins and isinstance(d["args"]["wait_hint"], int)
    assert d["args"]["wait_reason"] == reason


async def test_next_action_plan_in_progress_headsdown_band(env):
    _save_plan(env, "p-ip", [{"id": "a1", "status": "in_progress"}])
    d = _ok(await env.call("next_action", handle="p-ip", handle_type="plan"))
    mins, reason = _band("child_in_progress_recent_output")
    assert d["args"]["wait_hint"] == mins
    assert d["args"]["wait_reason"] == reason


async def test_next_action_recipe_awaiting_user_band(env):
    # COMPREHENDING with outcomes + steps but no signoff → AWAIT_USER.
    env.ctx.recipes.save(_recipe("comprehending", step_status="pending"))
    d = _ok(await env.call("next_action", handle="r", handle_type="recipe"))
    assert d["kind"] == "await_user"
    mins, reason = _band("awaiting_user")
    assert d["args"]["wait_hint"] == mins and isinstance(d["args"]["wait_hint"], int)
    assert d["args"]["wait_reason"] == reason


# --- reconcile (real staleness from the plan's last worklog ts) --------------
async def test_reconcile_plan_headsdown_when_output_fresh(env):
    _save_plan(env, "p-fresh", [{"id": "a1", "status": "in_progress"}])
    _worklog(env, "p-fresh", age_secs=5)          # well within the 600s floor
    rc = _ok(await env.call("reconcile", handle="p-fresh", handle_type="plan"))
    mins, reason = _band("child_in_progress_recent_output")
    assert rc["wait_hint"] == mins and isinstance(rc["wait_hint"], int)
    assert rc["wait_reason"] == reason


async def test_reconcile_plan_probe_when_output_stale(env):
    _save_plan(env, "p-stale", [{"id": "a1", "status": "in_progress"}])
    # s16: a stale-but-LIVE worker (a reasoning block runs long writing
    # nothing) must be paced (probe band), NOT reaped. Record its spawn so the
    # handle is backed by a live pool lock/session — otherwise an in_progress +
    # liveness-unknown + no-backing + past-grace action is now (correctly) a
    # PHANTOM and reconcile resets it, which is a different code path than this
    # pacing test exercises.
    await env.ctx.pool.spawn_worker("p-stale", "a1")
    _worklog(env, "p-stale", age_secs=3600)       # an hour of silence
    rc = _ok(await env.call("reconcile", handle="p-stale", handle_type="plan"))
    mins, reason = _band("child_in_progress_stale_output")
    assert rc["wait_hint"] == mins
    assert rc["wait_reason"] == reason


async def test_reconcile_env_knob_tightens_staleness(env, monkeypatch):
    # EDP_STALE_OUTPUT_SECS=0 makes any positive age stale.
    monkeypatch.setenv("EDP_STALE_OUTPUT_SECS", "0")
    _save_plan(env, "p-knob", [{"id": "a1", "status": "in_progress"}])
    _worklog(env, "p-knob", age_secs=5)
    rc = _ok(await env.call("reconcile", handle="p-knob", handle_type="plan"))
    assert rc["wait_hint"] == _band("child_in_progress_stale_output")[0]


async def test_reconcile_recipe_carries_int_hint(env):
    env.ctx.recipes.save(_recipe("executing", step_status="in_progress"))
    rc = _ok(await env.call("reconcile", handle="r", handle_type="recipe"))
    assert isinstance(rc["wait_hint"], int)
    assert isinstance(rc["wait_reason"], str) and rc["wait_reason"]


# --- status_ping (liveness + action status + output staleness) ---------------
def _stub_liveness(env, monkeypatch, value):
    # W7: liveness returns {state, last_output_ts} (a2). status_ping reads
    # ["state"]; a1 derives output-staleness from the worklog ts, not this
    # last_output_ts, so it can stay None here.
    async def _fake(handle):
        return {"state": value, "last_output_ts": None}
    monkeypatch.setattr(env.ctx.pool, "liveness", _fake)


async def test_status_ping_alive_fresh_is_headsdown(env, monkeypatch):
    _stub_liveness(env, monkeypatch, "alive")
    _save_plan(env, "p-sp", [{"id": "a1", "status": "in_progress"}])
    _worklog(env, "p-sp", age_secs=5)
    d = _ok(await env.call("status_ping", handle="p-sp:a1"))
    mins, reason = _band("child_in_progress_recent_output")
    assert d["wait_hint"] == mins and isinstance(d["wait_hint"], int)
    assert d["wait_reason"] == reason
    # the qualitative liveness prose is preserved (not lost in the upgrade).
    assert "do NOT force-fail" in d["liveness_note"]


async def test_status_ping_alive_stale_is_probe(env, monkeypatch):
    _stub_liveness(env, monkeypatch, "alive")
    _save_plan(env, "p-sp2", [{"id": "a1", "status": "in_progress"}])
    _worklog(env, "p-sp2", age_secs=3600)
    d = _ok(await env.call("status_ping", handle="p-sp2:a1"))
    mins, reason = _band("child_in_progress_stale_output")
    assert d["wait_hint"] == mins and d["wait_reason"] == reason


async def test_status_ping_verify_is_acceptance_imminent(env, monkeypatch):
    _stub_liveness(env, monkeypatch, "alive")
    _save_plan(env, "p-sp3", [{"id": "a1", "status": "verify"}])
    _worklog(env, "p-sp3", age_secs=5)
    d = _ok(await env.call("status_ping", handle="p-sp3:a1"))
    assert (d["wait_hint"], d["wait_reason"]) == _band("verify_pending")


async def test_status_ping_dead_is_idle(env, monkeypatch):
    _stub_liveness(env, monkeypatch, "dead")
    _save_plan(env, "p-sp4", [{"id": "a1", "status": "in_progress"}])
    d = _ok(await env.call("status_ping", handle="p-sp4:a1"))
    assert (d["wait_hint"], d["wait_reason"]) == _band("idle_or_done")


# ── 4. every pacing band is reachable through pacing_hint on all 3 surfaces ──
def test_all_five_bands_have_distinct_data():
    # the table is the single source the three surfaces funnel through, so a
    # correct table + a single pacing_hint() lookup per surface is what makes
    # "every state maps right across all three outputs" hold.
    assert set(PACING) == set(EXPECTED_PACING)
    for state in EXPECTED_PACING:
        mins, reason = pacing_hint(state)
        assert isinstance(mins, int) and isinstance(reason, str)
