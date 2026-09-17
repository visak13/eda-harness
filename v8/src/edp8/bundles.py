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
import contextvars
import enum as _enum
import os
import sys
import threading
import typing
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import AliasChoices, BaseModel, Field, ValidationError

from . import seat_choice
from .client import BoardClient
from .schemas import (
    ENUMS,
    ArtifactForm,
    Check,
    CheckedBy,
    ConsultModel,
    ConsultProfile,
    ConsultPurpose,
    DocType,
    Gate,
    MessageKind,
    Relation,
    Role,
    StatusValue,
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
    return _req_session.get() or os.environ.get("EDP_SPAWN_SESSION_ID") or None


def unavailable(message: str, hint: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": "unavailable", "message": message}, "hint": hint}


# ----------------------------------------------------------------------------- tool def


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
    return out


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
    parts = [f"{k} one of: {'|'.join(v)}" for k, v in ef.items()]
    return "Enum args — " + "; ".join(parts) + " (describe('enums') lists every enum). "


def compose_description(what: str, when: str, returns: str, args_model: type[BaseModel]) -> str:
    what = what.strip().rstrip(".") + "."
    when = when.strip().rstrip(".") + "."
    returns = returns.strip().rstrip(".") + "."
    return f"{what} When to call: {when} {_enum_clause(args_model)}Returns {returns}"


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
        return compose_description(self.what, self.when, self.returns, self.args_model)

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


def _validation_envelope(tool: ToolDef, exc: ValidationError) -> dict[str, Any]:
    err = exc.errors()[0]
    field = ".".join(str(x) for x in err.get("loc", ())) or "?"
    allowed = enum_fields(tool.args_model).get(field)
    error: dict[str, Any] = {"code": "schema",
                             "message": f"{tool.name}: invalid {field!r} — {err.get('msg')}",
                             "field": field}
    if allowed:
        error["allowed"] = allowed
    hint = (f"pass a valid {field}"
            + (f" — one of: {'|'.join(allowed)}" if allowed else "")
            + "; describe('enums') lists allowed values")
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
# rule 4). A tool that launches a process or waits on the pool (consult, spawn, resume,
# reap, preflight) runs its work in a daemon thread the server owns; if it does not finish
# within the cap the tool returns {status:"running", poll:...} and the work continues in the
# background. consult additionally wakes the caller with a consult_done thread note when a
# background run finishes (see _consult).


def _call_cap() -> float:
    try:
        return float(os.environ.get("EDP8_TOOL_CALL_CAP_S", "30"))
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


class SubscribeArgs(BaseModel):
    pass


class ContextArgs(BaseModel):
    ticket_id: str | None = Field(default=None, description="a specific ticket id, or omit for all your tickets")


class DescribeArgs(BaseModel):
    type: str = Field(description="object type (participant|ticket|criterion|doc|link|message|event|artifact|"
                      "session), or 'enums' to list every enum, or 'enum:<Name>' for one enum's allowed values")


class GetGuideArgs(BaseModel):
    name: str = Field(description="guide file name (without .md), e.g. 'design-template' or 'feed-format'")


class WhoamiArgs(BaseModel):
    pass


class PreflightArgs(BaseModel):
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
        from . import pool_adapter
        got = pool_adapter.sessions()
        rows = (got["value"] if isinstance(got.get("value"), list) else (got.get("value") or {}).get("sessions", [])) \
            if got.get("ok") else []
        live = [s for s in rows if s.get("state") in ("active", "starting", "resuming", "parked")]
        out["seats"] = {"live": len(live), "handles": sorted(s.get("handle") or "" for s in live)}
        cap = pool_adapter.capacity()
        if cap.get("ok"):
            out["seats"]["caps"] = cap["value"]
    except Exception as e:  # noqa: BLE001
        out["seats"] = {"note": f"pool unreachable: {type(e).__name__}"}
    try:
        from . import run_state
        out["services"] = run_state.snapshot()  # launcher-owned infra state, read-only (design §22 rule 4)
    except Exception as e:  # noqa: BLE001
        out["services"] = {"note": f"run-state unreadable: {type(e).__name__}"}
    try:
        from . import consult as consult_mod
        out["consult"] = consult_mod.lane_status()
        out["advisory"] = consult_mod.advisory()
    except Exception as e:  # noqa: BLE001
        out["consult"] = {"note": f"lane unreadable: {type(e).__name__}"}
    out["rules_of_thumb"] = {"claude_seat_mb": "250-500 (grows with context)", "codex_text_mb": "~300",
                             "codex_image_gen_mb": "up to ~1000", "stack_mb": "~500"}
    return {"ok": True, "value": out,
            "hint": "advisory, never a gate: compare host.free_mb with what you are about to start "
                    "(rules_of_thumb); consult.in_flight/queued is the fleet-wide codex lane; "
                    "a quota note means codex itself refused recently — you decide, and say why on the thread"}


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
        resp["value"]["bundles_available"] = ROLE_BUNDLES.get(role, [])
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


_LISTENING_ROLES = {"architect", "owner", "coordinator"}


def _heartbeat_prompt(participant: str) -> str:
    """The cron fallback text is role-aware: a listening seat idles on a quiet board, a doing
    seat resumes its plan. (2026-09-08: a role-blind "act only if new" prompt made an engineer
    with an unbuilt plan end every idle wake — m-0743c493b2.)"""
    role = participant.split(".", 1)[0]
    if role in _LISTENING_ROLES:
        return ("edp8 heartbeat: call context() and act only if something is new; "
                "if nothing, end the turn silently")
    return ("edp8 heartbeat: call context(); answer anything new, then RESUME THE NEXT UNBUILT ITEM of "
            "your plan doc — a quiet board is not a reason to stop. End the turn silently only when your "
            "ticket is in_review/done or you are blocked (post kind=blocked or deviation first).")


def _subscribe(_: SubscribeArgs) -> dict[str, Any]:
    client = get_client()
    py = sys.executable.replace("\\", "/")  # bash-safe: the Monitor tool runs bash, which eats backslashes
    monitor_cmd = f'"{py}" -m edp8.feed_driver --participant {client.participant} --board {client.base_url}'
    broker = os.environ.get("EDP_BROKER_URL")
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


def _context(args: ContextArgs) -> dict[str, Any]:
    return get_client().context(ticket_id=args.ticket_id)


_TOOLS_BY_TYPE: dict[str, list[str]] = {
    "ticket": ["ticket_create", "ticket_read", "ticket_query", "ticket_update", "find", "board", "spawn"],
    "criterion": ["criterion_create", "criterion_query", "criterion_update", "ticket_read"],
    "doc": ["doc_create", "doc_read", "doc_query", "doc_update", "link_create", "assemble_ruleset", "find"],
    "link": ["link_create", "link_query", "link_delete", "ticket_read"],
    "message": ["message_send", "message_query", "message_read", "inbox", "record_status", "find"],
    "event": ["events_query", "subscribe"],
    "artifact": ["artifact_create", "artifact_read"],
    "session": ["session_query", "spawn", "reap", "resume", "close_self"],
    "participant": ["participants", "whoami", "spawn"],
}


def _describe(args: DescribeArgs) -> dict[str, Any]:
    t = args.type
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
    out = get_client().describe(t)
    if out.get("ok"):
        out["value"]["tools"] = _TOOLS_BY_TYPE.get(t, [])
    return out


def _edp8_home() -> Path:
    return Path(os.environ.get("EDP8_HOME", str(Path(__file__).resolve().parents[2])))


def _get_guide(args: GetGuideArgs) -> dict[str, Any]:
    p = _edp8_home() / "guides" / f"{args.name}.md"
    if not p.is_file():
        return {"ok": False, "error": {"code": "not_found", "message": f"guide {args.name!r} does not exist"},
                "hint": f"guides live under {p.parent}"}
    return {"ok": True, "value": {"name": args.name, "body": p.read_text(encoding="utf-8")}, "hint": ""}


IDENTITY_TOOLS = [
    ToolDef("whoami",
            "Report your registered identity and which tool bundles your role has",
            "at boot, or whenever you need your handle, role, open tickets or lineage",
            "the participant record, its open tickets, the bundle list, and the server version",
            WhoamiArgs, _whoami, "identity"),
    ToolDef("preflight",
            "Read host free RAM, live seats vs the pool caps, the fleet-wide codex lane (in flight / "
            "queued), and any recent codex usage-cap note — idempotent, read-only, ADVISORY (it never blocks)",
            "before you spawn or consult, to weigh headroom yourself",
            "the numbers plus rules of thumb; a hint that it is advisory, never a gate",
            PreflightArgs, _preflight_bounded, "identity"),
    ToolDef("subscribe",
            "Arm your event feed for this session (one-time setup)",
            "once, at boot, right after whoami",
            "the monitor command to run and the heartbeat cron to create",
            SubscribeArgs, _subscribe, "identity"),
    ToolDef("context",
            "Load everything needed to act on your ticket(s): chain, criteria, docs, thread, open asks",
            "at boot after subscribe, and whenever a feed event says your ticket changed",
            "one context block per ticket, plus any unanswered questions addressed to you",
            ContextArgs, _context, "identity"),
    ToolDef("describe",
            "Look up an object type's shape and one-line contract, or an enum's allowed values "
            "(type='enums' lists every enum, type='enum:<Name>' returns one)",
            "when you are unsure of a type's fields or a strict argument's allowed values",
            "the JSON schema and contract text for a type, or the values for an enum",
            DescribeArgs, _describe, "identity"),
    ToolDef("get_guide",
            "Fetch one on-demand reference page (a template, a format spec)",
            "when a task points you at a named guide, e.g. get_guide('tools')",
            "the guide's markdown body, or not_found if no such guide exists",
            GetGuideArgs, _get_guide, "identity"),
]

# ============================================================================= ticket


class TicketCreateArgs(BaseModel):
    kind: TicketKind = Field(description="epic (owner/coordinator) | story (architect) | task (engineer/architect)")
    work_type: WorkType = Field(description="feature|bug|rnd|creative|review|knowledge|chore")
    title: str = Field(description="epic: the owner's words verbatim; the board keeps them in `words` and derives "
                       "a short title (<=80 chars) from the first clause. story/task: names the slice")
    words: str | None = Field(default=None, description="epic only: the owner's verbatim request, if given "
                              "separately from a short title; immutable after create")
    parent_id: str | None = Field(default=None, description="required for story/task: the parent ticket id")
    assignee: str | None = Field(default=None, description="participant id to assign, if known now")
    description: str = Field(default="", description="the slice in prose: scope, intent, pointers to files/docs "
                             "— searchable by find and ticket_query(q=)")
    tags: list[str] | None = Field(default=None, description="free labels for filtering (ticket_query(tag=))")


class TicketReadArgs(BaseModel):
    ticket_id: str = Field(description="ticket id", validation_alias=AliasChoices("ticket_id", "id"))
    include: str | None = Field(default=None, description="comma list to narrow: chain,criteria,docs,children,"
                                "blockers,gates,thread,links — omit for everything")
    thread_limit: int = Field(default=20, ge=0, le=200,
                              description="how many of the newest thread messages to include (0 = none, max 200)")


class TicketQueryArgs(BaseModel):
    kind: TicketKind | None = Field(default=None, description="epic|story|task")
    work_type: WorkType | None = None
    parent_id: str | None = None
    status: TicketStatus | None = Field(default=None, description="drafted|designed|signed_off|ready|in_progress|"
                                        "in_review|blocked|done|partial|dropped")
    assignee: str | None = None
    epic_id: str | None = Field(default=None, description="every ticket under this epic (any depth)")
    created_by: str | None = None
    tag: str | None = Field(default=None, description="tickets carrying this tag")
    q: str | None = Field(default=None, description="words to match in title/description/tags (exact-word search)")


class TicketUpdateArgs(BaseModel):
    ticket_id: str = Field(description="ticket id", validation_alias=AliasChoices("ticket_id", "id"))
    status: TicketStatus | None = Field(default=None, description="a legal next status: drafted→designed→signed_off→"
                                        "ready→in_progress→in_review→done (or blocked/partial/dropped); the "
                                        "transition guard names what is missing")
    assignee: str | None = Field(default=None, description="participant id to assign")
    design_ref: str | None = Field(default=None, description="doc id of the design/plan doc")
    description: str | None = Field(default=None, description="replace the description (creator/assignee/architect/owner)")
    tags: list[str] | None = Field(default=None, description="replace the tag list")
    title: str | None = Field(default=None, description="a short human title (<=80 chars) for an epic or a story "
                              "(architect/owner); an epic's words stay verbatim")


class CriterionCreateArgs(BaseModel):
    ticket_id: str
    text: str = Field(description="a checkable definition of done")
    check: Check = Field(description="command|path|look|verdict")
    checked_by: CheckedBy | None = Field(default=None, description="IGNORED (accepted for one release): "
                                         "the board DERIVES the checker from the ticket — qa for every "
                                         "story/task/epic criterion, reviewer only when a story is tagged "
                                         "review_required, owner for a knowledge ticket. The owner may "
                                         "override by ALSO passing override_reason")
    override_reason: str | None = Field(default=None, description="owner-only: a reason to override the "
                                        "derived checker (recorded as a criterion_checker_overridden event)")


class CriterionQueryArgs(BaseModel):
    ticket_id: str


class CriterionUpdateArgs(BaseModel):
    model_config = {"extra": "forbid"}  # an unknown kwarg is an ERROR, never a silent drop
    id: str = Field(description="criterion id")
    evidence_ref: str | None = Field(default=None, description="doc id (a report) proving the check")
    verdict: Verdict | None = Field(default=None, description="pending|pass|fail — set after evidence_ref")
    text: str | None = Field(default=None, description="reword the criterion (authors only, while verdict pending)")
    evidence_version: int | None = Field(default=None,
        description="the doc version this verdict signed off (§14); refused if below the doc's current version")
    stale_ok: bool = Field(default=False, description="sign the version you read even if the doc has since moved on")


def _ticket_create(a: TicketCreateArgs) -> dict[str, Any]:
    return get_client().ticket_create(kind=a.kind, work_type=a.work_type, title=a.title,
                                      parent_id=a.parent_id, assignee=a.assignee, description=a.description,
                                      tags=a.tags, words=a.words)


def _ticket_read(a: TicketReadArgs) -> dict[str, Any]:
    return get_client().ticket_read(a.ticket_id, include=a.include, thread_limit=a.thread_limit)


def _ticket_query(a: TicketQueryArgs) -> dict[str, Any]:
    return get_client().ticket_query(kind=a.kind, work_type=a.work_type, parent_id=a.parent_id,
                                     status=a.status, assignee=a.assignee, epic_id=a.epic_id,
                                     created_by=a.created_by, tag=a.tag, q=a.q)


def _ticket_update(a: TicketUpdateArgs) -> dict[str, Any]:
    return get_client().ticket_update(a.ticket_id, status=a.status, assignee=a.assignee, design_ref=a.design_ref,
                                      description=a.description, tags=a.tags, title=a.title)


def _criterion_create(a: CriterionCreateArgs) -> dict[str, Any]:
    return get_client().criterion_create(ticket_id=a.ticket_id, text=a.text, check=a.check,
                                         checked_by=a.checked_by, override_reason=a.override_reason)


def _criterion_query(a: CriterionQueryArgs) -> dict[str, Any]:
    return get_client().criterion_query(a.ticket_id)


def _criterion_update(a: CriterionUpdateArgs) -> dict[str, Any]:
    return get_client().criterion_update(a.id, evidence_ref=a.evidence_ref, verdict=a.verdict, text=a.text,
                                         evidence_version=a.evidence_version, stale_ok=a.stale_ok)


TICKET_TOOLS = [
    ToolDef("ticket_create",
            "Create a ticket — epic (owner/coordinator), story (architect), task (engineer/architect). "
            "Caps (design §24.1): at most 8 open stories per epic (the owner raises it by answering a "
            "scope gate) and at most 5 tasks per story",
            "when you own a new slice of work: an epic from the owner's words (given verbatim; the board derives "
            "a short title), a story, or a task under your story",
            "the ticket and a hint for the next step, or a scope error when a cap is hit",
            TicketCreateArgs, _ticket_create, "ticket"),
    ToolDef("ticket_read",
            "ONE fat read of a ticket: the record (title, description, tags, status, assignee), its chain up to "
            "the epic, criteria, docs WITH their relation, children with assignee_role and criteria tally, "
            "blockers, open gates, the newest thread messages (thread_seq for message_query since_seq), and links",
            "whenever you need the full state of a ticket — instead of stitching ticket_query + link_query + "
            "message_query",
            "the full ticket record",
            TicketReadArgs, _ticket_read, "ticket"),
    ToolDef("ticket_query",
            "List tickets by kind, status, assignee, parent, epic_id (whole subtree), created_by, tag, or q "
            "(words in title/description/tags)",
            "to find tickets matching a filter when you do not have the id",
            "matching ticket records",
            TicketQueryArgs, _ticket_query, "ticket"),
    ToolDef("ticket_update",
            "Change a ticket's status/assignee/design_ref/description/tags/title, guarded by the transition rules "
            "(e.g. done needs every criterion passed). title: a short human title (<=80 chars) on an epic or "
            "story, architect/owner only — an epic's words stay verbatim",
            "to move your ticket to its next status, (re)assign it, or attach its design",
            "the updated ticket, or a transition/scope error naming what is missing",
            TicketUpdateArgs, _ticket_update, "ticket"),
    ToolDef("criterion_create",
            "Add a checkable definition of done to a ticket. The board DERIVES its checker from the "
            "ticket (qa for every story/task/epic criterion; reviewer only when a story is tagged "
            "review_required; owner for a knowledge ticket) — the checked_by argument is accepted for "
            "one release but ignored unless the owner also passes override_reason. A story carries at "
            "most 6 freshly-written criteria (a folded story keeps what it inherits)",
            "before work starts, while you own the ticket, one criterion per checkable fact",
            "the criterion (its checked_by is the derived checker, or the owner override)",
            CriterionCreateArgs, _criterion_create, "ticket"),
    ToolDef("criterion_query",
            "List a ticket's criteria",
            "to see what a ticket must satisfy, or which criteria are still pending",
            "the criterion records",
            CriterionQueryArgs, _criterion_query, "ticket"),
    ToolDef("criterion_update",
            "Record an evidence_ref then a verdict on a criterion (the checker only, never the doer)",
            "as a reviewer/qa/owner, after the evidence doc exists, to pass or fail a criterion",
            "the criterion plus a hint on remaining pending criteria",
            CriterionUpdateArgs, _criterion_update, "ticket"),
]

# ============================================================================= doc


class DocCreateArgs(BaseModel):
    doc_type: DocType = Field(description="design(architect)|strategy_hl/strategy_ll/domain(sme)|report(engineer/"
                              "reviewer/qa)|note(any)")
    title: str
    body_md: str
    scope: str = Field(description="epic_id | domain:<name> | global")


class DocReadArgs(BaseModel):
    id: str = Field(description="doc id")
    version: int | None = Field(default=None, description="a specific version, or omit for latest")


class DocQueryArgs(BaseModel):
    doc_type: DocType | None = None
    scope: str | None = None
    owner_role: Role | None = None


class DocUpdateArgs(BaseModel):
    id: str = Field(description="doc id")
    body_md: str | None = None
    title: str | None = None


class LinkCreateArgs(BaseModel):
    from_id: str = Field(description="ticket or doc id — the SUBJECT: from_id <relation> to_id "
                         "(blocks: from_id must finish before to_id may start; "
                         "extends: from_id is the more specific layer, to_id its parent)")
    to_id: str = Field(description="doc, artifact or ticket id — the OBJECT of the relation")
    relation: Relation = Field(description="designed_by|uses_strategy|uses_domain|evidence_for|blocks|produced|extends")


class LinkQueryArgs(BaseModel):
    from_id: str | None = None
    to_id: str | None = None
    relation: Relation | None = None


class LinkDeleteArgs(BaseModel):
    id: str = Field(description="link id")


def _doc_create(a: DocCreateArgs) -> dict[str, Any]:
    return get_client().doc_create(doc_type=a.doc_type, title=a.title, body_md=a.body_md, scope=a.scope)


def _doc_read(a: DocReadArgs) -> dict[str, Any]:
    return get_client().doc_read(a.id, version=a.version)


def _doc_query(a: DocQueryArgs) -> dict[str, Any]:
    return get_client().doc_query(doc_type=a.doc_type, scope=a.scope, owner_role=a.owner_role)


def _doc_update(a: DocUpdateArgs) -> dict[str, Any]:
    return get_client().doc_update(a.id, body_md=a.body_md, title=a.title)


def _link_create(a: LinkCreateArgs) -> dict[str, Any]:
    return get_client().link_create(from_id=a.from_id, to_id=a.to_id, relation=a.relation)


def _link_query(a: LinkQueryArgs) -> dict[str, Any]:
    return get_client().link_query(from_id=a.from_id, to_id=a.to_id, relation=a.relation)


def _link_delete(a: LinkDeleteArgs) -> dict[str, Any]:
    return get_client().link_delete(a.id)


DOC_TOOLS = [
    ToolDef("doc_create",
            "Author a versioned markdown doc — design/strategy_hl/strategy_ll/domain/report/note, per your role",
            "to record a design, strategy, domain guide, evidence report, or a thread-worthy note",
            "the doc and a hint to link it to its ticket",
            DocCreateArgs, _doc_create, "doc"),
    ToolDef("doc_read",
            "Read a doc, latest or a specific version",
            "when a ticket's design_ref or a link points at a doc you need to act on",
            "the doc plus the list of versions",
            DocReadArgs, _doc_read, "doc"),
    ToolDef("doc_query",
            "List docs matching doc_type/scope/owner_role filters",
            "to find the design or strategy docs for an epic when you do not have their ids",
            "doc summaries",
            DocQueryArgs, _doc_query, "doc"),
    ToolDef("doc_update",
            "Revise a doc's body/title; every update is a new version",
            "to amend a doc you own without losing its history",
            "the updated doc",
            DocUpdateArgs, _doc_update, "doc"),
    ToolDef("link_create",
            "Link a ticket/doc to a doc/artifact/ticket with a typed relation",
            "to attach a design, strategy, evidence, blocker, produced artifact, or doc-layer edge",
            "the link",
            LinkCreateArgs, _link_create, "doc"),
    ToolDef("link_query",
            "List links matching from_id/to_id/relation filters",
            "to discover what a ticket or doc is linked to",
            "the link records",
            LinkQueryArgs, _link_query, "doc"),
    ToolDef("link_delete",
            "Remove a link",
            "to undo a link created in error",
            "whether it was deleted",
            LinkDeleteArgs, _link_delete, "doc"),
]

# ============================================================================= thread


class MessageSendArgs(BaseModel):
    ticket_id: str
    kind: MessageKind = Field(description="question|answer|steer|status|finding|deviation|note")
    text: str
    to: str | None = Field(default=None, description="participant id, @handle, role, or omit for a thread note")
    reply_to: str | None = Field(default=None, description="message id this answers")


class MessageQueryArgs(BaseModel):
    ticket_id: str | None = Field(default=None, description="the thread to read")
    to: str | None = Field(default=None, description="only messages addressed to this participant id / role")
    kind: MessageKind | None = Field(default=None, description="question|answer|steer|status|finding|deviation|note")
    created_by: str | None = Field(default=None, description="only messages from this participant id")
    since_seq: int | None = Field(default=None, description="only messages newer than this seq (the last_seq "
                                  "hint of your previous call, or ticket_read's thread_seq) — the way to poll")
    limit: int = 50


class MessageReadArgs(BaseModel):
    id: str = Field(description="message id", validation_alias=AliasChoices("id", "message_id"))


class GateOpenArgs(BaseModel):
    ticket_id: str
    gate: Gate = Field(description="design_signoff|poc|demo|adversarial|budget|acceptance")
    note: str = ""


class GateAnswerArgs(BaseModel):
    ticket_id: str
    gate: Gate
    answer: str


class GatesArgs(BaseModel):
    ticket_id: str


def _message_send(a: MessageSendArgs) -> dict[str, Any]:
    return get_client().message_send(ticket_id=a.ticket_id, kind=a.kind, text=a.text, to=a.to, reply_to=a.reply_to)


def _message_query(a: MessageQueryArgs) -> dict[str, Any]:
    return get_client().message_query(ticket_id=a.ticket_id, to=a.to, kind=a.kind, limit=a.limit,
                                      since_seq=a.since_seq, created_by=a.created_by)


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
            "Post to a ticket's thread, addressed to a participant/role/@handle or left as a note",
            "at every milestone, blocker, question, answer or hand-off — an event not sent is work nobody sees",
            "the message; a question or steer is delivered to the recipient's feed",
            MessageSendArgs, _message_send, "thread"),
    ToolDef("message_query",
            "List thread messages, oldest first, each with its seq; since_seq returns ONLY what is new",
            "to read a thread, or to poll it with since_seq (from the last_seq hint or ticket_read's thread_seq)",
            "the messages and a last_seq hint",
            MessageQueryArgs, _message_query, "thread"),
    ToolDef("message_read",
            "Read one message by id with its seq, the message it replies to, and its replies",
            "to inspect a single message a feed event or reply_to pointed you at",
            "the message record",
            MessageReadArgs, _message_read, "thread"),
    ToolDef("gate_open",
            "Open a human gate on a ticket (precondition: none already open for that gate)",
            "when work needs a human decision — design sign-off, poc, demo, adversarial, budget, or acceptance",
            "the gate_opened event; the owner is notified",
            GateOpenArgs, _gate_open, "thread"),
    ToolDef("gate_answer",
            "Answer an open human gate (owner only)",
            "as the owner, to resolve a gate a seat opened",
            "the gate_answered event",
            GateAnswerArgs, _gate_answer, "thread"),
    ToolDef("gates",
            "List a ticket's currently open gates",
            "to see whether a ticket is waiting on a human decision",
            "the open gate events",
            GatesArgs, _gates, "thread"),
]

