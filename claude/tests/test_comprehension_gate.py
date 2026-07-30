"""Comprehension gate (REDESIGN 2026-05-28).

record_outcome refuses until comprehension is converged: curiosity
returned clear/done (auto-captured from its reply — the neuron can't
fake it) OR the user explicitly signed off. A TERMINATED/crashed
curiosity is NOT clear. Stops the neuron laundering a disrupted
curiosity into "goal clear" and skipping the loop (new-trends failure).
"""

import uuid
from datetime import datetime, timezone

from edp_contracts import BrokerMessage, ToolError, ToolOk

from edp_claude.schemas import Recipe


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _recipe(env, rid="r-gate"):
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state="comprehending",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[], context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))
    return rid


async def _send_curiosity(env, to, body):
    await env.ctx.broker.send(BrokerMessage.model_validate({
        "msg_id": str(uuid.uuid4()), "ts": datetime.now(timezone.utc),
        "from": f"curiosity-{uuid.uuid4().hex[:8]}", "to": to,
        "kind": "answer", "body": body,
    }))


async def _record(env, rid, desc="d", ver="v"):
    return await env.call("record_outcome", recipe_id=rid,
                          description=desc, verification=ver)


# ── the gate is closed by default ──────────────────────────────────────────
async def test_record_outcome_refused_before_convergence(env):
    rid = _recipe(env)
    res = await _record(env, rid)
    assert isinstance(res, ToolError)
    m = res.message.lower()
    assert "not converged" in m or "comprehension" in m
    assert "curiosity" in m
    assert "terminated" in m            # explicitly: terminated != clear
    # nothing got recorded
    assert env.ctx.recipes.load(rid).comprehension.expected_outcomes == []


# ── path 1: a real curiosity clear/done opens the gate (auto-captured) ──────
async def test_curiosity_done_reply_opens_gate_via_reconcile(env):
    rid = _recipe(env)
    # curiosity replies clear/done. The comprehension auto-capture is part
    # of state-sync, so it moved to `reconcile` (FSM-RESPONSIBILITY) —
    # next_action stays pure. reconcile is the NON-consuming broker sync
    # that converges the gate.
    await _send_curiosity(env, rid, {"clear": True, "status": "done",
                                     "questions": []})
    rc = _ok(await env.call("reconcile", handle=rid, handle_type="recipe"))
    assert rc["changed"] is True
    # flag set automatically on the recipe
    assert env.ctx.recipes.load(rid).comprehension.curiosity_cleared is True
    # the message is still readable via check_inbox (non-consuming scan)
    ci = _ok(await env.call("check_inbox", handle=rid))
    assert any(mm["body"].get("clear") is True for mm in ci["messages"])
    # now record_outcome succeeds
    _ok(await _record(env, rid))
    assert len(env.ctx.recipes.load(rid).comprehension.expected_outcomes) == 1


async def test_curiosity_NOT_clear_does_not_open_gate(env):
    # a reply with clear=false (still interrogating) must NOT open the gate
    rid = _recipe(env, "r-gate-open")
    await _send_curiosity(env, rid, {"clear": False,
                                     "status": "awaiting_followup",
                                     "questions": ["q1"]})
    _ok(await env.call("reconcile", handle=rid, handle_type="recipe"))
    assert env.ctx.recipes.load(rid).comprehension.curiosity_cleared is False
    res = await _record(env, rid)
    assert isinstance(res, ToolError)        # still gated


async def test_terminated_curiosity_stays_gated(env):
    # the new-trends failure: curiosity terminated (no clear reply ever).
    # The gate must stay closed — "questions answered" != "clear".
    rid = _recipe(env, "r-gate-term")
    # (no curiosity clear message is ever delivered)
    res = await _record(env, rid)
    assert isinstance(res, ToolError)
    assert "infer 'clear'" in res.message or "terminated" in res.message.lower()


# ── path 2: explicit user sign-off opens the gate ──────────────────────────
async def test_user_signoff_opens_gate(env):
    rid = _recipe(env, "r-gate-signoff")
    _ok(await env.call("record_comprehension_signoff", recipe_id=rid,
                       user_quote="just proceed, I'm confident"))
    r = env.ctx.recipes.load(rid)
    assert r.comprehension.user_signoff is True
    assert "confident" in r.comprehension.signoff_quote
    _ok(await _record(env, rid))
    assert len(env.ctx.recipes.load(rid).comprehension.expected_outcomes) == 1


async def test_signoff_requires_user_quote(env):
    rid = _recipe(env, "r-gate-noquote")
    res = await env.call("record_comprehension_signoff", recipe_id=rid,
                         user_quote="   ")
    assert isinstance(res, ToolError)
    assert "user_quote" in res.message
    # gate stayed closed
    assert env.ctx.recipes.load(rid).comprehension.user_signoff is False


# ── brief documents the gate ───────────────────────────────────────────────
def test_phase_b_documents_the_gate():
    from pathlib import Path
    g = (Path(__file__).resolve().parents[1] / "docs" / "guides"
         / "neuron-phase-b.md").read_text(encoding="utf-8").lower()
    assert "gated" in g or "gate" in g
    assert "terminated" in g and "not" in g          # terminated != clear
    assert "record_comprehension_signoff" in g
    assert "never infer" in g or "do not infer" in g
