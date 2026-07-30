"""Item 2 — close the flow-back loop: a proposed learning can be terminally
resolved so the 'proposed' queue drains.

v7 P0: the SINGULAR resolve_spec_learning verb was deleted (retired by W6.4,
deregistered by the break-and-migrate); the loop now closes through the BATCH
`resolve_spec_learnings` — the same tool the neuron's triage gate uses.
Proposals are seeded via the store primitive the live W3 auto-propose path
calls (the propose tool is gone too).
"""
from edp_contracts import ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _spec(env):
    c = _ok(await env.call("create_specialization", name="X",
                           subject="x", description="x x x"))
    return c["spec_id"]


def _propose(env, sid, rule_text):
    return env.ctx.specs.append_proposed_learning(
        sid, rule_text=rule_text, tag="[preferred]", overrides=None,
        source={"recipe_id": "r-test"})


async def test_resolve_rejected_drains_the_proposed_queue(env):
    sid = await _spec(env)
    lid = _propose(env, sid, "please DISCARD — smoke test")
    # it's in the proposed queue
    q = _ok(await env.call("list_spec_learnings", spec_id=sid,
                           status="proposed"))
    assert q["count"] == 1
    # resolve it as rejected — the batch verb drains the queue
    r = _ok(await env.call("resolve_spec_learnings", spec_id=sid,
                           reject=[lid], note="stale smoke record"))
    assert r["rejected"] == [lid]
    # it has LEFT the proposed queue (last-write-wins)
    q2 = _ok(await env.call("list_spec_learnings", spec_id=sid,
                            status="proposed"))
    assert q2["count"] == 0
    # and is visible terminally
    allq = _ok(await env.call("list_spec_learnings", spec_id=sid, status=None))
    assert any(x["learning_id"] == lid and x["status"] == "rejected"
               for x in allq["learnings"])


async def test_resolve_unknown_learning_is_precondition(env):
    sid = await _spec(env)
    res = await env.call("resolve_spec_learnings", spec_id=sid,
                         accept=["learn-nope"])
    # a non-existent learning id is a precondition error, not a silent no-op
    assert not isinstance(res, ToolOk)
