"""Object model — read-side CRUD (OBJECT-MODEL.md increment 1).

describe_objects (schema docs) + read_object (one) + query_objects
(filtered list) over the domain: mutate objects (recipe/plan/action/
step/outcome/neuron/spec) read here, inspect-only (session/lock/
message/worklog) read/query only.
"""

from datetime import datetime, timezone

from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Plan, Recipe


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _recipe(env, rid="r-obj", state="executing"):
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state=state,
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "doc", "verification": "v"},
            {"id": "o2", "description": "tests", "verification": "v",
             "met": True, "met_evidence": "passed"}]},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))
    return rid


def _plan(env, pid="r-obj-s1", actions=()):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id="r-obj", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=list(actions), context={},
    )))
    return pid


def _a(aid, status="pending"):
    return {"action_id": aid, "description": "d", "status": status,
            "depends_on": [], "executor_mode": "subagent",
            "acceptance": {"kind": "manual_review"}}


# ── describe_objects ───────────────────────────────────────────────────────
async def test_describe_index_lists_both_classes(env):
    d = _ok(await env.call("describe_objects"))["doc"].lower()
    assert "mutate" in d and "inspect-only" in d
    for o in ("recipe", "plan", "action", "session", "lock", "message",
              "worklog", "neuron", "spec"):
        assert f"`{o}`" in d
    assert "read_object" in d and "query_objects" in d


async def test_describe_one_object_has_fields(env):
    d = _ok(await env.call("describe_objects", name="action"))["doc"].lower()
    assert "action_id" in d and "verify" in d   # the new status appears
    assert "read" in d and "query" in d


async def test_describe_action_teaches_rx_and_capacity_rollback(env):
    # 2026-06-01 "rx not working": objects shipped with schema/CRUD only,
    # so the agent never learned to subscribe (fell back to polling) and
    # couldn't tell a capacity-blocked action from a phantom. The object
    # must now carry its rx plane + the when-to-use-which knowledge.
    d = _ok(await env.call("describe_objects", name="action"))["doc"].lower()
    assert "react (rx)" in d and "when to use which plane" in d
    assert "rx.worklog" in d and "rx.pool" in d
    # the exact knowledge the planner had to rediscover by hand:
    assert "capacity" in d and "pending" in d
    assert "phantom" in d and "legitimate" in d


async def test_describe_session_teaches_liveness_is_the_pools_truth(env):
    d = _ok(await env.call("describe_objects", name="session"))["doc"].lower()
    assert "react (rx)" in d and "rx.pool" in d
    assert "scope=" in d                       # the must-scope rule
    assert "alive" in d and "dead" in d and "unknown" in d


async def test_describe_message_teaches_subscribe_first(env):
    d = _ok(await env.call("describe_objects", name="message"))["doc"].lower()
    assert "rx.broker" in d
    assert "subscribe first" in d


async def test_describe_index_composes_the_liveness_question(env):
    # the cross-object composition (alive/queued/done/dead) that no single
    # field answers — surfaced on the index so it's never re-derived.
    d = _ok(await env.call("describe_objects"))["doc"].lower()
    assert "three planes" in d
    for state in ("alive", "queued", "done", "dead"):
        assert state in d
    assert "capacity" in d and "legitimate" in d   # the a3 case
    assert "reconcile" in d and "heartbeat" in d    # backstop framing


async def test_describe_exposes_state_machine(env):
    # FSM-RESPONSIBILITY Step 1: the deterministic progression is part of
    # the object TYPE — describe_objects renders the legal transitions so
    # the LLM mutates state correctly instead of re-deriving it.
    a = _ok(await env.call("describe_objects", name="action"))["doc"]
    assert "state machine" in a.lower()
    assert "pending -> in_progress" in a
    assert "in_progress -> verify, done, failed, pending" in a
    assert "verify -> done, failed" in a
    assert "done -> (terminal)" in a
    r = _ok(await env.call("describe_objects", name="recipe"))["doc"]
    assert "executing -> planning" in r and "reviewing -> planning, closed" in r
    p = _ok(await env.call("describe_objects", name="plan"))["doc"]
    assert "drafted -> dispatching" in p
    # objects without a fixed state machine don't render one
    s = _ok(await env.call("describe_objects", name="session"))["doc"]
    assert "state machine" not in s.lower()


