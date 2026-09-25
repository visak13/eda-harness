"""edp8 object model — the ten objects (FRAMEWORK-V8-DRAFT-v2 §3).

Every object is a small typed record with an owner and CRUD. Prose lives only in
Doc.body_md. Nothing here knows about roles' prompts; roles know nothing here
except these shapes (returned by `describe`).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

# ----------------------------------------------------------------------------- enums


class Role(StrEnum):
    owner = "owner"
    coordinator = "coordinator"  # retired seat (kept for old records); the owner shell orchestrates
    architect = "architect"
    sme = "sme"
    engineer = "engineer"
    # "reviewer" is not a role (S-ROLES, owner m-bba708e10e): qa checks stories; the store migrates
    # old reviewer participants/criteria/docs to qa at open (Store._migrate_reviewer_locked)
    adversary = "adversary"
    qa = "qa"
    consultant = "consultant"
    # S-SME-SURFACE (owner m-de07c37d0c): a named human from the owner's team linked to ONE Library topic;
    # its token reaches that topic's page, docs and thread and nothing else (service.topic_actor)
    expert = "expert"


class TicketKind(StrEnum):
    epic = "epic"
    story = "story"
    task = "task"
    # S-SME-SURFACE (owner m-bdfb407429): a Library topic — its own record with no parent, a thread, tags,
    # docs, experts and one resident sme seat; opened and closed by the owner (edp8.topics)
    topic = "topic"


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


class DocStatus(StrEnum):
    """S-LIBRARY (design-34bf11cc07 §4.3): a knowledge doc is in force (active), awaiting the owner
    (proposed: a seat's suggested new doc or new version of an active one), or out of use (retired)."""
    active = "active"
    proposed = "proposed"
    retired = "retired"


# The knowledge kinds the Library tab lists; only these carry tags/status in practice.
KNOWLEDGE_DOC_TYPES = ("strategy_hl", "strategy_ll", "domain")


def normalize_tags(tags: list[str] | None) -> list[str]:
    """Tags are lower-case words, deduped in first-seen order; blanks dropped."""
    out: list[str] = []
    for t in tags or []:
        k = str(t).strip().lower()
        if k and k not in out:
            out.append(k)
    return out


class Relation(StrEnum):
    designed_by = "designed_by"
    uses_strategy = "uses_strategy"
    uses_domain = "uses_domain"
    evidence_for = "evidence_for"
    blocks = "blocks"
    produced = "produced"
    extends = "extends"  # doc -> doc layering: assemble_ruleset composes the chain universal-first
    has_expert = "has_expert"  # topic -> expert participant (S-SME-SURFACE); written by edp8.topics only


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
    withdrawn = "withdrawn"  # retired without a successor (e.g. superseded by a re-curation); kept, never handed out


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
    # S-SME-SURFACE: a topic seat's bounded research fetch: {url, fetched_at, status, bytes, by} — the receipt
    # a proposal's source URL + fetched-at are stamped from (edp8.topics.propose)
    topic_fetched = "topic_fetched"
    binding_changed = "binding_changed"  # a decision's binding flag was set: {decision, from, to, reason, by} (D5 audit)


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
    # a Library topic's config on its own record (t-3e246b5e32 (d)): {seed_url, allowlist, tags_set_by};
    # None on every other ticket and on a topic from before the field (topics.config backfills it once)
    topic_config: dict[str, Any] | None = None


class Criterion(Obj):
    ticket_id: str
    text: str
    check: Check
    checked_by: Literal["qa", "owner", "engineer"]
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
    # S-LIBRARY (design-34bf11cc07 §4.3). Defaults keep every stored row valid without a migration.
    tags: list[str] = Field(default_factory=list)  # stack/product/area words, lower-case
    status: DocStatus = DocStatus.active
    proposes: str | None = None  # a proposed doc: the active doc id it would become the next version of
    source: dict[str, str | None] | None = None  # a proposed doc: {participant, ticket} it came from
    source_url: str | None = None  # an imported doc (skills.sh / raw SKILL.md): its origin, the re-import key
    resolution: str | None = None  # a resolved proposal: "approved -> <id> v<n>" | "rejected"


class Link(Obj):
    from_id: str
    to_id: str
    relation: Relation


class DocumentContext(BaseModel):
    design_ref: str
    reviewed_version: int = Field(ge=1)


SNIPPET_MAX_B = 4096  # CodeContext.snippet cap in UTF-8 bytes (design-449b628cdd §4)
LINE_MAX = 10_000_000  # a line number past this is a producer bug, not a file


def _escaped_len(s: str) -> int:
    """Bytes `s` costs inside a JSON string as the MCP client serialises it (ASCII-escaped)."""
    return len(json.dumps(s, ensure_ascii=True)) - 2


def _bad_char(ch: str) -> bool:
    """Control (C0/C1), format (bidi overrides, zero-width) and line/paragraph separators: a path
    or root carrying one renders spoofed or breaks the anchor line."""
    return unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp")


class CodeAnchor(BaseModel):
    """A message's code anchor AS STORED (epic-91fcd3b370 S4): plain fields, no validators. The store
    re-validates every row on read, so the door rules live on CodeContext below — a later tightening
    of them can never make an already-stored message (and with it its whole thread) unreadable."""
    repo_root: str
    path: str
    line_start: int
    line_end: int
    commit: str | None = None
    dirty: bool = False
    snippet: str
    snippet_sha: str

    def at(self) -> str:
        """`path:L10-20 @abc1234[dirty]` (or `@no-git`), the compact anchor agents read."""
        at = (f"@{self.commit[:7]}" if self.commit else "@no-git") + ("[dirty]" if self.dirty else "")
        return f"{self.path}:L{self.line_start}-{self.line_end} {at}"

    def anchor(self, snippet_cap: int | None = None) -> str:
        """The anchor plus the snippet in a fence longer than any backtick run in it, so code that
        contains ``` cannot break out. `snippet_cap` bounds the snippet in JSON-escaped bytes (what a
        byte-bounded read actually pays: a control char costs 6) and clips on a code-point boundary;
        message_read passes None and gets the whole snippet. `snippet_cap=0` gives the anchor line only."""
        snippet, clipped = self.snippet, ""
        if snippet_cap is not None and _escaped_len(snippet) > snippet_cap:
            lo, hi = 0, len(snippet)  # the longest prefix whose escaped form fits
            while lo < hi:
                mid = (lo + hi + 1) // 2
                lo, hi = (mid, hi) if _escaped_len(snippet[:mid]) <= snippet_cap else (lo, mid - 1)
            total = len(snippet.encode("utf-8"))
            snippet = snippet[:lo]
            if not snippet:
                return f"`{self.at()}` (snippet omitted, {total} B; message_read for it)"
            clipped = f" (snippet clipped to {len(snippet.encode('utf-8'))} of {total} B; message_read for all)"
        fence = "`" * max(3, *(len(r) + 1 for r in re.findall(r"`+", snippet)), 0)
        return f"`{self.at()}`{clipped}\n{fence}\n{snippet}\n{fence}"


class CodeContext(CodeAnchor):
    """The door rules for a code anchor (design-449b628cdd §4): the EDP extension produces it
    (strategyll-ab18531441); POST /v1/messages validates it here, so a bad anchor is a 400 that names
    the field instead of misleading an agent later. Every error is located on a field."""
    model_config = ConfigDict(extra="forbid")  # a typo (`lineStart`) is named, not dropped

    repo_root: str = Field(min_length=1, max_length=1024)  # absolute: the git root, else the open folder
    path: str = Field(min_length=1, max_length=1024)       # relative to repo_root, forward slashes
    line_start: int = Field(ge=1, le=LINE_MAX)            # 1-based, inclusive
    line_end: int = Field(ge=1, le=LINE_MAX)
    commit: str | None = None                             # 40-hex HEAD sha; None = not a git repo
    dirty: bool = False
    snippet: str
    snippet_sha: str                                      # sha256 hex of exactly `snippet`

    @field_validator("repo_root")
    @classmethod
    def _absolute(cls, v: str) -> str:
        if any(_bad_char(ch) for ch in v):
            raise ValueError("must not contain control or format characters")
        if not (PureWindowsPath(v).is_absolute() or v.startswith("/")):
            raise ValueError("must be an absolute path")
        return v

    @field_validator("path")
    @classmethod
    def _relative(cls, v: str) -> str:
        if "\\" in v:
            raise ValueError("must use forward slashes")
        if v.startswith("/") or ":" in v:  # a drive (C:x) or an NTFS stream (a::$DATA)
            raise ValueError("must be relative to repo_root (no '/' start, no ':')")
        if any(seg in ("", ".", "..") or seg != seg.strip() for seg in v.split("/")):
            raise ValueError("must be normalised: no '..', '.', empty or space-padded segments")
        if "`" in v or any(_bad_char(ch) for ch in v):
            raise ValueError("must not contain backticks, control or format characters")
        return v

    @field_validator("line_end")
    @classmethod
    def _order(cls, v: int, info: ValidationInfo) -> int:
        start = info.data.get("line_start")
        if start is not None and v < start:
            raise ValueError("must be >= line_start")
        return v

    @field_validator("commit")
    @classmethod
    def _sha(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"[0-9a-f]{40}", v):
            raise ValueError("must be a 40-char lower-case hex sha, or null outside git")
        return v

    @field_validator("snippet")
    @classmethod
    def _cap(cls, v: str) -> str:
        if len(v.encode("utf-8")) > SNIPPET_MAX_B:
            raise ValueError(f"must be at most {SNIPPET_MAX_B} UTF-8 bytes")
        return v

    @field_validator("snippet_sha")
    @classmethod
    def _digest(cls, v: str, info: ValidationInfo) -> str:
        snippet = info.data.get("snippet")
        if snippet is not None and v != hashlib.sha256(snippet.encode("utf-8")).hexdigest():
            raise ValueError("must be the sha256 hex of snippet")
        return v


ANCHOR_SNIPPET_CAP_B = 1024  # snippet bytes a byte-bounded read (context, context_delta) carries


def code_row(m: Any, snippet_cap: int | None = ANCHOR_SNIPPET_CAP_B) -> dict[str, Any]:
    """The agent-facing form of a message's code anchor: `code_anchor` (rendered, snippet clipped to
    `snippet_cap` escaped bytes). A capped (byte-bounded) read also drops the raw snippet from `code_context`, since
    the anchor already carries it; an uncapped read (message_read) keeps the record intact. Empty for
    a message without one, so callers can always `**code_row(m)`."""
    cc = getattr(m, "code_context", None)
    if cc is None:
        return {}
    raw = cc.model_dump(mode="json", exclude={"snippet"} if snippet_cap is not None else None)
    return {"code_context": raw, "code_anchor": cc.anchor(snippet_cap)}


class QuoteLocator(BaseModel):
    """Where a quote sits in its source AS STORED. A doc: `heading` (derived by the board, the nearest
    markdown heading at or above line_start) + 1-based inclusive lines of that version's body_md. A
    message: an optional 0-based, end-exclusive character range of its text. A code quote keeps its
    place in `QuoteStored.code`."""
    heading: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None


class QuoteContext(BaseModel):
    before: str = ""  # the line(s) just before the passage
    after: str = ""   # the line(s) just after it


class QuoteStored(BaseModel):
    """One quote of a message AS STORED (design-10b21760d9 §14.5): plain fields, no validators, for the
    same reason as CodeAnchor. The door rules live in edp8.quotes; the board verified `text` against
    the source when the message was sent, so `text` is what that source said then."""
    source: Literal["doc", "message", "code"]
    id: str | None = None          # doc id | message id; None for code
    version: int | None = None     # doc version quoted
    author: str | None = None      # a message source's author, stored so the render needs no lookup
    locator: QuoteLocator = Field(default_factory=QuoteLocator)
    text: str
    context: QuoteContext | None = None
    note: str | None = None        # the sender's comment on this passage (steer m-d735e11c27)
    sha: str                       # sha256 hex of text
    code: CodeAnchor | None = None  # a code quote: the S4 anchor (its snippet is `text`)


class Message(Obj):
    ticket_id: str
    to: str | None = None  # participant id | role | @handle | None (thread note)
    kind: MessageKind
    text: str
    reply_to: str | None = None
    document_context: DocumentContext | None = None
    code_context: CodeAnchor | None = None  # epic-91fcd3b370 S4: the code anchor a tag carries
    quotes: list[QuoteStored] = Field(default_factory=list)  # C18: ordered, verified at send; older rows have none
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
    decided_at: datetime | None = None  # when the ruling was MADE (source msg/doc date); scoring +
    # render use it over created_at, which for a backfilled record is only when the record was written


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
    withdrawn_reason: str = Field(default="", max_length=240)  # one line, set when status→withdrawn
    decided_at: datetime | None = None  # when the claim was MADE (source date); scoring/render over created_at


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


# ----------------------------------------------------------------------------- RSI (report-9a85d0418e §7)
# Phase 1 (S18): the self-triggered retrieval regression monitor. Only edp8.rsi writes these three.
class Policy(Obj):
    """One tried retrieval policy (a knob set). Phase 1 holds exactly one incumbent, p-0 = the
    module constants in knowledge.py; later phases add candidates."""
    status: Literal["candidate", "incumbent", "retired", "rejected"] = "candidate"
    parent: str | None = None
    knobs: dict[str, Any] = Field(default_factory=dict)
    bounds_ref: str | None = None
    proposed_by: str = ""
    rationale: str = ""


class RsiRun(Obj):
    """One F0 tripwire run: what triggered it, the full identity it ran under, the per-question
    evidence and the verdict. Holds are not runs (they live in RsiState.last_attempt)."""
    trigger: Literal["bootstrap", "T1", "T2", "manual"]
    stage: Literal["replay", "live"] = "replay"
    policy_id: str = "p-0"
    identity: dict[str, Any] = Field(default_factory=dict)
    per_question: list[dict[str, Any]] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)
    regressions: list[dict[str, Any]] = Field(default_factory=list)
    f0: dict[str, Any] = Field(default_factory=dict)
    f1: dict[str, Any] | None = None
    baseline_run: str | None = None
    verdict: Literal["pass", "regressed", "error"]
    hold_reason: str = ""
    error: str = ""
    finding_msg_id: str | None = None
    tokens: dict[str, Any] | None = None
    wall_s: float | None = None
    peak_rss_mb: float | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class RsiState(Obj):
    """The singleton bookkeeping row (id `rsi-state`): attempt, consumed trigger and last pass are
    kept apart (§3) so a hold or an error never consumes a trigger."""
    last_attempt: dict[str, Any] | None = None
    last_consumed: dict[str, Any] | None = None  # {at, run_id, corpus_fp, code_hash, rows}
    last_pass_run: str | None = None
    in_flight: dict[str, Any] | None = None  # {run_id, lease_until}
    story_watermarks: dict[str, int] = Field(default_factory=dict)


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
    "policy": Policy,
    "rsi_run": RsiRun,
    "rsi_state": RsiState,
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


