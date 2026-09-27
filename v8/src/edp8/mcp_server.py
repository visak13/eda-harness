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
import sys
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any
from pathlib import Path
from dataclasses import replace

from edp_contracts.roles import non_agent_refusal

from .http_upload import HttpUploadPolicy

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import CallToolResult, ImageContent, ListToolsResult, TextContent
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from pydantic import ConfigDict, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import __version__, run_state, settings
from .bundles import (ALL_TOOLS, ToolDef, bind_request, invoke, is_human_role, set_client, standard_roles,
                      tools_for_role)
from .workflow import KERNEL_TOOLS
from .client import BoardClient
from .schemas import Role

CUSTOM_PATH = "custom"  # S13/S14: the /mcp/<role> endpoint that serves every workflow's custom roles
STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def server_version() -> str:
    """Git sha of the code this process runs — whoami reports it so a seat can tell stale code.
    Read from .git directly (tool modules never spawn processes): run_state.git_rev."""
    return run_state.git_rev()


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
    return (settings.get("EDP8_PARTICIPANT") or None,
            settings.get("EDP_SPAWN_SESSION_ID") or None,
            settings.get("EDP8_TOKEN") or None)


# t-3e246b5e32 (a): the tools a caller gets are bound to its BOARD role (whoami), never to the
# /mcp/<role> path it names — an expert (or any caller the board refuses) gets zero tools on every
# path, and a seat naming another role's path gets only the tools both roles share.
_ROLE_TTL_S = 60.0
_role_cache: dict[tuple[str, str | None, str | None], tuple[float, str]] = {}
# S13/S14: every seat is served the bundle its epic's pinned workflow declares for its role (whoami `bundle`;
# a custom role's is clipped by its permissions; the kernel tools always), cached with the role, and the
# workflow ref it came from so a refusal names it
_bundle_cache: dict[tuple[str, str | None, str | None], list[str] | None] = {}
_workflow_cache: dict[tuple[str, str | None, str | None], str | None] = {}


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
        try:
            _bundle_cache[key] = list(resp["value"].get("bundle") or []) or None
        except (KeyError, TypeError, AttributeError):
            _bundle_cache[key] = None
        _workflow_cache[key] = (resp.get("value") or {}).get("workflow")
    return role


def _caller_bundle(board_url: str, participant: str | None, token: str | None) -> list[str] | None:
    """The declared bundle whoami returned with the cached role (None when unknown)."""
    return _bundle_cache.get((board_url, participant, token))


def allowed_tool_names(path_role: str, caller_role: str | None, caller_bundle: list[str] | None = None) -> set[str]:
    """Tools a caller with board role `caller_role` may use on /mcp/<path_role>; nothing at all for an expert
    or a caller the board refused. The caller's own tools are the bundle its epic's pinned workflow declares
    for its role (`caller_bundle`, from whoami; S13 owner m-30023429f7 "any workflow"), Standard's when whoami
    did not say (a seat with no epic resolves to Standard on the board). A seat's kernel tools always stay
    in; a custom role also keeps the identity tools. On another role's /mcp/<role> path the caller gets only
    what that path's Standard bundle shares (t-3e246b5e32)."""
    if not caller_role or caller_role == Role.expert.value:
        return set()
    std = {t.name for t in tools_for_role(caller_role)}
    if caller_bundle is None:
        mine = std
    elif caller_role in standard_roles():
        mine = set(caller_bundle)
    else:
        mine = std | set(caller_bundle)
    if not is_human_role(caller_role):
        mine |= set(KERNEL_TOOLS)
    mine &= set(ALL_TOOLS)
    if path_role in (CUSTOM_PATH, caller_role):
        return mine
    return mine & {t.name for t in tools_for_role(path_role)}


