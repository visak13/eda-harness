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


class CheckedBy(StrEnum):
    """The checker role a criterion is verdicted by (a strict subset of Role). A task's criterion
    is `engineer` — the task is the doer's own checklist, self-verdicted, and gates nothing."""
    reviewer = "reviewer"
    qa = "qa"
    owner = "owner"
    engineer = "engineer"


class ConsultPurpose(StrEnum):
    """consult(purpose=…) — selects the consultant's brief."""
    adversary = "adversary"
    creative = "creative"
    visual = "visual"
    second_opinion = "second_opinion"
    build = "build"


class ConsultProfile(StrEnum):
    """consult(profile=…) — the codex-exec invocation (sandbox/effort/MCP+feature set)."""
    design = "design"
    concept = "concept"
    blender = "blender"
    verify = "verify"
    direct = "direct"


class ConsultModel(StrEnum):
    """consult(model=…) — the consultant model for one call."""
    astra = "gpt-6-astra"
    # gpt-5.6-sol RETIRED (owner ruling 2026-09-10): never a valid consult model again; the bridge
    # refuses any other model name at the choke point (consult.ALLOWED_MODELS) as well.


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


class DecisionStatus(StrEnum):
    live = "live"           # in force; binding ones are always handed to agents in scope
    replaced = "replaced"   # a newer decision names it in replaces[]; kept, never handed out
    withdrawn = "withdrawn"  # retracted without a successor


class ClaimBasis(StrEnum):
    assumption = "assumption"
    measured = "measured"
    ruled = "ruled"


class ClaimStatus(StrEnum):
    open = "open"
    confirmed = "confirmed"
    refuted = "refuted"


class LessonStatus(StrEnum):
    live = "live"
    retired = "retired"


class LinkKind(StrEnum):
    """Knowledge-graph edge kinds (design-d2c4f39fc6 §3), distinct from product `Relation`.
    Only decides/replaces/must_follow/learned_from are written on purpose; part_of/came_from/
    touches are derived (parent, source ticket, git)."""
    part_of = "part_of"
    decides = "decides"
    replaces = "replaces"
    must_follow = "must_follow"
    implements = "implements"
    verifies = "verifies"
    proves = "proves"
    came_from = "came_from"
    learned_from = "learned_from"
    touches = "touches"


class MessageKind(StrEnum):
    question = "question"
    answer = "answer"
    steer = "steer"
    status = "status"
    finding = "finding"
    deviation = "deviation"
    note = "note"


class StatusValue(StrEnum):
    """What a seat records about its own work before it closes (record_status)."""
    done = "done"
    deferred = "deferred"
    failed = "failed"
    blocked = "blocked"
    reviewed = "reviewed"
    handed_off = "handed_off"


class EventKind(StrEnum):
    status_recorded = "status_recorded"  # a seat recorded its work outcome: {participant, status, ticket, message}
    status_changed = "status_changed"
    gate_opened = "gate_opened"
    gate_answered = "gate_answered"
    design_reviewed = "design_reviewed"
    gate_closed = "gate_closed"  # a gate retired without a human answer (§24.1(a): its epic dropped/closed)
    assigned = "assigned"
    doc_updated = "doc_updated"
    message_sent = "message_sent"
    shell_dead = "shell_dead"
    shell_stalled = "shell_stalled"
    ticket_created = "ticket_created"
    ticket_updated = "ticket_updated"  # a non-status field changed: {changed: [field...], by} (ruling #32: title)
    # a verdict landed: {criterion, verdict, by, by_type, evidence, ticket, check, checked_by}
    criterion_checked = "criterion_checked"
    # owner overrode the derived checker: {criterion, from, to, reason, by}
    criterion_checker_overridden = "criterion_checker_overridden"
    service_restarted = "service_restarted"  # launcher restarted a shared service: {service, reason, by, git_rev} (design §22)


class Reason(StrEnum):
    """Why one participant is woken for one event — the vocabulary of delivery.delivery_plan
    (design §16.2 rule 0). One event can yield several reasons for the same recipient; the
    feed's one-clause `why` picks the highest-priority one (Board._primary)."""
    addressed = "addressed"            # the message's `to` is you (or your role, on your epic)
    mention = "mention"                # @you in the text
    on_ticket = "on_ticket"            # you work the subject ticket
    ancestor_seat = "ancestor_seat"    # you work an ancestor of the subject ticket
    architect_listener = "architect_listener"  # you are the epic's architect, crucial event (rule 1)
    owner_listener = "owner_listener"  # you are the epic's human owner, spawn/decision event (rule 2)
    gate_party = "gate_party"          # a gate you can answer / opened / worked the subtree of
    recovery = "recovery"              # empty plan for a question/deviation fell back to you (rule 3)


