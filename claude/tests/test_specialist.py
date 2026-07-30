"""Specialization vision phase 4 (2026-05-22) — /specialist self-train.

Validates the train_specialist substrate (mirrors consult_critic):
- train_specialist posts the {subject, description, category} task to
  the SME's inbox FIRST, then spawns a /specialist shell.
- The SME's broker id is unique per spawn; spawn role is "specialist".
- The brief tells the SME exactly how to operate (research current
  sources, knowledge-as-links, submit to pending_review, don't
  self-approve, don't do the downstream task).
- The full self-train loop (an SME authoring + submitting a recipe)
  drives the existing tools end-to-end.
"""

from pathlib import Path

from edp_contracts import ToolOk

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _body() -> str:
    return (_CMD / "specialist.md").read_text(encoding="utf-8").lower()


async def test_train_specialist_posts_task_then_spawns(env):
    res = _ok(await env.call(
        "train_specialist", subject="Java / DDD / Spring Boot",
        description="domain-driven design and Spring Boot services",
        category="domain", name="Java Expert", handle="recipe-x"))
    sid = res["specialist_id"]
    assert sid.startswith("specialist-java-expert-")
    # 2026-05-24 fix: training_complete routes to the recipe handle
    task = (await env.ctx.broker.poll(sid))[0]
    assert task.body["caller"] == "recipe-x"

    spawns = [s for s in env.ctx.pool.spawns if s["role"] == "specialist"]
    assert len(spawns) == 1 and spawns[0]["handle"] == sid
    # phase 5: the base claude session is pinned up front
    base = res["base_session_id"]
    assert spawns[0]["claude_session"] == base
    # v2.3: interactive training spawns a VISIBLE (monitor) console
    assert spawns[0]["mode"] == "monitor"

    # the task is in the SME inbox BEFORE the spawn (Step 0 reads it)
    msgs = await env.ctx.broker.poll(sid)
    assert len(msgs) == 1
    task = msgs[0]
    assert task.kind == "consult"
    assert task.body["task"] == "self-train"
    assert task.body["subject"].startswith("Java")
    assert task.body["category"] == "domain"
    # the SME learns its branchable base id from the consult
    assert task.body["base_session_id"] == base
    # v2.3: interactive flag tells the SME the user is present
    assert task.body["interactive"] is True


async def test_train_specialist_unique_per_spawn(env):
    a = _ok(await env.call("train_specialist", subject="x",
                           description="x", handle="r"))["specialist_id"]
    b = _ok(await env.call("train_specialist", subject="x",
                           description="x", handle="r"))["specialist_id"]
    assert a != b


async def test_train_specialist_requires_handle_from_main_shell(env):
    from edp_contracts import ToolError
    r = await env.call("train_specialist", subject="x", description="x")
    assert isinstance(r, ToolError) and "handle" in r.message.lower()


async def test_self_train_loop_produces_pending_review_recipe(env):
    # Simulate what the SME shell does: create → fill (links + steps) →
    # checkpoint → submit. Then it's discoverable but NOT yet usable.
    c = _ok(await env.call("create_specialization", name="Java Expert",
                           subject="Java / DDD",
                           description="java ddd spring boot"))
    nid, sid = c["neuron_id"], c["spec_id"]
    assert env.ctx.neurons.get(nid).status == "trained"
    _ok(await env.call("add_spec_entry", spec_id=sid, kind="link",
                       text="https://docs.spring.io", note="official"))
    _ok(await env.call("add_spec_entry", spec_id=sid, kind="anti_pattern",
                       text="anemic domain model"))
    _ok(await env.call("record_spec_version", spec_id=sid,
                       summary="covers DDD + Spring basics"))
    _ok(await env.call("neuron_set_status", neuron_id=nid,
                       status="pending_review"))
    # discoverable, but pending_review (the HITL gate) → not usable yet
    rec = env.ctx.neurons.get(nid)
    assert rec.status == "pending_review"
    # human approves
    _ok(await env.call("neuron_set_status", neuron_id=nid, status="stable"))
    assert env.ctx.neurons.get(nid).status == "stable"


def test_specialist_brief_discipline():
    b = _body()
    assert "self-train" in b or "self training" in b or "become an expert" in b
    # research current sources (token-completion caveat)
    assert "websearch" in b or "web" in b
    assert "check_inbox" in b
    # knowledge as links, not copied content
    assert "link" in b
    # the intent tools it must drive
    assert "create_specialization" in b and "add_spec_entry" in b
    assert "record_spec_version" in b
    # the HITL gate: submit to pending_review, do NOT self-approve
    assert "pending_review" in b
    assert "approving yourself" in b or "self-approval" in b \
        or "approve yourself" in b
    # don't do the downstream task
    assert "downstream task" in b
    # v2.3: interactive training + learns generally (forked for many uses)
    assert "interactive" in b
    assert "forked" in b
    assert "user says training is complete" in b or "user is here" in b \
        or "train with them" in b
