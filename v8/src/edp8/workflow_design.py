"""Design-tab support for workflow drafts (design-e963c656f5 §4.14(c)-(e), S14 s-42a72db3dd).

- `dry_run(body)`: walk a synthetic epic through a draft on a throwaway in-memory board and return a
  timeline of spawns, wakes, gates and transitions; a step no role can take is the named `stall`, and a
  stall blocks Publish (§4.14(e).3).
- `diff(a, b)`: a structural diff of two definitions, keyed by role id, edge, gate and hook.
- `merge3(base, ours, theirs)`: the three-way merge behind "upstream changed" (§4.14(e).4); a field both
  sides changed differently keeps ours and is listed as a conflict.
- `ROLE_TEMPLATES`: the builder and checker starting points for Add role.

The walk uses the real board (`Board(Store(':memory:'))`), so every refusal it names is the board's own.
Nothing it does leaves the scratch board: spawns go to a recording pool and no card file is materialised.
"""
from __future__ import annotations

import copy
from typing import Any

from edp_contracts.roles import non_agent_refusal, retired_refusal

from . import workflow as wflow

# ----------------------------------------------------------------------------- role templates

_TEMPLATE_CARDS = {
    "builder": ("You build one story end to end. Read the story, its criteria and the design it points at, "
                "write a short plan, build it, attach evidence to every criterion, then hand the story to "
                "review."),
    "checker": ("You check finished work. For each criterion checked by your role, re-run its evidence cold "
                "and record a verdict (pass or fail) with a one-line reason. You never build what you check."),
}

#: Add role starting points (§4.14(e).3): the fields a role of that shape needs to pass Validate.
ROLE_TEMPLATES: dict[str, dict[str, Any]] = {
    "builder": {"label": "Builder", "help": "builds stories and tasks; never checks its own work",
                "role": {"card_md": _TEMPLATE_CARDS["builder"], "spawnable": True, "capacity_class": "builder",
                         "may_create": ["task"], "doc_types": ["note", "report"],
                         "bundle": ["ticket_read", "ticket_update", "ticket_create", "criterion_update",
                                    "doc_create", "doc_read", "doc_update", "link_create", "artifact_create"]}},
    "checker": {"label": "Checker", "help": "verdicts criteria it did not build",
                "role": {"card_md": _TEMPLATE_CARDS["checker"], "spawnable": True, "capacity_class": "checker",
                         "criterion_checker": True, "doc_types": ["report"],
                         "bundle": ["ticket_read", "criterion_query", "criterion_update", "doc_create",
                                    "doc_read", "link_create"]}},
}


def role_from_template(template: str, role_id: str) -> dict[str, Any]:
    why = retired_refusal(role_id) or non_agent_refusal(role_id)
    if why:  # owner m-da9a2ae62f: Add role never makes a removed role or a person's role a seat
        raise wflow.WorkflowError("schema", why, "pick another role id")
    t = ROLE_TEMPLATES.get(template)
    if t is None:
        raise wflow.WorkflowError("schema", f"no role template {template!r}", f"one of {sorted(ROLE_TEMPLATES)}")
    return {"id": role_id, **copy.deepcopy(t["role"])}


# ----------------------------------------------------------------------------- diff and merge


def _flat(d: dict[str, Any]) -> dict[str, Any]:
    """A definition as {path: value}: roles by id and field, edges by from→to, gates and hooks by id."""
    out: dict[str, Any] = {}
    for k in ("name", "description", "kinds", "statuses", "terminal", "checkers"):
        if k in d:
            out[k] = d[k]
    for k, v in (d.get("caps") or {}).items():
        out[f"caps.{k}"] = v
    for k, v in (d.get("permissions") or {}).items():
        out[f"permissions.{k}"] = v
    for k, v in (d.get("hooks") or {}).items():
        out[f"hooks.{k}"] = v
    for r in d.get("roles") or []:
        for f, v in r.items():
            if f != "id":
                out[f"roles.{r['id']}.{f}"] = v
        out[f"roles.{r['id']}"] = True  # presence
    for t in d.get("transitions") or []:
        out[f"transitions.{t['from']}→{t['to']}"] = t
    for g in d.get("gates") or []:
        out[f"gates.{g['id']}"] = g
    return out


def _norm(d: wflow.WorkflowDef | dict[str, Any]) -> dict[str, Any]:
    if isinstance(d, dict):
        d = wflow.WorkflowDef.model_validate(wflow.migrate(d))
    return d.model_dump(by_alias=True, mode="json")


