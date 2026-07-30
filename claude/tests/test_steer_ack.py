"""DESIGN-v7 P3.2 — steer acknowledgment + silence detection.

A steer is the least-checked artifact in the system (d130): it lands in an
inbox and can be absorbed without consumption, and the sender has no signal.
The defense, in code:

  * `broker_send(kind="steer")` durably records the send (msg_id + recipient)
    — in the sender's plan worklog (planner/worker) or the recipe events
    trail (neuron, which has no plan worklog);
  * `reconcile` correlates those records with inbound `steer_ack`s on the
    sender's own inbox and surfaces every steer past the grace window with
    no ack, BY NAME — "absorbed unread" becomes visible instead of silent.

Kept fast (in-memory stubs, no LLM — principle 6).
"""

from datetime import datetime, timezone

from edp_contracts import ToolOk

from edp_claude.schemas import Plan, Recipe

RID = "recipe-steer"
SID = "s1"
PID = f"{RID}-{SID}"
OLD_TS = "2020-01-01T00:00:00+00:00"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _save_plan(env):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=PID, recipe_id=RID, recipe_step_id=SID, domain="generic",
        shape="x", goal="g", state="dispatching",
        actions=[dict(action_id="a1", description="do a1",
                      status="in_progress", depends_on=[],
                      executor_mode="subagent",
                      acceptance={"kind": "tests_pass"})],
    )))


def _save_recipe(env):
    now = datetime.now(timezone.utc)
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=RID, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": SID, "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={}, created_at=now, updated_at=now,
    )))


# ── the send is durably recorded ─────────────────────────────────────────────
async def test_planner_steer_send_lands_in_the_plan_worklog(env, monkeypatch):
    _save_plan(env)
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", f"{RID}:{SID}")
    _ok(await env.call("broker_send", to=f"{PID}:a1", kind="steer",
                       body={"correction": "write to src/, not docs/"}))
    lines = [ln for ln in env.ctx.plans.read_worklog(PID, tail=50)
             if ln.get("msg_kind") == "steer"]
    assert lines and lines[-1]["msg_id"], "steer send left no durable record"
    assert lines[-1]["to"] == f"{PID}:a1"


async def test_neuron_steer_send_lands_in_the_recipe_events(env):
    _save_recipe(env)
    # conftest clears EDP_ROLE/EDP_HANDLE — this is the neuron surface.
    _ok(await env.call("broker_send", to=PID, kind="steer",
                       body={"correction": "scope moved"}))
    evs = env.ctx.recipes.read_events_tail(RID, kinds=["steer_sent"])
    assert evs and evs[-1]["msg_id"], "neuron steer left no durable record"
    assert evs[-1]["to"] == PID


# ── the silence detector ─────────────────────────────────────────────────────
async def test_stale_unacked_steer_surfaces_in_recipe_reconcile(env):
    _save_recipe(env)
    env.ctx.recipes.append_worklog(RID, {
        "ts": OLD_TS, "kind": "steer_sent", "msg_id": "m-123", "to": PID,
    })
    res = _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    adv = res.get("unacked_steers") or ""
    assert "UNACKED STEERS" in adv and "m-123" in adv, res


async def test_acked_steer_is_silent(env):
    _save_recipe(env)
    env.ctx.recipes.append_worklog(RID, {
        "ts": OLD_TS, "kind": "steer_sent", "msg_id": "m-123", "to": PID,
    })
    # the receiver acknowledged: a steer_ack naming the msg_id, addressed to
    # the SENDER's inbox (the recipe_id — the neuron's inbox).
    _ok(await env.call("broker_send", to=RID, kind="steer_ack",
                       body={"restatement": "scope moved to X",
                             "steer_msg_id": "m-123"}))
    res = _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    assert "UNACKED" not in (res.get("unacked_steers") or ""), res


async def test_fresh_steer_inside_grace_window_is_silent(env):
    _save_recipe(env)
    env.ctx.recipes.append_worklog(RID, {
        "kind": "steer_sent", "msg_id": "m-fresh", "to": PID,   # ts = now
    })
    res = _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    assert "UNACKED" not in (res.get("unacked_steers") or ""), res


async def test_planner_reconcile_surfaces_its_own_unacked_steer(
        env, monkeypatch):
    _save_plan(env)
    env.ctx.plans.append_worklog(PID, {
        "ts": OLD_TS, "kind": "message_sent", "msg_kind": "steer",
        "msg_id": "m-777", "to": f"{PID}:a1", "agent_role": "planner",
    })
    res = _ok(await env.call("reconcile", handle=PID, handle_type="plan"))
    adv = res.get("unacked_steers") or ""
    assert "UNACKED STEERS" in adv and "m-777" in adv, res