async def test_describe_states_honest_ops(env):
    # 2026-05-30: the catalog advertised plan/step as full CRUD but they
    # error on query/update. describe_objects must now surface the REAL
    # ops + the gotcha note so the agent never guesses.
    # 2026-08-21 tool-doc overhaul: plan-LEVEL fields became patchable
    # (shape/goal/review_policy/test_budget) — ops honestly says update
    # now, and the note teaches the patchable set. Query stays absent.
    idx = _ok(await env.call("describe_objects"))["doc"]
    assert "[read, create, update]" in idx       # plan: still no query
    plan = _ok(await env.call("describe_objects", name="plan"))["doc"]
    assert "read, create, update" in plan
    assert "review_policy" in plan               # the patchable set taught
    assert "action" in plan.lower()              # action fields via 'action'
    step = _ok(await env.call("describe_objects", name="step"))["doc"]
    assert "append-only" in step.lower()


async def test_query_unsupported_object_is_consumable_error(env):
    # plan has no cross-list query — must be a clear ToolError, not a hang.
    res = await env.call("query_objects", type="plan", where={})
    assert isinstance(res, ToolError)
    assert "plan" in res.message


# ── read_object (mutate objects) ───────────────────────────────────────────
async def test_read_recipe_plan_action_outcome(env):
    _recipe(env)
    _plan(env, actions=[_a("a1", status="done"), _a("a2", status="verify")])
    r = _ok(await env.call("read_object", type="recipe",
                           ids={"recipe_id": "r-obj"}))["object"]
    assert r["recipe_id"] == "r-obj" and r["state"] == "executing"
    a = _ok(await env.call("read_object", type="action",
                           ids={"plan_id": "r-obj-s1",
                                "action_id": "a2"}))["object"]
    assert a["status"] == "verify"
    o = _ok(await env.call("read_object", type="outcome",
                           ids={"recipe_id": "r-obj",
                                "outcome_id": "o2"}))["object"]
    assert o["met"] is True


async def test_read_missing_returns_null(env):
    out = _ok(await env.call("read_object", type="plan",
                             ids={"plan_id": "nope"}))
    assert out["object"] is None


async def test_read_missing_id_is_precondition(env):
    res = await env.call("read_object", type="action", ids={"plan_id": "x"})
    assert isinstance(res, ToolError)
    assert "action_id" in res.message


async def test_unknown_object_type_refused(env):
    res = await env.call("read_object", type="wat", ids={})
    assert isinstance(res, ToolError)
    assert "unknown object" in res.message


# ── query_objects (mutate) ─────────────────────────────────────────────────
async def test_query_recipe_by_state(env):
    _recipe(env, "r-exec", state="executing")
    _recipe(env, "r-rev", state="reviewing")
    out = _ok(await env.call("query_objects", type="recipe",
                             where={"state": "executing"}))["objects"]
    ids = {r["recipe_id"] for r in out}
    assert "r-exec" in ids and "r-rev" not in ids


async def test_query_actions_by_status_within_plan(env):
    _recipe(env)
    _plan(env, actions=[_a("a1", status="done"), _a("a2", status="verify"),
                        _a("a3", status="verify")])
    out = _ok(await env.call("query_objects", type="action",
                             where={"status": "verify"},
                             scope={"plan_id": "r-obj-s1"}))["objects"]
    assert {a["action_id"] for a in out} == {"a2", "a3"}


async def test_query_outcomes_unmet(env):
    _recipe(env)
    out = _ok(await env.call("query_objects", type="outcome",
                             where={"met": False},
                             scope={"recipe_id": "r-obj"}))["objects"]
    assert [o["id"] for o in out] == ["o1"]