def diff(a: wflow.WorkflowDef | dict[str, Any], b: wflow.WorkflowDef | dict[str, Any]) -> list[dict[str, Any]]:
    """What changed from `a` to `b`: [{path, op: added|removed|changed, before, after}] in path order."""
    fa, fb = _flat(_norm(a)), _flat(_norm(b))
    out = []
    for p in sorted(set(fa) | set(fb)):
        if p not in fb:
            out.append({"path": p, "op": "removed", "before": fa[p], "after": None})
        elif p not in fa:
            out.append({"path": p, "op": "added", "before": None, "after": fb[p]})
        elif fa[p] != fb[p]:
            out.append({"path": p, "op": "changed", "before": fa[p], "after": fb[p]})
    return out


def merge3(base: Any, ours: Any, theirs: Any) -> dict[str, Any]:
    """Three-way merge of definitions: a side that left a field as in `base` takes the other side's value;
    both changed alike is taken; both changed differently keeps ours and is a conflict. Returns
    {"body": merged definition, "conflicts": [{path, base, ours, theirs}], "taken": [paths from theirs]}."""
    b, o, t = _norm(base), _norm(ours), _norm(theirs)
    fb, fo, ft = _flat(b), _flat(o), _flat(t)
    missing = object()
    merged: dict[str, Any] = {}
    conflicts, taken = [], []
    for p in sorted(set(fb) | set(fo) | set(ft)):
        vb, vo, vt = fb.get(p, missing), fo.get(p, missing), ft.get(p, missing)
        if vo == vt:
            v = vo
        elif vo == vb:
            v = vt
            taken.append(p)
        elif vt == vb:
            v = vo
        else:
            v = vo
            conflicts.append({"path": p, "base": None if vb is missing else vb,
                              "ours": None if vo is missing else vo, "theirs": None if vt is missing else vt})
        if v is not missing:
            merged[p] = v
    return {"body": _unflat(merged, o, t), "conflicts": conflicts, "taken": taken}


def _unflat(f: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in ours.items() if k not in ("roles", "transitions", "gates", "caps", "permissions",
                                                        "hooks", "name", "description", "kinds", "statuses",
                                                        "terminal", "checkers")}
    for k in ("name", "description", "kinds", "statuses", "terminal", "checkers"):
        if k in f:
            out[k] = f[k]
    for sec in ("caps", "permissions", "hooks"):
        out[sec] = {p.split(".", 1)[1]: v for p, v in f.items() if p.startswith(sec + ".")}

    def ordered(key: str, ident) -> list[Any]:
        seen, order = set(), []
        for x in (ours.get(key) or []) + (theirs.get(key) or []):
            i = ident(x)
            if i not in seen:
                seen.add(i)
                order.append(i)
        return order

    roles = []
    for rid in ordered("roles", lambda r: r["id"]):
        if f.get(f"roles.{rid}") is not True:
            continue
        prefix = f"roles.{rid}."
        roles.append({"id": rid, **{p[len(prefix):]: v for p, v in f.items() if p.startswith(prefix)}})
    out["roles"] = roles
    out["transitions"] = [f[f"transitions.{e}"] for e in ordered("transitions", lambda x: f"{x['from']}→{x['to']}")
                          if f"transitions.{e}" in f]
    out["gates"] = [f[f"gates.{g}"] for g in ordered("gates", lambda x: x["id"]) if f"gates.{g}" in f]
    return out


# ----------------------------------------------------------------------------- dry run


class _RecordingPool:
    def __init__(self) -> None:
        self.spawned: list[tuple[str, str]] = []

    def spawn(self, role: str, pid: str, **_: Any) -> dict[str, Any]:
        self.spawned.append((str(role), pid))
        return {"ok": True}


def _scratch_board():
    from .board import Board
    from .store import Store

    class _DryBoard(Board):
        def seat_spawn_spec(self, ticket_id: str | None, role: Any) -> dict[str, Any]:
            # never materialise a card file from a dry run: the scratch board shares the agent home
            wf = self.workflow_of(self.store.get("ticket", ticket_id) if ticket_id else None)
            return {"env": {}, "capacity": wf.capacity(str(role)), "workflow": wf.ref}

    return _DryBoard(Store(":memory:"), pool=_RecordingPool(), free_mb=lambda: 100_000)


class _Stall(Exception):
    def __init__(self, step: str, needs: str, tried: list[dict[str, str]]):
        super().__init__(step)
        self.step, self.needs, self.tried = step, needs, tried


