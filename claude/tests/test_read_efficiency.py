"""P1 read-efficiency — worklog filters/digest, inbox summary/byte budget,
read_object detail levels.

Hard constraint proven here: every DEFAULT path returns exactly what it did
before P1 (full entries, full bodies, full objects); the cheap views are
opt-in and full fidelity is always one explicit call away.
"""

import uuid
from datetime import datetime, timezone

from edp_contracts import BrokerMessage, ToolOk

from edp_claude.schemas import Plan, Recipe


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _recipe(env, rid="r-eff", state="executing"):
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state=state,
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "a long outcome " * 30,
             "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "k",
                "description": "step text " * 100,
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={"decisions": [
            {"id": "d1", "text": "DECISION ONE. " + "body " * 200,
             "rationale": "r", "by": "neuron",
             "at": datetime.now(timezone.utc).isoformat(),
             "load_bearing": True}]},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))
    return rid


def _plan(env, pid="r-eff-s1"):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id="r-eff", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{
            "action_id": "a1", "description": "build the thing",
            "status": "done", "depends_on": [],
            "executor_mode": "subagent",
            "acceptance": {"kind": "artifact", "expected": "exists",
                           "actual": "evidence blob " * 300},
        }],
        context={},
    )))
    return pid


async def _send(env, to, body, kind="answer"):
    await env.ctx.broker.send(BrokerMessage.model_validate({
        "msg_id": str(uuid.uuid4()), "ts": datetime.now(timezone.utc),
        "from": "x", "to": to, "kind": kind, "body": body,
    }))


# ── worklog filters ─────────────────────────────────────────────────────────

async def test_worklog_kinds_filter_applies_before_tail(env):
    pid = _plan(env)
    for i in range(30):
        env.ctx.plans.append_worklog(pid, {"kind": "noise", "i": i})
    for i in range(5):
        env.ctx.plans.append_worklog(pid, {"kind": "verify_pending", "i": i})
    # unfiltered tail=10 is dominated by noise
    base = _ok(await env.call("read_worklog", plan_id=pid, tail=10))
    assert any(e["kind"] == "noise" for e in base["entries"])
    # filtered: all 5 verify_pending survive a tail=10 cut
    got = _ok(await env.call("read_worklog", plan_id=pid, tail=10,
                             kinds=["verify_pending"]))
    assert [e["kind"] for e in got["entries"]] == ["verify_pending"] * 5


async def test_worklog_since_and_action_id_filters(env):
    pid = _plan(env)
    env.ctx.plans.append_worklog(pid, {"kind": "k", "action_id": "a1"})
    cut = datetime.now(timezone.utc).isoformat()
    env.ctx.plans.append_worklog(
        pid, {"kind": "message_received", "from": f"{pid}:a2"})
    got = _ok(await env.call("read_worklog", plan_id=pid, since=cut))
    assert len(got["entries"]) == 1
    assert got["entries"][0]["kind"] == "message_received"
    # action_id matches the explicit field OR the worker-handle suffix
    a1 = _ok(await env.call("read_worklog", plan_id=pid, action_id="a1"))
    assert [e["kind"] for e in a1["entries"]] == ["k"]
    a2 = _ok(await env.call("read_worklog", plan_id=pid, action_id="a2"))
    assert [e["kind"] for e in a2["entries"]] == ["message_received"]


async def test_worklog_digest_lines(env):
    pid = _plan(env)
    env.ctx.plans.append_worklog(
        pid, {"kind": "action_status_change", "action_id": "a1",
              "detail": "x" * 500})
    got = _ok(await env.call("read_worklog", plan_id=pid, digest=True))
    line = got["entries"][-1]
    assert isinstance(line, str)
    ts, kind, action_id, detail = line.split("|", 3)
    assert kind == "action_status_change" and action_id == "a1"
    assert len(detail) <= 120


async def test_worklog_default_unchanged(env):
    pid = _plan(env)
    env.ctx.plans.append_worklog(pid, {"kind": "k", "x": 1})
    got = _ok(await env.call("read_worklog", plan_id=pid))
    assert isinstance(got["entries"][-1], dict)
    assert got["entries"][-1]["x"] == 1


