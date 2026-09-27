"""S23 tool-layer metadata: which objects and skills each MCP tool is linked to, and the describe()
contracts of the objects the tool layer owns (the board's OBJECT_TYPES describe the rest).

Owner standards 1 and 5 (s-da61d38c5e): a tool's description names its linked objects, enums and
skills, composed from THIS metadata (never hand-typed prose), and describe(<object>) explains every
object a tool names. tests/test_tool_contract.py enforces both on every registered tool.
"""

from __future__ import annotations

from typing import Any

# tool -> the objects it reads or writes (first = primary). describe(<object>) must answer each one.
TOOL_OBJECTS: dict[str, tuple[str, ...]] = {
    # identity
    "whoami": ("participant",), "preflight": ("service", "session"), "subscribe": ("event",),
    "resume_self": ("session",), "context": ("ticket", "message"), "context_delta": ("event",),
    "describe": ("enum",), "describe_objects": ("enum",), "get_guide": ("guide",),
    # ticket
    "ticket_create": ("ticket",), "ticket_read": ("ticket", "criterion"), "ticket_query": ("ticket",),
    "ticket_update": ("ticket",), "criterion_create": ("criterion",), "criterion_query": ("criterion",),
    "criterion_update": ("criterion", "doc"),
    # doc
    "doc_create": ("doc",), "doc_read": ("doc",), "doc_query": ("doc",), "doc_update": ("doc",),
    "doc_edit": ("doc",), "link_create": ("link",), "link_query": ("link",), "link_delete": ("link",),
    "assemble_ruleset": ("doc",),
    # thread
    "message_send": ("message",), "message_query": ("message",), "message_read": ("message",),
    "gate_open": ("gate",), "gate_answer": ("gate",), "gates": ("gate",), "inbox": ("message",),
    "record_status": ("message",),
    # board
    "board": ("ticket", "gate"), "events_query": ("event",), "participants": ("participant",),
    "find": ("ticket", "doc", "message"),
    # pool
    "close_self": ("session",), "spawn": ("session", "participant"), "resume": ("session",),
    "reap": ("session",), "session_query": ("session",), "close": ("ticket", "session"),
    # knowledge
    "record_decision": ("decision",), "record_claim": ("claim",), "record_lesson": ("lesson",),
    "lookup": ("decision", "claim", "lesson"), "withdraw_decision": ("decision",),
    "withdraw_claim": ("claim",), "set_binding": ("decision",), "dense_search": ("decision",),
    "topic_research": ("topic",), "topic_propose": ("topic", "doc"),
    # artifact
    "artifact_create": ("artifact",), "artifact_read": ("artifact",), "artifact_upload": ("artifact",),
    # doctor
    "doctor_health": ("service",), "doctor_pool": ("session",), "doctor_feed_lag": ("session",),
    "doctor_dead_mail": ("message",), "why_stuck": ("ticket", "gate"), "workflow_check": ("workflow",),
    "doctor_pains": ("pain",), "doctor_logs": ("service",), "propose_fix": ("fix",),
    # S23 framework tools
    "pain": ("pain",), "workflow": ("workflow",), "teammate": ("teammate",),
    "service_status": ("service",), "harvest_cost": ("cost",),
}

# object -> the skills that walk it (named as /skill in every linked tool's description)
OBJECT_SKILLS: dict[str, tuple[str, ...]] = {
    "ticket": ("/ticket",), "criterion": ("/verify",), "artifact": ("/demo",), "doc": ("/methodology",),
    "pain": ("/pain",), "lesson": ("/learn",), "cost": ("/harvest",), "decision": ("/doubt",),
    "gate": ("/epic",), "workflow": ("/epic",),
}


def tool_objects(name: str) -> tuple[str, ...]:
    return TOOL_OBJECTS.get(name, ())


def tool_skills(name: str) -> tuple[str, ...]:
    out: list[str] = []
    for obj in tool_objects(name):
        for s in OBJECT_SKILLS.get(obj, ()):
            if s not in out:
                out.append(s)
    return tuple(out)


def link_clause(name: str) -> str:
    """The fixed advertising clause (architect ruling m-fbd6ae40d3: terse, generated, <=80 B)."""
    objs = tool_objects(name)
    if not objs:
        return ""
    skills = tool_skills(name)
    return f"Objects: {', '.join(objs)}." + (f" Skills: {', '.join(skills)}." if skills else "") + " "