# ── a3: count-first windowing (bounds the token blowout by construction) ────
async def test_query_objects_windows_with_count_cursor_and_paging(env):
    # a plan with more than one WINDOW of actions: the default query returns a
    # bounded page (<=WINDOW) but reports the FULL count + a cursor to page on,
    # so an unscoped/large query can't dump everything and blow the budget.
    from edp_claude.tools._bounds import WINDOW
    _recipe(env)
    n = WINDOW + 7
    _plan(env, actions=[_a(f"a{i}", status="pending") for i in range(n)])
    res = _ok(await env.call("query_objects", type="action",
                             where={"status": "pending"},
                             scope={"plan_id": "r-obj-s1"}))
    assert len(res["objects"]) == WINDOW      # bounded slice, still a list
    assert res["count"] == n                  # full match total surfaced
    assert res["offset"] == 0 and res["cursor"] == WINDOW
    assert res["elided"] == n - WINDOW
    # page 2: resume from the cursor → the remainder, cursor now None (end)
    res2 = _ok(await env.call("query_objects", type="action",
                              where={"status": "pending"},
                              scope={"plan_id": "r-obj-s1"}, offset=WINDOW))
    assert len(res2["objects"]) == n - WINDOW and res2["cursor"] is None
    # full fidelity is one wide-limit call away
    allres = _ok(await env.call("query_objects", type="action",
                                where={"status": "pending"},
                                scope={"plan_id": "r-obj-s1"}, limit=1000))
    assert len(allres["objects"]) == n and allres["cursor"] is None


async def test_query_small_result_unwindowed(env):
    # the common case (well under a WINDOW) is unaffected: every match returns,
    # cursor is None, count == len(objects).
    _recipe(env)
    _plan(env, actions=[_a("a1", status="verify"), _a("a2", status="verify")])
    res = _ok(await env.call("query_objects", type="action",
                             where={"status": "verify"},
                             scope={"plan_id": "r-obj-s1"}))
    assert {a["action_id"] for a in res["objects"]} == {"a1", "a2"}
    assert res["count"] == 2 and res["cursor"] is None and res["elided"] == 0


async def test_read_recipe_digest_windows_steps_and_decisions(env):
    # a recipe with more than one WINDOW of steps AND decisions: the digest
    # caps each projection to <=WINDOW (still a plain list) and adds a
    # count/cursor sibling; the full read is unbounded.
    from edp_claude.tools._bounds import WINDOW
    n = WINDOW + 5
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id="r-win", user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": f"s{i}", "kind": "k", "description": f"step {i}",
                "status": "pending", "depends_on": [],
                "execution": "spawn_planner"} for i in range(n)],
        context={"decisions": [
            {"id": f"d{i}", "text": f"DECISION {i}. body", "rationale": "r",
             "by": "neuron", "at": datetime.now(timezone.utc).isoformat(),
             "load_bearing": False} for i in range(n)]},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))
    d = _ok(await env.call("read_object", type="recipe",
                           ids={"recipe_id": "r-win"},
                           detail="digest"))["object"]
    assert isinstance(d["steps"], list) and len(d["steps"]) == WINDOW
    assert d["steps_count"] == n and d["steps_cursor"] == WINDOW
    dec = d["context"]["decisions"]
    assert isinstance(dec, list) and len(dec) == WINDOW
    assert d["context"]["decisions_count"] == n
    assert d["context"]["decisions_cursor"] == WINDOW
    # detail='full' still returns every step + decision (fidelity preserved)
    full = _ok(await env.call("read_object", type="recipe",
                              ids={"recipe_id": "r-win"}))["object"]
    assert len(full["steps"]) == n
    assert len(full["context"]["decisions"]) == n


# ── inspect-only: session / lock / worklog ─────────────────────────────────
async def test_query_sessions_and_locks(env):
    _recipe(env)
    pid = _plan(env, actions=[_a("a1", status="in_progress")])
    await env.ctx.pool.spawn_worker(pid, "a1")
    sess = _ok(await env.call("query_objects", type="session",
                              where={"role": "worker"}))["objects"]
    assert any(s["handle"] == f"{pid}:a1" for s in sess)
    locks = _ok(await env.call("query_objects", type="lock"))["objects"]
    assert any(lk["handle"] == f"{pid}:a1" for lk in locks)


async def test_query_sessions_scoped_to_recipe(env):
    # two recipes' shells in the pool; scope must return only the target
    # recipe's (the 2026-05-29 unscoped-query bug returned ALL recipes').
    await env.ctx.pool.spawn_planner("rA", "s1")        # handle rA:s1
    await env.ctx.pool.spawn_worker("rA-s1", "a1")      # handle rA-s1:a1
    await env.ctx.pool.spawn_planner("rB", "s1")        # handle rB:s1
    sess = _ok(await env.call("query_objects", type="session",
                              scope={"recipe_id": "rA"}))["objects"]
    handles = {s["handle"] for s in sess}
    assert handles == {"rA:s1", "rA-s1:a1"}             # rB excluded
    # plan scope narrows to just that plan's worker(s)
    psess = _ok(await env.call("query_objects", type="session",
                               scope={"plan_id": "rA-s1"}))["objects"]
    assert {s["handle"] for s in psess} == {"rA-s1:a1"}  # planner excluded
    # where + scope compose
    workers = _ok(await env.call("query_objects", type="session",
                                 where={"role": "worker"},
                                 scope={"recipe_id": "rA"}))["objects"]
    assert {s["handle"] for s in workers} == {"rA-s1:a1"}


