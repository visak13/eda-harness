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
from dataclasses import replace

from .http_upload import HttpUploadPolicy

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ListToolsResult
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .bundles import ROLE_BUNDLES, ToolDef, bind_request, invoke, set_client, tools_for_role
from .client import BoardClient
from .schemas import Role

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


# t-3e246b5e32 (a): the tools a caller gets are bound to its BOARD role (whoami), never to the
# /mcp/<role> path it names — an expert (or any caller the board refuses) gets zero tools on every
# path, and a seat naming another role's path gets only the tools both roles share.
_ROLE_TTL_S = 60.0
_role_cache: dict[tuple[str, str | None, str | None], tuple[float, str]] = {}


def _caller_role(board_url: str, admin_token: str | None, participant: str | None, token: str | None) -> str | None:
    """The caller's role per the board's whoami, or None when the board refuses the caller (an expert's
    403, a missing/wrong token's 401, an unknown handle). Only an accepted role is cached (60 s), so a
    freshly minted token is never locked out. BoardUnreachable propagates: a board outage is an error
    to the client, never a silently empty tool list it would cache for the session."""
    key = (board_url, participant, token)
    now = time.monotonic()
    hit = _role_cache.get(key)
    if hit and now - hit[0] < _ROLE_TTL_S:
        return hit[1]
    resp = BoardClient(base_url=board_url, participant=participant, admin_token=admin_token, token=token).whoami()
    try:
        role = resp["value"]["participant"]["role"] if resp.get("ok") else None
    except (KeyError, TypeError):
        role = None
    if role:
        _role_cache[key] = (now, role)
    return role


def allowed_tool_names(path_role: str, caller_role: str | None) -> set[str]:
    """Tools a caller with board role `caller_role` may use on /mcp/<path_role>: the intersection of
    both roles' bundles; nothing at all for an expert or a caller the board refused."""
    if not caller_role or caller_role == Role.expert.value:
        return set()
    return {t.name for t in tools_for_role(path_role)} & {t.name for t in tools_for_role(caller_role)}


def _refused(tool_name: str, path_role: str, caller_role: str | None) -> str:
    """`unauthorized` when the board refused the caller outright, `forbidden` when its role lacks the tool."""
    who = f"role {caller_role!r}" if caller_role else "a caller the board refuses"
    return json.dumps({"ok": False, "error": {
        "code": "forbidden" if caller_role else "unauthorized",
        "message": f"tool {tool_name!r} is not available to {who} on /mcp/{path_role}"},
        "hint": "tools follow your board role (whoami), not the /mcp/<role> path"})


def _wrap(tool: ToolDef, *, board_url: str, admin_token: str | None, workspace_root: Path | None = None,
          http_upload_policy: HttpUploadPolicy | None = None, path_role: str | None = None):
    """Build a function whose signature mirrors tool.args_model's fields (flat input schema)
    plus a Context parameter the SDK injects; the request identity binds the BoardClient."""

    def call(ctx: Context, **kwargs: Any) -> str:
        participant, session, token = _identity_from(ctx)
        if path_role is not None:
            caller_role = _caller_role(board_url, admin_token, participant, token)
            if tool.name not in allowed_tool_names(path_role, caller_role):
                return _refused(tool.name, path_role, caller_role)
        client = BoardClient(base_url=board_url, participant=participant, admin_token=admin_token,
                             token=token, workspace_root=workspace_root)
        request_tool = tool
        if tool.name == 'artifact_upload' and http_upload_policy is not None:
            # Transport peer is server request metadata, never a forwarded/header claim.
            try:
                request = ctx.request_context.request
                peer = request.client.host
                if any(h in request.headers for h in ('forwarded', 'x-forwarded-for', 'x-real-ip')):
                    peer = None  # proxied topology is not the authorized single-host route
            except (AttributeError, ValueError):
                peer = None
            request_tool = replace(tool, handler=lambda a: http_upload_policy.upload(client, a.path, a.note, peer))
        with bind_request(client, session_id=session, server_version=VERSION):
            # invoke() validates args → envelope on a bad enum (naming field + allowed values),
            # carries the deprecation hint, and counts consecutive failures per seat (§19).
            result = invoke(request_tool, kwargs, seat=participant)
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


class _RoleServer(MCPServer):
    """One /mcp/<role> endpoint whose tools/list is filtered per request by the caller's board role."""

    def __init__(self, *args: Any, path_role: str, board_url: str, admin_token: str | None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._path_role, self._board_url, self._admin_token = path_role, board_url, admin_token

    async def _handle_list_tools(self, ctx, params) -> ListToolsResult:
        context = Context(request_context=ctx, mcp_server=self, input_params=params, subscriptions=self._subscriptions)
        participant, _, token = _identity_from(context)
        caller_role = await anyio.to_thread.run_sync(
            _caller_role, self._board_url, self._admin_token, participant, token)
        allowed = allowed_tool_names(self._path_role, caller_role)
        return ListToolsResult(tools=[t for t in await self.list_tools() if t.name in allowed])


def build_role_server(role: str, *, board_url: str, admin_token: str | None,
                      workspace_root: Path | None = None,
                      http_upload_policy: HttpUploadPolicy | None = None) -> MCPServer:
    server = _RoleServer("edp8", version="0.8.0",
                         instructions=f"edp8 board tools for role {role!r} (server {VERSION})",
                         path_role=role, board_url=board_url, admin_token=admin_token)
    for tool in tools_for_role(role):
        server.add_tool(_wrap(tool, board_url=board_url, admin_token=admin_token, workspace_root=workspace_root,
                              http_upload_policy=http_upload_policy, path_role=role),
                        name=tool.name, description=tool.description)
        # advertise the compact schema (S20); FastMCP still validates against the wrapper signature
        server._tool_manager.get_tool(tool.name).parameters = tool.input_schema
    return server


def _env() -> tuple[str, str | None]:
    return (os.environ.get("EDP8_BOARD_URL", "http://127.0.0.1:9400"), os.environ.get("EDP8_ADMIN_TOKEN"))


# ------------------------------------------------------------------ HTTP (shared, stateless)

def build_http_app(roles: list[str] | None = None) -> Starlette:
    board_url, admin_token = _env()
    roles = roles or sorted(ROLE_BUNDLES)
    upload_policy = HttpUploadPolicy.from_environment(board_url)
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
    )
    managers: dict[str, StreamableHTTPSessionManager] = {}
    routes: list[Route] = []
    for role in roles:
        srv = build_role_server(role, board_url=board_url, admin_token=admin_token,
                                http_upload_policy=upload_policy)
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