def _refused(tool_name: str, path_role: str, caller_role: str | None, workflow: str | None = None) -> str:
    """`unauthorized` when the board refused the caller outright, `forbidden` when its role lacks the tool
    (naming the workflow whose bundle it is, S13)."""
    who = f"role {caller_role!r}" if caller_role else "a caller the board refuses"
    under = f" under workflow {workflow}" if caller_role and workflow else ""
    return json.dumps({"ok": False, "error": {
        "code": "forbidden" if caller_role else "unauthorized",
        "message": f"tool {tool_name!r} is not available to {who}{under} on /mcp/{path_role}"},
        "hint": "tools follow your board role in your epic's workflow (whoami bundles_available), "
                "not the /mcp/<role> path"})


def _agent_shell_as_human(board_url: str, admin_token: str | None, participant: str | None, session: str | None,
                          token: str | None, tool_name: str) -> str | None:
    """Owner m-da9a2ae62f ("no way anyone can launch the owner role"): a call from an agent shell (it carries
    a pool session id) whose board identity is a person's role (owner, expert, human) is refused, so no model
    ever acts as the owner. A person's own client (no session) is unaffected; the board still authorises it."""
    if not session:
        return None
    why = non_agent_refusal(None, participant)
    if why is None:
        role = _caller_role(board_url, admin_token, participant, token)
        why = non_agent_refusal(role) if role else None
    if why is None:
        return None
    return json.dumps({"ok": False, "error": {
        "code": "forbidden", "message": f"tool {tool_name!r} refused: an agent shell never acts as a person ({why})"},
        "hint": "a seat runs as its own agent role (EDP_ROLE / EDP_HANDLE from its spawn); people act in the web UI"})


def _wrap(tool: ToolDef, *, board_url: str, admin_token: str | None, workspace_root: Path | None = None,
          http_upload_policy: HttpUploadPolicy | None = None, path_role: str | None = None):
    """Build a function whose signature mirrors tool.args_model's fields (flat input schema)
    plus a Context parameter the SDK injects; the request identity binds the BoardClient."""

    def call(ctx: Context, **kwargs: Any) -> str:
        participant, session, token = _identity_from(ctx)
        refused = _agent_shell_as_human(board_url, admin_token, participant, session, token, tool.name)
        if refused:
            return refused
        if path_role is not None:
            caller_role = _caller_role(board_url, admin_token, participant, token)
            if tool.name not in allowed_tool_names(path_role, caller_role,
                                                   _caller_bundle(board_url, participant, token)):
                return _refused(tool.name, path_role, caller_role,
                                _workflow_cache.get((board_url, participant, token)))
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
        return _as_content(result)

    params = [inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context)]
    for fname, field in tool.args_model.model_fields.items():
        # default_factory fields (list args such as record_decision replaces/domains) have no
        # field.default; call the factory so the tool schema marks them optional (pain p-13393743)
        default = inspect.Parameter.empty if field.is_required() else field.get_default(call_default_factory=True)
        annotation = Annotated[field.annotation, Field(description=field.description or "")]
        params.append(inspect.Parameter(fname, inspect.Parameter.KEYWORD_ONLY,
                                        default=default, annotation=annotation))
    call.__signature__ = inspect.Signature(params)
    call.__name__ = tool.name
    call.__annotations__ = {"ctx": Context, **{p.name: p.annotation for p in params[1:]}, "return": str}
    return call


def _as_content(result: dict[str, Any]) -> Any:
    """The JSON envelope as text; an artifact_read image (value.content.base64, S23) also goes out as an MCP
    image block, so the model sees the pixels. The base64 never sits in the text or structured copy."""
    content = (result.get("value") or {}).get("content") if isinstance(result.get("value"), dict) else None
    data = content.pop("base64", None) if isinstance(content, dict) else None
    text = json.dumps(result, default=str)
    if not data:
        return text
    return CallToolResult(content=[TextContent(type="text", text=text),
                                   ImageContent(type="image", data=data, mime_type=content.get("mime") or "image/png")],
                          structured_content={"result": text})


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
        allowed = allowed_tool_names(self._path_role, caller_role,
                                     _caller_bundle(self._board_url, participant, token))
        return ListToolsResult(tools=[t for t in await self.list_tools() if t.name in allowed])


