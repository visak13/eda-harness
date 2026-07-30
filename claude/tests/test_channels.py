"""CHANNELS (2026-07-21): derivation + the for-filter + member reads."""

from edp_claude.channels import (
    EXPERTS_CHANNEL,
    addressed_to,
    member_channels,
    plan_of,
)


def test_membership_derivation():
    assert member_channels("rec-a-s3:a4", "worker") == ["rec-a-s3"]
    assert member_channels("rec-a-s3:r1", "reviewer") == ["rec-a-s3"]
    assert member_channels("rec-a:s3", "planner") == ["rec-a", "rec-a-s3"]
    assert member_channels("sme-x", "specialist") == [EXPERTS_CHANNEL]
    assert plan_of("rec-a-s3:a4") == "rec-a-s3"
    assert plan_of("experts") is None


def test_for_filter_preserves_owner_semantics():
    ch = "rec-a-s3"
    # unaddressed mail = the owner's (today's behavior, unchanged)
    assert addressed_to({}, ch, ch) is True
    assert addressed_to({}, "rec-a-s3:a4", ch) is False
    # addressed mail reaches exactly its target (+ @all reaches everyone)
    body = {"for": "rec-a-s3:a4"}
    assert addressed_to(body, "rec-a-s3:a4", ch) is True
    assert addressed_to(body, ch, ch) is False
    assert addressed_to({"for": "@all"}, "anyone", ch) is True


def test_done_flowback_message_is_constructible():
    # The a4 stranding root cause: BrokerMessage requires msg_id+ts; the
    # flowback publish omitted them and ValidationError was swallowed —
    # done recorded, parent never woken. Pin constructibility itself.
    import uuid
    from datetime import datetime, timezone
    from edp_contracts import BrokerMessage
    m = BrokerMessage(
        msg_id=str(uuid.uuid4()), ts=datetime.now(timezone.utc),
        from_="rec-a-s1:a1", to="rec-a-s1", kind="done",
        body={"action_id": "a1", "status": "done", "for": "rec-a-s1"})
    assert m.kind == "done" and m.to == "rec-a-s1"


import asyncio as _aio


def test_review_leg_as_worker_is_refused(tmp_path, monkeypatch):
    # d67 fail-closed (2026-07-21 live incident): a review leg dispatched
    # role='worker' = the builder reviewing its own work. Refused, named.
    from edp_claude.tools._tools import PoolSpawnWorker
    from edp_claude.store.plan_store import PlanStore
    from edp_claude.store.recipe_store import RecipeStore
    from edp_claude.schemas import Plan, Action
    from edp_claude.schemas.plan import Acceptance

    class _Ctx:
        recipes = RecipeStore(tmp_path / ".recipes")
        plans = PlanStore(tmp_path / ".plans")
        broker = None
        pool = None
    ctx = _Ctx()
    p = Plan(plan_id="rec-x-s1", recipe_id="rec-x", recipe_step_id="s1",
             domain="framework", shape="linear-build", goal="g",
             state="dispatching",
             actions=[Action(action_id="review-universal",
                             description="review leg", status="pending",
                             executor_mode="subagent",
                             acceptance=Acceptance(kind="manual_review",
                                                   expected="x"))])
    ctx.plans.save(p)
    tool = PoolSpawnWorker(ctx)
    out = _aio.run(tool._run(tool.InputModel(
        plan_id="rec-x-s1", action_id="review-universal", role="worker")))
    text = str(getattr(out, "message", out))
    assert "role='reviewer'" in text and "d67" in text
