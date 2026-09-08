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
from collections.abc import Iterable
from typing import Any

from .schemas import (
    CRITERION_AUTHORS,
    CRITERION_CHECKERS,
    DOC_AUTHORS,
    TICKET_CREATORS,
    TRANSITIONS,
    Artifact,
    ArtifactForm,
    Check,
    CheckedBy,
    Criterion,
    Doc,
    DocType,
    Event,
    EventKind,
    Gate,
    Link,
    Message,
    MessageKind,
    Participant,
    Reason,
    Relation,
    Role,
    Session,
    SessionState,
    StatusValue,
    Ticket,
    TicketKind,
    TicketStatus,
    Verdict,
    WorkType,
    now,
)
from .store import Store, new_id

_MENTION_RX = re.compile(r"@([A-Za-z0-9][A-Za-z0-9_.\-]*)")
_log = logging.getLogger("edp8.board")
HUMAN_GATE_ANSWERERS = {Role.owner}
_TERMINAL = (TicketStatus.done, TicketStatus.partial, TicketStatus.dropped)

# Design §24.1 caps — the tool layer bounds what an architect can file, so an epic's shell
# count is bounded by construction, not restraint. Enforced in the board (not the cards).
STORY_CAP = 8    # stories per epic (not counting done/dropped); the owner raises it via a scope gate
TASK_CAP = 5     # tasks per story (not counting done/dropped)
CRITERIA_CAP = 6  # criteria written fresh on a story (a folded story carries what it inherits)


