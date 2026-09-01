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

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from .client import BoardClient
from .schemas import (
    ArtifactForm,
    Check,
    DocType,
    Gate,
    MessageKind,
    Relation,
    Role,
    TicketKind,
    TicketStatus,
    WorkType,
)

# ----------------------------------------------------------------------------- client wiring

_client: BoardClient | None = None


def set_client(client: BoardClient) -> None:
    global _client
    _client = client


def get_client() -> BoardClient:
    if _client is None:
        raise RuntimeError("edp8.bundles: no BoardClient set — call set_client() before invoking a tool handler")
    return _client


def unavailable(message: str, hint: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": "unavailable", "message": message}, "hint": hint}


# ----------------------------------------------------------------------------- tool def


@dataclass
class ToolDef:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[BaseModel], dict[str, Any]]
    bundle: str


# ============================================================================= identity


class SubscribeArgs(BaseModel):
    pass


class ContextArgs(BaseModel):
    ticket_id: str | None = Field(default=None, description="a specific ticket id, or omit for all your tickets")


class DescribeArgs(BaseModel):
    type: str = Field(description="object type: participant|ticket|criterion|doc|link|message|event|artifact|session")


class GetGuideArgs(BaseModel):
    name: str = Field(description="guide file name (without .md), e.g. 'design-template' or 'feed-format'")


class WhoamiArgs(BaseModel):
    pass


def _whoami(_: WhoamiArgs) -> dict[str, Any]:
    resp = get_client().whoami()
    if resp.get("ok"):
        role = resp["value"]["participant"]["role"]
        resp["value"]["role"] = role
        resp["value"]["bundles_available"] = ROLE_BUNDLES.get(role, [])
    return resp


def _subscribe(_: SubscribeArgs) -> dict[str, Any]:
    client = get_client()
    py = sys.executable.replace("\\", "/")  # bash-safe: the Monitor tool runs bash, which eats backslashes
    monitor_cmd = f'"{py}" -m edp8.feed_driver --participant {client.participant} --board {client.base_url}'
    broker = os.environ.get("EDP_BROKER_URL")
    if broker:
        monitor_cmd += f" --broker {broker}"
    return {
        "ok": True,
        "value": {
            "monitor_cmd": monitor_cmd,
            "cron": {
                "expr": "*/30 * * * *",
                "prompt": "edp8 heartbeat: call context() and act only if something is new; if nothing, end the turn silently",
            },
        },
        "hint": "run monitor_cmd under the Monitor tool once (your event+message wake plane); "
                "CronCreate the cron once (the fallback if a wake is missed)",
    }


def _context(args: ContextArgs) -> dict[str, Any]:
    return get_client().context(ticket_id=args.ticket_id)


def _describe(args: DescribeArgs) -> dict[str, Any]:
    return get_client().describe(args.type)


def _edp8_home() -> Path:
    return Path(os.environ.get("EDP8_HOME", str(Path(__file__).resolve().parents[2])))


def _get_guide(args: GetGuideArgs) -> dict[str, Any]:
    p = _edp8_home() / "guides" / f"{args.name}.md"
    if not p.is_file():
        return {"ok": False, "error": {"code": "not_found", "message": f"guide {args.name!r} does not exist"},
                "hint": f"guides live under {p.parent}"}
    return {"ok": True, "value": {"name": args.name, "body": p.read_text(encoding="utf-8")}, "hint": ""}


IDENTITY_TOOLS = [
    ToolDef("whoami", "Report your registered identity and which tool bundles your role has. "
            "Returns the participant record, its open tickets, and the bundle list.",
            WhoamiArgs, _whoami, "identity"),
    ToolDef("subscribe", "Arm your event feed for this session (one-time setup). "
            "Returns the monitor command to run and the heartbeat cron to create.",
            SubscribeArgs, _subscribe, "identity"),
    ToolDef("context", "Load everything needed to act on your ticket(s): chain, criteria, docs, thread, open asks. "
            "Returns one context block per ticket, plus any unanswered questions addressed to you.",
            ContextArgs, _context, "identity"),
    ToolDef("describe", "Look up an object type's shape and one-line contract. "
            "Returns the JSON schema and the contract text for that type.",
            DescribeArgs, _describe, "identity"),
    ToolDef("get_guide", "Fetch one on-demand reference page (a template, a format spec). "
            "Returns the guide's markdown body, or not_found if no such guide exists.",
            GetGuideArgs, _get_guide, "identity"),
]

# ============================================================================= ticket


