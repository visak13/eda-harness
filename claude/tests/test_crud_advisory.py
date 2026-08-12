"""P3 — full CRUD + advisory FSM.

Steps become editable + deletable, actions deletable, acceptance_review
plans reopenable; risky-but-legal mutations PROCEED with `advisories`
(warning + audit-trail record) instead of refusing. Hard blocks remain for
terminal-state mutation and deleting under a LIVE shell.

NOTE: this deliberately retires the old behavior locked in by
_CATALOG["step"]'s APPEND-ONLY note — the honest history now lives in the
audit trail (step_deleted / advisory_override records), not in immutable
steps.
"""

from edp_contracts import ToolOk

from edp_claude import objects


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _recipe_with_steps(env, n=2):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    sids = []
    for i in range(n):
        sids.append(_ok(await env.call(
            "add_step", recipe_id=rid, description=f"step {i}",
            execution="spawn_planner", estimate={"hours": 1}))["step_id"])
    return rid, sids


async def _plan_with_actions(env, rid, sid, aids=("a1", "a2")):
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    for aid in aids:
        _ok(await env.call("add_action", plan_id=pid, action_id=aid,
                           description="work"))
    return pid


# ── step update ─────────────────────────────────────────────────────────────

async def test_step_edit_in_place(env):
    rid, (s1, s2) = await _recipe_with_steps(env)
    got = _ok(await env.call(
        "update_object", type="step", ids={"recipe_id": rid, "step_id": s2},
        patch={"description": "REVISED direction", "depends_on": [s1]}))
    res = got["result"]
    assert res["ok"] and sorted(res["updated"]) == ["depends_on",
                                                    "description"]
    r = env.ctx.recipes.load(rid)
    step = next(s for s in r.steps if s.step_id == s2)
    assert step.description == "REVISED direction"
    assert step.depends_on == [s1]


async def test_step_edit_in_flight_returns_advisory_and_audit(env):
    rid, (s1, _) = await _recipe_with_steps(env)
    r = env.ctx.recipes.load(rid)
    next(s for s in r.steps if s.step_id == s1).status = "in_progress"
    env.ctx.recipes.save(r)
    got = _ok(await env.call(
        "update_object", type="step", ids={"recipe_id": rid, "step_id": s1},
        patch={"description": "changed under a planner"}))
    res = got["result"]
    assert res["ok"]
    advisories = res.get("advisories") or []
    assert any(a["code"] == "edit_in_flight" for a in advisories)
    events = (env.ctx.recipes.root / rid / "events.jsonl").read_text(
        encoding="utf-8")
    assert "advisory_override" in events and "update_step" in events


async def test_step_update_rejects_unknown_fields(env):
    rid, (s1, _) = await _recipe_with_steps(env)
    res = await env.call("update_object", type="step",
                         ids={"recipe_id": rid, "step_id": s1},
                         patch={"bogus": 1})
    assert not isinstance(res, ToolOk)


# ── step delete ─────────────────────────────────────────────────────────────

async def test_delete_step_rewrites_dependents(env):
    rid, (s1, s2) = await _recipe_with_steps(env)
    _ok(await env.call("update_object", type="step",
                       ids={"recipe_id": rid, "step_id": s2},
                       patch={"depends_on": [s1]}))
    got = _ok(await env.call("delete_object", type="step",
                             ids={"recipe_id": rid, "step_id": s1},
                             reason="obsolete scope"))
    res = got["result"]
    assert res["ok"] and res["deleted"] == s1
    codes = [a["code"] for a in res.get("advisories", [])]
    assert "dependents_rewritten" in codes
    r = env.ctx.recipes.load(rid)
    assert [s.step_id for s in r.steps] == [s2]
    assert next(s for s in r.steps if s.step_id == s2).depends_on == []
    events = (env.ctx.recipes.root / rid / "events.jsonl").read_text(
        encoding="utf-8")
    assert "step_deleted" in events and "obsolete scope" in events


async def test_delete_last_step_past_comprehension_refused(env):
    rid, (s1, s2) = await _recipe_with_steps(env)
    r = env.ctx.recipes.load(rid)
    r.state = "planning"
    env.ctx.recipes.save(r)
    _ok(await env.call("delete_object", type="step",
                       ids={"recipe_id": rid, "step_id": s1}, reason="x"))
    got = _ok(await env.call("delete_object", type="step",
                             ids={"recipe_id": rid, "step_id": s2},
                             reason="x"))
    res = got["result"]
    assert res["ok"] is False and "LAST step" in res["error"]


async def test_delete_in_progress_step_with_live_planner_refused(env,
                                                                 monkeypatch):
    rid, (s1, _) = await _recipe_with_steps(env)
    r = env.ctx.recipes.load(rid)
    next(s for s in r.steps if s.step_id == s1).status = "in_progress"
    env.ctx.recipes.save(r)

    async def alive(handle):
        return {"state": "alive", "last_output_ts": None}  # W7 dict (a2)
    monkeypatch.setattr(env.ctx.pool, "liveness", alive)
    got = _ok(await env.call("delete_object", type="step",
                             ids={"recipe_id": rid, "step_id": s1},
                             reason="x"))
    res = got["result"]
    assert res["ok"] is False and "LIVE planner" in res["error"]


