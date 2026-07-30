"""DESIGN-v6 W7 ACCEPTANCE — end-to-end simulation + real token-drop measurement.

This suite does NOT re-implement W7 (items a1-a5 landed the pacing table, the
computed wait_hint, and the reconcile->next_action short-circuit). It EXERCISES
the landed behavior end to end on the live tool seam (no broker/pool restart)
and MEASURES the per-tick token cost, proving the three acceptance bars:

  1. A ~20-min HEADS-DOWN worker (a child action in_progress, output still
     recent) drives a SEQUENCE of paced planner ticks — each
     reconcile->next_action(reconcile_changed=False) pair collapses to the
     one-line {no_change, wait_hint>=10, ...} payload (the
     child_in_progress_recent_output PACING band).

  2. A worker ANSWER (a new inbox message) landing on the plan flips the VERY
     NEXT tick from no_change back to the FULL instruction within one cadence —
     the short-circuit releases the instant there is something to say.

  3. The idle-tick token cost drops by an ORDER OF MAGNITUDE: the REAL tiktoken
     count of the collapsed no_change payload is >=10x smaller than the full
     instruction+context payload next_action would otherwise push on that same
     idle tick. Ticks/hour is constant, so this per-tick ratio IS the idle
     planner-hour drop. This is a real token count (tiktoken cl100k_base), not
     a proxy.

d7/d8 discipline: this runner may itself be a spawned worker whose
EDP_ROLE/EDP_HANDLE (and the staleness knob) leak into pytest — the autouse
fixture CLEARS them so role-scoping / addressing / staleness don't skew a tick.
Env is PINNED via monkeypatch (no shell 'env' prefix).
"""

from datetime import datetime, timedelta, timezone

import pytest
from edp_contracts import ToolOk

from edp_claude.schemas import Plan, Recipe

RID = "recipe-w7acc"
SID = "s1"
PID = f"{RID}-{SID}"

# Heads-down band, from the shared PACING table (state_machines.PACING).
HEADS_DOWN_MIN = 10
HEADS_DOWN_REASON = "heads-down; leave alone"

# 20 one-minute heartbeat ticks == the "20-min heads-down" window. Ticks/hour is
# a constant of the cron cadence; we model the WINDOW as a fixed tick count.
HEADS_DOWN_TICKS = 20

# The order-of-magnitude bar the design pins for the idle-tick collapse.
TOKEN_DROP_FLOOR = 10.0


# ── tiktoken: a REAL token count (cl100k_base loads offline in this venv) ─────
def _encoder():
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def _token_count(payload) -> int:
    """Real token count of a tool-result payload, serialized the way it would
    ride the wire (compact JSON, datetimes/enums coerced to str)."""
    import json

    text = json.dumps(payload, default=str, sort_keys=True)
    return len(_encoder().encode(text))


# ── d7: clear the env a spawned-worker pytest would otherwise inherit ────────
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.delenv("EDP_STALE_OUTPUT_SECS", raising=False)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _save_recipe(env, *, n_decisions=4, rid=RID):
    """An EXECUTING recipe with a handful of ACTIVE decisions + outcomes — a
    realistic mid-run planner whose full next_action push carries real context
    (recap/phase/active_decisions index). This is the payload the short-circuit
    is suppressing, so it must be representative, not empty."""
    now = datetime.now(timezone.utc)
    decisions = [
        dict(id=f"d{i}", text=f"settled decision {i}: use approach {i}",
             rationale=f"because option {i} was validated in the spike",
             by="neuron", at=now, title=f"decision {i}", kind="direction")
        for i in range(1, n_decisions + 1)
    ]
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="ship the W7 pacing loop",
        domain="generic", state="executing",
        comprehension={"branches": [],
                       "expected_outcomes": [
                           {"id": "o1", "description": "idle ticks collapse",
                            "verification": "token drop measured"},
                           {"id": "o2", "description": "answer restores push",
                            "verification": "next tick is full instruction"}]},
        steps=[{"step_id": SID, "kind": "work", "description": "drive plan",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={"decisions": decisions},
        created_at=now, updated_at=now,
    )))


def _save_plan(env, pid=PID, *, status="in_progress", state="dispatching"):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id=RID, recipe_step_id=SID, domain="generic",
        shape="x", goal="drive the heads-down worker", state=state,
        actions=[dict(action_id="a1", description="the heads-down child action",
                      status=status, depends_on=[], executor_mode="subagent",
                      acceptance={"kind": "tests_pass"})],
    )))