# ============================================================================= board


class BoardArgs(BaseModel):
    epic_id: str = Field(description="an epic id, or any ticket under it")


class EventsQueryArgs(BaseModel):
    subject_id: str | None = None
    since: int = 0
    limit: int = 200


class ParticipantsArgs(BaseModel):
    role: Role | None = None


def _board(a: BoardArgs) -> dict[str, Any]:
    return get_client().board(a.epic_id)


def _events_query(a: EventsQueryArgs) -> dict[str, Any]:
    return get_client().events_query(subject_id=a.subject_id, since=a.since, limit=a.limit)


def _participants(a: ParticipantsArgs) -> dict[str, Any]:
    resp = get_client().participants(role=a.role)
    if not resp.get("ok"):
        return resp
    c = get_client()
    rows = resp.get("value") or []
    for row in rows:
        if row.get("handle", "").startswith(("__", "wt-")):
            row["reach"] = "test fixture"
            continue
        if row.get("type") == "human":
            row["reach"] = "person — message_send(to='@'+handle) reaches their inbox + Slack doorbell"
            continue
        sq = c.session_query(participant_id=row.get("id"))
        states = [s.get("state") for s in (sq.get("value") or [])] if sq.get("ok") else []
        row["reach"] = ("live seat — a message wakes it now" if any(s in ("alive", "parked") for s in states)
                        else "closed seat — post on its ticket thread; the next shell reads it at boot")
    resp["hint"] = ("need a HUMAN review? pick the closest role match among type=human rows and "
                    "message_send(to='@'+handle, kind=question) — their Slack fires with a deep link. "
                    "A named person works the same: to='@name'")
    return resp


