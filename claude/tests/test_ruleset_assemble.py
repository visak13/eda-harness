"""SPECIALIZATION-LAYERED-RULESETS.md (2026-06-01), Stage 3.

Assemble a worker's effective ruleset from the layers: tech `extends`-chain
(universal-first, most-specific-last) + per-action `concerns`, split into
the constructive (coder) and enforced (verify) views. Cycles / missing
parents are refused, never partially assembled.
"""

from datetime import datetime, timezone

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.ruleset import AssembleError, assemble_ruleset
from edp_claude.schemas import SpecEntry, Specialization

_NOW = datetime.now(timezone.utc)


def _spec(spec_id, entries, extends):
    return Specialization(
        spec_id=spec_id, neuron_id=spec_id, name=spec_id, subject="x",
        entries=entries, extends=extends, created_at=_NOW, updated_at=_NOW,
    )


def _loader(*specs):
    store = {s.spec_id: s for s in specs}
    return lambda sid: store.get(sid)


# ── pure resolver ────────────────────────────────────────────────────────

def test_extends_chain_is_universal_first_most_specific_last():
    universal = _spec("spec-universal", [
        SpecEntry(kind="checklist", text="logging", adherence="required")], [])
    java = _spec("spec-java", [
        SpecEntry(kind="step", text="model aggregates")], ["spec-universal"])
    spring = _spec("spec-spring", [
        SpecEntry(kind="work_order", text="controller then service")],
        ["spec-java"])
    r = assemble_ruleset(_loader(universal, java, spring), "spec-spring")
    assert r.layers == ["spec-universal", "spec-java", "spec-spring"]


def test_split_into_constructive_enforced_and_mcp_bindings():
    universal = _spec("spec-universal", [
        SpecEntry(kind="checklist", text="logging", adherence="required"),
        SpecEntry(kind="link", text="docs/guides/coding-standards.md",
                  link_role="ruleset", adherence="required"),
        SpecEntry(kind="step", text="design first")], [])
    spring = _spec("spec-spring", [
        SpecEntry(kind="link", text="eda-designs://react", link_role="mcp_binding"),
        SpecEntry(kind="anti_pattern", text="anemic model")], ["spec-universal"])
    r = assemble_ruleset(_loader(universal, spring), "spec-spring")
    enforced = {e.text for e in r.enforced}
    constructive = {e.text for e in r.constructive}
    assert "logging" in enforced                      # checklist → verify
    assert "docs/guides/coding-standards.md" in enforced   # ruleset link → verify
    assert "design first" in constructive             # step → coder
    assert "anemic model" in constructive             # anti_pattern → coder
    # mcp_binding shows up for the coder AND in the convenience list
    assert "eda-designs://react" in constructive
    assert {e.text for e in r.mcp_bindings} == {"eda-designs://react"}
    # each enforced entry keeps its adherence + provenance
    log = next(e for e in r.enforced if e.text == "logging")
    assert log.adherence == "required" and log.layer == "spec-universal"


def test_additive_union_dedupes_keeping_most_universal():
    universal = _spec("spec-universal", [
        SpecEntry(kind="checklist", text="logging", adherence="required")], [])
    # a leaf that restates a CORE rule must not double it; provenance stays CORE
    spring = _spec("spec-spring", [
        SpecEntry(kind="checklist", text="logging", adherence="required")],
        ["spec-universal"])
    r = assemble_ruleset(_loader(universal, spring), "spec-spring")
    logs = [e for e in r.enforced if e.text == "logging"]
    assert len(logs) == 1 and logs[0].layer == "spec-universal"


def test_concern_chain_appends_after_tech():
    universal = _spec("spec-universal", [
        SpecEntry(kind="checklist", text="logging", adherence="required")], [])
    spring = _spec("spec-spring", [
        SpecEntry(kind="step", text="build")], ["spec-universal"])
    security = _spec("spec-security", [
        SpecEntry(kind="checklist", text="validate all input",
                  adherence="required", link_role=None)], ["spec-universal"])
    r = assemble_ruleset(_loader(universal, spring, security),
                         "spec-spring", concerns=["security"])
    # universal appears once (deduped), security appended after tech
    assert r.layers == ["spec-universal", "spec-spring", "spec-security"]
    assert "validate all input" in {e.text for e in r.enforced}


def test_cycle_is_refused():
    a = _spec("spec-a", [SpecEntry(kind="step", text="x")], ["spec-b"])
    b = _spec("spec-b", [SpecEntry(kind="step", text="y")], ["spec-a"])
    with pytest.raises(AssembleError) as ei:
        assemble_ruleset(_loader(a, b), "spec-a")
    assert "cycle" in str(ei.value).lower()


def test_missing_parent_is_refused_not_partial():
    leaf = _spec("spec-leaf", [SpecEntry(kind="step", text="x")],
                 ["spec-ghost"])
    with pytest.raises(AssembleError) as ei:
        assemble_ruleset(_loader(leaf), "spec-leaf")
    assert "spec-ghost" in str(ei.value)
    assert "does not exist" in str(ei.value)


# ── the tool ─────────────────────────────────────────────────────────────

def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def test_assemble_ruleset_tool_resolves_universal_under_a_tech_spec(env):
    _ok(await env.call("ensure_universal"))
    d = _ok(await env.call("create_specialization", name="Spring", subject="spring",
                           description="spring boot rest"))
    sid = d["spec_id"]
    _ok(await env.call("add_spec_entry", spec_id=sid, kind="work_order",
                       text="controller routes only", adherence="required"))
    out = _ok(await env.call("assemble_ruleset", spec_id=sid))
    # a freshly-created tech spec extends the universal layer by default
    assert out["layers"][0] == "spec-universal"
    assert out["layers"][-1] == sid
    # the CORE standards are present in the enforced view
    assert any("logging" in e["text"].lower() for e in out["enforced"])


async def test_assemble_ruleset_tool_refuses_missing_concern(env):
    _ok(await env.call("ensure_universal"))
    d = _ok(await env.call("create_specialization", name="React", subject="react",
                           description="react tailwind"))
    res = await env.call("assemble_ruleset", spec_id=d["spec_id"],
                         concerns=["nonexistent"])
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"
