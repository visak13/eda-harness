"""Proactive escalation on prolonged waits.

Fix C (2026-05-24) counted consecutive WAIT ticks: after N ticks with no
recipe-level change the wait rationale escalated. Backlog items 10 + 11
(2026-07-10) replaced that contract, because it measured the wrong thing twice:

  * item 10 — the counter reset only on a RECIPE-level change, so a plan
    advancing briskly underneath (actions driven, planner healthy) looked
    identical to a wedged one. It cried wolf twice on 2026-07-09.
  * item 11 — a tick count is not a duration. Patience in wall-clock terms was
    whatever the caller's cron happened to be, and `wait_hint` (which the loop
    is supposed to obey) never entered the calculation at all.

The contract now: escalate after enough WALL-CLOCK time with no PLAN-LEVEL
progress. `wait_cycles` survives as observability only. These tests inject the
clock — a patience test must never sleep.

The both-direction and mutation proofs for the whole self-pacing cluster live
in tests/test_s26_self_pacing.py.
"""

from datetime import datetime, timezone

from edp_contracts import ToolOk

from edp_claude.schemas import Recipe
from edp_claude.tools import _tools


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _executing(env, rid):
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))


def _freeze(monkeypatch, start=1000.0):
    """Inject the wait clock. Returns a dict whose 't' the test advances.

    Patches `_wait_clock` (monotonic, patience only) — NOT the module's `_now`
    (wall-clock datetime, used by ~28 timestamp sites). The two are separate on
    purpose; conflating them shadowed `_now` and reddened 68 tests once."""
    clock = {"t": start}
    monkeypatch.setattr(_tools, "_wait_clock", lambda: clock["t"])
    return clock


async def _tick(env, rid):
    return (await env.call("next_action", handle=rid,
                           handle_type="recipe")).data


async def test_wait_escalates_on_elapsed_time_not_tick_count(env, monkeypatch):
    """A recipe EXECUTING with an in_progress step pacing-classifies as
    child_in_progress_recent_output → a 10-minute wait_hint. Patience is
    multiplier(3) × 600s = 1800s, and NOTHING but the passage of that time
    makes it fire."""
    monkeypatch.setenv("EDP_WAIT_ESCALATE_MULTIPLIER", "3")
    _tools._WAIT_STATE.clear()
    clock = _freeze(monkeypatch)
    rid = "recipe-wait-esc"
    _executing(env, rid)

    # Ten ticks, zero elapsed time. The OLD tick-counting contract escalated on
    # the third; the new one has no business escalating on any of them.
    for expected in range(1, 11):
        d = await _tick(env, rid)
        assert d["kind"] == "wait"
        assert d["args"]["wait_cycles"] == expected
        assert d["args"]["waited_secs"] == 0
        assert "proactive escalation" not in d["rationale"].lower()
    assert d["args"]["escalate_after_secs"] == 1800

    # One tick, after the patience window has actually elapsed.
    clock["t"] += 1800
    d = await _tick(env, rid)
    r = d["rationale"].lower()
    assert "proactive escalation" in r
    assert "ask_above" in r or "askuserquestion" in r
    assert "30 minutes" in r
    assert d["args"]["waited_secs"] == 1800


async def test_escalation_rearms_rather_than_firing_every_tick(env, monkeypatch):
    """A wedged plan surfaces once per patience window. Firing on every
    subsequent tick would defeat the idle collapse forever."""
    monkeypatch.setenv("EDP_WAIT_ESCALATE_MULTIPLIER", "3")
    _tools._WAIT_STATE.clear()
    clock = _freeze(monkeypatch)
    rid = "recipe-wait-rearm"
    _executing(env, rid)

    await _tick(env, rid)
    clock["t"] += 1800
    assert "proactive escalation" in (await _tick(env, rid))["rationale"].lower()
    # immediately after: re-armed, so quiet again
    d = await _tick(env, rid)
    assert "proactive escalation" not in d["rationale"].lower()
    assert d["args"]["waited_secs"] == 0
    # ...until another full window passes
    clock["t"] += 1800
    assert "proactive escalation" in (await _tick(env, rid))["rationale"].lower()


async def test_progress_resets_the_wait_accounting(env, monkeypatch):
    """A non-wait instruction IS progress: the accounting is dropped."""
    monkeypatch.setenv("EDP_WAIT_ESCALATE_MULTIPLIER", "3")
    _tools._WAIT_STATE.clear()
    _freeze(monkeypatch)
    rid = "recipe-wait-reset"
    _executing(env, rid)
    for _ in range(2):
        assert (await _tick(env, rid))["kind"] == "wait"
    assert _tools._WAIT_STATE[rid].cycles == 2
    # progress: the planner's plan closes → reconcile syncs it, then
    # next_action advances (non-wait)
    await env.call("broker_send", to=rid, kind="plan_closed",
                   body={"plan_id": f"{rid}-s1"})
    await env.call("reconcile", handle=rid, handle_type="recipe")
    d = await _tick(env, rid)
    assert d["kind"] != "wait"               # progressed
    assert rid not in _tools._WAIT_STATE     # accounting dropped on progress
