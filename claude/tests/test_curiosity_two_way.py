"""Curiosity persistent two-way comms (REDESIGN 2026-05-28).

The failure: curiosity replied + closed with no lifecycle signal, so the
neuron couldn't tell whether to reuse the same curiosity or spawn a new
one — and ended up launching many while expecting a continuous two-way
conversation. Fix (Model A): one persistent curiosity per cycle; the
neuron follows up on the SAME curiosity_id; curiosity stays alive until
it returns clear; the reply carries a `status`.
"""

from pathlib import Path

from edp_contracts import ToolError, ToolOk

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"
_GUIDES = Path(__file__).resolve().parents[1] / "docs" / "guides"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


# ── tool: spawn vs follow-up ───────────────────────────────────────────────
async def test_first_consult_spawns(env):
    d = _ok(await env.call("consult_curiosity",
                           decision="scope the work",
                           context="ctx", handle="recipe-x"))
    assert d["mode"] == "spawned"
    cid = d["curiosity_id"]
    assert cid.startswith("curiosity-")
    # the pool recorded exactly one curiosity spawn
    spawns = [s for s in env.ctx.pool.spawns
              if s.get("handle") == cid]
    assert len(spawns) == 1


async def test_followup_does_not_spawn_a_second_curiosity(env):
    first = _ok(await env.call("consult_curiosity",
                               decision="d1", context="c1",
                               handle="recipe-x"))
    cid = first["curiosity_id"]
    spawns_before = len(env.ctx.pool.spawns)
    # follow-up to the SAME curiosity — must NOT spawn another
    fu = _ok(await env.call("consult_curiosity",
                            decision="d2 (refined)",
                            context="user answered: ...",
                            handle="recipe-x",
                            curiosity_id=cid))
    assert fu["mode"] == "followup"
    assert fu["curiosity_id"] == cid
    assert len(env.ctx.pool.spawns) == spawns_before   # no new spawn
    # the follow-up consult landed in the SAME curiosity's inbox
    msgs = await env.ctx.broker.poll(cid)
    assert any(m.kind == "consult" and "refined" in m.body["decision"]
               for m in msgs)


async def test_followup_to_closed_curiosity_is_refused(env):
    first = _ok(await env.call("consult_curiosity",
                               decision="d1", context="c1",
                               handle="recipe-x"))
    cid = first["curiosity_id"]
    # simulate curiosity having closed (returned clear → pool_close_self)
    env.ctx.pool.mark_dead(cid)
    res = await env.call("consult_curiosity",
                         decision="d2", context="c2",
                         handle="recipe-x", curiosity_id=cid)
    assert isinstance(res, ToolError)
    assert "not alive" in res.message or "closed" in res.message
    assert "spawn a fresh" in res.message or "fresh one" in res.message


# ── brief discipline ───────────────────────────────────────────────────────
def test_curiosity_brief_is_persistent_two_way():
    b = (_CMD / "curiosity.md").read_text(encoding="utf-8").lower()
    assert "persistent" in b and "two-way" in b
    # heartbeat to wake between rounds, not close-after-one-reply
    assert "croncreate" in b and "heartbeat" in b
    # lifecycle status in the reply
    assert "awaiting_followup" in b and "done" in b and "status" in b
    # stays alive; closes only on clear
    assert "do not" in b and "pool_close_self" in b
    assert "only when you return `clear`" in b or "only after" in b
    # same handle = same shell, remembers prior rounds
    assert "same handle" in b and "remember" in b


def test_phase_b_drives_persistent_curiosity():
    g = (_GUIDES / "neuron-phase-b.md").read_text(encoding="utf-8").lower()
    # follow up on the SAME curiosity_id, don't spawn a second
    assert "curiosity_id" in g
    assert "never spawn a second curiosity" in g \
        or "do not spawn a new one" in g
    # recognize the lifecycle status
    assert "awaiting_followup" in g and "done" in g
    # the named failure is recorded as an anti-pattern
    assert "2026-05-28" in g and "persistent" in g
