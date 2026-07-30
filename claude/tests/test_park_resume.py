"""DESIGN-v7 1.5.2/1.5.3 — planner park + resume backstop (claude side).

The pool owns the park mechanics (watermark, flush, kill, lock-kept, fork-
resume, watchdog) and is tested there. THIS suite proves the MCP-side seams:

  * `_enrich_wait` attaches a code-computed `park_hint` on the PLANNER
    surface when the pacing state expects a long structural wait — and never
    on the neuron/bare surface or the short probe bands;
  * `pool_close_self(park=true)` stamps `Plan.parked` (the durable recovery
    copy) and arms the pool's idle-gated park (`close_when_idle(park=true)`,
    the pool's designed self-park trigger — never the mid-turn kill);
  * the plan's next successful `next_action` CLEARS `Plan.parked` (the
    resumed planner touching the plan proves it is live again);
  * `reconcile` (recipe handle) emits the LATCHED advisory RESUME_PLANNER
    when a parked planner has unread inbox since its park — and stays silent
    for a provably idle park (the watchdog owns the fast path);
  * `pool_resume_planner(handle)` drives the pool's resume route.

Kept fast (in-memory stubs, no LLM — principle 6).
"""

from datetime import datetime, timezone

import pytest
from edp_contracts import BrokerMessage, ToolOk

from edp_claude.schemas import Plan, Recipe

RID = "recipe-park"
SID = "s1"
PID = f"{RID}-{SID}"
HANDLE = f"{RID}:{SID}"
OLD_TS = "2020-01-01T00:00:00+00:00"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _action(aid, status="pending", deps=()):
    return dict(action_id=aid, description=f"do {aid}", status=status,
                depends_on=list(deps), executor_mode="subagent",
                acceptance={"kind": "tests_pass"})


def _save_plan(env, actions, *, state="dispatching", parked=None, pid=PID,
               sid=SID):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id=RID, recipe_step_id=sid, domain="generic",
        shape="x", goal="park me", state=state, actions=actions,
        parked=parked,
    )))


def _save_recipe(env, *, step_status="in_progress"):
    now = datetime.now(timezone.utc)
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=RID, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": SID, "kind": "work", "description": "d",
                "status": step_status, "depends_on": [],
                "execution": "spawn_planner"}],
        context={}, created_at=now, updated_at=now,
    )))