def tools_by_object() -> dict[str, list[str]]:
    """The inverse index describe() reports as each object's `tools`."""
    out: dict[str, list[str]] = {}
    for tool, objs in TOOL_OBJECTS.items():
        for o in objs:
            out.setdefault(o, []).append(tool)
    return out


# Objects the tool layer owns: the board has no OBJECT_TYPES row for them, so describe() answers
# locally (no board round-trip). Each names its fields, contract and where it lives.
LOCAL_OBJECTS: dict[str, dict[str, Any]] = {
    "gate": {
        "contract": "A human decision point on a ticket (one open per gate kind at a time). A seat opens it; "
                    "the owner answers it; an open gate blocks the edge it guards.",
        "fields": {"ticket_id": "the gated ticket", "gate": "the Gate enum (describe('enum:Gate'))",
                   "note": "why it is opened", "answer": "the owner's answer"},
        "enums": ["Gate"], "guides": ["agent-tools"]},
    "topic": {
        "contract": "A Library topic an sme seat researches: topic_research fetches skills.sh/GitHub/the seed "
                    "host with a receipt; topic_propose files a proposed doc the owner approves.",
        "fields": {"topic_id": "the topic", "source_url": "a URL topic_research fetched"},
        "enums": ["DocType"], "guides": ["agent-tools"]},
    "workflow": {
        "contract": "A versioned workflow definition (roles, lifecycle, bundles). Built-in and published versions "
                    "are immutable: duplicate one to a draft, edit, validate, then publish. An epic pins a "
                    "version at creation. Same registry as the Design tab.",
        "fields": {"ref": "id or id@version, e.g. standard@1", "definition": "the full workflow JSON (edit)",
                   "new_id": "duplicate target id"},
        "enums": [], "guides": ["agent-tools"]},
    "pain": {
        "contract": "A pain record: a tool or guide found wrong versus reality. Append-only log; a resolution "
                    "is a new line (latest wins); dup_of folds a duplicate into its original's status; "
                    "supersedes names a record this one replaces.",
        "fields": {"id": "p-xxxxxxxx", "area": "tools|guides|board|pool|...", "symptom": "what happened",
                   "expected": "what should have happened", "evidence": "ids, paths", "severity": "low|medium|high",
                   "workaround": "what you did instead", "status": "open|fixed|invalid|superseded",
                   "dup_of": "an earlier pain id", "supersedes": "a pain id this replaces"},
        "enums": [], "guides": ["agent-tools"]},
    "service": {
        "contract": "A host service the launcher runs (board, broker, pool, mcp, ...): state up/down, pid, port, "
                    "git rev, uptime. Read-only to seats; start/stop/restart is a human action (edp.ps1).",
        "fields": {"service": "name", "state": "up|down", "port": "listen port", "git_rev": "running code",
                   "uptime": "since start"},
        "enums": [], "guides": ["shared-host-rules", "edp-ps1"]},
    "teammate": {
        "contract": "A human participant with a board credential (owner-managed). create registers the human "
                    "and returns a one-time invite link; mint issues a new token and returns it ONCE (never "
                    "logged or stored in events); revoke disables the token; list shows teammates without "
                    "secrets.",
        "fields": {"handle": "the teammate's @handle", "role": "board role (owner by default)",
                   "admin": "grant the admin tier"},
        "enums": [], "guides": ["tailnet-public-mode"]},
    "cost": {
        "contract": "A seat's framework token cost: input/output/cache tokens summed from its transcript "
                    "between two instants, plus the knowledge records it wrote. Bounded totals, no bodies.",
        "fields": {"participant_id": "the seat", "since": "ISO start (default: its harvest trigger)",
                   "until": "ISO end (default: its close)"},
        "enums": [], "guides": ["agent-tools"]},
    "guide": {
        "contract": "A reference guide under the agent home's guides/ (markdown). Cards and tasks name them.",
        "fields": {"name": "guide file name without .md"}, "enums": [], "guides": ["agent-tools"]},
    "enum": {
        "contract": "A strict vocabulary a tool argument takes. describe('enums') lists all, describe('enum:<Name>') "
                    "one; a schema error names the allowed values.",
        "fields": {"name": "enum class name", "values": "allowed values"}, "enums": [], "guides": []},
}
