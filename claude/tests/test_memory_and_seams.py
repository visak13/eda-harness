"""Coverage for the file-memory + FSM-abstention seams (DESIGN-v4 §5, §3)."""

from edp_contracts import ToolError, ToolOk

from edp_claude.server import make_context
from edp_claude.tools import build_registry


async def _tools(tmp_path):
    return {t.name: t for t in build_registry(make_context(tmp_path))}


async def test_remember_then_recall_software_engineering(tmp_path):
    t = await _tools(tmp_path)
    res = await t["record_context"].run(
        {"kind": "fact", "fact": {"text": "Ed25519 chosen for signing"},
         "domain": "software_engineering"})
    assert isinstance(res, ToolOk) and res.data["stored"] is True
    got = await t["recall"].run({"query": "ed25519 signing"})
    assert isinstance(got, ToolOk)
    assert any("Ed25519" in str(r) for r in got.data["results"])


async def test_se_kg_filter_rejects_chatter(tmp_path):
    t = await _tools(tmp_path)
    res = await t["record_context"].run(
        {"kind": "fact", "fact": {"text": "let me think about this"},
         "domain": "software_engineering"})
    assert isinstance(res, ToolOk)
    assert res.data["stored"] is False
    assert "chatter" in res.data["reason"]


async def test_generic_domain_rejects_non_durable(tmp_path):
    t = await _tools(tmp_path)
    res = await t["record_context"].run({"kind": "fact", "fact": {"text": "x"}, "domain": "generic"})
    assert isinstance(res, ToolOk) and res.data["stored"] is False
    res2 = await t["record_context"].run(
        {"kind": "fact", "fact": {"text": "x", "durable": True}, "domain": "generic"})
    assert res2.data["stored"] is True


async def test_recall_empty_when_no_store(tmp_path):
    t = await _tools(tmp_path)
    got = await t["recall"].run({"query": "anything"})
    assert isinstance(got, ToolOk) and got.data["results"] == []


async def test_unknown_domain_falls_back_to_generic(tmp_path):
    t = await _tools(tmp_path)
    res = await t["record_context"].run(
        {"kind": "fact", "fact": {"text": "y"}, "domain": "astrophysics"})
    # generic fallback => rejected (not durable)
    assert isinstance(res, ToolOk) and res.data["stored"] is False


async def test_stub_fsm_abstains_with_envelope(tmp_path):
    ctx = make_context(tmp_path)
    res = await ctx.fsm.decide("r", {}, [])
    assert isinstance(res, ToolError)
    assert res.code == "fsm_undecidable"
    assert res.source == "edp-fsm"