class TicketCreateArgs(BaseModel):
    kind: TicketKind = Field(description="epic (owner/coordinator) | story (architect) | task (engineer/architect)")
    work_type: WorkType = Field(description="feature|bug|rnd|creative|review|knowledge|chore")
    title: str = Field(description="epic: the owner's words verbatim. story/task: names the slice")
    parent_id: str | None = Field(default=None, description="required for story/task: the parent ticket id")
    assignee: str | None = Field(default=None, description="participant id to assign, if known now")


class TicketReadArgs(BaseModel):
    id: str = Field(description="ticket id")


class TicketQueryArgs(BaseModel):
    kind: TicketKind | None = None
    work_type: WorkType | None = None
    parent_id: str | None = None
    status: TicketStatus | None = None
    assignee: str | None = None


class TicketUpdateArgs(BaseModel):
    id: str = Field(description="ticket id")
    status: TicketStatus | None = Field(default=None, description="a legal next status; see the transition guard")
    assignee: str | None = Field(default=None, description="participant id to assign")
    design_ref: str | None = Field(default=None, description="doc id of the design/plan doc")


class CriterionCreateArgs(BaseModel):
    ticket_id: str
    text: str = Field(description="a checkable definition of done")
    check: Check = Field(description="command|path|look|verdict")
    checked_by: str = Field(description="the role that will verdict this: reviewer|qa|owner")


class CriterionQueryArgs(BaseModel):
    ticket_id: str


class CriterionUpdateArgs(BaseModel):
    model_config = {"extra": "forbid"}  # an unknown kwarg is an ERROR, never a silent drop
    id: str = Field(description="criterion id")
    evidence_ref: str | None = Field(default=None, description="doc id (a report) proving the check")
    verdict: str | None = Field(default=None, description="pending|pass|fail — set after evidence_ref")
    text: str | None = Field(default=None, description="reword the criterion (authors only, while verdict pending)")


def _ticket_create(a: TicketCreateArgs) -> dict[str, Any]:
    return get_client().ticket_create(kind=a.kind, work_type=a.work_type, title=a.title,
                                      parent_id=a.parent_id, assignee=a.assignee)


def _ticket_read(a: TicketReadArgs) -> dict[str, Any]:
    return get_client().ticket_read(a.id)


def _ticket_query(a: TicketQueryArgs) -> dict[str, Any]:
    return get_client().ticket_query(kind=a.kind, work_type=a.work_type, parent_id=a.parent_id,
                                     status=a.status, assignee=a.assignee)


def _ticket_update(a: TicketUpdateArgs) -> dict[str, Any]:
    return get_client().ticket_update(a.id, status=a.status, assignee=a.assignee, design_ref=a.design_ref)


def _criterion_create(a: CriterionCreateArgs) -> dict[str, Any]:
    return get_client().criterion_create(ticket_id=a.ticket_id, text=a.text, check=a.check, checked_by=a.checked_by)


def _criterion_query(a: CriterionQueryArgs) -> dict[str, Any]:
    return get_client().criterion_query(a.ticket_id)


def _criterion_update(a: CriterionUpdateArgs) -> dict[str, Any]:
    return get_client().criterion_update(a.id, evidence_ref=a.evidence_ref, verdict=a.verdict, text=a.text)