BOARD_TOOLS = [
    ToolDef("board",
            "Render an epic's ticket tree with status counts, ready/in_review lists and open gates",
            "to see the whole epic's state at a glance",
            "the board view for that epic",
            BoardArgs, _board, "board"),
    ToolDef("events_query",
            "Read the audit/feed log, by subject or since a sequence number",
            "to reconstruct what happened on a subject, or to catch up on events since a seq",
            "matching events",
            EventsQueryArgs, _events_query, "board"),
    ToolDef("participants",
            "List the whole team — humans and agent seats — optionally by role; each row carries type, @handle, "
            "role, and reach (person / live seat / closed seat)",
            "to find a collaborator: match the role you need, then message_send(to='@'+handle)",
            "the roster; a hint on reaching a human reviewer",
            ParticipantsArgs, _participants, "board"),
]

# ============================================================================= pool


class SpawnArgs(BaseModel):
    role: Role = Field(description="role the new shell will run as (/<role>)")
    ticket_id: str | None = Field(default=None, description="ticket the shell works on: a participant "
                                  "'<role>.<ticket_id>' is registered (if missing) and assigned to it")
    participant_id: str | None = Field(default=None, description="explicit participant id (pool handle); "
                                       "omit when ticket_id is given")
    parent_session: str | None = Field(default=None, description="session id spawning this one, for fan-out")
    assign: bool | None = Field(default=None, description="assign the ticket to the new seat: default only "
                                "when it is unassigned or its assignee's shell is dead; false = advisor/checker "
                                "spawn that never touches the assignee; true = take it over explicitly")
    model: str | None = Field(default=None, description="a models.json seat name (e.g. 'astra') or exact id; "
                              "omitted = the epic's seat choice (seat-model tag), else the Claude roles column")
    effort: str | None = Field(default=None, description="low | medium | high; omitted = the epic's choice "
                               "(seat-effort tag). Claude seats are capped at medium")
    mode: str | None = None


