"""edp8 MCP stdio server — registers one participant's role-scoped tool bundle.

On start: read EDP8_PARTICIPANT, call whoami() to learn the role (fallback
EDP8_ROLE, default owner), then register only that role's ToolDefs from
bundles.py. Each tool wraps its pydantic args model into a signature the MCP
SDK can introspect, calls the ToolDef handler, and returns the envelope as
JSON text.
"""

from __future__ import annotations

import inspect
import json
import os
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .bundles import ToolDef, set_client, tools_for_role
from .client import BoardClient


def _wrap(tool: ToolDef):
    """Build a function whose signature mirrors tool.args_model's fields, so the
    MCP SDK generates a flat input schema instead of a single nested `args` object."""

    def call(**kwargs: Any) -> str:
        args = tool.args_model(**kwargs)
        result = tool.handler(args)
        return json.dumps(result, default=str)

    params = []
    for fname, field in tool.args_model.model_fields.items():
        default = inspect.Parameter.empty if field.is_required() else field.default
        annotation = Annotated[field.annotation, Field(description=field.description or "")]
        params.append(inspect.Parameter(fname, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                        default=default, annotation=annotation))
    call.__signature__ = inspect.Signature(params)
    call.__name__ = tool.name
    return call


def _resolve_role(client: BoardClient) -> str:
    role = os.environ.get("EDP8_ROLE") or os.environ.get("EDP_ROLE")
    try:
        resp = client.whoami()
        if resp.get("ok"):
            role = resp["value"]["participant"]["role"]
    except Exception:
        pass
    return role or "owner"


def build_server() -> MCPServer:
    participant = os.environ.get("EDP8_PARTICIPANT") or os.environ.get("EDP_HANDLE")
    board_url = os.environ.get("EDP8_BOARD_URL", "http://127.0.0.1:9400")
    admin_token = os.environ.get("EDP8_ADMIN_TOKEN")
    client = BoardClient(base_url=board_url, participant=participant, admin_token=admin_token)
    set_client(client)

    role = _resolve_role(client)
    server = MCPServer("edp8", version="0.8.0",
                       instructions=f"edp8 board tools for participant {participant!r}, role {role!r}")
    for tool in tools_for_role(role):
        server.add_tool(_wrap(tool), name=tool.name, description=tool.description)
    return server


def run() -> None:
    server = build_server()
    server.run("stdio")


if __name__ == "__main__":
    run()
