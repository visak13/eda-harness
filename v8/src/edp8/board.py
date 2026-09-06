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

_MENTION_RX = re.compile(r"@([A-Za-z0-9][A-Za-z0-9_.\-]*)")

from .schemas import (
    CRITERION_AUTHORS,
    CRITERION_CHECKERS,
    DOC_AUTHORS,
    TICKET_CREATORS,
    TRANSITIONS,
    Artifact,
    ArtifactForm,
    Check,
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

_log = logging.getLogger("edp8.board")
HUMAN_GATE_ANSWERERS = {Role.owner}
_TERMINAL = (TicketStatus.done, TicketStatus.partial, TicketStatus.dropped)


class BoardError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code, self.message, self.hint = code, message, hint

    def to_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message}, "hint": self.hint}


class Board:
    def __init__(self, store: Store, index: Any | None = None):
        self.store = store
        self.index = index  # edp8.search.Index or None
        self._subs: dict[str, list[asyncio.Queue]] = {}
        self._lock = threading.RLock()

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
                t.tags = [x.strip() for x in tags if x.strip()]
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
                raise BoardError("transition", "designed needs at least one criterion",
                                 "criterion_create(...) — checkable: command|path|look|verdict")
        if to == TicketStatus.signed_off:
            if r not in (Role.owner, Role.architect):
                raise BoardError("scope", "sign-off is recorded by the owner, or by the architect quoting the owner")
        if to == TicketStatus.ready:
            if r not in (Role.coordinator, Role.architect, Role.owner, Role.engineer):
                raise BoardError("scope", "ready is set by coordinator/architect/owner (engineer: its tasks)")
            open_blockers = [b for b in self.blockers(t.id) if b.status != TicketStatus.done]
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

    def _design_gate_open(self, t: Ticket) -> bool:
        """An open design_signoff gate on the epic HARD-BLOCKS readiness below it (2026-09-01 pain:
        the board auto-readied stories and seats ran while the owner was still deciding)."""
        epic = self.epic_of(t)
        return epic.id != t.id and bool(self.open_gates(epic.id, Gate.design_signoff))

    def _after_status(self, t: Ticket) -> None:
        # readiness: any sibling/dependent waiting on this ticket becomes ready when unblocked
        if t.status == TicketStatus.done:
            deps_raw = [self.store.get("ticket", lk.to_id)  # type: ignore[attr-defined]
                        for lk in self.store.query("link", {"from_id": t.id, "relation": Relation.blocks})]
            if t.kind == TicketKind.story and t.parent_id:
                deps_raw += [k for k in self.children(t.parent_id) if k.work_type == WorkType.review and k.id != t.id]
            seen: set[str] = set()
            deps = [d for d in deps_raw if d is not None and not (d.id in seen or seen.add(d.id))]
            for dep in deps:
                if dep and dep.status == TicketStatus.signed_off:
                    if all(b.status == TicketStatus.done for b in self.blockers(dep.id))                             and not self._design_gate_open(dep):
                        dep.status = TicketStatus.ready
                        self.store.put("ticket", dep)
                        self._emit(dep.id, EventKind.status_changed,
                                   {"from": "signed_off", "to": "ready", "by": "board"})
        if (t.status == TicketStatus.signed_off and t.kind != TicketKind.epic
                and not [b for b in self.blockers(t.id) if b.status != TicketStatus.done]
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
            elif kids and all(k.status in (TicketStatus.done, TicketStatus.dropped) for k in kids):
                if parent.kind == TicketKind.epic and parent.status not in (TicketStatus.done, TicketStatus.partial):
                    self.gate_open(parent.id, Gate.acceptance, by="board")
                elif parent.kind == TicketKind.story and parent.status == TicketStatus.in_progress:
                    self._emit(parent.id, EventKind.status_changed, {"note": "all tasks done; hand the story to review"})

    # ------------------------------------------------------------------ criteria
    def criterion_create(self, actor: Participant, *, ticket_id: str, text: str, check: Check,
                         checked_by: str) -> Criterion:
        t = self.ticket(ticket_id)
        if actor.role not in CRITERION_AUTHORS:
            raise BoardError("scope", f"{actor.role} may not write criteria",
                             "the parent owner writes criteria before work: architect (epic/story), engineer (task)")
        if actor.role == Role.engineer and t.kind != TicketKind.task:
            raise BoardError("scope", "an engineer writes criteria for its tasks only")
        if t.status in (TicketStatus.in_review, TicketStatus.done, TicketStatus.partial, TicketStatus.dropped):
            raise BoardError("transition", f"criteria cannot be added to a {t.status} ticket")
        if (t.assignee == actor.id and t.kind != TicketKind.task
                and not (actor.role == Role.architect and t.kind == TicketKind.epic)):
            # the architect IS the designer of epics/stories — assignment bookkeeping must not
            # deadlock criteria authoring (pain 2026-08-23 architect epic deadlock)
            raise BoardError("scope", "the doer of a ticket does not write its criteria")
        if t.work_type == WorkType.review and checked_by == "reviewer":
            raise BoardError("schema", "a review-type ticket is checked by qa (or owner), not by reviewer",
                             "the reviewer is the usual doer of a review story; set checked_by=qa")
        c = Criterion(id=new_id("c"), ticket_id=ticket_id, text=text, check=check,
                      checked_by=checked_by, created_by=actor.id)  # type: ignore[arg-type]
        return self.store.put("criterion", c)

    def criterion_update(self, actor: Participant, id_: str, *, evidence_ref: str | None = None,
                         verdict: Verdict | None = None, text: str | None = None) -> Criterion:
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
            if actor.role not in CRITERION_CHECKERS:
                raise BoardError("scope", "verdicts are recorded by reviewer/qa/owner only")
            if actor.role.value != c.checked_by and actor.role != Role.owner:
                raise BoardError("scope", f"this criterion is checked_by {c.checked_by}; you are {actor.role}")
            if actor.id == t.assignee:
                raise BoardError("scope", "the doer cannot verdict its own ticket")
            if verdict != Verdict.pending and not c.evidence_ref:
                raise BoardError("transition", "a verdict needs evidence_ref first", "criterion_update(evidence_ref=...)")
            c.verdict = verdict
        self.store.put("criterion", c)
        pending = [x.id for x in self.criteria(t.id) if x.verdict != Verdict.passed]
        if verdict is not None:  # a verdict is a first-class WHO/WHAT event, not a doc edit
            self._emit(t.id, EventKind.criterion_checked,
                       {"criterion": c.id, "verdict": c.verdict, "by": actor.id, "by_type": actor.type,
                        "evidence": c.evidence_ref, "ticket": t.id, "pending": pending})
        else:
            self._emit(t.id, EventKind.doc_updated,
                       {"criterion": c.id, "verdict": c.verdict, "pending": pending, "by": actor.id})
        self._auto_advance(self.ticket(t.id))
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
        if relation == Relation.extends:  # layering is doc->doc; a dangling layer breaks assemble_ruleset
            for x in (from_id, to_id):
                if self.store.get("doc", x) is None:
                    raise BoardError("scope", f"extends links DOCS only; {x!r} is not a doc",
                                     "layer docs with extends; tie docs to tickets via uses_strategy/uses_domain")
        dup = [lk for lk in self.store.query("link", {"from_id": from_id, "to_id": to_id, "relation": relation})]
        if dup:
            return dup[0]  # type: ignore[return-value]
        lk = Link(id=new_id("lk"), from_id=from_id, to_id=to_id, relation=relation, created_by=actor.id)
        return self.store.put("link", lk)

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
        if self.open_gates(ticket_id, gate):
            return self.open_gates(ticket_id, gate)[0]
        return self._emit(t.id, EventKind.gate_opened, {"gate": gate, "by": by, "note": note})

    def gate_answer(self, actor: Participant, ticket_id: str, gate: Gate, answer: str) -> Event:
        if actor.role not in HUMAN_GATE_ANSWERERS:
            raise BoardError("scope", f"gate {gate} is answered by a human owner, not {actor.role}")
        if not self.open_gates(ticket_id, gate):
            raise BoardError("transition", f"no open {gate} gate on {ticket_id}")
        self.message_send(actor, ticket_id=ticket_id, to=None, kind=MessageKind.answer, text=f"[{gate}] {answer}")
        ev = self._emit(ticket_id, EventKind.gate_answered, {"gate": gate, "answer": answer, "by": actor.id})
        if gate == Gate.design_signoff:
            # the human's word releases what the gate held back: signed-off, unblocked stories go ready now
            for k in self._descendants(ticket_id):
                if k.status == TicketStatus.signed_off:
                    self._after_status(k)
        return ev

    def open_gates(self, ticket_id: str, gate: Gate | None = None) -> list[Event]:
        evs = self.store.query("event", {"subject_id": ticket_id, "kind": [EventKind.gate_opened, EventKind.gate_answered]})
        opened: dict[str, Event] = {}
        for e in evs:  # type: ignore[assignment]
            g = e.data.get("gate")
            if e.kind == EventKind.gate_opened:
                opened[g] = e
            else:
                opened.pop(g, None)
        return [e for g, e in opened.items() if gate is None or g == gate]

    # ------------------------------------------------------------------ sessions (pool-owned)
    def session_upsert(self, *, id_: str, participant_id: str, ticket_id: str | None, pool_id: str,
                       state: SessionState, resume_token: str = "", reason: str = "") -> Session:
        prev = self.store.get("session", id_)
        s = Session(id=id_, participant_id=participant_id, ticket_id=ticket_id, pool_id=pool_id, state=state,
                    resume_token=resume_token or (prev.resume_token if prev else ""), last_output_at=now(),
                    reason=reason or (prev.reason if prev else ""), created_by="pool")
        self.store.put("session", s)
        if ticket_id and state in (SessionState.dead, SessionState.stalled) and (prev is None or prev.state != state):
            kind = EventKind.shell_dead if state == SessionState.dead else EventKind.shell_stalled
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
            for t in self.store.query("ticket", {"status": TicketStatus.in_review}):
                if any(c.checked_by == p.role.value for c in self.criteria(t.id)) and all(x.id != t.id for x in mine):
                    mine.append(t)  # type: ignore[arg-type]
            if p.role == Role.qa:
                for t in self.store.query("ticket", {"kind": TicketKind.epic}):
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

    def relevant(self, ev: Event, p: Participant) -> bool:
        d = ev.data
        if p.id in (d.get("mentions") or []):  # an @mention reaches its person, any role
            return True
        if p.role == Role.owner:
            if ev.kind in (EventKind.gate_opened, EventKind.gate_answered):
                return self._owner_scope(p, ev.subject_id)
            if ev.kind == EventKind.message_sent and d.get("from") != p.id:
                to = d.get("to")
                if to == p.id:
                    return True
                if to == p.role.value:
                    return self._owner_scope(p, ev.subject_id)
                return to is None and d.get("kind") in (MessageKind.status, MessageKind.finding,
                                                         MessageKind.deviation) \
                    and self._owner_scope(p, ev.subject_id)
            # the owner is the orchestrator + recovery seat (no coordinator): it must see
            # dying shells and the phase boundaries its card spawns on — for ITS epics
            if ev.kind in (EventKind.shell_dead, EventKind.shell_stalled):
                return self._owner_scope(p, ev.subject_id)
            if ev.kind == EventKind.status_changed:
                return d.get("to") in ("ready", "in_review", "done", "blocked", "partial") \
                    and self._owner_scope(p, ev.subject_id)
            if ev.kind == EventKind.criterion_checked:
                return d.get("by") != p.id and self._owner_scope(p, ev.subject_id)
            return False
        if ev.kind == EventKind.message_sent:
            to = d.get("to")
            if d.get("from") == p.id:
                return False
            if to == p.id:
                return True
            if to == p.role.value:  # unresolved role note: my epic only, never fleet-wide
                return self._epic_id_of(ev.subject_id) in self.my_epics(p)
            if to is None:  # a thread note reaches the seats working that ticket and its ancestors
                return self._on_ticket(p, ev.subject_id, parents=True)
            return False
        if ev.kind == EventKind.gate_opened:
            return p.role in HUMAN_GATE_ANSWERERS or self._in_subtree(p, ev.subject_id)
        if ev.kind == EventKind.gate_answered:
            opened_by_me = any(e.data.get("gate") == d.get("gate") and e.data.get("by") == p.id
                               for e in self.store.query("event", {"subject_id": ev.subject_id,
                                                                    "kind": EventKind.gate_opened}))
            return d.get("by") == p.id or opened_by_me or self._in_subtree(p, ev.subject_id)
        if ev.kind in (EventKind.shell_dead, EventKind.shell_stalled):
            return p.role == Role.coordinator or self._on_ticket(p, ev.subject_id, parents=True)
        if ev.kind in (EventKind.status_changed, EventKind.ticket_created, EventKind.assigned,
                       EventKind.criterion_checked):
            if p.role == Role.coordinator:
                return True
            if d.get("assignee") == p.id:
                return True
            return self._on_ticket(p, ev.subject_id, parents=True)
        if ev.kind == EventKind.doc_updated:
            return self._on_ticket(p, ev.subject_id, parents=True) if self.store.get("ticket", ev.subject_id) else False
        return False

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
        t = self.store.get("ticket", ticket_id)
        while t is not None:
            if self._works(p, t):
                return True
            if not parents or not t.parent_id:
                return False
            t = self.store.get("ticket", t.parent_id)
        return False

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
