"""edp8 MCP server — ONE shared process for the whole fleet (2026-09-06), stdio kept as a fallback.

HTTP (default): `python -m edp8.mcp_server` serves streamable-http on EDP8_MCP_PORT (9402),
one endpoint per role — `/mcp/<role>` registers exactly that role's ToolDefs, so a seat's
tool list stays role-scoped without in-handler gating. Identity travels per request in
headers set by `.mcp.json` from the shell's env: `X-Participant` (handle) and `X-Session`
(pool session id). The server is STATELESS (no Mcp-Session-Id), so restarting it is
invisible to connected shells — a fix to any tool reaches every seat on the next call,
and the fleet runs 1 server process instead of 2 per shell.

stdio (fallback, `--stdio` or EDP8_MCP_TRANSPORT=stdio): the pre-2026-09-06 shape — one
process per shell, identity from EDP8_PARTICIPANT/EDP_HANDLE at start.

Each tool wraps its pydantic args model into a signature the MCP SDK can introspect, binds
the request's identity into a contextvar-scoped BoardClient, calls the ToolDef handler, and
returns the envelope as JSON text.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import os
import sys
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any
from pathlib import Path

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .bundles import ROLE_BUNDLES, ToolDef, bind_request, invoke, set_client, tools_for_role
from .client import BoardClient

STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def server_version() -> str:
    """Git sha of the code this process runs — whoami reports it so a seat can tell stale code.
    Read from .git directly (tool modules never spawn processes)."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        root = here
        for _ in range(6):
            if os.path.isdir(os.path.join(root, ".git")):
                break
            root = os.path.dirname(root)
        head = open(os.path.join(root, ".git", "HEAD"), encoding="utf-8").read().strip()
        if head.startswith("ref: "):
            ref = os.path.join(root, ".git", *head[5:].split("/"))
            head = open(ref, encoding="utf-8").read().strip()
        return head[:7] or "unknown"
    except OSError:
        return "unknown"


VERSION = server_version()


def _identity_from(ctx: Context | None) -> tuple[str | None, str | None, str | None]:
    """(participant, pool session id, seat token) from request headers (HTTP) or the process env
    (stdio). §24.1(c): the per-request X-Token is carried through so a minted-token seat behind the
    shared proxy authenticates as itself — the proxy's own env EDP8_TOKEN is not that seat's secret."""
    headers = None
    if ctx is not None:
        try:
            headers = ctx.headers
        except Exception:  # noqa: BLE001 — no request context (stdio)
            headers = None
    if headers:
        h = {k.lower(): v for k, v in headers.items()}
        return (h.get("x-participant") or None), (h.get("x-session") or None), (h.get("x-token") or None)
    return (os.environ.get("EDP8_PARTICIPANT") or os.environ.get("EDP_HANDLE") or None,
            os.environ.get("EDP_SPAWN_SESSION_ID") or None,
            os.environ.get("EDP8_TOKEN") or None)


def _wrap(tool: ToolDef, *, board_url: str, admin_token: str | None, workspace_root: Path | None = None):
    """Build a function whose signature mirrors tool.args_model's fields (flat input schema)
    plus a Context parameter the SDK injects; the request identity binds the BoardClient."""

    def call(ctx: Context, **kwargs: Any) -> str:
        participant, session, token = _identity_from(ctx)
        client = BoardClient(base_url=board_url, participant=participant, admin_token=admin_token,
                             token=token, workspace_root=workspace_root)
        with bind_request(client, session_id=session, server_version=VERSION):
            # invoke() validates args → envelope on a bad enum (naming field + allowed values),
            # carries the deprecation hint, and counts consecutive failures per seat (§19).
            result = invoke(tool, kwargs, seat=participant)
        return json.dumps(result, default=str)

    params = [inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context)]
    for fname, field in tool.args_model.model_fields.items():
        default = inspect.Parameter.empty if field.is_required() else field.default
        annotation = Annotated[field.annotation, Field(description=field.description or "")]
        params.append(inspect.Parameter(fname, inspect.Parameter.KEYWORD_ONLY,
                                        default=default, annotation=annotation))
    call.__signature__ = inspect.Signature(params)
    call.__name__ = tool.name
    call.__annotations__ = {"ctx": Context, **{p.name: p.annotation for p in params[1:]}, "return": str}
    return call


def build_role_server(role: str, *, board_url: str, admin_token: str | None,
                      workspace_root: Path | None = None) -> MCPServer:
    server = MCPServer("edp8", version="0.8.0",
                       instructions=f"edp8 board tools for role {role!r} (server {VERSION})")
    for tool in tools_for_role(role):
        server.add_tool(_wrap(tool, board_url=board_url, admin_token=admin_token, workspace_root=workspace_root),
                        name=tool.name, description=tool.description)
    return server


def _env() -> tuple[str, str | None]:
    return (os.environ.get("EDP8_BOARD_URL", "http://127.0.0.1:9400"), os.environ.get("EDP8_ADMIN_TOKEN"))


# ------------------------------------------------------------------ HTTP (shared, stateless)

def build_http_app(roles: list[str] | None = None) -> Starlette:
    board_url, admin_token = _env()
    roles = roles or sorted(ROLE_BUNDLES)
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
    )
    managers: dict[str, StreamableHTTPSessionManager] = {}
    routes: list[Route] = []
    for role in roles:
        srv = build_role_server(role, board_url=board_url, admin_token=admin_token)
        mgr = StreamableHTTPSessionManager(app=srv._lowlevel_server, json_response=True, stateless=True,
                                           security_settings=security)
        managers[role] = mgr
        routes.append(Route(f"/mcp/{role}", endpoint=StreamableHTTPASGIApp(mgr)))

    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "version": VERSION, "started_at": STARTED_AT,
                             "roles": roles, "transport": "streamable-http/stateless"})

    routes.append(Route("/healthz", endpoint=healthz))

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        async with contextlib.AsyncExitStack() as stack:
            for mgr in managers.values():
                await stack.enter_async_context(mgr.run())
            yield

    return Starlette(routes=routes, lifespan=lifespan)


def run_http() -> None:
    import uvicorn

    host = os.environ.get("EDP8_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("EDP8_MCP_PORT", "9402"))
    uvicorn.run(build_http_app(), host=host, port=port, log_level="info")


# ------------------------------------------------------------------ stdio (fallback)

def _resolve_role(client: BoardClient) -> str:
    role = os.environ.get("EDP8_ROLE") or os.environ.get("EDP_ROLE")
    try:
        resp = client.whoami()
        if resp.get("ok"):
            role = resp["value"]["participant"]["role"]
    except Exception as e:  # board unreachable at start: fall back to the env role, say so on stderr
        sys.stderr.write(f"edp8-mcp: whoami failed at start ({e}); using role from env\n")
    return role or "owner"


def build_server() -> MCPServer:
    board_url, admin_token = _env()
    participant = os.environ.get("EDP8_PARTICIPANT") or os.environ.get("EDP_HANDLE")
    client = BoardClient(base_url=board_url, participant=participant, admin_token=admin_token)
    set_client(client)
    role = _resolve_role(client)
    # Only the seat-local stdio process accepts an explicit root. HTTP never supplies one.
    root = os.environ.get("EDP8_UPLOAD_ROOT")
    return build_role_server(role, board_url=board_url, admin_token=admin_token,
                             workspace_root=Path(root) if root else None)


def run() -> None:
    if "--stdio" in sys.argv[1:] or os.environ.get("EDP8_MCP_TRANSPORT", "").lower() == "stdio":
        build_server().run("stdio")
    else:
        run_http()


if __name__ == "__main__":
    run()