def build_role_server(role: str, *, board_url: str, admin_token: str | None,
                      workspace_root: Path | None = None,
                      http_upload_policy: HttpUploadPolicy | None = None) -> MCPServer:
    server = _RoleServer("edp8", version=__version__,
                         instructions=f"edp8 board tools for role {role!r} (server {VERSION})",
                         path_role=role, board_url=board_url, admin_token=admin_token)
    # S13/S14: every endpoint registers every tool; tools/list and each call filter them to the caller's
    # bundle in its epic's pinned workflow (allowed_tool_names), so a workflow can add a tool to a role
    for tool in ALL_TOOLS.values():
        server.add_tool(_wrap(tool, board_url=board_url, admin_token=admin_token, workspace_root=workspace_root,
                              http_upload_policy=http_upload_policy, path_role=role),
                        name=tool.name, description=tool.description)
        # advertise the compact schema (S20); the raw arguments reach invoke(), whose strict args_model
        # rejects an unknown or misspelled arg with the nearest accepted name (S23) — the SDK's own
        # signature model would silently drop it and answer a bad enum with a bare ToolError
        registered = server._tool_manager.get_tool(tool.name)
        registered.parameters = tool.input_schema
        registered.fn_metadata.arg_model = _RawArgs
    return server


class _RawArgs(ArgModelBase):
    """Pass every argument through unvalidated; bundles.invoke validates against the tool's args_model."""
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


def _env() -> tuple[str, str | None]:
    return (settings.get("EDP8_BOARD_URL"), settings.get("EDP8_ADMIN_TOKEN"))


# ------------------------------------------------------------------ HTTP (shared, stateless)

def build_http_app(roles: list[str] | None = None) -> Starlette:
    board_url, admin_token = _env()
    roles = roles or standard_roles()
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

    # home_id + home: the launcher acts only on an mcp server of its own home (t-596660619c)
    from edp_contracts.identity import home_identity
    identity = home_identity()

    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "version": VERSION, "started_at": STARTED_AT,
                             "roles": roles, "transport": "streamable-http/stateless", **identity})

    # S13: a workflow's custom role (not a built-in bundle) is served the kernel bundle on /mcp/<role>;
    # the board still authorises every call by the seat's role
    custom = build_role_server(CUSTOM_PATH, board_url=board_url, admin_token=admin_token,
                               http_upload_policy=upload_policy)
    managers["custom"] = StreamableHTTPSessionManager(app=custom._lowlevel_server, json_response=True,
                                                      stateless=True, security_settings=security)
    routes.append(Route("/mcp/{role}", endpoint=StreamableHTTPASGIApp(managers["custom"])))
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

    host = settings.get("EDP8_MCP_HOST")
    port = settings.get("EDP8_MCP_PORT")
    uvicorn.run(build_http_app(), host=host, port=port, log_level="info")


# ------------------------------------------------------------------ stdio (fallback)

def _resolve_role(client: BoardClient) -> str:
    role = settings.get("EDP8_ROLE")
    try:
        resp = client.whoami()
        if resp.get("ok"):
            role = resp["value"]["participant"]["role"]
    except Exception as e:  # board unreachable at start: fall back to the env role, say so on stderr
        sys.stderr.write(f"edp8-mcp: whoami failed at start ({e}); using role from env\n")
    return role or "owner"


def build_server() -> MCPServer:
    board_url, admin_token = _env()
    participant = settings.get("EDP8_PARTICIPANT")
    client = BoardClient(base_url=board_url, participant=participant, admin_token=admin_token)
    set_client(client)
    role = _resolve_role(client)
    # Only the seat-local stdio process accepts an explicit root. HTTP never supplies one.
    root = settings.get("EDP8_UPLOAD_ROOT")
    return build_role_server(role, board_url=board_url, admin_token=admin_token,
                             workspace_root=Path(root) if root else None)


def run() -> None:
    if "--stdio" in sys.argv[1:] or settings.get("EDP8_MCP_TRANSPORT").lower() == "stdio":
        build_server().run("stdio")
    else:
        run_http()


if __name__ == "__main__":
    run()
