"""Phase 9 — decay/refresh (decision #4).

check_specialist_decay is a deterministic, ON-DEMAND staleness detector
(not a polling daemon). A stable/underused neuron is stale when its TTL
elapsed OR its flag-rate is high — whichever first. It reports; it does
not mutate. The neuron then re-validates via the existing transition +
recipe-edit tools.
"""

from datetime import datetime, timedelta, timezone

from edp_contracts import ToolOk

from edp_claude.schemas import NeuronRecord


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _mk(env, nid, *, status="stable", trained_days_ago=1,
        use_count=0, flag_count=0):
    now = datetime.now(timezone.utc)
    env.ctx.neurons.create(NeuronRecord(
        neuron_id=nid, name=nid, description=f"{nid} expert",
        category="domain", status=status,
        use_count=use_count, flag_count=flag_count,
        created_at=now, updated_at=now,
        trained_at=now - timedelta(days=trained_days_ago),
    ))


async def test_ttl_decay_flags_old_specialist(env):
    _mk(env, "old", trained_days_ago=120)
    _mk(env, "fresh", trained_days_ago=10)
    out = _ok(await env.call("check_specialist_decay", ttl_days=90))
    ids = [s["neuron_id"] for s in out["stale"]]
    assert "old" in ids and "fresh" not in ids
    reason = next(s for s in out["stale"] if s["neuron_id"] == "old")
    assert any("ttl" in r.lower() for r in reason["reasons"])


async def test_flag_rate_decay(env):
    # high flag-rate with enough flags → stale, regardless of age
    _mk(env, "buggy", trained_days_ago=5, use_count=4, flag_count=3)
    # one-off flag below min_flags → NOT stale
    _mk(env, "blip", trained_days_ago=5, use_count=4, flag_count=1)
    out = _ok(await env.call("check_specialist_decay", ttl_days=365,
                             flag_rate_threshold=0.3))
    ids = [s["neuron_id"] for s in out["stale"]]
    assert "buggy" in ids and "blip" not in ids
    reason = next(s for s in out["stale"] if s["neuron_id"] == "buggy")
    assert any("flag-rate" in r.lower() for r in reason["reasons"])


async def test_healthy_specialist_not_flagged(env):
    _mk(env, "good", trained_days_ago=10, use_count=10, flag_count=0)
    out = _ok(await env.call("check_specialist_decay"))
    assert out["stale"] == []
    assert out["checked"] == 1


async def test_non_stable_neurons_skipped(env):
    _mk(env, "draft", status="pending_review", trained_days_ago=999)
    _mk(env, "gone", status="archived", trained_days_ago=999,
        use_count=5, flag_count=5)
    out = _ok(await env.call("check_specialist_decay", ttl_days=90))
    assert out["stale"] == []        # neither is stable/underused
    assert out["checked"] == 0


async def test_revalidation_path_uses_existing_transition(env):
    # the action on a stale neuron: re-enter the review flow (decision #4)
    _mk(env, "stale1", trained_days_ago=200)
    out = _ok(await env.call("check_specialist_decay", ttl_days=90))
    assert "stale1" in [s["neuron_id"] for s in out["stale"]]
    # stable -> pending_review is legal (re-validation)
    _ok(await env.call("neuron_set_status", neuron_id="stale1",
                       status="pending_review"))
    assert env.ctx.neurons.get("stale1").status == "pending_review"
