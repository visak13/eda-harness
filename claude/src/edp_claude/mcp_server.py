"""edp-claude MCP stdio server (resolves the deferred #2 transport TODO).

Pure transport: exposes the existing 15 `Tool`s (already unit-tested via
WALK-1) over MCP stdio. Each MCP tool is a thin shim — call `tool.run`,
return the `ToolOk`/`ToolError` envelope as a dict. No tool logic here.

A `claude` launched with cwd = the claude repo auto-registers this via
`.mcp.json`. Run standalone: `python -m edp_claude.mcp_server`
(uses `EDP_AGENT_HOME`, default = repo root containing this package).
"""

import inspect
import os
from pathlib import Path

from .server import make_context, make_http_context
from .tools import build_registry
from .store.attribution import is_spawned
from .tools.roles import toolset_for_role


def _agent_home() -> Path:
    env = os.environ.get("EDP_AGENT_HOME")
    if env:
        return Path(env)
    # default: the repo root (…/eda-base/claude) — two parents up from
    # src/edp_claude/mcp_server.py
    return Path(__file__).resolve().parents[2]


def _build_context(root: Path):
    """Backend select. Default = http (real edp-broker + edp-pool, so
    cross-shell signalling works in a live `/neuron` spine). Force the
    stub backend with EDP_MCP_BACKEND=stub (offline / tests).

    Constructing the httpx client + Http* clients here is network-free
    (lazy transport) — only an actual tool call touches the network, at
    which point a down service surfaces as a verbatim ToolError.
    """
    if os.environ.get("EDP_MCP_BACKEND", "http") == "stub":
        return make_context(root)
    import httpx

    from .clients import HttpBroker, HttpEmbed, HttpPool

    client = httpx.AsyncClient(timeout=30.0)
    broker = HttpBroker(
        os.environ.get("EDP_BROKER_URL", "http://127.0.0.1:9300"), client
    )
    pool = HttpPool(
        os.environ.get("EDP_POOL_URL", "http://127.0.0.1:9301"), client
    )
    # Real ollama embeddings for the neuron DB's discovery index. Defaults
    # to the deployed docker-animation-ollama container; neuron_search
    # degrades to token-overlap (search_text) if it's unreachable, so
    # this is safe even when ollama is down.
    embed = HttpEmbed(
        os.environ.get("EDP_OLLAMA_URL", "http://localhost:11435"), client
    )
    return make_http_context(root, broker=broker, pool=pool, embed=embed)


# Context-diet Phase 4: the catalog description is "[roles] purpose-clause".
# The ROLE TAG is derived from ROLE_TOOLSETS at registration (it cannot drift
# from roles.py); the hand-written purpose clauses live in tools/catalog.py.
# The empirical W4/a3 ruling stands — one lean clause per tool, never the
# long docstrings ("verbose tool descriptions demonstrably regress the
# planner tool catalog"); what changed is that EVERY tool now advertises its
# owning role(s) + purpose instead of a generated name+backing placeholder.
from .tools.catalog import TOOL_ONE_LINERS
from .tools.roles import ROLE_TOOLSETS


def _describe(tool) -> str:
    roles = sorted(r for r, ts in ROLE_TOOLSETS.items() if tool.name in ts)
    tag = f"[{','.join(roles)}]" if roles else "[unscoped]"
    clause = TOOL_ONE_LINERS.get(
        tool.name, f"edp-claude tool '{tool.name}' (backing={tool.backing}).")
    return f"{tag} {clause}"


