"""SPEC-FLOWBACK (2026-06-04; reshaped by DESIGN-v7 P0).

A worker's field-discovered stack-craft reaches a spec's QUARANTINED sidecar
`.specs/<spec_id>/learnings.jsonl` via the W3 auto-propose path
(`emit_recipe_event(kind="learning")` → `_autopropose_learning` →
`SpecStore.append_proposed_learning`). The proposal must NOT enter the live
read path (load / assemble_ruleset / compiled docs) until a human approves it
through `resolve_spec_learnings`.

v7 P0 DELETED the explicit `propose_spec_learning` tool (retired by W6.4,
deregistered by v7 break-and-migrate) — proposals here are seeded through the
same store primitive the live auto-propose path calls
(test_w3_spec_flowback_store.py covers that primitive directly). What THIS
file pins is the surviving read surface: `list_spec_learnings` and the
quarantine invariant.
"""

from edp_contracts import ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _spec(env):
    return _ok(await env.call("create_specialization", name="React TS",
                              subject="react", description="react ts"))["spec_id"]


def _propose(env, sid, rule_text, tag="[preferred]"):
    """Seed a proposal exactly as the live W3 auto-propose path does."""
    return env.ctx.specs.append_proposed_learning(
        sid, rule_text=rule_text, tag=tag, overrides=None,
        source={"recipe_id": "r-test", "action_id": "a1"})


async def test_propose_then_list_round_trips(env):
    sid = await _spec(env)
    lid = _propose(env, sid, "never useEffect-as-fetch", tag="[required]")
    assert lid.startswith("learn-")
    listed = _ok(await env.call("list_spec_learnings", spec_id=sid))
    assert listed["count"] == 1
    rec = listed["learnings"][0]
    assert rec["learning_id"] == lid
    assert rec["status"] == "proposed"
    assert rec["rule_text"] == "never useEffect-as-fetch"
    assert rec["tag"] == "[required]"
    assert "ts" in rec                       # append_jsonl stamps it


async def test_proposals_are_quarantined_from_live_read_path(env):
    """The crux: a proposal must NOT leak into the spec the worker reads."""
    sid = await _spec(env)
    _propose(env, sid, "pin TanStack Query v5")
    # the live specialization the worker/assembler reads is UNCHANGED —
    # no entry was added by proposing.
    spec = _ok(await env.call("get_specialization", spec_id=sid))["spec"]
    assert spec["entries"] == []
    # and there is no compiled doc materialized from a mere proposal
    # (the plural read is the only live doc surface post-v7).
    docs = _ok(await env.call("get_specialist_docs", spec_ids=[sid]))
    assert docs.get("grounding") is None
    # the sidecar file exists; the live JSON has no learnings field.
    assert env.ctx.specs.learnings_path(sid).exists()


async def test_status_filter(env):
    sid = await _spec(env)
    _propose(env, sid, "a")
    _propose(env, sid, "b")
    # default status='proposed' returns both
    assert _ok(await env.call("list_spec_learnings", spec_id=sid))["count"] == 2
    # a status nobody wrote returns an empty queue, not an error
    none = _ok(await env.call("list_spec_learnings", spec_id=sid,
                              status="approved"))
    assert none["count"] == 0 and none["learnings"] == []
    # status=None (null) returns all records regardless of status
    all_ = _ok(await env.call("list_spec_learnings", spec_id=sid, status=None))
    assert all_["count"] == 2


async def test_append_only_accumulates(env):
    sid = await _spec(env)
    for t in ("one", "two", "three"):
        _propose(env, sid, t)
    texts = [r["rule_text"] for r in
             _ok(await env.call("list_spec_learnings", spec_id=sid))["learnings"]]
    assert texts == ["one", "two", "three"]   # ordered, nothing overwritten


async def test_list_unknown_spec_is_empty_not_error(env):
    listed = _ok(await env.call("list_spec_learnings", spec_id="spec-nope"))
    assert listed["count"] == 0 and listed["learnings"] == []