class ResumeArgs(BaseModel):
    participant_id: str


class InboxArgs(BaseModel):
    pass


class RecordStatusArgs(BaseModel):
    status: StatusValue = Field(description="done | deferred | failed | blocked | reviewed | handed_off")
    note: str = Field(default="", description="one line: what you did / what is left, for the people told")
    to: str | None = Field(default=None, description="an extra recipient (participant id, @handle or role); "
                           "your spawner, the epic architect and the epic's human owner are told anyway")
    ticket_id: str | None = Field(default=None, description="the ticket you worked; omit when you are a "
                                  "per-ticket seat (<role>.<ticket_id>)")


class CloseSelfArgs(BaseModel):
    pass


class ReapArgs(BaseModel):
    participant_id: str


class SessionQueryArgs(BaseModel):
    participant_id: str | None = None
    ticket_id: str | None = None
    state: str | None = None


def _pool_call(fn_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        from . import pool_adapter
    except ImportError:
        return unavailable("pool adapter not importable", "pool adapter not configured")
    fn = getattr(pool_adapter, fn_name, None)
    if fn is None:
        return unavailable(f"pool adapter has no {fn_name}()", "pool adapter not configured")
    return fn(**kwargs)


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
    tk = None
    if ticket_id:
        got_t = c.ticket_read(ticket_id)
        if not got_t.get("ok"):
            return got_t
        tk = got_t["value"].get("ticket", got_t["value"]) if isinstance(got_t["value"], dict) else None
        # the architect is RESIDENT per epic: while architect.<epic> is up, a second architect
        # seat on one of its stories only steals the assignment — message the resident instead
        if a.role.value == "architect" and tk and tk.get("kind") != "epic":
            epic_id = _epic_id(c, tk)
            resident = f"architect.{epic_id}" if epic_id else None
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
        # else — e.g. a reviewer doing a review-type story whose criteria are checked by qa.
        assign = True
        if a.role.value in ("reviewer", "qa"):
            crits = c.criterion_query(ticket_id)
            rows = crits.get("value") or []
            assign = bool(rows) and all(x.get("checked_by") != a.role.value for x in rows)
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
    choice = seat_choice.resolve(args.get("model"), args.get("effort"), epic_tags, _edp8_home())
    args["model"], args["effort"] = choice.model, choice.effort
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
    return _pool_call("reap", a.model_dump())


def _session_query(a: SessionQueryArgs) -> dict[str, Any]:
    return get_client().session_query(participant_id=a.participant_id, ticket_id=a.ticket_id, state=a.state)


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
            "Everything addressed to you that still awaits an answer or an action (questions and steers), "
            "oldest first, each with its answer_with call",
            "the first thing to call when woken, and step 1 of closing",
            "the list (empty == clear); a hint on how many items await you",
            InboxArgs, _inbox, "pool"),
    ToolDef("record_status",
            "Record the outcome of your work on your ticket, with a one-line note; tells your spawner, the "
            "epic's architect and its human owner (plus `to`)",
            "at milestones and as step 2 of closing (a resident architect records status and keeps listening)",
            "the message and who was told",
            RecordStatusArgs, _record_status, "pool"),
    ToolDef("close_self",
            "End your own shell NOW; refuses (one structured error) while inbox() is non-empty or no status "
            "is recorded",
            "step 3 of closing, after inbox is clear and record_status is done",
            "the release result — then stop calling tools and end the turn",
            CloseSelfArgs, _close_self, "pool"),
    ToolDef("spawn",
            "Start a new session for a role on a ticket (fan-out); the seat boots whoami → subscribe → context, "
            "records status to you when done, and closes itself",
            "to delegate a story/task to a fresh seat, or spawn a reviewer/qa on a ticket",
            "the session (or unavailable if the pool adapter is not configured); it returns within the "
            "call cap — a slow pool yields {status:'running', poll:'session_query'}",
            SpawnArgs, _spawn_bounded, "pool"),
    ToolDef("resume",
            "Resume a parked/stalled session",
            "to wake a seat that parked or stalled mid-work",
            "the session, or unavailable; a slow pool yields {status:'running', poll:'session_query'}",
            ResumeArgs, _resume_bounded, "pool"),
    ToolDef("reap",
            "Tear down a seat's shell (a dead one, or a resident architect at epic close)",
            "to clear a dead seat, or close the resident architect once the epic is done",
            "confirmation, or unavailable; a slow pool yields {status:'running', poll:'session_query'}",
            ReapArgs, _reap_bounded, "pool"),
    ToolDef("session_query",
            "List sessions matching participant/ticket/state filters",
            "to check whether a seat is live before messaging or spawning it",
            "matching session records",
            SessionQueryArgs, _session_query, "pool"),
]

