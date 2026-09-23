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
import copy
import functools
import contextvars
import enum as _enum
import json
import os
import sys
import threading
import typing
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import AliasChoices, BaseModel, Field, ValidationError

from . import seat_choice
from .client import BoardClient
from .doc_tools import DocEdit
from .schemas import (
    ENUMS,
    ArtifactForm,
    Check,
    CheckedBy,
    ClaimBasis,
    ConsultModel,
    ConsultProfile,
    ConsultPurpose,
    DocType,
    Gate,
    MessageKind,
    Relation,
    Role,
    StatusValue,
    SessionState,
    SeatEffort,
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
    parts = [f"{k}: {'|'.join(v)}" for k, v in ef.items()]
    return "Enum args — " + "; ".join(parts) + " (describe('enums')). "


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
    """args_model's JSON schema with every `title`, empty default (null, "", []) and
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
            if k in ("title", "$defs", "additionalProperties") or (k == "default" and v in (None, "", [])):
                continue
            out[k] = {p: walk(s, depth) for p, s in v.items()} if k == "properties" else walk(v, depth)
        alts = out.get("anyOf")
        if isinstance(alts, list) and len(alts) == 2 and {"type": "null"} in alts:
            other = next(a for a in alts if a != {"type": "null"})
            out.pop("anyOf")
            out = {**other, **out}
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


class ResumeSelfArgs(BaseModel):
    pass


class ContextArgs(BaseModel):
    ticket_id: str | None = Field(default=None, description='one ticket, or omit for all yours')
    verbose: bool = Field(default=False, description='full unbounded snapshot')


class ContextDeltaArgs(BaseModel):
    # not a subclass of ContextArgs: context_delta takes no `verbose` — its behaviour is unchanged by S12.
    ticket_id: str | None = Field(default=None, description='one ticket, or omit for all yours')
    cursor: str = Field(description='the cursor from your last context/delta')
    limit: int = Field(default=50, ge=1, le=100, description='max changes per page; continue if has_more')


class DescribeObjectsArgs(BaseModel):
    type: str | None = Field(default=None, description="omit to list; an object name, a Context* type, 'enums' or 'enum:<Name>'")


class DescribeArgs(BaseModel):
    type: str = Field(description="an object type, 'enums', or 'enum:<Name>'")


class GetGuideArgs(BaseModel):
    name: str = Field(description='guide name without .md')


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


# S12 (qa finding 18): a multi-ticket checking seat's context() returned ~120k chars and
# overflowed the MCP client cap. The snapshot is bounded HERE, in the tool layer, so board.py
# _context_snapshot / ticket_view (shared by context_delta) stay unchanged. Default is bounded;
# verbose=True hands back the full snapshot. The budget is deliberately below the client cap.
_CONTEXT_BUDGET_B = 40_000        # default byte cap for the bounded snapshot (env-overridable)
_THREAD_HEAD = 200                # per-message body kept in a bounded thread
_THREAD_KEEP = 3                  # newest messages kept per ticket by default
_DOC_SUMMARY_HEAD = 200           # doc summary kept in a bounded snapshot


def _context_budget() -> int:
    try:
        return max(4_000, int(os.environ.get("EDP8_CONTEXT_BUDGET_B", _CONTEXT_BUDGET_B)))
    except ValueError:
        return _CONTEXT_BUDGET_B


def _clip(s: Any, n: int) -> Any:
    if not isinstance(s, str) or len(s) <= n:
        return s
    return s[:n].rstrip() + f"… (+{len(s) - n} chars)"


def _bound_snapshot(snap: dict[str, Any], *, thread_keep: int, thread_head: int,
                    doc_head: int, words_head: int | None) -> tuple[dict[str, Any], set[str]]:
    """Return a byte-bounded copy of a context snapshot and the set of categories trimmed
    ('thread'/'docs'/'words'). Per-ticket summaries + read_refs stay; thread bodies and doc
    summaries are clipped/paged. Never touches `cursor`, `asks_for_me`, criteria, chain or the
    ticket record."""
    hit: set[str] = set()
    out = dict(snap)
    tickets_in = snap.get("tickets") or []
    new_tickets: list[dict[str, Any]] = []
    for tv in tickets_in:
        tv = dict(tv)
        rows = tv.get("thread") or []
        total = tv.get("thread_total", len(rows))
        kept = rows[-thread_keep:] if thread_keep > 0 else []
        tv["thread"] = [{**r, "text": _clip(r.get("text"), thread_head)} for r in kept]
        if total > len(kept) or any(len(r.get("text") or "") > thread_head for r in rows):
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
        new_tickets.append(tv)
    out["tickets"] = new_tickets
    return out, hit


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
        dict(thread_keep=1, thread_head=120, doc_head=120, words_head=400),
        dict(thread_keep=0, thread_head=0, doc_head=0, words_head=200),
    ]
    bounded: dict[str, Any] = {}
    hit: set[str] = set()
    for i, p in enumerate(passes):
        bounded, hit = _bound_snapshot(snap, **p)
        if i > 0:
            hit.add("_tightened")
        if _bytes(bounded) <= budget - reserve:
            break
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


_TOOLS_BY_TYPE: dict[str, list[str]] = {
    "ticket": ["ticket_create", "ticket_read", "ticket_query", "ticket_update", "find", "board", "spawn"],
    "criterion": ["criterion_create", "criterion_query", "criterion_update", "ticket_read"],
    "doc": ["doc_create", "doc_read", "doc_query", "doc_update", "doc_edit", "link_create", "assemble_ruleset", "find"],
    "link": ["link_create", "link_query", "link_delete", "ticket_read"],
    "message": ["message_send", "message_query", "message_read", "inbox", "record_status", "find"],
    "event": ["events_query", "subscribe"],
    "artifact": ["artifact_create", "artifact_read", "artifact_upload"],
    "session": ["session_query", "spawn", "reap", "resume", "resume_self", "close_self"],
    "participant": ["participants", "whoami", "spawn"],
    "decision": ["record_decision", "withdraw_decision", "set_binding", "lookup", "dense_search", "find"],
    "claim": ["record_claim", "withdraw_claim", "lookup", "find"],
    "lesson": ["record_lesson", "lookup", "find"],
    "kglink": ["lookup"],
}


def _describe_objects(args: DescribeObjectsArgs) -> dict[str, Any]:
    from .context_contracts import CONTEXT_TYPES
    if args.type is None:
        return {"ok": True, "value": {"objects": sorted(_TOOLS_BY_TYPE) + sorted(CONTEXT_TYPES),
                "enums": sorted(ENUMS), "guides": ["context-refresh", "agent-tools"]},
                "hint": "describe_objects(type=<name>) for schema, relationships and skill references"}
    return _describe(DescribeArgs(type=args.type))


def _describe(args: DescribeArgs) -> dict[str, Any]:
    from .context_contracts import CONTEXT_TYPES
    t = args.type
    if t in CONTEXT_TYPES:
        return {"ok": True, "value": {"schema": CONTEXT_TYPES[t].model_json_schema(),
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
    out = get_client().describe(t)
    if out.get("ok"):
        out["value"]["tools"] = _TOOLS_BY_TYPE.get(t, [])
        out["value"]["relationships"] = {"ticket": ["criterion", "doc", "message", "link"],
            "doc": ["ticket", "link", "criterion"], "artifact": ["message", "ticket", "link"]}.get(t, ["ticket"])
        out["value"]["skills"] = {"doc": ["methodology", "verify"], "artifact": ["demo"],
            "criterion": ["verify"], "ticket": ["methodology", "handoff"]}.get(t, [])
        out["value"]["guides"] = ["agent-tools"]
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
            'Host free RAM, live seats vs pool caps, the codex lane and any usage-cap note; advisory, never blocks',
            'before a spawn or consult',
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


class TicketCreateArgs(BaseModel):
    kind: TicketKind = Field()
    work_type: WorkType = Field()
    title: str = Field(description="epic: the owner's words verbatim (a short title is derived); story/task: the slice name")
    words: str | None = Field(default=None, description="epic or quick task: the owner's verbatim request; immutable")
    parent_id: str | None = None  # story/task: required, except the owner's quick task (the tool description says so)
    assignee: str | None = Field(default=None)
    description: str = Field(default="", description='scope, intent, pointers to files/docs')
    tags: list[str] | None = Field(default=None)


class TicketReadArgs(BaseModel):
    ticket_id: str = Field(validation_alias=AliasChoices("ticket_id", "id"))
    include: str | None = Field(default=None, description='comma list of chain,criteria,docs,children,blockers,gates,thread,links; omit for all')
    thread_limit: int = Field(default=20, ge=0, le=200,
                              description='newest thread messages to include (0-200)')


class TicketQueryArgs(BaseModel):
    kind: TicketKind | None = Field(default=None)
    work_type: WorkType | None = None
    parent_id: str | None = None
    status: TicketStatus | None = Field(default=None)
    assignee: str | None = None
    epic_id: str | None = Field(default=None, description='every ticket under this epic')
    created_by: str | None = None
    tag: str | None = Field(default=None)
    q: str | None = Field(default=None, description='exact words in title/description/tags')


class TicketUpdateArgs(BaseModel):
    ticket_id: str = Field(validation_alias=AliasChoices("ticket_id", "id"))
    status: TicketStatus | None = Field(default=None, description='next legal status')
    assignee: str | None = Field(default=None)
    design_ref: str | None = Field(default=None, description='design/plan doc id')
    description: str | None = Field(default=None, description='replaces the description')
    tags: list[str] | None = Field(default=None, description='replaces the tag list')
    title: str | None = Field(default=None, description='short title, <=80 chars (architect/owner)')


class CriterionCreateArgs(BaseModel):
    ticket_id: str
    text: str = Field()
    check: Check = Field()
    checked_by: CheckedBy | None = None  # the tool description: needs the owner's override_reason
    override_reason: str | None = Field(default=None, description='owner only: why the derived checker is overridden')


class CriterionQueryArgs(BaseModel):
    ticket_id: str


class CriterionUpdateArgs(BaseModel):
    model_config = {"extra": "forbid"}  # an unknown kwarg is an ERROR, never a silent drop
    id: str = Field()
    evidence_ref: str | None = None  # the report doc id proving the check
    verdict: Verdict | None = Field(default=None, description='set after evidence_ref (checker only)')
    text: str | None = Field(default=None, description='reword (author, while pending)')
    evidence_version: int | None = Field(default=None,
        description='doc version signed; refused if below current')
    stale_ok: bool = Field(default=False, description='sign the version you read though the doc moved on')
    note: str = ''  # why, with a verdict; the board keeps it as a claim (S-IMPLICIT)


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
            'matching tickets',
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


class DocCreateArgs(BaseModel):
    doc_type: DocType = Field(description='design: architect; strategy_*/domain: sme; report: engineer/adversary/qa; note: any')
    title: str
    body_md: str
    scope: str = Field(description='epic id | domain:<name> | global')
    tags: list[str] | None = Field(default=None, description='knowledge tags')
    status: Literal["active", "proposed"] | None = Field(
        default=None, description='proposed: owner approves')
    proposes: str | None = Field(default=None, description='active doc id it revises')
    ticket_id: str | None = Field(default=None, description='source ticket')


class DocReadArgs(BaseModel):
    id: str = Field()
    version: int | None = Field(default=None, description='omit for latest; reuse the returned one to continue')
    offset: int | None = Field(default=None, ge=0, description='char offset; opts into bounded output')
    limit: int | None = Field(default=None, ge=1, le=32768, description='chars, default 8192 when bounded')
    section: str | None = Field(default=None, description='exact heading line; offset is relative to it')


class DocEditArgs(DocEdit):
    id: str = Field()


class DocQueryArgs(BaseModel):
    doc_type: DocType | None = None
    scope: str | None = None
    owner_role: Role | None = None
    tag: str | None = None
    status: Literal["active", "proposed", "retired"] | None = None


class DocUpdateArgs(BaseModel):
    id: str = Field()
    body_md: str | None = None
    title: str | None = None
    tags: list[str] | None = Field(default=None, description='replaces the tag list')
    compact: bool = Field(default=False, description='return only a receipt')


class LinkCreateArgs(BaseModel):
    from_id: str = Field(description='subject (blocks: finishes first; extends: the more specific layer)')
    to_id: str = Field(description='object')
    relation: Relation = Field()


class LinkQueryArgs(BaseModel):
    from_id: str | None = None
    to_id: str | None = None
    relation: Relation | None = None


class LinkDeleteArgs(BaseModel):
    id: str = Field()


def _doc_create(a: DocCreateArgs) -> dict[str, Any]:
    return get_client().doc_create(doc_type=a.doc_type, title=a.title, body_md=a.body_md, scope=a.scope,
                                   tags=a.tags, status=a.status, proposes=a.proposes, ticket_id=a.ticket_id)


def _doc_read(a: DocReadArgs) -> dict[str, Any]:
    return get_client().doc_read(a.id, version=a.version, offset=a.offset, limit=a.limit, section=a.section)


def _doc_query(a: DocQueryArgs) -> dict[str, Any]:
    return get_client().doc_query(doc_type=a.doc_type, scope=a.scope, owner_role=a.owner_role,
                                  tag=a.tag, status=a.status)


def _doc_update(a: DocUpdateArgs) -> dict[str, Any]:
    return get_client().doc_update(a.id, body_md=a.body_md, title=a.title, compact=a.compact, tags=a.tags)


def _doc_edit(a: DocEditArgs) -> dict[str, Any]:
    return get_client().doc_edit(a.id, a.expected_version, [e.model_dump() for e in a.edits], a.title)


def _link_create(a: LinkCreateArgs) -> dict[str, Any]:
    return get_client().link_create(from_id=a.from_id, to_id=a.to_id, relation=a.relation)


def _link_query(a: LinkQueryArgs) -> dict[str, Any]:
    return get_client().link_query(from_id=a.from_id, to_id=a.to_id, relation=a.relation)


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
            'doc summaries',
            DocQueryArgs, _doc_query, "doc"),
    ToolDef("doc_update",
            "Replace a doc's body/title as a new version",
            'to amend a doc you own',
            'the doc (compact=true: a receipt)',
            DocUpdateArgs, _doc_update, "doc"),
    ToolDef("link_create",
            'Link from_id <relation> to_id (ticket/doc/artifact)',
            'to attach a design, strategy, evidence, blocker, artifact or doc layer',
            'the link',
            LinkCreateArgs, _link_create, "doc"),
    ToolDef("link_query",
            'List links by from_id/to_id/relation',
            'to see what something is linked to',
            'the links',
            LinkQueryArgs, _link_query, "doc"),
    ToolDef("link_delete",
            'Remove a link',
            'to undo a link made in error',
            'whether it was deleted',
            LinkDeleteArgs, _link_delete, "doc"),
]

# ============================================================================= thread


class MessageSendArgs(BaseModel):
    ticket_id: str
    kind: MessageKind = Field()
    text: str
    to: str | None = Field(default=None, description='participant id, @handle or role; omit for a note')
    reply_to: str | None = Field(default=None, description='message id answered')
    artifacts: list[str] | None = Field(default=None, description='your staged artifact ids to attach')


class MessageQueryArgs(BaseModel):
    ticket_id: str | None = Field(default=None)
    to: str | None = Field(default=None, description='addressed to this id/role')
    kind: MessageKind | None = Field(default=None)
    created_by: str | None = Field(default=None)
    since_seq: int | None = Field(default=None, description='only newer than this seq (your last last_seq)')
    limit: int = 50


class MessageReadArgs(BaseModel):
    id: str = Field(validation_alias=AliasChoices("id", "message_id"))


class GateOpenArgs(BaseModel):
    ticket_id: str
    gate: Gate = Field()
    note: str = ""


class GateAnswerArgs(BaseModel):
    ticket_id: str
    gate: Gate
    answer: str


class GatesArgs(BaseModel):
    ticket_id: str


def _message_send(a: MessageSendArgs) -> dict[str, Any]:
    return get_client().message_send(ticket_id=a.ticket_id, kind=a.kind, text=a.text, to=a.to,
                                     reply_to=a.reply_to, artifacts=a.artifacts)


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
            'Post to a ticket thread, to a participant/role/@handle or as a note',
            'at every milestone, blocker, question, answer or hand-off',
            "the message; questions and steers reach the recipient's feed",
            MessageSendArgs, _message_send, "thread"),
    ToolDef("message_query",
            'List thread messages oldest first with seq; since_seq returns only newer ones',
            'to read or poll a thread',
            'the messages and a last_seq hint',
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


class BoardArgs(BaseModel):
    epic_id: str = Field(description='an epic, or any ticket under it')


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
            "An epic's ticket tree with status counts, ready/in_review lists and open gates",
            'for the whole epic at a glance',
            'the board view',
            BoardArgs, _board, "board"),
    ToolDef("events_query",
            'Read the event log by subject or since a seq',
            'to reconstruct or catch up on events',
            'matching events',
            EventsQueryArgs, _events_query, "board"),
    ToolDef("participants",
            'List humans and seats, optionally by role, with @handle and reach',
            "to find a collaborator, then message_send(to='@'+handle)",
            'the roster',
            ParticipantsArgs, _participants, "board"),
]

# ============================================================================= pool


class SpawnArgs(BaseModel):
    role: Role = Field()
    ticket_id: str | None = Field(default=None, description="registers and assigns '<role>.<ticket_id>'")
    participant_id: str | None = Field(default=None, description='explicit pool handle; omit with ticket_id')
    parent_session: str | None = Field(default=None, description='spawning session id')
    assign: bool | None = Field(default=None, description='default: only if unassigned/dead; false = checker; true = take over')
    model: str | None = Field(default=None, description="seat or model id; default: epic tag")
    effort: SeatEffort | None = Field(default=None, description="default: epic tag; Claude caps at medium")
    mode: SpawnMode | None = None


class ResumeArgs(BaseModel):
    participant_id: str


class InboxArgs(BaseModel):
    pass


class RecordStatusArgs(BaseModel):
    status: StatusValue = Field()
    note: str = Field(default="", description='one line: done / left')
    to: str | None = Field(default=None, description='an extra recipient')
    ticket_id: str | None = Field(default=None, description='omit on a per-ticket seat')


class CloseSelfArgs(BaseModel):
    pass


class ReapArgs(BaseModel):
    participant_id: str


class SessionQueryArgs(BaseModel):
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
        if a.role.value == "qa":
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
    choice = seat_choice.resolve(args.get("model"), args.get("effort"), epic_tags, _edp8_home(),
                                 role=str(args.get("role") or "") or None)
    args["model"], args["effort"] = choice.pool_model, choice.effort
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
            'matching sessions',
            SessionQueryArgs, _session_query, "pool"),
]

# ============================================================================= search


class FindArgs(BaseModel):
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


class RecordDecisionArgs(BaseModel):
    scope: str = Field(description='epic or ticket id it is in force for')
    text: str = Field(description='one sentence, <=240 chars')
    detail: str = Field(default="", description='why, <=1000 chars')
    replaces: list[str] = Field(default_factory=list,
                                description='older decision ids it supersedes')
    binding: bool | None = Field(default=None,
                                 description='true = always handed to seats in scope; omit to inherit')
    source: str | None = Field(default=None, description='message, doc or attachment id')
    domains: list[str] = Field(default_factory=list, description='domain checklist names')


class RecordClaimArgs(BaseModel):
    scope: str = Field(description='epic or ticket id')
    text: str = Field(description='one sentence')
    basis: ClaimBasis = Field(default=ClaimBasis.assumption)
    evidence: list[str] = Field(default_factory=list,
                                description='attachment/check/commit ids; a fact needs these plus measured|ruled')
    source: str | None = Field(default=None, description='message or doc id')


class RecordLessonArgs(BaseModel):
    # S-HARVEST: no field descriptions — record_lesson is back in every /learn seat's bundle and must
    # fit the tightest S20 surface budget; the tool description names the fields.
    domain: str
    topic: str
    text: str
    evidence: list[str] = Field(default_factory=list)


class LookupArgs(BaseModel):
    scope: str = Field(description='epic or ticket id (never crosses epics)')
    question: str | None = Field(default=None, description='plain words; or use id/path')
    id: str | None = Field(default=None, description='record/ticket/doc id to start from')
    path: str | None = Field(default=None, description='file path to start from')


def _record_decision(a: RecordDecisionArgs) -> dict[str, Any]:
    return get_client().record_decision(a.scope, a.text, detail=a.detail, replaces=a.replaces,
                                        binding=a.binding, source=a.source, domains=a.domains)


def _record_lesson(a: RecordLessonArgs) -> dict[str, Any]:
    return get_client().record_lesson(a.domain, a.topic, a.text, evidence=a.evidence)


def _record_claim(a: RecordClaimArgs) -> dict[str, Any]:
    return get_client().record_claim(a.scope, a.text, basis=a.basis.value, evidence=a.evidence, source=a.source)


class WithdrawDecisionArgs(BaseModel):
    decision_id: str = Field()
    reason: str = Field(default="", description='one line, <=240 chars')


class WithdrawClaimArgs(BaseModel):
    claim_id: str = Field()
    reason: str = Field(default="", description='one line, <=240 chars')


class SetBindingArgs(BaseModel):
    decision_id: str = Field(description='a live decision')
    binding: bool = Field()
    reason: str = Field(default="", description='one line, <=240 chars')


class DenseSearchArgs(BaseModel):
    scope: str = Field(description='epic or ticket id')
    question: str = Field()
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


class AssembleRulesetArgs(BaseModel):
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

# ============================================================================= consult


class ConsultArgs(BaseModel):
    question: str = Field(description='what to read, or the build brief')
    purpose: ConsultPurpose = Field(default=ConsultPurpose.second_opinion)
    profile: ConsultProfile | None = Field(default=None,
                          description='overrides purpose; only concept/blender write (and take write_dir)')
    context: str = ""
    files: list[str] | None = None
    ticket_id: str | None = Field(default=None, description='post the answer to this thread')
    timeout_s: int = 600
    write_dir: str | None = Field(default=None, description='dir the consultant may write; else read-only')
    thread_id: str | None = Field(default=None, description='resume an earlier consult session')
    images: list[str] | None = Field(default=None, description='png/jpg files to attach (a path in the prompt is not seen)')
    model: ConsultModel | None = Field(default=None, description='omit for the default')


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
    run_id: str = Field(description='omit for your newest run')
    verbose: bool = Field(default=False, description='add write-fence rows')


# S12 (qa finding 18): consult_status returned `answer` twice (top-level + inside the manifest copy)
# and listed ~55 pre-dirty fence rows even for a read-only run. Compacted HERE, in the tool layer.
# Only pre-dirty / concurrent noise is dropped; ATTRIBUTED escapes (real boundary violations) and
# their remediation evidence are always kept — dropping them would hide a real fence breach from qa.
_NOISE_KEYS = ("fence", "concurrent_writes")   # write-fence detail + pre-dirty/concurrent noise


def _has_real_escape(man: dict[str, Any]) -> bool:
    """A run with attributed escapes or a boundary-violation verdict must keep its full fence detail."""
    if man.get("status") == "boundary_violation" or man.get("writes_outside_write_dir"):
        return True
    fence = man.get("fence")
    escapes = fence.get("escapes") if isinstance(fence, dict) else None
    return bool(escapes and any(e.get("action") not in ("pre_dirty_concurrent", "unattributed_concurrent")
                                for e in escapes if isinstance(e, dict)))


def _consult_status(a: ConsultStatusArgs) -> dict[str, Any]:
    from . import consult as consult_mod

    resp = consult_mod.consult_status(a.run_id)
    if a.verbose or not resp.get("ok"):
        return resp
    val = resp.get("value")
    if not isinstance(val, dict):
        return resp
    val = dict(val)
    dropped: list[str] = []
    man = val.get("manifest")
    if isinstance(man, dict):
        man = dict(man)
        # `answer` is already returned once at value.answer — don't ship it a second time
        if man.pop("answer", None) is not None:
            dropped.append("manifest.answer (returned once at value.answer)")
        if not _has_real_escape(man):
            for k in _NOISE_KEYS:
                if man.pop(k, None) is not None:
                    dropped.append(f"manifest.{k}")
        val["manifest"] = man
    if dropped:
        val["omitted"] = {"fields": dropped,
                          "full": f"consult_status(run_id={val.get('run_id')!r}, verbose=True)"}
    return {**resp, "value": val}


CONSULT_TOOLS = [
    ToolDef("consult_status",
            "A consult run's status and recovered answer (once), plus the consult lane and quota block",
            'after a consult returned running or timed out; instead of re-asking',
            'status, answer if any, lane and quota; verbose adds fence rows',
            ConsultStatusArgs, _consult_status, "consult"),
    ToolDef("consult",
            'Ask the consultant for a second opinion, adversarial/creative/visual review, or (write_dir) a build; brief goal and bar',
            'for an independent read or a build; long runs end with consult_done',
            'the answer and run_id, or status running (poll consult_status)',
            ConsultArgs, _consult, "consult"),
]

# ============================================================================= artifact


class ArtifactCreateArgs(BaseModel):
    form: ArtifactForm = Field()
    uri: str = Field(description='a uri, never a machine path')
    note: str = ""
    ticket_id: str | None = Field(default=None, description='link as produced')


class ArtifactUploadArgs(BaseModel):
    path: str = Field(description='workspace file (HTTP policy: absolute, inside configured roots)')
    note: str = ""


class ArtifactReadArgs(BaseModel):
    id: str = Field()


def _artifact_create(a: ArtifactCreateArgs) -> dict[str, Any]:
    return get_client().artifact_create(form=a.form, uri=a.uri, note=a.note, ticket_id=a.ticket_id)


def _artifact_read(a: ArtifactReadArgs) -> dict[str, Any]:
    return get_client().artifact_read(a.id)


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
            'Read one artifact',
            'when a ticket or link names it',
            'the artifact',
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
        + SEARCH_TOOLS + KNOWLEDGE_TOOLS + RULESET_TOOLS + CONSULT_TOOLS + ARTIFACT_TOOLS + CLOSE_TOOLS
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
        + ["find", "consult", "consult_status", "artifact_create", "artifact_read", "spawn", "inbox", "record_status",
           # owner m-268fc869f5 / m-faf46d284a (2026-09-18): the spawner decides and executes recovery of its
           # own seats (the board already scopes these to the architect's own epic, service._authorize_pool_op)
           "reap", "resume", "session_query"],
    Role.sme.value: _IDENTITY + _TICKET_RO + _DOC_RW + _THREAD
        + ["find", "participants", "assemble_ruleset", "criterion_query", "criterion_update",
           "artifact_create", "artifact_read"] + _CLOSING,
    Role.engineer.value: _IDENTITY + _TICKET_RW + _DOC_RW + _THREAD
        + ["find", "participants", "assemble_ruleset", "consult", "consult_status", "artifact_create", "artifact_read"] + _CLOSING,
    Role.adversary.value: _IDENTITY + _TICKET_RW + _DOC_RW + _THREAD
        + ["find", "participants", "assemble_ruleset", "consult", "consult_status", "artifact_create", "artifact_read"] + _CLOSING,
    Role.qa.value: _IDENTITY + _TICKET_RO + _CHECK + _DOC_RW + _THREAD + _BOARD
        + ["find", "assemble_ruleset", "consult", "consult_status", "artifact_create", "artifact_read"] + _CLOSING,
}


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
for _role_tools in ROLE_BUNDLES.values():
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
# preflight stays in every bundle (consult lane: the advisory host check is every seat's)
_S20_UNUSED: dict[str, tuple[str, ...]] = {
    Role.owner.value: ("gate_open", "inbox", "dense_search", "record_lesson", "withdraw_decision",
                       "withdraw_claim", "set_binding"),
    Role.architect.value: ("artifact_read", "dense_search", "gate_answer", "withdraw_claim",
                           "withdraw_decision"),
    Role.engineer.value: ("dense_search", "gate_answer", "gate_open", "gates", "link_delete",
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


def tools_for_role(role: str) -> list[ToolDef]:
    names = ROLE_BUNDLES.get(role, _IDENTITY)  # a retired/unknown role never inherits the owner's tools
    return [ALL_TOOLS[n] for n in names if n in ALL_TOOLS]