def _dedup(reasons: list[Reason]) -> list[Reason]:
    """Preserve first-seen order, drop repeats — a recipient's reason list for one event."""
    out: list[Reason] = []
    for r in reasons:
        if r not in out:
            out.append(r)
    return out


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
        # §24 finding 3: the pending queue is volatile; on boot re-derive it from durable board
        # state so a restart between enqueue and drain never loses a reviewer/qa pairing.
        try:
            self._rederive_pending_pairings()
        except Exception as e:  # noqa: BLE001 — a rederive hiccup must never block board startup
            _log.warning("pairing rederive on init failed: %s", e)

    SEAT_FLOOR_MB = 500  # design §24 rule 3: free RAM below this queues a pairing instead of spawning

    # ------------------------------------------------------------------ helpers
    def _get(self, type_: str, id_: str, what: str | None = None):
        o = self.store.get(type_, id_)
        if o is None:
            raise BoardError("not_found", f"{what or type_} {id_!r} does not exist")
        return o

    def _emit(self, subject_id: str, kind: EventKind, data: dict[str, Any] | None = None) -> Event:
        ev = Event(id=new_id("ev"), subject_id=subject_id, kind=kind, data=data or {})
        self.store.put("event", ev)
        self._fanout(ev)
        return ev

    def _index(self, type_: str, id_: str, text: str) -> None:
        if self.index is not None:
            try:
                self.index.upsert(type_, id_, text)
            except Exception as e:  # search is never on the write path's critical line — but never silent
                _log.warning("search index update failed for %s %s: %s", type_, id_, e)

    # ------------------------------------------------------------------ participants
    def participant_create(self, type_: str, role: Role, handle: str, *, location: str | None = None,
                           model: str | None = None, id_: str | None = None) -> Participant:
        handle = handle.lstrip("@")
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
    def ticket_create(self, actor: Participant, *, kind: TicketKind, work_type: WorkType, title: str,
                      parent_id: str | None = None, assignee: str | None = None, description: str = "",
                      tags: list[str] | None = None) -> Ticket:
        if actor.role not in TICKET_CREATORS[kind]:
            raise BoardError("scope", f"{actor.role} may not create a {kind}",
                             f"creators of {kind}: {sorted(r.value for r in TICKET_CREATORS[kind])}")
        if kind == TicketKind.epic and parent_id:
            raise BoardError("schema", "an epic has no parent")
        if kind != TicketKind.epic:
            if not parent_id:
                raise BoardError("schema", f"a {kind} needs parent_id")
            parent = self._get("ticket", parent_id, "parent ticket")
            expected = TicketKind.epic if kind == TicketKind.story else TicketKind.story
            if parent.kind != expected:
                raise BoardError("schema", f"a {kind} must hang under a {expected}, not a {parent.kind}")
        if not title.strip():
            raise BoardError("schema", "title is empty",
                             "an epic's title is the owner's words verbatim; a story/task title names the slice")
        # §24 finding 11: the cap count and the insert are one atomic step under the board lock, so
        # two concurrent creates cannot both read N-1 and both insert (producing N+1 over the cap).
        with self._lock:
            if kind == TicketKind.story and parent_id:
                self._enforce_story_cap(parent_id)
            if kind == TicketKind.task and parent_id:
                self._enforce_task_cap(parent_id)
            t = Ticket(id=new_id(kind.value[0] if kind != TicketKind.epic else "epic"), kind=kind, work_type=work_type,
                       title=title, parent_id=parent_id, assignee=assignee, created_by=actor.id,
                       description=description or "", tags=[x.strip() for x in (tags or []) if x.strip()])
            t.epic_id = t.id if kind == TicketKind.epic else self.epic_of(t).id
            self.store.put("ticket", t)
        self._index("ticket", t.id, self.store._fts_text("ticket", t.model_dump(mode="json")) or t.title)
        self._emit(t.id, EventKind.ticket_created, {"kind": kind, "parent_id": parent_id, "by": actor.id})
        if assignee:
            self._emit(t.id, EventKind.assigned, {"assignee": assignee})
        return t

    def ticket(self, id_: str) -> Ticket:
        return self._get("ticket", id_, "ticket")

    def tickets(self, **filters: Any) -> list[Ticket]:
        return self.store.query("ticket", filters)  # type: ignore[return-value]

    def epic_of(self, t: Ticket) -> Ticket:
        while t.parent_id:
            t = self._get("ticket", t.parent_id)
        return t

    def children(self, ticket_id: str) -> list[Ticket]:
        return self.store.query("ticket", {"parent_id": ticket_id})  # type: ignore[return-value]

    # ------------------------------------------------------------------ caps (design §24.1)
    def _open_stories(self, epic_id: str) -> list[Ticket]:
        """Stories under an epic that still count against the cap (not done/dropped)."""
        return [k for k in self.children(epic_id)
                if k.kind == TicketKind.story and k.status not in (TicketStatus.done, TicketStatus.dropped)]

    def _scope_cap_raised(self, epic_id: str) -> bool:
        """The owner raised this epic's story cap by answering a `scope` gate on it (§24.1)."""
        return any(e.data.get("gate") == Gate.scope.value
                   for e in self.store.query("event", {"subject_id": epic_id, "kind": EventKind.gate_answered}))

    def _enforce_story_cap(self, epic_id: str) -> None:
        if len(self._open_stories(epic_id)) >= STORY_CAP and not self._scope_cap_raised(epic_id):
            raise BoardError("scope", f"an epic holds at most {STORY_CAP} open stories",
                             "split the epic (or the owner answers a `scope` gate to raise the cap)")

    def _enforce_task_cap(self, story_id: str) -> None:
        tasks = [k for k in self.children(story_id)
                 if k.kind == TicketKind.task and k.status not in (TicketStatus.done, TicketStatus.dropped)]
        if len(tasks) >= TASK_CAP:
            raise BoardError("scope", f"a story holds at most {TASK_CAP} tasks",
                             "fold work into fewer tasks, or hand a slice to a second engineer")

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

    def ticket_view(self, ticket_id: str, include: Iterable[str] | None = None, thread_limit: int = 20) -> dict[str, Any]:
        """ONE fat read of a ticket: the record plus every section an agent used to assemble by
        hand (2026-09-06: the most-called tool in the fleet was message_query re-fetching threads).
        `include` narrows the sections; default = all of them."""
        t = self.ticket(ticket_id)
        want = set(include) if include else set(self._VIEW_SECTIONS)
        epic = self.epic_of(t)
        out: dict[str, Any] = {"ticket": t.model_dump(mode="json"), "words": epic.title}
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
            tail = rows[-thread_limit:]
            out["thread"] = [{**m.model_dump(mode="json"), "seq": seq} for seq, m in tail]
            out["thread_seq"] = rows[-1][0] if rows else 0
            out["thread_total"] = len(rows)
        if "links" in want:
            out["links"] = [lk.model_dump(mode="json") for lk in (*self.links(from_id=t.id), *self.links(to_id=t.id))]
        return out

    def message_read(self, id_: str) -> dict[str, Any]:
        m = self._get("message", id_, "message")
        row = m.model_dump(mode="json")
        row["seq"] = self.store.seq_of("message", m.id)
        row["replies"] = [r.model_dump(mode="json") for r in self.store.query("message", {"reply_to": m.id})]
        if m.reply_to:
            parent = self.store.get("message", m.reply_to)
            row["in_reply_to"] = parent.model_dump(mode="json") if parent else None
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
                      description: str | None = None, tags: list[str] | None = None) -> Ticket:
        t = self.ticket(id_)
        changed: dict[str, Any] = {}
        if description is not None or tags is not None:
            if actor.id not in (t.created_by, t.assignee) and actor.role not in (Role.architect, Role.owner,
                                                                                  Role.coordinator):
                raise BoardError("scope", f"{actor.role} may not edit this ticket's description/tags",
                                 "the creator, the assignee, the architect or the owner may")
            if description is not None:
                t.description = description
                changed["description"] = True
            if tags is not None:
                new_tags = [x.strip() for x in tags if x.strip()]
                # §24 finding 5: `review_required` picks the checker, and the checker is baked into
                # each criterion at creation — so once a story has criteria the tag is frozen.
                # Flipping it later would spawn a reviewer who cannot verdict qa-checked criteria, or
                # drop a reviewer whose criteria still demand one. Tag before writing criteria.
                # The criteria-count check is taken under the board lock (second-opinion 2026-09-08)
                # so it serialises against criterion_create's derive+insert — a flip cannot slip in
                # while a first criterion is mid-insert.
                with self._lock:
                    if t.kind == TicketKind.story and self.criteria(t.id):
                        old_rr = "review_required" in (t.tags or [])
                        new_rr = "review_required" in new_tags
                        if old_rr != new_rr:
                            raise BoardError("scope",
                                             "review_required is frozen once a story has criteria "
                                             "(its checkers are already derived)",
                                             "tag the story before writing criteria, or override a "
                                             "criterion's checker as the owner")
                    t.tags = new_tags
                    changed["tags"] = t.tags
        if assignee is not None:
            if actor.role not in (Role.coordinator, Role.architect, Role.engineer, Role.owner):
                raise BoardError("scope", f"{actor.role} may not assign tickets",
                                 "coordinator/architect/owner assign; an engineer assigns its own tasks")
            self.participant(assignee)
            t.assignee = assignee
            changed["assignee"] = assignee
        if design_ref is not None:
            d = self._get("doc", design_ref, "design doc")
            if d.doc_type not in (DocType.design, DocType.report, DocType.note):
                raise BoardError("schema", "design_ref must point at a design (or plan) doc")
            if actor.role not in (Role.architect, Role.engineer):
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
        if "description" in changed or "tags" in changed:
            self._index("ticket", t.id, self.store._fts_text("ticket", t.model_dump(mode="json")) or t.title)
        if "assignee" in changed:
            self._emit(t.id, EventKind.assigned, {"assignee": t.assignee, "by": actor.id})
        if "status" in changed:
            self._emit(t.id, EventKind.status_changed, {**changed["status"], "by": actor.id})
            self._after_status(t)
        return t

    def _guard_transition(self, actor: Participant, t: Ticket, to: TicketStatus) -> None:
        legal = TRANSITIONS[t.status]
        if to not in legal:
            raise BoardError("transition", f"{t.kind} {t.id} is {t.status}; cannot go to {to}",
                             f"legal from {t.status}: {sorted(s.value for s in legal) or 'none (terminal)'}")
        r = actor.role
        crits = self.criteria(t.id)
        if to == TicketStatus.designed:
            if r != Role.architect and not (r == Role.engineer and t.kind == TicketKind.task):
                raise BoardError("scope", "only the architect marks a ticket designed (engineer: its tasks)")
            if t.kind != TicketKind.task and not t.design_ref:
                raise BoardError("transition", "designed needs a design_ref doc",
                                 "doc_create(doc_type=design) then ticket_update(design_ref=...)")
            if not crits:
                # §24 finding 12 (accepted as harmless): "a task cannot leave drafted without a
                # criterion" is enforced only for the FORWARD transition to designed. drafted→dropped
                # (cancelling never-started work) stays legal by design — dropping is not progress.
                raise BoardError("transition", "designed needs at least one criterion",
                                 "criterion_create(...) — checkable: command|path|look|verdict")
        if to == TicketStatus.signed_off:
            if r not in (Role.owner, Role.architect):
                raise BoardError("scope", "sign-off is recorded by the owner, or by the architect quoting the owner")
        if to == TicketStatus.ready:
            if r not in (Role.coordinator, Role.architect, Role.owner, Role.engineer):
                raise BoardError("scope", "ready is set by coordinator/architect/owner (engineer: its tasks)")
            open_blockers = [b for b in self.blockers(t.id) if not self._released(b)]
            if open_blockers:
                raise BoardError("transition", "blocked by unfinished tickets",
                                 "open blockers: " + ", ".join(f"{b.id}({b.status})" for b in open_blockers))
        if to == TicketStatus.in_progress and t.status != TicketStatus.in_review:
            if not (t.assignee or r in (Role.engineer, Role.sme, Role.architect)):
                raise BoardError("transition", "in_progress needs an assignee", "ticket_update(assignee=...)")
            if not t.assignee:
                t.assignee = actor.id
        if to == TicketStatus.in_review:
            if t.assignee and actor.id != t.assignee and r not in (Role.coordinator,):
                raise BoardError("scope", "only the assignee hands a ticket to review")
            if not crits:
                # §24.1(a): a zero-criteria ticket is never evidence-complete, so it must not reach
                # in_review — there is nothing for a checker to verdict and _released would never fire.
                raise BoardError("transition", "in_review needs at least one criterion with evidence",
                                 "criterion_create(...) then criterion_update(evidence_ref=...)")
            missing = [c.id for c in crits if not c.evidence_ref]
            if missing:
                raise BoardError("transition", "in_review needs evidence_ref on every criterion",
                                 f"criteria without evidence: {missing} — /verify, doc_create(report), criterion_update")
        if to == TicketStatus.done:
            if r not in CRITERION_CHECKERS | {Role.coordinator}:
                raise BoardError("scope", "done is set by the checker (reviewer/qa/owner) or the coordinator")
            if not crits:
                raise BoardError("transition", "done needs criteria", "a ticket with no criteria cannot be verified")
            failing = [c.id for c in crits if c.verdict != Verdict.passed]
            if failing:
                raise BoardError("transition", "done needs every criterion verdict=pass",
                                 f"not passed: {failing}")
            if t.kind == TicketKind.epic:
                by_qa = [c for c in crits if c.checked_by == "qa"]
                if not by_qa:
                    raise BoardError("transition", "an epic needs criteria checked_by=qa", "qa acceptance is the last word")

    def legal_transitions(self, actor: Participant, id_: str) -> dict[str, Any]:
        """Every status edge from the ticket's current status, each marked allowed/blocked for THIS
        actor with the board's own reason — the data behind the S16 status control (design §16).
        Reuses `_guard_transition` (the single rule source, so the UI cannot drift from enforcement)
        by probing a deep COPY of the ticket, so a probe never mutates the stored row. The one-line
        consequence per target is left to the client's glossary (one copy source)."""
        t = self.ticket(id_)
        out: list[dict[str, Any]] = []
        for to in sorted(TRANSITIONS[t.status], key=lambda s: s.value):
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
        only when actually `done`, never merely evidence-complete in_review."""
        if b.status == TicketStatus.done:
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
        deps_raw = [self.store.get("ticket", lk.to_id)  # type: ignore[attr-defined]
                    for lk in self.store.query("link", {"from_id": t.id, "relation": Relation.blocks})]
        if t.kind == TicketKind.story and t.parent_id:
            deps_raw += [k for k in self.children(t.parent_id) if k.work_type == WorkType.review and k.id != t.id]
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
        # readiness: a successor waiting on this ticket becomes ready the moment this ticket is
        # RELEASED — evidence-complete in_review, or done (design §24.1: done no longer gates).
        if self._released(t):
            self._release_successors(t)
        # §24 rule 3: a story reaching in_review pairs a reviewer (when review_required); the
        # actual spawn is deferred to run_pending_pairings (the pool-watch loop), preflight-aware.
        if t.status == TicketStatus.in_review and t.kind == TicketKind.story:
            self._on_reach_in_review(t)
        if (t.status == TicketStatus.signed_off and t.kind != TicketKind.epic
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
                parent.status = TicketStatus.in_progress
                self.store.put("ticket", parent)
                self._emit(parent.id, EventKind.status_changed, {"from": "ready", "to": "in_progress", "by": "board"})
            # §24 finding 1 (independent `if`, NOT elif — second-opinion 2026-09-08): an epic opens
            # its acceptance gate once every child is dropped OR released (done, or an evidence-
            # complete in_review story), NOT only when every child is `done`. This MUST run even
            # when the active branch above just moved the epic to in_progress: an evidence-complete
            # story can auto-advance ready→in_review directly (never in_progress), so the epic is
            # still ready/signed_off when its last child releases — an `elif` here skipped the gate
            # and deadlocked (qa is spawned BY the gate). qa then verdicts the in_review stories,
            # then the epic's own criteria.
            if kids and all(k.status == TicketStatus.dropped or self._released(k) for k in kids):
                if parent.kind == TicketKind.epic and parent.status not in (TicketStatus.done, TicketStatus.partial):
                    self.gate_open(parent.id, Gate.acceptance, by="board")
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

    def _enqueue_pairing(self, participant_id: str, role: str, ticket_id: str) -> None:
        with self._lock:
            if self._seat_live(participant_id):
                return
            self._pending_pairings.setdefault(participant_id,
                                              {"role": role, "ticket": ticket_id, "noted": False})

    def _story_wants_reviewer(self, t: Ticket) -> bool:
        """Whether a story pairs a reviewer — derived from the PERSISTED criteria (any criterion
        checked_by=reviewer), NOT the ticket's current tags (§24 finding 5). The checker is baked
        into each criterion at creation; editing `review_required` afterwards cannot retarget a
        criterion, so pairing must read what the criteria actually say — otherwise a late tag change
        spawns a reviewer who cannot verdict, or leaves qa-checked criteria with no reviewer."""
        return (t.kind == TicketKind.story
                and any(c.checked_by == CheckedBy.reviewer.value for c in self.criteria(t.id)))

    def _ticket_has_live_reviewer(self, ticket_id: str) -> bool:
        """A live reviewer-role seat already bound to THIS ticket — matched by the seat handle's
        ticket, not only the canonical `reviewer.<ticket>` id (m-1760540512), so a variant/suffixed
        or separately-spawned reviewer for the same story is not double-paired. Sibling reviewers
        (`reviewer.<other-story>`) do NOT match — pairing is per story."""
        prefix = f"reviewer.{ticket_id}"
        for p in self.store.query("participant", {"role": Role.reviewer}):
            pid = getattr(p, "id", "") or ""
            if (pid == prefix or pid.startswith(prefix + ".") or pid.startswith(prefix + "-")) \
                    and self._seat_live(pid):
                return True
        return False

    def _reviewer_pairing_needed(self, t: Ticket) -> bool:
        """Whether a reviewer must still be paired for story `t`: it is reviewer-checked, no live
        reviewer seat is already on it, and at least one of its reviewer criteria is still
        unverdicted. Skipping an all-verdicted story, or one that already has a live reviewer,
        closes the double-spawn the pairing sweep and the restart re-derivation used to cause
        (m-1760540512: reviewer.s-13cd244cc9 spawned beside reviewer.s-ac1c99a2cb)."""
        if not self._story_wants_reviewer(t):
            return False
        reviewer_crits = [c for c in self.criteria(t.id) if c.checked_by == CheckedBy.reviewer.value]
        if reviewer_crits and all(c.verdict != Verdict.pending for c in reviewer_crits):
            return False  # every reviewer criterion already has a verdict — nothing left to review
        return not self._ticket_has_live_reviewer(t.id)

    def _on_reach_in_review(self, t: Ticket) -> None:
        """A story reaching in_review pairs reviewer.<story> when its criteria are reviewer-checked
        (§24.1: qa is the default checker, so a plain story pairs no reviewer — qa verdicts at
        acceptance). Idempotent: a live reviewer seat (any handle for this ticket) or an
        all-verdicted story short-circuits. The spawn itself is deferred to run_pending_pairings
        (the pool-watch loop / an explicit drain), so no request thread blocks on the pool."""
        if not self._reviewer_pairing_needed(t):
            return
        self._enqueue_pairing(f"reviewer.{t.id}", Role.reviewer.value, t.id)

    def on_new_evidence(self, t: Ticket) -> None:
        """New evidence landed on a reviewer-checked story that is in_review: if its reviewer seat
        closed after a first pass, re-pair it (§24 rule 3, re-spawn on new evidence) — unless a live
        reviewer is already on it or every reviewer criterion is verdicted (m-1760540512)."""
        if t.status == TicketStatus.in_review and self._reviewer_pairing_needed(t):
            self._enqueue_pairing(f"reviewer.{t.id}", Role.reviewer.value, t.id)

    def _rederive_pending_pairings(self) -> None:
        """Rebuild the volatile pairing queue from durable board state (§24 finding 3), so a board
        restart between enqueue and drain never strands a checker. Two sources: a reviewer-checked
        story that is in_review without a live reviewer seat, and an epic whose acceptance gate is
        open without a live qa seat. Idempotent — _enqueue_pairing skips a live seat and de-dups."""
        # scan ALL tickets — the default 500-row page would silently skip eligible stories/epics on
        # a long-lived board (second-opinion 2026-09-08), stranding their pairing after a restart.
        for t in self.store.query("ticket", {}, limit=1_000_000):  # type: ignore[assignment]
            if (t.kind == TicketKind.story and t.status == TicketStatus.in_review
                    and self._reviewer_pairing_needed(t)):  # skips a live reviewer / all-verdicted (m-1760540512)
                self._enqueue_pairing(f"reviewer.{t.id}", Role.reviewer.value, t.id)
            elif (t.kind == TicketKind.epic and t.status not in _TERMINAL
                    and self.open_gates(t.id, Gate.acceptance)):
                # §24.1(a): a terminal epic (done/partial/DROPPED) never re-spawns qa — dropping now
                # closes its gates too, but excluding dropped here is the belt to that suspenders.
                self._enqueue_pairing(f"qa.{t.id}", Role.qa.value, t.id)

    def _pairing_epic_active(self, ticket_id: str) -> bool:
        """§24.1(a): the pairing's epic is still active. A qa pairing's ticket IS the epic; a reviewer
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
        reviewer/qa can authenticate to the board in public mode. Trusted mode (no minter, or the
        minter returns None) injects nothing, exactly as the service route does."""
        if self.store.get("participant", participant_id) is None:
            try:
                self.participant_create("agent", Role(role), participant_id, id_=participant_id)
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
        try:
            res = self._pool_adapter().spawn(role, participant_id, env=env)
        except Exception as e:  # noqa: BLE001 — a pool hiccup keeps the seat registered; retry next tick
            _log.warning("pairing spawn for %s failed: %s", participant_id, e)
            return False
        if isinstance(res, dict) and res.get("ok") is False:
            _log.warning("pairing spawn for %s refused: %s", participant_id, res.get("error"))
            return False
        return True

    def _pairing_note(self, ticket_id: str, text: str) -> None:
        """Post one board-authored thread note (the queued-pairing notice)."""
        m = Message(id=new_id("m"), ticket_id=ticket_id, to=None, kind=MessageKind.note, text=text,
                    created_by="board")
        self.store.put("message", m)
        self._emit(ticket_id, EventKind.message_sent,
                   {"message": m.id, "to": None, "kind": MessageKind.note, "from": "board",
                    "from_type": "agent", "from_role": "board", "text": text[:280], "mentions": []})

    # ------------------------------------------------------------------ criteria
    def checker_for(self, t: Ticket) -> str:
        """The board derives a criterion's checker from its ticket (design §24.1, owner ruling
        v22 2026-09-08): **qa** is the default for a story/epic criterion; a **reviewer** is paired
        only when the architect tags a non-review story `review_required` (auth, sanitiser, cutover);
        a **task** criterion is the task's own **engineer** (a task is the doer's checklist —
        self-verdicted, no paired seat, gating nothing); a knowledge ticket's criteria are the
        **owner**'s single HITL sign-off (the strategy-doc approval). The doer never chooses — this
        removes the blind spot where a story froze on a checker role with no seat."""
        if t.work_type == WorkType.knowledge:
            return CheckedBy.owner.value
        if t.kind == TicketKind.task:
            # §24.1(d): a task derives to its OWN engineer (the story doer). A task is a checklist,
            # self-verdicted by the doer; no seat is paired and a task gates nothing — deriving it to
            # qa deadlocked the epic (qa is auto-paired only at acceptance, which needs tasks done).
            return CheckedBy.engineer.value
        if (t.kind == TicketKind.story and t.work_type != WorkType.review
                and "review_required" in (t.tags or [])):
            return CheckedBy.reviewer.value
        return CheckedBy.qa.value

    def _is_folded(self, ticket_id: str) -> bool:
        """A folded story carries criteria inherited from other stories (prefixed `(from S…)`) —
        its criteria count is not the freshly-written count the cap bounds."""
        return any((c.text or "").lstrip().startswith("(from S") for c in self.criteria(ticket_id))

    def criterion_create(self, actor: Participant, *, ticket_id: str, text: str, check: Check,
                         checked_by: str | None = None, override_reason: str | None = None) -> Criterion:
        t = self.ticket(ticket_id)
        # the owner overriding the derived checker (checked_by + override_reason) is the one case
        # where a non-author writes a criterion; it bypasses the author/engineer/doer guards.
        owner_override = actor.role == Role.owner and checked_by is not None and override_reason is not None
        if not owner_override:
            if actor.role not in CRITERION_AUTHORS:
                raise BoardError("scope", f"{actor.role} may not write criteria",
                                 "the parent owner writes criteria before work: architect (epic/story), engineer (task)")
            if actor.role == Role.engineer and t.kind != TicketKind.task:
                raise BoardError("scope", "an engineer writes criteria for its tasks only")
            if (t.assignee == actor.id and t.kind != TicketKind.task
                    and not (actor.role == Role.architect and t.kind == TicketKind.epic)):
                # the architect IS the designer of epics/stories — assignment bookkeeping must not
                # deadlock criteria authoring (pain 2026-08-23 architect epic deadlock)
                raise BoardError("scope", "the doer of a ticket does not write its criteria")
        if t.status in (TicketStatus.in_review, TicketStatus.done, TicketStatus.partial, TicketStatus.dropped):
            raise BoardError("transition", f"criteria cannot be added to a {t.status} ticket")
        # §24 finding 11 + finding 5 freeze race (second-opinion 2026-09-08): the checker DERIVATION,
        # the cap count and the insert are one atomic step under the board lock. Deriving the checker
        # inside the lock closes the window where a concurrent ticket_update flips `review_required`
        # after this thread read the tags but before it inserted the (now stale-tagged) criterion.
        with self._lock:
            # §24: the board DERIVES the checker; the checked_by argument is accepted for one release
            # but ignored (a hint says so) unless the actor is the owner AND passes an override_reason,
            # which is recorded as a criterion_checker_overridden event.
            derived = self.checker_for(t)
            final = derived
            if checked_by is not None and checked_by != derived and actor.role == Role.owner and override_reason:
                final = checked_by
            if t.kind == TicketKind.story and not self._is_folded(t.id):
                fresh = [c for c in self.criteria(t.id) if not (c.text or "").lstrip().startswith("(from S")]
                if len(fresh) >= CRITERIA_CAP:
                    raise BoardError("scope", f"a story carries at most {CRITERIA_CAP} freshly-written criteria",
                                     "tighten to the load-bearing checks, or split the story")
            c = Criterion(id=new_id("c"), ticket_id=ticket_id, text=text, check=check,
                          checked_by=final, created_by=actor.id)  # type: ignore[arg-type]
            self.store.put("criterion", c)
        if final != derived:
            self._emit(ticket_id, EventKind.criterion_checker_overridden,
                       {"criterion": c.id, "from": derived, "to": final,
                        "reason": override_reason, "by": actor.id})
        return c

    def criterion_update(self, actor: Participant, id_: str, *, evidence_ref: str | None = None,
                         verdict: Verdict | None = None, text: str | None = None,
                         evidence_version: int | None = None, stale_ok: bool = False) -> Criterion:
        c: Criterion = self._get("criterion", id_, "criterion")
        t = self.ticket(c.ticket_id)
        if text is not None:
            if actor.role not in CRITERION_AUTHORS:
                raise BoardError("scope", "criterion text is edited by its authors (architect/engineer)")
            if c.verdict != Verdict.pending:
                raise BoardError("transition", "a verdicted criterion's text is frozen — add a new criterion instead")
            c.text = text
        if evidence_ref is not None:
            self._get("doc", evidence_ref, "evidence doc")
            if actor.id != t.assignee and actor.role not in CRITERION_CHECKERS \
                    and actor.role not in (Role.engineer, Role.sme, Role.adversary):
                raise BoardError("scope", "evidence is recorded by the ticket's doer (engineer/sme/adversary), "
                                          "its assignee, or its checker")
            c.evidence_ref = evidence_ref
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
            if c.checked_by == CheckedBy.engineer.value:
                # §24.1(d): a task criterion is the doer's own checklist — its engineer (or an sme
                # standing in) self-verdicts it; no paired seat and NO doer guard (the doer IS the
                # checker here). Nothing gates on it.
                if actor.role not in (Role.engineer, Role.sme, Role.owner):
                    raise BoardError("scope", "a task criterion is verdicted by its engineer (the task's doer)")
            else:
                if actor.role not in CRITERION_CHECKERS:
                    raise BoardError("scope", "verdicts are recorded by reviewer/qa/owner only")
                if actor.role.value != c.checked_by and actor.role != Role.owner:
                    raise BoardError("scope", f"this criterion is checked_by {c.checked_by}; you are {actor.role}")
                if actor.id == t.assignee:
                    raise BoardError("scope", "the doer cannot verdict its own ticket")
            if verdict != Verdict.pending and not c.evidence_ref:
                raise BoardError("transition", "a verdict needs evidence_ref first", "criterion_update(evidence_ref=...)")
            if verdict != Verdict.pending:
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
            c.verdict = verdict
        self.store.put("criterion", c)
        pending = [x.id for x in self.criteria(t.id) if x.verdict != Verdict.passed]
        if verdict is not None:  # a verdict is a first-class WHO/WHAT event, not a doc edit
            self._emit(t.id, EventKind.criterion_checked,
                       {"criterion": c.id, "verdict": c.verdict, "by": actor.id, "by_type": actor.type,
                        "by_role": actor.role.value if hasattr(actor.role, "value") else actor.role,
                        "evidence": c.evidence_ref, "evidence_version": c.evidence_version,
                        "ticket": t.id, "pending": pending, "check": c.check, "checked_by": c.checked_by})
        else:
            self._emit(t.id, EventKind.doc_updated,
                       {"criterion": c.id, "verdict": c.verdict, "pending": pending, "by": actor.id})
        self._auto_advance(self.ticket(t.id))
        if evidence_ref is not None:  # §24 rule 3: re-pair a closed reviewer when new evidence lands
            self.on_new_evidence(self.ticket(t.id))
        return c

    def _auto_advance(self, t: Ticket) -> None:
        """The board walks a ticket whose facts are already in: evidence on every criterion
        advances ready/in_progress -> in_review; every verdict passed advances in_review -> done
        (the substantive done-guards still apply). Removes the doer/coordinator status-walk
        handshake — a finish before the flip no longer strands the ticket."""
        crits = self.criteria(t.id)
        if not crits:
            return
        if t.status in (TicketStatus.ready, TicketStatus.in_progress) and all(c.evidence_ref for c in crits):
            frm = t.status
            t.status = TicketStatus.in_review
            self.store.put("ticket", t)
            self._emit(t.id, EventKind.status_changed, {"from": frm, "to": "in_review", "by": "board",
                                                        "note": "auto: evidence complete"})
            # §24.1 release rule + §24 rule 3 pairing run in _after_status (in_review branch).
            self._after_status(t)
        if t.status == TicketStatus.in_review and all(c.verdict == Verdict.passed for c in crits):
            if t.kind == TicketKind.epic and not any(c.checked_by == "qa" for c in crits):
                return
            t.status = TicketStatus.done
            self.store.put("ticket", t)
            self._emit(t.id, EventKind.status_changed, {"from": "in_review", "to": "done", "by": "board",
                                                        "note": "auto: all verdicts passed"})
            self._after_status(t)

    # ------------------------------------------------------------------ docs / links
    def doc_create(self, actor: Participant, *, doc_type: DocType, title: str, body_md: str, scope: str) -> Doc:
        if actor.role not in DOC_AUTHORS[doc_type]:
            raise BoardError("scope", f"{actor.role} may not author {doc_type} docs",
                             f"authors: {sorted(r.value for r in DOC_AUTHORS[doc_type])}")
        d = Doc(id=new_id(doc_type.value.replace('_', '')), doc_type=doc_type, title=title, body_md=body_md,
                owner_role=actor.role, scope=scope, created_by=actor.id)
        self.store.put("doc", d)
        self._index("doc", d.id, f"{title}\n{body_md}")
        self._emit(d.id, EventKind.doc_updated, {"version": 1, "doc_type": doc_type, "scope": scope, "by": actor.id})
        return d

    def doc_update(self, actor: Participant, id_: str, *, body_md: str | None = None, title: str | None = None) -> Doc:
        d: Doc = self._get("doc", id_, "doc")
        if actor.role not in DOC_AUTHORS[d.doc_type] and actor.role != d.owner_role:
            raise BoardError("scope", f"{actor.role} may not update {d.doc_type} docs")
        if body_md is None and title is None:
            return d
        d.body_md = body_md if body_md is not None else d.body_md
        d.title = title if title is not None else d.title
        d.version += 1
        self.store.put("doc", d)
        self._index("doc", d.id, f"{d.title}\n{d.body_md}")
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
        for x in (from_id, to_id):
            if not any(self.store.get(t, x) for t in ("ticket", "doc", "artifact")):
                raise BoardError("not_found", f"{x!r} is not a ticket, doc or artifact")
            art = self.store.get("artifact", x)
            if art is not None and getattr(art, "staged", False):  # §18.1: staged uploads are invisible
                raise BoardError("scope", f"artifact {x} is a staged upload; attach it with a message first")
        if relation == Relation.extends:  # layering is doc->doc; a dangling layer breaks assemble_ruleset
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
        self.ticket(ticket_id)
        for a in arts:  # a staged upload is finalised only by the actor who uploaded it (§18.1)
            if a.staged and a.created_by != actor.id:
                raise BoardError("scope", f"artifact {a.id} was uploaded by someone else; "
                                          "only its uploader can attach it")
        for a in arts:
            if a.staged:
                a.staged = False
                self.store.put("artifact", a)
            self.link_create(actor, from_id=ticket_id, to_id=a.id, relation=Relation.produced)
        return arts

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
        for h in _MENTION_RX.findall(text or ""):
            try:
                pid = self.participant(f"@{h}").id
            except BoardError:
                continue
            if pid not in out and pid not in (exclude or set()):
                out.append(pid)
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

    def seat_state(self, pid: str) -> str | None:
        """Latest session state for a participant (alive|parked|dead|stalled); None = never had a shell."""
        rows = sorted(self.store.query("session", {"participant_id": pid}), key=lambda s: s.created_at)
        return rows[-1].state.value if rows else None  # type: ignore[union-attr]

    def seat_for_role(self, role: str, t: Ticket) -> str | None:
        """The seat participant that plays `role` for ticket t: role.<t>, then up the chain to
        role.<epic>, then any role.<sibling> under the epic. A live seat wins; else a registered
        one (the next shell on it reads its inbox first thing); else None."""
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
        self.participant(to)
        return to, ""

    def resolve(self, actor: Participant | None, *, ticket_id: str, to: str | None,
                kind: MessageKind = MessageKind.question) -> dict[str, Any]:
        """The composer wake preview (design §16.1): who a message to `to` of this `kind` on this
        ticket WOULD wake, and why — computed from the SAME delivery.delivery_plan that delivers,
        without persisting or publishing anything. `wakes` and `plan` are the same list (the
        criterion names it `wakes`, the SPA design §16.1 names it `plan`)."""
        from . import delivery
        t = self.ticket(ticket_id)
        resolved, note = self.resolve_recipient(to, t)
        ev = Event(id="ev-preview", subject_id=ticket_id, kind=EventKind.message_sent,
                   data={"to": resolved, "kind": kind,
                         "from": actor.id if actor else None,
                         "from_type": actor.type if actor else None,
                         "from_role": actor.role.value if actor else None,
                         "mentions": self.mentions("")})
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
                     text: str, reply_to: str | None = None) -> Message:
        t = self.ticket(ticket_id)
        asked = to
        to, note = self.resolve_recipient(to, t)
        if reply_to:
            self._get("message", reply_to, "message")
        m = Message(id=new_id("m"), ticket_id=ticket_id, to=to, kind=kind, text=text, reply_to=reply_to,
                    created_by=actor.id)
        self.store.put("message", m)
        self._index("message", m.id, text)
        mentioned = self.mentions(text, exclude={actor.id, to} if to else {actor.id})
        self._emit(t.id, EventKind.message_sent, {"message": m.id, "to": to, "kind": kind, "from": actor.id,
                                                  "from_type": actor.type, "from_role": actor.role.value,
                                                  "text": text[:280], "mentions": mentioned,
                                                  **({"asked": asked, "note": note} if note else {})})
        self.last_send_note = note
        if kind == MessageKind.steer and actor.role == Role.owner and t.kind != TicketKind.task:
            pass  # a steer is data on the thread; widening is the asker's call via /doubt → architect
        return m

    def thread(self, ticket_id: str, limit: int = 50) -> list[Message]:
        return self.store.query("message", {"ticket_id": ticket_id}, limit=limit)  # type: ignore[return-value]

    def gate_open(self, ticket_id: str, gate: Gate, *, by: str = "board", note: str = "") -> Event:
        t = self.ticket(ticket_id)
        # §24.1 cap: design_signoff is refused while the epic carries more than STORY_CAP open
        # stories (a scope gate can raise creation past the cap, but the epic must be split back
        # under the cap before its design is signed off — the cap is a design-time ceiling too).
        if gate == Gate.design_signoff and t.kind == TicketKind.epic:
            n = len(self._open_stories(t.id))
            if n > STORY_CAP:
                raise BoardError("scope", f"the epic has {n} open stories (> {STORY_CAP}); design_signoff is refused",
                                 f"split the epic, or drop/fold stories to {STORY_CAP} or fewer")
        if self.open_gates(ticket_id, gate):
            return self.open_gates(ticket_id, gate)[0]
        ev = self._emit(t.id, EventKind.gate_opened, {"gate": gate, "by": by, "note": note})
        # §24 rule 3: the acceptance gate opening pairs qa.<epic> once (the spawn is deferred to
        # run_pending_pairings so no request thread blocks on the pool).
        if gate == Gate.acceptance and t.kind == TicketKind.epic:
            self._enqueue_pairing(f"qa.{t.id}", Role.qa.value, t.id)
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
        checked by owner (no seat path — qa/reviewer are auto-paired, owner is not a per-story
        seat); (b) a `blocks` cycle among the epic's tickets; (c) a non-review story blocked by the
        review story (the review pass runs after delivery, never before)."""
        stories = [k for k in self._descendants(epic_id) if k.kind == TicketKind.story]
        by_id = {s.id: s for s in stories}
        for s in stories:
            if s.work_type in (WorkType.review, WorkType.knowledge):
                continue
            for c in self.criteria(s.id):
                if c.checked_by == CheckedBy.owner.value:
                    return (f"criterion {c.id} on story {s.id} is checked by owner, which has no seat "
                            f"path before the story is done — the board derives qa/reviewer; drop the "
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
            if frm is not None and to is not None and frm.work_type == WorkType.review \
                    and to.work_type != WorkType.review:
                return (f"non-review story {to.id} is blocked by the review story {frm.id} — the "
                        f"review pass runs after delivery, not before; remove that blocks link")
        return None

    def gate_answer(self, actor: Participant, ticket_id: str, gate: Gate, answer: str) -> Event:
        if actor.role not in HUMAN_GATE_ANSWERERS:
            raise BoardError("scope", f"gate {gate} is answered by a human owner, not {actor.role}")
        if not self.open_gates(ticket_id, gate):
            raise BoardError("transition", f"no open {gate} gate on {ticket_id}")
        if gate == Gate.design_signoff:
            offence = self._design_signoff_lint(self.epic_of(self.ticket(ticket_id)).id)
            if offence:
                raise BoardError("transition", offence,
                                 "fix the named criterion or link, then answer the gate again")
        self.message_send(actor, ticket_id=ticket_id, to=None, kind=MessageKind.answer, text=f"[{gate}] {answer}")
        ev = self._emit(ticket_id, EventKind.gate_answered, {"gate": gate, "answer": answer, "by": actor.id})
        if gate == Gate.design_signoff:
            # the human's word releases what the gate held back: signed-off, unblocked stories go ready now
            for k in self._descendants(ticket_id):
                if k.status == TicketStatus.signed_off:
                    self._after_status(k)
        return ev

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
        return [e for g, e in opened.items() if gate is None or g == gate]

    def _close_open_gates(self, t: Ticket) -> None:
        """§24.1(a): retire every open gate on a ticket that has gone terminal (dropped/done/partial),
        so a dead epic never keeps an acceptance/design_signoff gate that re-derivation would honour."""
        for e in self.open_gates(t.id):
            self._emit(t.id, EventKind.gate_closed, {"gate": e.data.get("gate"), "by": "board",
                                                     "reason": f"{t.kind} {t.id} is {t.status}"})

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
        s = Session(id=id_, participant_id=participant_id, ticket_id=ticket_id, pool_id=pool_id, state=eff_state,
                    resume_token=resume_token or (prev.resume_token if prev else ""), last_output_at=now(),
                    reason=reason or (prev.reason if prev else ""), presence_stale_since=stale_since,
                    created_by="pool")
        self.store.put("session", s)
        if (not presence_stale and ticket_id and eff_state in (SessionState.dead, SessionState.stalled)
                and (prev is None or prev.state != eff_state)):
            kind = EventKind.shell_dead if eff_state == SessionState.dead else EventKind.shell_stalled
            clean = any(k in (reason or "").lower() for k in ("closed by self", "reaped", "clean exit"))
            self._emit(ticket_id, kind, {"session": id_, "participant": participant_id,
                                         "reason": reason or "no reason recorded", "clean": clean})
        return s

    # ------------------------------------------------------------------ context / board / feed
    def my_tickets(self, p: Participant) -> list[Ticket]:
        """Tickets a participant works on: assigned; for checkers (reviewer/qa/owner) also tickets in_review
        whose criteria are checked by their role, and for qa epics with an open acceptance gate; else created-by."""
        mine: list[Ticket] = list(self.store.query("ticket", {"assignee": p.id}))  # type: ignore[arg-type]
        # a per-seat participant is NAMED for its ticket (role.<ticket_id>): surface that ticket
        # even when unassigned (checkers are deliberately not assigned — pain 2026-09-01: a
        # spawned reviewer booted with an empty plate while its story was still in_progress)
        if "." in p.id:
            tid = p.id.split(".", 1)[1]
            tk = self.store.get("ticket", tid)
            if tk is not None and all(x.id != tk.id for x in mine):
                mine.append(tk)  # type: ignore[arg-type]
        if p.role == Role.coordinator:
            for t in self.store.query("ticket", {"kind": TicketKind.epic}):
                if t.status not in _TERMINAL and all(x.id != t.id for x in mine):
                    mine.append(t)  # type: ignore[arg-type]
            mine = [t for t in mine if not (t.kind == TicketKind.epic and t.status in _TERMINAL)]
        if p.role in CRITERION_CHECKERS:
            # §24.1(b) (live failure m-969cb61cfe): a qa seat is named qa.<epic_id> and verdicts ONLY
            # its own epic. Two qa seats for dropped epics were seeing — and starting to verdict — a
            # LIVE epic's in_review stories because qa context was not epic-scoped. Confine both the
            # in_review-story surfacing and the acceptance-gate epics to the seat's own epic.
            own_epic = p.id.split(".", 1)[1] if (p.role == Role.qa and "." in p.id) else None
            for t in self.store.query("ticket", {"status": TicketStatus.in_review}):
                if own_epic is not None and self._epic_id_of(t.id) != own_epic:
                    continue
                if any(c.checked_by == p.role.value for c in self.criteria(t.id)) and all(x.id != t.id for x in mine):
                    mine.append(t)  # type: ignore[arg-type]
            if p.role == Role.qa:
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
                "summary": d.body_md[:n].strip(), "full": "doc_read(id)"}

    def context(self, p: Participant, ticket_id: str | None = None) -> dict[str, Any]:
        """Everything a shell needs: identity, its ticket chain, criteria, linked docs, thread, open asks."""
        tickets = [self.ticket(ticket_id)] if ticket_id else self.my_tickets(p)
        out: dict[str, Any] = {"participant": p.model_dump(mode="json"), "tickets": [], "asks_for_me": [],
                               "hint": ""}
        for t in tickets:
            view = self.ticket_view(t.id)
            strategy_links = view.get("strategy_links", False)
            out["tickets"].append(view)
            if strategy_links and not out["hint"]:
                out["hint"] = (f"strategy/domain docs are linked: run assemble_ruleset(ticket_id={t.id!r}) "
                               "for your working brief (docs above are summaries; doc_read fetches full text)")
        out["asks_for_me"] = self.inbox(p)
        if not tickets:
            out["hint"] = "no ticket assigned or created by you yet"
        return out

    def inbox(self, p: Participant) -> list[dict[str, Any]]:
        """Unanswered questions AND steers addressed to this participant, oldest first. A directed
        steer to a booting seat must survive the whoami->subscribe race, so this is queried BY
        RECIPIENT (indexed) — a global scan capped at 200 rows silently dropped every recent ask
        once the board grew (drill 2026-09-03). Empty list == clear to close."""
        asks = list(self.store.query("message", {"to": p.id,
                                                 "kind": [MessageKind.question, MessageKind.steer]}, limit=100))
        if p.role.value != p.id:
            # a bare-role address (legacy rows, or a role with no seat when sent) reaches the
            # seats of that role ON THE SAME EPIC only — never every seat of the role fleet-wide
            mine = self.my_epics(p)
            for m in self.store.query("message", {"to": p.role.value,
                                                  "kind": [MessageKind.question, MessageKind.steer]}, limit=100):
                if self._epic_id_of(m.ticket_id) in mine:  # type: ignore[union-attr]
                    asks.append(m)

        def _is_answered(ask_id: str) -> bool:
            return bool(self.store.query("message", {"reply_to": ask_id, "kind": MessageKind.answer}, limit=1))

        def _ask_live(m: Message) -> bool:
            """An ask dies with its EPIC (or a dropped ticket) — but a DONE ticket in a live
            epic still takes questions (post-hoc reviews are real; drill 2026-09-03)."""
            tk = self.store.get("ticket", m.ticket_id)
            if tk is None or tk.status == TicketStatus.dropped:  # type: ignore[union-attr]
                return False
            return self.epic_of(tk).status not in _TERMINAL  # type: ignore[arg-type]

        def _ask_row(m: Message) -> dict[str, Any]:
            row = m.model_dump(mode="json")
            sender = self.store.get("participant", m.created_by)
            row["from_type"] = getattr(sender, "type", "agent") if sender else "agent"
            row["from_role"] = getattr(getattr(sender, "role", None), "value", "unknown") if sender else "unknown"
            row["answer_with"] = (f"message_send(ticket_id={m.ticket_id!r}, kind='answer', "
                                  f"to={m.created_by!r}, reply_to={m.id!r})")
            return row

        return [_ask_row(m) for m in asks if not _is_answered(m.id) and _ask_live(m)]

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
        to, _ = self.resolve_recipient(to, t)
        text = f"[{status.value}] {note}".strip()
        m = Message(id=new_id("m"), ticket_id=t.id, to=to, kind=MessageKind.status, text=text,
                    status=status, created_by=actor.id)
        self.store.put("message", m)
        self._index("message", m.id, text)
        self._emit(t.id, EventKind.message_sent, {"message": m.id, "to": to, "kind": MessageKind.status,
                                                  "status": status.value,  # structured; delivery never parses text
                                                  "from": actor.id, "from_type": actor.type,
                                                  "from_role": actor.role.value, "text": text[:280],
                                                  "mentions": self.mentions(text, exclude={actor.id})})
        self._emit(t.id, EventKind.status_recorded, {"participant": actor.id, "status": status.value,
                                                     "ticket": t.id, "message": m.id, "note": note[:280]})
        recipients: list[str] = []
        epic = self.epic_of(t)
        arch = f"architect.{epic.id}"
        if self.store.get("participant", arch) is not None and arch != actor.id:
            recipients.append(arch)
        owner = self.epic_owner(t.id)
        if owner and owner != actor.id and owner not in recipients:
            recipients.append(owner)
        if to and to != actor.id and to not in recipients:
            recipients.append(to)
        return m, recipients

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
        return {"inbox": self.inbox(p), "status": self.last_status(p)}

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
                "open_gates": gates, "words": epic.title}

    def _descendants(self, ticket_id: str) -> list[Ticket]:
        out: list[Ticket] = []
        for k in self.children(ticket_id):
            out.append(k)
            out.extend(self._descendants(k.id))
        return out

    # feed -------------------------------------------------------------
    def _owner_scope(self, p: Participant, subject_id: str) -> bool:
        """Does this owner own the epic this event belongs to? Cross-functional teams:
        each owner-human sees their own epics; legacy/agent-created epics reach every owner."""
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
                        "steer anywhere in your epic whatever the `to`; every recorded status of "
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
        if ev.kind == EventKind.message_sent:
            to = d.get("to")
            if d.get("from") == p.id:
                return out
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
            if p.role in HUMAN_GATE_ANSWERERS or self._in_subtree(p, ev.subject_id):
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
            if p.role == Role.coordinator:
                out.append(Reason.on_ticket)
            else:
                r = self._on_ticket_reason(p, ev.subject_id, parents=True)
                if r:
                    out.append(r)
            return out
        if ev.kind in (EventKind.status_changed, EventKind.ticket_created, EventKind.assigned,
                       EventKind.criterion_checked):
            if p.role == Role.coordinator:
                out.append(Reason.on_ticket)
            elif d.get("assignee") == p.id:
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
        if ev.kind == EventKind.shell_stalled:  # a stall always needs the human
            if self._owner_scope(p, ev.subject_id):
                out.append(Reason.owner_listener)
            return out
        if ev.kind == EventKind.shell_dead:  # v21: a CLEAN self-close after done/reviewed is not paged
            if not d.get("clean") and self._owner_scope(p, ev.subject_id):
                out.append(Reason.owner_listener)
            return out
        if ev.kind == EventKind.status_changed:
            if d.get("to") in ("ready", "in_review", "done", "blocked", "partial", "dropped") \
                    and self._owner_scope(p, ev.subject_id):
                out.append(Reason.owner_listener)
            return out
        if ev.kind == EventKind.criterion_checked:
            # v21 / §24 finding 9 (tightened per second-opinion 2026-09-08): the owner is paged for
            # EVERY criterion check EXCEPT the one case rule 2 names — an AGENT reviewer/qa PASSING a
            # command/path check. Keying suppression on the acting role (by_role), not just by_type +
            # checked_by, closes the branch where an agent seat with Role.owner verdicts a reviewer
            # criterion and was wrongly suppressed. A human's pass, any fail, a `look` check, and an
            # owner-checked criterion all still page.
            if d.get("by") != p.id and self._owner_scope(p, ev.subject_id):
                agent_reviewer_qa_pass = (
                    d.get("by_type") == "agent"
                    and d.get("by_role") in (Role.reviewer.value, Role.qa.value)
                    and d.get("verdict") == Verdict.passed
                    and d.get("check") in (Check.command, Check.path)
                    and d.get("checked_by") != CheckedBy.owner.value)
                if not agent_reviewer_qa_pass:
                    out.append(Reason.owner_listener)
        return out

    def _architect_listener_reasons(self, ev: Event, p: Participant) -> list[Reason]:
        """rule 1: the epic's architect seat hears every crucial event in its subtree whatever
        the addressee — the fix for a low-tier seat addressing its problem to the wrong seat.
        Additive: the addressee still gets its own copy via _general_reasons."""
        d = ev.data
        if d.get("from") == p.id:  # never page the architect for its own action
            return []
        epic = self._epic_ticket(ev.subject_id)
        if epic is None or p.id != f"architect.{epic.id}":
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
        if k in (EventKind.gate_opened, EventKind.gate_answered):
            return [Reason.architect_listener]
        if k == EventKind.shell_stalled:  # a stall is always crucial
            return [Reason.architect_listener]
        if k == EventKind.shell_dead and not d.get("clean"):  # v21: a CLEAN self-close is not a page
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

    def subscribe(self, participant_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs.setdefault(participant_id, []).append(q)
        return q

    def unsubscribe(self, participant_id: str, q: asyncio.Queue) -> None:
        with self._lock:
            lst = self._subs.get(participant_id, [])
            if q in lst:
                lst.remove(q)

    def _fanout(self, ev: Event) -> None:
        with self._lock:
            targets = list(self._subs.items())
        for pid, queues in targets:
            p = self.store.get("participant", pid)
            if p is None or not self.relevant(ev, p):  # type: ignore[arg-type]
                continue
            for q in queues:
                try:
                    q.put_nowait(ev)
                except Exception as e:  # a full/closed feed queue: the subscriber will replay by seq
                    _log.warning("feed queue for %s dropped %s: %s", pid, ev.id, e)

    def replay(self, p: Participant, since_seq: int) -> list[tuple[int, Event]]:
        """All relevant events after since_seq — paged through in full: a monitor that
        reconnects far behind must never silently skip the gap (events_since caps one page)."""
        out: list[tuple[int, Event]] = []
        cur = since_seq
        while True:
            batch = self.store.events_since(cur, limit=500)
            if not batch:
                return out
            for s, e in batch:
                cur = s
                if self.relevant(e, p):
                    out.append((s, e))

    def find(self, query: str, *, k: int = 10, types: Iterable[str] | None = None,
             epic_id: str | None = None) -> list[dict[str, Any]]:
        """Exact words (FTS5) ∪ semantic (BM25 + vectors), fused by reciprocal rank; every hit
        names its ticket and epic so the reader rarely needs a second call."""
        tset = set(types) if types else None
        fused: dict[str, dict[str, Any]] = {}
        rrf_k = 60

        def add(hits: list[dict[str, Any]]) -> None:
            for rank, h in enumerate(hits, start=1):
                key = f"{h['type']}:{h['id']}"
                cur = fused.setdefault(key, {"type": h["type"], "id": h["id"], "score": 0.0,
                                             "snippet": h.get("snippet", "")})
                cur["score"] += 1.0 / (rrf_k + rank)
                if not cur["snippet"] and h.get("snippet"):
                    cur["snippet"] = h["snippet"]

        try:
            add(self.store.fts_search(query, types=tset, limit=max(k * 3, 20)))
        except Exception as e:  # noqa: BLE001 — fts is best-effort, never the write path
            _log.warning("fts search failed: %s", e)
        if self.index is not None:
            add(self.index.search(query, k=max(k * 3, 20), types=tset))
        ranked = sorted(fused.values(), key=lambda h: h["score"], reverse=True)
        out: list[dict[str, Any]] = []
        for h in ranked:
            self._locate(h)
            if epic_id and h.get("epic_id") != epic_id:
                continue
            out.append(h)
            if len(out) >= k:
                break
        return out

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
