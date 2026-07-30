"""v2.2 — the curiosity neuron (per-decision interrogator).

consult_curiosity mirrors consult_critic: posts {decision, context} to
the curiosity inbox FIRST, then spawns a /curiosity shell. The neuron
relays its questions to the user and re-consults with answers until
clear. The brief enforces: surface ambiguity (esp. location), never
decide for the user, `clear` is valid.
"""

from pathlib import Path

from edp_contracts import ToolOk

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"
_GUIDES = Path(__file__).resolve().parents[1] / "docs" / "guides"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def test_consult_curiosity_posts_then_spawns(env):
    res = _ok(await env.call(
        "consult_curiosity",
        decision="where should I build this Java project?",
        context="goal: tiny Java REST endpoint; cwd is the live repo",
        handle="recipe-x"))
    cid = res["curiosity_id"]
    assert cid.startswith("curiosity-")

    spawns = [s for s in env.ctx.pool.spawns if s["role"] == "curiosity"]
    assert len(spawns) == 1 and spawns[0]["handle"] == cid

    # the consult is in the curiosity inbox BEFORE spawn (Step 0 reads it)
    msgs = await env.ctx.broker.poll(cid)
    assert len(msgs) == 1
    c = msgs[0]
    assert c.kind == "consult"
    assert "where should I build" in c.body["decision"]
    assert "live repo" in c.body["context"]
    # 2026-05-24 fix: from = the recipe handle (so the reply routes back
    # to where the neuron polls), NOT the literal "neuron".
    assert c.from_ == "recipe-x"
    assert c.body["caller"] == "recipe-x"


async def test_curiosity_reply_routes_back_to_the_neuron_handle(env):
    # the bug: curiosity's reply went to "neuron" but the neuron polls
    # the recipe handle → dead letter. With handle set, the reply lands
    # where next_action(recipe) reads it.
    res = _ok(await env.call("consult_curiosity", decision="d",
                             handle="recipe-route"))
    cid = res["curiosity_id"]
    consult = (await env.ctx.broker.poll(cid))[0]
    # curiosity replies to the consult
    _ok(await env.call("broker_send", to=consult.from_, kind="answer",
                       body={"clear": False, "questions": ["where?"],
                             "in_reply_to": consult.msg_id}))
    # the neuron, polling its recipe handle, receives it
    got = await env.ctx.broker.poll("recipe-route")
    assert any(m.kind == "answer" for m in got)


async def test_consult_curiosity_requires_handle_from_main_shell(env):
    # called without handle from the neuron's main shell (no EDP_HANDLE)
    # → precondition, not a silent dead-letter.
    from edp_contracts import ToolError
    r = await env.call("consult_curiosity", decision="d")
    assert isinstance(r, ToolError)
    assert "handle" in r.message.lower()


async def test_consult_curiosity_unique_per_decision(env):
    a = _ok(await env.call("consult_curiosity", decision="d1",
                           handle="r"))["curiosity_id"]
    b = _ok(await env.call("consult_curiosity", decision="d2",
                           handle="r"))["curiosity_id"]
    assert a != b   # a fresh interrogator per decision point


def test_curiosity_brief_discipline():
    b = (_CMD / "curiosity.md").read_text(encoding="utf-8").lower()
    assert "interrogat" in b
    assert "location" in b and "cost" in b and "scope" in b
    # never decides for the user
    assert "answering the question yourself" in b or "decide for them" in b \
        or "make it for them" in b
    # clear is a valid verdict
    assert "clear" in b
    assert "check_inbox" in b and "reply" in b


def test_phase_b_drives_curiosity_not_solo_decisions():
    b = (_GUIDES / "neuron-phase-b.md").read_text(encoding="utf-8").lower()
    assert "consult_curiosity" in b
    assert "do not decide alone" in b or "you do not decide alone" in b
    assert "askuserquestion" in b
    # the comprehension loop runs until curiosity converges. Post-2026-05-28
    # this is the persistent two-way loop: follow up on the same
    # curiosity_id until status="done".
    assert "loop step 2" in b or "until `status=\"done\"`" in b \
        or "follow-up" in b
