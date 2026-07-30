"""P5 — proactive comms: whoami lineage, status_ping, ask_above routing.

- whoami().lineage gives every shell its place in the recipe tree (own
  lineage only — no global registry).
- status_ping is the cheap heartbeat-tick child check.
- ask_above(audience='neuron') routes a decision-class question straight
  to the neuron with an fyi CC to the parent planner — the fix for the
  planner absorbing questions it cannot answer.
"""

from edp_contracts import ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _scaffold(env):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="work"))
    return rid, sid, pid


# ── whoami lineage ──────────────────────────────────────────────────────────

async def test_whoami_worker_lineage(env, monkeypatch):
    rid, _, pid = await _scaffold(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    got = _ok(await env.call("whoami"))
    assert got["self_address"] == f"{pid}:a1"
    assert got["parent_address"] == pid
    assert got["recipe_id"] == rid
    lin = got["lineage"]
    assert lin["plan_id"] == pid and lin["planner_address"] == pid
    assert lin["action_id"] == "a1"
    assert lin["neuron_address"] == rid


async def test_whoami_planner_lineage_dash_gotcha(env, monkeypatch):
    rid, sid, pid = await _scaffold(env)
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:{sid}")
    monkeypatch.setenv("EDP_ROLE", "planner")
    got = _ok(await env.call("whoami"))
    assert got["self_address"] == pid          # DASH form, not the colon handle
    assert got["recipe_id"] == rid
    assert got["lineage"]["step_id"] == sid
    assert got["lineage"]["neuron_address"] == rid


async def test_whoami_neuron_has_no_lineage(env, monkeypatch):
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.delenv("EDP_ROLE", raising=False)
    got = _ok(await env.call("whoami"))
    assert got["self_address"] is None and got["lineage"] == {}


# ── status_ping ─────────────────────────────────────────────────────────────

async def test_status_ping_worker_handle(env, monkeypatch):
    _, _, pid = await _scaffold(env)
    env.ctx.plans.append_worklog(pid, {"kind": "action_status_change",
                                       "action_id": "a1"})

    async def dead(handle):
        return {"state": "dead", "last_output_ts": None}  # W7 dict (a2)
    monkeypatch.setattr(env.ctx.pool, "liveness", dead)
    got = _ok(await env.call("status_ping", handle=f"{pid}:a1"))
    assert got["liveness"] == "dead"
    assert got["action_status"] == "pending"
    assert got["last_worklog_kind"] == "action_status_change"
    # W7 item 1: wait_hint is now MINUTES (int); the liveness prose moved to
    # liveness_note (dead → idle wrap-up band, 30 min).
    assert isinstance(got["wait_hint"], int)
    assert "pool_reap" in got["liveness_note"]
    # no bodies / no tail list in the payload — this is the cheap check
    assert "recent" not in got


async def test_status_ping_planner_handle_dash_resolution(env, monkeypatch):
    rid, sid, pid = await _scaffold(env)

    async def alive(handle):
        return {"state": "alive", "last_output_ts": None}  # W7 dict (a2)
    monkeypatch.setattr(env.ctx.pool, "liveness", alive)
    got = _ok(await env.call("status_ping", handle=f"{rid}:{sid}"))
    assert got["liveness"] == "alive"
    assert got["last_worklog_kind"] is not None   # read via the dash plan
    # W7 item 1: the liveness prose moved from wait_hint (now int minutes) to
    # liveness_note.
    assert isinstance(got["wait_hint"], int)
    assert "do NOT force-fail" in got["liveness_note"]


# ── ask_above routing ───────────────────────────────────────────────────────

async def test_ask_above_default_goes_to_parent(env, monkeypatch):
    _, _, pid = await _scaffold(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _ok(await env.call("ask_above", question="which dep order?"))
    msgs = await env.ctx.broker.poll(pid, since_ts=None)
    assert any(x.kind == "question" and "dep order" in str(x.body)
               for x in msgs)


async def test_ask_above_neuron_routes_direct_with_planner_cc(env,
                                                              monkeypatch):
    rid, _, pid = await _scaffold(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _ok(await env.call("ask_above", audience="neuron",
                       question="does the goal allow paid datasets?"))
    # the question lands at the NEURON's inbox (the recipe id)
    neuron_msgs = await env.ctx.broker.poll(rid, since_ts=None)
    q = [x for x in neuron_msgs if x.kind == "question"]
    assert len(q) == 1 and "paid datasets" in str(q[0].body)
    assert q[0].from_ == f"{pid}:a1"      # reply(msg_id) routes back to worker
    # the planner got an fyi CC, not the question itself
    planner_msgs = await env.ctx.broker.poll(pid, since_ts=None)
    assert any(x.kind == "fyi" and "routed directly" in str(x.body)
               for x in planner_msgs)
    assert not any(x.kind == "question" for x in planner_msgs)


async def test_ask_above_neuron_from_planner_is_just_parent(env,
                                                            monkeypatch):
    rid, sid, _ = await _scaffold(env)
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:{sid}")
    monkeypatch.setenv("EDP_ROLE", "planner")
    _ok(await env.call("ask_above", audience="neuron",
                       question="scope question"))
    msgs = await env.ctx.broker.poll(rid, since_ts=None)
    qs = [x for x in msgs if x.kind == "question"]
    assert len(qs) == 1                    # one question, no duplicate CC
    assert not any(x.kind == "fyi" for x in msgs)
