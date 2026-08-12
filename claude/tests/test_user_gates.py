"""P6 — curiosity independence + user-in-the-loop gates.

(a) consult_curiosity carries recipe_id + caller_framing so the curiosity
    shell can read ground truth instead of only the neuron's framing.
(b) comprehending → planning requires user signoff on the comprehension
    brief, or an explicitly recorded skip (reason mandatory, audited).
(c) a load-bearing decision recorded (or superseded) after the last
    re-grounding fires a persistent recheck nag; a fresh curiosity clear
    or a fresh signoff clears it.
"""

import uuid
from datetime import datetime, timezone

from edp_contracts import BrokerMessage, ToolOk

from edp_claude.fsm import recipe_context


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _comprehended(env, signoff=True):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    r = env.ctx.recipes.load(rid)
    r.comprehension.curiosity_cleared = True   # curiosity converged
    env.ctx.recipes.save(r)
    _ok(await env.call("record_outcome", recipe_id=rid,
                       description="o", verification="v"))
    _ok(await env.call("add_step", recipe_id=rid, description="build",
                       execution="spawn_planner", estimate={"hours": 1}))
    if signoff:
        _ok(await env.call("record_comprehension_signoff", recipe_id=rid,
                           user_quote="looks good, proceed"))
    return rid


# ── (b) the user-discussion gate ────────────────────────────────────────────

async def test_gate_blocks_first_dispatch_without_signoff(env):
    rid = await _comprehended(env, signoff=False)
    d = _ok(await env.call("next_action", handle=rid, handle_type="recipe"))
    assert d["kind"] == "await_user"
    assert "COMPREHENSION BRIEF" in d["rationale"]
    # state did NOT advance — no planner was suggested
    r = env.ctx.recipes.load(rid)
    assert str(getattr(r.state, "value", r.state)) == "comprehending"


async def test_gate_opens_with_user_signoff(env):
    rid = await _comprehended(env, signoff=True)
    d = _ok(await env.call("next_action", handle=rid, handle_type="recipe"))
    assert d["kind"] == "spawn_planner"
    r = env.ctx.recipes.load(rid)
    assert r.comprehension.user_signoff is True
    assert r.comprehension.signoff_quote == "looks good, proceed"


async def test_gate_opens_with_recorded_skip(env):
    rid = await _comprehended(env, signoff=False)
    _ok(await env.call("record_comprehension_signoff", recipe_id=rid,
                       skipped=True,
                       reason="user offline; autonomous overnight run"))
    d = _ok(await env.call("next_action", handle=rid, handle_type="recipe"))
    assert d["kind"] == "spawn_planner"
    events = (env.ctx.recipes.root / rid / "events.jsonl").read_text(
        encoding="utf-8")
    assert "comprehension_signoff_skipped" in events
    assert "autonomous overnight run" in events


async def test_skip_requires_reason(env):
    rid = await _comprehended(env, signoff=False)
    res = await env.call("record_comprehension_signoff", recipe_id=rid,
                         skipped=True)
    assert not isinstance(res, ToolOk)


# ── (c) load-bearing drift recheck ──────────────────────────────────────────

async def _past_gate(env):
    rid = await _comprehended(env, signoff=True)
    _ok(await env.call("next_action", handle=rid,
                       handle_type="recipe"))   # leaves comprehending
    return rid


async def test_load_bearing_drift_fires_persistent_nag(env):
    rid = await _past_gate(env)
    ctx0 = recipe_context(env.ctx.recipes.load(rid))
    assert "comprehension_recheck" not in ctx0
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="STRATEGY PIVOT: meta-reasoning core.",
                       load_bearing=True))
    ctx1 = recipe_context(env.ctx.recipes.load(rid))
    assert "LOAD-BEARING DECISION DRIFT" in ctx1["comprehension_recheck"]
    # persistent: still nagging on the next tick
    ctx2 = recipe_context(env.ctx.recipes.load(rid))
    assert "comprehension_recheck" in ctx2


async def test_supersede_also_fires_nag(env):
    rid = await _past_gate(env)
    _ok(await env.call("record_context", kind="decision", recipe_id=rid, text="old way"))
    _ok(await env.call("record_context", kind="decision", recipe_id=rid, text="new way"))
    _ok(await env.call("supersede_decision", recipe_id=rid,
                       decision_id="d1", replaced_by="d2"))
    ctx = recipe_context(env.ctx.recipes.load(rid))
    assert "LOAD-BEARING DECISION DRIFT" in ctx["comprehension_recheck"]


async def test_fresh_signoff_clears_nag(env):
    rid = await _past_gate(env)
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="PIVOT.", load_bearing=True))
    assert "comprehension_recheck" in recipe_context(
        env.ctx.recipes.load(rid))
    _ok(await env.call("record_comprehension_signoff", recipe_id=rid,
                       user_quote="discussed the pivot; proceed"))
    assert "comprehension_recheck" not in recipe_context(
        env.ctx.recipes.load(rid))


async def test_fresh_curiosity_clear_clears_nag(env):
    rid = await _past_gate(env)
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="PIVOT.", load_bearing=True))
    assert "comprehension_recheck" in recipe_context(
        env.ctx.recipes.load(rid))
    # a NEW curiosity clear arrives on the recipe inbox → reconcile
    # captures it as a re-grounding moment and refreshes the baseline.
    await env.ctx.broker.send(BrokerMessage.model_validate({
        "msg_id": str(uuid.uuid4()), "ts": datetime.now(timezone.utc),
        "from": "curiosity-fresh1", "to": rid, "kind": "verdict",
        "body": {"status": "done", "clear": True, "questions": []},
    }))
    _ok(await env.call("reconcile", handle=rid, handle_type="recipe"))
    assert "comprehension_recheck" not in recipe_context(
        env.ctx.recipes.load(rid))


# ── (a) curiosity gets ground truth ─────────────────────────────────────────

async def test_consult_carries_recipe_id_and_framing(env):
    rid = await _comprehended(env, signoff=True)
    got = _ok(await env.call(
        "consult_curiosity", handle=rid,
        decision="pivot to meta-reasoning",
        context="my framing of the situation"))
    cid = got["curiosity_id"]
    msgs = await env.ctx.broker.poll(cid, since_ts=None)
    [consult] = [x for x in msgs if x.kind == "consult"]
    assert consult.body["recipe_id"] == rid
    assert consult.body["caller_framing"] == "my framing of the situation"
    assert consult.body["context"] == "my framing of the situation"  # compat
    assert consult.body["caller"] == rid


async def test_consult_without_recipe_omits_id(env, monkeypatch):
    """First consult of a brand-new goal: no recipe exists yet — framing
    only, no recipe_id key (curiosity proceeds as today)."""
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    got = await env.call(
        "consult_curiosity", handle="recipe-not-yet-created",
        decision="d", context="c")
    if isinstance(got, ToolOk):
        cid = got.data["curiosity_id"] if isinstance(got.data, dict) else \
            got.data.curiosity_id
        msgs = await env.ctx.broker.poll(cid, since_ts=None)
        [consult] = [x for x in msgs if x.kind == "consult"]
        assert "recipe_id" not in consult.body
