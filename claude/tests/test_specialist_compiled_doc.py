"""SPECIALIST-COMPILED-DOCS.md (2026-06-02), Stage 1.

The compiled per-stack instruction doc: write_specialist_doc (SME writes it)
+ get_specialist_doc (worker loads it clean), stored at
.specs/<spec_id>/compiled.md.
"""

from edp_contracts import ToolError, ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _spec(env):
    return _ok(await env.call("create_specialization", name="React TS",
                              subject="react", description="react ts"))["spec_id"]


_DOC = (
    "# Specialist: React + TypeScript\n\n"
    "## House style\n- Server state: TanStack Query v5. [required]\n"
    "## Never\n- useEffect-as-fetch.\n"
)


async def test_write_then_get_specialist_doc_round_trips(env):
    sid = await _spec(env)
    out = _ok(await env.call("write_specialist_doc", spec_id=sid, content=_DOC))
    assert out["bytes"] == len(_DOC)
    assert out["path"].endswith("compiled.md")
    got = _ok(await env.call("get_specialist_docs", spec_ids=[sid]))
    # F37#6: the provenance banner frames the grounding; doc rides verbatim
    assert got["grounding"].startswith("<!-- SPECIALIST GROUNDING")
    assert got["grounding"].endswith(_DOC)
    # lands next to the JSON + snapshots
    assert (env.ctx.specs.doc_path(sid)).exists()


async def test_get_specialist_doc_null_when_not_compiled(env):
    sid = await _spec(env)
    got = _ok(await env.call("get_specialist_docs", spec_ids=[sid]))
    assert got["grounding"] is None        # no doc yet → worker surfaces BLOCKED


async def test_get_specialist_doc_unknown_spec_is_null(env):
    got = _ok(await env.call("get_specialist_docs", spec_ids=["spec-nope"]))
    assert got["grounding"] is None


async def test_write_specialist_doc_rejects_empty(env):
    sid = await _spec(env)
    res = await env.call("write_specialist_doc", spec_id=sid, content="   ")
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"


async def test_write_specialist_doc_unknown_spec_is_precondition(env):
    res = await env.call("write_specialist_doc", spec_id="spec-nope",
                         content=_DOC)
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"


async def test_recompile_overwrites(env):
    sid = await _spec(env)
    _ok(await env.call("write_specialist_doc", spec_id=sid, content=_DOC))
    v2 = "# v2\nnew content\n"
    _ok(await env.call("write_specialist_doc", spec_id=sid, content=v2))
    got = _ok(await env.call("get_specialist_docs", spec_ids=[sid]))
    assert got["grounding"].endswith(v2)