# ── park_hint (1.5.2, harness-gated 2026-07-21) ──────────────────────────────
async def test_wait_carries_park_hint_on_opencode_planner_surface(
        env, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HARNESS", "opencode")
    # a child in flight, nothing ready → WAIT in the 10-min heads-down band,
    # which meets the default EDP_PARK_THRESHOLD_SECS=600.
    _save_plan(env, [_action("a1", status="in_progress")])
    res = _ok(await env.call("next_action", handle=PID, handle_type="plan"))
    assert res["kind"] == "wait"
    hint = res["args"].get("park_hint")
    assert hint and hint["park"] is True, res["args"]
    assert hint["expected_wait_secs"] >= hint["threshold_secs"]
    assert "pool_close_self" in hint["reason"]


async def test_claude_planner_is_never_advised_to_park(env, monkeypatch):
    """The 2026-07-21 operator ruling: on claude a park CLOSES the shell and
    the resume is a fresh one replaying the transcript onto a dead activation
    prompt. Same long-wait conditions as the opencode test above — the ONLY
    difference is the harness — and the planner must be left resident."""
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HARNESS", "claude")
    _save_plan(env, [_action("a1", status="in_progress")])
    res = _ok(await env.call("next_action", handle=PID, handle_type="plan"))
    assert res["kind"] == "wait"
    assert "park_hint" not in res["args"], res["args"]
    # and it is still told how to pace itself — residency is not silence
    assert res["args"]["heartbeat_secs"] > 0


async def test_unset_harness_reads_as_claude_never_parks(env, monkeypatch):
    """Fail SAFE: an unclassifiable shell is never advised to kill itself."""
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.delenv("EDP_HARNESS", raising=False)
    _save_plan(env, [_action("a1", status="in_progress")])
    res = _ok(await env.call("next_action", handle=PID, handle_type="plan"))
    assert res["kind"] == "wait"
    assert "park_hint" not in res["args"], res["args"]


async def test_no_park_hint_off_the_planner_surface(env, monkeypatch):
    # conftest clears EDP_ROLE — a bare/neuron caller never gets the hint
    # (parking is a pool-spawned planner's move, nobody else's). Pinned on
    # the opencode harness so the ROLE gate is what this proves, not the
    # harness gate.
    monkeypatch.setenv("EDP_HARNESS", "opencode")
    _save_plan(env, [_action("a1", status="in_progress")])
    res = _ok(await env.call("next_action", handle=PID, handle_type="plan"))
    assert res["kind"] == "wait"
    assert "park_hint" not in res["args"]


async def test_no_park_hint_when_threshold_not_met(env, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HARNESS", "opencode")
    monkeypatch.setenv("EDP_PARK_THRESHOLD_SECS", "999999")
    _save_plan(env, [_action("a1", status="in_progress")])
    res = _ok(await env.call("next_action", handle=PID, handle_type="plan"))
    assert res["kind"] == "wait"
    assert "park_hint" not in res["args"]


# ── pool_close_self(park=true) (1.5.2) ──────────────────────────────────────
async def test_pool_close_self_park_stamps_plan_and_arms_pool(
        env, monkeypatch):
    monkeypatch.setenv("EDP_SPAWN_SESSION_ID", "sess-42")
    monkeypatch.setenv("EDP_HANDLE", HANDLE)
    _save_plan(env, [_action("a1", status="in_progress")])
    _ok(await env.call("pool_close_self", park=True))
    # (1) the durable recovery copy: parked_at stamped; watermark honestly
    # None (the pool cuts the real one inside its own park op).
    p = env.ctx.plans.load(PID)
    assert p.parked and p.parked["parked_at"]
    assert p.parked["inbox_watermark"] is None
    # (2) the pool was armed via the idle-gated SELF-park trigger, not the
    # immediate mid-turn kill.
    arm = env.ctx.pool.armed_closes[-1]
    assert arm["session_id"] == "sess-42" and arm["park"] is True


async def test_pool_close_self_without_park_is_the_legacy_release(
        env, monkeypatch):
    monkeypatch.setenv("EDP_SPAWN_SESSION_ID", "sess-43")
    _save_plan(env, [_action("a1")])
    _ok(await env.call("pool_close_self"))
    assert not env.ctx.pool.armed_closes       # no park arm on a plain close
    assert env.ctx.plans.load(PID).parked is None


async def test_next_action_clears_plan_parked(env):
    # the resumed/fresh planner touching the plan proves it is live again.
    _save_plan(env, [_action("a1", status="in_progress")],
               parked={"parked_at": OLD_TS, "inbox_watermark": None,
                       "claude_session_id": None})
    _ok(await env.call("next_action", handle=PID, handle_type="plan"))
    assert env.ctx.plans.load(PID).parked is None


# ── reconcile's RESUME_PLANNER advisory backstop (1.5.3) ────────────────────
async def _send_to_planner(env, body=None):
    import uuid
    await env.ctx.broker.send(BrokerMessage.model_validate({
        "msg_id": str(uuid.uuid4()), "ts": datetime.now(timezone.utc),
        "from": "worker-x", "to": PID, "kind": "answer",
        "body": body or {"answer": "done"},
    }))


async def test_reconcile_advises_resume_on_parked_with_unread_inbox(env):
    _save_recipe(env)
    _save_plan(env, [_action("a1", status="in_progress")],
               parked={"parked_at": OLD_TS, "inbox_watermark": None,
                       "claude_session_id": None})
    await _send_to_planner(env)     # lands AFTER parked_at → unread
    res = _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    adv = res["advisory"]
    assert adv and adv["kind"] == "resume_planner", res
    assert adv["args"]["handle"] == HANDLE
    assert "pool_resume_planner" in adv["rationale"]
    # LATCHED (d76): the identical signal state does not re-fire.
    res2 = _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    assert res2["advisory"] is None
    # …but a NEWER message advances the signal and re-arms the advisory.
    await _send_to_planner(env, {"answer": "more"})
    res3 = _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    assert res3["advisory"] and res3["advisory"]["kind"] == "resume_planner"


async def test_reconcile_stays_silent_on_idle_park(env):
    # inbox checkable and EMPTY since the park → the watchdog owns it;
    # the backstop emits nothing.
    _save_recipe(env)
    _save_plan(env, [_action("a1", status="in_progress")],
               parked={"parked_at": datetime.now(timezone.utc).isoformat(),
                       "inbox_watermark": None, "claude_session_id": None})
    res = _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    assert res["advisory"] is None


# ── pool_resume_planner (1.5.3) ─────────────────────────────────────────────
async def test_pool_resume_planner_drives_the_pool_resume_route(env):
    env.ctx.pool.mark_parked(HANDLE)
    res = _ok(await env.call("pool_resume_planner", handle=HANDLE))
    assert env.ctx.pool.resumes == [HANDLE]
    assert res["resumed"] is True
    # double-caller (watchdog won the race): truthful no-op, never an error.
    res2 = _ok(await env.call("pool_resume_planner", handle=HANDLE))
    assert res2["resumed"] is False