TICKET_TOOLS = [
    ToolDef("ticket_create", "Create a ticket (epic by owner/coordinator, story by architect, task by engineer). "
            "Returns the ticket and a hint for the next step.",
            TicketCreateArgs, _ticket_create, "ticket"),
    ToolDef("ticket_read", "Read one ticket with its criteria, linked docs and open gates. "
            "Returns the full ticket record.",
            TicketReadArgs, _ticket_read, "ticket"),
    ToolDef("ticket_query", "List tickets matching filters. Returns matching ticket records.",
            TicketQueryArgs, _ticket_query, "ticket"),
    ToolDef("ticket_update", "Change a ticket's status/assignee/design_ref. Guarded by the transition rules "
            "(e.g. done needs every criterion passed). Returns the updated ticket, or a transition/scope error.",
            TicketUpdateArgs, _ticket_update, "ticket"),
    ToolDef("criterion_create", "Add a checkable definition of done to a ticket, before work starts. "
            "Returns the criterion.",
            CriterionCreateArgs, _criterion_create, "ticket"),
    ToolDef("criterion_query", "List a ticket's criteria. Returns the criterion records.",
            CriterionQueryArgs, _criterion_query, "ticket"),
    ToolDef("criterion_update", "Record evidence_ref then a verdict on a criterion (the checker only; not the doer). "
            "Returns the criterion plus a hint on remaining pending criteria.",
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
    ToolDef("doc_create", "Author a versioned markdown doc (design/strategy/domain/report/note per your role). "
            "Returns the doc and a hint to link it to its ticket.",
            DocCreateArgs, _doc_create, "doc"),
    ToolDef("doc_read", "Read a doc, latest or a specific version. Returns the doc plus the list of versions.",
            DocReadArgs, _doc_read, "doc"),
    ToolDef("doc_query", "List docs matching filters. Returns doc summaries.",
            DocQueryArgs, _doc_query, "doc"),
    ToolDef("doc_update", "Revise a doc's body/title; every update is a new version. Returns the updated doc.",
            DocUpdateArgs, _doc_update, "doc"),
    ToolDef("link_create", "Link a ticket/doc to a doc/artifact/ticket with a typed relation. Returns the link.",
            LinkCreateArgs, _link_create, "doc"),
    ToolDef("link_query", "List links matching filters. Returns the link records.",
            LinkQueryArgs, _link_query, "doc"),
    ToolDef("link_delete", "Remove a link. Returns whether it was deleted.",
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
    ticket_id: str | None = None
    to: str | None = None
    kind: MessageKind | None = None
    limit: int = 50


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
    return get_client().message_query(ticket_id=a.ticket_id, to=a.to, kind=a.kind, limit=a.limit)


def _gate_open(a: GateOpenArgs) -> dict[str, Any]:
    return get_client().gate_open(a.ticket_id, a.gate, note=a.note)


def _gate_answer(a: GateAnswerArgs) -> dict[str, Any]:
    return get_client().gate_answer(a.ticket_id, a.gate, a.answer)


def _gates(a: GatesArgs) -> dict[str, Any]:
    return get_client().gates(a.ticket_id)


THREAD_TOOLS = [
    ToolDef("message_send", "Post to a ticket's thread, addressed to a participant/role/@handle or left as a note. "
            "Returns the message; a question or steer is delivered to the recipient's feed.",
            MessageSendArgs, _message_send, "thread"),
    ToolDef("message_query", "List a ticket's thread messages. Returns matching messages, newest-relevant first.",
            MessageQueryArgs, _message_query, "thread"),
    ToolDef("gate_open", "Open a human gate on a ticket (precondition: none already open for that gate). "
            "Returns the gate_opened event; the owner is notified.",
            GateOpenArgs, _gate_open, "thread"),
    ToolDef("gate_answer", "Answer an open human gate (owner only). Returns the gate_answered event.",
            GateAnswerArgs, _gate_answer, "thread"),
    ToolDef("gates", "List a ticket's currently open gates. Returns the open gate events.",
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
    return get_client().participants(role=a.role)


BOARD_TOOLS = [
    ToolDef("board", "Render an epic's ticket tree with status counts, ready/in_review lists and open gates. "
            "Returns the board view for that epic.",
            BoardArgs, _board, "board"),
    ToolDef("events_query", "Read the audit/feed log, by subject or since a sequence number. "
            "Returns matching events.",
            EventsQueryArgs, _events_query, "board"),
    ToolDef("participants", "List registered participants, optionally by role. Returns participant records.",
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
    model: str | None = None
    mode: str | None = None


class ResumeArgs(BaseModel):
    participant_id: str


class FinishArgs(BaseModel):
    note: str = Field(default="", description="one line: what you finished (post it on your ticket thread first)")


class ParkArgs(BaseModel):
    participant_id: str


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
    if not pid:
        pid = f"{a.role.value}.{ticket_id}"
    got = c.participant_get(pid)
    if not got.get("ok"):
        made = c.participant_create("agent", a.role.value, pid, id=pid)
        if not made.get("ok"):
            return made
    if ticket_id:
        # A checker is never assigned a ticket whose criteria it checks (the doer guard would
        # block its verdicts). But a checker CAN be the doer of a ticket checked by someone
        # else — e.g. a reviewer doing a review-type story whose criteria are checked by qa.
        assign = True
        if a.role.value in ("reviewer", "qa"):
            crits = c.criterion_query(ticket_id)
            rows = crits.get("value") or []
            assign = bool(rows) and all(x.get("checked_by") != a.role.value for x in rows)
        if assign:
            assigned = c.ticket_update(ticket_id, assignee=pid)
            if not assigned.get("ok"):
                return assigned
    args["participant_id"] = pid
    if not args.get("parent_session"):  # lineage: the pool records who spawned this shell
        args["parent_session"] = os.environ.get("EDP_SPAWN_SESSION_ID") or None
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
    return out


def _finish(a: FinishArgs) -> dict[str, Any]:
    """Stand down: ack pending comms first, then close this shell's own session."""
    me = os.environ.get("EDP8_PARTICIPANT") or os.environ.get("EDP_HANDLE")
    if not me:
        return {"ok": False, "error": {"code": "identity", "message": "no participant identity in env"},
                "hint": "EDP8_PARTICIPANT/EDP_HANDLE unset; ask the owner to close you"}
    ctx = get_client().context()
    if ctx.get("ok"):
        pending = [(m.get("id"), m.get("kind"), (m.get("text") or "")[:80])
                   for m in (ctx["value"].get("asks_for_me") or [])]
        if pending:
            listing = "; ".join(f"{i} ({k}): {t}" for i, k, t in pending)
            return {"ok": False,
                    "error": {"code": "precondition",
                              "message": f"{len(pending)} message(s) still await your answer: {listing}"},
                    "hint": "answer or explicitly acknowledge each (message_send kind=answer), then finish"}
    return _pool_call("finish_self", {"participant_id": me})


def _resume(a: ResumeArgs) -> dict[str, Any]:
    return _pool_call("resume", a.model_dump())


def _park(a: ParkArgs) -> dict[str, Any]:
    return _pool_call("park", a.model_dump())


def _reap(a: ReapArgs) -> dict[str, Any]:
    return _pool_call("reap", a.model_dump())


def _session_query(a: SessionQueryArgs) -> dict[str, Any]:
    return get_client().session_query(participant_id=a.participant_id, ticket_id=a.ticket_id, state=a.state)


POOL_TOOLS = [
    ToolDef("finish", "Stand down when your job on the ticket is recorded. Refuses while messages "
            "addressed to you are unanswered (ack them first — the transparency rule). On success the "
            "pool CLOSES this shell after 120s of quiet; disarm your cron (CronDelete) and monitor "
            "(TaskStop) before ending the turn. Post your closing status on the thread first. "
            "Returns the arm result, or the pending-comms list.", FinishArgs, _finish, "pool"),
    ToolDef("spawn", "Start a new session for a role on a ticket (fan-out). "
            "Returns the session, or unavailable if the pool adapter is not configured.",
            SpawnArgs, _spawn, "pool"),
    ToolDef("resume", "Resume a parked/stalled session. Returns the session, or unavailable.",
            ResumeArgs, _resume, "pool"),
    ToolDef("park", "Park a running session for later resume. Returns the session, or unavailable.",
            ParkArgs, _park, "pool"),
    ToolDef("reap", "Tear down a dead/finished session. Returns confirmation, or unavailable.",
            ReapArgs, _reap, "pool"),
    ToolDef("session_query", "List sessions matching filters. Returns matching session records.",
            SessionQueryArgs, _session_query, "pool"),
]

# ============================================================================= search


class FindArgs(BaseModel):
    query: str = Field(description="search text (BM25 + vectors over docs, tickets, threads)")
    k: int = 10
    types: str | None = Field(default=None, description="comma-separated object types to restrict to")


def _find(a: FindArgs) -> dict[str, Any]:
    return get_client().find(a.query, k=a.k, types=a.types)


SEARCH_TOOLS = [
    ToolDef("find", "Semantic search across tickets/docs/messages. Returns ranked hits.",
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
    ToolDef("assemble_ruleset", "Compose the layered ruleset for a ticket (or explicit docs): walks doc "
            "`extends` chains universal-first / most-specific-last, dedupes, and splits into the constructive "
            "view (how to build) and the enforced view (what a checker verifies). Returns the ordered layers "
            "and both views, or a precondition error on a cycle/missing layer.",
            AssembleRulesetArgs, _assemble_ruleset, "ruleset"),
]

# ============================================================================= consult


class ConsultArgs(BaseModel):
    question: str = Field(description="what you want a second, independent read on — or the build/delivery brief")
    purpose: str = Field(default="second_opinion",
                          description="adversary|creative|visual|second_opinion|build — selects the consultant's brief")
    context: str = ""
    files: list[str] | None = None
    ticket_id: str | None = Field(default=None, description="if set, post the answer to this ticket's thread")
    timeout_s: int = 600
    write_dir: str | None = Field(default=None, description="a directory Sol may WRITE (assets delivered there, "
                                  "or files edited in place). Without it Sol is read-only and can only advise")


def _consult(a: ConsultArgs) -> dict[str, Any]:
    from . import consult as consult_mod

    resp = consult_mod.consult(a.purpose, a.question, context=a.context,
                                files=a.files, timeout_s=a.timeout_s, write_dir=a.write_dir)
    if resp.get("ok") and a.ticket_id:
        answer = resp["value"]["answer"]
        get_client().message_send(ticket_id=a.ticket_id, kind="note",
                                  text=f"consultant[{a.purpose}]: {answer}", to=None)
    return resp


CONSULT_TOOLS = [
    ToolDef("consult", "Ask the consultant (GPT Sol) — adversarial review, creative/visual judgment, a second "
            "opinion, or (with write_dir) actual DELIVERY: Sol writes assets into the directory or edits files "
            "in place. Sol cannot return images inline — hand it a write_dir instead. For substantial creative "
            "or build work, consult TWICE: round 1 without write_dir to agree a plan, round 2 passing that plan "
            "back with write_dir to build it — never one-shot a large build. If ticket_id is given, the answer "
            "is also posted as a note to that ticket's thread. Returns the answer (with run log), or "
            "unavailable/timeout/exit on failure.",
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
    ToolDef("artifact_create", "Record a produced thing by uri. Returns the artifact.",
            ArtifactCreateArgs, _artifact_create, "artifact"),
    ToolDef("artifact_read", "Read one artifact. Returns the artifact record.",
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
    return {"ok": True, "value": {"disarm": ["CronDelete <ids you armed>", "TaskStop <monitor>"]},
            "hint": "epic is closed in the record; disarm your wiring"}


CLOSE_TOOLS = [
    ToolDef("close", "Confirm an epic is closed (done/partial) and hand back the wiring to disarm. "
            "Returns the disarm checklist, or a transition error if the epic is not yet closed.",
            CloseArgs, _close, "close"),
]

# ============================================================================= registry

ALL_TOOLS: dict[str, ToolDef] = {
    t.name: t for t in (
        IDENTITY_TOOLS + TICKET_TOOLS + DOC_TOOLS + THREAD_TOOLS + BOARD_TOOLS + POOL_TOOLS
        + SEARCH_TOOLS + RULESET_TOOLS + CONSULT_TOOLS + ARTIFACT_TOOLS + CLOSE_TOOLS
    )
}

_IDENTITY = ["whoami", "subscribe", "context", "describe", "get_guide"]
_TICKET_RW = ["ticket_create", "ticket_read", "ticket_query", "ticket_update", "criterion_create",
              "criterion_query", "criterion_update"]
_TICKET_RO = ["ticket_read", "ticket_query", "ticket_update"]  # owner: sign-off only, guarded by the board
_CHECK = ["criterion_query", "criterion_update"]  # checkers record verdicts (board guards who may)
_DOC_RW = ["doc_create", "doc_read", "doc_query", "doc_update", "link_create", "link_query", "link_delete"]
_DOC_RO = ["doc_read", "doc_query"]
_THREAD = ["message_send", "message_query", "gate_open", "gate_answer", "gates"]
_BOARD = ["board", "events_query", "participants"]

ROLE_BUNDLES: dict[str, list[str]] = {
    # The owner shell is the orchestrator: it spawns every seat (except SMEs —
    # the architect spawns those) and recovers dead ones. No coordinator seat.
    Role.owner.value: _IDENTITY + _THREAD + _BOARD + _DOC_RO + _TICKET_RO + _CHECK
        + ["find", "ticket_create", "spawn", "resume", "reap", "session_query", "close"],
    Role.architect.value: _IDENTITY + _TICKET_RW + _DOC_RW + _THREAD + _BOARD
        + ["find", "consult", "artifact_create", "artifact_read", "spawn", "finish"],
    Role.sme.value: _IDENTITY + _TICKET_RO + _DOC_RW + _THREAD
        + ["find", "assemble_ruleset", "criterion_query", "criterion_update",
           "artifact_create", "artifact_read", "finish"],
    Role.engineer.value: _IDENTITY + _TICKET_RW + _DOC_RW + _THREAD
        + ["find", "assemble_ruleset", "consult", "artifact_create", "artifact_read", "finish"],
    Role.reviewer.value: _IDENTITY + _TICKET_RO + _CHECK + _DOC_RW + _THREAD
        + ["find", "assemble_ruleset", "consult", "artifact_create", "artifact_read", "finish"],
    Role.adversary.value: _IDENTITY + _TICKET_RW + _DOC_RW + _THREAD
        + ["find", "assemble_ruleset", "consult", "artifact_create", "artifact_read", "finish"],
    Role.qa.value: _IDENTITY + _TICKET_RO + _CHECK + _DOC_RW + _THREAD + _BOARD
        + ["find", "assemble_ruleset", "consult", "artifact_create", "artifact_read", "finish"],
}


def tools_for_role(role: str) -> list[ToolDef]:
    names = ROLE_BUNDLES.get(role, ROLE_BUNDLES[Role.owner.value])
    return [ALL_TOOLS[n] for n in names if n in ALL_TOOLS]
