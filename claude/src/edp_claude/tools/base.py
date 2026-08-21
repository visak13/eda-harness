"""Tool base + injected context (LLD §5).

Note (flagged for S3b REFACTOR): the LLD §1 listed one file per tool. They
are implemented in `_tools.py` as one cohesive module instead — same
surface, far less ceremony. Deliberate deviation, recorded in REFACTOR.md.
"""

import time
from dataclasses import dataclass

from edp_contracts import Tool, get_logger
from edp_contracts.errors import ErrorCode
from pydantic import BaseModel, ValidationError

from ..ports import BrokerPort, EmbedPort, FsmPort, MemoryPort, PoolPort
from ..store import (NeuronStore, NorthStarStore, PlanStore, RecipeStore,
                     SpecStore)

# Per-shell MCP-tool logger (2026-05-25). Writes one daily-rolling file
# per shell (keyed by EDP_HANDLE) under EDP_LOG_DIR — so when a tool
# HANGS, the disk shows its `tool_start` (with the input) and no
# matching `tool_done`, pinpointing the exact tool + args that stalled.
_log = get_logger("edp-claude")


def _short(v: object, cap: int = 600) -> str:
    s = repr(v)
    return s if len(s) <= cap else s[:cap] + f"…(+{len(s) - cap})"


@dataclass
class Ctx:
    recipes: RecipeStore
    plans: PlanStore
    pool: PoolPort
    broker: BrokerPort
    memory: MemoryPort
    fsm: FsmPort
    neurons: NeuronStore
    specs: SpecStore
    embed: EmbedPort
    # DESIGN-v6 W1: per-recipe north-star store, sharing the .recipes root
    # (the north star lives in the recipe dir alongside recipe.json).
    north_star: NorthStarStore


def instruction_error(exc: ValidationError, model: type[BaseModel],
                      tool_name: str | None = None) -> str:
    """v5 P4: never raw pydantic. Emit a single first-try-actionable
    instruction — required fields (with type), bad enums (with the
    allowed set), and extras to drop. One precise retry, not a guessing
    storm (the prior system's named failure)."""
    missing: list[str] = []
    bad_enum: list[str] = []
    extra: list[str] = []
    for e in exc.errors():
        loc = ".".join(str(p) for p in e["loc"])
        t = e.get("type", "")
        if t == "missing":
            fld = e["loc"][-1] if e["loc"] else loc
            ann = ""
            desc = ""
            try:
                f = model.model_fields[str(fld)]
                ann = repr(f.annotation)
                # QoL F13/F14: a missing-field refusal that names only the
                # TYPE sends the caller into serial guessing (dict — of what
                # shape?). Ship the field's own description with the refusal
                # so the requirement travels with the error. Falls back to
                # the central FIELD_DOCS table (tools/field_docs.py).
                from .field_docs import field_doc
                _d = field_doc(tool_name or "", str(fld), f.description)
                if _d:
                    d = " ".join(_d.split())
                    desc = f" — {d[:220]}"
            except Exception:
                ann = "?"
            missing.append(f"{loc} ({ann}){desc}")
        elif "enum" in t or t == "literal_error":
            allowed = e.get("ctx", {}).get("expected", "?")
            bad_enum.append(f"{loc}: got {e.get('input')!r}; allowed {allowed}")
        elif t == "extra_forbidden":
            extra.append(loc)
        else:
            missing.append(f"{loc}: {e['msg']}")
    parts = []
    if missing:
        parts.append("ADD required: " + "; ".join(missing))
    if bad_enum:
        parts.append("FIX value: " + "; ".join(bad_enum))
    if extra:
        parts.append("DROP extra (not allowed): " + ", ".join(extra))
    return " | ".join(parts) + " | then resend the same tool call."


class _ClaudeTool(Tool):
    backing = "python"
    idempotent = False
    # QoL F12 (2026-08-21 baseline drill): the SAME concept carried a
    # different parameter name per verb (recipe_id vs handle, text vs
    # content, quote vs user_quote, action_id vs branch_id) and every
    # mismatch cost a refusal round-trip. Each tool may declare accepted
    # alternate spellings here: {alias: canonical}. An alias is applied
    # only when the canonical key is absent, so explicit canonical input
    # always wins and nothing is silently overwritten.
    param_aliases: dict[str, str] = {}

    def __init__(self, ctx: Ctx) -> None:
        self.ctx = ctx

    async def run(self, inp: BaseModel):
        name = getattr(self, "name", type(self).__name__)
        raw = inp if isinstance(inp, dict) else inp.model_dump()
        if self.param_aliases and isinstance(raw, dict):
            for alias, canonical in self.param_aliases.items():
                if alias in raw and canonical not in raw:
                    raw[canonical] = raw.pop(alias)
        # logged to DISK before the body runs → a hang shows as a
        # tool_start with no tool_done.
        _log.info("tool_start", name, tool=name, args=_short(raw))
        t0 = time.monotonic()
        try:
            model = self.InputModel.model_validate(raw)
        except ValidationError as e:
            _log.warning(
                "tool_input_invalid", name, tool=name,
                dur_ms=int((time.monotonic() - t0) * 1000),
            )
            return Tool.propagate(
                source="tool",
                code=ErrorCode.TOOL_INPUT_INVALID,
                message=instruction_error(e, self.InputModel, self.name),
            )
        try:
            res = await self._run(model)
        except Exception as e:
            _log.error(
                "tool_exception", name, tool=name, error=_short(e),
                dur_ms=int((time.monotonic() - t0) * 1000),
            )
            raise
        _log.info(
            "tool_done", name, tool=name,
            ok=getattr(res, "ok", None),
            code=getattr(res, "code", None),
            dur_ms=int((time.monotonic() - t0) * 1000),
        )
        return res

    async def _run(self, model: BaseModel):  # pragma: no cover - overridden
        raise NotImplementedError
