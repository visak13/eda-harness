"""F7 (2026-08-17) — dead-letter detection surfaces to the SENDER.

A broker_send to an inbox nobody owns used to succeed silently (the
2026-05-24 literal-"neuron" class). The send still succeeds (fail-open, the
broker stays a dumb pipe) but the result now carries an
`unknown_recipient` advisory so the sender fixes the address immediately.
"""

from datetime import datetime, timezone

from edp_claude.schemas import Recipe
from edp_claude.server import make_context
from edp_claude.tools._tools import BrokerSend, _SendIn


def _now():
    return datetime.now(timezone.utc)


def _advisories(res):
    data = res.data if isinstance(res.data, dict) else (
        res.data.model_dump() if hasattr(res.data, "model_dump") else {})
    return data.get("advisories") or []


async def test_unknown_recipient_send_succeeds_with_warning(tmp_path):
    ctx = make_context(tmp_path)
    res = await BrokerSend(ctx)._run(_SendIn(
        to="neuron", kind="answer", body={"x": 1}))
    assert res.ok, res
    adv = _advisories(res)
    assert any(a["kind"] == "unknown_recipient" for a in adv), adv
    assert "DEAD-LETTER" in adv[0]["detail"]


async def test_known_recipe_recipient_carries_no_warning(tmp_path):
    ctx = make_context(tmp_path)
    ctx.recipes.save(Recipe(
        recipe_id="recipe-f7", user_goal_verbatim="g",
        user_goal_distilled="g", domain="software_engineering",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "pending", "depends_on": [],
                "execution": "inline"}],
        created_at=_now(), updated_at=_now()))
    res = await BrokerSend(ctx)._run(_SendIn(
        to="recipe-f7", kind="answer", body={"x": 1}))
    assert res.ok, res
    assert not _advisories(res)


async def test_live_pool_handle_and_topic_carry_no_warning(tmp_path):
    ctx = make_context(tmp_path)
    await ctx.pool.spawn_worker("recipe-f7-s1", "a1")
    live = await BrokerSend(ctx)._run(_SendIn(
        to="recipe-f7-s1:a1", kind="steer", body={"x": 1}))
    assert live.ok and not _advisories(live)
    topic = await BrokerSend(ctx)._run(_SendIn(
        to="topic:builds", kind="fyi", body={"x": 1}))
    assert topic.ok and not _advisories(topic)
