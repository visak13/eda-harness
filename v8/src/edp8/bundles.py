"""edp8 tool registry — the ReactiveAgents-style bundles (FRAMEWORK-V8-DRAFT-v2 §8).

A tool is `ToolDef(name, description, args_model, handler, bundle)`. Handlers take a
validated pydantic args instance and return the board's JSON envelope unchanged
(`{ok, value|error, hint}`). Handlers reach the board through a module-level
`BoardClient` set once by the process that hosts these tools (the MCP server, or a
test) via `set_client()` — this keeps `handler: Callable[[BaseModel], dict]` exactly
as specified, with no client threaded through call sites.

`ROLE_BUNDLES` is the static, per-role allow list: `mcp_server.py` registers only the
named tools for the running participant's role.
"""

from __future__ import annotations

import contextlib
import difflib
import copy
import functools
import contextvars
import enum as _enum
import json
import sys
import threading
import typing
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from edp_contracts.roles import non_agent_refusal
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from . import seat_choice, settings
from .client import BoardClient
from .doc_tools import DocEdit
from . import tool_idem, tool_paging
from .tool_contracts import LOCAL_OBJECTS, link_clause, tool_objects, tools_by_object
from .schemas import (
    ParticipantType,
    ENUMS,
    ArtifactForm,
    Check,
    CheckedBy,
    ClaimBasis,
    DocType,
    Gate,
    MessageKind,
    Relation,
    SeatRelation,
    SeatRole,
    SeatTicketKind,
    SpawnRole,
    Role,
    StatusValue,
    SessionState,
    SeatEffort,
    PainAction,
    PainSeverity,
    TeammateAction,
    WorkflowAction,
    SpawnMode,
    TicketKind,
    TicketStatus,
    Verdict,
    WorkType,
)

# ----------------------------------------------------------------------------- client wiring

_client: BoardClient | None = None
# The shared HTTP server binds a per-REQUEST client (identity from headers) in a contextvar;
# stdio and tests keep the module global. get_client() prefers the request-scoped one.
_req_client: contextvars.ContextVar[BoardClient | None] = contextvars.ContextVar("edp8_req_client", default=None)
_req_session: contextvars.ContextVar[str | None] = contextvars.ContextVar("edp8_req_session", default=None)
_server_version: str = "stdio"


def set_client(client: BoardClient) -> None:
    global _client
    _client = client


def get_client() -> BoardClient:
    c = _req_client.get()
    if c is not None:
        return c
    if _client is None:
        raise RuntimeError("edp8.bundles: no BoardClient set — call set_client() before invoking a tool handler")
    return _client


@contextlib.contextmanager
def bind_request(client: BoardClient, *, session_id: str | None = None,
                 server_version: str | None = None) -> Iterator[None]:
    """Scope one tool call to a request identity (the shared server calls this per request)."""
    global _server_version
    if server_version:
        _server_version = server_version
    t1 = _req_client.set(client)
    t2 = _req_session.set(session_id)
    try:
        yield
    finally:
        _req_client.reset(t1)
        _req_session.reset(t2)


def my_session_id() -> str | None:
    """The caller's pool session id: the request header on the shared server, else the env."""
    return _req_session.get() or settings.get("EDP_SPAWN_SESSION_ID") or None


