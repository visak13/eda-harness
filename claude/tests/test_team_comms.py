"""Team-architecture bi-directional comms (REACTIVE-STREAMS 2026-05-29).

Delivery moved OFF next_action (now a pure-protocol pacer) onto
`check_inbox` (the explicit pull) + rx push (live shells). This suite
validates the comms round-trips over `check_inbox`:

- Sender uses ask_above / notify_above (parent auto-resolved from
  EDP_HANDLE — agent never knows about brokers).
- Receiver calls `check_inbox` to pull pending items; the cursor
  advances so the same message is not re-delivered.
- Receiver calls reply(msg_id, body) — the tool looks up the original
  message and routes the answer; the agent never types addressing.
- next_action stays protocol-only and never returns handle_messages.
"""

from datetime import datetime, timezone

from edp_contracts import ToolError, ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _executing_recipe_with_step(env, rid="recipe-x", sid="s1"):
    """Spin up a recipe in EXECUTING with one in-flight spawn_planner
    step — the state where a planner would naturally be talking to it."""
    from edp_claude.schemas import Recipe

    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={
            "branches": [{"id": "b1", "question": "?",
                          "status": "resolved", "verdict": "v" * 50}],
            "expected_outcomes": [{"id": "o1", "description": "d",
                                   "verification": "v"}],
        },
        steps=[{"step_id": sid, "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))


async def test_planner_asks_neuron_delivered_via_check_inbox(env, monkeypatch):
    # Planner has EDP_HANDLE=<recipe_id>:<step_id> → parent = recipe_id.
    rid = "recipe-x"
    sid = "s1"
    _executing_recipe_with_step(env, rid, sid)
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:{sid}")
    monkeypatch.setenv("EDP_ROLE", "planner")

    # Planner asks.
    res = await env.call(
        "ask_above", question="A or B?",
        body={"options": ["A", "B"]})
    assert isinstance(res, ToolOk)

    # Neuron pulls via check_inbox (delivery path; rx push in live shells).
    msgs = (await env.call("check_inbox", handle=rid)).data["messages"]
    assert len(msgs) == 1
    assert msgs[0]["kind"] == "question"
    assert msgs[0]["body"]["question"] == "A or B?"
    assert msgs[0]["body"]["options"] == ["A", "B"]
    # Planner's broker identity is its plan_id (dash form), not its
    # EDP_HANDLE (colon form) — so the answer can route back via the
    # plan's inbox.
    assert msgs[0]["from"] == f"{rid}-{sid}"
    assert msgs[0]["msg_id"]
    # next_action stays protocol-only (never delivers the message).
    d = (await env.call("next_action", handle=rid,
                        handle_type="recipe")).data
    assert d["kind"] != "handle_messages"


async def test_inbox_cursor_advances_no_double_delivery(env, monkeypatch):
    rid = "recipe-cursor"
    _executing_recipe_with_step(env, rid)
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:s1")
    monkeypatch.setenv("EDP_ROLE", "planner")

    await env.call("ask_above", question="q1")

    # First check_inbox returns the message
    first = (await env.call("check_inbox", handle=rid)).data["messages"]
    assert len(first) == 1

    # Second check_inbox (no new messages) does NOT re-deliver it
    second = (await env.call("check_inbox", handle=rid)).data["messages"]
    assert second == []
    # next_action progresses the recipe (executing → wait; step in_progress)
    d = (await env.call("next_action", handle=rid,
                        handle_type="recipe")).data
    assert d["kind"] == "wait"


async def test_neuron_responds_planner_picks_it_up(env, monkeypatch):
    """Round-trip: planner asks → neuron responds → planner pulls the
    answer via check_inbox."""
    rid = "recipe-roundtrip"
    pid = f"{rid}-s1"
    _executing_recipe_with_step(env, rid, "s1")

    from edp_claude.schemas import Plan

    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id=rid, recipe_step_id="s1",
        domain="generic", shape="x", goal="g",
        state="dispatching",
        actions=[{"action_id": "a1", "description": "d",
                  "status": "in_progress", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "tests_pass"}}],
    )))

    # 1) Planner asks neuron
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:s1")
    monkeypatch.setenv("EDP_ROLE", "planner")
    await env.call("ask_above", question="proceed with A?")

    # 2) Neuron pulls the question via check_inbox
    msg = (await env.call("check_inbox", handle=rid)).data["messages"][0]

    # 3) Neuron replies — only the msg_id; the tool looks up the
    # original sender via the broker and routes the answer. The agent
    # never types `to=` or knows about the planner's plan_id.
    monkeypatch.delenv("EDP_HANDLE", raising=False)  # neuron has no handle
    monkeypatch.delenv("EDP_ROLE", raising=False)
    _ok(await env.call(
        "reply", msg_id=msg["msg_id"], body={"answer": "yes, A"}))

    # 4) Planner (handle = plan_id) pulls the answer via check_inbox
    answer = (await env.call("check_inbox", handle=pid)).data["messages"][0]
    assert answer["kind"] == "answer"
    assert answer["body"]["in_reply_to"] == msg["msg_id"]
    assert answer["body"]["answer"] == "yes, A"


async def test_notify_above_one_way_no_response_expected(env, monkeypatch):
    rid = "recipe-notify"
    _executing_recipe_with_step(env, rid)
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:s1")
    monkeypatch.setenv("EDP_ROLE", "planner")

    await env.call("notify_above", kind="progress",
                   body={"completed": ["a1"], "starting": "a2"})

    msg = (await env.call("check_inbox", handle=rid)).data["messages"][0]
    assert msg["kind"] == "progress"
    assert msg["body"]["starting"] == "a2"