# ── action delete ───────────────────────────────────────────────────────────

async def test_delete_action_rewrites_dependents_and_audits(env):
    rid, (s1, _) = await _recipe_with_steps(env)
    pid = await _plan_with_actions(env, rid, s1)
    _ok(await env.call("update_object", type="action",
                       ids={"plan_id": pid, "action_id": "a2"},
                       patch={"depends_on": ["a1"]}))
    got = _ok(await env.call("delete_object", type="action",
                             ids={"plan_id": pid, "action_id": "a1"},
                             reason="wrongly authored"))
    res = got["result"]
    assert res["ok"]
    assert "dependents_rewritten" in [a["code"]
                                      for a in res.get("advisories", [])]
    p = env.ctx.plans.load(pid)
    assert [a.action_id for a in p.actions] == ["a2"]
    assert p.actions[0].depends_on == []
    log = (env.ctx.plans.root / pid / "worklog.jsonl").read_text(
        encoding="utf-8")
    assert "action_deleted" in log and "wrongly authored" in log


async def test_delete_done_action_proceeds_with_evidence_digest(env):
    rid, (s1, _) = await _recipe_with_steps(env)
    pid = await _plan_with_actions(env, rid, s1, aids=("a1",))
    p = env.ctx.plans.load(pid)
    p.actions[0].status = "done"
    p.actions[0].acceptance.actual = "the recorded evidence " * 20
    env.ctx.plans.save(p)
    got = _ok(await env.call("delete_object", type="action",
                             ids={"plan_id": pid, "action_id": "a1"},
                             reason="superseded"))
    res = got["result"]
    assert res["ok"]
    assert "deleting_done_action" in [a["code"]
                                      for a in res.get("advisories", [])]
    log = (env.ctx.plans.root / pid / "worklog.jsonl").read_text(
        encoding="utf-8")
    assert "evidence_digest" in log


async def test_delete_in_progress_action_live_worker_refused(env,
                                                             monkeypatch):
    rid, (s1, _) = await _recipe_with_steps(env)
    pid = await _plan_with_actions(env, rid, s1, aids=("a1",))
    p = env.ctx.plans.load(pid)
    p.actions[0].status = "in_progress"
    env.ctx.plans.save(p)

    async def alive(handle):
        return {"state": "alive", "last_output_ts": None}  # W7 dict (a2)
    monkeypatch.setattr(env.ctx.pool, "liveness", alive)
    got = _ok(await env.call("delete_object", type="action",
                             ids={"plan_id": pid, "action_id": "a1"},
                             reason="x"))
    res = got["result"]
    assert res["ok"] is False and "LIVE worker" in res["error"]


async def test_delete_action_terminal_plan_hard_blocked(env):
    rid, (s1, _) = await _recipe_with_steps(env)
    pid = await _plan_with_actions(env, rid, s1, aids=("a1",))
    p = env.ctx.plans.load(pid)
    p.actions[0].status = "done"
    p.state = "terminal"
    p.terminal_status = "succeeded"
    env.ctx.plans.save(p)
    got = _ok(await env.call("delete_object", type="action",
                             ids={"plan_id": pid, "action_id": "a1"},
                             reason="x"))
    res = got["result"]
    assert res["ok"] is False and "terminal" in res["error"]


# ── add_action reopen ───────────────────────────────────────────────────────

async def test_add_action_reopens_acceptance_review_with_advisory(env):
    rid, (s1, _) = await _recipe_with_steps(env)
    pid = await _plan_with_actions(env, rid, s1, aids=("a1",))
    p = env.ctx.plans.load(pid)
    p.actions[0].status = "done"
    p.state = "acceptance_review"
    env.ctx.plans.save(p)
    got = _ok(await env.call("add_action", plan_id=pid, action_id="a2",
                             description="the missing leg"))
    advisories = got.get("advisories") or []
    assert any(a["code"] == "plan_reopened" for a in advisories)
    p2 = env.ctx.plans.load(pid)
    assert str(getattr(p2.state, "value", p2.state)) == "dispatching"
    assert [a.action_id for a in p2.actions] == ["a1", "a2"]


async def test_add_action_terminal_plan_still_refused(env):
    rid, (s1, _) = await _recipe_with_steps(env)
    pid = await _plan_with_actions(env, rid, s1, aids=("a1",))
    p = env.ctx.plans.load(pid)
    p.actions[0].status = "done"
    p.state = "terminal"
    p.terminal_status = "succeeded"
    env.ctx.plans.save(p)
    res = await env.call("add_action", plan_id=pid, action_id="a2",
                         description="too late")
    assert not isinstance(res, ToolOk)