async def test_query_locks_scoped_to_recipe(env):
    await env.ctx.pool.spawn_worker("rA-s1", "a1")
    await env.ctx.pool.spawn_planner("rB", "s1")
    locks = _ok(await env.call("query_objects", type="lock",
                               scope={"recipe_id": "rA"}))["objects"]
    assert {lk["handle"] for lk in locks} == {"rA-s1:a1"}


async def test_read_session_carries_liveness(env):
    _recipe(env)
    pid = _plan(env, actions=[_a("a1", status="in_progress")])
    await env.ctx.pool.spawn_worker(pid, "a1")
    s = _ok(await env.call("read_object", type="session",
                           ids={"handle": f"{pid}:a1"}))["object"]
    assert s["liveness"] == "alive"


async def test_query_worklog_by_kind(env):
    _recipe(env)
    pid = _plan(env, actions=[_a("a1", status="in_progress")])
    # d30: the record path runs no gate and emits no gate worklog, so seed
    # worklog entries directly to exercise the query-by-kind filter surface.
    env.ctx.plans.append_worklog(pid, {"kind": "dispatch_failed",
                                        "action_id": "a1", "detail": "x"})
    env.ctx.plans.append_worklog(pid, {"kind": "plan_saved"})
    rows = _ok(await env.call("query_objects", type="worklog",
                              where={"kind": "dispatch_failed"},
                              scope={"plan_id": pid}))["objects"]
    assert len(rows) >= 1 and rows[0]["kind"] == "dispatch_failed"


# ── inspect-only: message cross-query (increment 3) ────────────────────────
async def test_query_messages_cross_inbox(env):
    from datetime import datetime, timezone

    from edp_contracts import BrokerMessage
    for mid, to, frm, kind in (("a", "neuron:r1", "p:1", "done"),
                               ("b", "planner:p7", "neuron:r1", "question")):
        await env.ctx.broker.send(BrokerMessage(
            msg_id=mid, ts=datetime.now(timezone.utc),
            **{"from": frm}, to=to, kind=kind, body={}))
    # no `to` → scans every inbox
    allm = _ok(await env.call("query_objects", type="message"))["objects"]
    assert {m["msg_id"] for m in allm} == {"a", "b"}
    # server-side from+kind filter
    q = _ok(await env.call("query_objects", type="message",
                           where={"kind": "question"}))["objects"]
    assert [m["msg_id"] for m in q] == ["b"]


# ── memory object (promoted to the CRUD surface, 2026-05-30) ───────────────
async def test_memory_create_then_query_and_read(env):
    # create = remember (durable fact passes the SE kg_filter gate)
    out = _ok(await env.call("create_object", type="memory", fields={
        "text": "react hooks must run unconditionally at the top level",
        "domain": "software_engineering"}))["result"]
    assert out.get("stored") is True
    # query = fuzzy recall (every word must appear)
    hits = _ok(await env.call("query_objects", type="memory",
                              where={"query": "react hooks"}))["objects"]
    assert len(hits) == 1 and "hooks" in hits[0]["text"]
    miss = _ok(await env.call("query_objects", type="memory",
                              where={"query": "vue composition"}))["objects"]
    assert miss == []
    # read = dump (optionally by domain)
    allf = _ok(await env.call("read_object", type="memory",
                              ids={"domain": "software_engineering"}))["object"]
    assert len(allf) == 1


async def test_memory_create_rejected_by_gate(env):
    # generic domain rejects unless explicitly durable → stored:false
    out = _ok(await env.call("create_object", type="memory", fields={
        "text": "let me think about this", "domain": "generic"}))["result"]
    assert out.get("stored") is False
    assert _ok(await env.call("read_object", type="memory",
                              ids={}))["object"] == []     # nothing stored