# ============================================================================= search


class FindArgs(BaseModel):
    query: str = Field(description="words or a phrase: exact-word (FTS) and semantic hits are fused")
    k: int = 10
    types: str | None = Field(default=None, description="comma list of ticket,doc,message,criterion to restrict to")
    epic_id: str | None = Field(default=None, description="only hits inside this epic")


def _find(a: FindArgs) -> dict[str, Any]:
    return get_client().find(a.query, k=a.k, types=a.types, epic_id=a.epic_id)


SEARCH_TOOLS = [
    ToolDef("find",
            "Search tickets (title/description/tags), criteria, docs and thread messages by words or meaning; "
            "every hit carries ticket_id and epic_id (and title/status for tickets)",
            "when you need something across the board and do not have its id — one ticket_read finishes the job",
            "ranked hits with snippets",
            FindArgs, _find, "search"),
]

# ============================================================================= ruleset


class AssembleRulesetArgs(BaseModel):
    ticket_id: str | None = Field(default=None, description="assemble from the strategy/domain docs linked to this "
                                  "ticket (uses_strategy/uses_domain), inherited up the parent chain")
    doc_ids: list[str] | None = Field(default=None, description="explicit leaf doc ids to assemble instead")


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
        return LayerDoc(id=v["id"], title=v["title"], doc_type=v["doc_type"], body_md=v["body_md"])

    def extends_of(doc_id: str) -> list[str]:
        links = c.link_query(from_id=doc_id, relation=Relation.extends.value)
        out: list[str] = []
        for lk in links.get("value") or []:
            # a dangling/non-doc layer (legacy extends pointing at a ticket) is SKIPPED
            # loudly, never a hard failure that strips the checker of its whole brief
            if c.doc_read(lk["to_id"]).get("ok"):
                out.append(lk["to_id"])
            else:
                skipped.append(lk["to_id"])
        return out

    leaves2 = [x for x in leaves if c.doc_read(x).get("ok")]
    skipped += [x for x in leaves if x not in leaves2]
    if not leaves2:
        return {"ok": False, "error": {"code": "not_found", "message": f"no readable leaf docs (skipped: {skipped})"},
                "hint": "re-link the ticket's uses_strategy/uses_domain to existing docs"}
    try:
        out = assemble_ruleset(load, extends_of, leaves2)
    except AssembleError as e:
        return {"ok": False, "error": {"code": "precondition", "message": e.instruction}, "hint": ""}
    hint = "apply constructive in full while building; enforced is the adherence view a checker verifies"
    if out.oversize:
        hint = f"OVERSIZE (~{out.approx_tokens} tokens): the layering is a scoping defect — split it, don't truncate"
    value = out.model_dump()
    if skipped:
        value["skipped_layers"] = skipped
        hint += f"; NOTE: {len(skipped)} dangling layer(s) skipped: {skipped}"
    return {"ok": True, "value": value, "hint": hint}


