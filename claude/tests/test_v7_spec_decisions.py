"""v7 WS3 §2.6 — the convention/decision split in specializations, and the
test-lineage tool surface (§2.5b)."""

import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _mk_spec(env) -> str:
    res = await env.call("create_specialization", name="tooling",
                         subject="LLM tool-call transport",
                         description="tool-call transport craft")
    return res.data["spec_id"]


async def test_decision_requires_alternatives(env):
    sid = await _mk_spec(env)
    res = await env.call("add_spec_entry", spec_id=sid, kind="decision",
                         text="use JSON tool output",
                         revisit_when="native calls malform args")
    assert not res.ok and "alternatives is empty" in res.message


async def test_decision_requires_revisit_when(env):
    sid = await _mk_spec(env)
    res = await env.call("add_spec_entry", spec_id=sid, kind="decision",
                         text="use JSON tool output",
                         alternatives=["ollama native tool calls"])
    assert not res.ok and "revisit_when is empty" in res.message


async def test_decision_required_adherence_needs_justification(env):
    sid = await _mk_spec(env)
    res = await env.call("add_spec_entry", spec_id=sid, kind="decision",
                         text="never eval() user input",
                         alternatives=["sandboxed eval"],
                         revisit_when="a vetted sandbox lands",
                         adherence="required")
    assert not res.ok and "reserved for safety" in res.message
    ok = await env.call("add_spec_entry", spec_id=sid, kind="decision",
                        text="never eval() user input",
                        alternatives=["sandboxed eval"],
                        revisit_when="a vetted sandbox lands",
                        adherence="required",
                        note="RCE risk — safety, not preference")
    assert ok.ok


async def test_decision_fields_refused_on_convention_kinds(env):
    sid = await _mk_spec(env)
    res = await env.call("add_spec_entry", spec_id=sid, kind="checklist",
                         text="lint passes",
                         alternatives=["nothing"])
    assert not res.ok and "decision-only fields" in res.message


async def test_valid_decision_persists_and_roundtrips(env):
    sid = await _mk_spec(env)
    res = await env.call("add_spec_entry", spec_id=sid, kind="decision",
                         text="use JSON tool output",
                         note="stronger under our providers",
                         alternatives=["ollama native tool calls"],
                         revisit_when="native calls stop malforming args")
    assert res.ok
    spec = env.ctx.specs.load(sid)
    e = spec.entries[-1]
    assert e.kind == "decision" and e.adherence == "expected"
    assert e.alternatives == ["ollama native tool calls"]
    assert e.revisit_when.startswith("native calls")
    # legacy entries stay byte-shape-identical: a plain entry emits neither field
    plain = await env.call("add_spec_entry", spec_id=sid, kind="checklist",
                           text="lint passes")
    assert plain.ok
    dumped = env.ctx.specs.load(sid).entries[-1].model_dump()
    assert "alternatives" not in dumped and "revisit_when" not in dumped


async def test_test_lineage_tools_roundtrip(env):
    reg = await env.call("record_test_lineage", test_id="t/x.spec.ts::a",
                         verifies=[], covers=["src/x.ts"])
    assert not reg.ok and "verifies nothing" in reg.message
    reg = await env.call("record_test_lineage", test_id="t/x.spec.ts::a",
                         verifies=["outcome:r1:o1"], covers=["src/x.ts"])
    assert reg.ok
    rep = await env.call("test_lineage_report", files=["src/x.ts"])
    assert rep.ok
    assert rep.data["impacted_tests"] == ["test:t/x.spec.ts::a"]
    # o1 was never declared in any store → the lineage target is dead
    assert ["test:t/x.spec.ts::a", "outcome:r1:o1"] in rep.data["dead_tests"]