def unavailable(message: str, hint: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": "unavailable", "message": message}, "hint": hint}


# ----------------------------------------------------------------------------- tool def


class Args(BaseModel):
    """Every tool's argument model (S23 standard 4): an unknown arg is an ERROR naming the nearest
    accepted field, never a silent drop (T1 audit: `limt` was accepted and ignored)."""
    model_config = ConfigDict(extra="forbid")


class CreateArgs(Args):
    """S23 standard 2: a create a seat may retry safely (tool_idem): the same idempotency_key + args replays the
    first result for 24 h, kept by the board. No field description (S20 surface budget): guides/agent-tools.md
    says it once for every create tool, and a replay's hint says what happened."""
    idempotency_key: str | None = None


class PageArgs(Args):
    """S23 standard 3/6: a list tool pages (tool_paging). No field descriptions: the Returns clause says it."""
    limit: int | None = None  # clamped to 1..100 by tool_paging
    cursor: str | None = None
    verbose: bool = False


# ----------------------------------------------------------------------------- description composer
#
# A tool's MCP description is COMPOSED, never hand-typed as one blob (design §19 rule 2):
# what it does · when to call it · the enum args it takes with allowed values inline ·
# what it returns. The enum clause is derived from the args_model, so a tool's advertised
# allowed values can never drift from its pydantic schema.


def _enum_class(annotation: Any) -> type[_enum.Enum] | None:
    """The StrEnum inside an annotation (unwrapping Optional/Union), or None."""
    if isinstance(annotation, type) and issubclass(annotation, _enum.Enum):
        return annotation
    for a in typing.get_args(annotation):
        got = _enum_class(a)
        if got is not None:
            return got
    return None


def enum_fields(args_model: type[BaseModel]) -> dict[str, list[str]]:
    """{field name -> allowed values} for every enum-typed argument of a tool."""
    out: dict[str, list[str]] = {}
    for fname, field in args_model.model_fields.items():
        ec = _enum_class(field.annotation)
        if ec is not None:
            out[fname] = [m.value for m in ec]
        elif lit := _literal_values(field.annotation):
            out[fname] = lit  # S23: a Literal is an enum arg too (doc status active|proposed)
    return out


def _literal_values(annotation: Any) -> list[str]:
    if typing.get_origin(annotation) is typing.Literal:
        vals = list(typing.get_args(annotation))
        return vals if all(isinstance(v, str) for v in vals) else []
    for a in typing.get_args(annotation):
        if got := _literal_values(a):
            return got
    return []


def _type_name(annotation: Any) -> str:
    origin = typing.get_origin(annotation)
    if origin is None:
        return getattr(annotation, "__name__", str(annotation))
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    return "|".join(_type_name(a) for a in args) or str(annotation)


def _enum_clause(args_model: type[BaseModel]) -> str:
    ef = enum_fields(args_model)
    if not ef:
        return ""
    # names only: the advertised schema carries every value (architect ruling m-fbd6ae40d3 — no duplicate)
    return f"Enums: {', '.join(ef)} (describe('enums')). "


def compose_description(what: str, when: str, returns: str, args_model: type[BaseModel], name: str = "") -> str:
    """what · when · objects/skills (tool_contracts metadata) · enums (from the schema) · returns."""
    what = what.strip().rstrip(".") + "."
    when = when.strip().rstrip(".") + "."
    if when[:5].lower() == "when ":  # "When: when …" says it twice
        when = when[5:]
    returns = returns.strip().rstrip(".") + "."
    return f"{what} When: {when} {link_clause(name)}{_enum_clause(args_model)}Returns {returns}"


@dataclass
class ToolDef:
    name: str
    what: str        # what the tool does
    when: str        # when to call it
    returns: str     # what it returns (value shape + the hint contract, in one line)
    args_model: type[BaseModel]
    handler: Callable[[BaseModel], dict[str, Any]]
    bundle: str

    @property
    def description(self) -> str:
        """The composed MCP description: what · when · enum args (from schema) · returns."""
        return compose_description(self.what, self.when, self.returns, self.args_model, self.name)

    @property
    def input_schema(self) -> dict[str, Any]:
        """The ADVERTISED argument schema (mcp_server sends it as the tool's parameters): the
        pydantic schema minus bytes a caller never needs. Validation is unchanged — invoke()
        still validates against args_model (S20 token-cost rework, s-b123a91d3f)."""
        return copy.deepcopy(compact_schema(self.args_model))

    def schema_inline(self) -> str:
        """The full argument schema on one line — inlined into the hint after the third
        consecutive failure of this tool by one seat (design §19 rule 6)."""
        rows = []
        ef = enum_fields(self.args_model)
        for fname, field in self.args_model.model_fields.items():
            req = "required" if field.is_required() else "optional"
            typ = f"one of {'|'.join(ef[fname])}" if fname in ef else _type_name(field.annotation)
            rows.append(f"{fname} ({req}: {typ})")
        return f"{self.name}({', '.join(rows)})"


@functools.cache
def compact_schema(args_model: type[BaseModel]) -> dict[str, Any]:
    """args_model's JSON schema with every `title`, empty default (null, "", [], false) and
    `additionalProperties` dropped, `anyOf [X, null]` collapsed to X, and `$defs` refs inlined (the def's own docstring
    description dropped; the field's description stays). Every enum, type,
    required list, other default and field description survives."""
    schema = args_model.model_json_schema()
    defs = schema.get("$defs", {})

    def walk(node: Any, depth: int = 0) -> Any:
        if isinstance(node, list):
            return [walk(x, depth) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node and depth < 8:
            target = {k: v for k, v in defs[node["$ref"].rsplit("/", 1)[-1]].items() if k != "description"}
            return walk({**target, **{k: v for k, v in node.items() if k != "$ref"}}, depth + 1)
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in ("title", "$defs", "additionalProperties") or (k == "default" and (v in (None, "", [])
                                                                                        or v is False)):
                continue
            out[k] = {p: walk(s, depth) for p, s in v.items()} if k == "properties" else walk(v, depth)
        alts = out.get("anyOf")
        if isinstance(alts, list) and len(alts) == 2 and {"type": "null"} in alts:
            other = next(a for a in alts if a != {"type": "null"})
            out.pop("anyOf")
            out = {**other, **out}
        if out.get("type") == "string" and isinstance(out.get("enum"), list):
            out.pop("type")  # S23: a string enum states its type by its values
        return out

    return walk(schema)


# ----------------------------------------------------------------------------- invoke (the dispatcher)
#
# Every tool call the MCP server serves goes through invoke(): it validates the args into
# the pydantic model — turning a bad enum into an envelope that NAMES the field and its
# allowed values (§19 rule 3/5) — carries the ticket_update `id`→`ticket_id` deprecation
# hint (§19 rule 3), counts consecutive failures per (seat, tool) and inlines the full
# schema on the third (§19 rule 6), then calls the handler. Tests may call a handler
# directly; the MCP path always goes through here.

_TRIPWIRE = 3
_FAIL_COUNTS: dict[tuple[str, str], int] = {}
_FAIL_LOCK = threading.Lock()
# tools whose primary id argument was renamed to <new>; the old `id` is accepted one release
_RENAMED_ID: dict[str, str] = {"ticket_update": "ticket_id", "ticket_read": "ticket_id"}


def _bump_failure(seat: str, name: str) -> int:
    with _FAIL_LOCK:
        key = (seat, name)
        _FAIL_COUNTS[key] = _FAIL_COUNTS.get(key, 0) + 1
        return _FAIL_COUNTS[key]


def _reset_failure(seat: str, name: str) -> None:
    with _FAIL_LOCK:
        _FAIL_COUNTS.pop((seat, name), None)


def accepted_args(args_model: type[BaseModel]) -> list[str]:
    """Every name a caller may pass: field names plus their validation aliases."""
    out: list[str] = []
    for fname, field in args_model.model_fields.items():
        out.append(fname)
        alias = field.validation_alias
        for choice in getattr(alias, "choices", None) or ([alias] if isinstance(alias, str) else []):
            if isinstance(choice, str) and choice not in out:
                out.append(choice)
    return out


def _validation_envelope(tool: ToolDef, exc: ValidationError) -> dict[str, Any]:
    """One schema error that names the fix: the field, its enum values, the nearest accepted arg for an
    unknown or misspelled one, and the accepted/required args (S23 standards 3-4)."""
    errs = exc.errors()
    # an unknown arg usually explains a 'missing' one (checkable vs check): report it first
    err = next((e for e in errs if e.get("type") == "extra_forbidden"), errs[0])
    field = ".".join(str(x) for x in err.get("loc", ())) or "?"
    accepted = accepted_args(tool.args_model)
    required = [n for n, f in tool.args_model.model_fields.items() if f.is_required()]
    allowed = enum_fields(tool.args_model).get(field)
    error: dict[str, Any] = {"code": "schema", "field": field}
    if err.get("type") == "extra_forbidden":
        near = difflib.get_close_matches(field, accepted, n=1, cutoff=0.5)
        error["message"] = f"{tool.name}: unknown arg {field!r}" + (f" — did you mean {near[0]!r}?" if near else "")
        if near:
            error["nearest"] = near[0]
    else:
        error["message"] = f"{tool.name}: invalid {field!r} — {err.get('msg')}"
    missing = [".".join(str(x) for x in e.get("loc", ())) for e in errs if e.get("type") == "missing"]
    if missing:
        error["missing"] = missing
    if allowed:
        error["allowed"] = allowed
    error["accepted"] = accepted
    hint = (f"pass a valid {field}" + (f" — one of: {'|'.join(allowed)}" if allowed else "")
            + (f"; required: {', '.join(required)}" if required else "")
            + "; describe('enums') lists enum values")
    return {"ok": False, "error": error, "hint": hint}


def _deprecation_note(tool: ToolDef, kwargs: dict[str, Any]) -> str | None:
    new = _RENAMED_ID.get(tool.name)
    if new and "id" in kwargs and new not in kwargs:
        return (f" | note: {tool.name} arg 'id' is deprecated — use '{new}' "
                "(the old name is accepted this release only)")
    return None


def _apply_tripwire(tool: ToolDef, seat: str, env: dict[str, Any]) -> dict[str, Any]:
    n = _bump_failure(seat, tool.name)
    if n >= _TRIPWIRE:
        env = dict(env)
        env["hint"] = ((env.get("hint") or "")
                       + f" | {n} consecutive {tool.name} failures by this seat — "
                       f"full schema: {tool.schema_inline()}").strip()
    return env


def invoke(tool: ToolDef, kwargs: dict[str, Any] | None, *, seat: str | None = None) -> dict[str, Any]:
    """Validate → dispatch → count. The one entry the MCP server uses for every call."""
    seat = seat or "?"
    kwargs = kwargs or {}
    try:
        args = tool.args_model(**kwargs)
    except ValidationError as e:
        return _apply_tripwire(tool, seat, _validation_envelope(tool, e))
    dep = _deprecation_note(tool, kwargs)
    result = tool.handler(args)
    if not isinstance(result, dict):
        result = {"ok": False, "error": {"code": "internal", "message": "handler returned a non-envelope"},
                  "hint": ""}
    if result.get("ok"):
        _reset_failure(seat, tool.name)
        if dep:
            result["hint"] = ((result.get("hint") or "") + dep).strip()
        return result
    return _apply_tripwire(tool, seat, result)


# ----------------------------------------------------------------------------- bounded calls
#
# No tool call blocks on an executable or another service beyond the call cap (design §19
# rule 4). A tool that launches a process or waits on the pool (spawn, resume, reap,
# preflight) runs its work in a daemon thread the server owns; if it does not finish
# within the cap the tool returns {status:"running", poll:...} and the work continues in the
# background.


def _call_cap() -> float:
    try:
        return float(settings.get("EDP8_TOOL_CALL_CAP_S"))
    except ValueError:
        return 30.0


def _bounded(name: str, thunk: Callable[[], dict[str, Any]], running: dict[str, Any]) -> dict[str, Any]:
    """Run `thunk` in a daemon thread carrying this request's context; return its result if it
    finishes within the call cap, else `running` (the work keeps going in the background)."""
    ctx = contextvars.copy_context()
    holder: dict[str, Any] = {}
    done = threading.Event()

    def _work() -> None:
        try:
            holder["r"] = ctx.run(thunk)
        except Exception as e:  # noqa: BLE001 — a crashed bg call must still surface, never hang
            holder["r"] = {"ok": False, "error": {"code": "internal", "message": f"{name} crashed: {e}"},
                           "hint": "the background call raised; see the server log"}
        finally:
            done.set()

    threading.Thread(target=_work, name=f"bounded:{name}", daemon=True).start()
    if done.wait(timeout=_call_cap()):
        return holder["r"]
    return running


# ============================================================================= identity


class SubscribeArgs(Args):
    pass


class ResumeSelfArgs(Args):
    pass


class ContextArgs(Args):
    ticket_id: str | None = Field(default=None, description='one ticket, or omit for all yours')
    verbose: bool = Field(default=False, description='full unbounded snapshot')


class ContextDeltaArgs(Args):
    # not a subclass of ContextArgs: context_delta takes no `verbose` — its behaviour is unchanged by S12.
    ticket_id: str | None = Field(default=None, description='one ticket, or omit for all yours')
    cursor: str = Field(description='the cursor from your last context/delta')
    limit: int = Field(default=50, ge=1, le=100, description='max changes per page; continue if has_more')


class DescribeObjectsArgs(Args):
    type: str | None = Field(default=None, description="omit to list; an object name, a Context* type, 'enums' or 'enum:<Name>'")


class DescribeArgs(Args):
    type: str = Field(description="an object type, 'enums', or 'enum:<Name>'")


class GetGuideArgs(Args):
    name: str = Field(description='guide name without .md')


class WhoamiArgs(Args):
    pass


class PreflightArgs(Args):
    pass


def _preflight(_: PreflightArgs) -> dict[str, Any]:
    """Host + fleet headroom in one idempotent read. Advisory only: nothing here refuses
    anything (owner ruling 2026-09-07) — the caller weighs it and decides."""
    out: dict[str, Any] = {}
    try:
        import psutil
        vm = psutil.virtual_memory()
        out["host"] = {"free_mb": int(vm.available // 2**20), "total_mb": int(vm.total // 2**20),
                       "used_pct": round(vm.percent, 1)}
    except Exception as e:  # noqa: BLE001
        out["host"] = {"note": f"memory unreadable: {type(e).__name__}"}
    try:
        from . import launcher, pool_adapter
        got = pool_adapter.sessions()
        rows = launcher.parse_sessions(got.get("value")) if got.get("ok") else None
        if rows is None:  # the pool cannot say: unknown, never "0 live" (t-326566ee13)
            out["seats"] = {"live": None, "note": "the pool cannot say which seats are live"}
        else:
            live = [s for s in rows if launcher.seat_is_live(s)]
            out["seats"] = {"live": len(live), "handles": sorted(s.get("handle") or "" for s in live)}
        cap = pool_adapter.capacity()
        if cap.get("ok") and rows is not None:
            out["seats"]["caps"] = cap["value"]
    except Exception as e:  # noqa: BLE001
        out["seats"] = {"note": f"pool unreachable: {type(e).__name__}"}
    try:
        from . import run_state
        out["services"] = run_state.snapshot()  # launcher-owned infra state, read-only (design §22 rule 4)
    except Exception as e:  # noqa: BLE001
        out["services"] = {"note": f"run-state unreadable: {type(e).__name__}"}
    out["rules_of_thumb"] = {"claude_seat_mb": "250-500 (grows with context)", "codex_text_mb": "~300",
                             "codex_image_gen_mb": "up to ~1000", "stack_mb": "~500"}
    return {"ok": True, "value": out,
            "hint": "advisory, never a gate: compare host.free_mb with what you are about to start "
                    "(rules_of_thumb) — you decide, and say why on the thread"}


def _preflight_bounded(a: PreflightArgs) -> dict[str, Any]:
    # §19 rule 4: even the advisory read is bounded — a slow host/pool never hangs the call.
    return _bounded("preflight", lambda: _preflight(a),
                    {"ok": True, "value": {"status": "running", "poll": "preflight"},
                     "hint": "preflight is taking unusually long (host/pool slow) — retry, and weigh the risk yourself"})


def _whoami(_: WhoamiArgs) -> dict[str, Any]:
    resp = get_client().whoami()
    if resp.get("ok"):
        role = resp["value"]["participant"]["role"]
        resp["value"]["role"] = role
        wf_bundle = resp["value"].pop("bundle", None)  # S13: the board reads it from the epic's workflow
        resp["value"]["bundles_available"] = wf_bundle if wf_bundle is not None else ROLE_BUNDLES.get(role, [])
        resp["value"]["lineage"] = _lineage(resp["value"]["participant"].get("id") or "")
        resp["value"]["server_version"] = _server_version  # the tool code you are talking to (git sha)
    return resp


def _lineage(me: str) -> dict[str, Any]:
    """Who spawned me, what I spawned, who else is live on my epic — every shell
    knows its team and which inboxes exist. Best-effort: pool down = empty."""
    out: dict[str, Any] = {"my_handle": me, "spawned_by": None, "children": [], "epic_team": []}
    try:
        from . import pool_adapter
        got = pool_adapter.sessions()
        if not got.get("ok"):
            return out
        rows = got["value"] if isinstance(got["value"], list) else got["value"].get("sessions", [])
        by_sid = {s.get("session_id"): s for s in rows}
        mine = next((s for s in rows if s.get("handle") == me and s.get("state") in ("active", "alive", "starting")), None) \
            or next((s for s in rows if s.get("handle") == me), None)
        if mine:
            parent = by_sid.get(mine.get("parent"))
            out["spawned_by"] = parent.get("handle") if parent else (mine.get("parent") or None)
            out["children"] = sorted({s.get("handle") for s in rows
                                      if s.get("parent") == mine.get("session_id") and s.get("handle")})
        epic = me.split(".", 1)[1] if "." in me else None
        if epic:
            epic_root = epic.split(".", 1)[0]
            out["epic_team"] = sorted({f"{s.get('handle')} ({s.get('state')})" for s in rows
                                       if s.get("handle") and s.get("handle") != me
                                       and epic_root in s.get("handle", "")
                                       and s.get("state") in ("active", "alive", "parked")})
    except Exception as e:  # pool down = no lineage, but never silently: name it in the payload
        out["note"] = f"lineage unavailable (pool unreachable: {type(e).__name__})"
    return out


_LISTENING_ROLES = {"architect", "owner"}


def _heartbeat_prompt(participant: str) -> str:
    """The cron fallback text is role-aware: a listening seat idles on a quiet board, a doing
    seat resumes its plan. (2026-09-08: a role-blind "act only if new" prompt made an engineer
    with an unbuilt plan end every idle wake — m-0743c493b2.)"""
    role = participant.split(".", 1)[0]
    choice = ("edp8 heartbeat: choose context_delta(cursor=your last valid cursor) for changes since your last read. "
              "Use context() at boot, after compaction if you lack sufficient context/a valid cursor, or when a delta "
              "explicitly requires resynchronization. Do not call both routinely. ")
    if role in _LISTENING_ROLES:
        return choice + "Act only on new actionable information; otherwise end silently."
    return (choice + "Answer anything new, then RESUME THE NEXT UNBUILT ITEM of "
            "your plan doc — a quiet board is not a reason to stop. End the turn silently only when your "
            "ticket is in_review/done or you are blocked (record_status(status=blocked) and a deviation first).")


def _subscribe(_: SubscribeArgs) -> dict[str, Any]:
    client = get_client()
    py = sys.executable.replace("\\", "/")  # bash-safe: the Monitor tool runs bash, which eats backslashes
    monitor_cmd = f'"{py}" -m edp8.feed_driver --participant {client.participant} --board {client.base_url}'
    broker = settings.get("EDP_BROKER_URL") if settings.is_set("EDP_BROKER_URL") else None
    if broker:
        monitor_cmd += f" --broker {broker}"
    listening: dict[str, Any] = {}
    try:  # the delivery contract for this seat's role; best-effort (an old board lacks the route)
        got = client.listening()
        if got.get("ok"):
            listening = got["value"]
    except Exception:  # noqa: BLE001 — the wake plane still works without the contract text
        pass
    return {
        "ok": True,
        "value": {
            "monitor_cmd": monitor_cmd,
            "listening": listening,
            "cron": {
                "expr": "*/30 * * * *",
                "prompt": _heartbeat_prompt(client.participant),
            },
        },
        "hint": "run monitor_cmd under the Monitor tool once — it is your wake plane, and its first line "
                "prints `listening` (what wakes you); CronCreate the cron once as the fallback if a wake is missed",
    }


# S12 (qa finding 18): a multi-ticket checking seat's context() returned ~120k chars and
# overflowed the MCP client cap. The snapshot is bounded HERE, in the tool layer, so board.py
# _context_snapshot / ticket_view (shared by context_delta) stay unchanged. Default is bounded;
# verbose=True hands back the full snapshot. The budget is deliberately below the client cap.
_CONTEXT_BUDGET_B = 16_000        # default byte cap for the bounded snapshot (env-overridable; dec-7581ebda87)
_THREAD_HEAD = 200                # per-message body kept in a bounded thread
_THREAD_KEEP = 3                  # newest messages kept per ticket by default
_DOC_SUMMARY_HEAD = 200           # doc summary kept in a bounded snapshot
_FOR_YOU_HEAD = 400               # per-message body kept for a message addressed to the seat


def _context_budget() -> int:
    try:
        return max(4_000, int(settings.get("EDP8_CONTEXT_BUDGET_B")))
    except ValueError:
        return _CONTEXT_BUDGET_B


def _clip(s: Any, n: int) -> Any:
    if not isinstance(s, str) or len(s) <= n:
        return s
    return s[:n].rstrip() + f"… (+{len(s) - n} chars)"


def _thread_row(r: dict[str, Any], head: int, tight: bool) -> dict[str, Any]:
    return {**r, "text": _clip(r.get("text"), head),
            # C18: the rendered quotes get a few bodies' room, never unbounded; a tighter
            # pass drops the compact refs too (message_read has them)
            **({"quoted": _clip(r["quoted"], 4 * head)} if r.get("quoted") else {}),
            **({"quotes": []} if r.get("quotes") and tight else {}),
            # S4: a tighter pass keeps a code anchor's first line (path:Lx-y @sha) only
            **({"code_anchor": r["code_anchor"].split("\n", 1)[0]} if r.get("code_anchor") and tight else {})}


def _bound_snapshot(snap: dict[str, Any], *, thread_keep: int, thread_head: int,
                    doc_head: int, words_head: int | None,
                    desc_head: int | None = None, for_you_keep: int = 5,
                    for_you_head: int = _FOR_YOU_HEAD) -> tuple[dict[str, Any], set[str]]:
    """Return a byte-bounded copy of a context snapshot and the set of categories trimmed
    ('thread'/'docs'/'words'). Per-ticket summaries + read_refs stay; thread bodies and doc
    summaries are clipped/paged. Never touches `cursor`, `asks_for_me`, criteria, chain or the
    ticket record. dec-7581ebda87: `for_you` (messages addressed to the seat) is kept ahead of the thread,
    and the newest-N window never holds the seat's own posts or a row already in `for_you`."""
    hit: set[str] = set()
    out = dict(snap)
    me = (snap.get("participant") or {}).get("id")
    tickets_in = snap.get("tickets") or []
    new_tickets: list[dict[str, Any]] = []
    for tv in tickets_in:
        tv = dict(tv)
        rows = tv.get("thread") or []
        total = tv.get("thread_total", len(rows))
        tight = thread_head < _THREAD_HEAD
        mine = [r for r in tv.get("for_you") or [] if isinstance(r, dict)]
        if "for_you" in tv:
            tv["for_you"] = [_thread_row(r, for_you_head, tight) for r in mine[-for_you_keep:]]
            if len(mine) > for_you_keep or any(len(r.get("text") or "") > for_you_head for r in mine):
                hit.add("thread")
        shown = {r.get("id") for r in mine[-for_you_keep:]}
        window = [r for r in rows if r.get("created_by") != me and r.get("id") not in shown]
        kept = window[-thread_keep:] if thread_keep > 0 else []
        tv["thread"] = [_thread_row(r, thread_head, tight) for r in kept]
        if total > len(kept) or any(len(r.get("text") or "") > thread_head
                                    or len(r.get("quoted") or "") > 4 * thread_head for r in rows):
            hit.add("thread")
        if total > len(kept):
            tv["thread_omitted"] = total - len(kept)
        if tv.get("docs"):
            new_docs = []
            for d in tv["docs"]:
                d = dict(d)
                if isinstance(d.get("summary"), str) and len(d["summary"]) > doc_head:
                    d["summary"] = _clip(d["summary"], doc_head)
                    hit.add("docs")
                new_docs.append(d)
            tv["docs"] = new_docs
        if words_head is not None and isinstance(tv.get("words"), str) and len(tv["words"]) > words_head:
            tv["words"] = _clip(tv["words"], words_head)
            hit.add("words")
        rec = tv.get("ticket")
        if desc_head is not None and isinstance(rec, dict) and len(rec.get("description") or "") > desc_head:
            # S23: a tight budget — a long ticket description is the usual floor; ticket_read has it
            tv["ticket"] = {**rec, "description": _clip(rec["description"], desc_head)}
            hit.add("description")
        if desc_head is not None and isinstance(tv.get("recall"), dict) and tv["recall"].get("items"):
            tv["recall"] = {**tv["recall"], "items": [{**r, "text": _clip(r.get("text"), 100)}
                                                      for r in tv["recall"]["items"]]}
        new_tickets.append(tv)
    out["tickets"] = new_tickets
    return out, hit


def _compact_snapshot(snap: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """S23 floor pass (tight budget): each ticket keeps its record, chain and criteria as compact rows
    (id/status/verdict, text clipped) and its docs/children/links as refs; recall becomes a count. Every
    dropped field has a named fetch in `omitted`."""
    out = dict(snap)
    me = (snap.get("participant") or {}).get("id")
    tickets = []
    for tv in snap.get("tickets") or []:
        rec = tv.get("ticket") or {}
        tickets.append({
            "ticket": {k: (_clip(rec.get(k), 160) if k in ("title", "description") else rec.get(k))
                       for k in ("id", "kind", "status", "assignee", "parent_id", "design_ref", "title",
                                 "description") if rec.get(k)},
            "chain": [{"id": c.get("id"), "kind": c.get("kind"), "status": c.get("status")}
                      for c in tv.get("chain") or []],
            "criteria": [{"id": c.get("id"), "text": _clip(c.get("text"), 120), "check": c.get("check"),
                          "checked_by": c.get("checked_by"), "verdict": c.get("verdict"),
                          **({"evidence_ref": c["evidence_ref"]} if c.get("evidence_ref") else {})}
                         for c in tv.get("criteria") or []],
            "docs": [f"{d.get('id')} {d.get('doc_type')} v{d.get('version')}" for d in tv.get("docs") or []],
            "children": [f"{c.get('id')} {c.get('status')}" for c in tv.get("children") or []],
            "links": [f"{x.get('from_id')} {x.get('relation')} {x.get('to_id')}" for x in tv.get("links") or []],
            **({"open_gates": tv["open_gates"]} if tv.get("open_gates") else {}),
            **({"blockers": tv["blockers"]} if tv.get("blockers") else {}),
            # dec-7581ebda87: messages addressed to the seat first, then the newest one not its own (clipped);
            # older bodies are the named thread fetch
            "for_you": [{k: (_clip(m.get(k), 160) if k == "text" else m.get(k))
                         for k in ("id", "kind", "created_by", "created_at", "text", "answered") if m.get(k)}
                        for m in (tv.get("for_you") or [])[-3:] if isinstance(m, dict)],
            "thread": [{k: (_clip(m.get(k), 120) if k == "text" else m.get(k))
                        for k in ("id", "kind", "created_by", "created_at", "text") if m.get(k)}
                       for m in [m for m in tv.get("thread") or [] if isinstance(m, dict)
                                 and m.get("created_by") != me
                                 and m.get("id") not in {f.get("id") for f in tv.get("for_you") or []}][-1:]],
            "thread_total": tv.get("thread_total", len(tv.get("thread") or [])),
            "recall_count": len((tv.get("recall") or {}).get("items") or []),
        })
    out["tickets"] = tickets
    return out, {"thread", "docs", "words", "description", "compact"}


def _bytes(obj: Any) -> int:
    # match the MCP client's serialisation (ASCII-escaped) so the budget is a real cap even for
    # non-ASCII bodies — ensure_ascii=False would under-count a CJK snapshot by ~2x.
    return len(json.dumps(obj, ensure_ascii=True, default=str).encode("utf-8"))


def _context(args: ContextArgs) -> dict[str, Any]:
    resp = get_client().context(ticket_id=args.ticket_id)
    if args.verbose or not isinstance(resp, dict) or not resp.get("ok"):
        return resp
    snap = resp.get("value")
    if not isinstance(snap, dict):
        return resp
    budget = _context_budget()
    reserve = 1_500                       # room for the `omitted` receipt + the {ok,hint} envelope
    # progressively tighter passes; take the FIRST that fits, else the tightest available (the
    # per-ticket records + criteria + asks are the irreducible floor and are never dropped).
    passes = [
        dict(thread_keep=_THREAD_KEEP, thread_head=_THREAD_HEAD, doc_head=_DOC_SUMMARY_HEAD, words_head=800),
        dict(thread_keep=1, thread_head=120, doc_head=120, words_head=400, desc_head=1500,
             for_you_keep=3, for_you_head=240),
        dict(thread_keep=0, thread_head=0, doc_head=0, words_head=200, desc_head=600,
             for_you_keep=2, for_you_head=160),
    ]
    bounded: dict[str, Any] = {}
    hit: set[str] = set()
    for i, p in enumerate(passes):
        bounded, hit = _bound_snapshot(snap, **p)
        if i > 0:
            hit.add("_tightened")
        if _bytes(bounded) <= budget - reserve:
            break
    else:
        bounded, hit = _compact_snapshot(snap)
    over = _bytes(bounded) > budget
    if hit:  # something was clipped or a tighter pass was forced
        fetch = {}
        if "thread" in hit:
            fetch["thread_bodies"] = ("full window: context(ticket_id=<id>, verbose=True); complete history: "
                                      "message_query(ticket_id=<id>, since_seq=0) then continue from last_seq")
        if "docs" in hit:
            fetch["doc_summaries"] = "doc_read(id) for the full body"
        if "words" in hit:
            fetch["epic_words"] = "context(verbose=True) or ticket_read(<epic id>) for the owner's full words"
        if "description" in hit:
            fetch["description"] = "ticket_read(ticket_id=<id>, include='') for the full description"
        if "compact" in hit:
            fetch["compact"] = ("criteria/docs/children/links are refs; ticket_read(ticket_id=<id>) or "
                                "criterion_query(ticket_id=<id>) for rows, lookup(scope=<epic>) for recall")
        bounded["omitted"] = {
            "why": f"bounded to EDP8_CONTEXT_BUDGET_B={budget} bytes (verbose=False); "
                   f"snapshot is {_bytes(bounded)} bytes",
            **fetch,
            "full_snapshot": "context(verbose=True)",
        }
        if over:
            bounded["omitted"]["still_over_budget"] = (
                "the per-ticket records/criteria/asks alone exceed the budget; nothing summary-level was "
                "dropped — narrow with context(ticket_id=<id>) or raise EDP8_CONTEXT_BUDGET_B")
    return {**resp, "value": bounded}


def _session_is_fresh_spawn() -> bool:
    """True when the caller's CURRENT pool session is a fresh spawn — never resumed (no `resumed_at`)
    and not launched to continue an old conversation (spawn_settings.resume_session empty). Pain
    p-fb874501: a participant id respawned after close sees its own earlier work in context(), answers
    the card's "Resumed?" with yes and posts a false [resumed]. Unknown (no session id, pool down,
    row missing) answers False, so resume_self keeps its resume behaviour."""
    sid = my_session_id()
    if not sid:
        return False
    out = _pool_call("sessions", {})
    rows = out.get("value") if out.get("ok") else None
    if not isinstance(rows, list):
        return False
    row = next((r for r in rows if isinstance(r, dict) and r.get("session_id") == sid), None)
    if row is None:
        return False
    return not row.get("resumed_at") and not (row.get("spawn_settings") or {}).get("resume_session")


def _resume_self(_: ResumeSelfArgs) -> dict[str, Any]:
    """The seat-side resume command (owner m-268fc869f5, 2026-09-18). A resumed shell holds a
    transcript whose Monitor and cron died with the old process and that may end in a hand-off;
    nothing in it can be trusted as "current". This tool regenerates, from the board, everything
    the seat must do next, in order, and records the resume on the seat's thread so the spawner
    and the owner see it happened. Guide: get_guide('resume')."""
    client = get_client()
    who = client.whoami()
    armed = _subscribe(SubscribeArgs())
    asks = client.inbox()
    rows = (asks.get("value") or []) if asks.get("ok") else []
    identity = who.get("value") if who.get("ok") else {"id": client.participant}
    if _session_is_fresh_spawn():
        # a fresh spawn: nothing to resume, no [resumed] receipt; the spawn's steer/asks go first
        rows = sorted(rows, key=lambda r: 0 if isinstance(r, dict) and r.get("kind") == "steer" else 1)
        return {
            "ok": True,
            "value": {
                "identity": identity,
                "fresh_spawn": True,
                "steps": [
                    "fresh spawn: boot normally, nothing to resume. Your earlier sessions' work is history "
                    "on the board, not a conversation to continue.",
                    "1. Arm your wake plane if you have not: `monitor_cmd` under Monitor once, `cron` via "
                    "CronCreate once (both below).",
                    f"2. Do the {len(rows)} open ask(s) below first (a steer from your spawner is listed first), "
                    "each with its answer_with call.",
                    "3. Continue your role card's boot: context() and the card's protocol.",
                ],
                "monitor_cmd": (armed.get("value") or {}).get("monitor_cmd"),
                "cron": (armed.get("value") or {}).get("cron"),
                "listening": (armed.get("value") or {}).get("listening"),
                "open_asks": rows,
            },
            "hint": "this session was spawned fresh (the pool row was never resumed); no [resumed] note posted",
        }
    steps = [
        "1. Arm your wake plane NOW: run `monitor_cmd` under the Monitor tool once, then CronCreate the "
        "`cron` once (both below). Without them nothing wakes you; the old ones died with the old process.",
        f"2. Answer the {len(rows)} open ask(s) below, oldest first, each with its answer_with call; a steer "
        "changes your plan, a human message is a person waiting.",
        "3. context(ticket_id=<your ticket>) to reload the current state of your work (this is your resync; "
        "save its cursor for the heartbeat's context_delta), then continue your plan from its next unbuilt "
        "item. Your earlier hand-off or close is history: this session is live until you close it again.",
        "4. record_status at your next milestone so the resume is visible as progress; never end a turn "
        "silently while asks are open or your story is in_progress.",
    ]
    try:  # transparency: the spawner and the owner see the resume on the seat's thread (best effort)
        client.record_status("deferred", note=f"[resumed] re-arming wake plane; {len(rows)} open ask(s) to answer first")
    except Exception:  # noqa: BLE001 — a failed receipt must not block the resume itself
        pass
    return {
        "ok": True,
        "value": {
            "identity": identity,
            "steps": steps,
            "monitor_cmd": (armed.get("value") or {}).get("monitor_cmd"),
            "cron": (armed.get("value") or {}).get("cron"),
            "listening": (armed.get("value") or {}).get("listening"),
            "open_asks": rows,
        },
        "hint": "follow `steps` in order; get_guide('resume') is the full contract. resume_self is idempotent: "
                "call it again after compaction or whenever you are unsure whether you are armed",
    }


def _object_index() -> list[str]:
    """Every describable object: the board's types, the tool layer's own (LOCAL_OBJECTS) and every object a
    tool names (tool_contracts.TOOL_OBJECTS) — the contract test asserts the last is a subset."""
    from .schemas import OBJECT_TYPES
    return sorted(set(OBJECT_TYPES) | set(LOCAL_OBJECTS) | set(tools_by_object()))


def _describe_objects(args: DescribeObjectsArgs) -> dict[str, Any]:
    from .context_contracts import CONTEXT_TYPES
    if args.type is None:
        return {"ok": True, "value": {"objects": _object_index() + sorted(CONTEXT_TYPES),
                "enums": sorted(ENUMS), "guides": ["context-refresh", "agent-tools"]},
                "hint": "describe(type=<name>) for fields, contract, linked tools and skills"}
    return _describe(DescribeArgs(type=args.type))


def _links_for(t: str) -> dict[str, Any]:
    from .tool_contracts import OBJECT_SKILLS
    return {"tools": tools_by_object().get(t, []), "skills": list(OBJECT_SKILLS.get(t, ()))}


def _lean_schema(node: Any) -> Any:
    """A JSON schema without pydantic's generated titles: a property's "Created At" for `created_at`, a $def's
    "SessionState" under its own name. Each restates its key, so dropping it loses nothing; a hand-written
    title stays (S23 qa report-bcef24a36a: describe_objects may not grow bytes as objects are added)."""
    if isinstance(node, list):
        return [_lean_schema(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {k: _lean_schema(v) for k, v in node.items()}
    for key, auto in (("properties", lambda k: k.replace("_", " ").title()), ("$defs", lambda k: k)):
        if isinstance(out.get(key), dict):
            out[key] = {k: ({f: x for f, x in v.items() if not (f == "title" and x == auto(k))}
                            if isinstance(v, dict) else v) for k, v in out[key].items()}
    return out


def _describe(args: DescribeArgs) -> dict[str, Any]:
    from .context_contracts import CONTEXT_TYPES
    t = args.type
    if t in CONTEXT_TYPES:
        return {"ok": True, "value": {"schema": _lean_schema(CONTEXT_TYPES[t].model_json_schema()),
                "relationships": ["ticket", "doc", "message", "event"],
                "guides": ["context-refresh"], "tools": ["context", "context_delta"],
                "contract": "Full orientation or bounded reference changes; signed cursors are caller-owned, resync_required means context()."}, "hint": "get_guide('context-refresh')"}
    # Enums are answered from the schema registry (§19 rule 3): describe('enums') lists them
    # all, describe('enum:<Name>') returns one — no board round-trip, so every seat can look
    # up a strict argument's allowed values without a network call.
    if t == "enums":
        return {"ok": True,
                "value": {"enums": {name: [m.value for m in e] for name, e in ENUMS.items()}},
                "hint": "describe('enum:<Name>') returns one enum's values; these are the strict "
                        "vocabularies tool args use — pass one of these, never a guess"}
    if t.startswith("enum:"):
        name = t.split(":", 1)[1]
        e = ENUMS.get(name)
        if e is None:
            return {"ok": False,
                    "error": {"code": "not_found", "message": f"unknown enum {name!r}",
                              "field": "type", "allowed": sorted(ENUMS)},
                    "hint": "describe('enums') lists every enum name"}
        return {"ok": True, "value": {"enum": name, "values": [m.value for m in e]}, "hint": ""}
    if t in LOCAL_OBJECTS:  # S23: objects the tool layer owns (gate, topic, workflow, pain, ...)
        return {"ok": True, "value": {"type": t, **LOCAL_OBJECTS[t], **_links_for(t)}, "hint": ""}
    out = get_client().describe(t)
    if out.get("ok"):
        if isinstance(out["value"].get("schema"), dict):
            out["value"]["schema"] = _lean_schema(out["value"]["schema"])
        out["value"].update(_links_for(t))
        out["value"]["relationships"] = {"ticket": ["criterion", "doc", "message", "link"],
            "doc": ["ticket", "link", "criterion"], "artifact": ["message", "ticket", "link"]}.get(t, ["ticket"])
        out["value"]["guides"] = ["agent-tools"]
    elif (out.get("error") or {}).get("code") == "not_found":
        out["error"]["allowed"] = _object_index()
        out["hint"] = "describe_objects() lists every object; 'enums' or 'enum:<Name>' for vocabularies"
    return out


def _edp8_home() -> Path:
    return settings.agent_home()


def _get_guide(args: GetGuideArgs) -> dict[str, Any]:
    p = _edp8_home() / "guides" / f"{args.name}.md"
    if not p.is_file():
        return {"ok": False, "error": {"code": "not_found", "message": f"guide {args.name!r} does not exist"},
                "hint": f"guides live under {p.parent}"}
    return {"ok": True, "value": {"name": args.name, "body": p.read_text(encoding="utf-8")}, "hint": ""}


IDENTITY_TOOLS = [
    ToolDef("describe_objects", "List object/enum names, or one object's schema",
            "unsure of an object's contract; omit type to list names",
            'the index or the schema',
            DescribeObjectsArgs, _describe_objects, "identity"),
    ToolDef("context_delta", 'Read what changed for you since a context cursor',
            'on a heartbeat wake, with your last cursor; not with context() routinely',
            'changes, next_cursor, has_more (byte-capped, `omitted` names the fetch); resync_required means context()',
            ContextDeltaArgs, lambda a: get_client().context_delta(a.cursor, a.ticket_id, a.limit), "identity"),
    ToolDef("whoami",
            'Your identity, role, open tickets, lineage and tool bundles',
            'at boot',
            'the participant, tickets, bundles and server version',
            WhoamiArgs, _whoami, "identity"),
    ToolDef("preflight",
            'Host free RAM and live seats vs pool caps; advisory, never blocks',
            'before a spawn',
            'the numbers and rules of thumb',
            PreflightArgs, _preflight_bounded, "identity"),
    ToolDef("subscribe",
            'Arm your event feed (once per session)',
            'at boot, right after whoami',
            'the monitor command and heartbeat cron to arm',
            SubscribeArgs, _subscribe, "identity"),
    ToolDef("resume_self",
            'Resume after a park, reap, crash or respawn: re-arm wakes, list open asks and steps',
            'first call of a resumed shell, after compaction, or when unsure Monitor/cron are alive',
            "identity, ordered steps, monitor_cmd + cron, open asks; see get_guide('resume')",
            ResumeSelfArgs, _resume_self, "identity"),
    ToolDef("context",
            'Load your ticket(s): chain, criteria, docs, thread, open asks; byte-capped unless verbose',
            'at boot, after compaction without a cursor, or when a delta says resync_required',
            'ContextSnapshot with a cursor for context_delta; `omitted` names each fetch',
            ContextArgs, _context, "identity"),
    ToolDef("describe",
            "An object type's fields and contract, or an enum's values ('enums' = all, 'enum:<Name>' = one)",
            "unsure of a type's fields or an argument's allowed values",
            'the schema and contract, or the enum values',
            DescribeArgs, _describe, "identity"),
    ToolDef("get_guide",
            'Fetch one reference guide by name',
            'when a card or task names a guide',
            "the guide's markdown, or not_found",
            GetGuideArgs, _get_guide, "identity"),
]

# ============================================================================= ticket


class TicketCreateArgs(CreateArgs):
    kind: SeatTicketKind = Field(description='ticket level')
    work_type: WorkType = Field(description='kind of work')
    title: str = Field(description="epic: the owner's words verbatim (a short title is derived); story/task: the slice name")
    words: str | None = Field(default=None, description="epic or quick task: the owner's verbatim request; immutable")
    parent_id: str | None = None  # story/task: required, except the owner's quick task (the tool description says so)
    assignee: str | None = Field(default=None)
    description: str = Field(default="", description='scope, intent, pointers to files/docs')
    tags: list[str] | None = Field(default=None)


class TicketReadArgs(Args):
    ticket_id: str = Field(validation_alias=AliasChoices("ticket_id", "id"), description='ticket id')
    include: str | None = Field(default=None, description='comma list of chain,criteria,docs,children,blockers,gates,thread,links; omit for all; lifecycle (only when named) = the pinned workflow\'s lifecycle table')
    thread_limit: int = Field(default=20, ge=0, le=200,
                              description='newest thread messages to include (0-200)')


class TicketQueryArgs(PageArgs):
    kind: SeatTicketKind | None = Field(default=None)
    work_type: WorkType | None = None
    parent_id: str | None = None
    status: TicketStatus | None = Field(default=None)
    assignee: str | None = None
    epic_id: str | None = Field(default=None, description='every ticket under this epic')
    created_by: str | None = None
    tag: str | None = Field(default=None)
    q: str | None = Field(default=None, description='exact words in title/description/tags')


class TicketUpdateArgs(Args):
    ticket_id: str = Field(validation_alias=AliasChoices("ticket_id", "id"), description='ticket id')
    status: TicketStatus | None = Field(default=None, description='next legal status')
    assignee: str | None = Field(default=None)
    design_ref: str | None = Field(default=None, description='design/plan doc id')
    description: str | None = Field(default=None, description='replaces the description')
    tags: list[str] | None = Field(default=None, description='replaces the tag list')
    title: str | None = Field(default=None, description='short title, <=80 chars (architect/owner)')


class CriterionCreateArgs(CreateArgs):
    ticket_id: str = Field(description='ticket id')
    text: str = Field(description='the checkable fact')
    check: Check = Field(description='how it is checked')
    checked_by: CheckedBy | None = None  # the tool description: needs the owner's override_reason
    override_reason: str | None = Field(default=None, description='owner only: why the derived checker is overridden')


class CriterionQueryArgs(Args):
    ticket_id: str = Field(description='ticket id')


class CriterionUpdateArgs(Args):
    model_config = {"extra": "forbid"}  # an unknown kwarg is an ERROR, never a silent drop
    id: str = Field(description='criterion id')
    evidence_ref: str | None = None  # the report doc id proving the check
    verdict: Verdict | None = Field(default=None, description='set after evidence_ref (checker only)')
    text: str | None = Field(default=None, description='reword (author, while pending)')
    evidence_version: int | None = Field(default=None,
        description='doc version signed; refused if below current')
    stale_ok: bool = Field(default=False, description='sign the version you read though the doc moved on')
    note: str = ''  # why, with a verdict; the board keeps it as a claim (S-IMPLICIT)


def _once(tool: str, a: CreateArgs, create: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    return tool_idem.once(tool, get_client().participant,
                          a.model_dump(mode="json", exclude={"idempotency_key"}), a.idempotency_key, create)


ECHO_CLIP = 240  # chars of a write's own body echoed back; past it the reply names the read call


def _receipt(resp: dict[str, Any], fields: tuple[str, ...], read: Callable[[dict[str, Any]], str], *,
             key: str | None = None) -> dict[str, Any]:
    """S23-T6 N2 (report-36481f7a4e; architect ruling m-44ae9118d1): a write replies with what it made, not what
    it was sent. Each body field over ECHO_CLIP chars is clipped ("… (+N chars)") and `echo` names its byte
    count and the read call that returns it whole: the named read is the opt-in, never an arg. `key` picks a
    nested record (topic_propose: value.doc). Unset fields (null, [], {}) are left out: the writer set nothing
    there and the named read returns the whole row (S23 qa report-bcef24a36a: no task may grow bytes)."""
    v = resp.get("value") if resp.get("ok") else None
    rec = (v.get(key) if key else v) if isinstance(v, dict) else None
    if not isinstance(rec, dict):
        return resp
    rec = {f: x for f, x in rec.items() if x is not None and x != [] and x != {}}
    long = {f: rec[f] for f in fields if isinstance(rec.get(f), str) and len(rec[f]) > ECHO_CLIP}
    if long:
        rec = {**rec, **{f: tool_paging.clip(s, ECHO_CLIP) for f, s in long.items()},
               "echo": {"bytes": {f: len(s.encode("utf-8")) for f, s in long.items()}, "read": read(rec)}}
    return {**resp, "value": {**v, key: rec} if key else rec}


def _doc_ref(d: dict[str, Any]) -> str:
    return f"doc_read(id='{d.get('id')}')"


def _msg_ref(m: dict[str, Any]) -> str:
    return f"message_read(id='{m.get('id')}')"


def _ticket_ref(t: dict[str, Any]) -> str:
    return f"ticket_read(ticket_id='{t.get('id')}', include='')"


def _record_ref(r: dict[str, Any]) -> str:
    return f"lookup(scope='{r.get('scope') or r.get('domain') or '<scope>'}', id='{r.get('id')}')"


def _ticket_create(a: TicketCreateArgs) -> dict[str, Any]:
    return _receipt(_once("ticket_create", a, lambda: get_client().ticket_create(
        kind=a.kind, work_type=a.work_type, title=a.title, parent_id=a.parent_id, assignee=a.assignee,
        description=a.description, tags=a.tags, words=a.words)), ("description", "words"), _ticket_ref)


def _ticket_read(a: TicketReadArgs) -> dict[str, Any]:
    return get_client().ticket_read(a.ticket_id, include=a.include, thread_limit=a.thread_limit)


def _filters(a: PageArgs) -> dict[str, Any]:
    return a.model_dump(exclude={"limit", "cursor", "verbose"}, exclude_none=True)


def _paged(tool: str, resp: dict[str, Any], a: PageArgs, project: Callable[[dict[str, Any]], dict[str, Any]],
           full: str, rows_of: Callable[[Any], list[Any]] | None = None,
           enrich: Callable[[Any], Any] | None = None) -> dict[str, Any]:
    """Offset-page a board list reply (S23): count, compact items, next_cursor and the `page` receipt."""
    if not resp.get("ok"):
        return resp
    rows = rows_of(resp.get("value")) if rows_of else (resp.get("value") or [])
    try:
        value = tool_paging.offset_page(tool, list(rows), filters=_filters(a), limit=a.limit, cursor=a.cursor,
                                        verbose=a.verbose, project=project, full=full, enrich=enrich)
    except tool_paging.CursorError as e:
        return tool_paging.cursor_error(tool, e)
    return {**resp, "value": value}


def _ticket_row(r: dict[str, Any]) -> dict[str, Any]:
    return tool_paging.pick(r, ("id", "kind", "status", "title", "assignee", "parent_id", "work_type", "tags"),
                            {"title": 90})


def _ticket_query(a: TicketQueryArgs) -> dict[str, Any]:
    resp = get_client().ticket_query(kind=a.kind, work_type=a.work_type, parent_id=a.parent_id,
                                     status=a.status, assignee=a.assignee, epic_id=a.epic_id,
                                     created_by=a.created_by, tag=a.tag, q=a.q)
    return _paged("ticket_query", resp, a, _ticket_row, "ticket_read(ticket_id) or verbose=true")


def _ticket_update(a: TicketUpdateArgs) -> dict[str, Any]:
    return _receipt(get_client().ticket_update(a.ticket_id, status=a.status, assignee=a.assignee,
                                               design_ref=a.design_ref, description=a.description, tags=a.tags,
                                               title=a.title), ("description", "words"), _ticket_ref)


def _criterion_create(a: CriterionCreateArgs) -> dict[str, Any]:
    return _receipt(_once("criterion_create", a, lambda: get_client().criterion_create(
        ticket_id=a.ticket_id, text=a.text, check=a.check, checked_by=a.checked_by,
        override_reason=a.override_reason)), ("text",),
        lambda c: f"criterion_query(ticket_id='{c.get('ticket_id')}')")


def _criterion_query(a: CriterionQueryArgs) -> dict[str, Any]:
    return get_client().criterion_query(a.ticket_id)


def _criterion_update(a: CriterionUpdateArgs) -> dict[str, Any]:
    return get_client().criterion_update(a.id, evidence_ref=a.evidence_ref, verdict=a.verdict, text=a.text,
                                         evidence_version=a.evidence_version, stale_ok=a.stale_ok, note=a.note)


TICKET_TOOLS = [
    ToolDef("ticket_create",
            'Create an epic (owner), story (architect; owner: a quick task, tag quick, no parent) or task. At most 8 open stories per epic (raised via a scope gate), at most 5 tasks per story',
            'when you own a new slice of work',
            'the ticket, or a scope error at a cap',
            TicketCreateArgs, _ticket_create, "ticket"),
    ToolDef("ticket_read",
            'One read of a ticket: record, chain, criteria, docs, children, blockers, gates, newest thread (thread_seq), links',
            "when you need a ticket's full state",
            'the ticket record',
            TicketReadArgs, _ticket_read, "ticket"),
    ToolDef("ticket_query",
            'List tickets matching the filter args',
            'to find tickets without an id',
            'matching tickets as a ≤8 KB page + next_cursor; verbose=full rows',
            TicketQueryArgs, _ticket_query, "ticket"),
    ToolDef("ticket_update",
            "Change the args given, per the transition rules",
            'to move or assign a ticket; in_review only once verified',
            'the ticket, or an error naming what is missing',
            TicketUpdateArgs, _ticket_update, "ticket"),
    ToolDef("criterion_create",
            "Add a checkable done-fact. Checker derived: qa (story/epic), engineer (task), owner (knowledge ticket); checked_by needs owner override_reason. Max 6 fresh per story",
            'before work starts, one per checkable fact',
            'the criterion with its derived checker',
            CriterionCreateArgs, _criterion_create, "ticket"),
    ToolDef("criterion_query",
            "List a ticket's criteria",
            'to see what is pending',
            'the criteria',
            CriterionQueryArgs, _criterion_query, "ticket"),
    ToolDef("criterion_update",
            "Set a criterion's evidence_ref, then its verdict (checker only)",
            'as the checker after the evidence doc exists; a doer attaches evidence_ref only',
            'the criterion and the pending count',
            CriterionUpdateArgs, _criterion_update, "ticket"),
]

# ============================================================================= doc


class DocCreateArgs(CreateArgs):
    doc_type: DocType = Field(description='design: architect; strategy_*/domain: sme; report: engineer/adversary/qa; note: any')
    title: str = Field(description='doc title')
    body_md: str = Field(description='markdown body')
    scope: str = Field(description='epic id | domain:<name> | global')
    tags: list[str] | None = Field(default=None, description='knowledge tags')
    status: Literal["active", "proposed"] | None = Field(
        default=None, description='proposed: owner approves')
    proposes: str | None = Field(default=None, description='active doc id it revises')
    ticket_id: str | None = Field(default=None, description='source ticket')


class DocReadArgs(Args):
    id: str = Field(description='doc id')
    version: int | None = Field(default=None, description='omit for latest; reuse the returned one to continue')
    offset: int | None = Field(default=None, ge=0, description='char offset; opts into bounded output')
    limit: int | None = Field(default=None, ge=1, le=32768, description='chars, default 8192 when bounded')
    section: str | None = Field(default=None, description='exact heading line; offset is relative to it')


class DocEditArgs(DocEdit):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(description='doc id')


class DocQueryArgs(PageArgs):
    doc_type: DocType | None = None
    scope: str | None = None
    owner_role: SeatRole | None = None
    tag: str | None = None
    status: Literal["active", "proposed", "retired"] | None = None


class DocUpdateArgs(Args):
    id: str = Field(description='doc id')
    body_md: str | None = None
    title: str | None = None
    tags: list[str] | None = Field(default=None, description='replaces the tag list')
    compact: bool = True  # T6 N2 (m-44ae9118d1): a receipt by default; false returns the doc (doc_read does too)


class LinkCreateArgs(Args):
    from_id: str = Field(description='subject (blocks: finishes first; extends: the more specific layer)')
    to_id: str = Field(description='object')
    relation: SeatRelation = Field(description='from_id <relation> to_id')


class LinkQueryArgs(PageArgs):
    from_id: str | None = None
    to_id: str | None = None
    relation: SeatRelation | None = None


class LinkDeleteArgs(Args):
    id: str = Field(description='link id')


def _doc_create(a: DocCreateArgs) -> dict[str, Any]:
    return _receipt(_once("doc_create", a, lambda: get_client().doc_create(
        doc_type=a.doc_type, title=a.title, body_md=a.body_md, scope=a.scope, tags=a.tags, status=a.status,
        proposes=a.proposes, ticket_id=a.ticket_id)), ("body_md",), _doc_ref)


def _doc_read(a: DocReadArgs) -> dict[str, Any]:
    return get_client().doc_read(a.id, version=a.version, offset=a.offset, limit=a.limit, section=a.section)


def _doc_row(r: dict[str, Any]) -> dict[str, Any]:
    return tool_paging.pick(r, ("id", "doc_type", "title", "version", "scope", "status", "owner_role", "tags"),
                            {"title": 90})


def _doc_query(a: DocQueryArgs) -> dict[str, Any]:
    resp = get_client().doc_query(doc_type=a.doc_type, scope=a.scope, owner_role=a.owner_role,
                                  tag=a.tag, status=a.status)
    return _paged("doc_query", resp, a, _doc_row, "doc_read(id) or verbose=true")


def _doc_update(a: DocUpdateArgs) -> dict[str, Any]:
    return get_client().doc_update(a.id, body_md=a.body_md, title=a.title, compact=a.compact, tags=a.tags)


def _doc_edit(a: DocEditArgs) -> dict[str, Any]:
    return get_client().doc_edit(a.id, a.expected_version, [e.model_dump() for e in a.edits], a.title)


def _link_create(a: LinkCreateArgs) -> dict[str, Any]:
    return get_client().link_create(from_id=a.from_id, to_id=a.to_id, relation=a.relation)


def _link_query(a: LinkQueryArgs) -> dict[str, Any]:
    resp = get_client().link_query(from_id=a.from_id, to_id=a.to_id, relation=a.relation)
    return _paged("link_query", resp, a,
                  lambda r: tool_paging.pick(r, ("id", "from_id", "relation", "to_id")), "verbose=true")


def _link_delete(a: LinkDeleteArgs) -> dict[str, Any]:
    return get_client().link_delete(a.id)


DOC_TOOLS = [
    ToolDef("doc_edit", 'Apply exact, unique, non-overlapping edits to one doc version atomically',
            'for small revisions after doc_read; match old_text against the original',
            'a compact receipt, or a conflict/match error (re-read)',
            DocEditArgs, _doc_edit, "doc"),
    ToolDef("doc_create",
            'Author a versioned markdown doc',
            'to record a design, strategy, domain guide, report or note',
            'the doc; link it to its ticket',
            DocCreateArgs, _doc_create, "doc"),
    ToolDef("doc_read",
            'Read a doc (latest or a version), whole or a bounded range',
            'when a ticket or link points at a doc',
            'the doc; offset/limit/section: a version-pinned range',
            DocReadArgs, _doc_read, "doc"),
    ToolDef("doc_query",
            'List docs by doc_type/scope/owner_role',
            'to find docs without an id',
            'doc summaries as a ≤8 KB page + next_cursor; verbose=full rows',
            DocQueryArgs, _doc_query, "doc"),
    ToolDef("doc_update",
            "Replace a doc's body/title as a new version",
            'to amend a doc you own',
            'a receipt; compact=false: the doc',
            DocUpdateArgs, _doc_update, "doc"),
    ToolDef("link_create",
            'Link from_id <relation> to_id (ticket/doc/artifact)',
            'to attach a design, strategy, evidence, blocker, artifact or doc layer',
            'the link',
            LinkCreateArgs, _link_create, "doc"),
    ToolDef("link_query",
            'List links by from_id/to_id/relation',
            'to see what something is linked to',
            'the links as a ≤8 KB page + next_cursor; verbose=full rows',
            LinkQueryArgs, _link_query, "doc"),
    ToolDef("link_delete",
            'Remove a link',
            'to undo a link made in error',
            'whether it was deleted',
            LinkDeleteArgs, _link_delete, "doc"),
]

# ============================================================================= thread


class MessageSendArgs(CreateArgs):
    ticket_id: str = Field(description='thread ticket')
    kind: MessageKind = Field(description='message kind')
    text: str = Field(description='message body')
    to: str | None = Field(default=None, description='id/@handle/role; omit=note')
    reply_to: str | None = Field(default=None, description='id answered')
    artifacts: list[str] | None = Field(default=None, description='staged artifact ids')
    # S4 code anchor; the board validates it (a 400 names the field), rules in describe('message'). No
    # description: the S20 surface budget (test_s20_token_cost) had 6 B of headroom on the architect.
    code_context: dict | None = None
    quotes: list[dict] | None = None  # C18: rules in describe('message'); no description (S20 budget)


class MessageQueryArgs(PageArgs):
    ticket_id: str | None = Field(default=None)
    to: str | None = Field(default=None, description='addressee id/role')
    kind: MessageKind | None = Field(default=None)
    created_by: str | None = Field(default=None)
    since_seq: int | None = Field(default=None, description='newer than this seq; 0 = from the start')


class MessageReadArgs(Args):
    id: str = Field(validation_alias=AliasChoices("id", "message_id"), description='message id')


class GateOpenArgs(Args):
    ticket_id: str = Field(description='ticket id')
    gate: Gate = Field(description='gate kind')
    note: str = Field("", description="the answerer's question, plain words; blank is refused "
                                      "unless the workflow gate declares one")


class GateAnswerArgs(Args):
    ticket_id: str = Field(description='ticket id')
    gate: Gate = Field(description='gate kind')
    answer: str = Field(description='the decision')


class GatesArgs(Args):
    ticket_id: str = Field(description='ticket id')


def _message_send(a: MessageSendArgs) -> dict[str, Any]:
    return _receipt(_once("message_send", a, lambda: get_client().message_send(
        ticket_id=a.ticket_id, kind=a.kind, text=a.text, to=a.to, reply_to=a.reply_to, artifacts=a.artifacts,
        code_context=a.code_context, quotes=a.quotes)), ("text",), _msg_ref)


def _message_row(r: dict[str, Any]) -> dict[str, Any]:
    return tool_paging.pick(r, ("id", "seq", "kind", "created_by", "to", "ticket_id", "reply_to", "created_at",
                                "quoted", "text", "artifacts", "code_anchor"),
                            {"text": 240, "quoted": 960, "code_anchor": 400})


def _message_query(a: MessageQueryArgs) -> dict[str, Any]:
    filters = _filters(a)
    try:
        since = tool_paging.decode_cursor(a.cursor, filters).get("s", a.since_seq)
    except tool_paging.CursorError as e:
        return tool_paging.cursor_error("message_query", e)
    limit = max(1, min(a.limit or 20, tool_paging.MAX_LIMIT))
    resp = get_client().message_query(ticket_id=a.ticket_id, to=a.to, kind=a.kind, limit=limit,
                                      since_seq=since, created_by=a.created_by)
    if not resp.get("ok"):
        return resp
    rows = resp.get("value") or []
    value = tool_paging.seq_page("message_query", rows, filters=filters, limit=limit, verbose=a.verbose,
                                 project=_message_row, full="message_read(id) for a whole body, or verbose=true",
                                 more_possible=since is not None and len(rows) >= limit)
    if since is None and len(rows) >= limit:  # a full newest page: older messages may exist
        value["page"]["older"] = "this is the newest page; since_seq=0 pages the thread from the start"
    return {**resp, "value": value, "hint": tool_paging.seq_hint(value, "since_seq")}


def _message_read(a: MessageReadArgs) -> dict[str, Any]:
    return get_client().message_read(a.id)


def _gate_open(a: GateOpenArgs) -> dict[str, Any]:
    return get_client().gate_open(a.ticket_id, a.gate, note=a.note)


def _gate_answer(a: GateAnswerArgs) -> dict[str, Any]:
    return get_client().gate_answer(a.ticket_id, a.gate, a.answer)


def _gates(a: GatesArgs) -> dict[str, Any]:
    return get_client().gates(a.ticket_id)


THREAD_TOOLS = [
    ToolDef("message_send",
            'Post to a ticket thread: a participant/role/@handle, or a note',
            'milestones, blockers, questions, answers, hand-offs',
            "the message; asks reach the recipient's feed",
            MessageSendArgs, _message_send, "thread"),
    ToolDef("message_query",
            'List thread messages oldest first with seq; since_seq returns only newer ones',
            'to read or poll a thread',
            'the newest page (since_seq pages forward): items with text clipped to 240 chars, last_seq, next_cursor (a hint names older pages)',
            MessageQueryArgs, _message_query, "thread"),
    ToolDef("message_read",
            'Read one message with its seq, parent and replies',
            'when a feed event or reply_to names it',
            'the message',
            MessageReadArgs, _message_read, "thread"),
    ToolDef("gate_open",
            'Open a human gate on a ticket (one per gate at a time)',
            'when work needs a human decision',
            'the gate_opened event; the owner is notified',
            GateOpenArgs, _gate_open, "thread"),
    ToolDef("gate_answer",
            'Answer an open human gate (owner only)',
            'to resolve a gate a seat opened',
            'the gate_answered event',
            GateAnswerArgs, _gate_answer, "thread"),
    ToolDef("gates",
            "List a ticket's open gates",
            'to see if a ticket waits on a human',
            'the open gates',
            GatesArgs, _gates, "thread"),
]

# ============================================================================= board


class BoardArgs(Args):
    epic_id: str = Field(description='an epic, or any ticket under it')


class EventsQueryArgs(PageArgs):
    subject_id: str | None = None
    since: int = 0


class ParticipantsArgs(PageArgs):
    role: SeatRole | None = None
    type: ParticipantType | None = None  # type=human lists the people (T3 F4)


def _board(a: BoardArgs) -> dict[str, Any]:
    return get_client().board(a.epic_id)


def _events_query(a: EventsQueryArgs) -> dict[str, Any]:
    filters = _filters(a)
    try:
        since = tool_paging.decode_cursor(a.cursor, filters).get("s", a.since)
    except tool_paging.CursorError as e:
        return tool_paging.cursor_error("events_query", e)
    limit = max(1, min(a.limit or tool_paging.DEFAULT_LIMIT, tool_paging.MAX_LIMIT))
    resp = get_client().events_query(subject_id=a.subject_id, since=since, limit=limit)
    if not resp.get("ok"):
        return resp
    rows = resp.get("value") or []

    def row(r: dict[str, Any]) -> dict[str, Any]:
        out = tool_paging.pick(r, ("seq", "id", "kind", "subject_id", "created_by", "created_at"))
        if r.get("data"):
            out["data"] = tool_paging.clip(json.dumps(r["data"], default=str), 200)
        return out

    value = tool_paging.seq_page("events_query", rows, filters=filters, limit=limit, verbose=a.verbose,
                                 project=row, full="verbose=true", more_possible=len(rows) >= limit)
    return {**resp, "value": value, "hint": tool_paging.seq_hint(value, "since")}


def _participants(a: ParticipantsArgs) -> dict[str, Any]:
    c = get_client()

    def reach(row: dict[str, Any]) -> dict[str, Any]:
        """One session read per row that may be shown, never the whole roster; inside the fit (T6 N3)."""
        if row.get("handle", "").startswith(("__", "wt-")):
            return {**row, "reach": "test fixture"}
        if row.get("type") == "human":
            return {**row, "reach": "person — message_send(to='@'+handle) reaches their inbox + Slack doorbell"}
        sq = c.session_query(participant_id=row.get("id"))
        states = [s.get("state") for s in (sq.get("value") or [])] if sq.get("ok") else []
        return {**row, "reach": ("live seat — a message wakes it now" if any(s in ("alive", "parked") for s in states)
                                 else "closed seat — post on its ticket thread; the next shell reads it at boot")}

    resp = _paged("participants", c.participants(role=a.role, type=a.type and a.type.value), a,
                  lambda r: tool_paging.pick(r, ("id", "type", "role", "handle", "admin", "retired")), "verbose=true",
                  enrich=reach)
    if not resp.get("ok"):
        return resp
    resp["hint"] = ("need a HUMAN review? pick the closest role match among type=human rows and "
                    "message_send(to='@'+handle, kind=question) — their Slack fires with a deep link. "
                    "A named person works the same: to='@name'")
    return resp


BOARD_TOOLS = [
    ToolDef("board",
            "An epic's ticket tree with status counts, ready/in_review lists and open gates",
            'for the whole epic at a glance',
            'the board view',
            BoardArgs, _board, "board"),
    ToolDef("events_query",
            'Read the event log by subject or since a seq',
            'to reconstruct or catch up on events',
            'matching events, a ≤8 KB page from `since` + last_seq, next_cursor',
            EventsQueryArgs, _events_query, "board"),
    ToolDef("participants",
            'List humans and seats, optionally by role, with @handle and reach',
            "to find a collaborator, then message_send(to='@'+handle)",
            'the roster as a ≤8 KB page + next_cursor; verbose=full rows',
            ParticipantsArgs, _participants, "board"),
]

# ============================================================================= pool


def _spawnable_roles() -> set[str]:
    """The built-in spawnable roles, read from the Standard workflow (S13). The tool's `role` is a built-in
    seat role; the board's spawn route re-checks against the target epic's pinned workflow."""
    from .workflow import STANDARD_ID, Workflow, BUILTIN_BUILDERS
    return Workflow(BUILTIN_BUILDERS[STANDARD_ID]()).spawnable


class SpawnArgs(Args):
    role: SpawnRole = Field(description='seat role')
    ticket_id: str | None = Field(default=None, description="registers and assigns '<role>.<ticket_id>'")
    participant_id: str | None = Field(default=None, description='explicit pool handle; omit with ticket_id')
    parent_session: str | None = Field(default=None, description='spawning session id')
    assign: bool | None = Field(default=None, description='default: only if unassigned/dead; false = checker; true = take over')
    model: str | None = Field(default=None, description="seat or model id; default: epic tag")
    effort: SeatEffort | None = Field(default=None, description="default: epic tag; Claude caps at medium")
    mode: SpawnMode | None = None


class ResumeArgs(Args):
    participant_id: str = Field(description='seat id')


class InboxArgs(Args):
    pass


class RecordStatusArgs(Args):
    status: StatusValue = Field(description='your outcome')
    note: str = Field(default="", description='one line: done / left')
    to: str | None = Field(default=None, description='an extra recipient')
    ticket_id: str | None = Field(default=None, description='omit on a per-ticket seat')


class CloseSelfArgs(Args):
    pass


class ReapArgs(Args):
    participant_id: str = Field(description='seat id')


class SessionQueryArgs(PageArgs):
    participant_id: str | None = None
    ticket_id: str | None = None
    state: SessionState | None = None


def _pool_call(fn_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        from . import pool_adapter
    except ImportError:
        return unavailable("pool adapter not importable", "pool adapter not configured")
    fn = getattr(pool_adapter, fn_name, None)
    if fn is None:
        return unavailable(f"pool adapter has no {fn_name}()", "pool adapter not configured")
    return fn(**kwargs)


def _pool_caller_check(c: BoardClient, tk: dict[str, Any] | None, pid: str | None) -> dict[str, Any] | None:
    """S-ADV finding 2 (spawn) and adversary 09-23 #1 (reap): the tool binds the caller like REST — the owner
    operates any seat, an architect only seats in its own epic (the target's epic, from the ticket or the
    handle), every other role is refused; the board's whoami is the identity, never the endpoint's role."""
    me = c.whoami()
    if not me.get("ok"):
        return me
    mine = (me.get("value") or {}).get("participant") or {}
    my_role = str(mine.get("role") or "")
    if my_role == "owner":
        return None
    if my_role != "architect":
        return {"ok": False, "error": {"code": "scope",
                                       "message": f"role {my_role!r} may not operate the pool control plane"},
                "hint": "the owner or the epic's architect spawns and reaps seats"}
    target = _epic_id(c, tk) if tk else None
    for tid in (spawn_ticket_of(c, pid) if target is None and pid else []):
        got_e = c.ticket_read(tid)
        v = got_e.get("value") if got_e.get("ok") else None
        target = _epic_id(c, v.get("ticket", v)) if isinstance(v, dict) else None
        if target:
            break
    my_epics = set()
    for tid in (me.get("value") or {}).get("tickets") or []:
        got_m = c.ticket_read(tid)
        v = got_m.get("value") if got_m.get("ok") else None
        e = _epic_id(c, v.get("ticket", v)) if isinstance(v, dict) else None
        if e:
            my_epics.add(e)
    if "." in str(mine.get("id") or ""):
        my_epics.add(str(mine["id"]).split(".", 1)[1])
    if not target or target not in my_epics:
        return {"ok": False, "error": {"code": "scope",
                                       "message": f"architect {mine.get('id')!r} may only operate seats in its "
                                                  f"own epic" + (f" (target epic {target})" if target else
                                                                  "; target epic could not be resolved")},
                "hint": "pass ticket_id in your epic"}
    return None


SPAWN_TICKET_ENV = "EDP_SPAWN_TICKET"


def spawn_ticket_of(c: BoardClient, pid: str) -> list[str]:
    """The ticket(s) a seat was spawned for, most authoritative first (pain p-a05affa0: a custom
    participant_id is not '<role>.<ticket>', so its handle suffix names no ticket):
    1. the ticket the spawn recorded in the pool session's env (EDP_SPAWN_TICKET);
    2. the board's session rows for the seat (newest first);
    3. tickets the seat is assigned;
    4. the handle suffix (the '<role>.<ticket>' convention).
    Only resolves WHICH epic the seat belongs to — the caller's authority check is unchanged."""
    out: list[str] = []

    def add(t: Any) -> None:
        if isinstance(t, str) and t and t not in out:
            out.append(t)

    pool = _pool_call("sessions", {})
    rows = pool.get("value") if pool.get("ok") else None
    rows = rows.get("sessions", []) if isinstance(rows, dict) else (rows or [])
    for r in reversed([r for r in rows if isinstance(r, dict) and pid in (r.get("handle"), r.get("participant_id"))]):
        add(((r.get("spawn_settings") or {}).get("env") or {}).get(SPAWN_TICKET_ENV))
    sq = c.session_query(participant_id=pid)
    for r in _newest_first(sq.get("value") if sq.get("ok") else []):
        add(r.get("ticket_id"))
    tq = c.ticket_query(assignee=pid)
    for r in (tq.get("value") or []) if tq.get("ok") else []:
        add(r.get("id"))
    if "." in pid:
        add(pid.split(".", 1)[1])
    return out


def _spawn(a: SpawnArgs) -> dict[str, Any]:
    args = a.model_dump()
    ticket_id = args.pop("ticket_id", None)
    pid = args.pop("participant_id", None)
    if not pid and not ticket_id:
        return {"ok": False, "error": {"code": "schema", "message": "spawn needs ticket_id or participant_id"},
                "hint": "spawn(role=engineer, ticket_id=<story>) registers engineer.<story> and assigns it"}
    c = get_client()
    assign_flag = args.pop("assign", None)
    if not pid:
        pid = f"{a.role.value}.{ticket_id}"
    why = non_agent_refusal(a.role.value, pid)
    if why:  # owner m-da9a2ae62f: a person's role is never launched, whatever the handle
        return {"ok": False, "error": {"code": "scope", "message": why},
                "hint": "spawn an agent role: architect, engineer, qa, adversary, sme or doctor"}
    spawnable = _spawnable_roles()
    if a.role.value not in spawnable:  # S-ADV finding 1 on the tool path
        return {"ok": False, "error": {"code": "scope", "message": f"a {a.role.value} seat is not spawned"},
                "hint": f"spawnable roles: {sorted(spawnable)}"}
    tk = None
    if ticket_id:
        got_t = c.ticket_read(ticket_id)
        if not got_t.get("ok"):
            return got_t
        tk = got_t["value"].get("ticket", got_t["value"]) if isinstance(got_t["value"], dict) else None
    refused = _pool_caller_check(c, tk, pid)
    if refused:
        return refused
    # the architect is RESIDENT per epic: while architect.<epic> is up, a second architect seat on one
    # of its stories only steals the assignment — message the resident instead (the owner included;
    # qa full run on bb17851 caught this check indented under the architect-only branch)
    if a.role.value == "architect" and tk and tk.get("kind") != "epic":
        epic_id = _epic_id(c, tk)
        resident = _resident_architect(c, epic_id) if epic_id else None
        if resident and resident != pid:
            live = c.session_query(participant_id=resident)
            if live.get("ok") and any(r.get("state") in ("alive", "parked") for r in live.get("value") or []):
                return {"ok": False, "error": {"code": "conflict",
                                               "message": f"resident architect {resident} is up"},
                        "hint": f"message_send(ticket_id={ticket_id!r}, to='architect', kind='question') "
                                "reaches it; it answers without taking the ticket over"}
    got = c.participant_get(pid)
    if not got.get("ok"):
        made = c.participant_create("agent", a.role.value, pid, id=pid)
        if not made.get("ok"):
            return made
    assignee_kept = None
    if ticket_id and tk is not None:
        # A checker is never assigned a ticket whose criteria it checks (the doer guard would
        # block its verdicts). But a checker CAN be the doer of a ticket checked by someone
        # else — e.g. an adversary doing a review-type story whose criteria are checked by qa.
        assign = True
        if a.role.value in ("qa", "adversary"):
            # S-ADV finding 3: the same checker-never-doer rule the board enforces on ticket_update — an
            # adversary may do a review-type ticket none of whose criteria it checks; qa never takes one
            crits = c.criterion_query(ticket_id)
            rows = crits.get("value") or []
            checks = any(x.get("checked_by") == a.role.value for x in rows)
            assign = a.role.value == "adversary" and tk.get("work_type") == "review" and not checks
        current = tk.get("assignee")
        if assign_flag is False:
            assign = False
        elif assign_flag is None and current and current != pid:
            # never displace a LIVE assignee (2026-09-05 pain: a respawned advisor stole a
            # story mid-work); a dead one is replaced only by the same role
            live = c.session_query(participant_id=current)
            alive = live.get("ok") and any(r.get("state") in ("alive", "parked") for r in live.get("value") or [])
            same_role = current.split(".", 1)[0] == a.role.value
            assign = (not alive) and same_role
        if assign and current != pid:
            assigned = c.ticket_update(ticket_id, assignee=pid)
            if not assigned.get("ok"):
                return assigned
        elif current and current != pid:
            assignee_kept = current
    args["participant_id"] = pid
    if not args.get("parent_session"):  # lineage: the pool records who spawned this shell
        args["parent_session"] = my_session_id()
    # owner m-2d7ef9243d: a spawn without its own model/effort inherits the EPIC's seat choice
    # (seat-model / seat-effort tags on the epic ticket — see seat_choice.py); Claude high → medium.
    epic_tags: list[str] = []
    if tk is not None:
        epic_tk = tk
        if tk.get("kind") != "epic":
            eid = _epic_id(c, tk)
            got_e = c.ticket_read(eid) if eid else None
            v = (got_e or {}).get("value") if (got_e or {}).get("ok") else None
            epic_tk = (v.get("ticket", v) if isinstance(v, dict) else {}) or {}
        epic_tags = list(epic_tk.get("tags") or [])
    choice = seat_choice.resolve(args.get("model"), args.get("effort"), epic_tags, _edp8_home(),
                                 role=str(args.get("role") or "") or None)
    why = seat_choice.unknown_model(str(args.get("role") or ""), choice.model, _edp8_home())
    if why:  # S-ADV finding 10
        return {"ok": False, "error": {"code": "invalid", "message": why},
                "hint": "pick an id from models() / GET /v1/models for that role"}
    args["model"], args["effort"] = choice.pool_model, choice.effort
    # C8 (s-a4fd5df319): this tool calls the pool directly, so it must carry the seat's EDP8_TOKEN like
    # POST /v1/sessions/spawn does — a token-less seat 401s in public mode. Fail closed: no token, no spawn.
    minted = c.seat_token(pid, ticket_id, model=choice.model)
    if not minted.get("ok"):
        return minted
    args["env"] = dict((minted.get("value") or {}).get("env") or {})
    if ticket_id:  # the spawn ticket rides on the pool session, so reap resolves a custom id's epic
        args["env"][SPAWN_TICKET_ENV] = ticket_id
    if not args["env"]:
        args.pop("env")
    out = _pool_call("spawn", args)
    if not out.get("ok") and "lock" in str(out.get("error", "")).lower():
        # board said dead, pool lock says staffed (pain 2026-09-01 11:19) — resolve with the
        # pool's own liveness: a dead holder is reaped and the spawn retried ONCE; a live one
        # means the seat is genuinely staffed and the caller gets the truth.
        live = _pool_call("liveness", {"participant_id": pid})
        state = (live.get("value") or {}).get("state") if live.get("ok") else None
        if state == "dead":
            _pool_call("reap", {"participant_id": pid})
            out = _pool_call("spawn", args)
        elif state in ("alive", "parked"):
            return {"ok": False, "error": {"code": "conflict",
                                           "message": f"{pid} is already staffed (shell {state})"},
                    "hint": "message the seat instead of spawning; reap it first if it is truly stuck"}
    if out.get("ok") and isinstance(out.get("value"), dict):
        out["value"]["participant_id"] = pid
        out["value"]["seat_choice"] = choice.as_dict()
        out["value"]["closing"] = "the seat records status to you (record_status) and closes itself (close_self)"
        if assignee_kept:
            out["value"]["assignee_kept"] = assignee_kept
            out["hint"] = (out.get("hint") or "") + f"; {ticket_id} stays assigned to {assignee_kept} " \
                          "(pass assign=true to take it over)"
    return out


def _resident_architect(c: BoardClient, epic_id: str) -> str:
    """The epic's resident architect as the board resolves it (Board.resident_architect: the live
    architect assignee, else architect.<epic>); the convention when the board predates the field."""
    got = c.board(epic_id)
    arch = (got.get("value") or {}).get("architect") if got.get("ok") else None
    return (arch or {}).get("id") or f"architect.{epic_id}"


def _epic_id(c: BoardClient, tk: dict[str, Any]) -> str | None:
    """Walk parent_id up to the epic via ticket_read (bounded)."""
    cur = tk
    for _ in range(8):
        if cur.get("kind") == "epic":
            return cur.get("id")
        if not cur.get("parent_id"):
            return None
        got = c.ticket_read(cur["parent_id"])
        if not got.get("ok"):
            return None
        v = got["value"]
        cur = v.get("ticket", v) if isinstance(v, dict) else {}
    return None


def _inbox(_: InboxArgs) -> dict[str, Any]:
    out = get_client().inbox()
    if out.get("ok"):
        rows = out.get("value") or []
        out["hint"] = ("inbox clear — nothing addressed to you awaits an answer" if not rows else
                       f"{len(rows)} item(s) await you: answer each with its answer_with call, "
                       "act on steers, then call inbox() again until clear")
    return out


def _record_status(a: RecordStatusArgs) -> dict[str, Any]:
    return get_client().record_status(a.status.value, note=a.note, to=a.to, ticket_id=a.ticket_id)


def _close_self(_: CloseSelfArgs) -> dict[str, Any]:
    """The self-asserted close: refuse with everything still owed in ONE structured error,
    else release this shell's pool session synchronously with an honest reason."""
    client = get_client()
    me = client.participant
    if not me:
        return {"ok": False, "error": {"code": "identity", "message": "no participant identity"},
                "hint": "EDP8_PARTICIPANT/EDP_HANDLE unset; ask the owner to reap you"}
    chk = client.close_check()
    if not chk.get("ok"):
        chk["hint"] = (chk.get("hint") or "") + " | board unreachable: end your turn and stop calling tools; " \
                      "the SessionEnd hook releases your pool session"
        return chk
    inbox = chk["value"].get("inbox") or []
    status = chk["value"].get("status")
    owed: list[str] = []
    if inbox:
        owed.append(f"{len(inbox)} message(s) await you: " + "; ".join(
            f"{m.get('id')} ({m.get('kind')} from {m.get('created_by')}): {(m.get('text') or '')[:80]}"
            for m in inbox))
    if not status:
        owed.append("no status recorded yet")
    if chk["value"].get("resident"):  # S-SME-SURFACE: a topic's sme is resident until the owner closes it
        owed.append(chk["value"]["resident"])
    if owed:
        return {"ok": False,
                "error": {"code": "precondition", "message": " | ".join(owed)},
                "value": {"inbox": inbox, "status": status},
                "hint": "sequence: inbox() → answer/act on each → record_status(status=...) → close_self()"}
    reason = f"closed by self: {status.get('status')}"
    out = _pool_call("release_self", {"participant_id": me, "reason": reason})
    if not out.get("ok"):
        out["hint"] = (out.get("hint") or "") + " | fallback: end your turn and stop calling tools; " \
                      "the SessionEnd hook releases your pool session, and the owner can reap you"
    return out


def _resume(a: ResumeArgs) -> dict[str, Any]:
    return _pool_call("resume", a.model_dump())


def _reap(a: ReapArgs) -> dict[str, Any]:
    refused = _pool_caller_check(get_client(), None, a.participant_id)  # adversary 09-23 #1
    if refused:
        return refused
    return _pool_call("reap", a.model_dump())


def _session_row(r: dict[str, Any]) -> dict[str, Any]:
    return tool_paging.pick(r, ("id", "participant_id", "ticket_id", "state", "updated_at", "reason"),
                            {"reason": 120})


def _newest_first(v: Any) -> list[Any]:
    return sorted(v or [], key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""), reverse=True)


def _session_query(a: SessionQueryArgs) -> dict[str, Any]:
    resp = get_client().session_query(participant_id=a.participant_id, ticket_id=a.ticket_id, state=a.state)
    return _paged("session_query", resp, a, _session_row, "verbose=true", rows_of=_newest_first)


# Bounded (§19 rule 4): a pool call that hangs must not block the tool past the call cap.
# The work keeps going in a background thread; the caller gets a {status:"running"} pointer.

def _spawn_bounded(a: SpawnArgs) -> dict[str, Any]:
    return _bounded("spawn", lambda: _spawn(a),
                    {"ok": True, "value": {"status": "running", "poll": "session_query"},
                     "hint": "spawn is still starting the shell (pool slow); the seat will boot and "
                             "record_status to you — poll session_query(participant_id=...)"})


def _resume_bounded(a: ResumeArgs) -> dict[str, Any]:
    return _bounded("resume", lambda: _resume(a),
                    {"ok": True, "value": {"status": "running", "poll": "session_query"},
                     "hint": "resume is still working (pool slow); poll session_query(participant_id=...)"})


def _reap_bounded(a: ReapArgs) -> dict[str, Any]:
    return _bounded("reap", lambda: _reap(a),
                    {"ok": True, "value": {"status": "running", "poll": "session_query"},
                     "hint": "reap is still working (pool slow); poll session_query(participant_id=...)"})


POOL_TOOLS = [
    ToolDef("inbox",
            'Questions and steers awaiting you, oldest first, each with answer_with',
            'first when woken, and step 1 of closing',
            'the list (empty = clear)',
            InboxArgs, _inbox, "pool"),
    ToolDef("record_status",
            'Record your outcome with a one-line note to your spawner, architect and owner',
            'at milestones and as step 2 of closing',
            'the message and who was told',
            RecordStatusArgs, _record_status, "pool"),
    ToolDef("close_self",
            'End your own shell now; refused while inbox is non-empty or no status is recorded',
            'step 3 of closing',
            'the release result; then stop calling tools',
            CloseSelfArgs, _close_self, "pool"),
    ToolDef("spawn",
            'Start a seat for a role on a ticket',
            'to delegate a story/task or spawn a checker',
            'the session, or status running (poll session_query)',
            SpawnArgs, _spawn_bounded, "pool"),
    ToolDef("resume",
            'Resume a parked or stalled session',
            'to wake a stalled seat',
            'the session, or running/unavailable',
            ResumeArgs, _resume_bounded, "pool"),
    ToolDef("reap",
            "Tear down a seat's shell (dead, or the resident architect at epic close)",
            'to clear a dead seat or close the architect after the epic',
            'confirmation, or running/unavailable',
            ReapArgs, _reap_bounded, "pool"),
    ToolDef("session_query",
            'List sessions by participant/ticket/state',
            'to check a seat is live',
            'matching sessions, newest first, a ≤8 KB page + next_cursor; verbose=full rows',
            SessionQueryArgs, _session_query, "pool"),
]

# ============================================================================= search


class FindArgs(Args):
    query: str = Field(description='words or a phrase (FTS + semantic)')
    k: int = 10
    types: str | None = Field(default=None, description='comma list of ticket,doc,message,criterion')
    epic_id: str | None = Field(default=None)


def _find(a: FindArgs) -> dict[str, Any]:
    return get_client().find(a.query, k=a.k, types=a.types, epic_id=a.epic_id)


SEARCH_TOOLS = [
    ToolDef("find",
            'Search tickets, criteria, docs and messages by words or meaning; hits carry ticket_id and epic_id',
            'to find something without its id',
            'ranked hits with snippets',
            FindArgs, _find, "search"),
]

# ============================================================================= knowledge (design-d2c4f39fc6)


class RecordDecisionArgs(CreateArgs):
    scope: str = Field(description='epic or ticket id it is in force for')
    text: str = Field(description='one sentence, <=240 chars')
    detail: str = Field(default="", description='why, <=1000 chars')
    replaces: list[str] = Field(default_factory=list,
                                description='older decision ids it supersedes')
    binding: bool | None = Field(default=None,
                                 description='true = always handed to seats in scope; omit to inherit')
    source: str | None = Field(default=None, description='message, doc or attachment id')
    domains: list[str] = Field(default_factory=list, description='domain checklist names')


class RecordClaimArgs(CreateArgs):
    scope: str = Field(description='epic or ticket id')
    text: str = Field(description='one sentence')
    basis: ClaimBasis = Field(default=ClaimBasis.assumption)
    evidence: list[str] = Field(default_factory=list,
                                description='attachment/check/commit ids; a fact needs these plus measured|ruled')
    source: str | None = Field(default=None, description='message or doc id')


class RecordLessonArgs(CreateArgs):
    # S-HARVEST: no field descriptions — record_lesson is back in every /learn seat's bundle and must
    # fit the tightest S20 surface budget; the tool description names the fields.
    domain: str = Field(description='domain name')
    topic: str = Field(description='short topic')
    text: str = Field(description='one sentence')
    evidence: list[str] = Field(default_factory=list)


class LookupArgs(Args):
    scope: str = Field(description='epic or ticket id (never crosses epics)')
    question: str | None = Field(default=None, description='plain words; or use id/path')
    id: str | None = Field(default=None, description='record/ticket/doc id to start from')
    path: str | None = Field(default=None, description='file path to start from')


def _record_decision(a: RecordDecisionArgs) -> dict[str, Any]:
    return _receipt(_once("record_decision", a, lambda: get_client().record_decision(
        a.scope, a.text, detail=a.detail, replaces=a.replaces, binding=a.binding, source=a.source,
        domains=a.domains)), ("text", "detail"), _record_ref)


def _record_lesson(a: RecordLessonArgs) -> dict[str, Any]:
    return _receipt(_once("record_lesson", a, lambda: get_client().record_lesson(a.domain, a.topic, a.text,
                                                                               evidence=a.evidence)),
                    ("text",), _record_ref)


def _record_claim(a: RecordClaimArgs) -> dict[str, Any]:
    return _receipt(_once("record_claim", a, lambda: get_client().record_claim(
        a.scope, a.text, basis=a.basis.value, evidence=a.evidence, source=a.source)), ("text",), _record_ref)


class WithdrawDecisionArgs(Args):
    decision_id: str = Field(description='decision id')
    reason: str = Field(default="", description='one line, <=240 chars')


class WithdrawClaimArgs(Args):
    claim_id: str = Field(description='claim id')
    reason: str = Field(default="", description='one line, <=240 chars')


class SetBindingArgs(Args):
    decision_id: str = Field(description='a live decision')
    binding: bool = Field(description='true = binding')
    reason: str = Field(default="", description='one line, <=240 chars')


class DenseSearchArgs(Args):
    scope: str = Field(description='epic or ticket id')
    question: str = Field(description='plain words')
    k: int = Field(default=10)


def _lookup(a: LookupArgs) -> dict[str, Any]:
    return get_client().lookup(a.scope, question=a.question, id=a.id, path=a.path)


def _set_binding(a: SetBindingArgs) -> dict[str, Any]:
    return get_client().set_binding(a.decision_id, a.binding, reason=a.reason)


def _dense_search(a: DenseSearchArgs) -> dict[str, Any]:
    return get_client().dense_search(a.scope, a.question, k=a.k)


def _withdraw_decision(a: WithdrawDecisionArgs) -> dict[str, Any]:
    return get_client().withdraw_decision(a.decision_id, reason=a.reason)


def _withdraw_claim(a: WithdrawClaimArgs) -> dict[str, Any]:
    return get_client().withdraw_claim(a.claim_id, reason=a.reason)


class TopicResearchArgs(Args):
    topic_id: str = Field(description='Library topic id')
    query: str | None = Field(default=None, description="search skills.sh")
    url: str | None = None  # one page to read; the description names its hosts (T6: bytes for `offset`, S20)
    offset: int | None = None  # with url: reads on from the kept page text (the reply's `next` names it)


class TopicProposeArgs(CreateArgs):
    topic_id: str = Field(description='Library topic id')
    title: str = Field(description='doc title')
    body_md: str = Field(description="what you distilled; the board prepends Source + fetched-at")
    source_url: str = Field(description="a URL topic_research fetched")
    doc_type: DocType = DocType.strategy_hl
    tags: list[str] | None = None
    proposes: str | None = Field(default=None, description="active doc id this is the next version of")


def _topic_research(a: TopicResearchArgs) -> dict[str, Any]:
    return get_client().topic_research(a.topic_id, query=a.query, url=a.url, offset=a.offset)


def _topic_propose(a: TopicProposeArgs) -> dict[str, Any]:
    return _receipt(_once("topic_propose", a, lambda: get_client().topic_propose(
        a.topic_id, a.title, a.body_md, a.source_url, doc_type=a.doc_type.value, tags=a.tags, proposes=a.proposes)),
        ("body_md",), _doc_ref, key="doc")


# S-SME-SURFACE: the resident sme of a Library topic browses through the board (bounded hosts, receipts)
TOPIC_TOOLS = [
    ToolDef("topic_research",
            "Search skills.sh or read one page for your Library topic (skills.sh, GitHub, the seed host only)",
            "a topic seat's research step, before proposing a doc",
            "search results, or ≤8 KB of page text plus the fetch receipt",
            TopicResearchArgs, _topic_research, "knowledge"),
    ToolDef("topic_propose",
            "File a proposed Library doc from a page topic_research fetched; the owner approves it",
            "after research, or to propose the next version of a topic doc",
            "the proposed doc with Source + fetched-at in its header",
            TopicProposeArgs, _topic_propose, "knowledge"),
]

# ============================================================================= doctor (S19)
# The Help seat's tools: reads of the board, pool, supervisor, logs and pain log (edp8.doctor), plus
# propose_fix, which files an inert proposal an admin approves (edp8.fixes). Nothing here changes state.


class NoArgs(Args):
    pass


class WhyStuckArgs(Args):
    ticket_id: str = Field(description="the ticket the person says is stuck")


class WorkflowCheckArgs(Args):
    ref: str = Field(description="workflow id or id@version, e.g. standard@1")


class DoctorLogsArgs(Args):
    service: str = Field(description="board|broker|pool|mcp|bridge|supervisor|update|update-run, or pool-logs/<name>; a wrong name lists the available logs")
    lines: int = Field(default=100, ge=1, le=500)


class ProposeFixArgs(CreateArgs):
    topic_id: str = Field(description="your help thread (the topic in your context)")
    action: dict[str, Any] = Field(description="{kind: service.restart|service.start|service.stop|pool.set_limits|"
                                               "gate.open|gate.answer|teammate.rotate_token|agent_token.revoke, "
                                               "...its fields}")
    effect: str = Field(description="what the fix will do, in one or two plain sentences")


def _doctor_get(what: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return get_client().doctor_read(what, params)


DOCTOR_TOOLS = [
    ToolDef("doctor_health", "Service health, the supervisor, package versions and pool reachability",
            "first, for any 'it is broken' report", "services + causes (named root causes with a fix and a guide)",
            NoArgs, lambda a: _doctor_get("health"), "doctor"),
    ToolDef("doctor_pool", "Pool liveness, sessions, caps and usage, saturated caps and queued spawns",
            "seats not spawning, false deaths, slow spawns", "the pool view + causes",
            NoArgs, lambda a: _doctor_get("pool"), "doctor"),
    ToolDef("doctor_feed_lag", "Per live seat: unread addressed messages, their age, last request and output",
            "a seat that does not answer or wake", "seats + causes", NoArgs, lambda a: _doctor_get("feed-lag"), "doctor"),
    ToolDef("doctor_dead_mail", "Broker publishes that had no recipient (publish_no_route)",
            "a message that never arrived", "the dead messages + causes",
            NoArgs, lambda a: _doctor_get("dead-mail"), "doctor"),
    ToolDef("why_stuck", "Why a ticket does not move: gates nobody can answer, a missing checker or doer seat, "
            "blockers, the next edges' missing preconditions, a full cap",
            "a stuck ticket, epic or gate", "the ticket's facts + causes",
            WhyStuckArgs, lambda a: _doctor_get(f"why-stuck/{a.ticket_id}"), "doctor"),
    ToolDef("workflow_check", "Validate a workflow version and walk its status graph (unreachable, dead ends)",
            "a stuck walk under a custom workflow, or a failed update compat check", "problems, walk + causes",
            WorkflowCheckArgs, lambda a: _doctor_get(f"workflow/{a.ref}"), "doctor"),
    ToolDef("doctor_pains", "Open pain records (tools or guides found wrong)",
            "to see whether a symptom is already known", "the open pains",
            NoArgs, lambda a: _doctor_get("pains"), "doctor"),
    ToolDef("doctor_logs", "A redacted log tail (secrets, user paths, emails and tokens scrubbed)",
            "after a health or pool cause names a service", "the tail, or the available logs",
            DoctorLogsArgs, lambda a: _doctor_get(f"logs/{a.service}", {"lines": a.lines}), "doctor"),
    ToolDef("propose_fix", "Propose ONE fix as an admin approval card showing the exact action; nothing runs "
            "until an admin approves, then the result is posted on your thread",
            "after the evidence names a root cause a listed action fixes", "the proposal and its card",
            ProposeFixArgs, lambda a: _once("propose_fix", a, lambda: get_client().propose_fix(
                a.topic_id, a.action, a.effect)), "doctor"),
]

KNOWLEDGE_TOOLS = [
    ToolDef("record_decision",
            'Record what is in force, why, and which decisions it replaces',
            'the moment a ruling or in-authority decision is made, before acting on it',
            'the decision',
            RecordDecisionArgs, _record_decision, "knowledge"),
    ToolDef("record_claim",
            'Record something stated but not yet shown, with basis and evidence',
            'when you assert something without attached proof',
            'the claim',
            RecordClaimArgs, _record_claim, "knowledge"),
    ToolDef("record_lesson",
            'Record a lesson: domain, topic, one sentence, evidence ids',
            '/learn or /harvest',
            'the lesson',
            RecordLessonArgs, _record_lesson, "knowledge"),
    ToolDef("lookup",
            'Current decisions, claims and lessons for a question, id or path in one epic (binding ones always)',
            'on resume or before acting, instead of trusting memory',
            'records, rendered body and receipt',
            LookupArgs, _lookup, "knowledge"),
    ToolDef("withdraw_decision",
            'Withdraw a decision with no successor; lookup never returns it again',
            'when a decision was wrong and nothing replaces it',
            'the withdrawn decision',
            WithdrawDecisionArgs, _withdraw_decision, "knowledge"),
    ToolDef("withdraw_claim",
            'Withdraw a claim with no successor; lookup never returns it again',
            'when a claim was superseded or wrong and nothing replaces it',
            'the withdrawn claim',
            WithdrawClaimArgs, _withdraw_claim, "knowledge"),
    ToolDef("set_binding",
            "Promote or demote a live decision's binding flag (architect/owner); audited",
            'when re-judging which decisions every seat must follow',
            'the decision',
            SetBindingArgs, _set_binding, "knowledge"),
    ToolDef("dense_search",
            "Diagnostic: dense-only cosine top-k over an epic's live records",
            'when diagnosing why lookup missed a record',
            'hits with cosine scores',
            DenseSearchArgs, _dense_search, "knowledge"),
]

# ============================================================================= ruleset


class AssembleRulesetArgs(Args):
    ticket_id: str | None = Field(default=None, description='use its linked strategy/domain docs (inherited up the chain)')
    doc_ids: list[str] | None = Field(default=None, description='explicit leaf doc ids instead')
    full: bool = Field(default=False, description='also inline constructive lines')


def _ruleset_leaves_for_ticket(c: BoardClient, ticket_id: str) -> list[str]:
    """Strategy/domain docs linked to the ticket, walking UP the parent chain
    (epic-level strategies serve every story) — epic-first so the general
    layers land before the story-specific ones."""
    chain: list[str] = []
    tid: str | None = ticket_id
    while tid:
        chain.append(tid)
        got = c.ticket_read(tid)
        tid = (got.get("value") or {}).get("parent_id") if got.get("ok") else None
    leaves: list[str] = []
    for t in reversed(chain):  # epic first
        for rel in (Relation.uses_strategy.value, Relation.uses_domain.value):
            links = c.link_query(from_id=t, relation=rel)
            for lk in links.get("value") or []:
                if lk["to_id"] not in leaves:
                    leaves.append(lk["to_id"])
    return leaves


def _assemble_ruleset(a: AssembleRulesetArgs) -> dict[str, Any]:
    from .ruleset import AssembleError, LayerDoc, assemble_ruleset

    c = get_client()
    leaves = list(a.doc_ids or [])
    if not leaves and a.ticket_id:
        leaves = _ruleset_leaves_for_ticket(c, a.ticket_id)
    if not leaves:
        return {"ok": False, "error": {"code": "not_found", "message": "no strategy/domain docs to assemble"},
                "hint": "link docs to the ticket (relation=uses_strategy|uses_domain) or pass doc_ids"}

    skipped: list[str] = []

    def load(doc_id: str) -> LayerDoc | None:
        got = c.doc_read(doc_id)
        if not got.get("ok"):
            return None
        v = got["value"]
        return LayerDoc(id=v["id"], title=v["title"], doc_type=v["doc_type"], body_md=v["body_md"],
                        tags=v.get("tags") or [])

    def readable(doc_id: str) -> bool:
        # S-LIBRARY: only an active doc is a layer — a proposed one is unapproved, a retired one out of
        # use; both are skipped like a dangling layer and named in skipped_layers
        got = c.doc_read(doc_id)
        return bool(got.get("ok")) and (got["value"].get("status") or "active") == "active"

    def extends_of(doc_id: str) -> list[str]:
        links = c.link_query(from_id=doc_id, relation=Relation.extends.value)
        out: list[str] = []
        for lk in links.get("value") or []:
            # a dangling/non-doc layer (legacy extends pointing at a ticket) is SKIPPED
            # loudly, never a hard failure that strips the checker of its whole brief
            if readable(lk["to_id"]):
                out.append(lk["to_id"])
            else:
                skipped.append(lk["to_id"])
        return out

    leaves2 = [x for x in leaves if readable(x)]
    skipped += [x for x in leaves if x not in leaves2]
    if not leaves2:
        return {"ok": False, "error": {"code": "not_found", "message": f"no readable leaf docs (skipped: {skipped})"},
                "hint": "re-link the ticket's uses_strategy/uses_domain to existing docs"}
    try:
        out = assemble_ruleset(load, extends_of, leaves2, full=a.full)
    except AssembleError as e:
        return {"ok": False, "error": {"code": "precondition", "message": e.instruction}, "hint": ""}
    hint = ("enforced is inlined (the adherence view a checker verifies); `index` lists each linked doc — "
            "doc_read(id) the ones your work touches for the constructive craft")
    if out.oversize:
        hint = f"OVERSIZE (~{out.approx_tokens} inlined tokens): the layering is a scoping defect — split it, don't truncate"
    value = out.model_dump(exclude_none=True)
    if a.ticket_id:  # S-IMPLICIT: the brief carries the ticket's recall hits (board-side, no model call)
        got = c.recall(a.ticket_id)
        if got.get("ok"):
            value["recall"] = got["value"]
    if skipped:
        value["skipped_layers"] = skipped
        hint += f"; NOTE: {len(skipped)} dangling layer(s) skipped: {skipped}"
    return {"ok": True, "value": value, "hint": hint}


RULESET_TOOLS = [
    ToolDef("assemble_ruleset",
            "Compose a ticket's layered ruleset from its strategy/domain docs: enforced lines inlined, each doc one index line",
            'at the start of a story/task, for your working brief',
            'enforced lines + a doc index (full adds constructive), or a cycle/missing-layer error',
            AssembleRulesetArgs, _assemble_ruleset, "ruleset"),
]

# ============================================================================= artifact


class ArtifactCreateArgs(CreateArgs):
    form: ArtifactForm = Field(description='artifact form')
    uri: str = Field(description='a uri, never a machine path')
    note: str = ""
    ticket_id: str | None = Field(default=None, description='link as produced')


class ArtifactUploadArgs(Args):
    path: str = Field(description='workspace file (HTTP policy: absolute, inside configured roots)')
    note: str = ""


class ArtifactReadArgs(Args):
    id: str = Field(description='artifact id')
    offset: int = 0  # text continuation: the next_offset a previous read returned


IMAGE_CAP_B = 3_750_000   # an inline image block at most this size (the model's per-image limit is ~5 MB)
TEXT_CAP_B = 6_000        # inline text per call; next_offset continues
_TEXT_TYPES = ("text/", "application/json", "application/xml", "application/x-yaml", "application/yaml",
               "image/svg+xml")  # an SVG is markup: read as text, never an image block
_IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")


def _artifact_create(a: ArtifactCreateArgs) -> dict[str, Any]:
    return _once("artifact_create", a, lambda: get_client().artifact_create(
        form=a.form, uri=a.uri, note=a.note, ticket_id=a.ticket_id))


def _artifact_read(a: ArtifactReadArgs) -> dict[str, Any]:
    """S23 (T1 coverage gap 2): metadata AND content in one call — an image as an inline image block (the MCP
    layer turns value.content.base64 into an ImageContent), text inline up to TEXT_CAP_B with next_offset."""
    import base64
    c = get_client()
    meta = c.artifact_read(a.id)
    if not meta.get("ok") or not isinstance(meta.get("value"), dict):
        return meta
    v = meta["value"]
    if not v.get("has_content"):
        return {**meta, "hint": "no stored file (a uri artifact): open its uri"}
    ctype = str(v.get("content_type") or "")
    if ctype in _IMAGE_TYPES:
        status, got_type, body = c.artifact_content(a.id)
        if status != 200:
            return {**meta, "hint": f"metadata only: content read answered {status}"}
        if len(body) > IMAGE_CAP_B:
            v["content"] = {"kind": "image", "mime": got_type or ctype, "bytes": len(body), "inline": False}
            return {**meta, "hint": f"image is {len(body)} bytes, over the {IMAGE_CAP_B}-byte inline cap: "
                                    "open value.uri in the board UI; nothing was inlined"}
        v["content"] = {"kind": "image", "mime": (got_type or ctype).split(";")[0], "bytes": len(body),
                        "base64": base64.b64encode(body).decode()}
        return {**meta, "hint": "the image is attached as an image block"}
    if ctype.startswith(_TEXT_TYPES) or ctype == "":
        status, got_type, body = c.artifact_content(a.id, start=a.offset, length=TEXT_CAP_B + 1)
        if status == 416:  # offset at or past the end
            body = b""
        elif status not in (200, 206):
            return {**meta, "hint": f"metadata only: content read answered {status}"}
        more = len(body) > TEXT_CAP_B
        chunk = body[:TEXT_CAP_B]
        text = chunk.decode("utf-8", errors="ignore")
        v["content"] = {"kind": "text", "mime": (got_type or ctype).split(";")[0], "offset": a.offset,
                        "text": text, **({"next_offset": a.offset + len(chunk)} if more else {})}
        return {**meta, "hint": "artifact_read(id, offset=next_offset) continues" if more else ""}
    v["content"] = {"kind": "binary", "mime": ctype, "inline": False}
    return {**meta, "hint": f"{ctype} is not inlined (image and text are): open value.uri in the board UI"}


ARTIFACT_TOOLS = [
    ToolDef("artifact_upload", 'Stage a workspace file (25 MB cap) as an artifact',
            'to attach a local file',
            'the staged artifact; message_send(artifacts=[id]) finalizes it',
            ArtifactUploadArgs, lambda a: get_client().artifact_upload(a.path, a.note), "artifact"),
    ToolDef("artifact_create",
            'Record a produced thing by uri, optionally linked to a ticket',
            'when you ship something the owner should see',
            'the artifact',
            ArtifactCreateArgs, _artifact_create, "artifact"),
    ToolDef("artifact_read",
            'Read one artifact with its content: an image inline, text inline (6 KB per call)',
            'when a ticket, message or link names it',
            'the artifact + content; text: next_offset continues via offset',
            ArtifactReadArgs, _artifact_read, "artifact"),
]

# ============================================================================= S23 framework tools
# One action-enum tool per capability (architect ruling m-fbd6ae40d3), each replacing a shell workaround the
# T1 audit found (report-e517e9e87e coverage gaps). Every action's required args are checked here and a miss
# names the arg, like a schema error.


def _need(tool: str, action: str, a: BaseModel, *names: str) -> dict[str, Any] | None:
    missing = [n for n in names if getattr(a, n) in (None, "")]
    if not missing:
        return None
    return {"ok": False, "error": {"code": "schema", "field": missing[0], "missing": missing,
                                   "message": f"{tool}(action={action!r}) needs {', '.join(missing)}"},
            "hint": f"pass {', '.join(missing)}; describe('{ALL_TOOLS_OBJECT.get(tool, tool)}') has the fields"}


ALL_TOOLS_OBJECT = {"pain": "pain", "workflow": "workflow", "teammate": "teammate"}


class PainArgs(Args):
    action: PainAction = Field(description='what to do')
    id: str | None = None
    q: str | None = None
    area: str | None = None
    status: str | None = None
    severity: PainSeverity | None = None
    symptom: str | None = None
    expected: str | None = None
    evidence: str | None = None
    workaround: str | None = None
    dup_of: str | None = None
    supersedes: str | None = None
    note: str | None = None
    cursor: str | None = None


def _pain(a: PainArgs) -> dict[str, Any]:
    c = get_client()
    if a.action == PainAction.query:
        resp = c.pain_query(status=a.status or "open", area=a.area, q=a.q)
        if not resp.get("ok"):
            return resp
        try:
            value = tool_paging.offset_page(
                "pain", list(resp.get("value") or []), filters={"status": a.status, "area": a.area, "q": a.q},
                limit=None, cursor=a.cursor, verbose=False, project=lambda r: r,
                full="pain(action='read', id=<id>)")
        except tool_paging.CursorError as e:
            return tool_paging.cursor_error("pain", e)
        return {**resp, "value": value, "hint": "newest first; narrow with q/area"}
    if a.action == PainAction.read:
        return _need("pain", "read", a, "id") or c.pain_read(a.id or "")
    if a.action == PainAction.file:
        missing = _need("pain", "file", a, "severity", "area", "symptom", "expected", "evidence")
        if missing:
            return missing
        return c.pain_file({k: (v.value if hasattr(v, "value") else v) for k, v in a.model_dump().items()
                            if k in ("severity", "area", "symptom", "expected", "evidence", "workaround",
                                     "dup_of", "supersedes") and v not in (None, "")})
    return _need("pain", "resolve", a, "id", "status") or c.pain_resolve(a.id or "", a.status or "",
                                                                        note=a.note or "")


class WorkflowArgs(Args):
    action: WorkflowAction = Field(description='what to do')
    ref: str | None = None
    new_id: str | None = None
    definition: dict | None = None
    full: bool = False
    cursor: str | None = None


def _workflow(a: WorkflowArgs) -> dict[str, Any]:
    c = get_client()
    act = a.action
    if act == WorkflowAction.list:
        resp = c.workflows()
        if not resp.get("ok"):
            return resp
        rows = resp.get("value") or []
        rows = rows.get("workflows", rows) if isinstance(rows, dict) else rows
        try:
            value = tool_paging.offset_page(
                "workflow", list(rows), filters={"action": "list"}, limit=None, cursor=a.cursor, verbose=False,
                project=lambda r: tool_paging.pick(r, ("ref", "id", "version", "status", "title", "pinned_by",
                                                       "duplicated_from")),
                full="workflow(action='read', ref=...)")
        except tool_paging.CursorError as e:
            return tool_paging.cursor_error("workflow", e)
        return {**resp, "value": value}
    if act == WorkflowAction.read:
        miss = _need("workflow", "read", a, "ref")
        if miss:
            return miss
        resp = c.workflow_read(a.ref or "")
        if not resp.get("ok") or not isinstance(resp.get("value"), dict):
            return resp
        v = dict(resp["value"])
        problems = v.pop("problems", [])
        if a.full:  # the definition as edit takes it, with the lint problems beside it
            return {**resp, "value": {"definition": v, "problems": problems},
                    "hint": "change definition, then workflow(action='validate'|'edit', definition=...)"}
        return {**resp, "value": {**_wf_summary(v), "problems": len(problems)},
                "hint": "summary; full=true returns the definition to edit"}
    if act == WorkflowAction.duplicate:
        return _need("workflow", "duplicate", a, "ref") or _wf_compact(c.workflow_duplicate(a.ref or "", a.new_id))
    if act == WorkflowAction.edit:
        return _need("workflow", "edit", a, "definition") or _wf_compact(c.workflow_save(a.definition or {}))
    if act == WorkflowAction.validate:
        return _need("workflow", "validate", a, "definition") or c.workflow_validate(a.definition or {})
    return _need("workflow", "publish", a, "ref") or _wf_compact(c.workflow_publish(a.ref or ""))


def _wf_summary(v: dict[str, Any]) -> dict[str, Any]:
    out = {k: v.get(k) for k in ("id", "version", "status", "title", "duplicated_from") if v.get(k) is not None}
    roles = v.get("roles")
    out["roles"] = sorted(roles) if isinstance(roles, dict) else roles
    out["bytes"] = tool_paging.nbytes(v)
    return out


def _wf_compact(resp: dict[str, Any]) -> dict[str, Any]:
    """A stored version comes back as its summary (the full definition is read(full=true)'s job)."""
    v = resp.get("value") if resp.get("ok") else None
    if isinstance(v, dict) and "roles" in v:
        return {**resp, "value": _wf_summary(v)}
    return resp


class TeammateArgs(Args):
    action: TeammateAction = Field(description='what to do')
    handle: str | None = None
    role: str | None = None
    admin: bool = False


def _teammate(a: TeammateArgs) -> dict[str, Any]:
    """Owner-only credential lifecycle over the admin Teammates routes (the board still requires an admin
    human's token there, so an agent seat is refused 403: registration never widens authority). A minted token is returned ONCE in
    this reply; the tool layer never logs it and the board records no secret in its events."""
    c = get_client()
    if a.action == TeammateAction.list:
        resp = c.teammates()
        if resp.get("ok") and isinstance(resp.get("value"), list):
            resp["value"] = [tool_paging.pick(r, ("handle", "role", "admin", "state", "retired", "last_seen"))
                             for r in resp["value"]]
        return resp
    miss = _need("teammate", a.action.value, a, "handle")
    if miss:
        return miss
    handle = (a.handle or "").lstrip("@")
    if a.action == TeammateAction.create:
        return c.teammate_create(handle, role=a.role or "owner", admin=a.admin)
    if a.action == TeammateAction.mint:
        out = c.teammate_action(handle, "rotate")
        if out.get("ok"):
            out["hint"] = ("shown ONCE: hand it to the teammate privately; it is not stored anywhere you can "
                           "read again — mint again to replace it")
        return out
    return c.teammate_action(handle, "revoke")


class HarvestCostArgs(Args):
    participant_id: str = Field(description='the seat')
    since: str | None = None
    until: str | None = None


FRAMEWORK_TOOLS = [
    ToolDef("pain",
            "Pain log: query (q, area, status=all), read (id), file (severity, area, symptom, expected, "
            "evidence; dup_of), resolve (id, status)",
            "a tool or guide is wrong versus reality; query first",
            'rows or the record',
            PainArgs, _pain, "framework"),
    ToolDef("workflow",
            "Owner: workflow versions: list, read (ref, full), duplicate (ref), edit|validate (definition), publish (ref)",
            'changing the workflow an epic pins',
            'the version or its problems',
            WorkflowArgs, _workflow, "framework"),
    ToolDef("teammate",
            "Owner: teammate credentials: list, create (handle: invite link), mint (handle: token shown once), revoke",
            'adding, re-keying or removing a person',
            'the teammate, invite or token',
            TeammateArgs, _teammate, "framework"),
    ToolDef("service_status",
            'Read-only host services: state, pid, port, git rev, uptime',
            'a service seems down; restarting is a human action',
            'one row per service',
            NoArgs, lambda a: get_client().services_status(), "framework"),
    ToolDef("harvest_cost",
            "A seat's harvest token cost from its transcript, plus records it wrote",
            'at epic acceptance, after the harvest',
            'window, token totals, record counts',
            HarvestCostArgs, lambda a: get_client().harvest_cost(a.participant_id, a.since, a.until), "framework"),
]

# ============================================================================= close


class CloseArgs(Args):
    epic_id: str = Field(description='epic id')


def _close(a: CloseArgs) -> dict[str, Any]:
    resp = get_client().board(a.epic_id)
    if not resp.get("ok"):
        return resp
    status = resp["value"]["epic"]["status"]
    if status not in ("done", "partial"):
        return {"ok": False, "error": {"code": "transition", "message": f"epic {a.epic_id} is {status}, not done/partial"},
                "hint": "close only after the epic reaches done or partial"}
    resident = (resp["value"].get("architect") or {}).get("id") or f"architect.{a.epic_id}"
    disarm = ["CronDelete <ids you armed>", "TaskStop <monitor>"]
    seat = get_client().session_query(participant_id=resident)
    rows = (seat.get("value") or []) if seat.get("ok") else []
    if any((r.get("state") in ("alive", "parked")) for r in rows):
        disarm.insert(0, f"reap(participant_id={resident!r}) — the resident architect never closes itself")
    return {"ok": True, "value": {"disarm": disarm},
            "hint": "epic is closed in the record; disarm your wiring"}


CLOSE_TOOLS = [
    ToolDef("close",
            'Confirm an epic is closed and get the disarm checklist',
            'as the owner, once an epic is done/partial',
            'the checklist, or a transition error',
            CloseArgs, _close, "close"),
]

# ============================================================================= registry

ALL_TOOLS: dict[str, ToolDef] = {
    t.name: t for t in (
        IDENTITY_TOOLS + TICKET_TOOLS + DOC_TOOLS + THREAD_TOOLS + BOARD_TOOLS + POOL_TOOLS
        + SEARCH_TOOLS + KNOWLEDGE_TOOLS + TOPIC_TOOLS + RULESET_TOOLS + ARTIFACT_TOOLS + CLOSE_TOOLS
        + DOCTOR_TOOLS + FRAMEWORK_TOOLS
    )
}

_IDENTITY = ["whoami", "preflight", "subscribe", "resume_self", "context", "context_delta", "describe", "describe_objects", "get_guide"]
_TICKET_RW = ["ticket_create", "ticket_read", "ticket_query", "ticket_update", "criterion_create",
              "criterion_query", "criterion_update"]
_TICKET_RO = ["ticket_read", "ticket_query", "ticket_update"]  # owner: sign-off only, guarded by the board
_CHECK = ["criterion_query", "criterion_update"]  # checkers record verdicts (board guards who may)
_DOC_RW = ["doc_create", "doc_read", "doc_query", "doc_update", "doc_edit", "link_create", "link_query", "link_delete"]
_DOC_RO = ["doc_read", "doc_query"]
_THREAD = ["message_send", "message_query", "message_read", "gate_open", "gate_answer", "gates"]
_BOARD = ["board", "events_query", "participants"]
_CLOSING = ["inbox", "record_status", "close_self"]

ROLE_BUNDLES: dict[str, list[str]] = {
    # The owner shell is the orchestrator: it spawns every seat (except SMEs —
    # the architect spawns those) and recovers dead ones. No coordinator seat.
    # Closing is a self-assertion (inbox → record_status → close_self). The owner (a human
    # shell) and the architect (RESIDENT for the epic's life; the owner reaps it at close)
    # never get close_self — every other seat does.
    Role.owner.value: _IDENTITY + _THREAD + _BOARD + _DOC_RO + _TICKET_RO + _CHECK
        + ["find", "ticket_create", "inbox", "spawn", "resume", "reap", "session_query", "close"],
    Role.architect.value: _IDENTITY + _TICKET_RW + _DOC_RW + _THREAD + _BOARD
        + ["find", "artifact_create", "artifact_read", "spawn", "inbox", "record_status",
           # owner m-268fc869f5 / m-faf46d284a (2026-09-18): the spawner decides and executes recovery of its
           # own seats (the board already scopes these to the architect's own epic, service._authorize_pool_op)
           "reap", "resume", "session_query"],
    Role.sme.value: _IDENTITY + _TICKET_RO + _DOC_RW + _THREAD
        + ["find", "participants", "assemble_ruleset", "criterion_query", "criterion_update",
           "artifact_create", "artifact_read", "topic_research", "topic_propose"] + _CLOSING,
    Role.engineer.value: _IDENTITY + _TICKET_RW + _DOC_RW + _THREAD
        + ["find", "participants", "assemble_ruleset", "artifact_create", "artifact_read"] + _CLOSING,
    Role.adversary.value: _IDENTITY + _TICKET_RW + _DOC_RW + _THREAD
        + ["find", "participants", "assemble_ruleset", "artifact_create", "artifact_read"] + _CLOSING,
    Role.qa.value: _IDENTITY + _TICKET_RO + _CHECK + _DOC_RW + _THREAD + _BOARD
        + ["find", "assemble_ruleset", "artifact_create", "artifact_read"] + _CLOSING,
    # S19: the Help seat is read-only — reads, its thread's messages, propose_fix (an inert proposal an admin
    # approves) and the kernel's communication tools; no ticket/doc/criterion/decision/gate/spawn write
    Role.doctor.value: _IDENTITY + ["ticket_read", "ticket_query", "criterion_query", "doc_read", "doc_query",
                                    "message_send", "message_query", "message_read", "gates", "participants",
                                    "events_query", "board", "find", "lookup"]
        + [t.name for t in DOCTOR_TOOLS] + _CLOSING,
}

#: S19: roles whose bundle is read-only; the loops below never add a write tool to them
READ_ONLY_ROLES = frozenset({Role.doctor.value})


for _role_tools in ROLE_BUNDLES.values():
    if "artifact_create" in _role_tools and "artifact_upload" not in _role_tools:
        # close_self must stay last: a doer's bundle ends inbox → record_status → close_self
        # (test_lifecycle_fixes.py::test_architect_and_owner_have_no_close_self). Insert
        # artifact_upload just before the closing triplet, never after close_self.
        if "close_self" in _role_tools:
            _role_tools.insert(_role_tools.index("inbox"), "artifact_upload")
        else:
            _role_tools.append("artifact_upload")

# S-ROLES: the retired coordinator and consultant roles have NO bundle (deleted, not aliased); a
# participant of a role without a bundle gets identity tools only (tools_for_role).

# record_decision/record_claim/lookup are available to EVERY role (design-d2c4f39fc6 §2: the tools
# any seat calls). Insert before the closing triplet where a doer has one — close_self stays last
# (test_lifecycle_fixes.py). A role that already has a name (none do) is not duplicated.
for _role, _role_tools in ROLE_BUNDLES.items():
    if _role in READ_ONLY_ROLES:  # S19: lookup is already there; the record_*/withdraw_*/set_binding writes are not
        continue
    _at = _role_tools.index("inbox") if "close_self" in _role_tools else len(_role_tools)
    for _kt in ("record_decision", "record_claim", "record_lesson", "lookup", "withdraw_decision", "withdraw_claim",
                "set_binding", "dense_search"):
        if _kt not in _role_tools:
            _role_tools.insert(_at, _kt)
            _at += 1


# S20 (s-b123a91d3f) token-cost trim: tools a role never invoked in 30 days of seat transcripts
# (scripts/measure_token_cost.py invoked) and that no role card or skill names. Every tool is still
# served to some role; a role that needs one back re-adds it here. The invariants above stay: the
# identity set, record_decision/record_claim/lookup everywhere, close_self last.
# preflight stays in every bundle (the advisory host check is every seat's)
_S20_UNUSED: dict[str, tuple[str, ...]] = {
    Role.owner.value: ("gate_open", "inbox", "dense_search", "record_lesson", "withdraw_decision",
                       "withdraw_claim", "set_binding"),
    Role.architect.value: ("artifact_read", "dense_search", "gate_answer", "withdraw_claim",
                           "withdraw_decision"),
    # gate_open stays: the quick-task engineer opens its design_signoff (s-ccdafcb229)
    Role.engineer.value: ("dense_search", "gate_answer", "gates", "link_delete",
                          "set_binding", "withdraw_claim"),
    Role.adversary.value: ("dense_search", "gate_answer", "link_delete",
                           "set_binding", "withdraw_claim", "withdraw_decision"),
    Role.qa.value: ("artifact_create", "artifact_upload", "dense_search", "doc_query", "events_query", "gate_answer",
                    "gate_open", "link_delete", "link_query", "set_binding", "ticket_query",
                    "withdraw_claim", "withdraw_decision"),
    Role.sme.value: ("artifact_create", "artifact_read", "artifact_upload", "dense_search", "doc_edit", "find",
                     "gate_answer", "gate_open", "gates", "link_delete", "set_binding",
                     "withdraw_claim", "withdraw_decision"),
}
for _role, _unused in _S20_UNUSED.items():
    ROLE_BUNDLES[_role] = [n for n in ROLE_BUNDLES[_role] if n not in _unused]


# S23 framework tools (architect ruling m-fbd6ae40d3): pain for every role (resolve is enforced by the board
# for the owner and the doctor); workflow + teammate owner only; service_status for owner/architect/doctor;
# harvest_cost for qa and the owner. close_self stays last.
_S23_FRAMEWORK: dict[str, tuple[str, ...]] = {
    Role.owner.value: ("pain", "workflow", "teammate", "service_status", "harvest_cost"),
    Role.architect.value: ("pain", "service_status"),
    Role.engineer.value: ("pain",),
    Role.adversary.value: ("pain",),
    Role.qa.value: ("pain", "harvest_cost"),
    Role.sme.value: ("pain",),
    Role.doctor.value: ("pain", "service_status"),
}
for _role, _add in _S23_FRAMEWORK.items():
    _role_tools = ROLE_BUNDLES[_role]
    _at = _role_tools.index("inbox") if "close_self" in _role_tools else len(_role_tools)
    for _kt in _add:
        if _kt not in _role_tools:
            _role_tools.insert(_at, _kt)
            _at += 1


from .workflow import KERNEL_TOOLS  # noqa: E402 - S13 §4.14(e).1: every spawned role carries these


def tools_for_role(role: str) -> list[ToolDef]:
    # a retired/unknown role never inherits the owner's tools; a workflow's custom role gets the identity
    # tools plus the kernel bundle, so its seat still boots, reports and closes (S13)
    names = ROLE_BUNDLES.get(role) or _IDENTITY + [k for k in KERNEL_TOOLS if k not in _IDENTITY]
    return [ALL_TOOLS[n] for n in names if n in ALL_TOOLS]
