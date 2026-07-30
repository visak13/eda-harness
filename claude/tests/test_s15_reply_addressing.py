"""s12/s15 ITEM (c) — reply-addressing fix (F6) regression guard.

RCA: C:/Projects/Learning/eda-ml/docs/s12_framework_audit/REPLY-ADDRESSING-RCA.md

The neuron's broker SEND-identity is the symbolic literal ``"neuron"`` but
its LISTEN inbox is its ``recipe_id`` (dash form). ``reply(msg_id)`` faithfully
routes an answer to ``original.from_`` — so a reply to a NEURON-origin message
is addressed ``to="neuron"``. The s16 colon→dash alias bridge has no entry for
``"neuron"``, so without a fix that reply dead-letters in ``neuron.jsonl``, an
inbox the neuron's Monitor / rx.broker / next_action never poll.

FIX (mirrors the s16 pool-at-spawn colon→dash bridge): the neuron's recipe
``reconcile`` tick registers an absolute broker alias ``"neuron" → recipe_id``.
The broker resolves aliases on BOTH the store and read paths, so every
``to="neuron"`` message — including ``reply()``'s ``target=original.from_`` —
is rerouted to the live ``recipe_id`` inbox.

``test_planner_reply_to_neuron_reaches_recipe_inbox`` is the regression lock:
it FAILS on pre-fix code (reconcile registers no alias → the reply lands in
``"neuron"`` and ``poll(recipe_id)`` is empty) and PASSES once the alias is
registered. The companion ``..._dead_letters_without_alias`` documents the
exact pre-fix failure mode without depending on the fix's absence.
"""

from datetime import datetime, timezone

from edp_contracts import ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _executing_recipe_with_step(env, rid, sid):
    """A recipe in EXECUTING with one in-flight spawn_planner step — the
    state in which a planner is naturally talking to the neuron."""
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


def _dispatching_plan(env, rid, sid):
    """A plan for the step so the planner has a real (dash) inbox/identity."""
    from edp_claude.schemas import Plan

    pid = f"{rid}-{sid}"
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id=rid, recipe_step_id=sid,
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "d",
                  "status": "in_progress", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "tests_pass"}}],
    )))
    return pid


async def test_planner_reply_to_neuron_reaches_recipe_inbox(env, monkeypatch):
    """REGRESSION LOCK (fails pre-fix, passes post-fix).

    Neuron (from='neuron') steers a planner; the planner reply(msg_id) must
    reach the neuron's recipe_id inbox — NOT the dead 'neuron' inbox. Pre-fix,
    reconcile registers no alias, the reply lands in 'neuron', and poll on
    recipe_id is empty → the final assertion fails. Post-fix the reconcile
    tick bridges 'neuron' → recipe_id, so the store path reroutes the reply.
    """
    rid = "recipe-s15-reply"
    sid = "s1"
    _executing_recipe_with_step(env, rid, sid)
    pid = _dispatching_plan(env, rid, sid)

    # 1) Neuron's reconcile tick registers 'neuron' -> recipe_id (the fix).
    #    In production this runs at resume + every heartbeat, i.e. BEFORE any
    #    planner reply, exactly as ordered here.
    monkeypatch.delenv("EDP_HANDLE", raising=False)   # neuron has no handle
    monkeypatch.delenv("EDP_ROLE", raising=False)
    _ok(await env.call("reconcile", handle=rid, handle_type="recipe"))

    # 2) Neuron -> planner steer (broker_send defaults from='neuron').
    _ok(await env.call("broker_send", to=pid, kind="steer", body={"go": True}))
    steer = (await env.ctx.broker.poll(pid))[-1]
    assert steer.from_ == "neuron"            # the seed: neuron's send-identity

    # 3) Planner replies (its identity makes reply's from = the dash plan_id;
    #    reply routes to=original.from_ = "neuron").
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:{sid}")
    monkeypatch.setenv("EDP_ROLE", "planner")
    _ok(await env.call("reply", msg_id=steer.msg_id, body={"ack": True}))

    # 4) GUARD: the neuron, polling recipe_id, sees the reply. Pre-fix this
    #    inbox is empty (the reply dead-lettered in 'neuron').
    inbox = await env.ctx.broker.poll(rid)
    acks = [m for m in inbox
            if m.kind == "answer" and m.body.get("ack") is True
            and m.body.get("in_reply_to") == steer.msg_id]
    assert len(acks) == 1, (
        "planner reply to a neuron-origin message did not reach the recipe_id "
        f"inbox (got {inbox!r}) — the 'neuron' -> recipe_id alias was not "
        "registered on the reconcile tick"
    )


async def test_reply_to_neuron_dead_letters_without_alias(env, monkeypatch):
    """NEGATIVE / pre-fix behavior documentation.

    With NO alias registered (no reconcile tick), a reply to a neuron-origin
    message lands in the literal 'neuron' inbox and is ABSENT from recipe_id —
    the dead-letter the fix eliminates. This passes on both pre- and post-fix
    code (it never registers the alias) and pins the failure mode the lock
    above guards against.
    """
    rid = "recipe-s15-deadletter"
    sid = "s1"
    _executing_recipe_with_step(env, rid, sid)
    pid = _dispatching_plan(env, rid, sid)

    # Neuron -> planner steer WITHOUT a reconcile tick (no alias registered).
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.delenv("EDP_ROLE", raising=False)
    _ok(await env.call("broker_send", to=pid, kind="steer", body={"go": True}))
    steer = (await env.ctx.broker.poll(pid))[-1]

    # Planner replies -> routes to="neuron".
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:{sid}")
    monkeypatch.setenv("EDP_ROLE", "planner")
    _ok(await env.call("reply", msg_id=steer.msg_id, body={"ack": True}))

    # The reply dead-letters in 'neuron'; the neuron's recipe_id inbox is empty.
    assert any(m.kind == "answer" for m in await env.ctx.broker.poll("neuron"))
    assert not [m for m in await env.ctx.broker.poll(rid)
                if m.kind == "answer"]


async def test_broker_alias_reroutes_send_and_poll(env):
    """BROKER-LEVEL guard (mirrors RCA §7.1): once 'neuron' -> target is
    registered, a publish to 'neuron' is stored under target and a poll on
    target returns it; an unregistered name still resolves to identity."""
    import uuid

    from edp_contracts import BrokerMessage

    target = "rec-s15-xyz"
    await env.ctx.broker.register_alias("neuron", target)

    msg = BrokerMessage(
        msg_id=str(uuid.uuid4()), ts=datetime.now(timezone.utc),
        **{"from": "rec-s15:s1"}, to="neuron", kind="answer", body={"a": 1},
    )
    _ok(await env.ctx.broker.send(msg))

    # Stored under the alias target; poll on the live inbox finds it.
    got = await env.ctx.broker.poll(target)
    assert len(got) == 1 and got[0].body == {"a": 1}
    # Append/read symmetry: polling the alias name resolves to the same file.
    assert len(await env.ctx.broker.poll("neuron")) == 1
    # Behavior-preserving: an unmapped recipient still resolves to identity.
    assert await env.ctx.broker.poll("some-other-inbox") == []