async def test_memory_update_refused_append_only(env):
    res = await env.call("update_object", type="memory",
                         ids={}, patch={"text": "x"})
    assert isinstance(res, ToolError)
    assert "append-only" in res.message


async def test_memory_in_describe_index(env):
    idx = _ok(await env.call("describe_objects"))["doc"].lower()
    assert "`memory`" in idx
    one = _ok(await env.call("describe_objects", name="memory"))["doc"].lower()
    assert "append-only" in one and "recall" in one


# ── create_object (write-side, increment 2) ────────────────────────────────
async def test_create_action_delegates_to_add_action(env):
    _recipe(env)
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id="r-obj-s1", recipe_id="r-obj", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="drafted",
        actions=[], context={})))
    out = _ok(await env.call("create_object", type="action", fields={
        "plan_id": "r-obj-s1", "action_id": "a9", "description": "new",
        "executor_mode": "subagent", "depends_on": [],
        "acceptance": {"kind": "manual_review"}}))["result"]
    assert out.get("ok") is True
    a = _ok(await env.call("read_object", type="action",
                           ids={"plan_id": "r-obj-s1",
                                "action_id": "a9"}))["object"]
    assert a["action_id"] == "a9" and a["status"] == "pending"


async def test_create_inspect_only_refused(env):
    res = await env.call("create_object", type="session",
                         fields={"handle": "x"})
    assert isinstance(res, ToolError)
    assert "inspect-only" in res.message


async def test_create_unknown_object_refused(env):
    res = await env.call("create_object", type="wat", fields={})
    assert isinstance(res, ToolError)
    assert "unknown object" in res.message


# ── update_object (write-side, increment 2) ────────────────────────────────
async def test_update_action_status_done_is_pure_write(env):
    # d30: routing a status=done patch through update_object → record_action_
    # status is a PURE WRITE — it runs no gate and lands `done` directly even
    # when the (retained, worker/reviewer-run) verify deliverable is absent.
    _recipe(env)
    pid = _plan(env, actions=[{
        "action_id": "a1", "description": "d", "status": "in_progress",
        "depends_on": [], "executor_mode": "subagent",
        "acceptance": {"kind": "file_exists",
                       "verify": {"check": "file_exists",
                                  "path": "/no/such/x"}}}])
    out = _ok(await env.call("update_object", type="action",
                             ids={"plan_id": pid, "action_id": "a1"},
                             patch={"status": "done",
                                    "evidence": "claim"}))["result"]
    assert out["status"] == "done"            # pure write, no gate/parking
    a = _ok(await env.call("read_object", type="action",
                           ids={"plan_id": pid, "action_id": "a1"}))["object"]
    assert a["status"] == "done"
    # the verify criterion is retained as data (worker/reviewer re-run it)
    assert a["acceptance"]["verify"]["path"] == "/no/such/x"


async def test_update_action_correctable_verify_while_dispatching(env):
    _recipe(env)
    pid = _plan(env, actions=[_a("a1", status="in_progress")])
    out = _ok(await env.call("update_object", type="action",
                             ids={"plan_id": pid, "action_id": "a1"},
                             patch={"verify": {"check": "file_exists",
                                               "path": "/tmp/ok"}}))["result"]
    assert out["ok"] is True and out["updated"] == ["verify"]
    a = _ok(await env.call("read_object", type="action",
                           ids={"plan_id": pid, "action_id": "a1"}))["object"]
    assert a["acceptance"]["verify"]["path"] == "/tmp/ok"


async def test_update_action_rejects_unknown_field(env):
    _recipe(env)
    pid = _plan(env, actions=[_a("a1", status="in_progress")])
    res = await env.call("update_object", type="action",
                         ids={"plan_id": pid, "action_id": "a1"},
                         patch={"bogus": 1})
    assert isinstance(res, ToolError)
    assert "field-update allows" in res.message


async def test_update_inspect_only_refused(env):
    res = await env.call("update_object", type="lock",
                         ids={"handle": "x"}, patch={"state": "free"})
    assert isinstance(res, ToolError)
    assert "inspect-only" in res.message


async def test_update_empty_patch_refused(env):
    _recipe(env)
    pid = _plan(env, actions=[_a("a1")])
    res = await env.call("update_object", type="action",
                         ids={"plan_id": pid, "action_id": "a1"}, patch={})
    assert isinstance(res, ToolError)
    assert "non-empty" in res.message