class Gate(StrEnum):
    design_signoff = "design_signoff"
    poc = "poc"
    demo = "demo"
    adversarial = "adversarial"
    budget = "budget"
    acceptance = "acceptance"
    scope = "scope"  # the owner raises a story/criteria cap by answering this (design §24.1)


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
    title: str  # a short human title (<= 80 chars); story/task: names the slice (ruling #32, 2026-09-10)
    words: str | None = None  # epic only: the owner's verbatim request — immutable after create (design §1)
    parent_id: str | None = None
    status: TicketStatus = TicketStatus.drafted
    assignee: str | None = None  # participant id
    design_ref: str | None = None  # doc id
    description: str = ""  # the slice in prose: scope, intent, pointers — searchable (2026-09-06)
    tags: list[str] = Field(default_factory=list)  # free labels for filtering/grouping
    epic_id: str | None = None  # derived by the board at create time (an epic's own id for an epic)


class Criterion(Obj):
    ticket_id: str
    text: str
    check: Check
    checked_by: Literal["reviewer", "qa", "owner", "engineer"]
    evidence_ref: str | None = None  # doc id (report)
    evidence_version: int | None = None  # the doc version this verdict signed off (design §14 finding 3)
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


class DocumentContext(BaseModel):
    design_ref: str
    reviewed_version: int = Field(ge=1)


class Message(Obj):
    ticket_id: str
    to: str | None = None  # participant id | role | @handle | None (thread note)
    kind: MessageKind
    text: str
    reply_to: str | None = None
    document_context: DocumentContext | None = None
    status: StatusValue | None = None  # set on kind=status messages written by record_status
    # finalised upload artifacts this message carries (R1): ids only, bytes stay behind the
    # authenticated /v1/artifacts/{id}/content route; older rows have none.
    artifacts: list[str] = Field(default_factory=list)


class Event(Obj):
    subject_id: str
    kind: EventKind
    data: dict[str, Any] = Field(default_factory=dict)


class Artifact(Obj):
    form: ArtifactForm
    uri: str
    note: str = ""
    # uploaded-file artifacts (design §18.1). staged=true means uploaded but not yet finalised
    # via a message — invisible to every list/page/link query and swept after 24 h if never used.
    staged: bool = False
    content_type: str = ""  # sniffed MIME type (never the client's claim)
    filename: str = ""      # original client filename, for the download name only


class Session(Obj):
    participant_id: str
    ticket_id: str | None = None
    pool_id: str
    state: SessionState = SessionState.alive
    resume_token: str = ""
    last_output_at: datetime | None = None
    reason: str = ""  # why the shell ended (finish/reaped/clean exit/process gone) — "" while alive
    # set when a liveness sweep could not get a fresh answer for a LIVE row: the state shown is
    # the last known one, not a probed truth. The UI renders "Presence not refreshed" (S10) —
    # silence is never rendered as Closed (design §18.3). Cleared on the next positive answer.
    presence_stale_since: datetime | None = None


class Decision(Obj):
    """What is in force (design-d2c4f39fc6 §3). Written at the moment a ruling is made,
    never guessed after. A new decision that names an older one in replaces[] flips that
    older one to `replaced` in the same transaction, across any ticket or thread."""
    scope: str  # epic id | ticket id — the isolation boundary
    text: str = Field(max_length=240)  # one sentence
    detail: str = Field(default="", max_length=1000)  # WHY the choice was made, in detail
    status: DecisionStatus = DecisionStatus.live
    replaces: list[str] = Field(default_factory=list)  # decision ids this supersedes
    binding: bool = False  # true = always handed to agents in scope, never cut by lookup
    source: str | None = None  # message | doc | attachment id it came from
    decided_by: str = ""  # participant id
    domains: list[str] = Field(default_factory=list)  # domain checklist names it touches
    withdrawn_reason: str = Field(default="", max_length=240)  # one line, set when status→withdrawn


class Claim(Obj):
    """Something stated but not yet shown (design-d2c4f39fc6 §3): keeps assumptions apart
    from facts. Counts as a fact only when evidence is non-empty and basis is measured|ruled;
    lookup labels everything else unconfirmed."""
    scope: str
    text: str  # one sentence (no hard char cap — a claim can be a full sentence; design §3)
    basis: ClaimBasis = ClaimBasis.assumption
    evidence: list[str] = Field(default_factory=list)  # attachment | check | commit ids
    status: ClaimStatus = ClaimStatus.open
    source: str | None = None


class Lesson(Obj):
    """Reusable across epics (design-d2c4f39fc6 §3): filed by topic, not by epic, so lookup
    finds it from any epic by domain/topic. The cap/self-improvement loop is a later story."""
    domain: str
    topic: str
    text: str  # one sentence (design §3; no hard char cap)
    evidence: list[str] = Field(default_factory=list)  # defect | rework | ruling ids
    uses: int = Field(default=0, ge=0)
    helped: int = Field(default=0, ge=0)
    harmed: int = Field(default=0, ge=0)
    status: LessonStatus = LessonStatus.live


