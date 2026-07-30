"""Phase 6 — subsume comprehension specialists into the neuron DB.

The shipped comprehension specialists become discoverable seeds
(decision #1): stable (pre-approved), editable=False (protected),
guide-backed (no base_session_id → consulted, not branched). The
comprehension phase discovers them via neuron_search instead of a
hardcoded list.
"""

from pathlib import Path

from edp_contracts import ToolOk

_GUIDES = Path(__file__).resolve().parents[1] / "docs" / "guides"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def test_seeding_registers_stable_protected_guide_backed(env):
    out = _ok(await env.call("seed_comprehension_specialists"))
    assert "feasibility" in out["seeded"] and "goal-setter" in out["seeded"]
    assert len(out["seeded"]) == 8 and out["skipped"] == []

    rec = env.ctx.neurons.get("feasibility")
    assert rec.category == "comprehension"
    assert rec.status == "stable"          # pre-approved, no HITL
    assert rec.editable is False            # protected seed
    assert rec.base_session_id is None      # guide-backed, not branched
    # the spec recipe links to the shipped guide (knowledge-as-links)
    spec = env.ctx.specs.load(rec.spec_id)
    link = next(e for e in spec.entries if e.kind == "link")
    assert link.text == "docs/guides/specialist-feasibility.md"


async def test_seeding_is_idempotent(env):
    first = _ok(await env.call("seed_comprehension_specialists"))
    assert len(first["seeded"]) == 8
    second = _ok(await env.call("seed_comprehension_specialists"))
    assert second["seeded"] == [] and len(second["skipped"]) == 8
    # not duplicated
    comp = env.ctx.neurons.list(category="comprehension")
    assert len(comp) == 8


async def test_comprehension_specialists_are_discoverable(env):
    _ok(await env.call("seed_comprehension_specialists"))
    # a gap phrased in the neuron's own words finds the right specialist.
    # (StubEmbed is token-overlap, so the query shares feasibility's
    # vocabulary; real ollama ranks the semantic equivalent — proven in
    # test_http_embed_live.)
    res = _ok(await env.call(
        "neuron_search",
        query="is this achievable at all given the available tools "
              "resources authorization and constraints",
        top_k=3))
    top = res["matches"][0]
    assert top["neuron_id"] == "feasibility"
    assert top["category"] == "comprehension"


async def test_seeded_id_consults_its_guide(env):
    # neuron_id == the guide id, so consult_specialist works directly on
    # a discovered seed.
    _ok(await env.call("seed_comprehension_specialists"))
    out = _ok(await env.call("consult_specialist",
                             specialist_id="feasibility",
                             query="can we build X with the given tools?"))
    assert out["specialist_id"] == "feasibility"
    assert out["knowledge"]              # the guide loaded
    assert out["source"] == "guide"      # seed → guide-backed
    assert out["mode"] == "exact"        # explicit id → no vector search


def test_phase_b_brief_discovers_not_hardcodes():
    b = (_GUIDES / "neuron-phase-b.md").read_text(encoding="utf-8").lower()
    assert "seed_comprehension_specialists" in b
    assert "neuron_search" in b
    assert "discover" in b