def build_mcp(root: Path | None = None):
    """Build a FastMCP server registering every tool in the registry.

    `mcp` is imported lazily so importing this module (e.g. for the unit
    test that asserts the registry wiring) does not require the SDK.
    """
    from mcp.server.fastmcp import FastMCP

    root = root or _agent_home()
    ctx = _build_context(root)
    tools = build_registry(ctx)

    # DESIGN-v6 W4 (per-role tool registration): scope the registered surface
    # to EDP_ROLE, GOVERNED BY EDP_ROLE_SCOPE (warn|enforce, DEFAULT enforce —
    # DESIGN-v7 P0, user ruling 2026-07-12: the derived floors were audited
    # all through v6, the last known enforce-break (the reviewer-leg
    # role="worker" default, d67/d100) is closed by P4.1, so warn-mode is now
    # the opt-OUT, not the milestone). F37#5 (2026-08-18) — identity fails
    # CLOSED: `toolset_for_role` returns None only for an ABSENT role, and
    # the full registry registers only for a NON-SPAWNED shell (no
    # EDP_HANDLE — the operator console / tests). A SPAWNED shell with a
    # missing role, or ANY shell with an unknown EDP_ROLE value, refuses to
    # build: both are spawn-env bugs that used to silently grant the full
    # surface.
    #
    #   warn (opt-out, EDP_ROLE_SCOPE=warn): ALL tools register — NO
    #     filtering. A call to a tool OUTSIDE the role's scoped set is
    #     recorded as a role_scope_violation worklog event (role + tool name)
    #     and then PROCEEDS. The observe-before-enforce Phase-1 bar, kept as
    #     the diagnostic mode.
    #   enforce (default, v7): the registry is FILTERED to exactly the
    #     role's ROLE_TOOLSETS (an off-set tool is simply absent).
    #
    # Drift between a role toolset name and the LIVE built registry
    # (ALL_TOOL_CLASSES) fails CLOSED in BOTH modes, with NO name special-cased:
    # we refuse to build a mis-scoped server rather than silently drop a tool a
    # role expects, or pass a name that no longer resolves (a hardcoded
    # carve-out would be the exact fail-open o7 forbids).
    role = (os.environ.get("EDP_ROLE") or "").strip() or None
    allowed = toolset_for_role(role)
    if role is not None and allowed is None:
        # F37#5: an UNKNOWN role value (typo, stale spawner) must never
        # silently register the full surface.
        raise RuntimeError(
            f"edp-claude: EDP_ROLE={role!r} is not a known role "
            "(tools/roles.py ROLE_TOOLSETS) — refusing to build a "
            "full-surface server for an unrecognised identity. Fix the "
            "spawn env, or unset EDP_ROLE for an operator console.")
    if role is None and is_spawned():
        raise RuntimeError(
            "edp-claude: this shell carries EDP_HANDLE (pool-spawned) but "
            "no EDP_ROLE — a spawned shell without its role would "
            "otherwise inherit the operator's full tool surface (F37#5). "
            "Fix the spawn env; only a non-spawned operator console may "
            "run role-less.")
    scope_mode = (os.environ.get("EDP_ROLE_SCOPE", "enforce").strip()
                  or "enforce")
    if scope_mode not in ("warn", "enforce"):
        # F37#12: EDP_ROLE_SCOPE is a strict enum. Every unknown value used
        # to fall through to warn behaviour — a typo ('enfroce') silently
        # registered the full surface in observe-only mode.
        raise RuntimeError(
            f"edp-claude: EDP_ROLE_SCOPE={scope_mode!r} is not a known "
            "mode — use 'enforce' (default) or 'warn'. Refusing to guess: "
            "an unknown value must never silently open the surface.")
    off_scope_names: set[str] = set()
    if allowed is not None:
        registered = {t.name for t in tools}
        missing = allowed - registered
        if missing:
            raise RuntimeError(
                "edp-claude role-toolset drift for "
                f"EDP_ROLE={role!r}: tools/roles.py "
                f"names {sorted(missing)} that are not registered tools in "
                "ALL_TOOL_CLASSES. Reconcile roles.py with the built "
                "registry — refusing to build a mis-scoped server rather "
                "than silently drop tools a role expects."
            )
        if scope_mode == "enforce":
            # F1 (owner ruling 2026-08-17): off-role tools are ABSENT — no
            # refusal stubs. The Phase-3c stubs kept every off-scope tool
            # visible in the listing ("(not available to role=…)"), which
            # re-bloated the system prompt with ~60 schemas and tempted
            # shells toward verbs they could never use. A mis-scoped call
            # now surfaces as the harness's own unknown-tool error; the
            # role's card names its surface, and the broker route
            # (ask_above/notify_above) remains the answer to "I need a verb
            # another role owns".
            tools = [t for t in tools if t.name in allowed]
        else:
            # warn: keep the full surface; the off-set tools get a shim that
            # logs a role_scope_violation on call, then proceeds.
            off_scope_names = registered - allowed

    # Lazy import (like the rest of this seam): the worklog-writing helper
    # lives with the tools it also guards. Used only by warn-mode off-set shims.
    from .tools._tools import record_role_scope_violation

    mcp = FastMCP("edp-claude")

    def _make_shim(bound_tool):
        # 2026-05-20 (§5.5 post-HITL sweep B): expose the tool's REAL
        # InputModel schema with FLAT top-level args — no `payload`
        # wrapper. The old shim took a single `payload: dict`, so every
        # tool advertised an opaque `{payload: object}` and the whole
        # contract lived in prose (the v5 disease at the MCP boundary).
        # We synthesise the shim's signature from InputModel.model_fields
        # so FastMCP emits the true per-tool schema: nested models
        # (Plan/Recipe) resolve via their field annotation; a no-field
        # model (pool_close_self) yields an empty schema, correctly
        # documenting "no args". The real body is `**kwargs` (the
        # factory arg still fixes loop late-binding); `__signature__` is
        # introspection-only, used solely for schema generation.
        fields = bound_tool.InputModel.model_fields
        off_scope = bound_tool.name in off_scope_names

        async def shim(**kwargs) -> dict:
            # warn mode: this tool is outside the role's scoped set, so record
            # the off-set CALL (role + tool name) then PROCEED — observe-only,
            # never block (d15). On-set tools and enforce/absent-role builds
            # never reach here (off_scope is False).
            if off_scope:
                record_role_scope_violation(ctx, bound_tool.name)
            res = await bound_tool.run(kwargs)
            return res.model_dump(mode="json")

        params = []
        annotations: dict = {}
        for fname, f in fields.items():
            required = f.is_required()
            default = (
                inspect.Parameter.empty
                if required
                else f.get_default(call_default_factory=True)
            )
            params.append(
                inspect.Parameter(
                    fname,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=default,
                    annotation=f.annotation,
                )
            )
            annotations[fname] = f.annotation
        annotations["return"] = dict
        shim.__signature__ = inspect.Signature(params)
        shim.__annotations__ = annotations
        shim.__name__ = bound_tool.name
        return shim

    for tool in tools:
        mcp.add_tool(
            _make_shim(tool),
            name=tool.name,
            description=_describe(tool),
        )

    # (Phase 3c's enforce-mode refusal stubs were REMOVED here — F1, owner
    # ruling 2026-08-17. Off-role tools are absent from the listing entirely;
    # see the enforce branch above for the rationale.)

    # F15 (2026-08-17) — object schemas as MCP RESOURCES: read ONCE at boot,
    # referenced by symbol thereafter (cards say "your objects:
    # edp://schema/<object>"). This replaces the withdrawn idea of repeating
    # schema in tool descriptions (paid per-request forever); a resource read
    # pays once and sits in stable early context. `edp://schema/index` is
    # the catalog.
    @mcp.resource("edp://schema/{name}")
    def _object_schema(name: str) -> str:
        from .objects import describe_objects
        return describe_objects(None if name == "index" else name)

    return mcp


def run() -> None:
    build_mcp().run()  # stdio transport (FastMCP default)


if __name__ == "__main__":
    run()