RULESET_TOOLS = [
    ToolDef("assemble_ruleset",
            "Compose the layered ruleset for a ticket (or explicit docs): walks doc `extends` chains "
            "universal-first / most-specific-last, dedupes, and splits into the constructive view (how to "
            "build) and the enforced view (what a checker verifies)",
            "at the start of a story/task, to get your working brief from the linked strategy/domain docs",
            "the ordered layers and both views, or a precondition error on a cycle/missing layer",
            AssembleRulesetArgs, _assemble_ruleset, "ruleset"),
]

# ============================================================================= consult


class ConsultArgs(BaseModel):
    question: str = Field(description="what you want a second, independent read on — or the build/delivery brief")
    purpose: ConsultPurpose = Field(default=ConsultPurpose.second_opinion,
                          description="adversary|creative|visual|second_opinion|build — selects the consultant's brief")
    profile: ConsultProfile | None = Field(default=None,
                          description="override the purpose→profile map: design (read-only advice) | concept "
                          "(image_gen + asset write) | blender (shell→Blender, asset write) | verify (images in, "
                          "read-only, structured PASS/FAIL/UNVERIFIED verdict) | direct (read-only inspection → "
                          "spec). Omit to derive from purpose. Only concept/blender may take write_dir")
    context: str = ""
    files: list[str] | None = None
    ticket_id: str | None = Field(default=None, description="if set, post the answer to this ticket's thread")
    timeout_s: int = 600
    write_dir: str | None = Field(default=None, description="a directory Sol may WRITE (assets delivered there, "
                                  "or files edited in place). Without it Sol is read-only and can only advise")
    thread_id: str | None = Field(default=None, description="STEER: the thread_id returned by an earlier consult — "
                                  "resumes that same Sol session (it remembers what it said and did). Omit for a "
                                  "cold start")
    images: list[str] | None = Field(default=None, description="image files (png/jpg) to attach — screenshots, "
                                     "renders, mockups. Attaching is the ONLY way a picture reaches Sol; a path "
                                     "in the prompt is a no-op")
    model: ConsultModel | None = Field(default=None, description="consultant model for this call: gpt-6-astra is the only "
                              "model (gpt-5.6-sol retired 2026-09-10 by owner ruling). Omit for the default")


