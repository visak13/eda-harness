"""SPECIALIZATION-LAYERED-RULESETS.md (2026-06-01), Stage 2.

The universal coding-standards layer (CORE). `ensure_universal()` is the
idempotent cold-start floor; `docs/guides/coding-standards.md` is the
human-readable source the spec links.
"""

from pathlib import Path

from edp_contracts import ToolOk

_GUIDES = Path(__file__).resolve().parents[1] / "docs" / "guides"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def test_ensure_universal_cold_start_then_idempotent(env):
    first = _ok(await env.call("ensure_universal"))
    assert first["spec_id"] == "spec-universal"
    assert first["created"] is True
    second = _ok(await env.call("ensure_universal"))
    assert second["created"] is False


async def test_universal_spec_is_root_with_adherence_tagged_seeds(env):
    _ok(await env.call("ensure_universal"))
    spec = env.ctx.specs.load("spec-universal")
    # the root of the layering — no parent, no self-cycle
    assert spec.extends == []
    # links the readable ruleset doc
    ruleset = next(e for e in spec.entries if e.link_role == "ruleset")
    assert "coding-standards.md" in ruleset.text
    # the seed carries real adherence weight (not all-default)
    adh = {e.adherence for e in spec.entries}
    assert "required" in adh and "expected" in adh
    # the load-bearing CORE rules are present + required
    text = " ".join(e.text.lower() for e in spec.entries)
    for rule in ("solid", "logging", "naming", "separation of concerns",
                 "integration test", "regex",
                 "close every resource",      # resource-lifecycle (2026-06-02)
                 "swallow an exception",       # exception-handling (2026-06-02)
                 "no secrets in code",         # secrets hygiene (2026-06-02)
                 "no dead or commented-out",   # anti-slop (2026-06-02)
                 "fail fast at boundaries",    # boundary validation (2026-06-02)
                 "timeouts on every outbound",  # hang prevention (2026-06-03)
                 "no magic numbers",            # config hygiene (2026-06-03)
                 "clean up on completion"):     # cleanup + delete-gate (2026-06-03)
        assert rule in text
    # no-regex-without-approval must be required (escalation), not advisory
    regex_entry = next(e for e in spec.entries if "regex" in e.text.lower())
    assert regex_entry.adherence == "required"


async def test_universal_is_not_a_discoverable_neuron(env):
    # it is a base spec, not a branchable neuron — never in neuron_search.
    _ok(await env.call("ensure_universal"))
    assert not env.ctx.neurons.exists("universal")


def test_coding_standards_doc_defines_adherence_behaviors():
    body = (_GUIDES / "coding-standards.md").read_text(encoding="utf-8").lower()
    # the three adherence words are defined by verify behavior (so the LLM
    # can't shrug them off as vague modality)
    for level in ("required", "expected", "preferred"):
        assert level in body
    assert "blocks `done`" in body or "blocks done" in body
    # the coder-vs-verify split is explicit (don't straitjacket the coder)
    assert "verify worker" in body and "coder" in body
    # additive law: a tech layer extends but never weakens CORE
    assert "extend" in body and ("never" in body and "weaken" in body
                                 or "additive" in body)