async def test_worker_two_way_via_check_inbox(env, monkeypatch):
    """Workers are now full team members. Pattern: worker arms a cron
    at Step 0; on each tick it calls `check_inbox()`. If the planner
    has answered a prior `ask_above`, the answer is in the inbox.

    No Monitor, no subscribe, no next_action loop for the worker —
    just one tool call per cron tick."""
    rid = "recipe-w"
    pid = f"{rid}-s1"
    aid = "a1"
    worker_handle = f"{pid}:{aid}"

    # Worker spawned: EDP_ROLE=worker, EDP_HANDLE=plan:action.
    monkeypatch.setenv("EDP_HANDLE", worker_handle)
    monkeypatch.setenv("EDP_ROLE", "worker")

    # Worker hits a fork, asks the planner.
    _ok(await env.call("ask_above", question="A or B?"))

    # Planner (separately) picks up the question and replies. We
    # simulate the planner's response directly via reply() — but
    # planner-identity must be set in env for the reply's `from` to
    # be the plan_id.
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:s1")
    monkeypatch.setenv("EDP_ROLE", "planner")
    # Find the question on the planner's inbox (broker.poll with plan_id)
    planner_msgs = await env.ctx.broker.poll(pid)
    question_msg = planner_msgs[-1]
    _ok(await env.call(
        "reply", msg_id=question_msg.msg_id, body={"answer": "A"}))

    # Worker comes back on cron tick — calls check_inbox() with no
    # args; tool reads EDP_HANDLE to know who to poll for.
    monkeypatch.setenv("EDP_HANDLE", worker_handle)
    monkeypatch.setenv("EDP_ROLE", "worker")
    inbox = (await env.call("check_inbox")).data
    assert len(inbox["messages"]) == 1
    answer = inbox["messages"][0]
    assert answer["kind"] == "answer"
    assert answer["body"]["answer"] == "A"
    assert answer["body"]["in_reply_to"] == question_msg.msg_id


async def test_check_inbox_cursor_no_double_delivery(env, monkeypatch):
    """Cursor managed under the hood: after the first check_inbox sees
    a message, subsequent calls do NOT re-deliver it. The cron tick
    pattern (worker calls check_inbox every tick) stays correct over
    many ticks because old messages are filtered."""
    from edp_claude.tools._tools import _INBOX_CURSORS
    _INBOX_CURSORS.clear()  # isolate test from module state

    rid = "recipe-cursor-worker"
    pid = f"{rid}-s1"
    worker_handle = f"{pid}:a1"

    # Set up a question from worker → planner so a reply arrives.
    monkeypatch.setenv("EDP_HANDLE", worker_handle)
    monkeypatch.setenv("EDP_ROLE", "worker")
    await env.call("ask_above", question="?")

    # Planner replies.
    planner_msgs = await env.ctx.broker.poll(pid)
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:s1")
    monkeypatch.setenv("EDP_ROLE", "planner")
    await env.call("reply", msg_id=planner_msgs[-1].msg_id,
                   body={"answer": "yes"})

    # Worker checks inbox — sees the answer
    monkeypatch.setenv("EDP_HANDLE", worker_handle)
    monkeypatch.setenv("EDP_ROLE", "worker")
    first = (await env.call("check_inbox")).data
    assert len(first["messages"]) == 1

    # Second tick: no new messages; cursor advanced; empty result.
    second = (await env.call("check_inbox")).data
    assert second["messages"] == []

    _INBOX_CURSORS.clear()  # leave clean


async def test_check_inbox_with_no_handle_is_precondition(env, monkeypatch):
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    res = await env.call("check_inbox")
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"


async def test_reply_unknown_msg_id_is_precondition(env):
    res = await env.call("reply", msg_id="does-not-exist", body={})
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"


async def test_comms_are_worklogged_for_visibility(env, monkeypatch):
    """2026-05-22: inter-shell messages must be VISIBLE in the worklog
    (they were buried in scattered broker inboxes). A planner's
    outbound ask_above → message_sent in its plan worklog; the neuron's
    inbound delivery → message_received in the recipe events."""
    import json
    from pathlib import Path

    rid = "recipe-vis"
    sid = "s1"
    pid = f"{rid}-{sid}"
    _executing_recipe_with_step(env, rid, sid)
    # the plan must exist for the planner's worklog target
    from edp_claude.schemas import Plan
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id=rid, recipe_step_id=sid,
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "d",
                  "status": "in_progress", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "tests_pass"}}],
    )))

    # planner asks → message_sent in the PLAN worklog
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:{sid}")
    monkeypatch.setenv("EDP_ROLE", "planner")
    await env.call("ask_above", question="A or B?")
    plan_wl = Path(env.ctx.plans.root) / pid / "worklog.jsonl"
    sent = [json.loads(x) for x in
            plan_wl.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert any(e.get("kind") == "message_sent"
               and e.get("msg_kind") == "question" for e in sent)

    # neuron receives via check_inbox → message_received in recipe events
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.delenv("EDP_ROLE", raising=False)
    ci = (await env.call("check_inbox", handle=rid)).data
    assert len(ci["messages"]) == 1
    events = Path(env.ctx.recipes.root) / rid / "events.jsonl"
    recv = [json.loads(x) for x in
            events.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert any(e.get("kind") == "message_received"
               and e.get("msg_kind") == "question" for e in recv)


async def test_ask_above_with_no_handle_is_precondition(env, monkeypatch):
    # Neuron has no EDP_HANDLE → ask_above is a no-op precondition.
    # (Neuron escalates via AskUserQuestion, not ask_above.)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    res = await env.call("ask_above", question="?")
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"
    assert "neuron" in res.message.lower() or "no parent" in res.message.lower()