class _Walk:
    """One synthetic epic (one story) walked through the draft; `events` is the timeline."""

    def __init__(self, d: wflow.WorkflowDef):
        from .schemas import TicketKind, WorkType
        self.d, self.K, self.W = d, TicketKind, WorkType
        self.b = _scratch_board()
        # a scratch id: a definition named like a preset must walk as written, not as the built-in preset
        d = d.model_copy(update={"published": True, "builtin": False, "id": f"dry-{d.id}"})
        self.b.workflows._put(d, by="dry-run")  # the scratch board pins the draft as if published
        self.ref = d.ref
        self.b.workflows.pin("E-dry-run-probe", self.ref)  # makes custom roles known before the epic exists
        self.wf = wflow.Workflow(d)
        self.events: list[dict[str, Any]] = []
        self.live: dict[str, Any] = {}  # role -> participant
        self.seq = 0
        self.epic_id = ""
        self._pending_spawn: tuple[str, Any, dict[str, Any]] | None = None
        designer = self.wf.hook_param("resident_designer", "role")
        self.designer = designer if designer in self.wf.roles else None

    # ---- people
    def _humans(self) -> list[str]:
        return [r.id for r in self.d.roles if r.human]

    def _seats(self) -> list[str]:
        return [r.id for r in self.d.roles if not r.human]

    def _order(self, prefer: list[str | None]) -> list[str]:
        """Candidate roles: the preferred ones, then live seats, then other seats, then humans."""
        out: list[str] = []
        for r in [*prefer, *[x for x in self.live if x in self._seats()], *self._seats(), *self._humans()]:
            if r and r in self.wf.roles and r not in out:
                out.append(r)
        return out

    def _spawner_of(self, role: str) -> str | None:
        """A live role that may spawn `role`; a seat (the architect) before a human (the owner)."""
        live = sorted(self.live, key=lambda r: self.wf.roles[r].human)
        return next((r for r in live if role in self.wf.roles[r].may_spawn), None)

    def who(self, role: str, *, step: str, spawn: bool = True) -> Any | None:
        """The participant acting as `role`: a human is always there; a seat must be spawned by a live role."""
        if role in self.live:
            return self.live[role]
        r = self.wf.roles[role]
        pid = f"{role}.{self.epic_id}" if self.epic_id else f"{role}.dry"
        if r.human:
            p = self.b.store.get("participant", pid) or self.b.participant_create("human", role, pid, id_=pid)
            self.live[role] = p
            return p
        if not spawn:
            return None
        by = self._spawner_of(role)
        if by is None or not r.spawnable:
            return None
        p = self.b.store.get("participant", pid) or self.b.participant_create("agent", role, pid, id_=pid)
        self._pending_spawn = (role, p, {"kind": "spawn", "who": role, "by": by, "step": step,
                                         "text": f"{by} spawns {role}"})
        return p

    def _commit_spawn(self, ok: bool) -> None:
        """A seat counts as spawned only when the step it was brought in for succeeds."""
        pend, self._pending_spawn = self._pending_spawn, None
        if pend and ok:
            role, p, ev = pend
            self.live[role] = p
            self.events.append(ev)

    # ---- timeline
    def _wakes(self, step: str) -> None:
        batch = self.b.store.events_since(self.seq, limit=500)
        for s, ev in batch:
            self.seq = s
            woken = []
            for role, p in self.live.items():
                why = self.b.why(ev, p)
                if why:
                    woken.append(f"{role} ({why})")
            if woken and ev.kind not in ("ticket_created",):
                self.events.append({"kind": "wake", "step": step, "event": str(ev.kind),
                                    "subject": ev.subject_id, "who": ", ".join(woken),
                                    "text": f"{ev.kind} on {ev.subject_id} wakes {', '.join(woken)}"})

    def act(self, step: str, needs: str, prefer: list[str | None], fn, *, kind: str = "act",
            roles: list[str] | None = None) -> tuple[str, Any]:
        """Try `fn(participant)` as each candidate role; the first that the board accepts takes the step."""
        from .board import BoardError
        tried: list[dict[str, str]] = []
        for role in roles if roles is not None else self._order(prefer):
            p = self.who(role, step=step)
            if p is None:
                why = "no live role may spawn it" if self.wf.roles[role].spawnable else "not spawnable"
                tried.append({"role": role, "refusal": why})
                continue
            try:
                out = fn(p)
            except BoardError as e:
                self._commit_spawn(False)
                tried.append({"role": role, "refusal": e.message})
                continue
            self._commit_spawn(True)
            self.events.append({"kind": kind, "step": step, "who": role, "text": f"{role}: {step}"})
            self._wakes(step)
            return role, out
        raise _Stall(step, needs, tried)

    def expect(self, t_id: str, status: str, step: str, needs: str, prefer: list[str | None]) -> None:
        """The ticket reaches `status`: carried by the board already, or moved by a role."""
        from .schemas import TicketStatus
        if str(self.b.ticket(t_id).status) == status:
            self.events.append({"kind": "transition", "step": step, "who": "board",
                                "text": f"board carries {t_id} to {status}"})
            return
        self.act(step, needs, prefer, lambda p: self.b.ticket_update(p, t_id, status=TicketStatus(status)),
                 kind="transition")

    def gate(self, t_id: str, gate: str, opener: str | None, step: str) -> None:
        from .schemas import Gate
        g = self.wf.gates.get(gate)
        if g is None:
            return
        try:
            self.b.gate_open(t_id, Gate(gate), by=opener or "board", note=self.b.gate_question(t_id, gate))
        except Exception as e:  # noqa: BLE001 - the board's refusal is the stall
            raise _Stall(step, f"the {gate} gate opens", [{"role": opener or "board",
                                                             "refusal": getattr(e, "message", str(e))}]) from None
        self.events.append({"kind": "gate", "step": step, "who": opener or "board",
                            "text": f"{gate} gate opens on {t_id}; asks {', '.join(g.answerers) or 'nobody'}"})
        self._wakes(step)
        self.act(f"answer {gate}", f"a human answerer of {gate}", [], kind="gate",
                 roles=[a for a in g.answerers if a in self.wf.roles and self.wf.roles[a].human],
                 fn=lambda p: self.b.gate_answer(p, t_id, Gate(gate), "approved (dry run)"))

    # ---- the walk
    def run(self) -> None:
        from .schemas import Check, DocType, TicketStatus, Verdict
        K, W, b = self.K, self.W, self.b
        epic_by = [r for r in self._humans() if "epic" in self.wf.roles[r].may_create] or self._humans()
        role, epic = self.act("create the epic", "a human role that may create an epic", epic_by, kind="act",
                              roles=epic_by, fn=lambda p: b.ticket_create(p, kind=K.epic, work_type=W.feature,
                                                                          title="Dry-run epic", workflow=self.ref))
        self.epic_id = epic.id
        owner = role
        # the resident designer (if any) is spawned on the epic first
        if self.designer and not self.wf.roles[self.designer].human:
            if self.who(self.designer, step="design the epic") is None:
                raise _Stall("design the epic", f"a live role that may spawn {self.designer}",
                             [{"role": self.designer, "refusal": "no live role may spawn it"}])
            self._commit_spawn(True)
        pref = [self.designer, owner]
        _, design = self.act("write the design", "a role that may author a design doc", pref,
                             fn=lambda p: b.doc_create(p, doc_type=DocType.design, title="design", body_md="# d",
                                                       scope=epic.id))
        self.act("set the epic's design_ref", "a role that may set design_ref on the epic", pref,
                 fn=lambda p: b.ticket_update(p, epic.id, design_ref=design.id))
        _, ec = self.act("write the epic's acceptance criterion", "a criterion author", pref,
                         fn=lambda p: b.criterion_create(p, ticket_id=epic.id, text="epic ships", check=Check.verdict))
        self.expect(epic.id, "designed", "epic → designed", "a role that marks the epic designed", pref)
        if "design_signoff" in self.wf.gates:
            self.gate(epic.id, "design_signoff", self.designer or owner, "design sign-off")
        self.expect(epic.id, "signed_off", "epic → signed_off", "a role that signs the epic off", pref)
        # one story, built by a builder and checked by the story checker
        builders = [r.id for r in self.d.roles if r.capacity_class == "builder"]
        _, story = self.act("create a story", "a role that may create a story", pref,
                            fn=lambda p: b.ticket_create(p, kind=K.story, work_type=W.feature, title="Dry-run story",
                                                         parent_id=epic.id))
        _, sc = self.act("write the story's criterion", "a criterion author", pref,
                         fn=lambda p: b.criterion_create(p, ticket_id=story.id, text="works", check=Check.command))
        self.act("set the story's design_ref", "a role that may set design_ref", pref,
                 fn=lambda p: b.ticket_update(p, story.id, design_ref=design.id))
        self.expect(story.id, "designed", "story → designed", "a role that marks the story designed", pref)
        self.expect(story.id, "signed_off", "story → signed_off", "a role that signs the story off", pref)
        self.expect(story.id, "ready", "story → ready", "a role that marks the story ready", pref)
        doer, _ = self.act("assign the story", "a builder the story can be assigned to", builders,
                           roles=[r for r in self._order(builders) if r in builders] or None,
                           fn=lambda p: b.ticket_update(p, story.id, assignee=p.id))
        self.act("start the story", f"{doer} moves the story to in_progress", [doer], roles=[doer],
                 kind="transition", fn=lambda p: b.ticket_update(p, story.id, status=TicketStatus.in_progress))
        _, rep = self.act("write the evidence report", f"{doer} may author a report", [doer], roles=[doer],
                          fn=lambda p: b.doc_create(p, doc_type=DocType.report, title="evidence", body_md="evidence",
                                                    scope=story.id))
        self.act("attach evidence", f"{doer} attaches evidence", [doer], roles=[doer],
                 fn=lambda p: b.criterion_update(p, sc.id, evidence_ref=rep.id))
        self.act("hand the story to review", f"{doer} moves the story to in_review", [doer], roles=[doer],
                 kind="transition", fn=lambda p: b.ticket_update(p, story.id, status=TicketStatus.in_review))
        # acceptance: the checker seat may be paired by the board
        spawned_before = len(b._pool.spawned)
        paired = b.run_pending_pairings().get("spawned") or []
        for pid in paired:
            prole = pid.split(".", 1)[0]
            p = b.store.get("participant", pid)
            if p is not None:
                self.live[prole] = p
                self.events.append({"kind": "spawn", "who": prole, "by": "board", "step": "acceptance",
                                    "text": f"board pairs {pid} at acceptance"})
        del spawned_before
        self._wakes("acceptance")
        checker = b.ticket(story.id)  # the story's checker is its criterion's checked_by
        c_by = str(b.criteria(checker.id)[0].checked_by)
        self.act("verdict the story's criterion", f"{c_by} verdicts the story", [c_by], roles=[c_by], kind="act",
                 fn=lambda p: b.criterion_update(p, sc.id, verdict=Verdict.passed))
        self.expect(story.id, "done", "story → done", "the checker marks the story done", [c_by])
        e_by = str(b.criteria(epic.id)[0].checked_by)
        self.act("attach epic evidence", f"{e_by} attaches the epic's evidence", [e_by, doer],
                 fn=lambda p: b.criterion_update(p, ec.id, evidence_ref=rep.id))
        self.act("verdict the epic", f"{e_by} verdicts the epic", [e_by], roles=[e_by],
                 fn=lambda p: b.criterion_update(p, ec.id, verdict=Verdict.passed))
        self.expect(epic.id, "done", "epic → done", "the checker marks the epic done", [e_by])