async def test_worklog_query_filters_via_objects(env):
    pid = _plan(env)
    env.ctx.plans.append_worklog(
        pid, {"kind": "message_received", "from": f"{pid}:a7"})
    env.ctx.plans.append_worklog(pid, {"kind": "noise"})
    got = _ok(await env.call(
        "query_objects", type="worklog", scope={"plan_id": pid},
        where={"action_id": "a7"}))
    assert [e["kind"] for e in got["objects"]] == ["message_received"]


# ── check_inbox summary / max_bytes ─────────────────────────────────────────

async def test_inbox_summary_rows_and_message_recovery(env):
    rcpt = "r-eff-s1:a1"
    await _send(env, rcpt, {"big": "y" * 5000})
    got = _ok(await env.call("check_inbox", handle=rcpt, summary=True))
    [row] = got["messages"]
    assert "body" not in row and row["body_bytes"] > 5000
    assert len(row["preview"]) <= 200
    assert "read_object" in (got["note"] or "")
    # full body recoverable by msg_id
    full = _ok(await env.call("read_object", type="message",
                              ids={"msg_id": row["msg_id"]}))
    assert full["object"]["body"]["big"] == "y" * 5000
    # cursor advanced over the summarized message — no re-delivery
    again = _ok(await env.call("check_inbox", handle=rcpt))
    assert again["messages"] == []


async def test_inbox_max_bytes_budget(env):
    rcpt = "r-eff-s1:a2"
    await _send(env, rcpt, {"q": "small"})
    await _send(env, rcpt, {"big": "z" * 4000})
    got = _ok(await env.call("check_inbox", handle=rcpt, max_bytes=100))
    first, second = got["messages"]
    assert first["body"]["q"] == "small"          # within budget → full
    assert "body" not in second                   # over budget → summary row
    assert second["body_bytes"] > 4000
    assert "summarized" in (got["note"] or "")


async def test_inbox_default_untruncated(env):
    rcpt = "r-eff-s1:a3"
    await _send(env, rcpt, {"big": "w" * 9000})
    got = _ok(await env.call("check_inbox", handle=rcpt))
    assert got["messages"][0]["body"]["big"] == "w" * 9000
    assert got["note"] is None


# ── read_object detail levels ───────────────────────────────────────────────

async def test_read_recipe_full_is_unchanged(env):
    rid = _recipe(env)
    got = _ok(await env.call("read_object", type="recipe",
                             ids={"recipe_id": rid}))
    direct = env.ctx.recipes.load(rid).model_dump(mode="json")
    assert got["object"] == direct


async def test_read_recipe_digest_trims_and_self_labels(env):
    rid = _recipe(env)
    got = _ok(await env.call("read_object", type="recipe",
                             ids={"recipe_id": rid}, detail="digest"))
    d = got["object"]
    assert d["_detail"] == "digest" and "detail='full'" in d["_full"]
    [dec] = d["context"]["decisions"]
    assert dec["id"] == "d1" and dec["load_bearing"] is True
    assert "body body" not in dec["title"]        # long text not shipped
    assert len(d["steps"][0]["description"]) < 200


async def test_read_plan_digest_drops_evidence(env):
    _recipe(env)
    pid = _plan(env)
    full = _ok(await env.call("read_object", type="plan",
                              ids={"plan_id": pid}))["object"]
    assert "evidence blob" in full["actions"][0]["acceptance"]["actual"]
    dig = _ok(await env.call("read_object", type="plan",
                             ids={"plan_id": pid},
                             detail="digest"))["object"]
    a = dig["actions"][0]
    assert a["has_actual"] is True and "acceptance" not in a
    assert dig["_detail"] == "digest"


async def test_read_action_digest_keeps_indicators(env):
    _recipe(env)
    pid = _plan(env)
    dig = _ok(await env.call("read_object", type="action",
                             ids={"plan_id": pid, "action_id": "a1"},
                             detail="digest"))["object"]
    assert dig["_detail"] == "digest"
    assert dig["acceptance"]["actual_bytes"] > 1000
    assert len(dig["acceptance"]["actual"]) < 200
    assert dig["has_injected_context"] is False
    full = _ok(await env.call("read_object", type="action",
                              ids={"plan_id": pid, "action_id": "a1"}))
    assert "evidence blob" in full["object"]["acceptance"]["actual"]