def _fence_status_line(resp: dict[str, Any], run_id: str | None) -> str:
    """ONE line naming the run and whether the write-fence was clean or failed the run
    closed — NEVER a file path (design §19 rule 7). The full fence report lives only in the
    run manifest (consult_status(run_id) surfaces it); a spacetravel-style path from another
    project can no longer leak onto a thread through this note."""
    if not run_id:
        return ""
    code = None if resp.get("ok") else (resp.get("error") or {}).get("code")
    if code == "boundary":
        return f"run {run_id} FAILED CLOSED (write-fence): see consult_status(run_id='{run_id}')"
    return f"run {run_id}, fence clean"


def _consult_complete(client: BoardClient, a: ConsultArgs, resp: dict[str, Any],
                      caller: str | None, run_id: str | None, *, wake: bool) -> None:
    """Post the answer to the ticket thread (one-line fence status appended, no paths) and,
    for a run that finished in the background, wake the caller with a consult_done note."""
    if not a.ticket_id:
        return
    val = resp.get("value") or {}
    rid = val.get("run_id") or run_id
    tag = val.get("profile") or getattr(a.purpose, "value", a.purpose)
    answer = val.get("answer")
    fence = _fence_status_line(resp, rid)
    try:
        if answer:
            note = f"consultant[{tag}]: {answer}"
            if fence:
                note = f"{note}\n\n{fence}"
            client.message_send(ticket_id=a.ticket_id, kind="note", text=note, to=None)
        if wake and caller:
            status = "ok" if resp.get("ok") else (resp.get("error") or {}).get("code", "failed")
            client.message_send(ticket_id=a.ticket_id, kind="note", to=caller,
                                text=f"consult_done: run {rid or '?'} finished ({status}); "
                                     + ("answer on this thread" if answer else
                                        f"see consult_status(run_id='{rid}')"))
    except Exception:  # noqa: BLE001 — a thread-note failure never crashes the background run
        pass


def _consult(a: ConsultArgs) -> dict[str, Any]:
    from . import consult as consult_mod

    client = get_client()          # concrete client, safe to use from the background thread
    caller = client.participant
    holder: dict[str, Any] = {}
    run_box: dict[str, str] = {}
    early = {"v": False}
    done = threading.Event()

    if a.ticket_id:  # hold the board's auto-advance on this ticket until the run lands
        consult_mod.inflight_mark(a.ticket_id, None, caller)

    def _work() -> None:
        try:
            resp = consult_mod.consult(a.purpose, a.question, context=a.context, files=a.files,
                                       timeout_s=a.timeout_s, write_dir=a.write_dir, images=a.images,
                                       thread_id=a.thread_id, model=a.model, profile=a.profile,
                                       on_run_id=lambda rid: run_box.setdefault("id", rid))
        except Exception as e:  # noqa: BLE001 — a crashed consult must surface, never hang the caller
            resp = {"ok": False, "error": {"code": "internal", "message": f"consult crashed: {e}"}, "hint": ""}
        holder["resp"] = resp
        if a.ticket_id:  # cleared BEFORE the thread note lands, so the note itself re-evaluates the advance
            consult_mod.inflight_clear(a.ticket_id)
        done.set()
        # Over-cap only: the caller already has a {running} envelope, so the background run
        # owns the completion side effects — post the answer AND wake the caller. Within the
        # cap the handler posts synchronously below (never both: `early` is set only over-cap).
        if early["v"]:
            _consult_complete(client, a, resp, caller, run_box.get("id"), wake=True)

    threading.Thread(target=_work, name="consult", daemon=True).start()
    if done.wait(timeout=_call_cap()):
        resp = holder["resp"]
        _consult_complete(client, a, resp, caller, run_box.get("id"), wake=False)
        return resp
    early["v"] = True
    rid = run_box.get("id")
    val: dict[str, Any] = {"status": "running", "poll": "consult_status"}
    if rid:
        val["run_id"] = rid
    hint = ("consult exceeds the tool-call cap and is running in the background; "
            + (f"poll consult_status(run_id='{rid}')" if rid else
               "it is queued behind another run — poll consult_status()"))
    if a.ticket_id:
        hint += "; a consult_done note lands on the ticket thread when it finishes"
    return {"ok": True, "value": val, "hint": hint}


class ConsultStatusArgs(BaseModel):
    run_id: str = Field(description="the run_id a consult returned (or the newest run when omitted)")


def _consult_status(a: ConsultStatusArgs) -> dict[str, Any]:
    from . import consult as consult_mod

    return consult_mod.consult_status(a.run_id)


