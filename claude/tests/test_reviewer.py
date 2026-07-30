"""v2.4 — domain reviewer-fork replaces /critic.

A recipe-end review is a fresh fork of the trained specialist (role=
reviewer) that judges the deliverable in its own domain. The generic
/critic is retired.
"""

from pathlib import Path

from edp_contracts import ToolError, ToolOk

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"
_GUIDES = Path(__file__).resolve().parents[1] / "docs" / "guides"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _stable_specialist(env, base="base-1", with_doc=True):
    c = _ok(await env.call("create_specialization", name="Java Expert",
                           subject="Java", description="java spring boot"))
    nid, sid = c["neuron_id"], c["spec_id"]
    _ok(await env.call("neuron_set_base_session", neuron_id=nid,
                       session_id=base))
    if with_doc:
        # the reviewer enforces the COMPILED doc, so it must exist
        _ok(await env.call("write_specialist_doc", spec_id=sid,
                           content="# Java\n## Rules\n- tests pass. [required]\n"))
    _ok(await env.call("neuron_set_status", neuron_id=nid,
                       status="pending_review"))
    _ok(await env.call("neuron_set_status", neuron_id=nid, status="stable"))
    return nid


async def test_branch_reviewer_spawns_fresh_not_forked(env):
    # 2026-06-02: the reviewer launches FRESH (no base resume) and enforces
    # the compiled doc — review is as cheap as a worker, no chat replay.
    nid = await _stable_specialist(env, base="base-1")
    out = _ok(await env.call(
        "branch_reviewer", neuron_id=nid,
        target="/path/TimeController.java",
        criteria="GET /time returns 200 + ISO-8601 JSON",
        handle="recipe-x"))
    rid, fork = out["reviewer_id"], out["fork_session_id"]
    assert rid.startswith(f"review-{nid}-")
    task = (await env.ctx.broker.poll(rid))[0]
    assert task.body["caller"] == "recipe-x"

    sp = [s for s in env.ctx.pool.spawns if s["handle"] == rid]
    assert len(sp) == 1
    assert sp[0]["role"] == "reviewer"
    # FRESH: a pinned session id, NO base resume (the fork is gone)
    assert sp[0]["resume_session"] is None
    assert sp[0]["base_session"] is None
    assert sp[0]["claude_session"] == fork

    msgs = await env.ctx.broker.poll(rid)
    assert msgs[0].body["task"] == "domain-review"
    assert "TimeController" in msgs[0].body["target"]


async def test_branch_reviewer_requires_compiled_doc(env):
    # a stable specialist with NO compiled doc can't review (no rubric).
    nid = await _stable_specialist(env, with_doc=False)
    res = await env.call("branch_reviewer", neuron_id=nid, target="/t.java",
                         handle="recipe-x")
    assert isinstance(res, ToolError)
    assert "compiled doc" in res.message.lower()


async def test_branch_reviewer_forwards_concerns(env):
    # 2026-06-01 (Decision 5): the reviewer must receive the action's
    # cross-cutting concerns so it assembles + enforces the FULL layered
    # ruleset (universal + tech + concerns), not just its tech leaf.
    nid = await _stable_specialist(env, base="base-c")
    out = _ok(await env.call(
        "branch_reviewer", neuron_id=nid, target="/path/LoginController.java",
        criteria="auth is sound", concerns=["security"], handle="recipe-y"))
    task = (await env.ctx.broker.poll(out["reviewer_id"]))[0]
    assert task.body["concerns"] == ["security"]


async def test_branch_reviewer_defaults_concerns_empty(env):
    nid = await _stable_specialist(env, base="base-d")
    out = _ok(await env.call("branch_reviewer", neuron_id=nid,
                             target="/t.java", handle="recipe-z"))
    task = (await env.ctx.broker.poll(out["reviewer_id"]))[0]
    assert task.body["concerns"] == []


async def test_branch_reviewer_requires_stable_based(env):
    c = _ok(await env.call("create_specialization", name="X", subject="x",
                           description="x"))
    # trained, no base, not stable → refused
    r = await env.call("branch_reviewer", neuron_id=c["neuron_id"],
                       target="t")
    assert isinstance(r, ToolError)


def test_critic_is_retired():
    # the generic critic tool + briefs are gone
    import tempfile

    from edp_claude.server import make_context
    from edp_claude.tools import build_registry
    names = {t.name for t in build_registry(make_context(tempfile.mkdtemp()))}
    assert "consult_critic" not in names
    assert "branch_reviewer" in names
    assert not (_CMD / "critic.md").exists()
    assert not (_CMD / "critic-review.md").exists()
    assert (_CMD / "reviewer.md").exists()


def test_reviewer_brief_discipline():
    b = (_CMD / "reviewer.md").read_text(encoding="utf-8").lower()
    # 2026-06-03: the reviewer launches FRESH and loads the compiled doc —
    # it is NOT a fork of the trained chat.
    assert "fresh domain reviewer" in b
    assert "not a fork" in b and "get_specialist_doc" in b
    assert "review" in b and "verdict" in b
    assert "pass" in b and "fail" in b and "concerns" in b
    assert "check_inbox" in b and "reply" in b
    # reviews, doesn't build
    assert "building" in b or "you review" in b


def test_phase_e_does_recipe_end_review():
    e = (_GUIDES / "neuron-phase-e.md").read_text(encoding="utf-8").lower()
    assert "branch_reviewer" in e
    assert "domain" in e and "review" in e


def test_phase_e_passes_concerns_and_prefers_matched_reviewer():
    # 2026-06-01 (Decision 5): recipe-end review threads the actions'
    # concerns into branch_reviewer, and prefers a concern-matched
    # specialist (e.g. a security reviewer) when one exists.
    e = (_GUIDES / "neuron-phase-e.md").read_text(encoding="utf-8").lower()
    assert "concerns=" in e
    assert "neuron_search" in e and "security" in e
    assert "additional reviewer" in e or "concern-matched" in e
