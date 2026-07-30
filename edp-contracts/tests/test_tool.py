"""TESTPLAN §2 — tool.py (load-bearing)."""

import inspect

import pytest
from pydantic import BaseModel

from edp_contracts import Tool, ToolError, ToolOk
from edp_contracts.errors import EnvelopeViolation, ErrorCode
from edp_contracts.tool import _REQUIRED_ENVELOPE_KEYS


class _In(BaseModel):
    x: int


class _Out(BaseModel):
    y: int


class _GoodTool(Tool):
    name = "good"
    backing = "python"
    idempotent = True
    InputModel = _In
    OutputModel = _Out

    async def run(self, inp: BaseModel):
        return self.ok(_Out(y=inp.x + 1))


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


async def test_tool_1_conforming_runs_and_ok_roundtrips():
    """TOOL-1 MUST."""
    t = _GoodTool()
    res = await t.run(_In(x=41))
    assert isinstance(res, ToolOk)
    assert res.ok is True
    assert res.data == {"y": 42}


def test_tool_1b_abc_blocks_incomplete_subclass():
    """TOOL-1 corollary: Tool is a real ABC (refactor S3b)."""

    class _Bad(Tool):
        name = "bad"
        backing = "python"
        idempotent = True
        InputModel = _In
        OutputModel = _Out
        # no run()

    with pytest.raises(TypeError):
        _Bad()


def test_tool_2_propagate_verbatim():
    """TOOL-2 MUST — message byte-identical, nothing appended."""
    msg = "max workers = 3; 3 active; cannot spawn a 4th"
    e = Tool.propagate(
        source="edp-pool", code=ErrorCode.POOL_CAPACITY_EXCEEDED, message=msg
    )
    assert e.message == msg
    assert e.source == "edp-pool"
    assert e.code == ErrorCode.POOL_CAPACITY_EXCEEDED
    assert e.retryable is True  # capacity is retryable-by-default


def test_tool_3_no_digest_surface():
    """TOOL-3 MUST — no constructor transforms the message."""
    # Only propagate / from_upstream / ok exist as result constructors.
    ctors = {
        n
        for n, _ in inspect.getmembers(Tool, predicate=inspect.isfunction)
        if not n.startswith("_")
    }
    assert ctors == {"ok", "propagate", "from_upstream", "run"}
    assert not hasattr(ToolError, "summarize")
    assert not hasattr(Tool, "summarize")


def test_tool_4_from_upstream_preserves():
    """TOOL-4 MUST."""
    body = {
        "ok": False,
        "source": "edp-pool",
        "code": "pool_spawn_failed",
        "message": "boom: shell exited 1",
        "retryable": False,
    }
    e = Tool.from_upstream(_FakeResp(body))
    assert (e.source, e.code, e.message) == (
        "edp-pool",
        "pool_spawn_failed",
        "boom: shell exited 1",
    )


def test_tool_5_envelope_violation_is_loud():
    """TOOL-5 MUST — malformed upstream raises, never silently wrapped."""
    with pytest.raises(EnvelopeViolation):
        Tool.from_upstream(_FakeResp({"err": "boom"}))


def test_tool_6_union_serializes_with_discriminator():
    """TOOL-6 MUST."""
    ok = ToolOk(data={"y": 1})
    err = Tool.propagate(
        source="tool", code=ErrorCode.TOOL_INPUT_INVALID, message="bad"
    )
    assert ok.model_dump()["ok"] is True
    assert err.model_dump()["ok"] is False


def test_tool_7_precondition_is_instruction_shaped():
    """TOOL-7 SHOULD."""
    e = Tool.propagate(
        source="tool",
        code=ErrorCode.TOOL_PRECONDITION,
        message="cannot mark done — call record_action_status with evidence first",
    )
    assert e.code == ErrorCode.TOOL_PRECONDITION
    assert "first" in e.message


def test_required_envelope_keys_constant():
    """Refactor S3b — extracted constant is the contract."""
    assert _REQUIRED_ENVELOPE_KEYS == ("source", "code", "message")
