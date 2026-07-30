"""Inbox delivery contract (REACTIVE-STREAMS 2026-05-29).

next_action is now a PURE PROTOCOL pacer — it does NOT deliver messages
and does NOT consume the inbox. `check_inbox` (and rx push in live
shells) is the message-delivery path; it advances `_INBOX_CURSORS` so a
consumed message isn't re-delivered. The original single-cursor bug
(next_action vs check_inbox double-delivery) is gone by construction:
only check_inbox consumes.
"""

from datetime import datetime, timezone

from edp_contracts import BrokerMessage, ToolOk

from edp_claude.schemas import Recipe


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _recipe(env, rid="r-cursor"):
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))
    return rid


async def _send(env, to, body, kind="answer", frm="curiosity-x"):
    import uuid
    await env.ctx.broker.send(BrokerMessage.model_validate({
        "msg_id": str(uuid.uuid4()), "ts": datetime.now(timezone.utc),
        "from": frm, "to": to, "kind": kind, "body": body,
    }))


async def test_next_action_does_not_consume_messages(env):
    rid = _recipe(env)
    await _send(env, rid, {"q": "first"})
    # next_action is pure protocol now — never handle_messages, and it
    # does NOT consume the inbox.
    d = _ok(await env.call("next_action", handle=rid, handle_type="recipe"))
    assert d["kind"] != "handle_messages"
    # so check_inbox STILL delivers the message (next_action left it).
    ci = _ok(await env.call("check_inbox", handle=rid))
    assert [m["body"].get("q") for m in ci["messages"]] == ["first"]


async def test_check_inbox_consumes_then_next_action_is_protocol(env):
    rid = _recipe(env, "r-cursor2")
    await _send(env, rid, {"q": "viaInbox"})
    # check_inbox consumes it, advancing the cursor
    ci = _ok(await env.call("check_inbox", handle=rid))
    assert len(ci["messages"]) == 1
    # next_action is protocol-only and never re-surfaces it
    d = _ok(await env.call("next_action", handle=rid, handle_type="recipe"))
    assert d["kind"] != "handle_messages"
    # a second check_inbox does not re-deliver (cursor advanced)
    assert _ok(await env.call("check_inbox", handle=rid))["messages"] == []


async def test_new_message_after_consumed_still_delivered(env):
    # check_inbox advances PAST consumed messages but still delivers NEW ones
    rid = _recipe(env, "r-cursor3")
    await _send(env, rid, {"q": "one"})
    _ok(await env.call("check_inbox", handle=rid))   # consume "one"
    await _send(env, rid, {"q": "two"})              # a genuinely new message
    ci = _ok(await env.call("check_inbox", handle=rid))
    bodies = [m["body"].get("q") for m in ci["messages"]]
    assert bodies == ["two"]                          # only the new one