# ── catalog honesty ─────────────────────────────────────────────────────────

async def test_catalog_advertises_new_ops(env):
    d = _ok(await env.call("describe_objects", name="step"))["doc"]
    assert "update, delete" in d and "advisor" in d.lower()
    assert "a step is not patchable" not in d   # the old refusal note is gone
    d2 = _ok(await env.call("describe_objects", name="action"))["doc"]
    assert "delete" in d2


# ── mid-flight step creation is the EXPENSIVE answer ────────────────────────
# Operator ruling 2026-07-26, after a recipe answered three mid-flight
# discoveries by creating three new steps and visibly dragged. `add_step` is
# the EASIEST verb to reach for and the MOST expensive to execute — planner
# spawn + plan authored cold + N workers + review legs + rebuild, hours —
# while update_object on a pending step costs seconds. The surface biased the
# caller toward the costly option and said nothing, so the cost was a silent
# schedule decision. Advisory rather than refusal, per this module's own
# philosophy: guards WARN, hard blocks are for the genuinely unsafe, and a
# late step is expensive rather than unsafe (a refusal also breaks the
# legitimate reopen-on-add flows).

async def test_declaring_steps_up_front_is_frictionless(env):
    """The lifecycle spine (R4) says declare known steps up front. That path
    must stay silent — a warning on every step is a warning on none."""
    rid, _ = await _recipe_with_steps(env, n=2)
    out = _ok(await env.call("add_step", recipe_id=rid, description="third",
                             execution="spawn_planner", estimate={"hours": 1}))
    assert out.get("advisories") in (None, []), out
    assert "MID-FLIGHT" not in (out.get("note") or "")


async def test_mid_flight_step_warns_with_the_cheaper_alternatives(env):
    """Once execution has begun a new step is a SCOPE CHANGE discovered late.
    It still proceeds — but the cost and the cheaper routes must arrive AT THE
    MOMENT OF THE DECISION, which is the point a guide can never reach,
    because a guide is read before the work and this fires during it."""
    rid, (s1, s2) = await _recipe_with_steps(env)
    r = env.ctx.recipes.load(rid)
    r.state = "executing"
    env.ctx.recipes.save(r)

    out = _ok(await env.call("add_step", recipe_id=rid,
                             description="a gap found mid-flight",
                             execution="spawn_planner", estimate={"hours": 1}))
    adv = " ".join(out.get("advisories") or [])
    assert "UNJUSTIFIED" in adv, out
    # the cheaper escalation order must travel WITH the warning
    assert "update_object" in adv and "ADD AN ACTION" in adv, adv
    # and it must name the actual pending steps that could take the work
    assert s1 in adv and s2 in adv, adv
    assert "CRITICAL PATH" in (out.get("note") or "").upper(), out


async def test_mid_flight_step_with_justification_records_it(env):
    rid, _ = await _recipe_with_steps(env)
    r = env.ctx.recipes.load(rid)
    r.state = "executing"
    env.ctx.recipes.save(r)

    out = _ok(await env.call(
        "add_step", recipe_id=rid, description="a real new capability",
        execution="spawn_planner", estimate={"hours": 1},
        justification="distinct user-visible feature; no step can own it"))
    adv = " ".join(out.get("advisories") or [])
    assert "UNJUSTIFIED" not in adv, adv
    assert "distinct user-visible feature" in adv, adv


async def test_mid_flight_step_depending_on_another_gets_THE_TELL(env):
    """The tell that the split was wrong: 'it needs X, and X is another
    step's subject' argues for building it INSIDE X. This is the exact
    mistake the ruling came from, so the tool names it."""
    rid, (s1, _s2) = await _recipe_with_steps(env)
    r = env.ctx.recipes.load(rid)
    r.state = "executing"
    env.ctx.recipes.save(r)

    out = _ok(await env.call("add_step", recipe_id=rid, description="join",
                             execution="spawn_planner", estimate={"hours": 1}, depends_on=[s1],
                             justification="needs the thing s1 builds"))
    adv = " ".join(out.get("advisories") or [])
    assert "THE TELL" in adv and s1 in adv, adv
    assert "INSIDE" in adv, adv


async def test_action_acceptance_fields_now_patchable(env):
    rid, (s1, _) = await _recipe_with_steps(env)
    pid = await _plan_with_actions(env, rid, s1, aids=("a1",))
    _ok(await env.call("update_object", type="action",
                       ids={"plan_id": pid, "action_id": "a1"},
                       patch={"acceptance_kind": "metric",
                              "acceptance_expected": "p95 < 100ms",
                              "executor_mode": "inline"}))
    a = env.ctx.plans.load(pid).actions[0]
    assert a.acceptance.kind == "metric"
    assert a.acceptance.expected == "p95 < 100ms"
    assert a.executor_mode == "inline"
