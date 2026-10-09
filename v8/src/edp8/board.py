"""edp8 board — the six invariants and nothing else (FRAMEWORK-V8-DRAFT-v2 §2).

1. schema          — every write is typed (pydantic in schemas.py)
2. identity/scope  — a participant writes what it owns / is assigned; reads are open
3. transitions     — legal status moves; done needs evidence + a checker other than the doer
4. human gates     — the board opens a gate and notifies; a human answers
5. capacity        — (pool adapter) spawns beyond capacity queue
6. continuity      — context() is complete; sessions are preserved per ticket

Every mutating method takes `actor` (a Participant) and returns the object; a
violation raises BoardError(code, message, hint) with the legal values.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from contextvars import ContextVar
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

from edp_contracts.roles import is_non_agent, non_agent_refusal

from . import advice
from . import epic_work
from . import requirements as requirements_mod
from . import doc_tools, epic_policy, guest_scope, harness, knowledge, lesson_scope, records, seat_choice
from . import workflow as wflow
from .quotes import render_quotes, with_quotes
from .schemas import (
    DECISION_DETAIL_MAX,
    DECISION_TEXT_MAX,
    Artifact,
    ArtifactForm,
    Check,
    CheckedBy,
    Claim,
    ClaimBasis,
    ClaimStatus,
    CodeContext,
    Criterion,
    Decision,
    DecisionStatus,
    Doc,
    DocStatus,
    DocType,
    Event,
    EventKind,
    Gate,
    KgLink,
    Lesson,
    LessonScope,
    LessonStatus,
    Link,
    LinkKind,
    Message,
    MessageKind,
    Participant,
    QuoteStored,
    Reason,
    Relation,
    Role,
    RoleId,
    Session,
    SessionState,
    StatusValue,
    Ticket,
    TicketKind,
    TicketStatus,
    Verdict,
    WorkType,
    code_row,
    normalize_tags,
    now,
)
from .store import Store, new_id

_MENTION_RX = re.compile(r"@([A-Za-z0-9][A-Za-z0-9_.\-]*)")
# Mention tokeniser contract (adversary round 2 #6, tests/fixtures/mention_cases.json — shared with
# the SPA composer): an @handle counts only when it is NOT inside an inline code span or a fenced
# block, and is preceded by start-of-text or a character that is neither a word char nor one of
# `.@-` (so `alice@bob` / `x@bob.com` are emails). A trailing `.`/`,` is punctuation, not handle.
_MENTION_TOKEN_RX = re.compile(r"(?<![\w.@\-])@([A-Za-z0-9][A-Za-z0-9_.\-]*)")
_FENCE_RX = re.compile(r"```.*?(?:```|$)", re.S)
_INLINE_CODE_RX = re.compile(r"`[^`\n]*`")


def _mention_handles(text: str) -> list[str]:
    """The @handles `text` addresses, in order, duplicates kept (the board maps them to participants
    and drops the unresolvable ones as prose). Code spans and fences never mention anyone."""
    plain = _INLINE_CODE_RX.sub(" ", _FENCE_RX.sub(" ", text or ""))
    out: list[str] = []
    for h in _MENTION_TOKEN_RX.findall(plain):
        h = h.rstrip(".,")
        if h:
            out.append(h)
    return out
_log = logging.getLogger("edp8.board")
HANDLE_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{1,47}$")  # S12 sweep #3: a handle is a path-safe slug
# The Standard workflow's source (S13): the board reads gate answerers, caps and every table below from the
# epic's pinned workflow (edp8.workflow); these constants only build Standard@1.
HUMAN_GATE_ANSWERERS = {Role.owner}
#: t-cfd8462f9d (owner m-fcb4463e1e: "a decision on the epic without any text?"): the plain-words question each
#: gate kind asks, used when the board opens a gate itself and for any legacy gate stored with a blank note.
#: {title} is the ticket's own title; acceptance on an epic reads its story count instead (Board.gate_question).
GATE_QUESTIONS = {
    "design_signoff": "Sign off the design for “{title}”: approve it to release the stories, or send it back "
                      "saying what to change.",
    "acceptance": "“{title}” is ready for acceptance: accept it (done or partial), or send it back.",
    "scope": "“{title}” is over its story or criteria cap: approve the larger scope, or ask for a split.",
}
_EPIC_ACCEPTANCE_Q = ("Every story on “{title}” is in review ({n} {stories}). qa is giving its verdicts; once "
                      "qa's report passes, accept the epic here: done, partial, or send back.")
_TERMINAL = (TicketStatus.done, TicketStatus.partial, TicketStatus.dropped)
# a pool reason that is the owner's or the seat's own act, never a failure (no crash notice, no owner page)
CLEAN_CLOSE_REASONS = ("closed by self", "reaped", "clean exit", "interrupted", "closed by owner",
                       "closed by architect")
# of those, the closes that park a seat on purpose: no fresh checker is queued to undo them
PARKED_CLOSE_REASONS = ("closed by self: deferred", "reaped", "interrupted", "closed by owner", "closed by architect")
#: v34 (owner m-8aa6439a77): the only statuses to a human that wait on them; a plain status is an update
ASK_STATUSES = (StatusValue.blocked, StatusValue.failed, StatusValue.deferred)
#: kinds that wait on their addressee (a status waits only when it is one of ASK_STATUSES)
# The seat close being processed on THIS thread/task: its dead-qa and unread-message hints fold into one. A ContextVar, not
# Board state: request handlers run in a threadpool, so two closes at once must never see each other's fold.
_CLOSE_FOLD: ContextVar[dict[str, Any] | None] = ContextVar("close_fold", default=None)
_MESSAGE_ID = re.compile(r"\bm-[0-9a-f]{10}\b")  # a message id as a seat cites it in its own text
ASK_KINDS = (MessageKind.question, MessageKind.steer, MessageKind.deviation)
#: e0cec S3 phase_past: a ticket's lifecycle order. An ask records the status it was asked in; the ticket moving to a
#: higher rank (or leaving `blocked`) settles it. `blocked` sits beside in_progress; the terminal three share the top.
PHASE_RANK = {"drafted": 0, "designed": 1, "signed_off": 2, "ready": 3, "in_progress": 4, "blocked": 4,
              "in_review": 5, "done": 6, "partial": 6, "dropped": 6}


def is_ask(m: "Message") -> bool:
    """Whether a message waits on its addressee: a question/steer/deviation, or a blocked/failed/deferred status."""
    return m.kind in ASK_KINDS or (m.kind == MessageKind.status and m.status in ASK_STATUSES)


def phase_is_past(asked_in: str | None, now: str) -> bool:
    """The ticket has moved past the status an ask was made in (a status the ask never recorded never resolves)."""
    if asked_in not in PHASE_RANK or now not in PHASE_RANK:
        return False
    if asked_in == "blocked":
        return now != "blocked"
    return PHASE_RANK[now] > PHASE_RANK[asked_in]

# Design §24.1 caps — the tool layer bounds what an architect can file, so an epic's shell
# count is bounded by construction, not restraint. Enforced in the board (not the cards).
STORY_CAP = 8    # stories per epic (not counting done/dropped); the owner raises it via a scope gate
TASK_CAP = 5     # tasks per story (not counting done/dropped)
CRITERIA_CAP = 6  # criteria written fresh on a story (a folded story carries what it inherits)
# S-QUICK (design-34bf11cc07 §4.2, owner m-5b3db5cb0d): the owner's own small task is a STORY tagged
# `quick`, usually with no epic parent. Its words are the design (it starts `ready`, no design_ref), its
# engineer writes the criteria, and the owner checks them on the ticket page — no architect, no qa seat.
QUICK_TAG = "quick"
FOR_YOU_KEEP = 5  # context(): newest messages addressed to the seat kept per ticket, ahead of the thread window
RECALL_TICKETS = 3  # context() without a ticket_id carries recall for at most this many tickets (S-IMPLICIT)


def is_quick(t: Ticket) -> bool:
    """A quick task: a story carrying the `quick` tag (S-QUICK)."""
    return t.kind == TicketKind.story and QUICK_TAG in (t.tags or [])


QUICK_ENGINEER_CARD = "engineer-quick"
#: S19: the Help seat diagnoses through its board tools only; its claude shell gets no shell or file writes
#: (the pool turns this spawn env into `--disallowedTools`; a codex seat of an unlisted role is read-only)
DOCTOR_DISALLOWED_TOOLS = "Bash,PowerShell,Edit,Write,MultiEdit,NotebookEdit"


def seat_card_env(t: Ticket | None, role: str) -> dict[str, str]:
    """s-ccdafcb229 (owner m-b13c61ddea, "polymorphism: same role, different card per flow"): the spawn
    env that picks a role card other than `/<role>`. An engineer on a quick task boots
    `.claude/commands/engineer-quick.md`; every launcher (pool activation_text, Pi, codex) reads
    EDP_CARD. Empty for every other seat."""
    if t is not None and str(role) in ("engineer", Role.engineer.value) and is_quick(t) and t.parent_id is None:
        return {"EDP_CARD": QUICK_ENGINEER_CARD}
    return {}


def materialise_card(name: str, text: str, home: Any = None) -> Any:
    """S13 (§4.14(d)): write a workflow version's card into the agent home's command dir as
    `<name>.md` (name = workflow.card_name: wf-<id>-<version>-<role> + a hash), so the seat boots
    `/<name>`. A published version is immutable, so a file is written once and never changes under a
    running seat; rewritten only when missing or different (a crash mid-write)."""
    import os
    from pathlib import Path as _P
    base = _P(home) if home is not None else _P(seat_choice.agent_home())
    path = base / ".claude" / "commands" / f"{name}.md"
    try:
        if path.read_text(encoding="utf-8") == text:
            return path
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def is_topic(t: Ticket | None) -> bool:
    """A Library topic (S-SME-SURFACE): its own parentless record, opened and closed by the owner."""
    return t is not None and t.kind == TicketKind.topic


HELP_TAG = "help"
ACCESS_TAG = "access-requests"  # s-aa76c83998: the one standing owner topic that carries "new access request" messages


def is_access(t: Ticket | None) -> bool:
    """The board's standing "Access requests" topic: no resident seat, never listed in the Library."""
    return is_topic(t) and ACCESS_TAG in (t.tags or [])  # type: ignore[union-attr]


def is_help(t: Ticket | None) -> bool:
    """A help thread (S19): a topic tagged `help`, opened by any human from Ask for help or
    `heronry doctor --agent`, with a resident doctor seat instead of an sme; never listed in the Library."""
    return is_topic(t) and HELP_TAG in (t.tags or [])  # type: ignore[union-attr]


def topic_seat_role(t: Ticket | None) -> str:
    """The resident seat's role on a topic: doctor on a help thread, else the Library's sme."""
    return Role.doctor.value if is_help(t) else Role.sme.value
# S22 c-0615088222: every feed queue (wake and view) is bounded. Drop policy: when a queue is full the
# OLDEST queued event is dropped and the queue is marked `resync`; the SSE stream then sends
# `: resync <cursor>` and ends, and the client reconnects from its last seq — the replay by seq
# refills exactly what was dropped. A stalled reader costs at most this many events of memory.
FEED_QUEUE_MAX = 1000


def _dedup(reasons: list[Reason]) -> list[Reason]:
    """Preserve first-seen order, drop repeats — a recipient's reason list for one event."""
    out: list[Reason] = []
    for r in reasons:
        if r not in out:
            out.append(r)
    return out


_LEDGER_EVENTS = (EventKind.ask_created, EventKind.ask_triaged, EventKind.ask_judged, EventKind.ask_archived,
                  EventKind.requirement_marked, EventKind.requirement_linked)


class BoardError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code, self.message, self.hint = code, message, hint

    def to_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message}, "hint": self.hint}