def _fresh_output(env, pid=PID, *, age_secs=1):
    """Model the heads-down worker still producing output: append a worklog
    entry whose ts is well within the staleness floor, so reconcile classifies
    the child as child_in_progress_recent_output (heads-down)."""
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_secs)).isoformat()
    env.ctx.plans.append_worklog(pid, {"ts": ts, "kind": "progress"})


async def _reconcile(env, pid=PID):
    return _ok(await env.call("reconcile", handle=pid, handle_type="plan"))


async def _next_action(env, pid=PID, **extra):
    return _ok(await env.call("next_action", handle=pid, handle_type="plan",
                              **extra))


# ── 1. a 20-min heads-down window: every paced tick collapses to no_change ───
async def test_headsdown_20min_window_every_tick_collapses(env):
    _save_recipe(env)
    _save_plan(env)

    collapsed_ticks = 0
    for minute in range(HEADS_DOWN_TICKS):
        # the worker heartbeats fresh output each minute (still heads-down)
        _fresh_output(env, age_secs=1)

        # the PACED loop: reconcile (sync) then next_action fed reconcile's
        # changed result. A heads-down child never diverges, so changed=False.
        rc = await _reconcile(env)
        assert rc["changed"] is False, f"tick {minute}: unexpected divergence"
        assert rc["wait_hint"] == HEADS_DOWN_MIN
        assert rc["wait_reason"] == HEADS_DOWN_REASON

        d = await _next_action(env, reconcile_changed=rc["changed"])
        # the pair collapsed to the one-liner — NOT the full instruction push.
        assert d.get("no_change") is True, f"tick {minute}: did not collapse"
        assert d["wait_hint"] >= HEADS_DOWN_MIN
        assert d["wait_reason"] == HEADS_DOWN_REASON
        assert "kind" not in d and "context" not in d  # full push suppressed
        collapsed_ticks += 1

    # every tick across the whole window collapsed — no drift, no leaked push.
    assert collapsed_ticks == HEADS_DOWN_TICKS


# ── 2. a worker answer flips the VERY NEXT tick back to the full instruction ─
async def test_worker_answer_flips_next_tick_to_full_instruction(env):
    _save_recipe(env)
    _save_plan(env)
    _fresh_output(env)

    # idle tick first → collapses.
    rc = await _reconcile(env)
    d0 = await _next_action(env, reconcile_changed=rc["changed"])
    assert d0.get("no_change") is True

    # the worker sends an ANSWER onto the plan's inbox (a real new message).
    _ok(await env.call("broker_send", to=PID, kind="answer",
                       body={"text": "here is the answer you asked for"}))

    # the very next paced tick — same reconcile_changed=False opt-in — must NOT
    # collapse: the non-empty inbox-diff restores the full WAIT instruction
    # within one cadence (short-circuit released).
    rc2 = await _reconcile(env)
    d1 = await _next_action(env, reconcile_changed=rc2["changed"])
    assert "no_change" not in d1, "answer did not release the short-circuit"
    assert d1["kind"] == "wait"                 # full instruction restored
    assert d1["args"]["wait_hint"] == HEADS_DOWN_MIN  # item-1 hint still rides

    # non-consuming: the answer is still deliverable to a real check_inbox.
    inbox = _ok(await env.call("check_inbox", handle=PID))
    assert any(mm["body"].get("text", "").startswith("here is the answer")
               for mm in inbox["messages"])


# ── 3. the idle-tick token cost drops by an ORDER OF MAGNITUDE (real count) ──
async def test_idle_tick_token_cost_drops_at_least_10x(env):
    _save_recipe(env)
    _save_plan(env)
    _fresh_output(env)

    # SAME idle tick, two ways:
    #  - collapsed: the paced loop opts in (reconcile_changed=False) -> no_change
    #  - full: a bare next_action (reconcile_changed=None) -> full instruction
    #          + pushed recipe context, exactly what the collapse suppresses.
    rc = await _reconcile(env)
    collapsed = await _next_action(env, reconcile_changed=rc["changed"])
    full = await _next_action(env)              # bare == the un-collapsed push

    assert collapsed.get("no_change") is True
    assert "no_change" not in full and full["kind"] == "wait"
    assert "context" in full                    # the expensive re-grounding push

    collapsed_tokens = _token_count(collapsed)
    full_tokens = _token_count(full)
    ratio = full_tokens / collapsed_tokens

    # order-of-magnitude reduction per idle tick (ticks/hour constant -> this IS
    # the idle-hour drop). Real tiktoken count, not a proxy.
    assert ratio >= TOKEN_DROP_FLOOR, (
        f"idle-tick token drop only {ratio:.1f}x "
        f"(full={full_tokens} tok, collapsed={collapsed_tokens} tok); "
        f"expected >= {TOKEN_DROP_FLOOR:.0f}x"
    )