# S-SME-SURFACE: the tool-facing vocabularies leave out what no seat writes through a generic tool — a topic
# is opened by the owner (POST /v1/topics), an expert is linked by edp8.topics — so the seat tool surface
# does not grow (S20 budget) and a seat is never offered a value the board would refuse.
SeatTicketKind = StrEnum("SeatTicketKind", {k.name: k.value for k in TicketKind if k != TicketKind.topic})
SeatRelation = StrEnum("SeatRelation", {r.name: r.value for r in Relation if r != Relation.has_expert})
SeatRole = StrEnum("SeatRole", {r.name: r.value for r in Role if r != Role.expert})

ENUMS: dict[str, type[StrEnum]] = {
    "SeatTicketKind": SeatTicketKind,
    "SeatRelation": SeatRelation,
    "SeatRole": SeatRole,
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
    "DocStatus": DocStatus,
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
    TicketKind.story: {Role.architect, Role.owner},  # owner: a quick task (S-QUICK, tag `quick`, parent optional)
    TicketKind.task: {Role.engineer, Role.architect},
    TicketKind.topic: {Role.owner},  # S-SME-SURFACE: the owner opens a Library topic
}

# Which roles may write criteria (the parent owner of the ticket).
CRITERION_AUTHORS: set[Role] = {Role.architect, Role.engineer}
CRITERION_CHECKERS: set[Role] = {Role.qa, Role.owner}