class Board:
    def __init__(self, store: Store, index: Any | None = None, *, pool: Any | None = None,
                 free_mb: Any | None = None, mint_token: Any | None = None):
        self.store = store
        self.index = index  # edp8.search.Index or None
        self._subs: dict[str, list[asyncio.Queue]] = {}
        # S19: view subscribers (the web page) get EVERY event, not the wake-filtered subset — a
        # page shows a whole thread, so a note between two seats must refresh it (chat freeze).
        self._watch: dict[str, list[asyncio.Queue]] = {}
        self._lock = threading.RLock()
        # Automatic checker pairing (design §24 rule 3): `pool` is the spawn adapter (defaults to
        # edp8.pool_adapter, injected as a stub in tests); `free_mb` reports host free RAM for the
        # preflight-aware queue. `mint_token(handle) -> secret|None` mints the per-seat EDP8_TOKEN so
        # an auto-paired seat authenticates exactly like a service-spawned one (§24 finding 4); the
        # service wires it to _mint_agent_token, tests inject a stub, and None means trusted mode
        # (header-only, nothing injected). `_pending_pairings` maps participant_id ->
        # {role, ticket, noted} for seats waiting on RAM headroom; run_pending_pairings() drains it.
        self._pool = pool
        self._free_mb = free_mb
        self._mint_token = mint_token
        self._pending_pairings: dict[str, dict[str, Any]] = {}
        # S13: versioned workflow definitions and each epic's pin; existing epics pin Standard@1 here
        self.workflows = wflow.WorkflowRegistry(store)
        self.workflows.migrate_all()
        try:
            self.retire_acceptance_gates()
        except Exception as e:  # noqa: BLE001 — a migration hiccup must never block board startup
            _log.warning("acceptance-gate retirement on init failed: %s", e)
        # §24 finding 3: the pending queue is volatile; on boot re-derive it from durable board
        # state so a restart between enqueue and drain never loses a qa pairing. HELD (owner m-e2edc8d256):
        # a start never launches a shell — each owed pairing waits for an explicit spawn/resume and is
        # raised once as an ask to the epic's architect (run_pending_pairings).
        try:
            self._rederive_pending_pairings(held=True)
        except Exception as e:  # noqa: BLE001 — a rederive hiccup must never block board startup
            _log.warning("pairing rederive on init failed: %s", e)

    SEAT_FLOOR_MB = 500  # design §24 rule 3: free RAM below this queues a pairing instead of spawning

    # ------------------------------------------------------------------ workflow (S13)
    def workflow_of(self, t: Ticket | str | None) -> wflow.Workflow:
        """The workflow a ticket runs under: its epic's pinned version (Standard@1 for an unpinned root,
        a topic or no ticket). Every rule the board enforces is read from it."""
        if t is None:
            return self.workflows.resolve(wflow.ref(wflow.STANDARD_ID, 1))
        if isinstance(t, str):
            t = self.store.get("ticket", t)  # type: ignore[assignment]
            if t is None:
                return self.workflow_of(None)
        root = t.epic_id or self.epic_of(t).id  # type: ignore[union-attr]
        return self.workflows.resolve(self.workflows.pin_of(root) or wflow.ref(wflow.STANDARD_ID, 1))

    def seat_spawn_spec(self, ticket_id: str | None, role: Any) -> dict[str, Any]:
        """What a spawn of `role` for `ticket_id` carries from the epic's pinned workflow (S13, §4.14(d)):
        env (EDP_CARD: the quick-task card, or the version's materialised card) and capacity
        ({capacity_class, max_concurrent}) for the pool's caps. Standard roles boot their shipped card."""
        t = self.store.get("ticket", ticket_id) if ticket_id else None
        wf = self.workflow_of(t)
        role = str(role)
        env = seat_card_env(t, role)  # type: ignore[arg-type]
        if not env:
            name, text = wf.card(role)
            if text is not None:
                materialise_card(name, text)
                env = {"EDP_CARD": name}
        if role == Role.doctor.value:
            env = {**env, "EDP_SEAT_DISALLOWED_TOOLS": DOCTOR_DISALLOWED_TOOLS}
        return {"env": env, "capacity": wf.capacity(role), "workflow": wf.ref}

    def materialise_pinned_cards(self, home: Any = None) -> list[str]:
        """S11 F6 migration (board start): write the inline card of every role of every pinned version whose
        file is missing, so a resumed seat or a fresh agent home finds the card its EDP_CARD names. A file
        already there is never touched (materialise_card writes only a missing or torn one). Returns the
        names written."""
        from pathlib import Path as _P
        base = _P(home) if home is not None else _P(seat_choice.agent_home())
        written = []
        for ref_ in sorted(self.workflows.pinned_refs()):
            try:
                wf = self.workflows.resolve(ref_)
            except wflow.WorkflowError:
                continue
            for rid in wf.roles:
                name, text = wf.card(rid)
                if text is not None and not (base / ".claude" / "commands" / f"{name}.md").is_file():
                    materialise_card(name, text, base)
                    written.append(name)
        return written

    def _wf_check(self, wf: wflow.Workflow, pres: list, ctx: wflow.Ctx, *, skip_roles: bool = False,
                  phase: str = "both") -> None:
        """Run declared preconditions; a failing one is the board's refusal naming the missing piece."""
        r = wf.missing(pres, ctx, quick=is_quick(ctx.t), skip_roles=skip_roles, phase=phase)
        if r is not None:
            raise BoardError(r.code, r.message, r.hint)

    def known_role(self, role: Any, t: Ticket | None = None) -> bool:
        """A built-in role, or a role of the ticket's workflow (of any pinned workflow when no ticket)."""
        if isinstance(role, Role):
            return True
        if t is not None:
            return str(role) in self.workflow_of(t).roles
        return any(str(role) in self.workflows.resolve(r).roles for r in self.workflows.pinned_refs())

    def human_role(self, role: Any) -> bool:
        """A person's role: a reserved non-agent id, or a role some pinned workflow marks human."""
        rid = str(getattr(role, "value", role))
        if is_non_agent(rid):
            return True
        wfs = [self.workflow_of(None)] + [self.workflows.resolve(r) for r in self.workflows.pinned_refs()]
        return any(rid in wf.roles and wf.roles[rid].human for wf in wfs)

    def checker_roles(self) -> set[str]:
        """Every role that checks criteria in some pinned workflow (Standard's qa/owner at least)."""
        out = set(self.workflow_of(None).criterion_checkers)
        for r in self.workflows.pinned_refs():
            out |= self.workflows.resolve(r).criterion_checkers
        return out

    # ------------------------------------------------------------------ helpers
    # ------------------------------------------------------------------ guests (e0cec S5, design §4.B)
    def _refuse_guest(self, actor: Participant | None, what: str) -> None:
        """Board-side half of the guest authority list (the REST gate is the other half): a guest reads,
        posts question/note and uploads on its member epics, nothing else."""
        if guest_scope.is_guest(actor):
            raise BoardError("forbidden", f"a guest may not {what}",
                             "a guest reads, posts a question or note, and uploads on its member epics")

    def _guest_may_post(self, actor: Participant, t: Ticket, kind: Any) -> None:
        if not guest_scope.is_guest(actor):
            return
        scope = guest_scope.scope_for(self, actor)
        if scope is None or t.id not in scope.tickets:
            raise guest_scope.not_found("ticket", t.id)
        if str(getattr(kind, "value", kind)) not in guest_scope.MESSAGE_KINDS:
            raise BoardError("forbidden", f"a guest posts a question or a note, not a {kind}",
                             "message_send(kind='question'|'note')")

    def _guest_refs(self, actor: Participant, to: str | None, reply_to: str | None,
                    resolves: list[str] | None, asked: str | None = None) -> None:
        """e0cec S5 (review m-33154269a9 #4 + nit): what a guest's message points at stays in its closure: a
        reply_to/resolves outside it is the same 404 as a missing id, and `to=` reaches only the people on its
        member epics (their seats, members, the owner), never an arbitrary handle."""
        if not guest_scope.is_guest(actor):
            return
        scope = guest_scope.scope_for(self, actor)
        for mid in [reply_to, *(resolves or [])]:
            if mid and not scope.has(mid):
                raise guest_scope.not_found("message", mid)
        if (asked or to) in {r.value for r in Role}:  # a role address: resolve_recipient maps it within the epic
            return
        if to and to not in scope.people and to.rsplit(".", 1)[-1] not in scope.tickets:
            raise BoardError("not_found", f"participant {(asked or to)!r} is not registered",  # = an unknown handle
                             "register with participant_create or use an existing @handle")

    def _epic_of_scope(self, scope: str | None) -> str | None:
        """The epic a doc scope / ticket id belongs to (None for global and domain scopes)."""
        if not scope:
            return None
        t = self.store.get("ticket", scope)
        return (t.epic_id or self.epic_of(t).id) if t is not None else None  # type: ignore[union-attr]

    def _screen(self, epic_id: str | None, text: str, where: str) -> None:
        """The secret screen: content bound for an epic a guest can read is refused when it carries a secret."""
        if epic_id and guest_scope.epic_has_guests(self, epic_id):
            from . import secret_screen
            secret_screen.check(text, where=where)

    def epic_members_set(self, actor: Participant, epic_id: str, members: list[str]) -> Ticket:
        """The epic's People panel: set the epic's members (owner or admin only). A member must be a registered
        human; the change is a ticket_updated event, so open guest streams recompute (and a removed guest's
        stream ends with a resync)."""
        from .admin.auth import is_admin
        if actor.role != Role.owner and not is_admin(actor):
            raise BoardError("forbidden", "only the owner edits an epic's people", "ask the owner")
        epic = self.ticket(epic_id)
        if epic.kind != TicketKind.epic:
            raise BoardError("invalid", f"{epic_id} is a {epic.kind}, not an epic", "members are per epic")
        want: list[str] = []
        for m in members:
            p = self.participant(m)
            if p.type != "human":
                raise BoardError("invalid", f"{p.handle} is a seat; an epic's people are humans")
            if p.id not in want:
                want.append(p.id)
        before = list(epic.members)
        epic.members = want
        self.store.put("ticket", epic)
        self._emit(epic.id, EventKind.ticket_updated, {
            "changed": ["members"], "by": actor.id,
            "added": [m for m in want if m not in before], "removed": [m for m in before if m not in want]})
        return epic

    def _get(self, type_: str, id_: str, what: str | None = None):
        o = self.store.get(type_, id_)
        if o is None:
            raise BoardError("not_found", f"{what or type_} {id_!r} does not exist")
        return o

    def _emit(self, subject_id: str, kind: EventKind, data: dict[str, Any] | None = None) -> Event:
        ev = Event(id=new_id("ev"), subject_id=subject_id, kind=kind, data=data or {})
        self.store.put("event", ev)
        self.store.after_commit(lambda: self._fanout(ev))
        if kind == EventKind.status_changed and (data or {}).get("to"):
            self._settle_phase_past(subject_id, str(data["to"]))  # type: ignore[index]
        return ev

    def _index(self, type_: str, id_: str, text: str) -> None:
        self.store.after_commit(lambda: self._index_committed(type_, id_, text))

    def _index_doc(self, d: Doc) -> None:
        """S17 decision 4: a doc is searched by section, so its units replace the old ones together."""
        parts = self.store.doc_units({"title": d.title, "body_md": d.body_md})
        self.store.after_commit(lambda: self._index_committed("doc", d.id, "", parts))

    def _index_committed(self, type_: str, id_: str, text: str,
                         parts: list[tuple[str | None, str]] | None = None) -> None:
        if self.index is not None:
            try:
                if parts is not None:
                    self.index.upsert_sections(type_, id_, parts)
                else:
                    self.index.upsert(type_, id_, text)
            except Exception as e:  # search is never on the write path's critical line — but never silent
                _log.warning("search index update failed for %s %s: %s", type_, id_, e)

    # ------------------------------------------------------------------ participants
    def participant_create(self, type_: str, role: RoleId, handle: str, *, location: str | None = None,
                           model: str | None = None, id_: str | None = None) -> Participant:
        handle = handle.lstrip("@")
        if type_ == "human" and (not HANDLE_RX.match(handle) or ".." in handle):
            raise BoardError("invalid", f"{handle[:60]!r} is not a valid handle",
                             "2–48 of a-z 0-9 . _ -, starting with a letter or digit; no '..'")
        from .schemas import role_id
        try:
            role = role_id(role)
        except ValueError as e:
            raise BoardError("schema", str(e)) from None
        if not self.known_role(role):
            raise BoardError("schema", f"role {role!r} is not a built-in role nor a role of any pinned workflow",
                             "pin an epic to the workflow that defines it first")
        if type_ == "agent":  # owner m-da9a2ae62f: a person's role is never an agent participant
            why = non_agent_refusal(role, id_ or handle)
            if why is None and self.human_role(role):
                why = f"the {role.value} role is a human role in its workflow: no seat is ever launched as it"
            if why:
                raise BoardError("scope", why, "people join through Teammates; seats are agent roles "
                                               "(architect, engineer, qa, adversary, sme, doctor)")
        if self.store.query("participant", {"handle": handle}):
            raise BoardError("conflict", f"handle @{handle} already registered", "choose another handle")
        p = Participant(id=id_ or new_id(role.value), type=type_, role=role, handle=handle,
                        location=location, model=model, created_by="registry")
        return self.store.put("participant", p)

    def participant(self, id_or_handle: str) -> Participant:
        p = self.store.get("participant", id_or_handle)
        if p is None:
            hits = self.store.query("participant", {"handle": id_or_handle.lstrip("@")})
            p = hits[0] if hits else None
        if p is None:
            raise BoardError("not_found", f"participant {id_or_handle!r} is not registered",
                             "register with participant_create or use an existing @handle")
        return p

    # ------------------------------------------------------------------ tickets
    _TITLE_HINT = "an epic's words stay verbatim in `words`; the title is the short form"
    TITLE_MAX = 80  # ruling #32 (2026-09-10, "Title ≠ words"): a ticket title is a short human title

    @classmethod
    def derive_title(cls, words: str) -> str:
        """A short human title from an epic's verbatim words (ruling #32): the first clause — up to
        the first `. ! ? ; : — –` or newline — and, if that is still over TITLE_MAX, cut at the last
        word boundary before TITLE_MAX-3 with an ellipsis appended. Never touches `words`."""
        text = words.strip()
        first = re.split(r"[.!?;:\u2014\u2013\n]", text, maxsplit=1)[0].strip()
        if not first:
            first = text
        if len(first) <= cls.TITLE_MAX:
            return first
        cut = first[:cls.TITLE_MAX - 3]
        cut = cut[:cut.rfind(" ")] if " " in cut else cut
        return cut.rstrip(" ,") + "\u2026"

    def ticket_create(self, actor: Participant, *, kind: TicketKind, work_type: WorkType, title: str,
                      parent_id: str | None = None, assignee: str | None = None, description: str = "",
                      tags: list[str] | None = None, words: str | None = None,
                      workflow: str | None = None, serves: list[str] | None = None,
                      cap_lift_message: str | None = None) -> Ticket:
        self._refuse_guest(actor, "create tickets")
        # S13: an epic is created under the workflow it pins (Standard@1 unless `workflow` names another
        # published version); a child is created under its epic's pinned workflow.
        if kind == TicketKind.epic:
            try:
                wf_ref = self._workflow_choice(workflow)
            except wflow.WorkflowError as e:
                raise BoardError("schema", e.message, e.hint) from None
            wf = self.workflows.resolve(wf_ref)
        else:
            if workflow is not None:
                raise BoardError("schema", "only an epic chooses a workflow", "a child runs under its epic's pin")
            wf = self.workflow_of(parent_id) if parent_id else self.workflow_of(None)
        creators = wf.creators(kind)
        if str(actor.role) not in creators:
            raise BoardError("scope", f"{actor.role} may not create a {kind}",
                             f"creators of {kind}: {sorted(creators)}")
        if kind in (TicketKind.epic, TicketKind.topic) and parent_id:
            raise BoardError("schema", f"an {kind} has no parent")
        clean_tags = [x.strip() for x in (tags or []) if x.strip()]
        if HELP_TAG in clean_tags:  # S19: a help thread is opened by POST /v1/help (edp8.help), with its doctor seat
            raise BoardError("invalid", f"the `{HELP_TAG}` tag marks a help thread",
                             "ask for help (POST /v1/help, the rail's Ask for help, `heronry doctor --agent`)")
        if ACCESS_TAG in clean_tags:
            raise BoardError("invalid", f"the `{ACCESS_TAG}` tag marks the board's access-requests topic",
                             "the board opens it itself when the first access request arrives")
        bad_policy = epic_policy.tag_problem(clean_tags)
        if bad_policy:
            raise BoardError("invalid", bad_policy, "sme:on|off and project:<key> are an epic's policy tags")
        quick = kind == TicketKind.story and QUICK_TAG in clean_tags
        if quick and actor.role != Role.owner:
            raise BoardError("scope", f"only the owner opens a quick task (tag `{QUICK_TAG}`)",
                             "an architect's story is designed under its epic; drop the tag")
        if kind == TicketKind.story and not parent_id and actor.role == Role.owner and not quick:
            quick, clean_tags = True, [*clean_tags, QUICK_TAG]  # the owner's parentless story IS a quick task
            advice.advise(f"tagged `{QUICK_TAG}`: the owner's parentless story is a quick task")
        if kind not in (TicketKind.epic, TicketKind.topic):
            if not parent_id and not quick:
                raise BoardError("schema", f"a {kind} needs parent_id")
            if parent_id:
                parent = self._get("ticket", parent_id, "parent ticket")
                expected = TicketKind.epic if kind == TicketKind.story else TicketKind.story
                if parent.kind != expected:
                    raise BoardError("schema", f"a {kind} must hang under a {expected}, not a {parent.kind}")
        served = epic_work.check_serves(self, kind, parent_id, serves)  # E6
        if not title.strip():
            raise BoardError("schema", "title is empty",
                             "an epic's title is derived from the owner's words; a story/task title names the slice")
        # Ruling #32 (2026-09-10): an epic's `words` are the owner's request verbatim and immutable; its
        # `title` is a short human title. A caller may pass both; passing only `title` (the historical
        # shape — the words verbatim) stores them as `words` and derives the title when they run long.
        if kind == TicketKind.epic:
            if words is not None and not words.strip():
                raise BoardError("schema", "request words are empty")
            if words is not None and words != title and len(title.strip()) > self.TITLE_MAX:
                raise BoardError("schema", f"explicit title is at most {self.TITLE_MAX} characters", self._TITLE_HINT)
            words = words if words is not None else title
            if len(title.strip()) > self.TITLE_MAX:
                title = self.derive_title(title)
                advice.advise(f"title longer than {self.TITLE_MAX} characters: derived the short title {title!r}; "
                              "the full text is kept as the epic's words")
            else:
                title = title.strip()
        elif quick:
            # a quick task's words are the owner's request verbatim (its design); its own title stays
            words = words.strip() if words and words.strip() else None
        elif kind == TicketKind.topic:
            # t-f5bf848f0f: a topic's purpose is the owner's words, verbatim and immutable like an epic's
            words = words if words and words.strip() else None
        else:
            words = None
        # §24 finding 11: the cap count and the insert are one atomic step under the board lock, so
        # two concurrent creates cannot both read N-1 and both insert (producing N+1 over the cap).
        with self._lock:
            if kind == TicketKind.story and parent_id and not quick:  # the owner's own task is not epic scope
                self._enforce_story_cap(parent_id, cap_lift_message)
            if kind == TicketKind.task and parent_id:
                self._enforce_task_cap(parent_id)
            prefix = kind.value if kind in (TicketKind.epic, TicketKind.topic) else kind.value[0]
            t = Ticket(id=new_id(prefix), kind=kind, work_type=work_type,
                       title=title, words=words, parent_id=parent_id, assignee=assignee, created_by=actor.id,
                       description=description or "", tags=clean_tags, serves=served)
            if quick:
                t.status = TicketStatus.ready  # the words are the design: no design_ref, no sign-off walk
            if kind == TicketKind.topic:
                t.status = TicketStatus.in_progress  # a topic is open from birth; only the owner's close ends it
            t.epic_id = t.id if kind == TicketKind.epic else self.epic_of(t).id
            if kind == TicketKind.epic:
                # R2-C: the epic and its pin commit together, or neither does when the version went away
                try:
                    with self.store.transaction():
                        self.store.put("ticket", t)
                        self.workflows.pin(t.id, wf.ref, live=True)  # immutable: editing never moves this epic
                except wflow.WorkflowError as e:
                    raise BoardError("conflict", e.message, e.hint) from None
            else:
                self.store.put("ticket", t)
        self._index("ticket", t.id, self.store._fts_text("ticket", t.model_dump(mode="json")) or t.title)
        self._emit(t.id, EventKind.ticket_created, {"kind": kind, "parent_id": parent_id, "by": actor.id})
        if assignee:
            self._emit(t.id, EventKind.assigned, {"assignee": assignee})
        if quick:  # S-IMPLICIT: a quick task gets its tagged Library docs like a signed-off epic
            records.safely(self.autolink_library, t.id, trigger="quick task")
        return t

    def _workflow_choice(self, workflow: str | None) -> str:
        """'lean' → its latest published version; 'lean@2' → that version, which must be published."""
        if not workflow:
            return wflow.ref(wflow.STANDARD_ID, 1)
        if "@" in workflow:
            wf_id, ver = wflow.parse_ref(workflow)
            d = self.workflows.get(wf_id, ver)
            if not d.published:
                raise wflow.WorkflowError("unpublished", f"{d.ref} is a draft", "publish it before pinning an epic")
            return d.ref
        return self.workflows.latest_published(workflow).ref

    def ticket(self, id_: str) -> Ticket:
        return self._get("ticket", id_, "ticket")

    def tickets(self, **filters: Any) -> list[Ticket]:
        return self.store.query("ticket", filters)  # type: ignore[return-value]

    def epic_of(self, t: Ticket) -> Ticket:
        while t.parent_id:
            t = self._get("ticket", t.parent_id)
        return t

    # ---- epic phase is machine-carried, never seat-remembered (c-c80f7cd8f0) ----
    # Root cause of the 2026-09-08 consult fork (m-77af6e8145): every story's context leads with
    # the epic's verbatim words, and the epic still read `drafted` long after its design was set,
    # so a fresh seat saw an open concept phase and asked rather than built. The board now advances
    # the epic's phase from facts (design_ref set → designed; design_signoff answered → signed_off;
    # a child story starting → in_progress, via the parent derivation in _after_status) and every
    # read stamps a one-line provenance header on the words, so the phase is never a seat's memory.
    # s-ccdafcb229 (owner m-b0a7f9cda9): every story released → the epic is carried to in_review by the
    # board too (no agent spends tokens on it); qa then marks the stories and the epic done.
    _EPIC_PHASE_ORDER = (TicketStatus.drafted, TicketStatus.designed, TicketStatus.signed_off,
                         TicketStatus.in_progress, TicketStatus.in_review)

    def _epic_phase_header(self, epic: Ticket) -> str:
        """The one-line provenance stamped above an epic's verbatim words: when they were recorded,
        the epic's current machine-carried phase, and the design version that now governs them."""
        recorded = epic.created_at.date().isoformat()
        gov = "(no design yet)"
        if epic.design_ref:
            d = self.store.get("doc", epic.design_ref)
            gov = f"{epic.design_ref} v{d.version}" if d is not None else epic.design_ref  # type: ignore[union-attr]
        return f"words recorded {recorded}; phase: {epic.status.value}; governed by {gov}"

    def _advance_epic_phase(self, epic: Ticket, to: TicketStatus, *, trigger: str) -> None:
        """Machine-carry an epic FORWARD along drafted→designed→signed_off→in_progress→in_review from a fact,
        no architect memory. Idempotent and monotonic: a no-op if the epic already sits at or past
        `to`, or is terminal; it never moves an epic backward. Bypasses _guard_transition (a
        board-authored transition, like the ready-release at _release_successors)."""
        order = self._EPIC_PHASE_ORDER
        if to != TicketStatus.designed and self.workflow_of(epic).hook("epic_auto_advance") is None:
            return  # the designed carry is the workflow's declared auto edge; the rest is this hook
        if (epic.kind != TicketKind.epic or epic.status in _TERMINAL
                or to not in order or epic.status not in order
                or order.index(epic.status) >= order.index(to)):
            return
        old = epic.status
        epic.status = to
        self.store.put("ticket", epic)
        self._emit(epic.id, EventKind.status_changed,
                   {"from": old.value, "to": to.value, "by": "board", "trigger": trigger})
        self._after_status(epic)
        if to == TicketStatus.in_review:
            self._hint_qa_available(epic)  # B: the board hints the architect; it enqueues and spawns no seat
        if to == TicketStatus.in_review:  # qa s-ccdafcb229 finding 3: epic lines verdicted before the last
            self._auto_advance(epic)      # story's hand-off close the epic now, not on a later verdict

    def children(self, ticket_id: str) -> list[Ticket]:
        # every child: the store's default 500-row window would silently cut a long-lived epic (C17 second opinion)
        return self.store.query("ticket", {"parent_id": ticket_id}, limit=100000)  # type: ignore[return-value]

    # ------------------------------------------------------------------ caps (design §24.1)
    def _open_stories(self, epic_id: str) -> list[Ticket]:
        """Stories under an epic that still count against the cap (not done/dropped)."""
        return [k for k in self.children(epic_id)
                if k.kind == TicketKind.story and k.status not in (TicketStatus.done, TicketStatus.dropped)]

    def _scope_cap_raised(self, epic_id: str) -> bool:
        """The owner raised this epic's story cap: by answering a `scope` gate on it (§24.1), or by a chat reply whose
        message id a ticket_create passed (design-63db8a7d42 J; `scope_cap_lifted`)."""
        return (any(e.data.get("gate") == Gate.scope.value
                    for e in self.store.query("event", {"subject_id": epic_id, "kind": EventKind.gate_answered}))
                or bool(self.store.query("event", {"subject_id": epic_id, "kind": EventKind.scope_cap_lifted})))

    def _lift_story_cap(self, epic_id: str, message_id: str) -> None:
        """J: the owner's reply message, on this epic, lifts the story cap for the epic. The board checks the sender,
        not the meaning (m-28ed419c47): the message must exist, be sent by this epic's own owner (any owner when the
        epic has none), and sit on this epic or one of its tickets. Every lift is one `scope_cap_lifted` event."""
        m = self.store.get("message", message_id)
        if m is None:
            raise BoardError("scope", f"cap_lift_message {message_id} is not a message",
                             "pass the id of the owner's chat reply (a message on this epic)")
        sender = self.store.get("participant", m.created_by)
        owner_id = self.epic_owner(epic_id)
        if sender is None or sender.role != Role.owner:
            raise BoardError("scope", f"message {message_id} is not the owner's; only the owner's reply lifts the cap",
                             "ask the owner in chat, then pass the id of their yes")
        if owner_id is not None and m.created_by != owner_id:
            raise BoardError("scope", f"message {message_id} is from {m.created_by}, not this epic's owner {owner_id}",
                             "only the owner of this epic lifts its cap: ask them in chat, then pass the id of their yes")
        on = self.store.get("ticket", m.ticket_id)
        if on is None or (on.epic_id or on.id) != epic_id:
            raise BoardError("scope", f"message {message_id} is not on epic {epic_id}",
                             "pass the owner's reply from this epic's thread")
        self._emit(epic_id, EventKind.scope_cap_lifted, {"message": message_id, "by": m.created_by})

    def _enforce_story_cap(self, epic_id: str, cap_lift_message: str | None = None) -> None:
        cap = self.workflow_of(epic_id).cap("stories_per_epic")
        raised = self._scope_cap_raised(epic_id)
        if cap_lift_message and not raised:  # F2: a valid id is recorded when passed, below the cap too
            self._lift_story_cap(epic_id, cap_lift_message)
            raised = True
        if len(self._open_stories(epic_id)) >= cap and not raised:
            raise BoardError("scope", f"an epic holds at most {cap} open stories",
                             "ask the owner in chat; when they reply yes, pass that message's id as "
                             "ticket_create(cap_lift_message=...) to lift the cap for this epic; pass only the owner's yes")

    def _enforce_task_cap(self, story_id: str) -> None:
        tasks = [k for k in self.children(story_id)
                 if k.kind == TicketKind.task and k.status not in (TicketStatus.done, TicketStatus.dropped)]
        cap = self.workflow_of(story_id).cap("tasks_per_story")
        if len(tasks) >= cap:
            advice.advise(f"a story normally holds at most {cap} tasks and this is number {len(tasks) + 1}; fold work "
                          "into fewer tasks, or hand a slice to a second engineer")

    def ensure_epic_ids(self) -> int:
        """Backfill Ticket.epic_id on boards created before 2026-09-06. Idempotent."""
        n = 0
        for t in self.store.query("ticket", {}, limit=100000):
            if t.epic_id:
                continue
            t.epic_id = t.id if t.kind == TicketKind.epic else self.epic_of(t).id  # type: ignore[union-attr]
            self.store.put("ticket", t)
            n += 1
        return n

    _VIEW_SECTIONS = ("chain", "criteria", "docs", "children", "blockers", "gates", "thread", "links")

    def ticket_view(self, ticket_id: str, include: Iterable[str] | None = None, thread_limit: int = 20,
                    before_seq: int | None = None) -> dict[str, Any]:
        """ONE fat read of a ticket: the record plus every section an agent used to assemble by
        hand (2026-09-06: the most-called tool in the fleet was message_query re-fetching threads).
        `include` narrows the sections; default = all of them. `before_seq` (e0cec S3) pages the thread tail
        back: the newest `thread_limit` messages OLDER than that seq; `thread_before_seq` names the next page."""
        t = self.ticket(ticket_id)
        want = set(include) if include else set(self._VIEW_SECTIONS)
        epic = self.epic_of(t)
        out: dict[str, Any] = {"ticket": t.model_dump(mode="json"), "words": epic.words or epic.title,
                               "words_header": self._epic_phase_header(epic),
                               # S13: the epic's pinned workflow (from workflow_pins — never a tag)
                               "workflow": self.workflow_of(epic).ref}
        if include and "lifecycle" in want:  # S13: opt-in; the /epic and /ticket skills read it
            out["lifecycle"] = wflow.lifecycle_md(self.workflow_of(epic), t.kind.value)
        if "chain" in want:
            chain: list[dict[str, Any]] = []
            cur: Ticket | None = t
            while cur is not None:
                chain.append({"id": cur.id, "kind": cur.kind, "title": cur.title, "status": cur.status,
                              "design_ref": cur.design_ref})
                cur = self.store.get("ticket", cur.parent_id) if cur.parent_id else None  # type: ignore[assignment]
            out["chain"] = chain
        if "criteria" in want:
            out["criteria"] = [c.model_dump(mode="json") for c in self.criteria(t.id)]
        if "docs" in want:
            rel_by_doc: dict[str, str] = {lk.to_id: lk.relation.value for lk in self.links(from_id=t.id)}
            docs = self.linked_docs(t.id)
            for ref, why in ((t.design_ref, "design_ref"), (epic.design_ref if epic.id != t.id else None, "epic design_ref")):
                if ref:
                    dd = self.store.get("doc", ref)
                    if dd and all(d.id != dd.id for d in docs):
                        docs.insert(0, dd)  # type: ignore[arg-type]
                        rel_by_doc.setdefault(dd.id, why)
            docs += self._layer_docs(t, epic, {d.id for d in docs}, rel_by_doc)
            # S17: a strategy/domain layer that is not active (proposed: unapproved; retired: out of use) is no
            # part of the ticket's reading list — the rule the removed ruleset tool applied to its layers
            docs = [d for d in docs if rel_by_doc.get(d.id) not in self._LAYER_RELS or d.status == DocStatus.active]
            out["docs"] = [{**self._doc_summary(d), "relation": rel_by_doc.get(d.id, "linked")} for d in docs]
            out["strategy_links"] = any(
                self.links(from_id=x, relation=rel) for x in {t.id, epic.id}
                for rel in (Relation.uses_strategy, Relation.uses_domain))
        if "children" in want:
            kids = []
            for k in self.children(t.id):
                crits = self.criteria(k.id)
                kids.append({"id": k.id, "kind": k.kind, "title": k.title, "status": k.status, "work_type": k.work_type,
                             "assignee": k.assignee,
                             "assignee_role": (k.assignee.split(".", 1)[0] if k.assignee and "." in k.assignee
                                               else getattr(self.store.get("participant", k.assignee or ""), "role", None)),
                             "criteria": f"{sum(c.verdict == Verdict.passed for c in crits)}/{len(crits)}",
                             "tags": k.tags})
            out["children"] = kids
        if "blockers" in want:
            out["blockers"] = [{"id": b.id, "status": b.status, "title": b.title[:80]} for b in self.blockers(t.id)]
        if "gates" in want:
            out["open_gates"] = [e.data.get("gate") for e in self.open_gates(t.id)]
        if "thread" in want:
            rows = self.store.query_seq("message", {"ticket_id": t.id}, limit=100000)
            # #37(a) (Astra, 2026-09-10): rows[-0:] is the WHOLE thread — 0 means none.
            window = rows if before_seq is None else [r for r in rows if r[0] < before_seq]
            tail = window[-thread_limit:] if thread_limit > 0 else []
            # S4: a code anchor rides as `code_anchor` (snippet capped) so the snapshot stays bounded
            out["thread"] = [with_quotes({**m.model_dump(mode="json"), **code_row(m), "seq": seq}, m, capped=True)
                             for seq, m in tail]
            out["thread_seq"] = rows[-1][0] if rows else 0
            out["thread_total"] = len(rows)
            if tail and len(window) > len(tail):  # older messages remain: this is where the next page starts
                out["thread_before_seq"] = tail[0][0]
        if "links" in want:
            out["links"] = [lk.model_dump(mode="json") for lk in (*self.links(from_id=t.id), *self.links(to_id=t.id))]
        return out

    def doc_comments(self, doc_id: str, version: int | None = None) -> list[dict[str, Any]]:
        """Messages commenting on a doc (version): a design-review comment (`document_context`) or a
        message quoting it (C18, design-10b21760d9 §14.5), oldest first, quotes rendered."""
        self.doc(doc_id, version)  # an unknown doc/version is a not_found error, not an empty list
        out = []
        for seq, m in self.store.query_body_like("message", f'"{doc_id}"'):
            dc = m.document_context
            by_review = dc is not None and dc.design_ref == doc_id and version in (None, dc.reviewed_version)
            by_quote = any(q.source == "doc" and q.id == doc_id and version in (None, q.version) for q in m.quotes)
            if by_review or by_quote:
                out.append(with_quotes({**m.model_dump(mode="json"), "seq": seq,
                                        "via": "review" if by_review else "quote"}, m))
        return out

    AROUND_DEFAULT, AROUND_MAX = 5, 25

    def messages_around(self, message_id: str, window: int | None = None, *,
                        ticket_id: str | None = None) -> list[dict[str, Any]]:
        """e0cec S3 (design §4.A "Old discussion"): the target message with `window` messages before and after it
        on its ticket, in seq order. Default 5, at most 25. The target carries `target: true` and its whole text."""
        m = self._get("message", message_id, "message")
        if ticket_id and ticket_id != m.ticket_id:
            raise BoardError("invalid", f"{message_id} is on {m.ticket_id}, not {ticket_id}",  # type: ignore[attr-defined]
                             "drop ticket_id: around finds the ticket from the message")
        n = self.AROUND_DEFAULT if window is None else max(0, min(int(window), self.AROUND_MAX))
        seq = self.store.seq_of("message", m.id)  # type: ignore[attr-defined]
        scope = {"ticket_id": m.ticket_id}  # type: ignore[attr-defined]
        before = self.store.query_seq("message", scope, before_seq=seq, limit=n, newest_first=True) if n else []
        after = self.store.query_seq("message", scope, since_seq=seq, limit=n) if n else []
        rows = [*reversed(before), (seq, m), *after]
        return [with_quotes({**x.model_dump(mode="json"), "seq": s, **({"target": True} if s == seq else {})}, x,
                            capped=s != seq) for s, x in rows]  # type: ignore[union-attr]

    def message_read(self, id_: str) -> dict[str, Any]:
        m = self._get("message", id_, "message")
        row = with_quotes({**m.model_dump(mode="json"), **code_row(m, None)}, m)  # S4/C18: whole snippet + quotes
        row["seq"] = self.store.seq_of("message", m.id)
        row["replies"] = [with_quotes(r.model_dump(mode="json"), r, capped=True)
                          for r in self.store.query("message", {"reply_to": m.id})]
        if m.reply_to:
            parent = self.store.get("message", m.reply_to)
            row["in_reply_to"] = with_quotes(parent.model_dump(mode="json"), parent, capped=True) if parent else None
        return row

    def criteria(self, ticket_id: str) -> list[Criterion]:
        return self.store.query("criterion", {"ticket_id": ticket_id})  # type: ignore[return-value]

    def blockers(self, ticket_id: str) -> list[Ticket]:
        """Explicit `blocks` links plus the implicit rule: a review story waits on every sibling
        non-review story (the adversarial pass reviews the delivery, so it cannot start before it)."""
        links = self.store.query("link", {"to_id": ticket_id, "relation": Relation.blocks})
        out: list[Ticket] = [self._get("ticket", lk.from_id) for lk in links]  # type: ignore[attr-defined]
        t = self.store.get("ticket", ticket_id)
        if t is not None and t.kind == TicketKind.story and t.work_type == WorkType.review and t.parent_id:
            for sib in self.children(t.parent_id):
                if sib.id != t.id and sib.work_type != WorkType.review and all(b.id != sib.id for b in out):
                    out.append(sib)
        return out

    def ticket_update(self, actor: Participant, id_: str, *, status: TicketStatus | None = None,
                      assignee: str | None = None, design_ref: str | None = None,
                      description: str | None = None, tags: list[str] | None = None,
                      title: str | None = None, work_type: WorkType | None = None) -> Ticket:
        kw = dict(status=status, assignee=assignee, design_ref=design_ref, description=description, tags=tags,
                  title=title, work_type=work_type)
        if is_topic(self.ticket(id_)):  # t-3e246b5e32 (b): a topic's read-check-put-attribute is one locked step
            with self._lock:
                return self._ticket_update(actor, id_, **kw)
        return self._ticket_update(actor, id_, **kw)

    def _ticket_update(self, actor: Participant, id_: str, *, status: TicketStatus | None = None,
                       assignee: str | None = None, design_ref: str | None = None,
                       description: str | None = None, tags: list[str] | None = None,
                       title: str | None = None, work_type: WorkType | None = None) -> Ticket:
        self._refuse_guest(actor, "change tickets (status, assignee, fields)")
        t = self.ticket(id_)
        wf = self.workflow_of(t)
        changed: dict[str, Any] = {}
        rechecked: list[dict[str, str]] = []
        if work_type is not None and WorkType(work_type) != t.work_type:
            rechecked = self._retype(actor, t, WorkType(work_type))
            changed["work_type"] = t.work_type
        if is_topic(t):  # adversary 09-23 #5/#7: a topic's seat is its resident sme and its tags are the
            if assignee is not None:  # owner's or the sme's, on every path (not only /v1/topics)
                raise BoardError("scope", f"topic {t.id} is worked by its resident sme seat",
                                 "the board assigns sme.<topic>; the owner closes the topic")
            if tags is not None and actor.role != Role.owner and actor.id != t.assignee:
                raise BoardError("scope", "the owner or the topic's sme sets its tags",
                                 "PATCH /v1/topics/<id>/tags as the owner, or ticket_update as the sme")
        if title is not None:
            # Ruling #32: the title is a short human title, settable by the architect or the owner on an
            # epic or a story; an epic's `words` are immutable — nothing after create writes them.
            if not wf.allowed("set_title", actor.role):
                raise BoardError("scope", f"{actor.role} may not set a ticket's title",
                                 "the architect or the owner sets an epic's or a story's title")
            if t.kind == TicketKind.task:  # design-63db8a7d42 I: a convention, so the title changes and the reply says so
                advice.advise("a task's title is normally fixed at create (titles are settable on epics and stories); "
                              "changed anyway")
            new_title = title.strip()
            if not new_title:
                raise BoardError("schema", "title is empty")
            if len(new_title) > self.TITLE_MAX:  # Q2: the same refusal and hint as create
                raise BoardError("schema", f"explicit title is at most {self.TITLE_MAX} characters", self._TITLE_HINT)
            if new_title != t.title:
                t.title = new_title
                changed["title"] = new_title
        if description is not None or tags is not None:
            if actor.id not in (t.created_by, t.assignee) and not wf.allowed("edit_ticket", actor.role):
                raise BoardError("scope", f"{actor.role} may not edit this ticket's description/tags",
                                 "the creator, the assignee, the architect or the owner may")
            if description is not None:
                t.description = description
                changed["description"] = True
            if tags is not None:
                new_tags = [x.strip() for x in tags if x.strip()]
                if t.kind == TicketKind.story and (QUICK_TAG in new_tags) != is_quick(t):
                    # S-QUICK: the tag decides who checks and whether a design is needed — fixed at create
                    raise BoardError("scope", f"the `{QUICK_TAG}` tag is set when the owner opens a quick task",
                                     "keep or leave out the tag as it was at create")
                if is_topic(t) and (HELP_TAG in new_tags) != is_help(t):
                    # S19: the tag decides the resident seat's role (sme vs doctor) — fixed at create
                    raise BoardError("scope", f"the `{HELP_TAG}` tag marks a help thread and is fixed at create",
                                     "keep or leave out the tag as it was")
                self._check_seat_tags(actor, t, new_tags)
                self._check_policy_tags(actor, t, new_tags)
                t.tags = new_tags
                changed["tags"] = t.tags
                if is_topic(t):  # the attribution rides the same put as the tags (the page reads it here)
                    from .topics import _now, config
                    t.topic_config = {**config(self, t), "tags_set_by": {"by": actor.id, "at": _now()}}
        if assignee is not None:
            if not wf.allowed("assign", actor.role):
                raise BoardError("scope", f"{actor.role} may not assign tickets",
                                 "architect/owner assign; an engineer assigns its own tasks")
            doer = self.participant(assignee)
            why = self.checker_as_doer_reason(t, doer)
            if why:  # S-ADV finding 3: the invariant holds on every path, not only the REST spawn
                raise BoardError("scope", why, "spawn a checker without assign; the doer stays the assignee")
            t.assignee = assignee
            changed["assignee"] = assignee
        if design_ref is not None:
            d = self._get("doc", design_ref, "design doc")
            if d.doc_type not in (DocType.design, DocType.report, DocType.note):
                raise BoardError("schema", "design_ref must point at a design (or plan) doc")
            if not wf.allowed("set_design_ref", actor.role):
                raise BoardError("scope", "only architect (epic/story) or engineer (task) sets design_ref")
            t.design_ref = design_ref
            changed["design_ref"] = design_ref
        if status is not None and status != t.status:
            self._guard_transition(actor, t, status)
            old = t.status
            t.status = status
            changed["status"] = {"from": old, "to": status}
        if not changed:
            return t
        self.store.put("ticket", t)
        if "description" in changed or "tags" in changed or "title" in changed:
            self._index("ticket", t.id, self.store._fts_text("ticket", t.model_dump(mode="json")) or t.title)
        if "title" in changed:
            self._emit(t.id, EventKind.ticket_updated, {"changed": ["title"], "title": t.title, "by": actor.id})
        if "work_type" in changed:
            self._emit(t.id, EventKind.ticket_updated, {"changed": ["work_type"], "work_type": t.work_type.value,
                                                        "rechecked": rechecked, "by": actor.id})
            for r in rechecked:
                self._emit(t.id, EventKind.criterion_checker_overridden,
                           {"criterion": r["criterion"], "from": r["from"], "to": r["to"],
                            "reason": f"the ticket was retyped to {t.work_type.value}", "by": actor.id})
        if "tags" in changed and is_topic(t):  # one list, last write wins, and the page shows who set it
            self._emit(t.id, EventKind.ticket_updated, {"changed": ["tags"], "tags": t.tags, "by": actor.id})
        if "assignee" in changed:
            self._emit(t.id, EventKind.assigned, {"assignee": t.assignee, "by": actor.id})
        if "status" in changed:
            self._emit(t.id, EventKind.status_changed, {**changed["status"], "by": actor.id})
            self._after_status(t)
            if t.status == TicketStatus.in_review and t.kind != TicketKind.epic:
                # p-c3c5d460: lines the doer's checker passed BEFORE the hand-off complete it now; waiting for
                # a verdict that already exists strands the ticket in_review (no role may set done by hand)
                records.safely(self._auto_advance, self.ticket(t.id))
        # c-c80f7cd8f0: setting an epic's design_ref carries it to `designed` on its own — now the declared
        # auto edge drafted→designed of the epic's workflow (its preconditions: design_ref + ≥1 criterion).
        if "design_ref" in changed:
            self.auto_carry(t, trigger="design_ref set")
        return t

    def _retype(self, actor: Participant, t: Ticket, work_type: WorkType) -> list[dict[str, str]]:
        """Owner m-b9f93cddf0: a story typed `knowledge` (research, checked by the epic's sme) that is really
        product work goes to qa once retyped. The architect or the owner retypes an epic or a story before it is
        done; every pending criterion still on the derived checker moves to the new one, and verdicted lines and
        an owner's explicit checker stay as they are. `review` is fixed at create (the review-story-last hook)."""
        if not self.workflow_of(t).allowed("set_title", actor.role):
            raise BoardError("scope", f"{actor.role} may not retype a ticket",
                             "the architect or the owner sets an epic's or a story's work_type")
        if is_topic(t):  # a topic's work_type picks its resident seat, so it stays a refusal
            raise BoardError("scope", "a topic's work_type is fixed at create",
                             "work_type is settable on epics, stories and tasks")
        if t.kind == TicketKind.task:
            advice.advise("a task's work_type is normally fixed at create; changed anyway")
        if t.status in (TicketStatus.done, TicketStatus.dropped):
            raise BoardError("transition", f"{t.id} is {t.status.value}; its type is part of the record")
        if WorkType.review in (work_type, t.work_type):
            raise BoardError("scope", "a review story is review from create to close",
                             "create a review story, or keep this one's type")
        old_checker = self.checker_for(t)
        t.work_type = work_type
        new_checker = self.checker_for(t)
        moved: list[dict[str, str]] = []
        if new_checker == old_checker:
            return moved
        for c in self.criteria(t.id):
            if c.verdict == Verdict.pending and c.checked_by == old_checker:
                c.checked_by = new_checker
                self.store.put("criterion", c)
                moved.append({"criterion": c.id, "from": old_checker, "to": new_checker})
        return moved

    def auto_carry(self, t: Ticket, *, trigger: str) -> bool:
        """S13 guards as data: carry `t` along the first `auto` edge of its workflow whose `auto_when`
        matches and whose declared (non-role) preconditions all hold. Board-authored, like the release.
        An epic moves through _advance_epic_phase (forward-only, same event); any other ticket moves here."""
        wf = self.workflow_of(t)
        for e in wf.auto_edges(t.status.value):
            if e.auto_when is not None and not wflow.when_matches(e.auto_when, t, frm=e.from_, quick=is_quick(t)):
                continue
            ctx = wflow.Ctx(self, None, t.model_copy(deep=True), wf, frm=e.from_, to=e.to)
            if wf.missing(e.requires, ctx, quick=is_quick(t), skip_roles=True) is not None:
                continue
            to = TicketStatus(e.to)
            if t.kind == TicketKind.epic and to in self._EPIC_PHASE_ORDER:
                self._advance_epic_phase(t, to, trigger=trigger)
            else:
                old = t.status
                t.status = to
                self.store.put("ticket", t)
                self._emit(t.id, EventKind.status_changed,
                           {"from": old.value, "to": to.value, "by": "board", "trigger": trigger})
                self._after_status(t)
            return True
        return False

    def _guard_transition(self, actor: Participant, t: Ticket, to: TicketStatus) -> None:
        """S13: the edge must be in the epic's workflow and every precondition it declares must hold, in
        declared order — Standard's are today's guards verbatim (edp8.workflow._arrive_guards)."""
        if is_topic(t):  # S-SME-SURFACE: a topic has no delivery walk; it is open until the owner closes it
            raise BoardError("transition", f"topic {t.id} is opened and closed by the owner, not moved",
                             "the owner closes it from its Library page (POST /v1/topics/<id>/close)")
        wf = self.workflow_of(t)
        legal = wf.legal(t.status.value)
        if to.value not in legal:
            raise BoardError("transition", f"{t.kind} {t.id} is {t.status}; cannot go to {to}",
                             f"legal from {t.status}: {sorted(legal) or 'none (terminal)'}")
        if t.kind == TicketKind.epic and to in (TicketStatus.done, TicketStatus.partial):
            held = requirements_mod.blocked_reason(self, t.id)  # s-aa76c83998: an epic can't finish with one open
            if held:
                raise BoardError("transition", f"{t.id} cannot be {to.value}: {held}",
                                 "requirement_link each one to a criterion or a design section (doc + version + heading)")
        edge = wf.edge(t.status.value, to.value)
        self._wf_check(wf, edge.requires, wflow.Ctx(self, actor, t, wf, frm=t.status.value, to=to.value))

    def _own_epic_architect(self, actor: Participant, t: Ticket) -> bool:
        """The designer of THIS epic (resident_designer hook; Standard: the architect seat
        `architect.<epic>`, its assignee or its creator) — the only one that may walk the epic to
        in_review/done/partial (Astra finding 2, s-ccdafcb229)."""
        return self.workflow_of(t).is_resident_designer(actor, t)

    def legal_transitions(self, actor: Participant, id_: str) -> dict[str, Any]:
        """Every status edge from the ticket's current status, each marked allowed/blocked for THIS
        actor with the board's own reason — the data behind the S16 status control (design §16).
        Reuses `_guard_transition` (the single rule source, so the UI cannot drift from enforcement)
        by probing a deep COPY of the ticket, so a probe never mutates the stored row. The one-line
        consequence per target is left to the client's glossary (one copy source)."""
        t = self.ticket(id_)
        out: list[dict[str, Any]] = []
        for to in sorted((TicketStatus(x) for x in self.workflow_of(t).legal(t.status.value)),
                         key=lambda s: s.value):
            probe = t.model_copy(deep=True)
            try:
                self._guard_transition(actor, probe, to)
                out.append({"to": to.value, "allowed": True, "reason": None})
            except BoardError as e:
                out.append({"to": to.value, "allowed": False, "reason": e.hint or e.message})
        return {"status": t.status.value, "transitions": out}

    def _design_gate_open(self, t: Ticket) -> bool:
        """An open design_signoff gate on the epic HARD-BLOCKS readiness below it (2026-09-01 pain:
        the board auto-readied stories and seats ran while the owner was still deciding)."""
        epic = self.epic_of(t)
        return epic.id != t.id and bool(self.open_gates(epic.id, Gate.design_signoff))

    def _released(self, b: Ticket) -> bool:
        """A predecessor no longer blocks its successors (design §24.1 release rule): it is `done`,
        OR it is a STORY that is `in_review` with an evidence_ref on every criterion — `done` is qa's
        verdict, not the successor's trigger, so an evidence-complete story releases what it holds
        while its own status waits on qa. The early-release-on-in_review branch is story-only
        (§24 finding 6): a task is a checklist and an epic is the whole deliverable — both release
        only when actually `done`, never merely evidence-complete in_review. `partial` and `dropped` are terminal
        outcomes the owner or architect decided, so they release too (architect m-23b59aec97: a review story waits on
        every sibling, and a dropped or partial sibling held it forever); `blocked` and everything before
        in_review still hold."""
        if b.status in _TERMINAL:
            return True
        if b.status == TicketStatus.in_review and b.kind == TicketKind.story:
            crits = self.criteria(b.id)
            return bool(crits) and all(c.evidence_ref for c in crits)
        return False

    def _release_successors(self, t: Ticket) -> None:
        """Promote to ready every signed-off successor of t (explicit `blocks` links t holds, plus
        the implicit review-story-waits-on-its-siblings dependency) once all ITS blockers are
        released and no design gate holds it. This only ever PROMOTES: a reopen (a qa fail walking
        a blocker in_review→in_progress) never re-blocks a successor already readied (§24.1(a),
        owner ruling 2026-09-08) — release is monotonic, the successor keeps its head start."""
        wf = self.workflow_of(t)
        if wf.hook("release_cascade") is None:
            return
        deps_raw = [self.store.get("ticket", lk.to_id)  # type: ignore[attr-defined]
                    for lk in self.store.query("link", {"from_id": t.id, "relation": Relation.blocks})]
        review = wf.hook_param("review_story_last", "work_type")
        if review and t.kind == TicketKind.story and t.parent_id:
            deps_raw += [k for k in self.children(t.parent_id) if k.work_type == review and k.id != t.id]
        seen: set[str] = set()
        deps = [d for d in deps_raw if d is not None and not (d.id in seen or seen.add(d.id))]
        for dep in deps:
            if dep.status == TicketStatus.signed_off \
                    and all(self._released(b) for b in self.blockers(dep.id)) \
                    and not self._design_gate_open(dep):
                dep.status = TicketStatus.ready
                self.store.put("ticket", dep)
                self._emit(dep.id, EventKind.status_changed,
                           {"from": "signed_off", "to": "ready", "by": "board"})

    def _after_status(self, t: Ticket) -> None:
        # §24.1(a) (live failure m-969cb61cfe): a ticket that goes terminal (dropped/done/partial)
        # closes its own open gates. A dropped epic that kept an open acceptance gate made the boot
        # re-derivation re-spawn a qa seat for a dead epic — those qa seats then verdicted a LIVE
        # epic's in_review stories. Retiring the gate the moment the epic dies removes the source.
        if t.status in _TERMINAL:
            self._close_open_gates(t)
        if t.status == TicketStatus.in_review:  # e0cec S3: at hand-off a line no live seat can clear gets a checker
            records.safely(self.requeue_checkers, t)
        # readiness: a successor waiting on this ticket becomes ready the moment this ticket is
        # RELEASED — evidence-complete in_review, or done (design §24.1: done no longer gates).
        if self._released(t):
            self._release_successors(t)
        if t.kind == TicketKind.epic and t.status == TicketStatus.in_progress:
            # Astra finding 11: an explicitly blocked epic stays blocked while its last story is
            # released; the moment it is unblocked, "every story released → in_review" applies.
            kids = self.children(t.id)
            if kids and all(k.status == TicketStatus.dropped or self._released(k) for k in kids) \
                    and self.workflow_of(t).hook("epic_auto_advance") is not None:
                self._advance_epic_phase(self.ticket(t.id), TicketStatus.in_review,
                                         trigger="every story released")
                return
        if (t.status == TicketStatus.signed_off and t.kind != TicketKind.epic
                and self.workflow_of(t).hook("release_cascade") is not None
                and not [b for b in self.blockers(t.id) if not self._released(b)]
                and not self._design_gate_open(t)):
            t.status = TicketStatus.ready
            self.store.put("ticket", t)
            self._emit(t.id, EventKind.status_changed, {"from": "signed_off", "to": "ready", "by": "board"})
        # parent derivation
        if t.parent_id:
            parent = self.store.get("ticket", t.parent_id)
            if parent is None:
                return
            kids = self.children(parent.id)
            active = any(k.status in (TicketStatus.in_progress, TicketStatus.in_review, TicketStatus.blocked) for k in kids)
            if active and parent.status in (TicketStatus.signed_off, TicketStatus.ready):
                # signed_off/ready parent (any kind, incl. a `ready` epic that is not in the epic
                # phase-order) → in_progress the moment a child is active. Unchanged.
                parent.status = TicketStatus.in_progress
                self.store.put("ticket", parent)
                self._emit(parent.id, EventKind.status_changed, {"from": "ready", "to": "in_progress", "by": "board"})
            elif (parent.kind == TicketKind.epic and parent.status == TicketStatus.in_review
                  and t.status in (TicketStatus.in_progress, TicketStatus.blocked)):
                # a story sent back (a qa fail) reopens the epic's work: in_review → in_progress
                parent.status = TicketStatus.in_progress
                self.store.put("ticket", parent)
                self._emit(parent.id, EventKind.status_changed,
                           {"from": "in_review", "to": "in_progress", "by": "board", "trigger": f"child {t.id} reopened"})
            elif (active and parent.kind == TicketKind.epic
                  and not (t.work_type == WorkType.knowledge
                           and parent.status in (TicketStatus.drafted, TicketStatus.designed))):
                # p-5592b872: a knowledge ticket is preparation, not execution — it starts before the owner's
                # sign-off and must not carry its epic past it
                # finding 4 (second-opinion 2026-09-08): also machine-carry an epic still in `designed`
                # (or `drafted`) forward when a child starts. A story can be started while its
                # epic is still `designed`, so the signed_off/ready branch alone left the epic behind
                # (reproduced: story=in_progress, epic=designed).
                self._advance_epic_phase(parent, TicketStatus.in_progress, trigger=f"child {t.id} started")
            # §24 finding 1 (independent `if`, NOT elif — second-opinion 2026-09-08): an epic opens
            # its acceptance gate once every child is dropped OR released (done, or an evidence-
            # complete in_review story), NOT only when every child is `done`. This MUST run even
            # when the active branch above just moved the epic to in_progress: a lagging parent
            # can still be ready/signed_off when its last child explicitly hands off — an `elif` skipped the gate
            # and deadlocked (qa is spawned BY the gate). qa then verdicts the in_review stories,
            # then the epic's own criteria.
            if kids and all(k.status == TicketStatus.dropped or self._released(k) for k in kids):
                if (parent.kind == TicketKind.epic and parent.status not in (TicketStatus.done, TicketStatus.partial)
                        and self.workflow_of(parent).hook("epic_auto_advance") is not None):
                    self._advance_epic_phase(self.ticket(parent.id), TicketStatus.in_review,
                                             trigger="every story released")
                elif parent.kind == TicketKind.story and parent.status == TicketStatus.in_progress:
                    self._emit(parent.id, EventKind.status_changed, {"note": "all tasks done; hand the story to review"})

    # ------------------------------------------------------------------ automatic pairing (§24 rule 3)
    def _pool_adapter(self) -> Any:
        if self._pool is not None:
            return self._pool
        from . import pool_adapter
        return pool_adapter

    def _host_free_mb(self) -> int | None:
        """Host free RAM in MB (the preflight number), or None when it cannot be read."""
        if self._free_mb is not None:
            try:
                return self._free_mb()
            except Exception:  # noqa: BLE001 — a broken probe never blocks a spawn
                return None
        try:
            import psutil
            return int(psutil.virtual_memory().available // (1024 * 1024))
        except Exception:  # noqa: BLE001
            return None

    def _seat_live(self, pid: str) -> bool:
        return self.seat_state(pid) in ("alive", "parked")

    def _enqueue_pairing(self, participant_id: str, role: str, ticket_id: str, *, held: bool = False) -> None:
        """Queue a seat for the pool-watch drain. `held` (the boot rederive) queues it without launching: only an
        explicit event (gate opened, a help message) re-enqueues it un-held and releases it."""
        with self._lock:
            if self._seat_live(participant_id):
                return
            cur = self._pending_pairings.get(participant_id)
            if cur is not None:
                if cur.get("held") and not held:
                    cur["held"] = False
                return
            self._pending_pairings[participant_id] = {"role": role, "ticket": ticket_id, "noted": False,
                                                      **({"held": True} if held else {})}

    def _rederive_pending_pairings(self, *, held: bool = False) -> None:
        """Rebuild the volatile pairing queue from durable board state (§24 finding 3), so a board
        restart between enqueue and drain never strands a resident topic seat.
        Idempotent — _enqueue_pairing skips a live seat and de-dups."""
        # scan ALL tickets — the default 500-row page would silently skip eligible stories/epics on
        # a long-lived board (second-opinion 2026-09-08), stranding their pairing after a restart.
        for t in self.store.query("ticket", {}, limit=1_000_000):  # type: ignore[assignment]
            # B: the board never staffs qa; it hints the architect when the epic moves to in_review
            if is_topic(t) and t.status not in _TERMINAL and not is_access(t):  # S-SME-SURFACE: resident until the owner closes
                role = topic_seat_role(t)  # S19: a help topic's resident seat is the doctor
                if is_help(t):
                    from . import topics  # local: topics imports board
                    if not topics.help_seat_owed(self, t):  # t-67dad8c6aa: the next message re-queues it
                        continue
                self._enqueue_pairing(f"{role}.{t.id}", role, t.id, held=held)

    def _pairing_epic_active(self, ticket_id: str) -> bool:
        """§24.1(a): the pairing's epic is still active. A qa pairing's ticket IS the epic; any other
        pairing's ticket is a story under one. A pairing whose epic is terminal (or gone) is dead."""
        t = self.store.get("ticket", ticket_id)
        if t is None:
            return False
        epic_id = t.id if t.kind == TicketKind.epic else self._epic_id_of(t.id)
        epic = self.store.get("ticket", epic_id) if epic_id else None
        return epic is not None and epic.status not in _TERMINAL

    def run_pending_pairings(self) -> dict[str, Any]:
        """Drain the pairing queue: spawn each seat whose RAM headroom is sufficient, drop one that
        already has a live seat, leave an under-RAM one queued with ONE feed note, and KEEP a seat
        whose spawn failed (pool error or a falsey adapter result) queued for the 60 s retry with
        ONE feed note. Called at every pool-watch tick and directly by tests. Returns a summary.

        The whole drain runs under a single board lock (§24.1(b), owner ruling 2026-09-08): the
        snapshot, the live-seat/RAM/spawn decision and the queue mutation are one atomic step, so
        two concurrent drainers can never both claim the same entry and double-spawn. The lock is
        re-entrant, so _spawn_seat's participant_create and _pairing_note's emit nest safely."""
        spawned: list[str] = []
        queued: list[str] = []
        failed: list[str] = []
        with self._lock:
            for pid, info in list(self._pending_pairings.items()):
                if not self._pairing_epic_active(info["ticket"]):
                    # §24.1(a): the pairing's epic died (dropped/done/partial) while it sat queued —
                    # drop it rather than spawn a checker for a dead epic.
                    self._pending_pairings.pop(pid, None)
                    continue
                if self._seat_live(pid):
                    self._pending_pairings.pop(pid, None)
                    continue
                if info.get("held"):  # owner m-e2edc8d256: a restart never launches a shell; the pairing waits
                    continue
                free = self._host_free_mb()
                if free is not None and free < self.SEAT_FLOOR_MB:
                    queued.append(pid)
                    if not info.get("noted"):
                        self._pairing_note(info["ticket"],
                                           f"{info['role']} for {info['ticket']} queued: {free} MB free")
                        info["noted"] = True
                    continue
                if self._spawn_seat(info["role"], pid, info["ticket"]):
                    spawned.append(pid)
                    self._pending_pairings.pop(pid, None)
                else:
                    # a failed spawn stays queued for the next 60 s tick; note it once (quietly)
                    failed.append(pid)
                    if not info.get("spawn_failed_noted"):
                        self._pairing_note(info["ticket"],
                                           f"{info['role']} for {info['ticket']} spawn failed; retrying next tick")
                        info["spawn_failed_noted"] = True
        return {"spawned": spawned, "queued": queued, "failed": failed}

    def _spawn_seat(self, role: str, participant_id: str, ticket_id: str) -> bool:
        """Register the seat participant (so it can be addressed and can verdict) then spawn its
        shell via the pool adapter — the assignee is never touched (a checker is not the doer).
        Returns True only when the spawn succeeded; a pool exception or an `{"ok": False}` adapter
        result returns False so the caller keeps the entry queued for the retry (§24.1(b)).

        §24 finding 4: the auto-paired seat goes through the SAME authenticated path as a
        service-spawned one — mint its per-seat EDP8_TOKEN and inject it as spawn env, so the
        qa can authenticate to the board in public mode. Trusted mode (no minter, or the
        minter returns None) injects nothing, exactly as the service route does."""
        why = non_agent_refusal(role, participant_id)
        if why or self.human_role(role):  # owner m-da9a2ae62f: never re-queued, so log and drop it
            _log.warning("pairing spawn for %s refused: %s", participant_id, why or f"{role} is a human role")
            return True
        c1 = self.qa_spawn_refusal(role, ticket_id, participant_id)  # C1: the board's own staffing obeys it too
        if c1:
            _log.warning("pairing spawn for %s dropped: %s", participant_id, c1)
            return True
        sme_off = self.sme_spawn_refusal(role, ticket_id)
        if sme_off:  # e0cec S6: dropped like a human role; the architect clears what an sme would have checked
            _log.warning("pairing spawn for %s refused: %s", participant_id, sme_off)
            return True
        if self.store.get("participant", participant_id) is None:
            try:
                self.participant_create("agent", role, participant_id, id_=participant_id)  # S13: or a custom role
            except BoardError:  # a concurrent create raced us; fine
                pass
        env: dict[str, str] | None = None
        if self._mint_token is not None:
            try:
                token = self._mint_token(participant_id)
            except Exception as e:  # noqa: BLE001 — second-opinion 2026-09-08: FAIL CLOSED.
                # A configured minter that RAISES must not silently fall back to a token-less spawn:
                # in public mode that seat could never authenticate, yet a successful spawn would
                # drop it from the queue. Keep it queued for the 60 s retry instead.
                _log.warning("token mint for %s failed; keeping the pairing queued: %s", participant_id, e)
                return False
            if token:  # a present minter returning None is trusted mode (no tokens.json) → header-only
                env = {"EDP8_TOKEN": token}
        choice = self.seat_choice_for(ticket_id, role=role)  # the epic's per-role model + effort
        refused = self.fable_refusal(role, choice.model)
        if refused:  # S4 §4.11: stays queued until a human acknowledges the Fable adversary risk
            _log.warning("pairing spawn for %s held: %s", participant_id, refused)
            return False
        if self._resume_saved_seat(participant_id, env):
            return True
        spec = self.seat_spawn_spec(ticket_id, role)  # S13: the pinned workflow's card + capacity
        if spec["env"]:
            env = {**(env or {}), **spec["env"]}
        try:
            res = self._pool_adapter().spawn(role, participant_id, env=env,
                                             model=choice.pool_model, effort=choice.effort,
                                             **spec["capacity"])
        except Exception as e:  # noqa: BLE001 — a pool hiccup keeps the seat registered; retry next tick
            _log.warning("pairing spawn for %s failed: %s", participant_id, e)
            return False
        if isinstance(res, dict) and res.get("ok") is False:
            _log.warning("pairing spawn for %s refused: %s", participant_id, res.get("error"))
            return False
        return True

    def _resume_saved_seat(self, participant_id: str, env: dict[str, str] | None = None) -> bool:
        """A seat that ran before is resumed with its own conversation, never replaced by a blank one (owner
        m-3b722c0a38: "why didnt it resume the one that you had spawned?"). False when it never ran, the pool
        cannot resume, or the resume fails: the caller then spawns fresh. `env` carries the seat's current
        EDP8_TOKEN so the resumed shell authenticates (p-451a2390)."""
        if not self.store.query("session", {"participant_id": participant_id}, limit=1):
            return False
        resume = getattr(self._pool_adapter(), "resume", None)
        if resume is None:
            return False
        try:
            res = resume(participant_id, env=env) if env else resume(participant_id)
        except Exception as e:  # noqa: BLE001 — a failed resume falls back to a fresh spawn
            _log.warning("pairing resume for %s failed, spawning fresh: %s", participant_id, e)
            return False
        if isinstance(res, dict) and res.get("ok") is False:
            _log.warning("pairing resume for %s refused, spawning fresh: %s", participant_id, res.get("error"))
            return False
        return True

    def sme_spawn_refusal(self, role: str | None, ticket_id: str | None) -> str | None:
        """e0cec S6: SMEs are opt-in per epic (tag `sme:on`, default off). The refusal for a `role=sme` spawn
        on `ticket_id`'s epic while it is off, else None. The one rule every spawn path calls."""
        if str(role or "") != Role.sme.value or not ticket_id:
            return None
        t = self.store.get("ticket", ticket_id)
        if t is None:
            return None
        try:
            epic = self.epic_of(t)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 — an orphaned chain has no epic policy to apply
            return None
        return epic_policy.sme_refusal(role, epic)

    def fable_refusal(self, role: str | None, model: str | None) -> str | None:
        """S4 (design-e963c656f5 §4.11, R5): an adversary seat on Fable is refused until a human has
        acknowledged the risk once (harness.py; the record sits beside this board's database)."""
        return harness.fable_refusal(role, model, harness.ack_path(self.store.path))

    def autolink_library(self, ticket_id: str, *, trigger: str) -> list[dict[str, Any]]:
        """S-IMPLICIT: link the Library docs whose tags match this epic/quick task (library.autolink)."""
        from .library import autolink  # local: library imports board
        return autolink(self, ticket_id, trigger=trigger)

    def _pairing_note(self, ticket_id: str, text: str) -> None:
        """Post one board-authored thread note (the queued-pairing notice)."""
        m = Message(id=new_id("m"), ticket_id=ticket_id, to=None, kind=MessageKind.note, text=text,
                    created_by="board")
        self.store.put("message", m)
        self._emit(ticket_id, EventKind.message_sent,
                   {"message": m.id, "to": None, "kind": MessageKind.note, "from": "board",
                    "from_type": "agent", "from_role": "board", "text": text[:280], "mentions": []})

    def owner_notice(self, ticket_id: str, text: str) -> Message | None:
        """s-aa76c83998 (design-63db8a7d42 item H): what used to wait in Needs you reaches the owner as a chat message.
        The board's own question to the human who owns this ticket's epic, on that ticket's thread; answered in chat
        (or settled by `settle_notice` when the thing it asks about is decided). None when nobody owns the ticket."""
        owner = self.epic_owner(ticket_id)
        if owner is None:
            return None
        t = self.ticket(ticket_id)
        m = Message(id=new_id("m"), ticket_id=ticket_id, to=owner, kind=MessageKind.question, text=text,
                    created_by="board", ask_phase=t.status.value)
        self.store.put("message", m)
        self._index("message", m.id, text)
        self._emit(ticket_id, EventKind.message_sent,
                   {"message": m.id, "to": owner, "kind": MessageKind.question, "from": "board", "from_type": "agent",
                    "from_role": "board", "text": text[:280], "mentions": []})
        return m

    def settle_notice(self, message_id: str | None, *, reason: str, via: str) -> None:
        """Settle a board notice once the thing it asked about is decided, so it stops waiting on the owner."""
        m = self.store.get("message", message_id) if message_id else None
        if m is not None and self._settled(m.id) is None:  # type: ignore[union-attr]
            self._emit(m.id, EventKind.ask_resolved,  # type: ignore[union-attr]
                       {"by": "board", "reason": reason, "via": via, "ticket": m.ticket_id})  # type: ignore[union-attr]

    # ------------------------------------------------------------------ criteria
    def checker_for(self, t: Ticket) -> str:
        """The board derives a criterion's checker from its ticket (design §24.1, owner ruling
        v22 2026-09-08; S-ROLES): **qa** checks every story/epic criterion; a
        **task** criterion is the task's own **engineer** (a task is the doer's checklist —
        self-verdicted, no paired seat, gating nothing); a knowledge ticket's criteria are the
        epic's **sme**'s (Standard; e0cec S6 — it verdicts its own after citing sources, the owner may
        overrule; Lean/Solo and a Library topic keep the **owner**'s single HITL sign-off). The doer never chooses — this
        removes the blind spot where a story froze on a checker role with no seat."""
        # S13: the checker map is the epic's workflow — the knowledge_tickets and quick_task hooks, then its
        # rules (Standard: a task → its own engineer, §24.1(d); everything else → qa).
        wf = self.workflow_of(t)
        if t.work_type == WorkType.knowledge and wf.hook("knowledge_tickets") is not None:
            if is_topic(t):  # a Library topic is the owner's own (e0cec S6: an epic's knowledge ticket is its sme's)
                return CheckedBy.owner.value
            return wf.hook_param("knowledge_tickets", "checked_by")
        if is_quick(t) and wf.hook("quick_task") is not None:
            return wf.hook_param("quick_task", "checked_by")  # S-QUICK: the owner verdicts on the ticket page
        return wf.checker_for(t, quick=is_quick(t))

    def _is_folded(self, ticket_id: str) -> bool:
        """A folded story carries criteria inherited from other stories (prefixed `(from S…)`) —
        its criteria count is not the freshly-written count the cap bounds."""
        return any((c.text or "").lstrip().startswith("(from S") for c in self.criteria(ticket_id))

    def criterion_create(self, actor: Participant, *, ticket_id: str, text: str, check: Check,
                         checked_by: str | None = None, override_reason: str | None = None) -> Criterion:
        t = self.ticket(ticket_id)
        wf = self.workflow_of(t)
        # the owner overriding the derived checker (checked_by + override_reason) is the one case
        # where a non-author writes a criterion; it bypasses the author/engineer/doer guards.
        owner_override = actor.role == Role.owner and checked_by is not None and override_reason is not None
        if not owner_override:
            if str(actor.role) not in wf.criterion_authors:
                raise BoardError("scope", f"{actor.role} may not write criteria",
                                 "architect writes epic/story criteria, engineer task criteria; "
                                 "send message_send(kind='deviation', to='architect') with the criterion text")
            # S-QUICK: a quick task has no architect — its engineer writes the criteria from the owner's
            # words, and the owner (not the doer) checks them, so the doer-writes guard is waived there.
            quick = is_quick(t)
            if actor.role == Role.engineer and t.kind != TicketKind.task and not quick:
                raise BoardError("scope", "an engineer writes criteria for its tasks only",
                                 "on a quick task (tag `quick`) the engineer writes them")
            designer = wf.hook_param("resident_designer", "role")
            if (t.assignee == actor.id and t.kind != TicketKind.task and not quick
                    and not (designer and str(actor.role) == designer and t.kind == TicketKind.epic)):
                # the architect IS the designer of epics/stories — assignment bookkeeping must not
                # deadlock criteria authoring (pain 2026-08-23 architect epic deadlock)
                advice.advise("the doer of a ticket does not normally write its criteria (its checker reads them cold); "
                              "added anyway")
        if t.status in (TicketStatus.in_review, TicketStatus.done, TicketStatus.partial, TicketStatus.dropped):
            raise BoardError("transition", f"criteria cannot be added to a {t.status} ticket")
        # §24 finding 11 (second-opinion 2026-09-08): the checker DERIVATION, the cap count and the
        # insert are one atomic step under the board lock.
        with self._lock:
            # §24: the board DERIVES the checker; the checked_by argument is accepted for one release
            # but ignored (a hint says so) unless the actor is the owner AND passes an override_reason,
            # which is recorded as a criterion_checker_overridden event.
            derived = self.checker_for(t)
            final = derived
            if checked_by is not None and checked_by != derived and actor.role == Role.owner and override_reason:
                final = checked_by
            elif checked_by is not None and checked_by != derived:
                advice.advise(f"checked_by={checked_by} ignored: the board derives the checker ({derived}); only the "
                              "owner overrides it, with an override_reason")
            if t.kind == TicketKind.story:
                # #37(b) (Astra, 2026-09-10): one "(from S…)" line used to switch the cap off for the
                # whole story, so later fresh lines went uncounted. The cap now counts the fresh
                # lines on every story, folded or not, and a total ceiling bounds fresh + inherited.
                existing = self.criteria(t.id)
                fresh = [c for c in existing if not (c.text or "").lstrip().startswith("(from S")]
                is_fresh = not text.lstrip().startswith("(from S")
                cap = wf.cap("criteria_per_story")
                if is_fresh and len(fresh) >= cap:
                    advice.advise(f"a story normally carries at most {cap} freshly-written criteria and this is "
                                  f"number {len(fresh) + 1}; tighten to the load-bearing checks, or split the story")
                if len(existing) >= 2 * cap:
                    advice.advise(f"a story normally carries at most {2 * cap} criteria in total (fresh + inherited) "
                                  f"and this is number {len(existing) + 1}; fold fewer stories into it, or split it")
            c = Criterion(id=new_id("c"), ticket_id=ticket_id, text=text, check=check,
                          checked_by=final, created_by=actor.id)  # type: ignore[arg-type]
            self.store.put("criterion", c)
        if final != derived:
            self._emit(ticket_id, EventKind.criterion_checker_overridden,
                       {"criterion": c.id, "from": derived, "to": final,
                        "reason": override_reason, "by": actor.id})
        # S16: the other order of c-c80f7cd8f0 — design_ref first, criteria second also lands the epic
        # in `designed` (epic-7f3d64e6de sat in `drafted` with both set).
        self.auto_carry(self.ticket(t.id), trigger="criterion added")
        return c

    def criterion_update(self, actor: Participant, id_: str, **kw: Any) -> Criterion:
        """See _criterion_update. A verdict the criterion's own checker role was refused is recorded (e0cec S3), so
        a checker that cannot clear its line shows up as a stuck criterion (stuck_cause `cannot_clear`)."""
        try:
            return self._criterion_update(actor, id_, **kw)
        except BoardError as e:
            if e.code == "scope" and kw.get("verdict") not in (None, Verdict.pending):
                self._note_refused_verdict(actor, id_, e.message)
            raise

    def _criterion_update(self, actor: Participant, id_: str, *, evidence_ref: str | None = None,
                          verdict: Verdict | None = None, text: str | None = None,
                          evidence_version: int | None = None, stale_ok: bool = False,
                          note: str = "", warnings: list[str] | None = None) -> Criterion:
        """`note`: the checker's one-line reason with a verdict; the board records it as a claim
        (S-IMPLICIT, records.claim_from_verdict) — no seat calls record_claim for it.
        `warnings`: filled with post-commit failures (pain p-334391e9) — once the criterion is
        stored the call succeeds; a failed event write or follow-on step is reported, never raised."""
        c: Criterion = self._get("criterion", id_, "criterion")
        t = self.ticket(c.ticket_id)
        wf = self.workflow_of(t)
        role = str(actor.role)
        if text is not None:
            if role not in wf.criterion_authors:
                raise BoardError("scope", "criterion text is edited by its authors (architect/engineer)")
            if c.verdict != Verdict.pending:
                raise BoardError("transition", "a verdicted criterion's text is frozen — add a new criterion instead")
            c.text = text
        if evidence_ref is not None:
            self._get("doc", evidence_ref, "evidence doc")
            if actor.id != t.assignee and role not in wf.criterion_checkers \
                    and not wf.allowed("evidence", role):
                raise BoardError("scope", "evidence is recorded by the ticket's doer (engineer/sme/adversary), "
                                          "its assignee, or its checker")
            if evidence_ref != c.evidence_ref:  # a new doc: the old doc's version means nothing here
                c.evidence_version = None
            c.evidence_ref = evidence_ref
        fallback: dict[str, str] | None = None
        if verdict is not None:
            # §14 finding 1/2: an owner may rule a criterion only on its OWN epic — this guards
            # BOTH the engineer-checklist branch and the checker branch (the owner-role bypass in
            # either must not cross owners). A human-owned epic refuses a foreign owner; an
            # agent-created epic has no human owner (epic_owner is None) and still reaches every
            # owner, so the None case is deliberately allowed.
            if actor.role == Role.owner:
                oid = self.epic_owner(t.id)
                if oid is not None and oid != actor.id:
                    raise BoardError("scope", "this criterion belongs to another owner's epic")
            cause = self.architect_fallback(actor, t, c)
            if cause is not None:
                # e0cec S3 (dec-49f1f6a911): the last link of the fallback chain. A stuck non-owner criterion is
                # cleared by the epic's resident architect, with its reason recorded; the owner never sees it.
                if not note.strip():
                    advice.advise("an architect fallback verdict should record its reason; recorded without one "
                                  "(criterion_update(..., note='why this stuck criterion is cleared here'))")
                fallback = {"fallback": "architect", "cause": cause, "reason": note.strip()[:240]}
            elif c.checked_by == CheckedBy.engineer.value:
                # §24.1(d): a task criterion is the doer's own checklist — its engineer (or an sme
                # standing in) self-verdicts it; no paired seat and NO doer guard (the doer IS the
                # checker here). Nothing gates on it.
                if not wf.allowed("task_verdict", role):
                    raise BoardError("scope", "a task criterion is verdicted by its engineer (the task's doer)")
            elif c.checked_by == CheckedBy.sme.value:
                self._sme_verdict_guard(actor, t, c, verdict, note)
            else:
                if role not in wf.criterion_checkers:
                    raise BoardError("scope", "verdicts are recorded by qa/owner only")
                if role != c.checked_by and actor.role != Role.owner:
                    raise BoardError("scope", f"this criterion is checked_by {c.checked_by}; you are {actor.role}")
                if actor.id == t.assignee:
                    raise BoardError("scope", "the doer cannot verdict its own ticket")
            if verdict != Verdict.pending and not c.evidence_ref:
                raise BoardError("transition", "a verdict needs evidence_ref first", "criterion_update(evidence_ref=...)")
            if verdict == Verdict.passed and c.check == Check.look and actor.role != Role.owner \
                    and c.checked_by != CheckedBy.sme.value and not self._ticket_screenshots(t.id):
                # t-cf891f387b (owner m-b1fe71dcca): a seat's look pass rests on what was seen, not on prose. The
                # owner's own verdict is the human eye; an sme line reads a doc and cites its sources (_sme_verdict_guard)
                advice.advise(f"criterion {c.id} is check=look: a pass should rest on a screenshot, and {t.id} has "
                              "no image uploaded on it since it went in_review; passed as given (upload the walk's "
                              f"screenshots and attach them to a message on {t.id} with message_send(artifacts=[...]))")
            if verdict != Verdict.pending or evidence_version is not None:
                # a pending reset that names its version records it too (qa m-db8924ad06: the row kept v2 of
                # the OLD report while citing v1 of the new one)
                # §14 finding 3: a verdict names the doc version it signed off. evidence_ref is
                # always a doc, so every pass/fail records a version — no null-version bypass of the
                # stale check on ANY path (ruling m-fb5296bfbd).
                ed = self.store.get("doc", c.evidence_ref) if c.evidence_ref else None
                cur = getattr(ed, "version", None)
                if evidence_version is not None:
                    # Refuse an OLDER version than the doc's current one (the author moved it after
                    # you read) unless stale_ok, and a nonexistent future version outright.
                    if cur is not None and evidence_version < cur and not stale_ok:
                        raise BoardError("transition",
                                         f"you are ruling version {evidence_version} but the doc is now v{cur}; "
                                         f"re-read and pass evidence_version={cur}, or stale_ok=true to sign the old one")
                    if cur is not None and evidence_version > cur:
                        raise BoardError("transition", f"the doc has no version {evidence_version} (current v{cur})",
                                         f"pass evidence_version={cur}")
                    c.evidence_version = evidence_version
                elif cur is not None:
                    # The two agent paths (PATCH /v1/criteria, MCP criterion_update) may omit the
                    # version; default it to the doc's CURRENT version and record it. The two human
                    # paths (/v1/me/verdict, legacy form) require it explicitly.
                    c.evidence_version = cur
                    advice.advise(f"evidence_version not given: recorded the evidence doc's current version (v{cur})")
            c.verdict = verdict
        self.store.put("criterion", c)
        # Everything below runs AFTER the criterion is committed: a failure here must not turn a
        # stored verdict into an error the caller retries (pain p-334391e9).
        self._criterion_after_commit(actor, t, c, verdict, note, warnings, fallback)
        return c

    SOURCES_HEADING = re.compile(r"^[ ]{0,3}#{1,6}[ \t]*(?:sources?|citations?|references?)\b[^\n]*$", re.I | re.M)
    _SOURCE_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S", re.M)

    @classmethod
    def cites_sources(cls, body_md: str) -> bool:
        """Does a doc carry a `## Sources` (or Citations/References) section with at least one list item?"""
        for m in cls.SOURCES_HEADING.finditer(body_md or ""):
            tail = (body_md or "")[m.end():]
            nxt = re.search(r"^[ ]{0,3}#{1,6}[ \t]", tail, re.M)
            if cls._SOURCE_ITEM.search(tail[: nxt.start()] if nxt else tail):
                return True
        return False

    def _sme_verdict_guard(self, actor: Participant, t: Ticket, c: Criterion, verdict: Verdict,
                           note: str) -> None:
        """e0cec S6: a knowledge ticket's lines are checked_by sme. The epic's sme (its own author included,
        the doer guard is lifted for it) may pass a line only after it checked the doc against cited sources:
        the evidence doc has a Sources section with items, and the verdict carries a note saying what it
        checked. The owner may still rule any line."""
        if actor.role == Role.owner:
            return
        if actor.role != Role.sme:
            raise BoardError("scope", f"this criterion is checked_by sme; you are {actor.role}",
                             "its sme verdicts it after checking the cited sources; the owner may too")
        if self.epic_of(t).id not in self.my_epics(actor):  # type: ignore[arg-type]
            raise BoardError("scope", f"{actor.id} is not a seat of {self.epic_of(t).id}",  # type: ignore[arg-type]
                             "only an sme of this epic verdicts its knowledge lines")
        if verdict in (None, Verdict.pending):
            return
        if not (note or "").strip():
            advice.advise("an sme verdict should record what it checked against the sources; recorded without a note "
                          "(criterion_update(..., note='checked <claim> against <source>'))")
        if verdict == Verdict.passed:
            ed = self.store.get("doc", c.evidence_ref) if c.evidence_ref else None
            if ed is None or not self.cites_sources(ed.body_md):  # type: ignore[attr-defined]
                advice.advise("an sme should pass a line only after its evidence doc cites sources; passed as given "
                              "(add a '## Sources' section with one list item per source: url, file path, doc or "
                              "message id)")

    def _criterion_after_commit(self, actor: Participant, t: Ticket, c: Criterion,
                                verdict: Verdict | None, note: str, warnings: list[str] | None,
                                fallback: dict[str, str] | None = None) -> None:
        """The steps after a stored criterion, each isolated: a failing event insert must not skip the
        quick reopen or the auto-advance (Astra finding 5). Failures are logged and returned as
        warnings, never raised — the verdict is committed and a retry would double-record it."""
        def step(name: str, fn: Any) -> None:
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                _log.exception("criterion %s stored; post-commit step %s failed", c.id, name)
                if warnings is not None:
                    warnings.append(f"criterion stored, but {name} failed ({type(e).__name__}: {e}); "
                                    "re-read the ticket before retrying")

        step("the event", lambda: self._criterion_event(actor, t, c, verdict, fallback))
        if verdict is not None and note.strip():
            step("the claim", lambda: records.safely(records.claim_from_verdict, self, actor, c, note))
        step("the quick reopen", lambda: self._reopen_quick_on_fail(self.ticket(t.id), c, actor))
        step("the auto-advance", lambda: self._auto_advance(self.ticket(t.id)))

    def _criterion_event(self, actor: Participant, t: Ticket, c: Criterion, verdict: Verdict | None,
                         fallback: dict[str, str] | None = None) -> None:
        pending = [x.id for x in self.criteria(t.id) if x.verdict != Verdict.passed]
        if verdict is not None:  # a verdict is a first-class WHO/WHAT event, not a doc edit
            self._emit(t.id, EventKind.criterion_checked,
                       {"criterion": c.id, "verdict": c.verdict, "by": actor.id, "by_type": actor.type,
                        "by_role": actor.role.value if hasattr(actor.role, "value") else actor.role,
                        "evidence": c.evidence_ref, "evidence_version": c.evidence_version,
                        "ticket": t.id, "pending": pending, "check": c.check, "checked_by": c.checked_by,
                        **(fallback or {})})
        else:
            self._emit(t.id, EventKind.doc_updated,
                       {"criterion": c.id, "verdict": c.verdict, "pending": pending, "by": actor.id})

    def _reopen_quick_on_fail(self, t: Ticket, c: Criterion, actor: Participant) -> None:
        """S-QUICK: the owner's `fail` on a handed-off quick task sends it straight back to its engineer
        (in_review → in_progress, board-authored) — there is no qa seat to route a failed verdict. The
        owner's note reaches the thread through record_verdict's message."""
        if not (is_quick(t) and t.status == TicketStatus.in_review and c.verdict == Verdict.failed
                and actor.role == Role.owner):
            return
        t.status = TicketStatus.in_progress
        self.store.put("ticket", t)
        self._emit(t.id, EventKind.status_changed, {"from": "in_review", "to": "in_progress", "by": "board",
                                                    "note": f"owner failed {c.id} on a quick task"})
        self._after_status(t)

    def _auto_advance(self, t: Ticket) -> None:
        """Complete an explicitly handed-off ticket after its checker verdicts pass.

        Evidence references may describe partial/negative results. They are prerequisites,
        never an assertion that the doer finished. Only ticket_update(in_review) hands off.
        """
        wf = self.workflow_of(t)
        if wf.hook("criteria_auto_done") is None:
            return
        crits = self.criteria(t.id)
        if not crits:
            return
        if t.status == TicketStatus.in_review and all(c.verdict == Verdict.passed for c in crits):
            if t.kind == TicketKind.epic and not any(c.checked_by == wf.epic_checker for c in crits):
                return
            if t.kind == TicketKind.epic and requirements_mod.blocked_reason(self, t.id):
                return  # s-aa76c83998: an epic can't finish with an open requirement
            t.status = TicketStatus.done
            self.store.put("ticket", t)
            self._emit(t.id, EventKind.status_changed, {"from": "in_review", "to": "done", "by": "board",
                                                        "note": "auto: all verdicts passed"})
            self._after_status(t)

    # ------------------------------------------------------------------ docs / links
    def doc_create(self, actor: Participant, *, doc_type: DocType, title: str, body_md: str, scope: str,
                   tags: list[str] | None = None, status: DocStatus | None = None, proposes: str | None = None,
                   ticket_id: str | None = None, source_url: str | None = None,
                   layout: str | None = None) -> Doc:
        """S-LIBRARY: `status=proposed` is a suggestion any seat may file (the owner approves it in the
        Library); `proposes` names the active doc it would become the next version of. Every other
        doc is authored per DOC_AUTHORS and starts active."""
        self._refuse_guest(actor, "author docs")
        self._screen(self._epic_of_scope(scope), f"{title}\n{body_md}", "doc_create")
        status = DocStatus(status or DocStatus.active)
        if status == DocStatus.active and self.topic_of_seat(actor) is not None:
            raise BoardError("scope", "a topic's sme files proposed docs; the owner activates them",
                             "topic_propose(...) or doc_create(status='proposed')")
        if status == DocStatus.retired:
            raise BoardError("invalid", "a doc cannot be created retired", "create it active or proposed")
        if status == DocStatus.active and proposes:
            raise BoardError("invalid", "`proposes` is for a proposed doc", "pass status=proposed")
        authors = self.workflow_of(scope).doc_authors(doc_type)
        if status == DocStatus.active and str(actor.role) not in authors:
            raise BoardError("scope", f"{actor.role} may not author {doc_type} docs",
                             f"authors: {sorted(authors)}; "
                             "or file it with status=proposed for the owner to approve")
        if proposes:
            target = self._get("doc", proposes, "doc")
            if target.doc_type != doc_type:
                raise BoardError("invalid", f"{proposes} is a {target.doc_type} doc, not {doc_type}",
                                 "propose a new version with the target's doc_type")
            if target.status != DocStatus.active:
                raise BoardError("invalid", f"{proposes} is {target.status}; only an active doc takes a proposal")
        d = Doc(id=new_id(doc_type.value.replace('_', '')), doc_type=doc_type, title=title, body_md=body_md,
                owner_role=actor.role, scope=scope, created_by=actor.id, tags=normalize_tags(tags),
                status=status, proposes=proposes, source_url=source_url, layout=layout or "summary_first",
                source={"participant": actor.id, "ticket": ticket_id} if status == DocStatus.proposed else None)
        self.store.put("doc", d)
        self._index_doc(d)
        self._emit(d.id, EventKind.doc_updated, {"version": 1, "doc_type": doc_type, "scope": scope, "by": actor.id,
                                                 "status": status.value, **({"proposes": proposes} if proposes else {})})
        return d

    def docs_query(self, *, doc_type: DocType | None = None, scope: str | None = None, owner_role: Role | None = None,
                   tag: str | None = None, status: DocStatus | None = None, limit: int = 500) -> list[Doc]:
        """doc_query with the S-LIBRARY filters. `status`/`tag` filter in Python: rows stored before the
        fields existed carry no column, and a SQL filter would hide them (they are active, untagged)."""
        filtered = status is not None or bool(tag)
        docs = self.store.query("doc", {"doc_type": doc_type, "scope": scope, "owner_role": owner_role},
                                limit=-1 if filtered else limit)
        if status is not None:
            docs = [d for d in docs if d.status == status]
        if tag:
            want = tag.strip().lower()
            docs = [d for d in docs if want in d.tags]
        return docs[:limit]

    def doc_resolve(self, actor: Participant, id_: str, *, approve: bool,
                    expected_version: int | None = None) -> dict[str, Any]:
        """The owner rules on a proposed doc. Approve: a proposal for an active doc becomes that doc's
        next version (links keep pointing at it, so the next brief carries it) and the proposal retires;
        a free-standing proposal becomes active. Reject: the proposal retires. `expected_version` (C17):
        the version the owner read; when given and the proposal has moved on, the ruling is refused
        (409) so it never lands on a version nobody read."""
        if actor.role != Role.owner:
            raise BoardError("scope", "only the owner approves or rejects a proposed doc")
        with self._lock, self.store._lock:
            d: Doc = self._get("doc", id_, "doc")
            if expected_version is not None and d.version != expected_version:
                raise BoardError("version_mismatch",
                                 f"you read {id_} v{expected_version}; it is now v{d.version}",
                                 f"read v{d.version}, then {'approve' if approve else 'reject'} it with expected_version={d.version}")
            if d.status != DocStatus.proposed:
                raise BoardError("invalid", f"{id_} is {d.status}, not proposed")
            target: Doc | None = None
            if not approve:
                d.status, d.resolution = DocStatus.retired, "rejected"
            elif d.proposes:
                target = self._get("doc", d.proposes, "doc")
                if target.status != DocStatus.active:
                    raise BoardError("invalid", f"{target.id} is {target.status}; reject this proposal instead")
                target.body_md, target.title, target.layout = d.body_md, d.title, d.layout
                target.tags = normalize_tags([*target.tags, *d.tags])
                target.version += 1
                self.store.put("doc", target)
                self._index_doc(target)
                self._emit(target.id, EventKind.doc_updated, {"version": target.version, "doc_type": target.doc_type,
                                                              "by": actor.id, "approved": d.id})
                d.status, d.resolution = DocStatus.retired, f"approved -> {target.id} v{target.version}"
            else:
                # the proposer's role is not an author: approval must not hand it write access
                d.status, d.resolution, d.owner_role = DocStatus.active, "approved", Role.owner
            self.store.put("doc", d)
            self._emit(d.id, EventKind.doc_updated, {"version": d.version, "doc_type": d.doc_type, "by": actor.id,
                                                     "status": d.status.value, "resolution": d.resolution})
            return {"doc": d, "target": target}

    def doc_diff(self, id_: str) -> dict[str, Any]:
        """A proposed doc against the active version it proposes (unified diff); a free-standing
        proposal diffs against nothing, so every line shows as added."""
        import difflib
        d: Doc = self._get("doc", id_, "doc")
        base: Doc | None = self.store.get("doc", d.proposes) if d.proposes else None
        old = base.body_md if base else ""
        diff = "\n".join(difflib.unified_diff(
            old.splitlines(), d.body_md.splitlines(),
            fromfile=f"{base.id} v{base.version} (active)" if base else "(none)",
            tofile=f"{d.id} v{d.version} ({d.status})", lineterm=""))
        return {"id": d.id, "status": d.status.value, "base_id": base.id if base else None,
                "base_version": base.version if base else None, "diff": diff,
                "title_changed": bool(base and base.title != d.title),
                "base_title": base.title if base else None, "title": d.title}

    def doc_update(self, actor: Participant, id_: str, *, body_md: str | None = None, title: str | None = None,
                   tags: list[str] | None = None, layout: str | None = None) -> Doc:
        with self._lock, self.store._lock:
            return self._doc_update_locked(actor, id_, body_md=body_md, title=title, tags=tags, layout=layout)

    def doc_edit(self, actor: Participant, id_: str, request) -> dict[str, Any]:
        from .doc_tools import edited_body, receipt
        with self._lock, self.store._lock:
            d = self.doc(id_)
            if not self._may_edit_doc(actor, d):
                raise BoardError("scope", f"{actor.role} may not update {d.doc_type} docs")
            if request.expected_version is not None and request.expected_version != d.version:
                raise BoardError("version_conflict", f"expected version {request.expected_version}; current version {d.version}",
                                 f"doc_read(id={id_!r}) then retry against that version")
            body = edited_body(d.body_md, request.edits)
            fields = ["body_md"] + (["title"] if request.title is not None else [])
            return receipt(self._doc_update_locked(actor, id_, body_md=body, title=request.title), fields)

    def _may_edit_doc(self, actor: Participant, d: Doc) -> bool:
        """The doc type's authors in the workflow of the doc's scope, or the role that owns the doc."""
        return str(actor.role) in self.workflow_of(d.scope).doc_authors(d.doc_type) or actor.role == d.owner_role

    def _doc_update_locked(self, actor: Participant, id_: str, *, body_md: str | None = None,
                           title: str | None = None, tags: list[str] | None = None,
                           layout: str | None = None) -> Doc:
        d: Doc = self._get("doc", id_, "doc")
        own_draft = (d.status == DocStatus.proposed and not d.source_url
                     and (d.source or {}).get("participant") == actor.id)  # p-ff30576a: its own unapproved note
        if self.topic_of_seat(actor) is not None and not own_draft:
            if d.status == DocStatus.active:
                raise BoardError("scope", f"{id_} is active; a topic's sme proposes its next version",
                                 f"topic_propose(..., proposes={id_!r}) — the owner approves it in the Library")
            # adversary 09-23 #6: a proposal's Source · fetched-at header is the board's stamp from a receipt;
            # an edit would forge it — the seat files a fresh proposal instead
            raise BoardError("scope", f"{id_} carries a board-stamped source; a topic's sme does not edit docs",
                             "topic_propose(...) files a new proposal (proposes=<doc> for a next version)")
        if not own_draft and not self._may_edit_doc(actor, d):
            raise BoardError("scope", f"{actor.role} may not update {d.doc_type} docs")
        self._refuse_guest(actor, "edit docs")
        if body_md is not None or title is not None:
            self._screen(self._epic_of_scope(d.scope), f"{title or ''}\n{body_md or ''}", "doc update/edit")
        if (body_md is None and title is None and (tags is None or normalize_tags(tags) == d.tags)
                and (layout is None or layout == d.layout)):
            return d
        d.body_md = body_md if body_md is not None else d.body_md
        d.layout = layout or d.layout  # S17: a summary-first rewrite clears the legacy flag; nothing infers it
        d.title = title if title is not None else d.title
        d.tags = normalize_tags(tags) if tags is not None else d.tags
        d.version += 1
        self.store.put("doc", d)
        self._index_doc(d)
        self._emit(d.id, EventKind.doc_updated, {"version": d.version, "doc_type": d.doc_type, "by": actor.id})
        return d

    def doc(self, id_: str, version: int | None = None) -> Doc:
        if version is None:
            return self._get("doc", id_, "doc")
        d = self.store.doc_version(id_, version)
        if d is None:
            raise BoardError("not_found", f"doc {id_} has no version {version}",
                             f"versions: {self.store.doc_versions(id_)}")
        return d

    def link_create(self, actor: Participant, *, from_id: str, to_id: str, relation: Relation) -> Link:
        self._refuse_guest(actor, "create links (a link would widen what a guest can read)")
        return self._link_create(actor, from_id=from_id, to_id=to_id, relation=relation)

    def _link_create(self, actor: Participant, *, from_id: str, to_id: str, relation: Relation) -> Link:
        for x in (from_id, to_id):
            if not any(self.store.get(t, x) for t in ("ticket", "doc", "artifact")):
                raise BoardError("not_found", f"{x!r} is not a ticket, doc or artifact")
            art = self.store.get("artifact", x)
            if art is not None and getattr(art, "staged", False):  # §18.1: staged uploads are invisible
                raise BoardError("scope", f"artifact {x} is a staged upload; attach it with a message first")
        if relation == Relation.extends:  # layering is doc->doc; a dangling layer is a broken reading chain
            for x in (from_id, to_id):
                if self.store.get("doc", x) is None:
                    raise BoardError("scope", f"extends links DOCS only; {x!r} is not a doc",
                                     "layer docs with extends; tie docs to tickets via uses_strategy/uses_domain")
        dup = [lk for lk in self.store.query("link", {"from_id": from_id, "to_id": to_id, "relation": relation})]
        if dup:
            return dup[0]  # type: ignore[return-value]
        # second-opinion 2026-09-08: the insert and its readiness reconciliation are one atomic step
        # under the board lock, so a successor cannot slip ready→in_progress between them (which
        # would dodge the walk-back) and two racing link_creates cannot interleave.
        with self._lock:
            lk = Link(id=new_id("lk"), from_id=from_id, to_id=to_id, relation=relation, created_by=actor.id)
            self.store.put("link", lk)
            if relation == Relation.blocks:
                self._reconcile_blocks(from_id, to_id)
        return lk

    def _reconcile_blocks(self, from_id: str, to_id: str) -> None:
        """A new `blocks` link ({from} blocks {to}) must reconcile the successor's readiness right
        away (§24 finding 7) — no later transition on the predecessor will revisit it otherwise:
        if the predecessor is already released, promote the successor (and its chain) via the normal
        release path; if the successor was already `ready` and this new blocker is NOT released, walk
        it back to `signed_off` so it does not run ahead of an unfinished dependency."""
        pred = self.store.get("ticket", from_id)
        succ = self.store.get("ticket", to_id)
        if pred is None or succ is None:  # a doc/artifact link — nothing to reconcile
            return
        if self._released(pred):
            self._release_successors(pred)
        elif succ.status == TicketStatus.ready:
            succ.status = TicketStatus.signed_off
            self.store.put("ticket", succ)
            self._emit(succ.id, EventKind.status_changed,
                       {"from": "ready", "to": "signed_off", "by": "board",
                        "note": f"new blocker {from_id} is not released"})

    def links(self, **filters: Any) -> list[Link]:
        return self.store.query("link", filters)  # type: ignore[return-value]

    _LAYER_RELS = ("uses_strategy", "uses_domain", "epic uses_strategy", "epic uses_domain", "extends")

    def _layer_docs(self, t, epic, have: set[str], rel_by_doc: dict[str, str]) -> list[Doc]:
        """S17 (design-f39cf0db7d decision 5): the strategy/domain docs a story's seat must read, now that the
        ruleset tool is gone — the epic's uses_strategy/uses_domain docs and every `extends` parent of a linked
        layer (general after specific). Each is listed once, with the relation that brought it in."""
        out: list[Doc] = []
        if epic.id != t.id:
            for lk in self.links(from_id=epic.id):
                if lk.relation in (Relation.uses_strategy, Relation.uses_domain) and lk.to_id not in have:
                    d = self.store.get("doc", lk.to_id)
                    if d:
                        have.add(d.id)
                        rel_by_doc[d.id] = f"epic {lk.relation.value}"
                        out.append(d)  # type: ignore[arg-type]
        queue = [i for i, r in rel_by_doc.items() if r in self._LAYER_RELS]
        while queue:
            child = queue.pop(0)
            for lk in self.links(from_id=child, relation=Relation.extends):
                if lk.to_id in have:
                    continue
                d = self.store.get("doc", lk.to_id)
                if d:
                    have.add(d.id)
                    rel_by_doc[d.id] = "extends"
                    out.append(d)  # type: ignore[arg-type]
                    queue.append(d.id)
        return out

    def linked_docs(self, ticket_id: str) -> list[Doc]:
        out: list[Doc] = []
        for lk in self.links(from_id=ticket_id):
            d = self.store.get("doc", lk.to_id)
            if d:
                out.append(d)  # type: ignore[arg-type]
        return out

    # ------------------------------------------------------------------ artifacts
    def artifact_create(self, actor: Participant, *, form: ArtifactForm, uri: str, note: str = "",
                        ticket_id: str | None = None) -> Artifact:
        a = Artifact(id=new_id("art"), form=form, uri=uri, note=note, created_by=actor.id)
        self.store.put("artifact", a)
        if ticket_id:
            self.link_create(actor, from_id=ticket_id, to_id=a.id, relation=Relation.produced)
        return a

    def artifact_upload(self, actor: Participant, *, form: ArtifactForm, content_type: str,
                        filename: str = "", note: str = "") -> Artifact:
        """Record a STAGED upload artifact (design §18.1): metadata only — the service has
        already streamed the sniffed bytes to <uploads>/<id>.<ext>. It is invisible everywhere
        until a message finalises it, and swept after 24 h if it never is. Returns the artifact
        so the caller knows the id (its content URI and the file both key off it)."""
        aid = new_id("art")
        a = Artifact(id=aid, form=form, uri=f"/v1/artifacts/{aid}/content", note=note,
                     staged=True, content_type=content_type, filename=filename, created_by=actor.id)
        self.store.put("artifact", a)
        return a

    def artifact_finalise(self, actor: Participant, *, artifact_ids: list[str],
                          ticket_id: str) -> list[Artifact]:
        """Finalise staged uploads onto a ticket (design §18.1): flip staged→false and link each
        `produced`. Validated all-or-nothing — every id and the ticket are resolved BEFORE any
        change, so a bad id leaves nothing visible (the message that carries them never posts)."""
        arts = [self._get("artifact", aid, "artifact") for aid in artifact_ids]
        t = self.ticket(ticket_id)
        for a in arts:  # a staged upload is finalised only by the actor who uploaded it (§18.1)
            if a.staged and a.created_by != actor.id:
                raise BoardError("scope", f"artifact {a.id} was uploaded by someone else; "
                                          "only its uploader can attach it")
        if guest_scope.is_guest(actor):  # e0cec S5: a guest attaches its own uploads, onto a member-epic ticket
            scope = guest_scope.scope_for(self, actor)
            if scope is None or t.id not in scope.tickets:
                raise guest_scope.not_found("ticket", t.id)
            for a in arts:
                if not a.staged and a.id not in scope.artifacts:
                    raise guest_scope.not_found("artifact", a.id)
        epic_id = t.epic_id or self.epic_of(t).id
        for a in arts:  # the secret screen reads a text upload's bytes before it becomes visible to a guest
            self._screen(epic_id, f"{a.filename}\n{self._artifact_text(a)}", f"artifact finalise ({a.id})")
        for a in arts:
            if a.staged:
                a.staged = False
                self.store.put("artifact", a)
            self._link_create(actor, from_id=ticket_id, to_id=a.id, relation=Relation.produced)
        return arts

    def _ticket_screenshots(self, ticket_id: str) -> list[str]:
        """The image uploads finalised onto a ticket (its `produced` links) since its latest move to in_review: what a
        check=look pass needs. An older shot shows an earlier build, not the one under review (qa m-5954b2e825)."""
        moved = [s for s, e in self.store.query_seq("event", {"subject_id": ticket_id, "kind": EventKind.status_changed})
                 if (e.data or {}).get("to") == TicketStatus.in_review.value]
        out = []
        for _s, lk in self.store.query_seq("link", {"from_id": ticket_id, "relation": Relation.produced},
                                           since_seq=max(moved) if moved else None):
            a = self.store.get("artifact", lk.to_id)
            if a is not None and not a.staged and (getattr(a, "content_type", "") or "").startswith("image/"):
                out.append(a.id)
        return out

    @staticmethod
    def _artifact_text(a: Artifact, cap: int = 2_000_000) -> str:
        """An upload's bytes as text when it is textual (sniffed type), else "" (images/video carry no text)."""
        ct = getattr(a, "content_type", "") or ""
        if not (ct.startswith("text/") or ct in ("application/json", "application/xml", "application/x-yaml")):
            return ""
        from . import uploads
        try:
            return uploads.content_path(a).read_bytes()[:cap].decode("utf-8", "replace")
        except OSError:
            return ""

    def artifact_unfinalise(self, *, artifact_ids: list[str], ticket_id: str) -> None:
        """Undo artifact_finalise for uploads that were staged before it ran: the message that
        should have carried them failed, so re-stage them and drop their `produced` links (§18.1)."""
        for aid in artifact_ids:
            a = self.store.get("artifact", aid)
            if a is None:
                continue
            a.staged = True
            self.store.put("artifact", a)
            for lk in self.store.query("link", {"from_id": ticket_id, "to_id": aid, "relation": Relation.produced}):
                self.store.delete("link", lk.id)

    def sweep_staged_artifacts(self, *, max_age_hours: int = 24) -> list[str]:
        """Delete staged upload artifacts (and their bytes) older than max_age_hours — an upload
        that was never finalised onto a message (design §18.1). Run at startup and hourly.
        Known limit (§14 finding 6, accepted): finalise and sweep take no shared lock, so a sweep
        that read a staged snapshot could in principle delete an artifact finalised a moment later.
        The board is single-writer (§24.1) — calls serialise — so this race cannot occur in the
        deployed topology; it is not defended against here."""
        from datetime import timedelta

        from . import uploads
        from .schemas import now as _now
        cutoff = _now() - timedelta(hours=max_age_hours)
        removed: list[str] = []
        for a in self.store.query("artifact", {}, limit=1000000):
            if not getattr(a, "staged", False) or a.created_at >= cutoff:
                continue
            self.store.delete("artifact", a.id)
            for f in uploads.uploads_dir().glob(f"{a.id}.*"):
                try:
                    f.unlink()
                except OSError:
                    pass
            removed.append(a.id)
        return removed

    # ------------------------------------------------------------------ messages / gates
    def mentions(self, text: str, *, exclude: set[str] | None = None) -> list[str]:
        """Participant ids @mentioned in text (unresolvable handles are just prose)."""
        out: list[str] = []
        for h in _mention_handles(text):
            try:
                pid = self.participant(f"@{h}").id
            except BoardError:
                continue
            if pid not in out and pid not in (exclude or set()):
                out.append(pid)
        return out

    @staticmethod
    def mention_sources(text: str, quotes: list[Any] | None) -> list[str]:
        """The texts a message's @mentions come from: its text, then every quote's note (C23).
        Kept apart so a code fence left open in one cannot swallow the next."""
        return [text or "", *(q.note for q in (quotes or []) if getattr(q, "note", None))]

    def message_mentions(self, m: Message, *, exclude: set[str] | None = None) -> list[str]:
        """Participant ids a message @mentions in its text OR in a quote's note (C23): same
        exclusions and unknown-handle-is-prose rule as `mentions`, one entry per participant."""
        out: list[str] = []
        for src in self.mention_sources(m.text, m.quotes):
            out += [p for p in self.mentions(src, exclude=exclude) if p not in out]
        return out

    def epic_owner(self, ticket_id: str) -> str | None:
        """The human who owns a ticket's epic (its creator when that is an owner-role
        participant). None for agent-created epics — there is NO fallback to a shared
        'owner' handle any more (2026-09-05 pain: every agent-created epic paged the one
        human running an unrelated epic)."""
        try:
            epic = self.epic_of(self.ticket(ticket_id))
        except BoardError:
            return None
        creator = self.store.get("participant", epic.created_by)
        if creator is not None and creator.role == Role.owner:  # type: ignore[union-attr]
            return epic.created_by
        return None

    def recovery_seat(self, ticket_id: str, exclude: set[str] | None = None) -> str | None:
        """Who is told when something on this ticket needs a decision and nobody is addressed:
        the epic's human owner, else the epic's LIVE resident architect, else nobody."""
        who = self.epic_owner(ticket_id)
        if who and who not in (exclude or set()):
            return who
        try:
            arch = self.seat_for_role("architect", self.ticket(ticket_id))
        except BoardError:
            return None
        if arch and arch not in (exclude or set()) and self.seat_state(arch) in ("alive", "parked"):
            return arch
        return None

    def pool_event_recipient(self, ticket_id: str, exclude: set[str] | None = None) -> str | None:
        """Who a pool event (crash, stall, close, resume) is told to (design-63db8a7d42 F): the epic's LIVE resident
        architect, who heals it. The owner is not paged; a quick task has no architect, so its owner is."""
        try:
            epic = self.epic_of(self.ticket(ticket_id))
        except BoardError:
            return None
        if is_quick(epic):
            return self.recovery_seat(ticket_id, exclude=exclude)
        arch = self.resident_architect(epic)
        if arch not in (exclude or set()) and self.seat_state(arch) in ("alive", "parked"):
            return arch
        # Q1: nobody can heal it, so the epic's owner hears it as a plain chat message
        owner = self.epic_owner(ticket_id)
        return owner if owner and owner not in (exclude or set()) else None

    def architect_unavailable(self, epic: Ticket) -> bool:
        """True when the epic has no LIVE resident architect to heal a pool event (or is a quick task, which has
        none): the one case a pool event may page the epic's owner."""
        return is_quick(epic) or self.seat_state(self.resident_architect(epic)) not in ("alive", "parked")

    def seat_state(self, pid: str) -> str | None:
        """Latest session state for a participant (alive|parked|dead|stalled); None = never had a shell."""
        rows = sorted(self.store.query("session", {"participant_id": pid}), key=lambda s: s.created_at)
        return rows[-1].state.value if rows else None  # type: ignore[union-attr]

    def resident_architect(self, epic: Ticket) -> str:
        """The epic's resident architect: the epic's assignee when it is an architect participant with a
        live, parked or stalled session (a resident spawned for another epic id keeps its own handle),
        else the convention architect.<epic>. Every "the architect of this epic" lookup goes through
        here — delivery, the architect listener, status recipients, spawn and close (t-cf353a4051)."""
        if epic.assignee:
            p = self.store.get("participant", epic.assignee)
            if (p is not None and p.role == Role.architect  # type: ignore[union-attr]
                    and self.seat_state(epic.assignee) in ("alive", "parked", "stalled")):
                return epic.assignee
        return f"architect.{epic.id}"

    def seat_for_role(self, role: str, t: Ticket) -> str | None:
        """The seat participant that plays `role` for ticket t: role.<t>, then up the chain to
        role.<epic>, then any role.<sibling> under the epic. A live seat wins; else a registered
        one (the next shell on it reads its inbox first thing); else None. The architect is the
        epic's live resident first (resident_architect)."""
        if role == Role.architect.value:
            resident = self.resident_architect(self.epic_of(t))
            if resident != f"architect.{self.epic_of(t).id}":
                return resident
        chain: list[str] = []
        cur: Ticket | None = t
        while cur is not None:
            chain.append(cur.id)
            cur = self.store.get("ticket", cur.parent_id) if cur.parent_id else None  # type: ignore[assignment]
        candidates = [f"{role}.{tid}" for tid in chain]
        candidates += [f"{role}.{x.id}" for x in self._descendants(chain[-1]) if x.id not in chain]
        existing = [c for c in candidates if self.store.get("participant", c) is not None]
        alive = [c for c in existing if self.seat_state(c) in ("alive", "parked")]
        return (alive or existing or [None])[0]

    def resolve_recipient(self, to: str | None, t: Ticket) -> tuple[str | None, str]:
        """A bare role name becomes the seat that plays it on this ticket's epic (owner → the
        epic's human owner). Returns (resolved_to, note); note is "" when nothing changed."""
        if not to:
            return None, ""
        if to.startswith("@"):
            return self.participant(to).id, ""
        if to == Role.owner.value:
            human = self.epic_owner(t.id)
            if human:
                return human, f"'owner' resolved to the epic's human owner {human}"
            if self.store.get("participant", to) is not None:
                return to, ""
            return to, "this epic has no human owner; nobody is paged"
        if to in {r.value for r in Role}:
            seat = self.seat_for_role(to, t)
            if seat:
                state = self.seat_state(seat) or "never spawned"
                return seat, f"'{to}' resolved to seat {seat} ({state})"
            return to, f"no {to} seat exists on this epic yet — stored as a role note; nobody is woken"
        # a bare handle ("bob") is stored as the canonical id, exactly like "@bob" — otherwise the
        # row is invisible to every by-recipient query on the id (adversary round 2 #3)
        return self.participant(to).id, ""

    def resolve(self, actor: Participant | None, *, ticket_id: str, to: str | None,
                kind: MessageKind = MessageKind.question, text: str = "") -> dict[str, Any]:
        """The composer wake preview (design §16.1): who a message to `to` of this `kind` on this
        ticket WOULD wake, and why — computed from the SAME delivery.delivery_plan that delivers,
        without persisting or publishing anything. `wakes` and `plan` are the same list (the
        criterion names it `wakes`, the SPA design §16.1 names it `plan`). `text` is the draft
        body: its @mentions are resolved exactly as message_send resolves them, so the preview
        lists the mentioned seats too (adversary round 2 #7)."""
        from . import delivery
        t = self.ticket(ticket_id)
        resolved, note = self.resolve_recipient(to, t)
        exclude = {actor.id} if actor else set()
        if resolved:
            exclude.add(resolved)
        ev = Event(id="ev-preview", subject_id=ticket_id, kind=EventKind.message_sent,
                   data={"to": resolved, "kind": kind,
                         "from": actor.id if actor else None,
                         "from_type": actor.type if actor else None,
                         "from_role": actor.role.value if actor else None,
                         "mentions": self.mentions(text, exclude=exclude)})
        wakes: list[dict[str, Any]] = []
        for pid, reasons in delivery.delivery_plan(self, ev):
            primary = self._primary(reasons)
            wakes.append({"recipient": pid, "reason": primary.value,
                          "reasons": [r.value for r in reasons],
                          "why": self._WHY_CLAUSE[primary],
                          "alive": self.seat_state(pid) in ("alive", "parked") if "." in pid else None})
        # recovery overrides any resolve_recipient note: a "nobody is woken" tail would be a lie
        # when the plan fell back to the human owner (design §16.2 rule 3 — no silent drop)
        if any(w["reason"] == Reason.recovery.value for w in wakes):
            note = "no live seat for this recipient and no architect seat on this epic; the epic's " \
                   "human owner is woken as the recovery recipient (design §16.2 rule 3)"
        elif not wakes and not note:
            note = "nobody is woken"
        return {"to": resolved, "wakes": wakes, "plan": wakes, "note": note}

    def message_send(self, actor: Participant, *, ticket_id: str, to: str | None, kind: MessageKind,
                     text: str, reply_to: str | None = None, artifacts: list[str] | None = None,
                     code_context: CodeContext | None = None, quotes: list[QuoteStored] | None = None,
                     resolves: list[str] | None = None) -> Message:
        t = self.ticket(ticket_id)
        self._guest_may_post(actor, t, kind)
        self._screen(t.epic_id or self.epic_of(t).id, text, "message_send")
        asked = to
        to, note = self.resolve_recipient(to, t)
        if reply_to:
            self._get("message", reply_to, "message")
        self._guest_refs(actor, to, reply_to, resolves, asked)
        resolves = list(dict.fromkeys(resolves or []))
        targets = self._resolve_targets(t, resolves)  # before anything is stored: a bad id changes nothing
        m = Message(id=new_id("m"), ticket_id=ticket_id, to=to, kind=kind, text=text, reply_to=reply_to,
                    created_by=actor.id, artifacts=list(artifacts or []), code_context=code_context,
                    quotes=list(quotes or []), resolves=resolves,
                    ask_phase=t.status.value if kind in ASK_KINDS else None)
        self.store.put("message", m)
        self._index("message", m.id, text)
        self._settle_asks(actor, t, m, targets)
        mentioned = self.message_mentions(m, exclude={actor.id, to} if to else {actor.id})
        if guest_scope.is_guest(actor):  # e0cec S5: a guest's @mention pages only the people of its epics
            people = guest_scope.scope_for(self, actor).people
            mentioned = type(mentioned)(p for p in mentioned if p in people)
        self._emit(t.id, EventKind.message_sent, {"message": m.id, "to": to, "kind": kind, "from": actor.id,
                                                  "from_type": actor.type, "from_role": actor.role.value,
                                                  # e0cec S5: a guest is named ext:<handle> to every seat
                                                  **({"from_handle": guest_scope.display_handle(actor)}
                                                     if guest_scope.is_guest(actor) else {}),
                                                  # C18: the cited passages ride above the preview
                                                  **({"quoted": render_quotes(m.quotes, capped=True)} if m.quotes else {}),
                                                  "text": text[:280], "mentions": mentioned,
                                                  **({"artifacts": m.artifacts} if m.artifacts else {}),
                                                  **({"asked": asked, "note": note} if note else {})})
        self.last_send_note = note
        if is_topic(t) and t.status not in _TERMINAL and actor.id != t.assignee:
            from . import topics  # local: topics imports board
            records.safely(topics.ensure_seat, self, t.id)  # the resident seat stays until the owner closes
        if kind == MessageKind.answer and reply_to:  # S-IMPLICIT: an accepted deviation is a decision
            records.safely(records.decision_from_deviation, self, actor, m)
        if t.status in (TicketStatus.ready, TicketStatus.in_progress, TicketStatus.in_review) \
                and t.kind != TicketKind.epic:
            # a new fact on the thread re-evaluates a held advance (p-c3c5d460: an in_review ticket whose lines
            # all passed is completed by the next message instead of waiting for a role that cannot set done)
            self._auto_advance(self.ticket(t.id))
        return m

    def thread(self, ticket_id: str, limit: int = 50, *, include: str | None = None) -> list[Message]:
        """The NEWEST `limit` messages on a ticket, in chronological order (adversary round 2 #5:
        oldest-first LIMIT dropped every new message once a thread outgrew the window). `include`
        names a message id that is returned in its chronological place even when it falls outside
        the window (a deep link to an old message), provided it belongs to this ticket."""
        rows = self.store.query_seq("message", {"ticket_id": ticket_id}, limit=limit, newest_first=True)
        rows.reverse()
        if include and all(m.id != include for _, m in rows):
            m = self.store.get("message", include)
            seq = self.store.seq_of("message", include)
            if m is not None and seq is not None and m.ticket_id == ticket_id:  # type: ignore[union-attr]
                rows.append((seq, m))
                rows.sort(key=lambda r: r[0])
        return [m for _, m in rows]  # type: ignore[misc]

    def gate_question(self, t: Ticket | str, gate: Gate | str) -> str:
        """The plain-words question a gate asks (t-cfd8462f9d): the workflow gate's declared `question` template,
        else the built-in one for the kind. Never empty; the ticket's title is in it, not only its id."""
        t = self.ticket(t) if isinstance(t, str) else t
        g = getattr(gate, "value", gate)
        return self._gate_question_base(t, g)

    def _gate_question_base(self, t: Ticket, g: str) -> str:
        gd = self.workflow_of(t).gates.get(g)
        vals = {"title": t.title, "id": t.id, "kind": t.kind.value}
        if gd is not None and gd.question.strip():
            try:
                return gd.question.format(**vals)
            except (KeyError, IndexError, ValueError):
                return gd.question
        if g == Gate.acceptance and t.kind == TicketKind.epic:
            n = sum(1 for k in self.children(t.id) if k.kind == TicketKind.story and k.status != TicketStatus.dropped)
            return _EPIC_ACCEPTANCE_Q.format(title=t.title, n=n, stories="story" if n == 1 else "stories")
        return GATE_QUESTIONS.get(g, "“{title}” waits on your {gate} decision: answer it here.").format(
            title=t.title, gate=g.replace("_", " "))

    def require_gate_note(self, ticket_id: str, gate: Gate, note: str | None) -> str:
        """The seat/human edge (MCP gate_open, REST open): a blank note is refused unless the workflow gate declares
        a default question, which is then the note (t-cfd8462f9d). Returns the note to store."""
        text = (note or "").strip()
        if text:
            return text
        t = self.ticket(ticket_id)
        gd = self.workflow_of(t).gates.get(gate.value)
        if gd is not None and gd.question.strip():
            return self.gate_question(t, gate)
        advice.advise(f"a {gate.value} gate should carry a note, the question the answerer is asked; opened with the "
                      "default question (pass note='…' in plain words to ask your own)")
        return self.gate_question(t, gate)

    def gate_open(self, ticket_id: str, gate: Gate, *, by: str = "board", note: str = "") -> Event:
        """S13 guards as data: a gate opens only when the preconditions its workflow declares hold, so the
        board never offers a gate the answer would refuse (S16, pain p-77ab1bf1). Standard's design_signoff
        declares the §24.1 story cap (lifted by a scope answer, owner m-b0a7f9cda9) and the sign-off lint."""
        t = self.ticket(ticket_id)
        wf = self.workflow_of(t)
        g = wf.gates.get(gate.value)
        if g is not None:
            # open-only checks (Standard: the story cap) run before the carry; the rest after it
            self._wf_check(wf, [x for x in g.requires if x.phase == "open"], wflow.Ctx(self, None, t, wf, gate=gate.value))
            if gate == Gate.design_signoff:
                # S16: an epic that already has both pieces but predates the auto-carry is carried first
                self.auto_carry(t, trigger="design_signoff opened")
                refusal = self.gate_refusal(t.id, gate)
                if refusal is not None:
                    raise refusal
        if self.open_gates(ticket_id, gate):
            return self.open_gates(ticket_id, gate)[0]
        # t-cfd8462f9d: no gate is ever stored blank, whatever the path (the edges refuse a blank note first)
        note = (note or "").strip() or self.gate_question(t, gate)
        if gate == Gate.acceptance and t.kind == TicketKind.epic:
            held = requirements_mod.blocked_reason(self, t.id)  # s-aa76c83998: an open requirement holds the gate
            if held:
                raise BoardError("transition", f"the acceptance gate waits on {held}",
                                 "requirement_link each one to a criterion or a design section (doc + version + heading)")
        notice = None
        if gate != Gate.design_signoff:  # the design sign-off stays the Approve button on the design and epic page
            notice = records.safely(self.owner_notice, t.id, f"{note} (gate: {gate.value if hasattr(gate, 'value') else gate})")
        ev = self._emit(t.id, EventKind.gate_opened, {"gate": gate, "by": by, "note": note,
                                                      **({"notice": notice.id} if notice is not None else {})})
        return ev

    def _first_cycle(self, edges: dict[str, list[str]]) -> list[str] | None:
        """First directed cycle in `edges` as a node path (…-> back to the repeat), or None."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {}
        stack: list[str] = []

        def dfs(u: str) -> list[str] | None:
            color[u] = GRAY
            stack.append(u)
            for v in edges.get(u, []):
                if color.get(v, WHITE) == GRAY:
                    return stack[stack.index(v):] + [v]
                if color.get(v, WHITE) == WHITE:
                    r = dfs(v)
                    if r:
                        return r
            stack.pop()
            color[u] = BLACK
            return None

        for n in list(edges):
            if color.get(n, WHITE) == WHITE:
                r = dfs(n)
                if r:
                    return r
        return None

    def _design_signoff_lint(self, epic_id: str) -> str | None:
        """Design §24 rule 2 (v22): the one plain sentence that refuses a design_signoff answer, or
        None when the epic is clean. Offenders: (a) a non-review, non-knowledge story criterion
        checked by owner (no seat path — qa is auto-paired, owner is not a per-story
        seat); (b) a `blocks` cycle among the epic's tickets; (c) a non-review story blocked by the
        review story (the review pass runs after delivery, never before)."""
        stories = [k for k in self._descendants(epic_id) if k.kind == TicketKind.story]
        by_id = {s.id: s for s in stories}
        wf = self.workflow_of(epic_id)
        paired = wf.hook("acceptance_pairs_checker") is not None  # (a) holds while a checker seat is paired
        review = wf.hook_param("review_story_last", "work_type")
        for s in stories:
            if not paired or s.work_type in (WorkType.review, WorkType.knowledge):
                continue
            for c in self.criteria(s.id):
                if c.checked_by == CheckedBy.owner.value:
                    return (f"criterion {c.id} on story {s.id} is checked by owner, which has no seat "
                            f"path before the story is done — the board derives qa; drop the "
                            f"owner override (a per-story human check is not a seat)")
        edges: dict[str, list[str]] = {}
        for lk in self.store.query("link", {"relation": Relation.blocks}):
            if self._epic_id_of(lk.from_id) == epic_id and self._epic_id_of(lk.to_id) == epic_id:
                edges.setdefault(lk.from_id, []).append(lk.to_id)
        cyc = self._first_cycle(edges)
        if cyc:
            return f"a blocks chain has a cycle ({' -> '.join(cyc)}) — break it before sign-off"
        for lk in self.store.query("link", {"relation": Relation.blocks}):
            frm, to = by_id.get(lk.from_id), by_id.get(lk.to_id)
            if review and frm is not None and to is not None and frm.work_type == review \
                    and to.work_type != review:
                return (f"non-review story {to.id} is blocked by the review story {frm.id} — the "
                        f"review pass runs after delivery, not before; remove that blocks link")
        return None

    def gate_answer(self, actor: Participant, ticket_id: str, gate: Gate, answer: str) -> Event:
        """Legacy acceptance-only path; negative feedback must use typed review decisions."""
        with self._lock, self.store.transaction():
            ev = self._gate_answer_locked(actor, ticket_id, gate, answer)
        # S-IMPLICIT: the answered gate is a decision; a signed-off design pulls in its tagged Library docs
        records.safely(records.decision_from_gate, self, actor, ticket_id, gate, answer, ev.data.get("message"))
        if gate == Gate.design_signoff:
            records.safely(self.autolink_library, ticket_id, trigger="design_signoff")
        return ev

    def gate_answer_refusal(self, actor: Participant, ticket_id: str, gate: Gate) -> BoardError | None:
        """The refusal `actor` answering `gate` on `ticket_id` would get, or None when the answer would
        land. One rule for the answer itself and for every list that offers the gate (S16 §4.16:
        Needs you never lists a gate the owner cannot answer) — read from the gate's declared answerers
        and preconditions in the epic's workflow (S13)."""
        wf = self.workflow_of(ticket_id)
        g = wf.gates.get(gate.value)
        answerers = set(g.answerers) if g is not None else wf.gate_answerers
        if actor.type != "human":  # S11 F2: a gate is a person's decision, whatever the role's human flag
            return BoardError("scope", f"gate {gate} is answered by a human, not an agent ({actor.role})")
        if str(actor.role) not in answerers:
            return BoardError("scope", f"gate {gate} is answered by a human owner, not {actor.role}")
        if not self.open_gates(ticket_id, gate):
            return BoardError("transition", f"no open {gate} gate on {ticket_id}")
        if g is None:
            return None
        t = self.ticket(ticket_id)
        r = wf.missing(g.answer_requires + g.requires, wflow.Ctx(self, actor, t, wf, gate=gate.value),
                       quick=is_quick(t), phase="answer")
        return None if r is None else BoardError(r.code, r.message, r.hint)

    def gate_refusal(self, ticket_id: str, gate: Gate) -> BoardError | None:
        """Why `gate` on this ticket cannot be answered (so is not opened either), naming the missing
        piece from the gate's declared preconditions; None when it is answerable."""
        t = self.ticket(ticket_id)
        wf = self.workflow_of(t)
        g = wf.gates.get(gate.value)
        if g is None:
            return None
        r = wf.missing(g.requires, wflow.Ctx(self, None, t, wf, gate=gate.value), quick=is_quick(t), phase="answer")
        return None if r is None else BoardError(r.code, r.message, r.hint)

    def design_signoff_refusal(self, ticket_id: str) -> BoardError | None:
        """S16 (pain p-77ab1bf1): why a design_signoff on this ticket cannot be answered — Standard's
        declared preconditions (the quick-task design note; the epic, in a designed phase, with its
        design_ref and acceptance criteria; the §24 rule 2 lint)."""
        return self.gate_refusal(ticket_id, Gate.design_signoff)

    def _gate_answer_locked(self, actor: Participant, ticket_id: str, gate: Gate, answer: str) -> Event:
        refusal = self.gate_answer_refusal(actor, ticket_id, gate)
        if refusal is not None:
            raise refusal
        return self._record_gate_answer(actor, ticket_id, gate, answer)

    def _record_gate_answer(self, actor: Participant, ticket_id: str, gate: Gate, answer: str) -> Event:
        am = self.message_send(actor, ticket_id=ticket_id, to=None, kind=MessageKind.answer, text=f"[{gate}] {answer}")
        opened = self.open_gates(ticket_id, gate)  # the notice the gate raised stops waiting once it is answered
        ev = self._emit(ticket_id, EventKind.gate_answered, {"gate": gate, "answer": answer, "by": actor.id,
                                                             "message": am.id})
        for o in opened:
            self.settle_notice(o.data.get("notice"), reason="gate_answered", via=ev.id)
        if gate == Gate.design_signoff and self.ticket(ticket_id).kind == TicketKind.epic:
            # c-c80f7cd8f0: the human's word IS the acceptance (a rejection is a steer, not a gate
            # answer — the lint above already refused a non-go), so the board carries the epic to
            # `signed_off` from the answer itself, no architect ticket_update.
            self._advance_epic_phase(self.ticket(ticket_id), TicketStatus.signed_off,
                                     trigger="design_signoff accepted")
            # the human's word releases what the gate held back: signed-off, unblocked stories go ready now
            for k in self._descendants(ticket_id):
                if k.status == TicketStatus.signed_off:
                    self._after_status(k)
        return ev

    def _design_signed(self, ticket_id: str) -> bool:
        """The owner answered a design_signoff gate on this ticket and none is open now."""
        if self.open_gates(ticket_id, Gate.design_signoff):
            return False
        return any(e.data.get("gate") == Gate.design_signoff.value
                   for e in self.store.query("event", {"subject_id": ticket_id, "kind": EventKind.gate_answered}))

    def open_gates(self, ticket_id: str, gate: Gate | None = None) -> list[Event]:
        evs = self.store.query("event", {"subject_id": ticket_id,
                                          "kind": [EventKind.gate_opened, EventKind.gate_answered, EventKind.gate_closed]})
        opened: dict[str, Event] = {}
        for e in evs:  # type: ignore[assignment]
            g = e.data.get("gate")
            if e.kind == EventKind.gate_opened:
                opened[g] = e
            else:  # gate_answered (human word) or gate_closed (§24.1(a) epic retired) both retire it
                opened.pop(g, None)
        # a retired gate kind (poc/demo/adversarial/budget, O) keeps its history but is no longer open to anyone
        return [e for g, e in opened.items() if g in Gate._value2member_map_ and (gate is None or g == gate)]

    ACCEPTANCE_RETIRED_REASON = "retired in 0.10.5: acceptance gate removed (design-63db8a7d42 row C)"

    def retire_acceptance_gates(self) -> list[str]:
        """Startup migration (design-63db8a7d42 row C): the board no longer opens an acceptance gate, so close every
        one the old auto-open left behind. Idempotent: a closed gate is no longer open, so a second start finds none.
        Returns the ticket ids whose gate it closed."""
        subjects = {e.subject_id for e in self.store.query("event", {"kind": EventKind.gate_opened})  # type: ignore[union-attr]
                    if e.data.get("gate") == Gate.acceptance.value}
        closed = []
        for tid in sorted(subjects):
            for e in self.open_gates(tid, Gate.acceptance):
                c = self._emit(tid, EventKind.gate_closed, {"gate": Gate.acceptance.value, "by": "board",
                                                            "reason": self.ACCEPTANCE_RETIRED_REASON})
                self.settle_notice(e.data.get("notice"), reason="gate_closed", via=c.id)
                closed.append(tid)
        return closed

    def _close_open_gates(self, t: Ticket) -> None:
        """§24.1(a): retire every open gate on a ticket that has gone terminal (dropped/done/partial),
        so a dead epic never keeps an acceptance/design_signoff gate that re-derivation would honour."""
        for e in self.open_gates(t.id):
            c = self._emit(t.id, EventKind.gate_closed, {"gate": e.data.get("gate"), "by": "board",
                                                         "reason": f"{t.kind} {t.id} is {t.status}"})
            self.settle_notice(e.data.get("notice"), reason="gate_closed", via=c.id)

    # ------------------------------------------------------------------ sessions (pool-owned)
    def session_upsert(self, *, id_: str, participant_id: str, ticket_id: str | None, pool_id: str,
                       state: SessionState, resume_token: str = "", reason: str = "",
                       presence_stale: bool = False) -> Session:
        prev = self.store.get("session", id_)
        # presence_stale: the sweep had no fresh answer for a LIVE row. Keep the previous state
        # (never downgrade a healthy seat to dead on a missed probe) and stamp when staleness
        # began; emit nothing. A positive answer (presence_stale=False) clears the stamp.
        if presence_stale and prev is not None:
            eff_state = prev.state
            stale_since = prev.presence_stale_since or now()
        else:
            eff_state = state
            stale_since = None
        # the current run began at the first mirror, and again when a closed seat resumes (close-race window)
        if prev is None or (prev.state == SessionState.dead and eff_state != SessionState.dead):
            started_seq: int | None = self.store.max_seq()
        else:  # a row from before the field is backfilled on its next mirror (R3), so later deaths use a boundary
            started_seq = prev.started_seq if prev.started_seq is not None else self._legacy_run_start(prev)
        s = Session(id=id_, participant_id=participant_id, ticket_id=ticket_id, pool_id=pool_id, state=eff_state,
                    resume_token=resume_token or (prev.resume_token if prev else ""), last_output_at=now(),
                    reason=reason or (prev.reason if prev else ""), presence_stale_since=stale_since,
                    started_seq=started_seq, created_by="pool")
        self.store.put("session", s)
        if (not presence_stale and ticket_id and eff_state in (SessionState.dead, SessionState.stalled)
                and (prev is None or prev.state != eff_state)):
            kind = EventKind.shell_dead if eff_state == SessionState.dead else EventKind.shell_stalled
            # "interrupted": the app was force-quit with the seat live (the owner's own act): never a page
            clean = any(k in (reason or "").lower() for k in CLEAN_CLOSE_REASONS)
            self._emit(ticket_id, kind, {"session": id_, "participant": participant_id,
                                         "reason": reason or "no reason recorded", "clean": clean,
                                         "run": started_seq})  # a resumed session's next close is a new wake
            # a seat is gone: a criterion only it could clear gets a fresh checker. Not when it parked on purpose
            # (closed itself deferred, or the owner reaped or force-quit it): a fresh checker would undo the park
            # and pop a new window per close (owner m-b0c290f469: qa was respawned three times while told to hold)
            parked = any(k in (reason or "").lower() for k in PARKED_CLOSE_REASONS)
            if kind == EventKind.shell_dead:
                # one close, one hint (m-65df772509: one qa close cost the architect 14 turns): the dead-qa hints and the
                # messages that raced the close are collected, then told as ONE closed_seat_message
                token = _CLOSE_FOLD.set({"dead_qa": {}, "messages": []})
                try:
                    if not parked:
                        records.safely(self._requeue_epic_checkers, ticket_id)
                    # c-a7059e9d27: a message that raced the close is hinted, never lost
                    records.safely(self._hint_messages_lost_to_close, participant_id, started_seq)
                finally:
                    fold = _CLOSE_FOLD.get()
                    _CLOSE_FOLD.reset(token)
                records.safely(self._emit_close_hint, participant_id, ticket_id, fold)
            if not clean:  # Q1/R4: with no live architect to heal it, the epic's owner is told in plain chat
                records.safely(self._page_owner_unhealed, ticket_id, participant_id, id_, kind, reason)
        elif (not presence_stale and ticket_id and eff_state == SessionState.alive
              and prev is not None and prev.state in (SessionState.dead, SessionState.stalled, SessionState.parked)):
            # F: a resume is a pool event too: the epic's architect hears it (a stall that cleared and a parked
            # seat that woke included)
            self.hint_architect(ticket_id, "seat_resumed", f"seat {participant_id} is running again on {ticket_id}",
                                seat=participant_id, session=id_)
            records.safely(self._tell_owner_resumed, ticket_id, participant_id, id_)
        return s

    def _legacy_run_start(self, sess: Session) -> int | None:
        """The run boundary of a session row written before `started_seq` (R3): the later of the row's own insert seq
        (the seat's first mirror, which a plain update never moves) and its latest `seat_resumed` hint. None only when
        neither exists, and the close-race sweep then uses its 180 s fallback."""
        seqs: list[int] = []
        first = self.store.seq_of("session", sess.id)
        if first is not None:
            seqs.append(first)
        for seq, e in self.store.query_seq("event", {"kind": EventKind.board_hint}, limit=500, newest_first=True):
            if e.data.get("hint") == "seat_resumed" and e.data.get("seat") == sess.participant_id:  # type: ignore[union-attr]
                seqs.append(seq)
                break
        return max(seqs) if seqs else None

    def owner_chat(self, ticket_id: str, text: str, *, key: str) -> Message | None:
        """A plain board chat message from the board to the human who owns this ticket's epic (a note, so it is not an
        ask and clears nothing). `key` dedupes: one message per key. None when nobody owns the ticket."""
        owner = self.epic_owner(ticket_id)
        if owner is None:
            return None
        with self._lock:
            for m in self.store.query("message", {"created_by": "board", "to": owner, "ticket_id": ticket_id},
                                      limit=500, newest_first=True):
                if f"[{key}]" in m.text:  # type: ignore[union-attr]
                    return None
            full = f"{text} [{key}]"
            m = Message(id=new_id("m"), ticket_id=ticket_id, to=owner, kind=MessageKind.note, text=full,
                        created_by="board")
            self.store.put("message", m)
            self._index("message", m.id, full)
            self._emit(ticket_id, EventKind.message_sent,
                       {"message": m.id, "to": owner, "kind": MessageKind.note, "from": "board", "from_type": "agent",
                        "from_role": "board", "text": full[:280], "mentions": []})
            return m

    def _page_owner_unhealed(self, ticket_id: str, participant_id: str, session_id: str, kind: EventKind,
                             reason: str) -> None:
        """Q1: a crash or stall nobody can heal reaches the epic's owner as plain chat, once per event."""
        epic = self.epic_of(self.ticket(ticket_id))
        if not self.architect_unavailable(epic):
            return
        last = self.store.query("event", {"subject_id": ticket_id, "kind": kind}, limit=1, newest_first=True)
        what = "crashed" if kind == EventKind.shell_dead else "stalled"
        self.owner_chat(ticket_id, f"Seat {participant_id} {what} on {ticket_id} ({reason or 'no reason recorded'}) and "
                                   f"this epic has no live architect to heal it (session {session_id}). Resume it "
                                   f"from the Seats page.", key=f"pool:{last[0].id}" if last else f"pool:{session_id}:{what}")

    def _tell_owner_resumed(self, ticket_id: str, participant_id: str, session_id: str) -> None:
        """R4: close the loop: a seat the owner was told about is running again."""
        owner = self.epic_owner(ticket_id)
        if owner is None:
            return
        tag = f"(session {session_id})"
        for m in self.store.query("message", {"created_by": "board", "to": owner, "ticket_id": ticket_id}, limit=500,
                                  newest_first=True):
            if tag in m.text:  # type: ignore[union-attr]
                if "is running again" in m.text:  # type: ignore[union-attr]
                    return
                break
        else:
            return  # the owner was never told it went down
        last = self.store.query("event", {"subject_id": ticket_id, "kind": EventKind.board_hint}, limit=1,
                                newest_first=True)
        self.owner_chat(ticket_id, f"Seat {participant_id} is running again on {ticket_id} {tag}.",
                        key=f"pool:{last[0].id}" if last else f"pool:{session_id}:resumed")

    # ------------------------------------------------------------------ context / board / feed
    def _hook_roles(self, hook: str) -> set[str]:
        """The `role` param of `hook` across Standard and every pinned workflow where it is on."""
        refs = {wflow.ref(wflow.STANDARD_ID, 1)} | self.workflows.pinned_refs()
        return {r for r in (self.workflows.resolve(x).hook_param(hook, "role") for x in refs) if r}

    def my_tickets(self, p: Participant) -> list[Ticket]:
        """Tickets a participant works on: assigned; for checkers (qa/owner) also tickets in_review
        whose criteria are checked by their role, and for qa epics with an open acceptance gate; else created-by."""
        mine: list[Ticket] = list(self.store.query("ticket", {"assignee": p.id}))  # type: ignore[arg-type]
        # a per-seat participant is NAMED for its ticket (role.<ticket_id>): surface that ticket
        # even when unassigned (checkers are deliberately not assigned — pain 2026-09-01: a
        # spawned checker booted with an empty plate while its story was still in_progress)
        if "." in p.id:
            tid = p.id.split(".", 1)[1]
            tk = self.store.get("ticket", tid)
            if tk is not None and all(x.id != tk.id for x in mine):
                mine.append(tk)  # type: ignore[arg-type]
        if str(p.role) in self.checker_roles():
            # §24.1(b) (live failure m-969cb61cfe): a qa seat is named qa.<epic_id> and verdicts ONLY
            # its own epic. Two qa seats for dropped epics were seeing — and starting to verdict — a
            # LIVE epic's in_review stories because qa context was not epic-scoped. Confine both the
            # in_review-story surfacing and the acceptance-gate epics to the seat's own epic.
            own_epic = (p.id.split(".", 1)[1]
                        if (str(p.role) in self._hook_roles("one_checker_per_epic") and "." in p.id) else None)
            for t in self.store.query("ticket", {"status": TicketStatus.in_review}):
                if own_epic is not None and self._epic_id_of(t.id) != own_epic:
                    continue
                if any(c.checked_by == p.role.value for c in self.criteria(t.id)) and all(x.id != t.id for x in mine):
                    mine.append(t)  # type: ignore[arg-type]
            if str(p.role) in self._hook_roles("acceptance_pairs_checker"):
                for t in self.store.query("ticket", {"kind": TicketKind.epic}):
                    if own_epic is not None and t.id != own_epic:
                        continue
                    if self.open_gates(t.id, Gate.acceptance) and all(x.id != t.id for x in mine):
                        mine.append(t)  # type: ignore[arg-type]
        if not mine:
            mine = [t for t in self.store.query("ticket", {}) if t.created_by == p.id]  # type: ignore[misc]
        return mine

    def _doc_summary(self, d: Doc, n: int = 300) -> dict[str, Any]:
        return {"id": d.id, "doc_type": d.doc_type, "title": d.title, "version": d.version, "scope": d.scope,
                "tags": list(d.tags), "status": d.status.value,
                **({"proposes": d.proposes} if d.proposes else {}),
                "summary": d.body_md[:n].strip(), "full": "doc_read(id)", "layout": d.layout,
                **doc_tools.legacy_note(d)}  # S17 decision 6: the head starts here; a legacy doc says so

    def _context_reader(self):
        from .context_delta import ContextReader
        if not hasattr(self, '_context_reader_instance'):
            self._context_reader_instance = ContextReader(self)
        return self._context_reader_instance

    def context(self, p: Participant, ticket_id: str | None = None) -> dict[str, Any]:
        # S-IMPLICIT: newly filed pains become lessons before the read (mtime-gated: a no-op when unchanged)
        records.safely(records.lessons_from_pains, self)
        # Store lock holds the snapshot and its watermark at one read boundary.
        with self._lock, self.store._lock:
            out = self._context_snapshot(p, ticket_id)
            out['cursor'] = self._context_reader().baseline(p, ticket_id)
            return out

    def context_delta(self, p: Participant, cursor: str, ticket_id: str | None = None,
                      limit: int = 50) -> dict[str, Any]:
        with self._lock, self.store._lock:
            return self._context_reader().delta(p, cursor, ticket_id, limit)

    def _context_snapshot(self, p: Participant, ticket_id: str | None = None) -> dict[str, Any]:
        """Everything a shell needs: identity, its ticket chain, criteria, linked docs, thread, open asks."""
        tickets = [self.ticket(ticket_id)] if ticket_id else self.my_tickets(p)
        out: dict[str, Any] = {"participant": p.model_dump(mode="json"), "tickets": [], "asks_for_me": [],
                               "hint": ""}
        answered = {m.reply_to for m in self.store.query("message", {"created_by": p.id}, limit=100000)
                    if m.reply_to}
        for t in tickets:
            view = self.ticket_view(t.id)
            if "thread" in view:  # dec-7581ebda87: what is addressed to the seat rides before the newest-N window
                for_you = self._for_you(p, t.id, answered)
                view = {k2: v2 for k, v in view.items()
                        for k2, v2 in ((("for_you", for_you), (k, v)) if k == "thread" else ((k, v),))}
            strategy_links = view.get("strategy_links", False)
            if ticket_id or len(tickets) <= RECALL_TICKETS:
                # S-IMPLICIT: recall hits ride along (records.recall: FTS + graph, capped, no model call)
                view["recall"] = records.safely(records.recall, self.store, t.id) or {"items": []}
            out["tickets"].append(view)
            if strategy_links and not out["hint"]:
                out["hint"] = ("strategy/domain docs are linked: doc_read(id) returns each one's summary and "
                               "heading map; read the sections your work touches")
        out["asks_for_me"] = self.inbox(p)
        records.safely(self.note_seen, p, [a["id"] for a in out["asks_for_me"]])  # listed in context(): read (close-hint receipt)
        if not tickets:
            out["hint"] = "no ticket assigned or created by you yet"
        return out

    def _for_you(self, p: Participant, ticket_id: str, answered: set[str]) -> list[dict[str, Any]]:
        """Owner ruling m-9f2b933578 (dec-7581ebda87): the exam's Q2 miss was a message addressed to the seat
        buried under newer posts. Rows on this ticket addressed to the seat (its handle, or its role) and not
        its own, oldest first, newest FOR_YOU_KEEP. context() is the boot read and has no cursor, so every
        such row is "since the cursor"; one the seat already replied to carries `answered: true`."""
        rows = self.store.query_seq("message", {"ticket_id": ticket_id}, limit=100000)
        hits = [(seq, m) for seq, m in rows if m.to in (p.id, p.role.value) and m.created_by != p.id]
        return [with_quotes({**m.model_dump(mode="json"), **code_row(m), "seq": seq,
                             **({"answered": True} if m.id in answered else {})}, m, capped=True)
                for seq, m in hits[-FOR_YOU_KEEP:]]

    def inbox(self, p: Participant) -> list[dict[str, Any]]:
        """Unanswered questions AND steers addressed to this participant, oldest first. A directed
        steer to a booting seat must survive the whoami->subscribe race, so this is queried BY
        RECIPIENT (indexed) — a global scan capped at 200 rows silently dropped every recent ask
        once the board grew (drill 2026-09-03). Empty list == clear to close.
        A HUMAN is also waited on by a deviation sent to them, and by a status whose `status` is blocked,
        failed or deferred (v34, owner m-8aa6439a77: 18 of 21 items were FYI statuses). A plain status,
        a note or a finding never counts (narrows m-bf83c16da7 / t-9e9ba3a6e5)."""
        kinds = [MessageKind.question, MessageKind.steer]
        if p.type == "human":
            kinds += [MessageKind.status, MessageKind.deviation]
        asks = [m for m in reversed(self.store.query("message", {"to": p.id, "kind": kinds},
                                                     limit=100, newest_first=True))
                if m.kind != MessageKind.status or m.status in ASK_STATUSES]
        if p.role.value != p.id:
            # a bare-role address (legacy rows, or a role with no seat when sent) reaches the
            # seats of that role ON THE SAME EPIC only — never every seat of the role fleet-wide
            mine = self.my_epics(p)
            for m in reversed(self.store.query("message", {"to": p.role.value,
                                                           "kind": [MessageKind.question, MessageKind.steer]},
                                               limit=100, newest_first=True)):
                if self._epic_id_of(m.ticket_id) in mine:  # type: ignore[union-attr]
                    asks.append(m)

        def _ask_live(m: Message) -> bool:
            """An ask dies with its EPIC (or a dropped ticket) — but a DONE ticket in a live
            epic still takes questions (post-hoc reviews are real; drill 2026-09-03)."""
            tk = self.store.get("ticket", m.ticket_id)
            if tk is None or tk.status == TicketStatus.dropped:  # type: ignore[union-attr]
                return False
            return self.epic_of(tk).status not in _TERMINAL  # type: ignore[arg-type]

        def _ask_row(m: Message) -> dict[str, Any]:
            row = with_quotes(m.model_dump(mode="json"), m, capped=True, refs=False)  # asks survive every pass
            sender = self.store.get("participant", m.created_by)
            row["from_type"] = getattr(sender, "type", "agent") if sender else "agent"
            row["from_role"] = getattr(getattr(sender, "role", None), "value", "unknown") if sender else "unknown"
            if guest_scope.is_guest(sender):  # e0cec S5: an outside person, never mistaken for a teammate
                row["from_handle"] = guest_scope.display_handle(sender)
            row["answer_with"] = (f"message_send(ticket_id={m.ticket_id!r}, kind='answer', "
                                  f"to={m.created_by!r}, reply_to={m.id!r})")
            return row

        rows = [_ask_row(m) for m in asks if not self.ask_resolved(m) and _ask_live(m)]
        return rows

    def ask_resolved(self, m: Message) -> bool:
        """Whether a directed question/steer no longer waits on anyone (t-899d295194, c-8f893cc2e8).
        Resolved when (a) its AGENT author's seat is closed — the latest session is dead, so nobody
        is left to read an answer (a human author, or an agent that never had a shell, stays open);
        (b) any kind=answer replies to it; or (c) any message from the ADDRESSEE replies to it — owners
        answer with notes and mentions, never kind=answer (26 "unanswered" on epic-44a0576511, 18 from
        closed seats). v34 (owner m-8aa6439a77) adds, for a HUMAN addressee: (d) any later message of theirs on
        the same ticket addressed to the asker, reply_to or not (the owner answered m-584a1c342d with
        m-f5f30e92bb and it stayed highlighted); (e) their dismissal (an ask_dismissed event).
        e0cec S3 (owner R3, dec-49f1f6a911) adds the stored settles, each an `ask_resolved` event carrying
        {by, reason, via}: (f) a reply/quote of any other seat, (g) `resolves=[id]`, (h) a later message of the
        human owner it is addressed to on the same ticket, (i) the ticket moving past the status it was asked in.
        The one rule the inbox, the epic's Needs attention and the attention trail read."""
        if self._settled(m.id) is not None:
            return True
        author = self.store.get("participant", m.created_by)
        if (author is not None and author.type == "agent"  # type: ignore[union-attr]
                and self.seat_state(m.created_by) == "dead"):
            return True
        for r in self.store.query("message", {"reply_to": m.id}, limit=200):
            if self._is_addressee(r.created_by, m.to):  # type: ignore[union-attr]
                return True
            if r.kind == MessageKind.answer and not self._is_guest_id(r.created_by):  # type: ignore[union-attr]
                return True  # S13 F7: a guest answers only what was asked of it
        human = self._human_addressee(m)
        if human is None:
            return False
        for e in self.store.query("event", {"subject_id": m.id, "kind": EventKind.ask_dismissed}, limit=20):
            if e.data.get("by") == human.id:  # type: ignore[union-attr]
                return True
        for r in self.store.query("message", {"ticket_id": m.ticket_id, "created_by": human.id}, limit=500):
            if r.created_at > m.created_at and self._is_addressee(m.created_by, r.to):  # type: ignore[union-attr]
                return True
        return False

    # ------------------------------------------------------------------ stuck criteria (e0cec S3, dec-49f1f6a911)
    REQUEUE_CAP = 3  # fresh checkers queued per seat id; after that the line is left to the architect

    def qa_ready(self, epic: Ticket) -> bool:
        """Guard C1 (owner: one qa per epic, once every story is in review; dec-40efecb36c): the epic has at least one
        story, every story that is not dropped is in_review, done or partial (review stories included: the
        adversarial review lands last and qa must see its findings), and no qa seat of the epic is live."""
        return self.qa_wait(epic) is None

    def qa_wait(self, epic: Ticket) -> str | None:
        """Why qa may not be spawned on this epic yet (the C1 refusal text), or None when it may."""
        stories = [k for k in self.children(epic.id) if k.kind == TicketKind.story and k.status != TicketStatus.dropped]
        if not stories:
            return f"{epic.id} has no story yet"
        waiting = [k.id for k in stories if k.status not in (TicketStatus.in_review, TicketStatus.done,
                                                             TicketStatus.partial)]
        if waiting:
            return (f"{len(waiting)} stor{'y is' if len(waiting) == 1 else 'ies are'} not in_review or done yet "
                    f"({', '.join(waiting[:5])})")
        if self._live_seats(Role.qa.value, epic.id):
            return f"a qa seat is already up on {epic.id}: one qa per epic"
        return None

    def qa_spawn_refusal(self, role: Any, ticket_id: str | None, participant_id: str | None = None) -> str | None:
        """Guard C1 at every spawn path (no-per-story-qa-spawns, m-ffb5b04081): `spawn(role=qa)` is refused unless it
        targets the epic and `qa_ready`. Other roles pass."""
        if str(getattr(role, "value", role)) != Role.qa.value:
            return None
        tid = ticket_id or (participant_id.split(".", 1)[1] if participant_id and "." in participant_id else None)
        t = self.store.get("ticket", tid) if tid else None
        if t is not None and is_quick(t):  # type: ignore[arg-type]
            return None  # a quick task is its own root: no epic, no stories to wait on
        if t is None or t.kind != TicketKind.epic:  # type: ignore[union-attr]
            return "qa is one seat per epic: spawn it on the epic, never on a story"
        return self.qa_wait(t)  # type: ignore[arg-type]

    def hint_architect(self, ticket_id: str, hint: str, text: str, **data: Any) -> Event:
        """The board does not act where a seat can decide (design-63db8a7d42 B, D): it emits one `board_hint` the epic
        architect's listener prints."""
        return self._emit(ticket_id, EventKind.board_hint, {"hint": hint, "text": text, "by": "board", **data})

    CLOSE_RACE_WINDOW = timedelta(seconds=180)  # fallback window for a session row written before `started_seq`

    def hint_closed_seat_message(self, m: Message, to: str) -> bool:
        """One `closed_seat_message` hint per (message, seat): the message waits in a seat that is closed or closing
        and the architect decides whether to start it (c-a7059e9d27). Idempotent, so the send path and the
        close path can both call it. Returns True when a hint was newly emitted."""
        with self._lock:  # the send path and the close path may race here; check-then-emit is one step
            return self._hint_closed_seat_message_locked(m, to)

    @staticmethod
    def _hint_names(e: Event, m_id: str, seat: str) -> bool:
        """Whether a stored `closed_seat_message` hint already names this message for this seat (one per message, or
        listed in a per-close hint's `messages`)."""
        return (e.data.get("hint") == "closed_seat_message" and e.data.get("seat") == seat
                and (e.data.get("message") == m_id or m_id in (e.data.get("messages") or [])))

    def _already_hinted(self, m: Message, seat: str) -> bool:
        """Whether a `closed_seat_message` hint already names this message for this seat. A close that left messages on
        several tickets anchors its ONE hint on the seat's own ticket, not the message's (adversary report-b9c60aeff1
        F3: the send path looked only on the message's ticket and hinted the same message twice), so the recent hints
        on every subject are searched too."""
        own = self.store.query("event", {"subject_id": m.ticket_id, "kind": EventKind.board_hint}, limit=500,
                               newest_first=True)
        if any(self._hint_names(e, m.id, seat) for e in own):  # type: ignore[arg-type]
            return True
        return any(self._hint_names(e, m.id, seat) for e in self.store.query(  # type: ignore[arg-type]
            "event", {"kind": EventKind.board_hint}, limit=2000, newest_first=True))

    def _hint_closed_seat_message_locked(self, m: Message, to: str) -> bool:
        if self._already_hinted(m, to):
            return False
        self.hint_architect(m.ticket_id, "closed_seat_message",
                            f"{m.kind.value} {m.id} from {m.created_by} awaits CLOSED seat {to} on {m.ticket_id}; "
                            f"spawn or resume it when you want it read",
                            seat=to, message=m.id, sender=m.created_by)
        return True

    def _hint_messages_lost_to_close(self, participant_id: str, started_seq: int | None) -> None:
        """A seat just died: a message sent to it (addressed, or @mentioning it) during this run may have been published
        after its last read (c-a7059e9d27, Astra F2-F4). Collect the ones it left unhandled, for the ONE per-close hint
        (`_emit_close_hint`). Left out: a status post; the seat's own posts; a message it answered (`reply_to`) or settled
        (`resolves`, an ask whose ticket phase moved past it); a message it read (a `read` receipt: message_read, the inbox, context();
        a `listener` receipt only once it is older than CLOSE_RACE_WINDOW or the seat posted after it); and everything posted before its run began (`started_seq`: the spawn steer).
        `started_seq` is the store seq when the seat's current run began (a resume restarts it), with no row cap."""
        if started_seq is None:  # no boundary of any kind (no session row seq): the old 3-minute race window
            cutoff = now() - self.CLOSE_RACE_WINDOW
            rows = [m for m in self.store.query("message", {}, limit=2000, newest_first=True) if m.created_at >= cutoff]  # type: ignore[union-attr]
        else:
            rows = self.store.query("message", {}, since_seq=started_seq, limit=1_000_000)
        handled: set[str] = set()
        mine = [m.created_at for m in rows if m.created_by == participant_id]  # type: ignore[union-attr]
        last_post = max(mine) if mine else None  # anything the seat posted: proof it was acting after a printed message
        for m in rows:  # R2: only a real (non-status) post from the seat counts as handling a message
            if m.created_by == participant_id and m.kind != MessageKind.status:  # type: ignore[union-attr]
                handled.update(x for x in (m.reply_to, *m.resolves) if x)  # type: ignore[union-attr]
            if m.created_by == participant_id:  # any post, a closing status too, that names a message by id read it
                handled.update(_MESSAGE_ID.findall(m.text or ""))  # type: ignore[union-attr]
        for m in rows:
            if m.kind == MessageKind.status or m.created_by == participant_id or m.id in handled:  # type: ignore[union-attr]
                continue
            try:
                if m.to != participant_id and not (  # type: ignore[union-attr]
                        "@" in self._mention_text(m)
                        and participant_id in self.message_mentions(m, exclude={m.created_by})):  # type: ignore[union-attr,arg-type]
                    continue
                if self.was_seen(m.id, participant_id, last_post=last_post) or self._ask_phase_moved(m):  # type: ignore[arg-type]
                    continue
                fold = _CLOSE_FOLD.get()
                if fold is not None:
                    fold["messages"].append(m)
                else:
                    self.hint_closed_seat_message(m, participant_id)  # type: ignore[arg-type]
            except BoardError:
                continue

    def _ask_phase_moved(self, m: Message) -> bool:
        """An ask whose ticket has moved past the status it was made in is settled (the seat acted on it)."""
        tk = self.store.get("ticket", m.ticket_id)
        return bool(m.ask_phase and tk is not None and phase_is_past(m.ask_phase, tk.status.value))  # type: ignore[union-attr]

    def note_seen(self, actor: Participant, message_ids: Iterable[str], via: str = "read") -> None:
        """A receipt that `actor` was shown these messages. `via` is `read` (message_read, the inbox, context(): the seat
        asked for it) or `listener` (the feed listener printed it into the seat's turn: shown, not acted on). One
        receipt per (message, actor, via); wakes no one."""
        for mid in message_ids:
            if not any(e.data.get("via", "read") == via for e in self._receipts(mid, actor.id)):
                self.store.put("event", Event(id=new_id("ev"), subject_id=mid, kind=EventKind.message_seen,
                                              data={"by": actor.id, "via": via}))

    def _receipts(self, message_id: str, participant_id: str) -> list[Event]:
        return [e for e in self.store.query("event", {"subject_id": message_id, "kind": EventKind.message_seen}, limit=200)
                if e.data.get("by") == participant_id]  # type: ignore[misc]

    def was_seen(self, message_id: str, participant_id: str, *, last_post: datetime | None = None) -> bool:
        """Whether the close sweep may treat this message as handled by the seat. A `read` receipt always counts. A
        `listener` receipt means only "printed" (a seat that dies 5 s after a print never acted on it, c-a7059e9d27), so it
        counts only once it is older than CLOSE_RACE_WINDOW at this moment, or when the seat posted anything after it
        (`last_post`: the time of the seat's latest post)."""
        t = now()
        for e in self._receipts(message_id, participant_id):
            if e.data.get("via", "read") == "read":
                return True
            if t - e.created_at > self.CLOSE_RACE_WINDOW or (last_post is not None and last_post > e.created_at):
                return True
        return False

    def _emit_close_hint(self, participant_id: str, ticket_id: str, fold: dict[str, Any]) -> None:
        """The ONE hint a seat's close gives the epic architect (m-65df772509): the unread messages it left, with the qa
        criteria left pending folded into the same line. A close with only dead-qa criteria keeps its own
        `qa_checker_dead` hint (one per close, not one per ticket)."""
        msgs: list[Message] = []
        with self._lock:
            for m in fold["messages"]:
                if not self._already_hinted(m, participant_id):
                    msgs.append(m)
            dead_qa: dict[str, tuple[Ticket, Ticket, list[str]]] = fold["dead_qa"]
            if not msgs:
                for t, epic, criteria in dead_qa.values():
                    self._hint_dead_qa(t, epic, criteria)
                return
            by_ticket = {m.ticket_id for m in msgs}
            anchor = msgs[0].ticket_id if len(by_ticket) == 1 else ticket_id
            lines = ", ".join(f"{m.kind.value} {m.id} from {m.created_by}" for m in msgs)
            text = (f"CLOSED seat {participant_id} left {len(msgs)} unread message{'s' if len(msgs) != 1 else ''} "
                    f"({lines}) on {ticket_id}")
            extra: dict[str, Any] = {}
            if dead_qa:
                crit = sorted({c for _, _, cs in dead_qa.values() for c in cs})
                text += f"; qa seat is gone with {', '.join(crit)} pending"
                extra["criteria"] = crit
            self.hint_architect(anchor, "closed_seat_message", text + "; spawn or resume it when you want it read",
                                seat=participant_id, message=msgs[0].id, messages=[m.id for m in msgs],
                                sender=msgs[0].created_by, **extra)

    def _mention_text(self, m: Message) -> str:
        """Cheap superset of where a message can @mention someone: its text and its quotes' notes."""
        return " ".join(self.mention_sources(m.text, m.quotes))

    def _hint_qa_available(self, epic: Ticket) -> None:
        """B: the epic moved to in_review; qa is the architect's to start (the board enqueues and spawns nothing)."""
        self.hint_architect(epic.id, "qa_available", "epic moved to in_review, qa now available for review")

    # ------------------------------------------------------------------ requirements (s-aa76c83998, item H)
    def requirements(self, epic_id: str, *, state: str | None = None) -> list[Any]:
        epic = self.ticket(epic_id)
        if epic.kind != TicketKind.epic:
            raise BoardError("invalid", f"{epic_id} is a {epic.kind}, not an epic", "requirements(epic_id=<the epic>)")
        return requirements_mod.epic_requirements(self, epic_id, state=state)

    def requirement_mark(self, actor: Participant, **kw: Any) -> Any:
        return requirements_mod.mark(self, actor, **kw)

    def requirement_link(self, actor: Participant, req_id: str, **kw: Any) -> Any:
        return requirements_mod.link(self, actor, req_id, **kw)

    def _live_seats(self, role: str, epic_id: str, *, within: set[str] | None = None) -> list[str]:
        """Live (alive/parked) seats of `role` on the epic; `within` limits them to sessions on those tickets."""
        out: list[str] = []
        for s in self.store.query("session", {"state": [SessionState.alive, SessionState.parked]}, limit=100000):
            pid = s.participant_id  # type: ignore[union-attr]
            if pid in out or not s.ticket_id:  # type: ignore[union-attr]
                continue
            if within is not None and s.ticket_id not in within:  # type: ignore[union-attr]
                continue
            if self._epic_id_of(s.ticket_id) != epic_id:  # type: ignore[union-attr,arg-type]
                continue
            p = self.store.get("participant", pid)
            if p is not None and str(p.role) == role and self._seat_live(pid):  # type: ignore[union-attr]
                out.append(pid)
        return out

    def stuck_cause(self, c: Criterion) -> str | None:
        """Why no seat can clear this pending criterion, or None while it is not stuck (owner R3). A criterion is
        stuck only once its ticket is handed over (in_review): `checker_dead` (no live seat of its checker role),
        `doer_guard` (the only one left is the ticket's own doer), `placeholder_doer` (a task whose doer never
        had a shell, and no checker is alive), `cannot_clear` (a checker of the right role was refused its
        verdict). An owner-checked criterion is never stuck: it is the owner's by their own setting, and qa
        before `qa_ready` is waiting by design."""
        if c.verdict != Verdict.pending or c.checked_by == CheckedBy.owner.value:
            return None
        t = self.store.get("ticket", c.ticket_id)
        if t is None or t.status != TicketStatus.in_review:
            return None
        epic = self.epic_of(t)  # type: ignore[arg-type]
        if epic.status in _TERMINAL:
            return None
        role = c.checked_by
        task = role == CheckedBy.engineer.value
        within = {x for x in (t.id, t.parent_id) if x} if task else None  # type: ignore[union-attr]
        live = self._live_seats(role, epic.id, within=within)
        if role == CheckedBy.qa.value and not live and not self.qa_ready(epic):
            return None
        if role == CheckedBy.sme.value and live:
            return None  # e0cec S6: a live sme verdicts its own knowledge ticket's lines; it is not stuck
        if not live:
            if task and (not t.assignee or self.seat_state(t.assignee) is None):  # type: ignore[union-attr]
                return "placeholder_doer"
            return "checker_dead"
        if not task and not [x for x in live if x != t.assignee]:  # type: ignore[union-attr]
            return "doer_guard"
        if self.store.query("event", {"subject_id": c.id, "kind": EventKind.criterion_verdict_refused}, limit=1):
            return "cannot_clear"
        return None

    def architect_fallback(self, actor: Participant, t: Ticket, c: Criterion) -> str | None:
        """The stuck cause when `actor` is the epic's resident architect and may clear this non-owner criterion
        (the last link of the chain: requeued checker, then the architect), else None."""
        if actor.role != Role.architect or c.checked_by == CheckedBy.owner.value:
            return None
        if actor.id != self.resident_architect(self.epic_of(t)):
            return None
        if c.checked_by != CheckedBy.engineer.value and actor.id == t.assignee:
            return None  # the doer guard still holds for story/epic lines
        return self.stuck_cause(c)

    def _note_refused_verdict(self, actor: Participant, criterion_id: str, reason: str) -> None:
        c = self.store.get("criterion", criterion_id)
        if c is None or c.verdict != Verdict.pending or str(actor.role) != c.checked_by:  # type: ignore[union-attr]
            return
        try:
            self._emit(c.id, EventKind.criterion_verdict_refused,  # type: ignore[union-attr]
                       {"by": actor.id, "role": str(actor.role), "reason": reason[:240], "ticket": c.ticket_id})  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 — a note about a refusal never changes the refusal
            _log.exception("could not record the refused verdict on %s", criterion_id)

    def _checker_pairing(self, role: str, t: Ticket, epic: Ticket) -> tuple[str, str]:
        """(seat id, ticket) of the fresh checker for `role`: an engineer checks a task as engineer.<task>; every
        other role is the epic's one seat of that role (qa.<epic>)."""
        if role == CheckedBy.engineer.value:
            return f"engineer.{t.id}", t.id
        return f"{role}.{epic.id}", epic.id

    def requeue_checkers(self, t: Ticket) -> list[str]:
        """Queue a fresh checker of the same role for every stuck criterion on a handed-over ticket (chain step
        1): engineer for task lines, and a qa seat that ran and is gone (the first qa is the architect's to start, B). `cannot_clear` is left to the architect (a live
        checker of that role already exists). Event-driven only: called at hand-off and on a seat's death, never at
        boot. Idempotent: a seat that is live or already queued is skipped, and each seat id is queued at most
        REQUEUE_CAP times so a crash-looping checker cannot spawn forever. Returns the seat ids newly queued."""
        if t.status != TicketStatus.in_review:
            return []
        epic = self.epic_of(t)
        wanted: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
        dead_qa: list[str] = []
        for c in self.criteria(t.id):
            cause = self.stuck_cause(c)
            if c.checked_by == CheckedBy.sme.value:
                continue  # e0cec S6: an sme-checked line is its own sme's; nothing is queued, the architect clears a stranded one
            if c.checked_by == CheckedBy.qa.value and cause == "checker_dead" and not self.store.query(
                    "session", {"participant_id": f"qa.{epic.id}"}, limit=1):
                continue  # B: the board never STAFFS qa (the architect starts it on the qa_available hint)
            if c.checked_by == CheckedBy.qa.value and cause == "checker_dead":
                # c-4ecf4e135a: a qa seat that ran and is gone is not re-spawned either; the architect decides
                dead_qa.append(c.id)
                continue
            if cause in ("checker_dead", "placeholder_doer", "doer_guard"):
                pid, tid = self._checker_pairing(c.checked_by, t, epic)
                wanted.setdefault((pid, c.checked_by, tid), []).append((c.id, cause))
        if dead_qa:
            self._hint_dead_qa(t, epic, dead_qa)
        queued: list[str] = []
        for (pid, role, tid), items in wanted.items():
            if self._seat_live(pid) or pid in self._pending_pairings:
                continue
            prior = [e for e in self.store.query("event", {"subject_id": t.id, "kind": EventKind.checker_requeued},
                                                 limit=200) if e.data.get("seat") == pid]
            if len(prior) >= self.REQUEUE_CAP:
                continue
            ids = [i for i, _ in items]
            self._enqueue_pairing(pid, role, tid)
            self._emit(t.id, EventKind.checker_requeued, {"role": role, "seat": pid, "cause": items[0][1],
                                                          "criteria": ids})
            self._pairing_note(t.id, f"a fresh {role} checker ({pid}) is queued for {', '.join(ids)}: "
                                     f"{items[0][1].replace('_', ' ')}. If it cannot clear them, the epic's architect may, "
                                     f"with its reason recorded; the owner is not asked.")
            queued.append(pid)
        return queued

    def _hint_dead_qa(self, t: Ticket, epic: Ticket, criteria: list[str]) -> None:
        """One `qa_checker_dead` hint to the architect per (seat, criteria set): the qa seat is gone with these
        criteria pending; restarting it is the architect's call (c-4ecf4e135a). Never repeated for the same set."""
        seat = f"qa.{epic.id}"
        fold = _CLOSE_FOLD.get()
        if fold is not None:  # a seat close in progress on this thread: told once, with its messages (_emit_close_hint)
            _, _, have = fold["dead_qa"].setdefault(epic.id, (t, epic, []))
            have.extend(c for c in criteria if c not in have)
            return
        with self._lock:
            for e in self.store.query("event", {"subject_id": t.id, "kind": EventKind.board_hint}, limit=500,
                                      newest_first=True):
                if e.data.get("hint") == "qa_checker_dead" and e.data.get("seat") == seat \
                        and sorted(e.data.get("criteria") or []) == sorted(criteria):
                    return
            self.hint_architect(t.id, "qa_checker_dead",
                                f"qa seat {seat} is gone with {', '.join(criteria)} pending on {t.id}; "
                                f"restart it when you want them checked",
                                seat=seat, criteria=list(criteria))

    def _requeue_epic_checkers(self, ticket_id: str) -> None:
        """A seat on this ticket's epic died: re-check every handed-over ticket of the epic."""
        t = self.store.get("ticket", ticket_id)
        if t is None:
            return
        epic = self.epic_of(t)  # type: ignore[arg-type]
        for x in (epic, *self._descendants(epic.id)):
            if x.status == TicketStatus.in_review:
                self.requeue_checkers(x)

    def checker_receipt(self, t: Ticket) -> list[dict[str, Any]]:
        """Who will check the pending criteria of a ticket, per checker role: what a hand-off receipt names
        (pain p-892b786f: a quick ticket handed off 'to whom?')."""
        pending = [c for c in self.criteria(t.id) if c.verdict == Verdict.pending]
        epic = self.epic_of(t)
        rows: list[dict[str, Any]] = []
        for role in dict.fromkeys(c.checked_by for c in pending):
            mine = [c.id for c in pending if c.checked_by == role]
            if role == CheckedBy.owner.value:
                who = "the owner, on the ticket page"
            else:
                task = role == CheckedBy.engineer.value
                live = self._live_seats(role, epic.id, within={x for x in (t.id, t.parent_id) if x} if task else None)
                queued = [p for p in self._pending_pairings if self._pending_pairings[p]["role"] == role
                          and self._pending_pairings[p]["ticket"] in (t.id, epic.id)]
                if live:
                    who = ", ".join(live)
                elif queued:
                    who = f"{', '.join(queued)} (queued)"
                elif role == CheckedBy.qa.value and not self.qa_ready(epic):
                    who = f"qa, once {epic.id} is ready for acceptance"
                elif role == CheckedBy.sme.value:
                    who = "the sme that wrote it; if it has closed, the epic's architect clears it with its reason recorded"
                else:
                    who = f"no live {role} seat: the board queues one at hand-off; else the epic's architect may clear it"
            rows.append({"checked_by": role, "criteria": mine, "who": who})
        return rows

    # ------------------------------------------------------------------ ask resolvers (e0cec S3, dec-49f1f6a911)
    def _settled(self, ask_id: str) -> Event | None:
        """The stored settle of an ask (who and why), or None while it is open."""
        rows = self.store.query("event", {"subject_id": ask_id, "kind": EventKind.ask_resolved}, limit=1)
        return rows[0] if rows else None  # type: ignore[return-value]

    def ask_resolution(self, ask_id: str) -> dict[str, Any] | None:
        """{resolved_by, reason, via, at} for a settled ask, else None."""
        ev = self._settled(ask_id)
        if ev is None:
            return None
        return {"resolved_by": ev.data.get("by"), "reason": ev.data.get("reason"), "via": ev.data.get("via"),
                "at": ev.created_at.isoformat()}

    def _resolve_targets(self, t: Ticket, ids: list[str]) -> dict[str, Message]:
        """`resolves=[...]` of a message_send: each id must be an ask on THIS ticket's thread (a 400 names the
        first that is not). An ask that is already settled is accepted and left as it is."""
        out: dict[str, Message] = {}
        for i in ids:
            a = self.store.get("message", i)
            if a is None or a.ticket_id != t.id:  # type: ignore[union-attr]
                raise BoardError("invalid", f"resolves: {i!r} is not a message on {t.id}",
                                 "resolves=[ids of asks on this ticket's thread]")
            if not is_ask(a):  # type: ignore[arg-type]
                raise BoardError("invalid", f"resolves: {i} is a {a.kind}, not an ask",  # type: ignore[union-attr]
                                 "resolves names a question, steer, deviation or a blocked/failed/deferred status")
            out[i] = a  # type: ignore[assignment]
        return out

    def _settle_asks(self, actor: Participant, t: Ticket, m: Message, targets: dict[str, Message]) -> None:
        """The write-time resolvers of one new message: `resolves=` (g), a reply_to/message-quote naming an ask
        on this ticket from any seat but its asker (f; answer, note or status only), and a message of the human
        owner an ask is addressed to (h). Each emits one ask_resolved event; an ask already settled is skipped."""
        cand: dict[str, tuple[Message, str]] = {i: (a, "resolves") for i, a in targets.items()}
        if m.kind in (MessageKind.answer, MessageKind.note, MessageKind.status):
            named = ([m.reply_to] if m.reply_to else []) + [q.id for q in m.quotes if q.source == "message" and q.id]
            for i in named:
                a = self.store.get("message", i)
                if (a is not None and a.ticket_id == t.id and is_ask(a)  # type: ignore[union-attr,arg-type]
                        and a.created_by != actor.id):  # type: ignore[union-attr]
                    cand.setdefault(i, (a, "reply"))  # type: ignore[arg-type]
        if actor.type == "human" and actor.role == Role.owner:
            for a in self.store.query("message", {"ticket_id": t.id, "to": actor.id}, limit=500, newest_first=True):
                if is_ask(a) and a.created_by != actor.id and a.id != m.id:  # type: ignore[arg-type,union-attr]
                    cand.setdefault(a.id, (a, "owner_message"))  # type: ignore[arg-type,union-attr]
        if guest_scope.is_guest(actor):  # S13 F7 (architect ruling): a guest's reply or note may answer an ask put to
            # the guest itself, never settle one from or to another participant (as it cannot answer gates or approve)
            cand = {i: c for i, c in cand.items() if self._is_addressee(actor.id, c[0].to)}
        for i, (_, reason) in cand.items():
            if self._settled(i) is None:
                self._emit(i, EventKind.ask_resolved, {"by": actor.id, "reason": reason, "via": m.id, "ticket": t.id})

    def _is_guest_id(self, pid: str) -> bool:
        p = self.store.get("participant", pid)
        return p is not None and guest_scope.is_guest(p)

    def _settle_phase_past(self, ticket_id: str, now: str) -> None:
        """(i) the ticket reached `now`: every open ask made in an earlier phase is settled by the board."""
        if now not in PHASE_RANK:
            return
        kinds = [*ASK_KINDS, MessageKind.status]
        for a in self.store.query("message", {"ticket_id": ticket_id, "kind": kinds}, limit=500, newest_first=True):
            if (a.ask_phase and is_ask(a) and phase_is_past(a.ask_phase, now)  # type: ignore[union-attr,arg-type]
                    and self._settled(a.id) is None):  # type: ignore[union-attr]
                self._emit(a.id, EventKind.ask_resolved,  # type: ignore[union-attr]
                           {"by": "board", "reason": "phase_past", "via": ticket_id, "from": a.ask_phase,  # type: ignore[union-attr]
                            "to": now, "ticket": ticket_id})

    def ask_waits_on_owner(self, m: Message) -> bool:
        """Whether an ask is the owner's to answer (Needs you is owner-only, e0cec S3): addressed to a human by id,
        or to the bare role `owner`. An ask to a seat or a seat role is that seat's, live or not."""
        return self._human_addressee(m) is not None or (m.to or "").lstrip("@") == Role.owner.value

    def _human_addressee(self, m: Message) -> Participant | None:
        """The human an ask is addressed to by id, or None (a role, a handle or an agent)."""
        p = self.store.get("participant", m.to) if m.to else None
        return p if p is not None and p.type == "human" else None  # type: ignore[return-value,union-attr]

    def dismiss_asks(self, actor: Participant, ids: list[str]) -> list[str]:
        """v34 item 6: the viewer dismisses asks waiting on them without replying (a server-side write, so the
        rail count, the dots and every highlight clear together). Only an ask in the viewer's own inbox can be
        dismissed; anything else is refused whole. Returns the dismissed ids."""
        waiting = {a["id"]: a for a in self.inbox(actor)}
        unknown = [i for i in ids if i not in waiting]
        if unknown:
            raise BoardError("invalid", f"not waiting on {actor.id}: {', '.join(unknown)}",
                             "dismiss only asks in your own attention list (GET /v1/me/attention)")
        with self.store.transaction():
            for i in dict.fromkeys(ids):
                self._emit(i, EventKind.ask_dismissed, {"by": actor.id, "ticket": waiting[i]["ticket_id"]})
        return list(dict.fromkeys(ids))

    def _is_addressee(self, pid: str, to: str | None) -> bool:
        """pid is who `to` names: the participant id, its @handle/handle, or its bare role."""
        if not to:
            return False
        if pid == to:
            return True
        p = self.store.get("participant", pid)
        if p is None:
            return False
        handle = getattr(p, "handle", "") or ""
        return to in (handle, f"@{handle.lstrip('@')}", handle.lstrip("@")) or to == p.role.value  # type: ignore[union-attr]

    SEAT_TAG_PREFIXES = ("model:", "seat-model:", "seat-effort:", seat_choice.STORY_TAG)

    def _check_policy_tags(self, actor: Participant, t: Ticket, new_tags: list[str]) -> None:
        """e0cec S6: an epic's `sme:` and `project:` tags are well-formed and changed by the owner or THAT
        epic's architect only (a seat cannot switch SMEs on for itself or move the epic's project)."""
        old = {x for x in (t.tags or []) if x.startswith(epic_policy.POLICY_PREFIXES)}
        new = {x for x in new_tags if x.startswith(epic_policy.POLICY_PREFIXES)}
        if old == new:
            return
        bad = epic_policy.tag_problem(new_tags)
        if bad:
            raise BoardError("invalid", bad, "sme:on|off and project:<key> are an epic's policy tags")
        if actor.role != Role.owner and not (actor.role == Role.architect
                                              and self.epic_of(t).id in self.my_epics(actor)):
            raise BoardError("scope", f"{actor.role.value} {actor.id!r} may not change this epic's policy tags "
                                      f"(sme/project on {self.epic_of(t).id})",
                             "the owner or the epic's own architect switches SMEs and the project")

    def _check_seat_tags(self, actor: Participant, t: Ticket, new_tags: list[str]) -> None:
        """S-ADV findings 5 and 10 (architect m-68e58f99d4): the seat tags of an epic (`model:<role>=` option
        lists, `seat-effort:<role>=`, the old `seat-model:`/`seat-effort:`) and of a story (`seat:<role>=`,
        S7) are written by the owner or THAT epic's architect only. Every id of a `model:<role>=` list names
        an id in the role's catalog or a legacy seat name, and no effort in it is above its model's cap; a
        story's `seat:<role>=` pick names a model of the role's catalog row within its cap (seat_choice.story_pick_problem)."""
        old = {x for x in (t.tags or []) if x.startswith(self.SEAT_TAG_PREFIXES)}
        new = {x for x in new_tags if x.startswith(self.SEAT_TAG_PREFIXES)}
        if old == new:
            return
        if actor.role != Role.owner and not (actor.role == Role.architect
                                              and self.epic_of(t).id in self.my_epics(actor)):
            raise BoardError("scope", f"{actor.role.value} {actor.id!r} may not change this epic's seat choice "
                                      f"(model/effort tags on {self.epic_of(t).id})",
                             "the owner or the epic's own architect switches models and efforts")
        home = seat_choice.agent_home()
        added = sorted(new - old)
        for tag in added:
            if tag.startswith(seat_choice.ROLE_MODEL_TAG):
                role, _, rest = tag[len(seat_choice.ROLE_MODEL_TAG):].partition("=")
                parsed = [seat_choice.parse_option(x) for x in rest.split(seat_choice.OPTION_SEP) if x.strip()]
                bad = [why for _, why in parsed if why]
                bad += seat_choice.option_problems(role.strip(), [o for o, _ in parsed if o[0]], home)
                if bad:
                    raise BoardError("invalid", f"{tag}: {bad[0]}",
                                     "pick ids from GET /v1/models for that role, each optionally @low|@medium|@high "
                                     "within its cap")
        epic_tags = list(self.epic_of(t).tags or [])
        if t.kind != TicketKind.epic:
            epic_tags = [x for x in epic_tags if x.startswith(seat_choice.ROLE_MODEL_TAG)]
        for tag in added:
            if tag.startswith(seat_choice.STORY_TAG):
                why = seat_choice.parse_option(tag.partition("=")[2])[1]
                if why:
                    raise BoardError("invalid", f"{tag}: {why}", "name low, medium or high, or no effort at all")
        for role, pick in seat_choice.story_picks_from_tags(added).items():
            if t.kind == TicketKind.epic:
                raise BoardError("invalid", f"`seat:{role}=` is a story's pick, not an epic's",
                                 "put it on the story; the epic's own choice is `model:<role>=`")
            why = seat_choice.story_pick_problem(role, pick, epic_tags, home)
            if why:
                raise BoardError("invalid", why, "pick a model GET /v1/models lists for that role, at most its effort cap")

    def checker_as_doer_reason(self, t: Ticket, doer: Participant) -> str | None:
        """S-QUICK c-3000a9760a: a qa or adversary seat checks a ticket and never becomes its doer, except an
        adversary on a review-type ticket none of whose criteria it checks. The reason, or None."""
        if doer.role not in (Role.qa, Role.adversary):
            return None
        checks = any(c.checked_by == doer.role.value
                     for c in self.store.query("criterion", {"ticket_id": t.id}, limit=-1))
        if doer.role == Role.adversary and t.work_type == WorkType.review and not checks:
            return None
        return f"a {doer.role.value} seat checks {t.id} and never becomes its assignee"

    def seat_choice_for(self, ticket_id: str | None, *, model: str | None = None,
                        effort: str | None = None, role: str | None = None) -> seat_choice.SeatChoice:
        """The model + effort a spawn of `role` on `ticket_id` runs with (owner m-2d7ef9243d, S-ROLES):
        the explicit arguments win, else the ticket's own `seat:<role>=` pick (a story), else the EPIC's
        `model:<role>=` option list (first = default) / seat-model / seat-effort tags, else the role's
        catalog default (seat_choice.py); every step clamped to the model's cap. Never raises."""
        tags: list[str] = []
        story_tags: list[str] = []
        if ticket_id:
            t = self.store.get("ticket", ticket_id)
            if t is not None:
                story_tags = list(t.tags or [])  # type: ignore[attr-defined]
                try:
                    epic = self.epic_of(t)  # type: ignore[arg-type]
                    # t-f5bf848f0f: a topic's sme choice is its open receipt, not a tag the owner edits away
                    tags = self._topic_choice_tags(epic.id) if is_topic(epic) else list(epic.tags or [])
                except Exception:  # noqa: BLE001 — an orphaned chain means no epic choice
                    tags = []
        return seat_choice.resolve(model, effort, tags, seat_choice.agent_home(), role=role,
                                   story_tags=story_tags)

    def _topic_choice_tags(self, topic_id: str) -> list[str]:
        """The sme model + effort the owner picked when opening the topic (a `seat_choice` receipt event,
        topics.create), as the `model:sme=` / `seat-effort:sme=` tags seat_choice.resolve reads; [] = the
        role's catalog default."""
        for ev in self.store.query("event", {"subject_id": topic_id, "kind": EventKind.ticket_updated.value},
                                   limit=-1, newest_first=True):
            if "seat_choice" in (ev.data.get("changed") or []):
                model, effort = ev.data.get("model"), ev.data.get("effort")
                return ([f"{seat_choice.ROLE_MODEL_TAG}{Role.sme.value}={model}"] if model else []) + (
                    [f"{seat_choice.EFFORT_TAG}{Role.sme.value}={effort}"] if effort else [])
        return []

    def _epic_id_of(self, ticket_id: str) -> str | None:
        t = self.store.get("ticket", ticket_id)
        return self.epic_of(t).id if t is not None else None  # type: ignore[arg-type]

    def my_epics(self, p: Participant) -> set[str]:
        """Epic ids this participant works in: its tickets' epics plus its seat ticket's epic."""
        out: set[str] = set()
        for t in self.my_tickets(p):
            out.add(self.epic_of(t).id)
        st = self.seat_ticket(p)
        if st is not None:
            out.add(self.epic_of(st).id)
        return out

    def seat_ticket(self, p: Participant) -> Ticket | None:
        """The ticket a seat is named for (role.<ticket_id>), else its first assigned ticket."""
        if "." in p.id:
            tk = self.store.get("ticket", p.id.split(".", 1)[1])
            if tk is not None:
                return tk  # type: ignore[return-value]
        mine = self.my_tickets(p)
        return mine[0] if mine else None

    def record_status(self, actor: Participant, *, status: StatusValue, note: str = "",
                      to: str | None = None, ticket_id: str | None = None) -> tuple[Message, list[str]]:
        """A seat records the outcome of its work as a status message on its ticket and a
        status_recorded event. Returns the message and the participant ids that should be
        told: the ticket's epic architect seat, the epic's human owner, plus `to`. (The
        spawner is added by delivery, which can ask the pool for lineage.)"""
        t = self.ticket(ticket_id) if ticket_id else self.seat_ticket(actor)
        if t is None:
            raise BoardError("precondition", "no ticket to record a status on",
                             "pass ticket_id=<the ticket you worked>")
        if status in (StatusValue.done, StatusValue.handed_off):  # e0cec S3: close_self's rule, at the earlier call
            waiting = self.inbox(actor)
            if waiting:  # design-63db8a7d42 I: recorded, and the reply names what still waits
                advice.advise(f"{len(waiting)} message(s) still await you; recorded {status.value} anyway: " +
                              "; ".join(f"{m['id']} ({m['kind']} from {m['created_by']}): {(m['text'] or '')[:80]}"
                                        for m in waiting[:5]) +
                              " (sequence: inbox() → answer/act on each → record_status(...) → close_self())")
        to, _ = self.resolve_recipient(to, t)
        text = f"[{status.value}] {note}".strip()
        m = Message(id=new_id("m"), ticket_id=t.id, to=to, kind=MessageKind.status, text=text,
                    status=status, created_by=actor.id,
                    ask_phase=t.status.value if status in ASK_STATUSES else None)
        self.store.put("message", m)
        self._index("message", m.id, text)
        self._emit(t.id, EventKind.message_sent, {"message": m.id, "to": to, "kind": MessageKind.status,
                                                  "status": status.value,  # structured; delivery never parses text
                                                  "from": actor.id, "from_type": actor.type,
                                                  "from_role": actor.role.value, "text": text[:280],
                                                  "mentions": self.mentions(text, exclude={actor.id})})
        self._emit(t.id, EventKind.status_recorded, {"participant": actor.id, "status": status.value,
                                                     "ticket": t.id, "message": m.id, "note": note[:280]})
        if status in (StatusValue.done, StatusValue.handed_off, StatusValue.reviewed):
            records.safely(self.requeue_checkers, self.ticket(t.id))  # a hand-off with no live checker queues one
        recipients: list[str] = []
        epic = self.epic_of(t)
        arch = self.resident_architect(epic)
        if self.store.get("participant", arch) is not None and arch != actor.id:
            recipients.append(arch)
        owner = self.epic_owner(t.id)
        if owner and owner != actor.id and owner not in recipients:
            recipients.append(owner)
        if to and to != actor.id and to not in recipients:
            recipients.append(to)
        return m, recipients

    # ------------------------------------------------------------------ knowledge records (design-d2c4f39fc6)
    def _kglink(self, actor: Participant, from_id: str, to_id: str, kind: LinkKind) -> KgLink:
        lk = KgLink(id=new_id("kl"), from_id=from_id, to_id=to_id, kind=kind, created_by=actor.id)
        self.store.put("kglink", lk)
        return lk

    def _source_date(self, source: str | None):
        """The created_at of the message or doc a record came from — the date the ruling was MADE.
        None when there is no source or it is an id we do not hold (e.g. a commit); caller falls back
        to created_at (steer m-34d0beb1e8)."""
        if not source:
            return None
        obj = self.store.get("message", source) or self.store.get("doc", source)
        return getattr(obj, "created_at", None) if obj is not None else None

    def backfill_decided_at(self) -> dict[str, int]:
        """Data pass (no re-curation): for every live decision/claim with a source id and no decided_at,
        set decided_at from the source's date so scoring/render use when it was decided, not the evening
        it was backfilled. Re-embedding is not needed — decided_at is not part of the embedded text."""
        set_dec = set_clm = skipped = 0
        for rtype in ("decision", "claim"):
            for rec in self.store.query(rtype, limit=100000):
                if getattr(rec, "decided_at", None) is not None:
                    continue
                dt = self._source_date(getattr(rec, "source", None))
                if dt is None:
                    skipped += 1
                    continue
                rec.decided_at = dt  # type: ignore[attr-defined]
                with self.store.transaction():
                    self.store.put(rtype, rec)
                if rtype == "decision":
                    set_dec += 1
                else:
                    set_clm += 1
        return {"decisions_set": set_dec, "claims_set": set_clm, "skipped_no_source_date": skipped}

    def record_decision(self, actor: Participant, *, scope: str, text: str, detail: str = "",
                        replaces: list[str] | None = None, binding: bool | None = None,
                        source: str | None = None, domains: list[str] | None = None) -> Decision:
        """Record what is in force (design §4.1). The decision and any replaces[] flips land in ONE
        transaction, whatever ticket or thread the older decision sat in; a `replaces` kglink and a
        `came_from` kglink to the source are written alongside. Raises if a replaced id is unknown.
        `binding=None` (the default) inherits: a successor of a binding decision stays binding, so a
        re-curation cannot silently demote a must-follow rule (m-db71577ddc); pass False to demote."""
        # C17: an over-long text/detail is a typed 422 naming the limit, checked before anything is read or
        # written (Decision(...) raised a pydantic ValidationError inside the transaction: a 500)
        for field, value, cap in (("text", text, DECISION_TEXT_MAX), ("detail", detail or "", DECISION_DETAIL_MAX)):
            if len(value) > cap:
                raise BoardError("too_long", f"decision {field} is {len(value)} characters; the limit is {cap}",
                                 "put one sentence in text and the why in detail" if field == "text"
                                 else f"shorten detail to at most {cap} characters")
        replaces = list(dict.fromkeys(replaces or []))  # O1: replaces=[x, x] is one successor, one edge
        if binding is not None:
            binding = bool(binding)  # F2: a truthy non-bool (binding=1) must meet the gate as True
        epic = knowledge._epic_id_of(self.store, scope) or scope
        with self.store.transaction(immediate=True):
            # F3: the predecessors are read and the binding gate checked INSIDE a write-locked
            # transaction, so a set_binding (from this or another connection) cannot land between
            # check and commit and let a non-architect replace a rule
            olds = []
            for rid in replaces:
                old = self.store.get("decision", rid)
                if old is None:
                    raise BoardError("not_found", f"decision {rid!r} to replace does not exist",
                                     "pass ids of existing decisions in replaces[]")
                # F1: a successor may only replace a record of its own epic (withdrawn or not)
                if (knowledge._epic_id_of(self.store, old.scope or "") or old.scope) != epic:
                    raise BoardError("scope", f"decision {rid!r} belongs to another epic than {scope!r}",
                                     "replace only decisions of the new record's own epic")
                # F8: a decision that already has a successor (even if later withdrawn) is not replaced
                # twice; replace that successor instead
                if old.status == DecisionStatus.replaced or self.store.query(
                        "kglink", {"to_id": rid, "kind": LinkKind.replaces}, limit=1):
                    raise BoardError("state", f"decision {rid!r} is already replaced",
                                     "replace its live successor, not the superseded record")
                olds.append(old)
            replaces_binding = any(bool(getattr(o, "binding", False)) for o in olds)
            # binding is architect/owner-only (m-1637080c9a): setting it, or superseding a binding rule
            # (which would inherit or demote it), goes through those roles — same gate as set_binding
            if (binding is True or replaces_binding) and actor.role not in (Role.architect, Role.owner):
                raise BoardError("forbidden", f"{actor.role} may not record a binding decision or replace one",
                                 "record it non-binding and ask the architect to set_binding, or leave the "
                                 "binding rule's replacement to the architect or owner")
            if binding is None:
                binding = replaces_binding
                if binding:
                    advice.advise("binding inherited: this decision replaces a binding one, so it is binding too")
            d = Decision(id=new_id("dec"), scope=scope, text=text, detail=detail or "",
                         status=DecisionStatus.live, replaces=replaces, binding=binding,
                         source=source, decided_by=actor.id, domains=list(domains or []), created_by=actor.id,
                         decided_at=self._source_date(source))  # when it was decided (source date), not now
            self.store.put("decision", d)
            # a `decides` edge to the scope ticket/epic connects the decision for a lookup by id/path
            # (derived-edge stand-in for part_of; §3 lists decides as written-on-purpose)
            if scope:
                self._kglink(actor, d.id, scope, LinkKind.decides)
            for old in olds:
                old.status = DecisionStatus.replaced  # type: ignore[attr-defined]
                self.store.put("decision", old)
                self._kglink(actor, d.id, old.id, LinkKind.replaces)
            if source:
                self._kglink(actor, d.id, source, LinkKind.came_from)
        self._index("decision", d.id, self.store._fts_text("decision", d.model_dump(mode="json")) or text)
        return d

    def record_claim(self, actor: Participant, *, scope: str, text: str,
                     basis: ClaimBasis = ClaimBasis.assumption, evidence: list[str] | None = None,
                     source: str | None = None, status: ClaimStatus = ClaimStatus.open) -> Claim:
        """Record something stated (design §4.1/§3). A `came_from` kglink to the source is written;
        lookup labels it confirmed only when evidence is non-empty and basis is measured|ruled."""
        c = Claim(id=new_id("clm"), scope=scope, text=text, basis=basis,
                  evidence=list(evidence or []), status=status, source=source, created_by=actor.id,
                  decided_at=self._source_date(source))
        with self.store.transaction():
            self.store.put("claim", c)
            if scope:
                self._kglink(actor, c.id, scope, LinkKind.part_of)  # connects claim to its ticket/epic
            if source:
                self._kglink(actor, c.id, source, LinkKind.came_from)
            for ev in (evidence or []):
                self._kglink(actor, c.id, ev, LinkKind.proves)
        self._index("claim", c.id, text)
        return c

    def record_lesson(self, actor: Participant, *, domain: str, topic: str, text: str,
                      evidence: list[str] | None = None, scope_kind: str | None = None,
                      project: str | None = None, domains: list[str] | None = None,
                      ticket_id: str | None = None) -> Lesson:
        """Record a reusable lesson (design §3): filed by domain/topic, not by epic. Scope (e0cec S6): a
        framework lesson reaches framework epics only, a project lesson the epics of its project (see
        lesson_scope). Unset, scope comes from `project`, else from `ticket_id`'s (or the first evidence
        ticket's) epic project, else framework. A learned_from kglink goes to each evidence id."""
        if not (domain or "").strip() or not (topic or "").strip() or not (text or "").strip():
            raise BoardError("invalid", "a lesson needs a domain, a topic and one sentence of text",
                             "pass domain (e.g. operations), topic (e.g. restart) and text")
        if scope_kind is not None and scope_kind not in (LessonScope.framework.value, LessonScope.project.value):
            raise BoardError("invalid", f"scope_kind must be framework or project, not {scope_kind!r}",
                             "omit it to derive the scope from the ticket's epic")
        key = lesson_scope.project_key(project or "")
        if scope_kind == LessonScope.project.value and not key:
            raise BoardError("invalid", "a project lesson needs a project key",
                             "pass project=<key> (the epic's project:<key> tag) or ticket_id")
        if key and scope_kind is None:
            scope_kind = LessonScope.project.value
        if scope_kind is None:
            scope_kind, key = lesson_scope.default_scope(self.store, ticket_id=ticket_id, evidence=evidence)
        elif scope_kind == LessonScope.framework.value:
            key = ""
        le = Lesson(id=new_id("les"), domain=domain.strip(), topic=topic.strip(), text=text.strip(),
                    evidence=list(evidence or []), created_by=actor.id, scope_kind=scope_kind,  # type: ignore[arg-type]
                    project=key, domains=[d.strip() for d in (domains or []) if d and d.strip()])
        with self.store.transaction():
            self.store.put("lesson", le)
            for ev in (evidence or []):
                self._kglink(actor, le.id, ev, LinkKind.learned_from)
        self._index("lesson", le.id, "\n".join([le.text, le.topic, le.domain, *le.domains]))
        return le

    def scope_lesson(self, actor: Participant, *, lesson_id: str, scope_kind: str, project: str = "") -> Lesson:
        """Re-file a live lesson under another scope (the backfill and the owner's correction)."""
        if actor.role not in (Role.architect, Role.owner, Role.doctor) and actor.id != "board":
            raise BoardError("scope", f"{actor.role} may not re-scope a lesson", "the architect or the owner does")
        le = self.store.get("lesson", lesson_id)
        if le is None:
            raise BoardError("not_found", f"lesson {lesson_id!r} does not exist", "pass the id of an existing lesson")
        key = lesson_scope.project_key(project)
        if scope_kind == LessonScope.project.value and not key:
            raise BoardError("invalid", "a project lesson needs a project key", "pass project=<key>")
        if scope_kind not in (LessonScope.framework.value, LessonScope.project.value):
            raise BoardError("invalid", f"scope_kind must be framework or project, not {scope_kind!r}", "")
        le.scope_kind = LessonScope(scope_kind)  # type: ignore[attr-defined]
        le.project = key if scope_kind == LessonScope.project.value else ""  # type: ignore[attr-defined]
        with self.store.transaction():
            self.store.put("lesson", le)
        return le

    def retire_lesson(self, actor: Participant, *, lesson_id: str, reason: str = "") -> Lesson:
        """Retire a lesson without a successor (status `retired`): the row and its links stay, lookup and
        recall never return it again and the search index drops it. Idempotent. Architect, owner or doctor."""
        if actor.role not in (Role.architect, Role.owner, Role.doctor) and actor.id != "board":
            raise BoardError("scope", f"{actor.role} may not retire a lesson",
                             "ask the architect or the owner to retire it")
        le = self.store.get("lesson", lesson_id)
        if le is None:
            raise BoardError("not_found", f"lesson {lesson_id!r} does not exist", "pass the id of an existing lesson")
        le.status = LessonStatus.retired  # type: ignore[attr-defined]
        le.retired_reason = f"{(reason or '').strip()} [by {actor.id}]"[:240]  # type: ignore[attr-defined]
        with self.store.transaction():
            self.store.put("lesson", le)
        self._index("lesson", le.id, "")  # overwrite the semantic vector so search drops it too
        return le

    def backfill_lesson_scopes(self, actor: Participant, *, dry_run: bool = False) -> dict[str, Any]:
        """Classify every live lesson (scope) and retire the ones that cite a retired tool. Idempotent."""
        if actor.role not in (Role.architect, Role.owner, Role.doctor) and actor.id != "board":
            raise BoardError("scope", f"{actor.role} may not run the lesson backfill", "")
        return lesson_scope.backfill(self, actor, dry_run=dry_run)

    def withdraw_decision(self, actor: Participant, *, decision_id: str, reason: str) -> Decision:
        """Retract a decision without a successor (design §3 status `withdrawn`): the row and its
        links are kept, but lookup never returns it and the search index drops it. Idempotent —
        re-withdrawing only refreshes the reason. Gives the owner a real way to retract a mistaken
        decision (ruling m-7baa527b65)."""
        d = self.store.get("decision", decision_id)
        if d is None:
            raise BoardError("not_found", f"decision {decision_id!r} does not exist",
                             "pass the id of an existing decision")
        d.status = DecisionStatus.withdrawn  # type: ignore[attr-defined]
        d.withdrawn_reason = (reason or "").strip()[:240]  # type: ignore[attr-defined]
        with self.store.transaction():
            self.store.put("decision", d)  # _fts_text returns "" for withdrawn → drops it from FTS
        self._index("decision", d.id, "")  # overwrite the semantic vector so search drops it too
        return d

    def withdraw_claim(self, actor: Participant, *, claim_id: str, reason: str) -> Claim:
        """Retire a claim without a successor (status `withdrawn`): the row and its links are kept,
        but lookup never returns it and the search index drops it. Idempotent. Gives re-curation a
        way to retire round-1 claims that round 2 superseded (steer m-70df16487c), the claim analogue
        of withdraw_decision."""
        c = self.store.get("claim", claim_id)
        if c is None:
            raise BoardError("not_found", f"claim {claim_id!r} does not exist",
                             "pass the id of an existing claim")
        c.status = ClaimStatus.withdrawn  # type: ignore[attr-defined]
        c.withdrawn_reason = (reason or "").strip()[:240]  # type: ignore[attr-defined]
        with self.store.transaction():
            self.store.put("claim", c)  # _fts_text returns "" for withdrawn → drops it from FTS
        self._index("claim", c.id, "")  # overwrite the semantic vector so search drops it too
        return c

    def set_binding(self, actor: Participant, *, decision_id: str, binding: bool, reason: str) -> Decision:
        """Promote or demote a LIVE decision's binding flag (D5 re-judge, steer m-70df16487c line).
        Architect or owner only; the id and every kglink stay, and a `binding_changed` audit event
        records who, when and why. Binding is neither embedded nor in the FTS text, so no re-index."""
        if actor.role not in (Role.architect, Role.owner):
            raise BoardError("scope", f"{actor.role} may not change a decision's binding flag",
                             "only the architect or the owner set binding")
        with self.store.transaction(immediate=True):  # F3: read + write under the write lock
            d = self.store.get("decision", decision_id)
            if d is None:
                raise BoardError("not_found", f"decision {decision_id!r} does not exist",
                                 "pass the id of an existing decision")
            if d.status != DecisionStatus.live:
                raise BoardError("state", f"decision {decision_id!r} is {d.status}, not live",
                                 "binding only means something for a live decision")
            was = bool(d.binding)
            d.binding = bool(binding)  # type: ignore[attr-defined]
            self.store.put("decision", d)
            self._emit(d.id, EventKind.binding_changed,
                       {"decision": d.id, "from": was, "to": d.binding,
                        "reason": (reason or "").strip()[:240], "by": actor.id})
        return d

    def epic_participant(self, p: Participant, epic: Ticket) -> bool:
        """Is p one of this epic's participants (C17: who may read its decision list)? An owner, unless the
        epic has another human owner (None = an agent-created epic, which every owner may read); a seat
        named for, assigned to, or the creator of a ticket of the epic."""
        if p.role == Role.owner:
            oid = self.epic_owner(epic.id)
            return oid is None or oid == p.id
        tickets = [epic, *self._descendants(epic.id)]
        named = p.id.split(".", 1)[1] if "." in p.id else None
        return any(t.id == named or t.assignee == p.id or t.created_by == p.id for t in tickets)

    def scope_decisions(self, actor: Participant, scope: str) -> dict[str, Any]:
        """The decision list of one scope (C17, design-10b21760d9 §14.2): the live and withdrawn decisions
        recorded on the ticket or any ticket under it (an epic: its stories and their tasks). Replaced ones
        are history, reached through a successor's `replaces`. Live binding decisions first, then newest.
        Readable by the epic's participants only."""
        t = self.ticket(scope)  # 404 on an unknown ticket
        epic = self.epic_of(t)
        if not self.epic_participant(actor, epic):
            raise BoardError("forbidden", f"{actor.id} is not a participant of {epic.id}",
                             "only the epic's owner, architect and seats read its decisions")
        ids = {t.id, *(x.id for x in self._descendants(t.id))}
        rows = self.store.query("decision", {"scope": sorted(ids),
                                             "status": [DecisionStatus.live.value, DecisionStatus.withdrawn.value]},
                                limit=100000)

        def when(d: Decision) -> datetime:
            at = d.decided_at or d.created_at  # a legacy naive stamp is UTC; mixing both must not 500 the list
            return at if at.tzinfo else at.replace(tzinfo=timezone.utc)

        rows.sort(key=lambda d: when(d), reverse=True)  # newest first, then binding live ones lifted (stable)
        rows.sort(key=lambda d: not (d.binding and d.status == DecisionStatus.live))

        def row(d: Decision) -> dict[str, Any]:
            src = d.source or None
            kind, src_ticket = None, None
            if src:
                m = self.store.get("message", src)
                if m is not None:
                    kind, src_ticket = "message", m.ticket_id  # type: ignore[union-attr]
                elif self.store.get("doc", src) is not None:
                    kind = "doc"
                else:
                    kind = "other"
            return {"id": d.id, "scope": d.scope, "text": d.text, "detail": d.detail, "source": src,
                    "source_kind": kind, "source_ticket": src_ticket, "decided_by": d.decided_by,
                    "decided_at": when(d).isoformat(), "created_at": d.created_at.isoformat(),
                    "binding": bool(d.binding), "status": d.status.value if hasattr(d.status, "value") else str(d.status),
                    "replaces": list(d.replaces), "withdrawn_reason": d.withdrawn_reason}

        out = [row(d) for d in rows]  # type: ignore[arg-type]
        live = sum(1 for r in out if r["status"] == "live")
        return {"scope": t.id, "epic": epic.id, "tickets": sorted(ids), "decisions": out,
                "counts": {"live": live, "withdrawn": len(out) - live},
                "can_manage": actor.role in (Role.architect, Role.owner)}

    def dense_diagnostic(self, actor: Participant, *, scope: str, question: str,
                         k: int = 10) -> dict[str, Any]:
        """Read-only D4/D5 diagnostic: the dense-only cosine top-k over the records in this epic's
        scope (no BM25 leg, no graph, no cap). Lets a checker see exactly what the dense seed leg
        votes for, which the fused lookup otherwise hides. Scope-limited to the epic's live records."""
        if self.index is None:
            return {"scope": scope, "question": question, "embedder": "none", "hits": []}
        epic = knowledge._epic_id_of(self.store, scope)
        allow = {r.id for rtype in knowledge.RECORD_TYPES
                 for r in self.store.query(rtype, limit=100000)
                 if getattr(r, "status", "live") not in ("replaced", "withdrawn", "refuted", "retired")
                 and (epic is None
                      or knowledge._epic_id_of(self.store, getattr(r, "scope", "") or "") == epic)}
        hits = self.index.dense_search(question, k=k, types=set(knowledge.RECORD_TYPES), allow_ids=allow)
        return {"scope": scope, "epic": epic, "question": question,
                "embedder": self.index.status(), "candidates": len(allow), "hits": hits}

    def reembed(self) -> dict[str, Any]:
        """R2 item-3: trigger the in-board bounded re-embed pass for any unit missing a vector (no
        restart). The board is the only process that holds the model (hard rule 4)."""
        if self.index is None:
            return {"embedder": "none", "reason": "no semantic index installed"}
        return self.index.reembed()

    def binding_audit(self) -> dict[str, Any]:
        """Replaced/withdrawn binding decisions with no live binding successor (m-0cccdead3e)."""
        orphans = knowledge.binding_orphans(self.store)
        return {"orphans": orphans, "count": len(orphans)}

    def embed_counts(self, scope: str) -> dict[str, Any]:
        """R2 item-3: embedded vs unembedded live records for an epic, so the backfill receipt can
        show whether the RAM guard left anything unembedded. Epic-scoped like lookup."""
        epic = knowledge._epic_id_of(self.store, scope)
        out: dict[str, Any] = {"scope": scope, "epic": epic,
                               "embeddings": self.index.status() if self.index is not None else None}
        emb_dec = self.index.embedded_ids("decision") if self.index is not None else set()
        emb_clm = self.index.embedded_ids("claim") if self.index is not None else set()
        for rtype, embedded in (("decision", emb_dec), ("claim", emb_clm)):
            live = [r for r in self.store.query(rtype, limit=100000)
                    if getattr(r, "status", "live") not in ("replaced", "withdrawn", "refuted", "retired")
                    and (epic is not None and knowledge._epic_id_of(self.store, getattr(r, "scope", "") or "") == epic)]
            ids = {r.id for r in live}
            e = len(ids & embedded)
            out[rtype] = {"live": len(ids), "embedded": e, "unembedded": len(ids) - e}
        return out

    def lookup(self, actor: Participant, *, scope: str, question: str | None = None,
               id: str | None = None, path: str | None = None,
               ref_now: datetime | None = None) -> dict[str, Any]:
        """Deterministic, capped, epic-isolated retrieval over the records (design §4.2).
        Reuses the board's semantic Index when installed; FTS otherwise. `ref_now` is the request
        clock: the freshness `now` is read ONCE per lookup (O2), so calls sharing a clock score alike."""
        ref_now = ref_now or now()
        # S18: the index wiring lives in knowledge.wired_lookup so the RSI tripwire replays this exact call
        return knowledge.wired_lookup(self.store, self.index, scope, question=question, id=id, path=path,
                                      ref_now=ref_now)

    def last_status(self, p: Participant) -> dict[str, Any] | None:
        """The most recent status_recorded event data by this participant on its tickets."""
        seen: list[Event] = []
        tickets = self.my_tickets(p)
        st = self.seat_ticket(p)
        if st is not None and all(x.id != st.id for x in tickets):
            tickets.append(st)
        for t in tickets:
            for ev in self.store.query("event", {"subject_id": t.id, "kind": EventKind.status_recorded}):
                if ev.data.get("participant") == p.id:  # type: ignore[union-attr]
                    seen.append(ev)  # type: ignore[arg-type]
        if not seen:
            return None
        last = max(seen, key=lambda e: e.created_at)
        return {**last.data, "at": last.created_at.isoformat()}

    def close_check(self, p: Participant) -> dict[str, Any]:
        """Everything close_self needs to decide, in one read: the open inbox and the last
        recorded status. The pool release itself happens client-side."""
        out: dict[str, Any] = {"inbox": self.inbox(p), "status": self.last_status(p)}
        topic = self.topic_of_seat(p)
        if topic is not None and topic.status not in _TERMINAL:  # S-SME-SURFACE: resident until the owner closes
            out["resident"] = f"{topic.id} is open: its sme stays until the owner closes the topic"
        return out

    def topic_of_seat(self, p: Participant) -> Ticket | None:
        """The Library topic this participant is the resident sme seat of (sme.<topic-id>, or the topic's
        assignee), else None (S-SME-SURFACE)."""
        if p.role not in (Role.sme, Role.doctor):
            return None
        t = self.store.get("ticket", p.id.split(".", 1)[1]) if "." in p.id else None
        if is_topic(t) and topic_seat_role(t) == p.role.value:  # type: ignore[arg-type]
            return t  # type: ignore[return-value]
        hits = [x for x in self.store.query("ticket", {"assignee": p.id, "kind": TicketKind.topic.value}, limit=5)]
        return hits[0] if hits else None  # type: ignore[return-value]

    def board(self, epic_id: str) -> dict[str, Any]:
        epic = self.ticket(epic_id)
        if epic.kind != TicketKind.epic:
            epic = self.epic_of(epic)

        def node(t: Ticket) -> dict[str, Any]:
            crits = self.criteria(t.id)
            return {"id": t.id, "kind": t.kind, "work_type": t.work_type, "title": t.title[:120],
                    "status": t.status, "assignee": t.assignee,
                    "criteria": f"{sum(c.verdict == Verdict.passed for c in crits)}/{len(crits)}",
                    "gates": [e.data.get("gate") for e in self.open_gates(t.id)],
                    "blocked_by": [b.id for b in self.blockers(t.id) if b.status != TicketStatus.done],
                    "children": [node(k) for k in self.children(t.id)]}

        tree = node(epic)
        flat: list[Ticket] = [epic, *self._descendants(epic.id)]
        counts: dict[str, int] = {}
        for t in flat:
            counts[t.status.value] = counts.get(t.status.value, 0) + 1
        ready = [t.id for t in flat if t.status == TicketStatus.ready and t.kind != TicketKind.epic]
        in_review = [t.id for t in flat if t.status == TicketStatus.in_review]
        gates = [(t.id, e.data.get("gate")) for t in flat for e in self.open_gates(t.id)]
        return {"epic": tree, "counts": counts, "ready": ready, "in_review": in_review,
                "open_gates": gates, "words": epic.words or epic.title,
                "words_header": self._epic_phase_header(epic),
                # the resident architect and its seat state, for spawn/close and the epic page (t-cf353a4051)
                "architect": {"id": (arch := self.resident_architect(epic)), "state": self.seat_state(arch)}}

    def _descendants(self, ticket_id: str) -> list[Ticket]:
        out: list[Ticket] = []
        for k in self.children(ticket_id):
            out.append(k)
            out.extend(self._descendants(k.id))
        return out

    # feed -------------------------------------------------------------
    def _owner_scope(self, p: Participant, subject_id: str) -> bool:
        """Does this owner own the epic this event belongs to? Cross-functional teams:
        each owner-human sees their own epics; an epic without a human owner pages no owner."""
        tk = self.store.get("ticket", subject_id)
        if tk is None:
            return True
        return self.epic_owner(tk.id) == p.id  # no fallback: an epic without a human owner pages no owner

    # delivery — who is woken and why (design §16.2). The single decider is _reason_for
    # (this participant, this event); relevant/why/delivery.delivery_plan all read it, so the
    # wake preview can never drift from delivery. Recovery (rule 3) is the one plan-level
    # rule (it needs to know the plan is otherwise empty) and lives in delivery.delivery_plan.
    _WHY_CLAUSE = {
        Reason.addressed: "addressed to you",
        Reason.mention: "@mention",
        Reason.architect_listener: "architect listener",
        Reason.owner_listener: "owner listener",
        Reason.gate_party: "on your ticket",
        Reason.on_ticket: "on your ticket",
        Reason.ancestor_seat: "on your ticket",
        Reason.recovery: "owner listener",
    }
    _WHY_PRIORITY = (Reason.addressed, Reason.mention, Reason.architect_listener,
                     Reason.owner_listener, Reason.gate_party, Reason.on_ticket,
                     Reason.ancestor_seat, Reason.recovery)

    def relevant(self, ev: Event, p: Participant) -> bool:
        if self._reason_for(ev, p):
            return True
        return self._is_recovery_recipient(ev, p)

    def why(self, ev: Event, p: Participant) -> str | None:
        """The one clause a subscriber sees on an event: why it was woken, or None if it
        would not be (a courtesy replay-by-seq can still carry an event a seat filters)."""
        reasons = self._reason_for(ev, p)
        if not reasons and self._is_recovery_recipient(ev, p):
            reasons = [Reason.recovery]
        if not reasons:
            return None
        return self._WHY_CLAUSE[self._primary(reasons)]

    def _primary(self, reasons: list[Reason]) -> Reason:
        return next(r for r in self._WHY_PRIORITY if r in reasons)

    def listening(self, role: str) -> dict[str, Any]:
        """The contract a seat sees before its first event (design §16.2 rule 4): what it is
        woken for, how to get what it is NOT woken for, and how any seat reaches the architect.
        Worded per role; the same block subscribe() returns and feed_driver prints as line 1."""
        _GET = "address it `to=` you (by id, or by your role on your epic), or @mention you in the text"
        consult = ("to reach the architect from any seat: message_send(kind='question', to='architect') — "
                   "the architect is woken for every question, deviation, finding and steer on its epic, "
                   "whatever the addressee")
        if role == Role.architect.value:
            receives = ("as the epic's architect you are woken for every question, deviation, finding and "
                        "steer anywhere in your epic whatever the `to`; every board hint (epic moved to "
                        "in_review so qa is available; a message waiting for a closed seat); every recorded status of "
                        "blocked/failed/deferred; every ticket moving to blocked/partial/dropped; gates "
                        "opened and answered; shells that die or stall; any criterion that fails; plus "
                        "anything addressed to you or @mentioning you")
            not_received = ("plain notes and answers between two other seats (they are on the thread for you "
                            f"to read, not a page) — to be paged on one, {_GET}")
        elif role == Role.owner.value:
            receives = ("you are woken, on epics you own, for: gates; anything addressed to you or the owner "
                        "role; shells that die or stall; tickets reaching ready/in_review/done/blocked/"
                        "partial/dropped; recorded statuses of failed/blocked whatever the addressee; and "
                        "criterion checks by others; plus @mentions")
            not_received = ("ticket_created and design-time status noise (drafted→designed→signed_off): a "
                            "story reaching `ready` is the page, not its birth. A question with no `to` is "
                            f"the architect's page, not yours — to be paged on one, {_GET}")
        else:
            receives = ("you are woken for anything addressed to you (by id, or by your role on your epic), "
                        "thread notes on your ticket and its ancestors, that ticket's status changes and "
                        "criterion checks, gates on it, and @mentions")
            not_received = ("events on sibling stories or other epics, and messages addressed to another "
                            f"seat — to be paged on one, {_GET}")
        return {"receives": receives, "not_received": not_received, "consult": consult}

    def _is_recovery_recipient(self, ev: Event, p: Participant) -> bool:
        """rule 3: a question/deviation whose plan is otherwise empty falls back to the epic's
        human owner. Cheap check for the feed path — only the epic owner can qualify."""
        d = ev.data
        if ev.kind != EventKind.message_sent or d.get("kind") not in (MessageKind.question, MessageKind.deviation):
            return False
        if self.epic_owner(ev.subject_id) != p.id:
            return False
        from . import delivery
        return not any(rs for pid, rs in delivery.delivery_plan(self, ev) if pid != p.id)

    def _reason_for(self, ev: Event, p: Participant) -> list[Reason]:
        """Every reason this event wakes this participant (never parses text; the message
        `status` field rides the event data). Empty == not woken (before recovery)."""
        d = ev.data
        reasons: list[Reason] = []
        if p.id in (d.get("mentions") or []):  # an @mention reaches its person, any role
            reasons.append(Reason.mention)
        if p.role == Role.owner:
            reasons += self._owner_reasons(ev, p)
            return _dedup(reasons)
        if p.role == Role.architect:  # rule 1, additive listener for the epic's architect seat
            reasons += self._architect_listener_reasons(ev, p)
            gen = self._general_reasons(ev, p)
            if self._architect_courtesy_copy(ev):
                # v21 (design §16.2 rule 1): the epic seat pays no ANCESTOR courtesy copy — a clean
                # death, a routine status note, a plain note between other seats, a passing check.
                # It keeps every rule-1 kind (question/deviation/finding/steer, blocked/failed status,
                # unclean death, gate, fail verdict, ready/in_review/done transitions) and any event
                # on the epic ticket it works DIRECTLY (on_ticket, never dropped).
                gen = [r for r in gen if r != Reason.ancestor_seat]
            reasons += gen
            return _dedup(reasons)
        reasons += self._general_reasons(ev, p)
        return _dedup(reasons)

    def _architect_courtesy_copy(self, ev: Event) -> bool:
        """A subtree event the epic's architect can READ but is NOT paged for by ANCESTOR delivery
        (design §16.2 rule 1, v21/v23 — rule 1 is EXHAUSTIVE, an allowlist not a blacklist, owner
        ruling 2026-09-08 §24.1(c)). It stays delivered (returns False) ONLY for a rule-1 crucial
        kind: an unclean death, a FAIL criterion verdict, a question/deviation/finding/steer or a
        blocked/failed/deferred status note, and a status_changed INTO a phase boundary
        (ready/in_review/blocked/done/partial/dropped). EVERYTHING else is a courtesy copy the
        architect can read but is not woken for — clean deaths, passing/pending checks, plain
        note/answer and routine status notes, ticket_created, assigned, doc_updated, and the
        design-time transitions drafted/designed/signed_off/in_progress. (Gates and stalls still
        reach the architect through _architect_listener_reasons, so dropping their ancestor copy
        here loses no page.)"""
        d = ev.data
        k = ev.kind
        if k == EventKind.shell_dead:
            return bool(d.get("clean"))
        if k == EventKind.criterion_checked:
            return d.get("verdict") != Verdict.failed
        if k == EventKind.message_sent:
            mk = d.get("kind")
            if mk in (MessageKind.note, MessageKind.answer):
                return True
            if mk == MessageKind.status:
                return d.get("status") not in (StatusValue.blocked, StatusValue.failed, StatusValue.deferred)
            return False  # question / deviation / finding / steer are crucial
        if k == EventKind.status_changed:
            # phase boundaries stay delivered; the design-time transitions are courtesy
            return d.get("to") not in ("ready", "in_review", "blocked", "done", "partial", "dropped")
        # ticket_created, assigned, doc_updated, gates, stalls, anything else: courtesy for ANCESTOR
        # delivery (rule 1 is the whole list). A crucial kind not named above must be added HERE.
        return True

    def _general_reasons(self, ev: Event, p: Participant) -> list[Reason]:
        """Delivery every seat has always had: addressed, its ticket/ancestors, gates it can
        answer or worked, its own status changes. Ported 1:1 from the pre-§16 relevant()."""
        d = ev.data
        out: list[Reason] = []
        if ev.kind in _LEDGER_EVENTS:  # retired ask rows and requirements wake nobody here; the architect hears marks below
            return out
        if ev.kind == EventKind.message_sent:
            to = d.get("to")
            if d.get("from") == p.id:
                return out
            topic = self.store.get("ticket", ev.subject_id)
            if is_topic(topic) and self._works(p, topic):  # type: ignore[arg-type]
                # S-SME-SURFACE: the topic's resident seat hears EVERY message on its thread, whoever it
                # is addressed to — an expert talking to the owner is still something the sme learns from
                return [Reason.addressed if to == p.id else Reason.on_ticket]
            if to == p.id:
                out.append(Reason.addressed)
            elif to == p.role.value:  # unresolved role note: my epic only, never fleet-wide
                if self._epic_id_of(ev.subject_id) in self.my_epics(p):
                    out.append(Reason.addressed)
            elif to is None:  # a thread note reaches the seats working that ticket and its ancestors
                r = self._on_ticket_reason(p, ev.subject_id, parents=True)
                if r:
                    out.append(r)
            return out
        if ev.kind == EventKind.gate_opened:
            if str(p.role) in self.workflow_of(ev.subject_id).gate_answerers or self._in_subtree(p, ev.subject_id):
                out.append(Reason.gate_party)
            return out
        if ev.kind == EventKind.gate_answered:
            opened_by_me = any(e.data.get("gate") == d.get("gate") and e.data.get("by") == p.id
                               for e in self.store.query("event", {"subject_id": ev.subject_id,
                                                                    "kind": EventKind.gate_opened}))
            if d.get("by") == p.id or opened_by_me or self._in_subtree(p, ev.subject_id):
                out.append(Reason.gate_party)
            return out
        if ev.kind in (EventKind.shell_dead, EventKind.shell_stalled):
            r = self._on_ticket_reason(p, ev.subject_id, parents=True)
            if r:
                out.append(r)
            return out
        if ev.kind in (EventKind.status_changed, EventKind.ticket_created, EventKind.assigned,
                       EventKind.criterion_checked):
            if d.get("assignee") == p.id:
                out.append(Reason.on_ticket)
            else:
                r = self._on_ticket_reason(p, ev.subject_id, parents=True)
                if r:
                    out.append(r)
            return out
        if ev.kind == EventKind.doc_updated and self.store.get("ticket", ev.subject_id):
            r = self._on_ticket_reason(p, ev.subject_id, parents=True)
            if r:
                out.append(r)
        return out

    def _owner_reasons(self, ev: Event, p: Participant) -> list[Reason]:
        """What a human owner is paged for on ITS epics (design §16.2 rule 2): gates,
        addressed messages, dying shells, phase boundaries incl. dropped, record_status of
        failed/blocked whatever the addressee, and others' criterion checks. Not ticket_created,
        not design-time noise."""
        d = ev.data
        out: list[Reason] = []
        if ev.kind in (EventKind.gate_opened, EventKind.gate_answered):
            if self._owner_scope(p, ev.subject_id):
                out.append(Reason.gate_party)
            return out
        if ev.kind == EventKind.message_sent and d.get("from") != p.id:
            to = d.get("to")
            scoped = self._owner_scope(p, ev.subject_id)
            if to == p.id:
                out.append(Reason.addressed)
            elif to == p.role.value and scoped:
                out.append(Reason.owner_listener)
            elif to is None and d.get("kind") in (MessageKind.status, MessageKind.finding,
                                                   MessageKind.deviation) and scoped:
                out.append(Reason.owner_listener)
            # rule 2: a recorded status of failed/blocked pages the owner however it is addressed
            if d.get("kind") == MessageKind.status and d.get("status") in (StatusValue.failed, StatusValue.blocked) \
                    and scoped and Reason.owner_listener not in out:
                out.append(Reason.owner_listener)
            return out
        if ev.kind == EventKind.board_hint:  # a quick task has no architect to hint: its owner hears the board
            tk = self.store.get("ticket", ev.subject_id)
            if (tk is not None and is_quick(self.epic_of(tk)) and d.get("from") != p.id  # type: ignore[arg-type]
                    and self._owner_scope(p, ev.subject_id)):
                out.append(Reason.owner_listener)
            return out
        if ev.kind in (EventKind.shell_stalled, EventKind.shell_dead):
            # design-63db8a7d42 F: every pool event goes to the epic's architect, who heals it. The owner is not paged by
            # the event: when no live architect can heal it (a quick task; Q1: a dead or stalled architect) the board
            # writes the owner a plain chat message instead (`_page_owner_unhealed`).
            return out
        if ev.kind == EventKind.status_changed:
            if d.get("to") in ("ready", "in_review", "done", "blocked", "partial", "dropped") \
                    and self._owner_scope(p, ev.subject_id):
                out.append(Reason.owner_listener)
            return out
        if ev.kind == EventKind.criterion_checked:
            # v21 / §24 finding 9 (tightened per second-opinion 2026-09-08): the owner is paged for
            # EVERY criterion check EXCEPT the one case rule 2 names — an AGENT qa PASSING a
            # command/path check. Keying suppression on the acting role (by_role), not just by_type +
            # checked_by, closes the branch where an agent seat with Role.owner verdicts a qa
            # criterion and was wrongly suppressed. A human's pass, any fail, a `look` check, and an
            # owner-checked criterion all still page.
            if d.get("by") != p.id and self._owner_scope(p, ev.subject_id):
                agent_qa_pass = (
                    d.get("by_type") == "agent"
                    and d.get("by_role") == Role.qa.value
                    and d.get("verdict") == Verdict.passed
                    and d.get("check") in (Check.command, Check.path)
                    and d.get("checked_by") != CheckedBy.owner.value)
                if not agent_qa_pass:
                    out.append(Reason.owner_listener)
        return out

    def _architect_listener_reasons(self, ev: Event, p: Participant) -> list[Reason]:
        """rule 1: the epic's architect seat hears every crucial event in its subtree whatever
        the addressee — the fix for a low-tier seat addressing its problem to the wrong seat.
        Additive: the addressee still gets its own copy via _general_reasons."""
        d = ev.data
        if d.get("from") == p.id:  # never page the architect for its own action
            return []
        if p.role != Role.architect:
            return []
        if ev.kind == EventKind.requirement_marked:  # s-aa76c83998: once per new requirement, the epic's architect
            ep = self.store.get("ticket", d.get("epic") or "")
            return [Reason.architect_listener] if ep is not None and p.id == self.resident_architect(ep) else []  # type: ignore[arg-type]
        epic = self._epic_ticket(ev.subject_id)
        if epic is None or p.id != self.resident_architect(epic):
            return []
        k = ev.kind
        if k == EventKind.message_sent:
            mk = d.get("kind")
            if mk in (MessageKind.question, MessageKind.deviation, MessageKind.finding, MessageKind.steer):
                return [Reason.architect_listener]
            if mk == MessageKind.status and d.get("status") in (StatusValue.blocked, StatusValue.failed,
                                                                StatusValue.deferred):
                return [Reason.architect_listener]
            return []
        if k == EventKind.status_changed and d.get("to") in ("blocked", "partial", "dropped"):
            return [Reason.architect_listener]
        if k in (EventKind.gate_opened, EventKind.gate_answered, EventKind.board_hint):
            return [Reason.architect_listener]
        if k == EventKind.shell_stalled:  # a stall is always crucial
            return [Reason.architect_listener]
        if k == EventKind.shell_dead:  # F: crash, close and self-close alike; the architect decides if it needs healing
            return [Reason.architect_listener]
        if k == EventKind.criterion_checked and d.get("verdict") == Verdict.failed:
            return [Reason.architect_listener]
        return []

    def _epic_ticket(self, subject_id: str) -> Ticket | None:
        t = self.store.get("ticket", subject_id)
        return self.epic_of(t) if t is not None else None  # type: ignore[arg-type]

    def _in_subtree(self, p: Participant, ticket_id: str) -> bool:
        """Involved anywhere in this ticket's epic tree: assignee or creator of the ticket, any
        ancestor, or any ticket in the same epic's subtree. Gate/thread events reach everyone
        who worked the epic — a gate answer must wake the seat that opened the gate."""
        t = self.store.get("ticket", ticket_id)
        if t is None:
            return False
        epic = self.epic_of(t)  # type: ignore[arg-type]
        for x in (epic, *self._descendants(epic.id)):
            if self._works(p, x):
                return True
        return False

    def _works(self, p: Participant, t: Ticket) -> bool:
        """p works ticket t: assigned to it, or the seat named for it. Creating a ticket does
        NOT subscribe you to it for life (2026-09-05 pain: created_by widened every feed)."""
        return t.assignee == p.id or p.id == f"{p.role.value}.{t.id}"

    def _on_ticket(self, p: Participant, ticket_id: str, parents: bool = False) -> bool:
        return self._on_ticket_reason(p, ticket_id, parents=parents) is not None

    def _on_ticket_reason(self, p: Participant, ticket_id: str, parents: bool = False) -> Reason | None:
        """on_ticket when p works the subject ticket itself, ancestor_seat when it works only an
        ancestor of it (design §16.2 reason vocabulary); None when it works neither."""
        t = self.store.get("ticket", ticket_id)
        first = True
        while t is not None:
            if self._works(p, t):
                return Reason.on_ticket if first else Reason.ancestor_seat
            if not parents or not t.parent_id:
                return None
            t = self.store.get("ticket", t.parent_id)
            first = False
        return None

    def subscribe(self, participant_id: str, watch: bool = False) -> asyncio.Queue:
        """A wake subscription (default: only events that page this participant) or, with
        `watch`, a view subscription that receives every event (S19: a page renders the whole
        thread, not just the viewer's pages)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=FEED_QUEUE_MAX)
        q.resync = False  # type: ignore[attr-defined]  # set when _offer dropped an event
        # e0cec S5: a guest's queue (wake or watch) carries its StreamScope; _fanout offers it only the events
        # inside the guest's member epics, so every stream caller inherits the filter (S1 report §5)
        p = self.store.get("participant", participant_id)
        q.scope = guest_scope.stream_scope(self, p) if p is not None else None  # type: ignore[attr-defined]
        with self._lock:
            (self._watch if watch else self._subs).setdefault(participant_id, []).append(q)
        return q

    def unsubscribe(self, participant_id: str, q: asyncio.Queue) -> None:
        with self._lock:
            for subs in (self._subs, self._watch):
                lst = subs.get(participant_id, [])
                if q in lst:
                    lst.remove(q)

    @staticmethod
    def _offer(q: asyncio.Queue, ev: Event) -> bool:
        """put_nowait under the bounded-queue drop policy (FEED_QUEUE_MAX): a full queue drops its
        oldest event and is marked for resync. Returns False when something was dropped."""
        try:
            q.put_nowait(ev)
            return True
        except asyncio.QueueFull:
            pass
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        q.resync = True  # type: ignore[attr-defined]
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            pass  # a racing producer refilled it: the resync replay covers this event too
        return False

    def _fanout(self, ev: Event) -> None:
        with self._lock:
            targets = list(self._subs.items())
            watchers = [q for queues in self._watch.values() for q in queues]
        for q in watchers:
            if not self._in_scope(q, ev):
                continue
            try:
                if not self._offer(q, ev):
                    _log.warning("view feed queue full: dropped the oldest event, stream will resync")
            except Exception as e:  # a closed view queue: the page replays by seq on reconnect
                _log.warning("view feed queue dropped %s: %s", ev.id, e)
        for pid, queues in targets:
            p = self.store.get("participant", pid)
            if p is None or not self.relevant(ev, p):  # type: ignore[arg-type]
                continue
            for q in queues:
                if not self._in_scope(q, ev):
                    continue
                try:
                    if not self._offer(q, ev):
                        _log.warning("feed queue for %s full: dropped the oldest event, stream will resync", pid)
                except Exception as e:  # a closed feed queue: the subscriber will replay by seq
                    _log.warning("feed queue for %s dropped %s: %s", pid, ev.id, e)

    @staticmethod
    def _in_scope(q: asyncio.Queue, ev: Event) -> bool:
        """A guest queue takes only its scope's events; on a revoked membership it gets one resync mark."""
        sc = getattr(q, "scope", None)
        if sc is None:
            return True
        if sc.keep(ev):
            return True
        if sc.revoked:  # the guest lost a member epic: wake the stream so it ends with a resync
            q.resync = True  # type: ignore[attr-defined]  # (the stream returns before yielding this event)
            return True
        return False

    def iter_replay(self, p: Participant, since_seq: int, watch: bool = False,
                    limit: int | None = None, keep: Any = None) -> Iterator[tuple[int, Event]]:
        """Relevant events after since_seq (every event with `watch`), streamed one store page at a
        time and stopped at `limit` (S22 c-0615088222: /v1/events used to materialise the whole
        history, then slice). A monitor far behind still gets the whole gap — lazily."""
        cur, n = since_seq, 0
        if limit is not None and limit <= 0:
            return
        if keep is None:  # e0cec S5: a guest's replay (watch=true included) never leaves its member epics
            keep = guest_scope.keep_event(self, p)
        while True:
            batch = self.store.events_since(cur, limit=500)
            if not batch:
                return
            for s, e in batch:
                cur = s
                if keep is not None and not keep(e):  # the guest scope (edp8.guest_scope)
                    continue
                if watch or self.relevant(e, p):
                    yield s, e
                    n += 1
                    if limit is not None and n >= limit:
                        return

    def replay(self, p: Participant, since_seq: int, watch: bool = False) -> list[tuple[int, Event]]:
        """All relevant events after since_seq, as a list (small histories and tests; the feed and
        /v1/events stream iter_replay)."""
        return list(self.iter_replay(p, since_seq, watch=watch))

    def replay_tail(self, p: Participant, n: int, watch: bool = False) -> list[tuple[int, Event]]:
        """The last `n` relevant events, oldest first — read backwards a page at a time, so an
        activity view never loads the whole history to keep its tail."""
        out: list[tuple[int, Event]] = []
        cur: int | None = None
        while len(out) < n:
            batch = self.store.events_before(cur, limit=500)
            if not batch:
                break
            for s, e in batch:
                cur = s
                if watch or self.relevant(e, p):
                    out.append((s, e))
                    if len(out) >= n:
                        break
        out.reverse()
        return out

    def find(self, query: str, *, k: int = 10, types: Iterable[str] | None = None,
             epic_id: str | None = None, keep: Any = None, scope: Any = None) -> list[dict[str, Any]]:
        """Exact words (FTS5) ∪ semantic (BM25 + vectors), fused by reciprocal rank; every hit
        names its ticket and epic so the reader rarely needs a second call. `scope` (a guest's
        guest_scope.EpicScope) restricts retrieval itself, and `keep` re-checks each located hit."""
        tset = set(types) if types else None
        fused: dict[str, dict[str, Any]] = {}
        rrf_k = 60

        def add(hits: list[dict[str, Any]]) -> None:
            for rank, h in enumerate(hits, start=1):
                key = f"{h['type']}:{h['id']}"
                cur = fused.setdefault(key, {"type": h["type"], "id": h["id"], "score": 0.0,
                                             "snippet": h.get("snippet", "")})
                if h["type"] == "doc" and "section" not in cur:  # S17: the section the first leg ranked best
                    cur["section"] = h.get("section")
                cur["score"] += 1.0 / (rrf_k + rank)
                if not cur["snippet"] and h.get("snippet"):
                    cur["snippet"] = h["snippet"]

        allow = None if scope is None else self._scope_ids(scope)  # e0cec S5: pushed into retrieval
        try:
            add(self.store.fts_search(query, types=tset, limit=max(k * 3, 20), ids=allow))
        except Exception as e:  # noqa: BLE001 — fts is best-effort, never the write path
            _log.warning("fts search failed: %s", e)
        if self.index is not None:
            add(self.index.search(query, k=max(k * 3, 20), types=tset, allow_ids=allow))
        # S13 F5: an exact readable id, then an exact title, come before relevance (the filters below still apply)
        exact = self._exact_hits(query, tset, allow)
        seen = {f"{h['type']}:{h['id']}" for h in exact}
        ranked = exact + [h for h in sorted(fused.values(), key=lambda h: h["score"], reverse=True)
                          if f"{h['type']}:{h['id']}" not in seen]
        out: list[dict[str, Any]] = []
        for h in ranked:
            self._locate(h)
            if epic_id and h.get("epic_id") != epic_id:
                continue
            if keep is not None and not keep(h):  # the guest scope, applied before the k cap
                continue
            out.append(h)
            if len(out) >= k:
                break
        return out

    _EXACT_TYPES = ("ticket", "doc", "message", "criterion", "decision", "claim", "lesson")

    def _exact_hits(self, query: str, tset: set[str] | None, allow: set[str] | None) -> list[dict[str, Any]]:
        """S13 F5: the object whose id is the query, then the docs and tickets whose title is the query (case
        aside). Only searchable types, only ids inside a guest's scope, never a withdrawn decision or claim."""
        q = query.strip()
        if not q:
            return []
        types = [t for t in self._EXACT_TYPES if tset is None or t in tset]
        out: list[dict[str, Any]] = []

        def hit(t: str, obj: Any, score: float) -> None:
            if (allow is not None and obj.id not in allow) or getattr(obj, "status", None) == "withdrawn":
                return
            text = self.store._fts_text(t, obj.model_dump(mode="json")) or ""
            out.append({"type": t, "id": obj.id, "score": score, "snippet": text.strip()[:200]})

        if len(q) <= 64 and not any(c.isspace() for c in q):
            for t in types:
                try:
                    obj = self.store.get(t, q)
                except Exception:  # noqa: BLE001 -- a type without that id shape is no hit
                    obj = None
                if obj is not None:
                    hit(t, obj, 2.0)
        for t in (t for t in ("doc", "ticket") if t in types):
            for _, obj in self.store.query_body_like(t, q, limit=50, newest_first=True):
                if (getattr(obj, "title", "") or "").strip().casefold() == q.casefold() and obj.id != q:
                    hit(t, obj, 1.0)
        return out

    def _scope_ids(self, scope: Any) -> set[str]:
        """Every searchable id inside a guest scope: its tickets, docs, messages, artifacts and their criteria."""
        ids = set(scope.tickets) | set(scope.docs) | set(scope.messages) | set(scope.artifacts)
        if scope.tickets:
            ids |= {c.id for c in self.store.query("criterion", {"ticket_id": list(scope.tickets)}, limit=1_000_000)}
        return ids

    def _locate(self, h: dict[str, Any]) -> None:
        """Attach ticket_id / epic_id / title to a search hit."""
        t, i = h["type"], h["id"]
        tid: str | None = None
        if t == "ticket":
            tid = i
        elif t == "criterion":
            c = self.store.get("criterion", i)
            tid = c.ticket_id if c else None  # type: ignore[union-attr]
        elif t == "message":
            m = self.store.get("message", i)
            tid = m.ticket_id if m else None  # type: ignore[union-attr]
        elif t == "doc":
            d = self.store.get("doc", i)
            if d is not None:
                h["title"] = d.title  # type: ignore[union-attr]
                h["scope"] = d.scope  # type: ignore[union-attr]
                h.update(doc_tools.legacy_note(d))  # S17 decision 6: every read path warns on a legacy doc
                if d.scope and self.store.get("ticket", d.scope):  # type: ignore[union-attr]
                    tid = d.scope  # type: ignore[union-attr]
        if tid:
            tk = self.store.get("ticket", tid)
            if tk is not None:
                h["ticket_id"] = tid
                h["epic_id"] = tk.epic_id or self.epic_of(tk).id  # type: ignore[union-attr]
                if t == "ticket":
                    h["title"] = tk.title  # type: ignore[union-attr]
                    h["status"] = tk.status  # type: ignore[union-attr]
