"""The Tool contract — every MCP tool the LLM sees is a :class:`Tool`.

Load-bearing rule (DESIGN-v4 §13.2): MCP tools never digest, swallow, or
reword an upstream error. The only sanctioned error constructors are
:meth:`Tool.propagate` and :meth:`Tool.from_upstream`, both verbatim.
There is intentionally no ``summarize``-style helper — the type system +
code review enforce "never digest an error".
"""

from abc import ABC, abstractmethod
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from .errors import RETRYABLE_CODES, EnvelopeViolation, ErrorCode

#: Keys an upstream error body must carry to be a valid envelope.
_REQUIRED_ENVELOPE_KEYS: tuple[str, ...] = ("source", "code", "message")


class ToolOk(BaseModel):
    """Successful tool result. ``data`` is the tool's OutputModel, dumped."""

    model_config = ConfigDict(extra="forbid")

    ok: Literal[True] = True
    data: dict


class ToolError(BaseModel):
    """Failed tool result. ``message`` is VERBATIM upstream text.

    Never construct this with an f-string that interpolates an upstream
    error into new prose — that is "digesting" and is forbidden. Use
    :meth:`Tool.propagate` / :meth:`Tool.from_upstream`.
    """

    model_config = ConfigDict(extra="forbid")

    ok: Literal[False] = False
    source: str  # microservice name, or "tool" for local validation
    code: str  # stable machine code (see errors.py)
    message: str  # verbatim upstream text — never rewritten
    retryable: bool = False


ToolResult = ToolOk | ToolError


@runtime_checkable
class HttpResponseLike(Protocol):
    """Minimal shape of an upstream microservice error response.

    Any object exposing ``.json() -> dict`` satisfies this; keeps
    edp-contracts free of an httpx dependency.
    """

    def json(self) -> dict: ...


class Tool(ABC):
    """Abstract base for every MCP tool.

    Subclasses set the class attributes and implement :meth:`run`.
    ``run`` MUST return a :class:`ToolOk` or :class:`ToolError` — never
    raise for an expected upstream failure, never return a bare dict.

    Note: an ABC enforces *method* implementation at instantiation, not
    *class-attribute* presence (name/backing/InputModel/OutputModel). That
    those attrs are set is a contract-test concern (TESTPLAN TOOL-1), not a
    runtime ABC guarantee.
    """

    name: str
    backing: Literal["python", "masked_llm"]
    idempotent: bool
    InputModel: type[BaseModel]
    OutputModel: type[BaseModel]

    @abstractmethod
    async def run(self, inp: BaseModel) -> ToolResult: ...

    # ── result constructors ──────────────────────────────────────────────

    @staticmethod
    def ok(output: BaseModel) -> ToolOk:
        """Wrap a validated OutputModel instance as a success result."""
        return ToolOk(data=output.model_dump(mode="json"))

    @staticmethod
    def propagate(
        *,
        source: str,
        code: str,
        message: str,
        retryable: bool | None = None,
    ) -> ToolError:
        """Construct a ToolError preserving ``message`` byte-for-byte.

        This is the ONLY sanctioned way to surface an upstream failure.
        There is deliberately no helper that summarizes or translates a
        message (DESIGN-v4 §13.2).

        ``retryable`` defaults from :data:`errors.RETRYABLE_CODES` when not
        given explicitly.
        """
        if retryable is None:
            retryable = code in RETRYABLE_CODES
        return ToolError(
            source=source, code=code, message=message, retryable=retryable
        )

    @staticmethod
    def from_upstream(resp: HttpResponseLike) -> ToolError:
        """Re-wrap a microservice's already-enveloped error, unchanged.

        Every Microservice emits the standard envelope, so an upstream
        error body is expected to be ``{source, code, message, ...}``.
        If it is not, raise :class:`EnvelopeViolation` — a non-conforming
        microservice is a contract failure, surfaced loudly, never
        silently re-wrapped.
        """
        body = resp.json()
        if not isinstance(body, dict) or any(
            k not in body for k in _REQUIRED_ENVELOPE_KEYS
        ):
            raise EnvelopeViolation(
                f"{ErrorCode.ENVELOPE_VIOLATION}: upstream error not in "
                f"standard envelope; got keys "
                f"{sorted(body) if isinstance(body, dict) else type(body).__name__}"
            )
        return ToolError(
            source=str(body["source"]),
            code=str(body["code"]),
            message=str(body["message"]),
            retryable=bool(body.get("retryable", False)),
        )