CONSULT_TOOLS = [
    ToolDef("consult_status",
            "Look up a consult run by run_id: its manifest status and, when the run produced one, the "
            "recovered answer; also reports the fleet-wide consult lane (in flight / queued) and any quota block",
            "after your own consult returned {status:running} or timed out, or the server restarted mid-run — "
            "instead of re-asking",
            "the run's status and recovered answer if any, plus the lane and quota block",
            ConsultStatusArgs, _consult_status, "consult"),
    ToolDef("consult",
            "Ask the consultant (GPT Sol/Astra) for adversarial review, creative/visual judgment or a second "
            "opinion — or, with write_dir, actual DELIVERY (Sol writes/edits files there). Brief it with the "
            "GOAL, audience, quality bar and reference work, not a step-by-step checklist. thread_id resumes a "
            "session; images attach pictures; ticket_id posts the answer to that thread",
            "when a task needs a second independent read or a build the consultant should produce; runs in the "
            "background — a long run returns a run_id and completes via a consult_done feed event",
            "the answer with run log and run_id, or {run_id, status:'running', poll:'consult_status'} when it "
            "exceeds the call cap, or unavailable/timeout/exit on failure",
            ConsultArgs, _consult, "consult"),
]

# ============================================================================= artifact


class ArtifactCreateArgs(BaseModel):
    form: ArtifactForm = Field(description="image|file|url|app|repo_ref")
    uri: str = Field(description="a uri, never a machine path")
    note: str = ""
    ticket_id: str | None = Field(default=None, description="link this artifact to a ticket (relation=produced)")


class ArtifactReadArgs(BaseModel):
    id: str = Field(description="artifact id")


def _artifact_create(a: ArtifactCreateArgs) -> dict[str, Any]:
    return get_client().artifact_create(form=a.form, uri=a.uri, note=a.note, ticket_id=a.ticket_id)


def _artifact_read(a: ArtifactReadArgs) -> dict[str, Any]:
    return get_client().artifact_read(a.id)


ARTIFACT_TOOLS = [
    ToolDef("artifact_create",
            "Record a produced thing by uri (never a machine path); optionally link it to a ticket",
            "when you ship an artifact — an image, file, url, app or repo_ref — the owner should see",
            "the artifact",
            ArtifactCreateArgs, _artifact_create, "artifact"),
    ToolDef("artifact_read",
            "Read one artifact",
            "to inspect an artifact a ticket or link points at",
            "the artifact record",
            ArtifactReadArgs, _artifact_read, "artifact"),
]

# ============================================================================= close


class CloseArgs(BaseModel):
    epic_id: str


def _close(a: CloseArgs) -> dict[str, Any]:
    resp = get_client().board(a.epic_id)
    if not resp.get("ok"):
        return resp
    status = resp["value"]["epic"]["status"]
    if status not in ("done", "partial"):
        return {"ok": False, "error": {"code": "transition", "message": f"epic {a.epic_id} is {status}, not done/partial"},
                "hint": "close only after the epic reaches done or partial"}
    resident = f"architect.{a.epic_id}"
    disarm = ["CronDelete <ids you armed>", "TaskStop <monitor>"]
    seat = get_client().session_query(participant_id=resident)
    rows = (seat.get("value") or []) if seat.get("ok") else []
    if any((r.get("state") in ("alive", "parked")) for r in rows):
        disarm.insert(0, f"reap(participant_id={resident!r}) — the resident architect never closes itself")
    return {"ok": True, "value": {"disarm": disarm},
            "hint": "epic is closed in the record; disarm your wiring"}


CLOSE_TOOLS = [
    ToolDef("close",
            "Confirm an epic is closed (done/partial) and hand back the wiring to disarm",
            "as the owner, once an epic reaches done/partial, to get the disarm checklist",
            "the disarm checklist, or a transition error if the epic is not yet closed",
            CloseArgs, _close, "close"),
]

# ============================================================================= registry

ALL_TOOLS: dict[str, ToolDef] = {
    t.name: t for t in (
        IDENTITY_TOOLS + TICKET_TOOLS + DOC_TOOLS + THREAD_TOOLS + BOARD_TOOLS + POOL_TOOLS
        + SEARCH_TOOLS + RULESET_TOOLS + CONSULT_TOOLS + ARTIFACT_TOOLS + CLOSE_TOOLS
    )
}

_IDENTITY = ["whoami", "preflight", "subscribe", "context", "describe", "get_guide"]
_TICKET_RW = ["ticket_create", "ticket_read", "ticket_query", "ticket_update", "criterion_create",
              "criterion_query", "criterion_update"]
_TICKET_RO = ["ticket_read", "ticket_query", "ticket_update"]  # owner: sign-off only, guarded by the board
_CHECK = ["criterion_query", "criterion_update"]  # checkers record verdicts (board guards who may)
_DOC_RW = ["doc_create", "doc_read", "doc_query", "doc_update", "link_create", "link_query", "link_delete"]
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
        + ["find", "consult", "consult_status", "artifact_create", "artifact_read", "spawn", "inbox", "record_status"],
    Role.sme.value: _IDENTITY + _TICKET_RO + _DOC_RW + _THREAD
        + ["find", "participants", "assemble_ruleset", "criterion_query", "criterion_update",
           "artifact_create", "artifact_read"] + _CLOSING,
    Role.engineer.value: _IDENTITY + _TICKET_RW + _DOC_RW + _THREAD
        + ["find", "participants", "assemble_ruleset", "consult", "consult_status", "artifact_create", "artifact_read"] + _CLOSING,
    Role.reviewer.value: _IDENTITY + _TICKET_RO + _CHECK + _DOC_RW + _THREAD
        + ["find", "participants", "assemble_ruleset", "consult", "consult_status", "artifact_create", "artifact_read"] + _CLOSING,
    Role.adversary.value: _IDENTITY + _TICKET_RW + _DOC_RW + _THREAD
        + ["find", "participants", "assemble_ruleset", "consult", "consult_status", "artifact_create", "artifact_read"] + _CLOSING,
    Role.qa.value: _IDENTITY + _TICKET_RO + _CHECK + _DOC_RW + _THREAD + _BOARD
        + ["find", "assemble_ruleset", "consult", "consult_status", "artifact_create", "artifact_read"] + _CLOSING,
}


ROLE_BUNDLES[Role.coordinator.value] = list(ROLE_BUNDLES[Role.owner.value])  # retired seat: explicit, not implicit
ROLE_BUNDLES[Role.consultant.value] = _IDENTITY + ["ticket_read", "ticket_query", "message_send", "message_query",
                                                   "find", "inbox"] + _DOC_RO


def tools_for_role(role: str) -> list[ToolDef]:
    names = ROLE_BUNDLES.get(role, ROLE_BUNDLES[Role.owner.value])
    return [ALL_TOOLS[n] for n in names if n in ALL_TOOLS]
