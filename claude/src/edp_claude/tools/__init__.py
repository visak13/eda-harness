from ._tools import ALL_TOOL_CLASSES
from .base import Ctx


def build_registry(ctx: Ctx) -> list:
    """Instantiate every tool with the injected context. The MCP server
    registers exactly this list (LLD §5 registry)."""
    return [cls(ctx) for cls in ALL_TOOL_CLASSES]


__all__ = ["build_registry", "Ctx", "ALL_TOOL_CLASSES"]