def stall_problem(stall: dict[str, Any]) -> dict[str, str]:
    """A stall as a lint problem (code dry_run_stall), so Validate and Publish report it like any other."""
    tried = "; ".join(f"{t['role']}: {t['refusal']}" for t in stall["tried"][:6])
    why, fix = wflow.WHY_FIX["dry_run_stall"]
    return {"code": "dry_run_stall", "severity": "error", "why": why, "fix": fix, "docs": wflow.WORKFLOW_DOCS,
            "message": f"the dry run stalls at '{stall['step']}': needs {stall['needs']}"
                       + (f" (tried {tried})" if tried else "")}


def dry_run(body: wflow.WorkflowDef | dict[str, Any]) -> dict[str, Any]:
    """Walk a synthetic epic through the definition. Returns {ok, ref, timeline, stall, problems}; `stall`
    is None when the epic reached done, else {step, needs, tried: [{role, refusal}]}."""
    from . import settings
    if settings.env_raw("EDP8_EMBEDDER") is None:
        settings.set_env("EDP8_EMBEDDER", "none")
    try:
        d = body if isinstance(body, wflow.WorkflowDef) else wflow.WorkflowDef.model_validate(wflow.migrate(body))
    except Exception as e:  # noqa: BLE001 - a definition that does not load cannot be walked
        return {"ok": False, "ref": None, "timeline": [], "problems": [],
                "stall": {"step": "load the definition", "needs": "a valid workflow definition",
                          "tried": [{"role": "-", "refusal": str(e)[:500]}]}}
    w = _Walk(d)
    stall = None
    try:
        w.run()
    except _Stall as s:
        stall = {"step": s.step, "needs": s.needs, "tried": s.tried}
        w.events.append({"kind": "stall", "step": s.step, "who": "-",
                         "text": f"stalls at '{s.step}': needs {s.needs}"})
    except Exception as e:  # noqa: BLE001 - any other failure is a stall the author must see
        stall = {"step": "walk", "needs": "the walk to finish", "tried": [{"role": "-", "refusal": str(e)[:500]}]}
        w.events.append({"kind": "stall", "step": "walk", "who": "-", "text": f"stalls: {e}"})
    else:
        w.events.append({"kind": "done", "step": "epic → done", "who": "-", "text": "the epic reached done"})
    return {"ok": stall is None, "ref": d.ref, "timeline": w.events, "stall": stall}
