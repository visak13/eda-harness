"""edp8 object model — the ten objects (FRAMEWORK-V8-DRAFT-v2 §3).

Every object is a small typed record with an owner and CRUD. Prose lives only in
Doc.body_md. Nothing here knows about roles' prompts; roles know nothing here
except these shapes (returned by `describe`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ----------------------------------------------------------------------------- enums


class Role(StrEnum):
    owner = "owner"
    coordinator = "coordinator"  # retired seat (kept for old records); the owner shell orchestrates
    architect = "architect"
    sme = "sme"
    engineer = "engineer"
    reviewer = "reviewer"
    adversary = "adversary"
    qa = "qa"
    consultant = "consultant"


class TicketKind(StrEnum):
    epic = "epic"
    story = "story"
    task = "task"


class WorkType(StrEnum):
    feature = "feature"
    bug = "bug"
    rnd = "rnd"
    creative = "creative"
    review = "review"
    knowledge = "knowledge"
    chore = "chore"


class TicketStatus(StrEnum):
    drafted = "drafted"
    designed = "designed"
    signed_off = "signed_off"
    ready = "ready"
    in_progress = "in_progress"
    in_review = "in_review"
    blocked = "blocked"
    done = "done"
    partial = "partial"
    dropped = "dropped"


class Check(StrEnum):
    command = "command"
    path = "path"
    look = "look"
    verdict = "verdict"


class Verdict(StrEnum):
    pending = "pending"
    passed = "pass"
    failed = "fail"


class DocType(StrEnum):
    design = "design"
    strategy_hl = "strategy_hl"
    strategy_ll = "strategy_ll"
    domain = "domain"
    report = "report"
    note = "note"


class Relation(StrEnum):
    designed_by = "designed_by"
    uses_strategy = "uses_strategy"
    uses_domain = "uses_domain"
    evidence_for = "evidence_for"
    blocks = "blocks"
    produced = "produced"
    extends = "extends"  # doc -> doc layering: assemble_ruleset composes the chain universal-first


class MessageKind(StrEnum):
    question = "question"
    answer = "answer"
    steer = "steer"
    status = "status"
    finding = "finding"
    deviation = "deviation"
    note = "note"


class EventKind(StrEnum):
    status_changed = "status_changed"
    gate_opened = "gate_opened"
    gate_answered = "gate_answered"
    assigned = "assigned"
    doc_updated = "doc_updated"
    message_sent = "message_sent"
    shell_dead = "shell_dead"
    shell_stalled = "shell_stalled"
    ticket_created = "ticket_created"
    criterion_checked = "criterion_checked"  # a verdict landed: {criterion, verdict, by, by_type, evidence, ticket}


class Gate(StrEnum):
    design_signoff = "design_signoff"
    poc = "poc"
    demo = "demo"
    adversarial = "adversarial"
    budget = "budget"
    acceptance = "acceptance"


class ArtifactForm(StrEnum):
    image = "image"
    file = "file"
    url = "url"
    app = "app"
    repo_ref = "repo_ref"


class SessionState(StrEnum):
    alive = "alive"
    stalled = "stalled"
    dead = "dead"
    parked = "parked"


# ----------------------------------------------------------------------------- base


def now() -> datetime:
    return datetime.now(UTC)


class Obj(BaseModel):
    id: str
    created_at: datetime = Field(default_factory=now)
    created_by: str = ""  # participant id


# ----------------------------------------------------------------------------- objects


class Participant(Obj):
    type: Literal["human", "agent"]
    role: Role
    handle: str  # @handle — inbox address
    location: str | None = None  # pool id
    model: str | None = None


class Ticket(Obj):
    kind: TicketKind
    work_type: WorkType
    title: str  # epic: the owner's words verbatim
    parent_id: str | None = None
    status: TicketStatus = TicketStatus.drafted
    assignee: str | None = None  # participant id
    design_ref: str | None = None  # doc id


class Criterion(Obj):
    ticket_id: str
    text: str
    check: Check
    checked_by: Literal["reviewer", "qa", "owner"]
    evidence_ref: str | None = None  # doc id (report)
    verdict: Verdict = Verdict.pending


class Doc(Obj):
    doc_type: DocType
    title: str
    body_md: str
    version: int = 1
    owner_role: Role
    scope: str  # epic_id | domain:<name> | global


class Link(Obj):
    from_id: str
    to_id: str
    relation: Relation


class Message(Obj):
    ticket_id: str
    to: str | None = None  # participant id | role | @handle | None (thread note)
    kind: MessageKind
    text: str
    reply_to: str | None = None


class Event(Obj):
    subject_id: str
    kind: EventKind
    data: dict[str, Any] = Field(default_factory=dict)


class Artifact(Obj):
    form: ArtifactForm
    uri: str
    note: str = ""


class Session(Obj):
    participant_id: str
    ticket_id: str | None = None
    pool_id: str
    state: SessionState = SessionState.alive
    resume_token: str = ""
    last_output_at: datetime | None = None
    reason: str = ""  # why the shell ended (finish/reaped/clean exit/process gone) — "" while alive


OBJECT_TYPES: dict[str, type[Obj]] = {
    "participant": Participant,
    "ticket": Ticket,
    "criterion": Criterion,
    "doc": Doc,
    "link": Link,
    "message": Message,
    "event": Event,
    "artifact": Artifact,
    "session": Session,
}

# ----------------------------------------------------------------------------- transitions

# Legal ticket transitions. Guards beyond shape live in board.py.
TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.drafted: {TicketStatus.designed, TicketStatus.dropped},
    TicketStatus.designed: {TicketStatus.signed_off, TicketStatus.drafted, TicketStatus.dropped},
    TicketStatus.signed_off: {TicketStatus.ready, TicketStatus.drafted, TicketStatus.dropped},
    TicketStatus.ready: {TicketStatus.in_progress, TicketStatus.blocked, TicketStatus.dropped},
    TicketStatus.in_progress: {
        TicketStatus.in_review,
        TicketStatus.blocked,
        TicketStatus.partial,
        TicketStatus.dropped,
    },
    TicketStatus.in_review: {TicketStatus.done, TicketStatus.in_progress, TicketStatus.partial},
    TicketStatus.blocked: {TicketStatus.ready, TicketStatus.in_progress, TicketStatus.dropped},
    TicketStatus.done: set(),
    TicketStatus.partial: {TicketStatus.in_progress},
    TicketStatus.dropped: set(),
}

# Which roles may create which ticket kinds.
TICKET_CREATORS: dict[TicketKind, set[Role]] = {
    TicketKind.epic: {Role.owner, Role.coordinator},
    TicketKind.story: {Role.architect},
    TicketKind.task: {Role.engineer, Role.architect},
}

# Which roles may write criteria (the parent owner of the ticket).
CRITERION_AUTHORS: set[Role] = {Role.architect, Role.engineer}
CRITERION_CHECKERS: set[Role] = {Role.reviewer, Role.qa, Role.owner}

# Which roles may author which doc types.
DOC_AUTHORS: dict[DocType, set[Role]] = {
    DocType.design: {Role.architect},
    DocType.strategy_hl: {Role.sme},
    DocType.strategy_ll: {Role.sme},
    DocType.domain: {Role.sme},
    DocType.report: {Role.engineer, Role.reviewer, Role.adversary, Role.qa},
    DocType.note: set(Role),
}

# Describe text: what `describe(type)` returns — the schema plus the one-line contract.
DESCRIBE: dict[str, str] = {
    "participant": "An actor (human or agent) with a role, an @handle inbox, and a location (pool). "
    "Owner: registry. CRUD: create, read, query, update(location, model).",
    "ticket": "A work item: epic (the owner's words verbatim as title) / story / task. Status is derived "
    "upward by the board. Owner: architect (epic design, stories), engineer (tasks). CRUD: create, read, "
    "query, update(status, assignee, design_ref). Has criteria, a thread, linked docs and artifacts.",
    "criterion": "A checkable definition of done on a ticket, written by the parent owner before work; "
    "the doer never edits it; the checker records verdict + evidence_ref. CRUD: create, read, update.",
    "doc": "A versioned markdown knowledge unit: design (architect), strategy_hl/strategy_ll/domain (sme), "
    "report (engineer/reviewer/qa), note. Every update is a new version. CRUD: create, read, query, update.",
    "link": "A typed edge: ticket/doc -> doc/artifact/ticket with a relation. CRUD: create, query, delete.",
    "message": "One unit of a ticket's thread addressed to a participant, role, @handle or nobody. "
    "Kinds: question, answer, steer, status, finding, deviation, note. CRUD: create, read, query.",
    "event": "Board-emitted audit + feed item (status_changed, gate_opened, ...). CRUD: query.",
    "artifact": "A produced thing by uri (never a machine path). CRUD: create, read, query.",
    "session": "A running/parked shell for a participant on a ticket (pool-owned). CRUD: read, query.",
}