class KgLink(Obj):
    """One knowledge-graph edge (design-d2c4f39fc6 §3). Separate from product `Link` so
    lookup walks only knowledge edges and product links stay untouched."""
    from_id: str
    to_id: str
    kind: LinkKind


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
    "decision": Decision,
    "claim": Claim,
    "lesson": Lesson,
    "kglink": KgLink,
}

# Every strict-valued enum in the model + the consult tool args, keyed by class name.
# `describe('enums')` lists them; `describe('enum:<Name>')` returns one. The description
# composer (bundles.py) and the error envelopes read allowed values from here so a
# tool's allowed set can never drift from its schema (design §19 rule 3).
class SeatEffort(StrEnum):
    low = 'low'
    medium = 'medium'
    high = 'high'


class SpawnMode(StrEnum):
    headless = 'headless'
    monitor = 'monitor'


ENUMS: dict[str, type[StrEnum]] = {
    'SeatEffort': SeatEffort,
    'SpawnMode': SpawnMode,
    "Role": Role,
    "TicketKind": TicketKind,
    "WorkType": WorkType,
    "TicketStatus": TicketStatus,
    "Check": Check,
    "Verdict": Verdict,
    "CheckedBy": CheckedBy,
    "DocType": DocType,
    "Relation": Relation,
    "MessageKind": MessageKind,
    "DecisionStatus": DecisionStatus,
    "ClaimBasis": ClaimBasis,
    "ClaimStatus": ClaimStatus,
    "LessonStatus": LessonStatus,
    "LinkKind": LinkKind,
    "StatusValue": StatusValue,
    "Gate": Gate,
    "ArtifactForm": ArtifactForm,
    "SessionState": SessionState,
    "EventKind": EventKind,
    "ConsultPurpose": ConsultPurpose,
    "ConsultProfile": ConsultProfile,
    "ConsultModel": ConsultModel,
}


def enum_values(name: str) -> list[str] | None:
    e = ENUMS.get(name)
    return [m.value for m in e] if e is not None else None

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
    "ticket": "A work item: epic (the owner's verbatim request in `words`, a short derived title) / story / "
    "task, with a description "
    "and tags. Status is derived upward by the board. Owner: architect (epic design, stories), engineer "
    "(tasks). CRUD: create, read (ticket_read = one fat read: chain, criteria, docs+relation, children+roles, "
    "blockers, gates, thread tail), query(kind, status, assignee, epic_id, created_by, tag, q text), "
    "update(status, assignee, design_ref, description, tags, title — words never change). Has criteria, "
    "a thread, linked docs and artifacts.",
    "criterion": "A checkable definition of done on a ticket, written by the parent owner before work; "
    "the doer never edits it; the checker records verdict + evidence_ref. The board DERIVES the checker "
    "from the ticket (design §24.1): qa for a story/epic criterion, reviewer only when a story "
    "is tagged review_required, engineer for a task criterion (a task is its doer's own checklist, "
    "self-verdicted, gating nothing), owner for a knowledge ticket — criterion_create's checked_by argument is "
    "accepted for one release but ignored unless the owner also passes override_reason (recorded as a "
    "criterion_checker_overridden event). CRUD: create, read, update.",
    "doc": "A versioned markdown knowledge unit: design (architect), strategy_hl/strategy_ll/domain (sme), "
    "report (engineer/reviewer/qa), note. Every update is a new version. CRUD: create, read, query, update.",
    "link": "A typed edge: ticket/doc -> doc/artifact/ticket with a relation. CRUD: create, query, delete.",
    "message": "One unit of a ticket's thread addressed to a participant, role, @handle or nobody. "
    "Kinds: question, answer, steer, status, finding, deviation, note. CRUD: create, read, query.",
    "event": "Board-emitted audit + feed item (status_changed, gate_opened, ...). CRUD: query.",
    "artifact": "A produced thing by uri (never a machine path). CRUD: create, read, query.",
    "session": "A running/parked shell for a participant on a ticket (pool-owned). CRUD: read, query.",
    "decision": "What is in force in an epic/ticket: one sentence + WHY (detail), a status "
    "(live|replaced|withdrawn), the ids it replaces, a binding flag (always handed to agents in scope), "
    "its source and who decided it. record_decision writes one and flips replaced ones in one "
    "transaction. Found by lookup, isolated to its epic.",
    "claim": "Something stated but not yet shown: text, basis (assumption|measured|ruled), evidence ids, "
    "status (open|confirmed|refuted). A fact only when evidence is non-empty and basis is measured|ruled. "
    "record_claim writes one; lookup labels it confirmed/unconfirmed.",
    "lesson": "A reusable lesson filed by domain+topic (not by epic), so lookup finds it across epics. "
    "Carries uses/helped/harmed counts for the self-improvement loop (a later story).",
    "kglink": "One knowledge-graph edge (part_of|decides|replaces|must_follow|implements|verifies|proves|"
    "came_from|learned_from|touches) between any two records/objects; separate from the product `link`. "
    "lookup walks these; only decides/replaces/must_follow/learned_from are written on purpose.",
}
