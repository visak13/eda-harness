"""FSM stub (LLD §3). The masked-LLM nuanced path is component #5.
Until then this always abstains so the deterministic FSM owns every
decision in the skeleton.

# TODO(edp-fsm, component #5): replace with HttpFsm routing to a
# long-running Claude shell with fsm-* skills (DESIGN-v4 §6).
"""

from edp_contracts import Tool
from edp_contracts.errors import ErrorCode

from ..ports import FsmPort, ToolResult


class StubFsm(FsmPort):
    async def decide(
        self, handle: str, snapshot: dict, events: list[dict]
    ) -> ToolResult:
        return Tool.propagate(
            source="edp-fsm",
            code=ErrorCode.FSM_UNDECIDABLE,
            message="masked-LLM FSM not built (component #5); "
            "deterministic path must decide",
        )