# Which roles may author which doc types.
DOC_AUTHORS: dict[DocType, set[Role]] = {
    DocType.design: {Role.architect},
    # S-LIBRARY: the owner authors knowledge in the Library tab (lessons: record_lesson, open to the owner)
    DocType.strategy_hl: {Role.sme, Role.owner},
    DocType.strategy_ll: {Role.sme, Role.owner},
    DocType.domain: {Role.sme, Role.owner},
    DocType.report: {Role.engineer, Role.adversary, Role.qa},
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
    "from the ticket (design §24.1): qa for a story/epic criterion, engineer for a task criterion (a task is its doer's own checklist, "
    "self-verdicted, gating nothing), owner for a knowledge ticket — criterion_create's checked_by argument is "
    "accepted for one release but ignored unless the owner also passes override_reason (recorded as a "
    "criterion_checker_overridden event). CRUD: create, read, update.",
    "doc": "A versioned markdown knowledge unit: design (architect), strategy_hl/strategy_ll/domain (sme, owner), "
    "report (engineer/adversary/qa), note. Every update is a new version. Knowledge docs carry tags and a status "
    "active|proposed|retired: any seat may file a proposed doc (proposes=<active id> for a new version of it); the "
    "owner approves (it becomes active / the target's next version) or rejects (retired). CRUD: create, read, "
    "query(doc_type, scope, tag, status), update.",
    "link": "A typed edge: ticket/doc -> doc/artifact/ticket with a relation. CRUD: create, query, delete.",
    "message": "One unit of a ticket's thread addressed to a participant, role, @handle or nobody. "
    "Kinds: question, answer, steer, status, finding, deviation, note. An optional code_context anchors code: "
    "{repo_root (absolute), path (relative, forward slashes, no '..'), line_start<=line_end (1-based), commit "
    "(40-hex, or null outside git), dirty, snippet (<=4096 UTF-8 bytes), snippet_sha (sha256 hex of snippet)}; "
    "reads render it as `path:Lx-y @sha7[dirty]` plus the fenced snippet. An optional ordered quotes[] (<=20) "
    "cites passages: {source doc|message|code, id, version (doc), locator {line_start, line_end} (doc, 1-based) "
    "or {char_start, char_end} (message, optional), text (<=4096 B, must occur in that source up to whitespace), "
    "context {before, after}, note (<=2000 chars), code (source code: a code_context object)}; a quote the "
    "board cannot verify is a 422 quote_mismatch / quote_source_missing. Reads render each as `> passage` "
    "plus `— <source> v<N> §<heading> L<a-b>` in `quoted`, above text. CRUD: create, read, query.",
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
    "policy": "One retrieval policy (knob set) the RSI loop has tried; status candidate|incumbent|retired|"
    "rejected. Phase 1 holds one incumbent, p-0 = the current constants. Written only by edp8.rsi.",
    "rsi_run": "One RSI F0 tripwire run (trigger bootstrap|T1|T2|manual, identity, per-question required "
    "evidence, verdict pass|regressed|error, finding message id). Written only by edp8.rsi.",
    "rsi_state": "The RSI singleton: last attempt, last consumed trigger, last pass run, single-flight "
    "lease. Written only by edp8.rsi.",
}
