"""Workflow engine as data (design-e963c656f5 §4.14(b), S13 s-461403ebd1).

A workflow definition is versioned JSON: roles, ticket kinds, statuses, the transition table with
each edge's preconditions, the checker map, caps, gates with their preconditions, permissions and
named hooks. The board resolves ONE `Workflow` per epic (its pin) and reads every rule from it.

No user code runs: a precondition names a predicate from `PREDICATES` and a hook names a behaviour
from `HOOKS`; both are closed vocabularies implemented here and in the board. The built-in presets
(Standard, Lean, Solo) are built from code, so Standard is always exactly today's tables (its
source is the old constants: schemas.TRANSITIONS & co, board caps, bundles.ROLE_BUNDLES).
"""
from __future__ import annotations

import copy
import json
import threading
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .schemas import Role, TicketKind, TicketStatus

STANDARD_ID = "standard"
# §4.14(e).4: the definition format's version. A stored body with an older schema_version is carried
# forward by MIGRATIONS[n] (n → n+1) on read; check_compat() proves every published one still loads.
SCHEMA_VERSION = 1
MIGRATIONS: dict[int, Any] = {}  # {from_version: fn(body: dict) -> dict}; the app ships one per bump

# §4.14(e).1 kernel vs policy: the kernel ships with the app and is never user-editable. Every spawned
# role's tool bundle includes KERNEL_TOOLS, and a card written in a workflow (card_md) is materialised
# as KERNEL_PREAMBLE + the role's own text — the user writes only the role-specific part.
KERNEL_TOOLS = ("whoami", "subscribe", "context", "context_delta", "message_send", "record_status", "inbox")
KERNEL_PREAMBLE = """<!-- edp kernel preamble (ships with the app; not editable in a workflow) -->
**Boot:** `whoami()` → `subscribe()` → arm the feed monitor once and the heartbeat cron once → `context()`.
**Heartbeat:** `context_delta(cursor=<your last cursor>)`; `context()` only at boot or on resync_required.
**Feed and wake:** you wake on events addressed to you and on your tickets; on an idle wake with your work
in progress, resume the next unbuilt item of your plan; end the turn silently only when handed off or blocked.
**Communication:** report on the board only (`message_send` on the ticket thread); nobody reads the shell.
**Close:** `inbox()` → `record_status` → close when your work is handed off.

---
"""


#: t-67dad8c6aa: Claude Code's own slash commands and bundled skills (claude 2.1.280). A role card or skill
#: named like one is booted as `/<name>` and may resolve to the built-in instead of the card, so no card,
#: skill or role takes one of these names. The one place this list lives; tests/test_card_collisions.py.
CLAUDE_BUILTIN_COMMANDS = frozenset({
    "add-dir", "agents", "bashes", "bug", "clear", "compact", "config", "context", "copy", "cost", "doctor",
    "exit", "export", "fast", "feedback", "help", "hooks", "ide", "init", "install-github-app",
    "install-slack-app", "login", "logout", "mcp", "memory", "migrate-installer", "model", "output-style",
    "permissions", "plan", "plugin", "plugins", "pr-comments", "privacy-settings", "quit", "release-notes",
    "remote-env", "rename", "resume", "review", "rewind", "sandbox", "security-review", "skills", "stats",
    "status", "statusline", "tasks", "terminal-setup", "theme", "todos", "upgrade", "usage", "vim",
    # bundled skills, invoked the same way
    "claude-api", "code-review", "fewer-permission-prompts", "keybindings-help", "loop", "run", "schedule",
    "simplify", "update-config", "workflow-authoring",
})
#: A name in both sets, kept on measured evidence that the project card wins over the built-in.
#: doctor: card_collision_drill.py (edp-pool/scripts) ran `/doctor` as the project card on claude 2.1.280
#: (t-67dad8c6aa, architect ruling m-e8f1a59731: no rename; the Help seat's failure was the argv swallow).
CLAUDE_BUILTIN_EXCEPTIONS = {"doctor": "project card measured to win on claude 2.1.280 (t-67dad8c6aa)"}


def ref(wf_id: str, version: int) -> str:
    return f"{wf_id}@{version}"


def card_name(wf_id: str, version: int, role: str) -> str:
    """A materialised card's command name (the pool's EDP_CARD pattern: [a-z][a-z0-9-]{0,40}).

    S11 F6: a readable prefix `wf-<id>-<version>-<role>` (sanitised, cut to 30) plus 10 hex of a sha256
    over the exact triple. A bare truncation made two versions of a long id share one file, so publishing
    v2 overwrote the card v1's epics were pinned to; the hash also separates ids that sanitise alike."""
    import hashlib
    import json
    import re
    digest = hashlib.sha256(json.dumps([wf_id, int(version), role]).encode("utf-8")).hexdigest()[:10]
    prefix = re.sub(r"[^a-z0-9-]", "-", f"wf-{wf_id}-{version}-{role}".lower())[:30].rstrip("-")
    return f"{prefix}-{digest}"


def parse_ref(s: str) -> tuple[str, int]:
    """'lean@2' | 'workflow:lean@2' → ('lean', 2). Raises ValueError on a malformed ref."""
    s = s.strip()
    wf_id, _, ver = s.partition("@")
    if not wf_id or not ver.isdigit():
        raise ValueError(f"workflow ref {s!r} is not <id>@<version>")
    return wf_id, int(ver)


# ----------------------------------------------------------------------------- definition schema


class When(BaseModel):
    """Which tickets a precondition (or checker rule) applies to; every set field must match."""
    model_config = ConfigDict(extra="forbid")
    kinds: list[str] | None = None
    not_kinds: list[str] | None = None
    work_types: list[str] | None = None
    quick: bool | None = None
    parentless: bool | None = None
    from_in: list[str] | None = None
    from_not_in: list[str] | None = None
    quick_root: bool | None = None  # a quick task with no parent (its own epic)


class Precondition(BaseModel):
    """One named check. `message`/`hint` are templates filled from the predicate's detail
    ({id} {kind} {status} {to} {role} plus predicate fields). `hook` ties it to a hook's on/off."""
    model_config = ConfigDict(extra="forbid")
    check: str
    params: dict[str, Any] = Field(default_factory=dict)
    when: When | None = None
    code: Literal["scope", "transition"] = "transition"
    message: str = ""
    hint: str = ""
    hook: str | None = None
    phase: Literal["open", "answer", "both"] = "both"  # gates: checked at gate_open, at the answer, or both


class TransitionDef(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    requires: list[Precondition] = Field(default_factory=list)
    auto: bool = False  # the board carries a ticket along this edge when its (non-role) requires pass
    auto_when: When | None = None  # which tickets the auto-carry applies to


class GateDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    answerers: list[str] = Field(default_factory=list)
    requires: list[Precondition] = Field(default_factory=list)  # to open, and so to answer
    answer_requires: list[Precondition] = Field(default_factory=list)  # extra checks on the answer


class RoleDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str = ""  # S14: the Design tab's display name for a custom role (the id when empty)
    human: bool = False
    card: str = ""  # an agent-home card name (.claude/commands/<card>.md)
    card_md: str = ""  # or the card inline
    model: str | None = None
    harness: str | None = None
    effort: str | None = None
    bundle: list[str] | None = None  # MCP tool names; None = no bundle (identity tools only)
    spawnable: bool = False
    may_spawn: list[str] = Field(default_factory=list)
    may_create: list[str] = Field(default_factory=list)  # ticket kinds
    criterion_author: bool = False
    criterion_checker: bool = False
    gate_answerer: bool = False
    doc_types: list[str] = Field(default_factory=list)  # active doc types it authors
    # §4.14(d) (owner m-c5fa0542fb): the pool caps a role by its class's cap, or by its own max_concurrent
    capacity_class: Literal["builder", "planner", "checker"] | None = None
    max_concurrent: int | None = None
    # §4.14(e).1: the kernel preamble and tool bundle are always applied; False is refused by the lint
    kernel: bool = True


class CheckerRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    when: When | None = None
    role: str


class HookSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class WorkflowDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = SCHEMA_VERSION
    id: str
    version: int = 1
    name: str = ""
    description: str = ""
    builtin: bool = False
    published: bool = False
    # S14 (§4.14(e).3-4): the version this one was duplicated from — the Design tab's diff base and its
    # "upstream changed" check; None for a preset or a definition written from scratch
    source: str | None = None
    roles: list[RoleDef]
    kinds: list[str]
    statuses: list[str]
    terminal: list[str] = Field(default_factory=lambda: ["done", "partial", "dropped"])
    transitions: list[TransitionDef]
    checkers: list[CheckerRule]
    caps: dict[str, int] = Field(default_factory=dict)
    gates: list[GateDef] = Field(default_factory=list)
    permissions: dict[str, list[str]] = Field(default_factory=dict)
    hooks: dict[str, HookSetting] = Field(default_factory=dict)

    @property
    def ref(self) -> str:
        return ref(self.id, self.version)


# ----------------------------------------------------------------------------- predicates (closed set)


class Ctx:
    """What a predicate sees: the board, the actor (None when the board itself carries), the ticket
    (a probe copy on a dry run), the workflow and the edge (from → to) or the gate."""
    __slots__ = ("board", "actor", "t", "wf", "frm", "to", "gate")

    def __init__(self, board: Any, actor: Any, t: Any, wf: Workflow, *, frm: str | None = None,
                 to: str | None = None, gate: str | None = None):
        self.board, self.actor, self.t, self.wf = board, actor, t, wf
        self.frm, self.to, self.gate = frm, to, gate

    @property
    def role(self) -> str | None:
        return None if self.actor is None else str(getattr(self.actor.role, "value", self.actor.role))


Fail = dict[str, Any] | None  # None = the precondition holds; a dict = the detail the message names


def _roles_param(ctx: Ctx, p: dict[str, Any]) -> set[str]:
    roles = set(p.get("roles") or [])
    src = p.get("roles_from")
    if src == "checkers":
        roles |= ctx.wf.criterion_checkers
    elif src == "criterion_authors":
        roles |= ctx.wf.criterion_authors
    elif src:
        roles |= set(ctx.wf.permission(src))
    kind = str(getattr(ctx.t.kind, "value", ctx.t.kind))
    roles |= set((p.get("by_kind") or {}).get(kind, []))
    return roles


def _p_role_in(ctx: Ctx, p: dict[str, Any]) -> Fail:
    if ctx.actor is None:  # a board-authored carry is never refused on the actor
        return None
    if ctx.role in _roles_param(ctx, p):
        return None
    if p.get("or_resident") and ctx.wf.is_resident_designer(ctx.actor, ctx.t):
        return None
    return {"role": ctx.role}


def _p_design_ref(ctx: Ctx, p: dict[str, Any]) -> Fail:
    return None if ctx.t.design_ref else {}


def _p_criteria_min(ctx: Ctx, p: dict[str, Any]) -> Fail:
    n = len(ctx.board.criteria(ctx.t.id))
    return None if n >= int(p.get("n", 1)) else {"n": n}


def _p_blockers_released(ctx: Ctx, p: dict[str, Any]) -> Fail:
    open_ = [b for b in ctx.board.blockers(ctx.t.id) if not ctx.board._released(b)]
    if not open_:
        return None
    return {"open_blockers": ", ".join(f"{b.id}({b.status})" for b in open_)}


def _p_design_signed(ctx: Ctx, p: dict[str, Any]) -> Fail:
    if ctx.role is not None and ctx.role in set(p.get("exempt_roles") or []):
        return None
    return None if ctx.board._design_signed(ctx.t.id) else {}


def _p_assignee_or_claim(ctx: Ctx, p: dict[str, Any]) -> Fail:
    if ctx.t.assignee:
        return None
    if ctx.actor is None or ctx.role not in _roles_param(ctx, p):
        return {}
    ctx.t.assignee = ctx.actor.id  # the claim: the mover becomes the assignee (as before, on the probe too)
    return None


def _p_actor_is_assignee(ctx: Ctx, p: dict[str, Any]) -> Fail:
    if ctx.actor is None or not ctx.t.assignee or ctx.actor.id == ctx.t.assignee:
        return None
    if p.get("or_resident") and ctx.wf.is_resident_designer(ctx.actor, ctx.t):
        return None
    return {}


def _p_evidence_all(ctx: Ctx, p: dict[str, Any]) -> Fail:
    missing = [c.id for c in ctx.board.criteria(ctx.t.id) if not c.evidence_ref]
    return {"missing": missing} if missing else None


def _p_verdicts_passed(ctx: Ctx, p: dict[str, Any]) -> Fail:
    failing = [c.id for c in ctx.board.criteria(ctx.t.id) if str(getattr(c.verdict, "value", c.verdict)) != "pass"]
    return {"failing": failing} if failing else None


def _p_checker_criteria(ctx: Ctx, p: dict[str, Any]) -> Fail:
    role = p.get("role") or ctx.wf.epic_checker
    return None if any(c.checked_by == role for c in ctx.board.criteria(ctx.t.id)) else {"checker": role}


def _p_kind_in(ctx: Ctx, p: dict[str, Any]) -> Fail:
    kind = str(getattr(ctx.t.kind, "value", ctx.t.kind))
    return None if kind in set(p.get("kinds") or []) else {}


def _p_not_terminal(ctx: Ctx, p: dict[str, Any]) -> Fail:
    st = str(getattr(ctx.t.status, "value", ctx.t.status))
    return {"status": st} if st in ctx.wf.terminal else None


def _p_story_cap(ctx: Ctx, p: dict[str, Any]) -> Fail:
    cap = ctx.wf.cap("stories_per_epic")
    n = len(ctx.board._open_stories(ctx.t.id))
    if n > cap and not ctx.board._scope_cap_raised(ctx.t.id):
        return {"n": n, "cap": cap}
    return None


def _p_design_ready(ctx: Ctx, p: dict[str, Any]) -> Fail:
    """The epic has its design_ref and acceptance criteria and sits in a phase the answer may land in."""
    t = ctx.t
    answerable = set(p.get("statuses") or [])
    missing = [what for what, have in (("design_ref", t.design_ref),
                                       ("acceptance criteria", ctx.board.criteria(t.id))) if not have]
    st = str(getattr(t.status, "value", t.status))
    if missing or st not in answerable:
        why = f"it has no {' and no '.join(missing)}" if missing else f"it is {st}, not designed"
        return {"why": why}
    return None


def _p_signoff_lint(ctx: Ctx, p: dict[str, Any]) -> Fail:
    offence = ctx.board._design_signoff_lint(ctx.t.id)
    return {"offence": offence} if offence else None


def _p_human_epic_owner(ctx: Ctx, p: dict[str, Any]) -> Fail:
    if ctx.actor is not None and ctx.actor.type == "human" and ctx.board.epic_owner(ctx.t.id) == ctx.actor.id:
        return None
    return {}


def _p_children_released(ctx: Ctx, p: dict[str, Any]) -> Fail:
    kids = ctx.board.children(ctx.t.id)
    open_ = [k.id for k in kids if not (str(k.status) == "dropped" or ctx.board._released(k))]
    return {"open_children": open_} if (not kids or open_) else None


# name → (fn, is_role_check). A role check is skipped when the board itself carries a ticket.
PREDICATES: dict[str, tuple[Any, bool]] = {
    "role_in": (_p_role_in, True),
    "actor_is_assignee": (_p_actor_is_assignee, True),
    "assignee_or_claim": (_p_assignee_or_claim, True),
    "design_signed": (_p_design_signed, False),
    "design_ref": (_p_design_ref, False),
    "criteria_min": (_p_criteria_min, False),
    "blockers_released": (_p_blockers_released, False),
    "evidence_all": (_p_evidence_all, False),
    "verdicts_passed": (_p_verdicts_passed, False),
    "checker_criteria": (_p_checker_criteria, False),
    "not_terminal": (_p_not_terminal, False),
    "kind_in": (_p_kind_in, False),
    "story_cap": (_p_story_cap, False),
    "design_ready": (_p_design_ready, False),
    "signoff_lint": (_p_signoff_lint, False),
    "human_epic_owner": (_p_human_epic_owner, True),
    "children_released": (_p_children_released, False),
}


class _Fill(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def when_matches(w: When | None, t: Any, *, frm: str | None = None, quick: bool | None = None) -> bool:
    if w is None:
        return True
    kind = str(getattr(t.kind, "value", t.kind))
    if w.kinds is not None and kind not in w.kinds:
        return False
    if w.not_kinds is not None and kind in w.not_kinds:
        return False
    if w.work_types is not None and str(getattr(t.work_type, "value", t.work_type)) not in w.work_types:
        return False
    if w.quick is not None and bool(quick) != w.quick:
        return False
    if w.parentless is not None and (t.parent_id is None) != w.parentless:
        return False
    if w.quick_root is not None and (bool(quick) and t.parent_id is None) != w.quick_root:
        return False
    if w.from_in is not None and frm not in w.from_in:
        return False
    if w.from_not_in is not None and frm in w.from_not_in:
        return False
    return True


class Refusal(Exception):
    """A failed precondition: the board raises it as BoardError(code, message, hint)."""

    def __init__(self, code: str, message: str, hint: str = "", check: str = ""):
        super().__init__(message)
        self.code, self.message, self.hint, self.check = code, message, hint, check


def _render(pre: Precondition, ctx: Ctx, detail: dict[str, Any]) -> Refusal:
    t = ctx.t
    fill = _Fill(id=t.id, kind=str(getattr(t.kind, "value", t.kind)),
                 status=str(getattr(t.status, "value", t.status)), to=ctx.to or "", gate=ctx.gate or "",
                 role=ctx.role or "board")
    fill.update(detail)
    msg = (pre.message or f"{pre.check} failed").format_map(fill)
    hint = pre.hint.format_map(fill) if pre.hint else ""
    return Refusal(pre.code, msg, hint, pre.check)


# ----------------------------------------------------------------------------- hooks (closed set)

# name → default params. A hook is a built-in board behaviour the definition switches and parameterises;
# the board asks `Workflow.hook(name)` at each call site. Unknown names and unknown params are lint errors.
HOOKS: dict[str, dict[str, Any]] = {
    "epic_auto_advance": {},  # the board carries an epic's phase from facts (in_progress, in_review, signed_off)
    "release_cascade": {"review_work_type": "review"},  # released tickets promote signed_off successors to ready
    "criteria_auto_done": {"epic_checker": "qa"},  # in_review → done once every criterion passed (an epic needs the epic checker)
    "signoff_before_start": {},  # a quick task starts only after the owner's design sign-off
    "evidence_before_review": {},  # in_review needs evidence on every criterion
    "acceptance_pairs_checker": {"role": "qa"},  # the acceptance gate pairs `<role>.<epic>` once
    "resident_designer": {"role": "architect"},  # the epic's own designer walks its epic and is addressed as it
    "review_story_last": {"work_type": "review"},  # the review story waits on its siblings, never blocks them
    "knowledge_tickets": {"checked_by": "owner"},  # knowledge tickets are checked by this role
    "one_checker_per_epic": {"role": "qa"},  # a `<role>.<epic>` checker seat verdicts only its own epic
    "quick_task": {"tag": "quick", "checked_by": "owner"},  # the owner's parentless story is a quick task
}


class Workflow:
    """A resolved workflow definition with the lookups the board, bundles and service read."""

    def __init__(self, d: WorkflowDef):
        self.d = d
        self.roles: dict[str, RoleDef] = {r.id: r for r in d.roles}
        self._edges: dict[str, dict[str, TransitionDef]] = {}
        for tr in d.transitions:
            self._edges.setdefault(tr.from_, {})[tr.to] = tr
        self.criterion_authors = {r.id for r in d.roles if r.criterion_author}
        self.criterion_checkers = {r.id for r in d.roles if r.criterion_checker}
        self.gate_answerers = {r.id for r in d.roles if r.gate_answerer}
        self.spawnable = {r.id for r in d.roles if r.spawnable}
        self.terminal = set(d.terminal)
        self.gates = {g.id: g for g in d.gates}

    # ---- identity
    @property
    def id(self) -> str:
        return self.d.id

    @property
    def ref(self) -> str:
        return self.d.ref

    # ---- tables
    def legal(self, status: str) -> set[str]:
        return set(self._edges.get(str(status), {}))

    def edge(self, frm: str, to: str) -> TransitionDef | None:
        return self._edges.get(str(frm), {}).get(str(to))

    def auto_edges(self, frm: str) -> list[TransitionDef]:
        return [e for e in self._edges.get(str(frm), {}).values() if e.auto]

    def creators(self, kind: str) -> set[str]:
        return {r.id for r in self.d.roles if str(kind) in r.may_create}

    def doc_authors(self, doc_type: str) -> set[str]:
        return {r.id for r in self.d.roles if str(doc_type) in r.doc_types or "*" in r.doc_types}

    def bundle(self, role: str) -> list[str] | None:
        """The role's tools; a seat (non-human role) always carries the kernel tools too (§4.14(e).1)."""
        r = self.roles.get(str(role))
        if r is None:
            return None
        out = list(r.bundle or [])
        if r.id not in _BUILTIN_ROLE_IDS:
            # S14 (c-e9d095f3a3): a custom role's bundle never exceeds what its permissions allow
            out = [t for t in out if tool_permitted(self.d, r, t)]
        if not r.human:
            out += [k for k in KERNEL_TOOLS if k not in out]
        return out

    def card(self, role: str) -> tuple[str, str | None]:
        """(card name, text to materialise). A card written in the workflow (card_md) is materialised per
        version as card_name(id, version, role) = KERNEL_PREAMBLE + its text, so an edit in a new version
        reaches only epics pinned to it; a shipped agent-home card (Standard) is used as is (None)."""
        r = self.roles.get(str(role))
        if r is None:
            return str(role), None
        if r.card_md:
            return card_name(self.d.id, self.d.version, r.id), KERNEL_PREAMBLE + r.card_md
        return (r.card or r.id), None

    def capacity(self, role: str) -> dict[str, Any]:
        """What the pool caps this role by: {capacity_class, max_concurrent} (None when unset)."""
        r = self.roles.get(str(role))
        return {"capacity_class": r.capacity_class if r else None, "max_concurrent": r.max_concurrent if r else None}

    def cap(self, name: str) -> int:
        return int(self.d.caps[name])

    def permission(self, name: str) -> list[str]:
        return list(self.d.permissions.get(name, []))

    def allowed(self, name: str, role: Any) -> bool:
        return str(getattr(role, "value", role)) in self.d.permissions.get(name, [])

    def hook(self, name: str) -> dict[str, Any] | None:
        """The hook's params when it is on, else None."""
        h = self.d.hooks.get(name)
        if h is None or not h.on:
            return None
        return {**HOOKS.get(name, {}), **h.params}

    def hook_param(self, name: str, key: str) -> Any:
        h = self.hook(name)
        return None if h is None else h.get(key)

    @property
    def epic_checker(self) -> str | None:
        """The role whose criteria an epic must carry before it is done (criteria_auto_done)."""
        h = self.hook("criteria_auto_done")
        return None if h is None else h.get("epic_checker")

    def checker_for(self, t: Any, *, quick: bool) -> str:
        for rule in self.d.checkers:
            if when_matches(rule.when, t, quick=quick):
                return rule.role
        raise LookupError(f"workflow {self.ref} has no checker for {t.kind}/{t.work_type}")

    def is_resident_designer(self, actor: Any, t: Any) -> bool:
        """The epic's own designer seat (resident_designer hook): `<role>.<epic>`, its assignee or creator."""
        role = self.hook_param("resident_designer", "role")
        if not role or actor is None:
            return False
        return (str(getattr(actor.role, "value", actor.role)) == role
                and str(getattr(t.kind, "value", t.kind)) == "epic"
                and actor.id in (f"{role}.{t.id}", t.assignee, t.created_by))

    # ---- preconditions
    def check(self, pres: list[Precondition], ctx: Ctx, *, quick: bool, skip_roles: bool = False,
              phase: str = "both") -> None:
        """Raise the first failing precondition as a Refusal (in declared order)."""
        for pre in pres:
            if phase != "both" and pre.phase not in (phase, "both"):
                continue
            if pre.hook is not None and self.hook(pre.hook) is None:
                continue
            if not when_matches(pre.when, ctx.t, frm=ctx.frm, quick=quick):
                continue
            fn, is_role = PREDICATES[pre.check]
            if skip_roles and is_role:
                continue
            detail = fn(ctx, pre.params)
            if detail is not None:
                raise _render(pre, ctx, detail)

    def missing(self, pres: list[Precondition], ctx: Ctx, *, quick: bool, skip_roles: bool = False,
                phase: str = "both") -> Refusal | None:
        try:
            self.check(pres, ctx, quick=quick, skip_roles=skip_roles, phase=phase)
        except Refusal as r:
            return r
        return None


# ----------------------------------------------------------------------------- the built-in presets


def _pre(check: str, message: str = "", hint: str = "", *, code: str = "transition", when: dict | None = None,
         hook: str | None = None, phase: str = "both", **params: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"check": check, "params": params, "code": code, "message": message, "hint": hint,
                           "phase": phase}
    if when:
        out["when"] = when
    if hook:
        out["hook"] = hook
    return out


def _arrive_guards(designer: str, signers: list[str], readiers: list[str]) -> dict[str, list[dict[str, Any]]]:
    """The preconditions of every edge INTO a status: today's `_guard_transition`, in its order, with
    its messages verbatim. `designer` marks designed (engineers mark their tasks)."""
    return {
        "designed": [
            _pre("role_in", "only the architect marks a ticket designed (engineer: its tasks)", code="scope",
                 roles=[designer], by_kind={"task": ["engineer"]}),
            _pre("design_ref", "designed needs a design_ref doc",
                 "doc_create(doc_type=design) then ticket_update(design_ref=...)",
                 when={"not_kinds": ["task"], "quick": False}),
            # §24 finding 12 (accepted as harmless): only the FORWARD move to designed needs a criterion;
            # drafted→dropped (cancelling never-started work) stays legal by design.
            _pre("criteria_min", "designed needs at least one criterion",
                 "criterion_create(...) — checkable: command|path|look|verdict", n=1),
        ],
        "signed_off": [
            _pre("role_in", "sign-off is recorded by the owner, or by the architect quoting the owner", code="scope",
                 roles=signers),
        ],
        "ready": [
            _pre("role_in", "ready is set by architect/owner (engineer: its tasks)", code="scope", roles=readiers),
            _pre("blockers_released", "blocked by unfinished tickets", "open blockers: {open_blockers}"),
        ],
        "in_progress": [
            # s-ccdafcb229 (owner m-b13c61ddea): on a quick task the owner reviews the design before any edit
            _pre("design_signed", "quick task {id} waits for the owner's design sign-off",
                 "doc_create(note) as the design, ticket_update(design_ref=…), "
                 "gate_open(design_signoff), then wait for the owner's answer",
                 when={"quick_root": True}, hook="signoff_before_start", exempt_roles=["owner"]),
            _pre("assignee_or_claim", "in_progress needs an assignee", "ticket_update(assignee=...)",
                 when={"from_not_in": ["in_review"]}, roles_from="claim"),
        ],
        "in_review": [
            _pre("actor_is_assignee", "only the assignee hands a ticket to review", code="scope", or_resident=True),
            # §24.1(a): a zero-criteria ticket is never evidence-complete, so it must not reach in_review
            _pre("criteria_min", "in_review needs at least one criterion with evidence",
                 "criterion_create(...) then criterion_update(evidence_ref=...)", n=1),
            _pre("evidence_all", "in_review needs evidence_ref on every criterion",
                 "criteria without evidence: {missing} — /verify, doc_create(report), criterion_update",
                 hook="evidence_before_review"),
        ],
        "partial": [
            _pre("role_in", "partial on an epic is set by the checker (qa/owner), or by the architect on its epic",
                 code="scope", when={"kinds": ["epic"]}, roles_from="checkers", or_resident=True),
        ],
        "done": [
            _pre("role_in", "done is set by the checker (qa/owner), or by the architect on its epic", code="scope",
                 roles_from="checkers", or_resident=True),
            _pre("criteria_min", "done needs criteria", "a ticket with no criteria cannot be verified", n=1),
            _pre("verdicts_passed", "done needs every criterion verdict=pass", "not passed: {failing}"),
            _pre("checker_criteria", "an epic needs criteria checked_by=qa", "qa acceptance is the last word",
                 when={"kinds": ["epic"]}),
        ],
    }


def _transitions(edges: dict[str, set[str]], guards: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out = []
    for frm in sorted(edges):
        for to in sorted(edges[frm]):
            tr: dict[str, Any] = {"from": frm, "to": to, "requires": copy.deepcopy(guards.get(to, []))}
            if frm == "drafted" and to == "designed":
                # S16 / c-c80f7cd8f0: an epic with its design_ref and >=1 criterion is carried to designed
                tr["auto"], tr["auto_when"] = True, {"kinds": ["epic"]}
            out.append(tr)
    return out


def _signoff_gate(answerers: list[str]) -> dict[str, Any]:
    """design_signoff: today's gate_open cap + S16 `design_signoff_refusal`, as declared preconditions."""
    not_quick = {"quick_root": False}
    return {"id": "design_signoff", "answerers": answerers, "requires": [
        # §24.1 cap, lifted by the owner's scope-gate answer (owner m-b0a7f9cda9, pain p-b618055b)
        _pre("story_cap", "the epic has {n} open stories (> {cap}); design_signoff is refused",
             "split the epic, drop/fold stories to {cap} or fewer, or ask the owner to answer a scope gate",
             code="scope", when={"kinds": ["epic"]}, phase="open"),
        _pre("design_ref", "quick task {id} has no design note to sign off",
             "the engineer sets design_ref to its design note first", when={"quick_root": True}),
        _pre("kind_in", "design_signoff is answered on the epic, not {id} ({kind})",
             "open and answer the gate on the epic ticket", code="scope", when=not_quick, kinds=["epic"]),
        _pre("design_ready", "epic {id} is not ready for design sign-off: {why}",
             "set the epic's design_ref and write its acceptance criteria; the board "
             "carries it to `designed` when both are present", when=not_quick,
             statuses=["designed", "signed_off", "in_progress", "in_review"]),
        _pre("signoff_lint", "{offence}", "fix the named criterion or link, then answer the gate again", when=not_quick),
    ], "answer_requires": [
        _pre("human_epic_owner", "this review has no matching human owner", code="scope"),
    ]}


def _plain_gates(answerers: list[str]) -> list[dict[str, Any]]:
    return [{"id": g, "answerers": answerers, "requires": [
        _pre("not_terminal", "{kind} {id} is {status}; a {gate} gate opens only on live work",
             "open it on a live ticket", phase="open")]}
        for g in ("poc", "demo", "adversarial", "budget", "acceptance", "scope")]


def _all_hooks_on() -> dict[str, dict[str, Any]]:
    return {name: {"on": True, "params": dict(params)} for name, params in HOOKS.items()}


def build_standard() -> WorkflowDef:
    """Standard@1 = today's behaviour exactly. Its SOURCE is the old tables, read here and nowhere else:
    schemas.TRANSITIONS/TICKET_CREATORS/CRITERION_AUTHORS/CRITERION_CHECKERS/DOC_AUTHORS, the board caps and
    HUMAN_GATE_ANSWERERS, and bundles.ROLE_BUNDLES."""
    from . import schemas as S
    from .board import CRITERIA_CAP, HUMAN_GATE_ANSWERERS, STORY_CAP, TASK_CAP
    from .bundles import ROLE_BUNDLES  # lazy: bundles imports the MCP client side

    # S19: doctor is the kernel-provided Help seat, always available: the board spawns it on a help topic
    # for any human (edp8.help), so its spawner is the owner; it checks nothing and builds nothing (checker
    # class = exempt from the class caps, counted toward the total only)
    spawnable = {"architect", "engineer", "qa", "adversary", "sme", "doctor"}
    may_spawn = {"owner": ["architect", "engineer", "qa", "adversary", "doctor"],
                 "architect": ["engineer", "qa", "adversary", "sme"]}
    capacity = {"engineer": "builder", "sme": "builder", "adversary": "checker", "qa": "checker",
                "architect": "planner", "doctor": "checker"}
    roles = []
    for r in Role:
        rid = r.value
        roles.append({
            "id": rid, "human": rid in ("owner", "expert"), "card": rid if rid in spawnable else "",
            "bundle": list(ROLE_BUNDLES[rid]) if rid in ROLE_BUNDLES else None,
            "spawnable": rid in spawnable, "may_spawn": may_spawn.get(rid, []),
            "may_create": sorted(k.value for k, who in S.TICKET_CREATORS.items() if r in who),
            "criterion_author": r in S.CRITERION_AUTHORS, "criterion_checker": r in S.CRITERION_CHECKERS,
            "gate_answerer": r in HUMAN_GATE_ANSWERERS,
            "doc_types": sorted(d.value for d, who in S.DOC_AUTHORS.items() if r in who),
            "capacity_class": capacity.get(rid),
        })
    edges = {s.value: {x.value for x in to} for s, to in S.TRANSITIONS.items()}
    answerers = sorted(r.value for r in HUMAN_GATE_ANSWERERS)
    return WorkflowDef.model_validate({
        "id": STANDARD_ID, "version": 1, "name": "Standard", "builtin": True, "published": True,
        "description": "owner → architect (design, sign-off) → engineers → qa at epic acceptance; "
                       "sme for knowledge, adversary review story last.",
        "roles": roles,
        "kinds": [k.value for k in TicketKind if k != TicketKind.topic],
        "statuses": [s.value for s in TicketStatus],
        "transitions": _transitions(edges, _arrive_guards("architect", ["owner", "architect"],
                                                         ["architect", "owner", "engineer"])),
        "checkers": [{"when": {"kinds": ["task"]}, "role": "engineer"}, {"role": "qa"}],
        "caps": {"stories_per_epic": STORY_CAP, "tasks_per_story": TASK_CAP, "criteria_per_story": CRITERIA_CAP},
        "gates": [_signoff_gate(answerers), *_plain_gates(answerers)],
        "permissions": {
            "set_title": ["architect", "owner"], "edit_ticket": ["architect", "owner"],
            "assign": ["architect", "engineer", "owner"], "set_design_ref": ["architect", "engineer"],
            "claim": ["engineer", "sme", "architect"], "evidence": ["engineer", "sme", "adversary"],
            "task_verdict": ["engineer", "sme", "owner"], "binding": ["architect", "owner"],
        },
        "hooks": _all_hooks_on(),
    })


def _preset_from_standard(wf_id: str, name: str, description: str, *, keep_roles: list[str],
                          designer: str, checker_roles: list[str], spawns: dict[str, list[str]],
                          story_checker: str, hooks: dict[str, dict[str, Any]]) -> WorkflowDef:
    """A smaller preset derived from Standard: the kept roles, `designer` doing the architect's part."""
    std = build_standard().model_dump(by_alias=True)
    roles = {r["id"]: r for r in std["roles"] if r["id"] in keep_roles}
    arch = next(r for r in std["roles"] if r["id"] == "architect")
    d = roles[designer]
    d["may_create"] = sorted(set(d["may_create"]) | {"story"})
    d["criterion_author"] = True
    d["doc_types"] = sorted(set(d["doc_types"]) | {"design"})
    d["bundle"] = sorted(set(d["bundle"] or []) | {"criterion_create", "doc_create", "doc_update", "link_create"})
    for rid, r in roles.items():
        r["criterion_checker"] = rid in checker_roles
        r["may_spawn"] = spawns.get(rid, [])
        r["spawnable"] = any(rid in v for v in spawns.values())
        r["doc_types"] = sorted(set(r["doc_types"]) | ({"report"} if rid in checker_roles and not r["human"] else set()))
    del arch
    signers = [designer]
    readiers = sorted({designer, "engineer"})
    std_hooks = _all_hooks_on()
    for k, v in hooks.items():
        std_hooks[k] = v
    edges: dict[str, set[str]] = {}
    for tr in std["transitions"]:
        edges.setdefault(tr["from"], set()).add(tr["to"])
    guards = _arrive_guards(designer, signers, readiers)
    guards["designed"][0]["message"] = f"only the {designer} marks a ticket designed (engineer: its tasks)"
    guards["signed_off"][0]["message"] = f"sign-off is recorded by the {designer}"
    guards["ready"][0]["message"] = f"ready is set by the {designer} (engineer: its tasks)"
    who = "/".join(checker_roles)
    guards["partial"][0]["message"] = f"partial on an epic is set by the checker ({who}), or by the {designer} on its epic"
    guards["done"][0]["message"] = f"done is set by the checker ({who}), or by the {designer} on its epic"
    guards["done"][3]["message"] = f"an epic needs criteria checked_by={story_checker}"
    guards["done"][3]["hint"] = f"{story_checker} acceptance is the last word"
    perms = copy.deepcopy(std["permissions"])
    for k, v in perms.items():
        perms[k] = sorted({designer if x == "architect" else x for x in v} & set(keep_roles))
    answerers = ["owner"]
    return WorkflowDef.model_validate({
        **std, "id": wf_id, "version": 1, "name": name, "description": description, "builtin": True,
        "published": True, "roles": list(roles.values()),
        "transitions": _transitions(edges, guards),
        "checkers": [{"when": {"kinds": ["task"]}, "role": "engineer"}, {"role": story_checker}],
        "gates": [_signoff_gate(answerers), *_plain_gates(answerers)],
        "permissions": perms, "hooks": std_hooks,
    })


def build_lean() -> WorkflowDef:
    """Lean: owner → engineer → qa. The owner designs and signs off; no architect or sme seat."""
    return _preset_from_standard(
        "lean", "Lean", "owner designs and signs off → engineers build → qa checks at epic acceptance.",
        keep_roles=["owner", "engineer", "qa"], designer="owner", checker_roles=["qa", "owner"],
        spawns={"owner": ["engineer", "qa"]}, story_checker="qa",
        hooks={"resident_designer": {"on": True, "params": {"role": "owner"}}})


def build_solo() -> WorkflowDef:
    """Solo: owner → engineer, and the owner checks. No checker seat is paired at acceptance."""
    return _preset_from_standard(
        "solo", "Solo", "owner designs, signs off and checks; one engineer builds.",
        keep_roles=["owner", "engineer"], designer="owner", checker_roles=["owner"],
        spawns={"owner": ["engineer"]}, story_checker="owner",
        hooks={"resident_designer": {"on": True, "params": {"role": "owner"}},
               "acceptance_pairs_checker": {"on": False, "params": {"role": "qa"}},
               "one_checker_per_epic": {"on": False, "params": {"role": "qa"}},
               "criteria_auto_done": {"on": True, "params": {"epic_checker": "owner"}}})


BUILTIN_BUILDERS = {"standard": build_standard, "lean": build_lean, "solo": build_solo}


# ----------------------------------------------------------------------------- lint (validate)


def _card_exists(name: str) -> bool:
    return card_path(name) is not None


def card_path(name: str) -> Any:
    """The shipped card file for `name` (agent home, then the wheel's packaged home or, in dev mode, the
    source checkout: materialise.source_root)."""
    from pathlib import Path
    try:
        from . import settings
        home = settings.agent_home()
    except Exception:  # noqa: BLE001 - no agent home resolvable: fall back to the packaged tree
        home = None
    roots = [Path(home)] if home else []
    from .materialise import source_root
    try:
        roots.append(source_root())
    except FileNotFoundError:
        pass
    return next((f for r in roots if (f := r / ".claude" / "commands" / f"{name}.md").is_file()), None)


_BUILTIN_ROLE_IDS = frozenset(r.value for r in Role)
WORKFLOW_DOCS = "/ui/design (the Design tab) and docs/site workflows page"
# §4.14(e).2: every problem says what is wrong (message), why it matters and the fix.
WHY_FIX: dict[str, tuple[str, str]] = {
    "schema": ("the board cannot load a definition that does not match the workflow schema",
               "correct the named field (GET /v1/workflows/standard@1 shows a complete definition)"),
    "schema_version": ("this app cannot read the definition's format version",
                       "update the app, or re-create the workflow from a preset here"),
    "unknown_status": ("the status set is kernel: board columns, guards, feed wake rules and the SPA key on it",
                       "use only the built-in statuses; a workflow chooses the edges between them"),
    "unknown_kind": ("the board only stores the built-in ticket kinds", "use epic, story or task"),
    "unknown_role": ("a rule naming a role that does not exist can never be satisfied, so tickets stall",
                     "add the role under `roles`, or name an existing one"),
    "unreachable_status": ("no ticket can ever enter this status, so work routed through it never arrives",
                           "add a transition into it, or remove it from `statuses`"),
    "dead_end_status": ("a ticket that enters this non-terminal status can never leave it, so the epic stalls",
                        "add a transition out of it, or list it under `terminal`"),
    "kind_without_checker": ("nobody verdicts this kind's criteria, so it can never reach done",
                             "add a `checkers` rule for the kind naming a role that does not build it"),
    "checker_is_doer": ("the role that builds the work would also verdict it, so work approves itself",
                        "check the kind with a role that is not a builder (qa, or the owner)"),
    "self_approval": ("the role that opens this gate also answers it, so the gate approves itself",
                      "make a different (human) role the gate's answerer"),
    "gate_unanswerable": ("no human can answer this gate: it waits forever, and Needs you never shows it",
                          "add a human role (the owner) to the gate's answerers"),
    "role_without_spawner": ("no seat of this role can ever start, so its tickets are never worked",
                             "add the role to some role's `may_spawn`"),
    "card_missing": ("a spawned seat boots from its card; without one it has no instructions",
                     "write the role's card (`card_md`) or name a shipped card (`card`)"),
    "unknown_capacity": ("the pool caps seats by capacity class or the role's own cap; an uncapped role "
                         "can exhaust the host", "set capacity_class (builder, planner, checker) or max_concurrent"),
    "cap_below_1": ("a cap of 0 does not pause work, it deadlocks it: nothing can be created or spawned",
                    "set it to 1 or more; pausing is its own control"),
    "kernel_stripped": ("the kernel preamble and tools carry the boot, feed and close contract every seat "
                        "relies on", "leave `kernel` true; write only the role-specific card and tools"),
    "unknown_hook": ("hooks are a fixed registry, because no user code runs", "pick a hook from the registry"),
    "hook_param": ("the hook ignores an unknown parameter, so the setting would silently do nothing",
                   "use one of the hook's named params"),
    "unknown_predicate": ("preconditions are a closed vocabulary; an unknown one cannot be evaluated",
                          "pick a predicate from the vocabulary"),
    "gate_without_precondition": ("a gate with no precondition can be opened on anything, so its answer "
                                  "means nothing", "declare what must hold before it opens (e.g. not_terminal)"),
    "transition_without_precondition": ("anyone may take this edge at any time",
                                        "declare who may take it (role_in) or what must hold"),
    # S14 (c-e9d095f3a3): custom roles
    "bundle_missing": ("a seat with no tools beyond the kernel can boot and report, but never do its work",
                       "tick the tools the role needs in its tool checklist (or start from a role template)"),
    "self_check": ("a role that both produces work (authors criteria, attaches evidence or builds) and "
                   "verdicts criteria approves its own work", "split the doing and the checking into two roles"),
    "escalation": ("the role's tools or permissions reach past what its job allows (an agent answering gates, "
                   "spawning without may_spawn), so it can grant itself what a human should decide",
                   "untick the tool, or give the permission to a human role"),
    "unusable_tool": ("the board refuses this tool for the role's permissions, so ticking it does nothing",
                      "untick it, or grant the matching permission"),
    "dry_run_stall": ("a synthetic epic walked through the draft cannot reach done, so real epics would stall",
                      "open Dry run to see the step no role can take, then fix that role or transition"),
}

#: S14 (c-e9d095f3a3): a tool that needs a permission. `escalation` (error) when granting the tool would let
#: an agent do a human's or a spawner's part; `unusable_tool` (warning) when the board would just refuse it.
TOOL_NEEDS: dict[str, tuple[str, str]] = {
    "gate_answer": ("gate_answerer", "escalation"),
    "spawn": ("may_spawn", "escalation"),
    "reap": ("may_spawn", "escalation"),
    "set_binding": ("binding", "escalation"),
    "ticket_create": ("may_create", "unusable_tool"),
    "criterion_create": ("criterion_author", "unusable_tool"),
}


def tool_permitted(d: WorkflowDef, r: RoleDef, tool: str) -> bool:
    """Does the role hold the permission a tool needs (TOOL_NEEDS)? A tool with no entry needs none."""
    need = TOOL_NEEDS.get(tool)
    if need is None:
        return True
    field = need[0]
    if field == "gate_answerer":
        return r.gate_answerer and r.human
    return bool(getattr(r, field)) if field in RoleDef.model_fields else r.id in d.permissions.get(field, [])


def _story_checked_apart(d: WorkflowDef, by_id: dict[str, RoleDef]) -> bool:
    probe = type("T", (), {"kind": "story", "work_type": "feature", "parent_id": "p"})()
    rule = next((r for r in d.checkers if when_matches(r.when, probe, quick=False)), None)
    return rule is not None and rule.role in by_id and by_id[rule.role].capacity_class != "builder"


def validate(d: WorkflowDef | dict[str, Any]) -> list[dict[str, str]]:
    """The lint and the publish invariants (§4.14(e).2). Each problem is {code, message, why, fix,
    severity, docs}; publish refuses any error. Codes: the keys of WHY_FIX."""
    errs: list[dict[str, str]] = []

    def err(code: str, message: str, severity: str = "error") -> None:
        why, fix = WHY_FIX.get(code, ("", ""))
        errs.append({"code": code, "message": message, "why": why, "fix": fix, "severity": severity,
                     "docs": WORKFLOW_DOCS})

    if isinstance(d, dict):
        try:
            d = WorkflowDef.model_validate(migrate(d))
        except WorkflowError as e:
            err("schema_version", e.message)
            return errs
        except Exception as e:  # noqa: BLE001 - pydantic's message is the lint line
            err("schema", str(e))
            return errs
    statuses, kinds, roles = set(d.statuses), set(d.kinds), {r.id for r in d.roles}
    by_id = {r.id: r for r in d.roles}
    for s in statuses - {x.value for x in TicketStatus}:
        err("unknown_status", f"status {s!r} is not a board status ({', '.join(x.value for x in TicketStatus)})")
    for k in kinds - {x.value for x in TicketKind}:
        err("unknown_kind", f"kind {k!r} is not a ticket kind")

    def pres_ok(where: str, pres: list[Precondition]) -> None:
        for p in pres:
            if p.check not in PREDICATES:
                err("unknown_predicate", f"{where}: precondition {p.check!r} is not one of {sorted(PREDICATES)}")
            if p.hook is not None and p.hook not in HOOKS:
                err("unknown_hook", f"{where}: precondition names hook {p.hook!r}, not one of {sorted(HOOKS)}")
            for key in ("roles",):
                for r in p.params.get(key) or []:
                    if r not in roles:
                        err("unknown_role", f"{where}: precondition {p.check} names role {r!r}")

    # transitions: known statuses, preconditions named, every status reachable from `drafted`
    graph: dict[str, set[str]] = {}
    for tr in d.transitions:
        for s in (tr.from_, tr.to):
            if s not in statuses:
                err("unknown_status", f"transition {tr.from_}→{tr.to} names status {s!r} not in statuses")
        graph.setdefault(tr.from_, set()).add(tr.to)
        pres_ok(f"transition {tr.from_}→{tr.to}", tr.requires)
        if not tr.requires and tr.to not in d.terminal and tr.to != "blocked":
            # a warning: a backward edge (redesign) may be deliberately free; publish refuses errors only
            err("transition_without_precondition", f"transition {tr.from_}→{tr.to} declares no precondition",
                "warning")
    start = "drafted" if "drafted" in statuses else (d.statuses[0] if d.statuses else "")
    seen, todo = {start}, [start]
    while todo:
        for nxt in graph.get(todo.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    for s in d.statuses:
        if s not in seen:
            err("unreachable_status", f"status {s!r} cannot be reached from {start!r}")
        elif s not in d.terminal and s != "blocked" and not graph.get(s):
            err("dead_end_status", f"non-terminal status {s!r} has no transition out")
    # checkers: every kind resolves to a checker role that exists
    for k in d.kinds:
        probe = type("T", (), {"kind": k, "work_type": "feature", "parent_id": "p"})()
        rule = next((r for r in d.checkers if when_matches(r.when, probe, quick=False)), None)
        if rule is None:
            err("kind_without_checker", f"kind {k!r} has no checker rule")
        elif rule.role not in roles:
            err("unknown_role", f"kind {k!r} is checked by {rule.role!r}, which is not a role")
        elif by_id[rule.role].capacity_class == "builder" and not (k == "task" and _story_checked_apart(d, by_id)):
            # a task's criteria roll up into its story's, so a task is fine when a non-builder checks stories
            err("checker_is_doer", f"kind {k!r} is checked by {rule.role!r}, a builder role")
    # roles: a spawner per spawnable role, cards, capacity
    for r in d.roles:
        for s in r.may_spawn:
            if s not in roles:
                err("unknown_role", f"role {r.id!r} may spawn {s!r}, which is not a role")
        if r.spawnable and not any(r.id in o.may_spawn for o in d.roles):
            err("role_without_spawner", f"role {r.id!r} is spawnable but no role may spawn it")
        if r.spawnable and not r.card_md and not (r.card and _card_exists(r.card)):
            err("card_missing", f"role {r.id!r} has no card (card_md, or an agent-home card named by `card`)")
        if r.spawnable and r.capacity_class is None and r.max_concurrent is None:
            err("unknown_capacity", f"role {r.id!r} declares neither capacity_class nor max_concurrent")
        if r.max_concurrent is not None and r.max_concurrent < 1:
            err("cap_below_1", f"role {r.id!r} has max_concurrent {r.max_concurrent}")
        if not r.kernel:
            err("kernel_stripped", f"role {r.id!r} turns the kernel preamble and tools off")
        for k in r.may_create:
            if k not in kinds and k != "topic":
                err("unknown_kind", f"role {r.id!r} may create {k!r}, which is not a kind")
    # S14 (c-e9d095f3a3): custom-role permission sets — a bundle, no self-checking, no escalation
    for r in d.roles:
        if r.human:
            continue
        if r.spawnable and not r.bundle:
            err("bundle_missing", f"role {r.id!r} has no tool bundle")
        doing = [w for w, on in (("authors criteria", r.criterion_author),
                                 ("attaches evidence", r.id in d.permissions.get("evidence", [])),
                                 ("is a builder", r.capacity_class == "builder")) if on]
        if r.criterion_checker and doing:
            err("self_check", f"role {r.id!r} verdicts criteria and also {' and '.join(doing)}")
        if r.gate_answerer:
            err("escalation", f"role {r.id!r} is an agent that answers gates (a human's decision)")
        for tool in r.bundle or []:
            need = TOOL_NEEDS.get(tool)
            if need is None:
                continue
            field, code = need
            granted = (bool(getattr(r, field)) if field in RoleDef.model_fields
                       else r.id in d.permissions.get(field, []))
            if not granted and code == "escalation":
                err("escalation", f"role {r.id!r} has tool {tool} without the {field} permission")
            elif not granted and r.id not in _BUILTIN_ROLE_IDS:
                err("unusable_tool", f"role {r.id!r} has tool {tool} but not the {field} permission", "warning")
    # gates: known answerers, at least one precondition
    for g in d.gates:
        for a in g.answerers:
            if a not in roles:
                err("unknown_role", f"gate {g.id!r} is answered by {a!r}, which is not a role")
        if not g.requires:
            err("gate_without_precondition", f"gate {g.id!r} declares no precondition")
        if not any(by_id[a].human for a in g.answerers if a in by_id):
            err("gate_unanswerable", f"gate {g.id!r} is answered by {g.answerers or 'nobody'}, none of them human")
        openers = {r for p in g.requires if p.check == "role_in" and p.phase in ("open", "both")
                   for r in p.params.get("roles") or []}
        if openers & set(g.answerers):
            err("self_approval", f"gate {g.id!r} is opened and answered by {sorted(openers & set(g.answerers))}")
        pres_ok(f"gate {g.id}", g.requires + g.answer_requires)
    # hooks: known names, known params
    for name, h in d.hooks.items():
        if name not in HOOKS:
            err("unknown_hook", f"hook {name!r} is not one of {sorted(HOOKS)}")
            continue
        for key in h.params:
            if key not in HOOKS[name]:
                err("hook_param", f"hook {name!r} has no param {key!r} (params: {sorted(HOOKS[name]) or 'none'})")
    for cap in ("stories_per_epic", "tasks_per_story", "criteria_per_story"):
        if cap not in d.caps:
            err("schema", f"caps.{cap} is missing")
    for cap, v in d.caps.items():
        if v < 1:
            err("cap_below_1", f"caps.{cap} is {v}")
    return errs


def migrate(body: dict[str, Any]) -> dict[str, Any]:
    """Carry a stored definition forward to SCHEMA_VERSION through MIGRATIONS (§4.14(e).4). A body from a
    newer app, or with a gap in the migration chain, is refused (WorkflowError schema_version)."""
    body = copy.deepcopy(body)
    v = int(body.get("schema_version", 1))
    if v > SCHEMA_VERSION:
        raise WorkflowError("schema_version", f"definition schema_version {v} is newer than this app's "
                                              f"{SCHEMA_VERSION}", WHY_FIX["schema_version"][1])
    while v < SCHEMA_VERSION:
        step = MIGRATIONS.get(v)
        if step is None:
            raise WorkflowError("schema_version", f"no migration from schema_version {v}",
                                "the app is missing a forward migration; report it")
        body = step(body)
        v += 1
        body["schema_version"] = v
    return body


def check_compat(registry: WorkflowRegistry) -> dict[str, Any]:
    """The pre-update compatibility check (§4.14(e).4): migrate and validate every PUBLISHED stored
    workflow in a scratch copy (the stored rows are never written). {ok, report: [{ref, ok, problems}]};
    any failure means the update must stop and change nothing."""
    with registry.store._lock:
        rows = registry.store._conn.execute(
            "SELECT id, version, body FROM workflow_defs WHERE published=1 ORDER BY id, version").fetchall()
    report: list[dict[str, Any]] = []
    for wf_id, ver, body in rows:
        scratch = json.loads(body)  # the scratch copy
        problems = [p for p in validate(scratch) if p["severity"] == "error"]
        report.append({"ref": ref(wf_id, ver), "ok": not problems, "problems": problems})
    return {"ok": all(r["ok"] for r in report), "schema_version": SCHEMA_VERSION, "report": report}


def check_db(db_path: Any) -> list[dict[str, Any]]:
    """The update gate's compatibility check (§4.14(e).4, S3 `heronry update`; steer m-f0835edaca).

    Copies the DB at `db_path` to a scratch file (the live DB is opened read-only and never written),
    opens the copy with THIS version's store (its schema migrations run on the copy), then validates
    every published custom workflow version through this version's migrations, kernel and validator,
    and checks every epic pin resolves to a published version. Drafts are not checked (they are not
    runnable and cannot be pinned). One row per version or broken pin:
    {workflow, version, ok, errors: [str]} with each error as '<code>: <what> (why: …; fix: …)'."""
    import sqlite3
    import tempfile
    from pathlib import Path

    from .store import Store

    src = Path(db_path)
    if not src.is_file():
        raise FileNotFoundError(f"no database at {src}")
    with tempfile.TemporaryDirectory(prefix="wf-check-") as tmp:
        dst = Path(tmp) / "copy.db"
        s, d = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True), sqlite3.connect(dst)
        try:
            s.backup(d)
        finally:  # sqlite3's context manager commits but never closes: Windows keeps the file locked
            s.close()
            d.close()
        store = Store(str(dst))
        try:
            reg = WorkflowRegistry(store)
            reg.migrate_all()  # this version's pin migration, on the copy
            rows: list[dict[str, Any]] = []
            with store._lock:
                stored = store._conn.execute(
                    "SELECT id, version, body FROM workflow_defs WHERE published=1 ORDER BY id, version").fetchall()
                pins = store._conn.execute(
                    "SELECT ref, count(*) FROM workflow_pins GROUP BY ref ORDER BY ref").fetchall()
            for wf_id, ver, body in stored:
                problems = [p for p in validate(json.loads(body)) if p["severity"] == "error"]
                rows.append({"workflow": wf_id, "version": ver, "ok": not problems,
                             "errors": [f"{p['code']}: {p['message']} (why: {p['why']}; fix: {p['fix']})"
                                        for p in problems]})
            seen = {(r["workflow"], r["version"]) for r in rows}
            for pin_ref, n in pins:
                try:
                    wf_id, ver = parse_ref(pin_ref)
                    d = reg.get(wf_id, ver)
                    bad = [] if d.published else [f"unpublished: pinned by {n} epic(s) but {pin_ref} is a draft"]
                except (ValueError, WorkflowError) as e:
                    wf_id, ver = pin_ref, 0
                    bad = [f"missing: pinned by {n} epic(s) but {pin_ref} does not load ({e})"]
                if bad or (wf_id, ver) not in seen and wf_id not in BUILTIN_BUILDERS:
                    rows.append({"workflow": wf_id, "version": ver, "ok": not bad, "errors": bad})
            return rows
        finally:
            store._conn.close()


# ----------------------------------------------------------------------------- the store + epic pins


class WorkflowError(Exception):
    def __init__(self, code: str, message: str, hint: str = "", problems: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.code, self.message, self.hint, self.problems = code, message, hint, problems or []


class WorkflowRegistry:
    """Versioned workflow definitions on the board DB plus each epic's pin. The built-in presets are
    built from code (never stored), so Standard always equals today's tables. A stored version is a
    draft until published; a published version is immutable (a change is a new version)."""

    def __init__(self, store: Any):
        self.store = store
        self._lock = threading.RLock()
        self._builtin: dict[str, WorkflowDef] = {}
        self._resolved: dict[str, Workflow] = {}
        with store._lock, store._conn:
            store._conn.execute("CREATE TABLE IF NOT EXISTS workflow_defs (id TEXT, version INTEGER, body TEXT, "
                                "published INTEGER, created_at TEXT, created_by TEXT, PRIMARY KEY(id, version))")
            store._conn.execute("CREATE TABLE IF NOT EXISTS workflow_pins (epic_id TEXT PRIMARY KEY, ref TEXT, "
                                "pinned_at TEXT)")
            # S14: the body of a version as it was when something was duplicated from it, so the diff and the
            # three-way merge keep their base after an app update rebuilds a preset at a new version
            store._conn.execute("CREATE TABLE IF NOT EXISTS workflow_snapshots (ref TEXT PRIMARY KEY, body TEXT)")
            # t-0c16c00424: a published version no epic pins is archived on delete (hidden, restorable)
            cols = {r[1] for r in store._conn.execute("PRAGMA table_info(workflow_defs)").fetchall()}
            if "archived" not in cols:
                store._conn.execute("ALTER TABLE workflow_defs ADD COLUMN archived INTEGER DEFAULT 0")

    # ---- reads
    def builtin(self, wf_id: str) -> WorkflowDef | None:
        if wf_id not in BUILTIN_BUILDERS:
            return None
        with self._lock:
            if wf_id not in self._builtin:
                self._builtin[wf_id] = BUILTIN_BUILDERS[wf_id]()
            return self._builtin[wf_id]

    def _row(self, wf_id: str, version: int | None) -> WorkflowDef | None:
        with self.store._lock:
            if version is None:
                row = self.store._conn.execute("SELECT body FROM workflow_defs WHERE id=? ORDER BY version DESC "
                                               "LIMIT 1", (wf_id,)).fetchone()
            else:
                row = self.store._conn.execute("SELECT body FROM workflow_defs WHERE id=? AND version=?",
                                               (wf_id, version)).fetchone()
        return WorkflowDef.model_validate(migrate(json.loads(row[0]))) if row else None

    def get(self, wf_id: str, version: int | None = None) -> WorkflowDef:
        b = self.builtin(wf_id)
        if b is not None:
            if version not in (None, b.version):
                raise WorkflowError("not_found", f"built-in workflow {wf_id} has only version {b.version}")
            return b
        d = self._row(wf_id, version)
        if d is None:
            raise WorkflowError("not_found", f"no workflow {ref(wf_id, version) if version else wf_id}",
                                "GET /v1/workflows lists them")
        return d

    def latest_published(self, wf_id: str) -> WorkflowDef:
        b = self.builtin(wf_id)
        if b is not None:
            return b
        with self.store._lock:
            row = self.store._conn.execute("SELECT body FROM workflow_defs WHERE id=? AND published=1 "
                                           "AND COALESCE(archived, 0)=0 ORDER BY version DESC LIMIT 1",
                                           (wf_id,)).fetchone()
        if not row:
            raise WorkflowError("not_found", f"workflow {wf_id} has no published version",
                                "publish a version before pinning an epic to it")
        return WorkflowDef.model_validate(migrate(json.loads(row[0])))

    def list(self, *, archived: bool = False) -> list[dict[str, Any]]:
        """Every version with the epics pinned to it (S14: the Design tab's list) and where it came from.
        An archived version is left out unless `archived` (t-0c16c00424); each row says what Delete would do."""
        pins = self.pins()

        def row(d: WorkflowDef, builtin: bool, arch: bool = False) -> dict[str, Any]:
            pinned = pins.get(d.ref, [])
            return {"id": d.id, "version": d.version, "ref": d.ref, "name": d.name, "description": d.description,
                    "builtin": builtin, "published": d.published or builtin, "source": d.source,
                    "pinned_by": pinned, "roles": len(d.roles), "archived": arch,
                    "delete_outcome": _delete_outcome(builtin, d.published, pinned, arch)}

        out = [row(d, True) for d in (self.builtin(k) for k in BUILTIN_BUILDERS) if d]
        with self.store._lock:
            rows = self.store._conn.execute("SELECT body, COALESCE(archived, 0) FROM workflow_defs "
                                            "ORDER BY id, version").fetchall()
        for body, arch in rows:
            if arch and not archived:
                continue
            out.append(row(WorkflowDef.model_validate(migrate(json.loads(body))), False, bool(arch)))
        return out

    def pins(self) -> dict[str, list[str]]:
        """{ref: [epic ids pinned to it]} (the dry-run probe pin excluded)."""
        with self.store._lock:
            rows = self.store._conn.execute("SELECT ref, epic_id FROM workflow_pins ORDER BY pinned_at").fetchall()
        out: dict[str, list[str]] = {}
        for r, e in rows:
            if not str(e).startswith("E-dry-run"):
                out.setdefault(r, []).append(e)
        return out

    def snapshot(self, wf_ref: str) -> WorkflowDef:
        """The version as it was when duplicated (S14): the saved snapshot, else the stored or preset version."""
        wf_id, ver = parse_ref(wf_ref)
        with self.store._lock:
            row = self.store._conn.execute("SELECT body FROM workflow_snapshots WHERE ref=?", (wf_ref,)).fetchone()
        if row:
            return WorkflowDef.model_validate(migrate(json.loads(row[0])))
        return self.get(wf_id, ver)

    def _snap(self, d: WorkflowDef) -> None:
        with self.store._lock, self.store._conn:
            self.store._conn.execute("INSERT OR IGNORE INTO workflow_snapshots (ref, body) VALUES (?,?)",
                                     (d.ref, d.model_dump_json(by_alias=True)))

    def upstream(self, wf_ref: str) -> dict[str, Any]:
        """S14 (§4.14(e).4): has the version this one came from moved on? {source, latest, changed, diff}."""
        from . import workflow_design
        wf_id, ver = parse_ref(wf_ref)
        d = self.get(wf_id, ver)
        none = {"ref": d.ref, "source": d.source, "latest": None, "changed": False, "diff": []}
        if not d.source:
            return none
        sid, sver = parse_ref(d.source)
        if sid == wf_id:
            return none  # a new version of the same workflow: its own history, not an upstream
        try:
            latest = self.latest_published(sid)
        except WorkflowError:
            return none
        changed = latest.version > sver
        return {**none, "latest": latest.ref, "changed": changed,
                "diff": workflow_design.diff(self.snapshot(d.source), latest) if changed else []}

    def merge_upstream(self, wf_ref: str, *, by: str) -> dict[str, Any]:
        """Three-way merge (base = the source as duplicated, theirs = its latest published version, ours =
        this version) into a NEW draft of this workflow whose source is the latest upstream."""
        from . import workflow_design
        up = self.upstream(wf_ref)
        if not up["changed"]:
            raise WorkflowError("conflict", f"{wf_ref} has no upstream change to merge", "nothing to do")
        wf_id, ver = parse_ref(wf_ref)
        ours = self.get(wf_id, ver)
        latest = self.latest_published(parse_ref(up["source"])[0])
        m = workflow_design.merge3(self.snapshot(up["source"]), ours, latest)
        last = self._row(wf_id, None)
        body = {**m["body"], "id": wf_id, "version": (last.version if last else ver) + 1, "source": latest.ref,
                "builtin": False, "published": False}
        d = WorkflowDef.model_validate(body)
        self._snap(latest)
        self._put(d, by)
        return {"draft": dump(d), "conflicts": m["conflicts"], "taken": m["taken"], "problems": validate(d)}

    def resolve(self, wf_ref: str) -> Workflow:
        """A pinned ref → its Workflow (cached: a published version never changes)."""
        with self._lock:
            w = self._resolved.get(wf_ref)
            if w is None:
                wf_id, ver = parse_ref(wf_ref)
                w = Workflow(self.get(wf_id, ver))
                if w.d.published:
                    self._resolved[wf_ref] = w
            return w

    # ---- writes
    def _put(self, d: WorkflowDef, by: str) -> None:
        with self.store._lock, self.store._conn:
            self.store._conn.execute(
                "INSERT OR REPLACE INTO workflow_defs (id, version, body, published, created_at, created_by) "
                "VALUES (?,?,?,?,?,?)", (d.id, d.version, d.model_dump_json(by_alias=True), int(d.published),
                                         datetime.now(UTC).isoformat(), by))

    def save(self, body: dict[str, Any], *, by: str) -> WorkflowDef:
        """Create or replace a DRAFT version. A built-in id or a published version is refused."""
        body = {**body, "builtin": False, "published": False}
        try:
            d = WorkflowDef.model_validate(migrate(body))
        except Exception as e:  # noqa: BLE001
            raise WorkflowError("schema", f"not a workflow definition: {e}") from e
        if d.id in BUILTIN_BUILDERS:
            raise WorkflowError("immutable", f"{d.id} is a built-in workflow and cannot be edited",
                                "duplicate it under a new id, edit the copy, publish it")
        cur = self._row(d.id, d.version)
        if cur is not None and cur.published:
            raise WorkflowError("immutable", f"{d.ref} is published and immutable",
                                f"duplicate it to {d.id}@{d.version + 1} (a new draft version) and edit that")
        self._put(d, by)
        return d

    def duplicate(self, src_ref: str, *, new_id: str | None = None, by: str) -> WorkflowDef:
        """Copy a version into a new draft: `new_id@1`, or the next version of the same id."""
        sid, sver = parse_ref(src_ref)
        src = self.get(sid, sver)
        if new_id and new_id != sid:
            if new_id in BUILTIN_BUILDERS or self._row(new_id, None) is not None:
                raise WorkflowError("conflict", f"workflow id {new_id} already exists", "pick another id")
            wf_id, ver = new_id, 1
        else:
            if sid in BUILTIN_BUILDERS:
                raise WorkflowError("immutable", f"{sid} is built in; duplicate it under a new id")
            last = self._row(sid, None)
            wf_id, ver = sid, (last.version if last else sver) + 1
        d = src.model_copy(deep=True, update={"id": wf_id, "version": ver, "builtin": False, "published": False,
                                              "name": src.name if wf_id == sid else f"{src.name} (copy)",
                                              # a new version of the same id keeps the upstream it tracks
                                              "source": src.source if wf_id == sid and src.source else src.ref})
        self._snap(src)
        self._put(d, by)
        return d

    def publish(self, wf_id: str, version: int, *, by: str) -> WorkflowDef:
        d = self.get(wf_id, version)
        if d.published:
            raise WorkflowError("immutable", f"{d.ref} is already published")
        problems = [p for p in validate(d) if p["severity"] == "error"]
        if problems:
            lines = "; ".join(f"{p['code']}: {p['message']} (why: {p['why']}; fix: {p['fix']})"
                              for p in problems)
            raise WorkflowError("invalid", f"{d.ref} does not validate ({len(problems)} problems): {lines}",
                                "fix each named problem (POST /v1/workflows/validate), then publish", problems)
        # S14 (§4.14(e).3): a synthetic epic must walk the draft to done; a stall blocks Publish
        from . import workflow_design
        stall = workflow_design.dry_run(d)["stall"]
        if stall is not None:
            problem = workflow_design.stall_problem(stall)
            raise WorkflowError("invalid", f"{d.ref} does not publish: {problem['message']}",
                                "run the dry run (POST /v1/workflows/dryrun) and fix the stalled step", [problem])
        d = d.model_copy(update={"published": True})
        self._put(d, by)
        return d

    def delete(self, wf_ref: str, *, by: str) -> dict[str, Any]:
        """t-0c16c00424: an unpublished draft is deleted outright; a published version no epic pins is archived
        (hidden from the list, restorable); a pinned version or a preset is refused."""
        wf_id, ver = parse_ref(wf_ref)
        if wf_id in BUILTIN_BUILDERS:
            raise WorkflowError("immutable", f"{wf_id} is a built-in preset and cannot be deleted",
                                "presets always stay; delete a copy you made instead")
        d = self.get(wf_id, ver)
        pinned = self.pins().get(d.ref, [])
        if pinned:
            raise WorkflowError("conflict", f"{d.ref} is pinned by {len(pinned)} epic"
                                f"{'' if len(pinned) == 1 else 's'}: {', '.join(pinned)}",
                                "an epic keeps the version it was created on; delete it once those epics are gone")
        with self.store._lock, self.store._conn:
            if not d.published:
                self.store._conn.execute("DELETE FROM workflow_defs WHERE id=? AND version=?", (d.id, d.version))
                outcome = "deleted"
            else:
                self.store._conn.execute("UPDATE workflow_defs SET archived=1 WHERE id=? AND version=?",
                                         (d.id, d.version))
                outcome = "archived"
        with self._lock:
            self._resolved.pop(d.ref, None)
        return {"ref": d.ref, "outcome": outcome, "by": by}

    def restore(self, wf_ref: str) -> dict[str, Any]:
        """Bring an archived version back into the list."""
        wf_id, ver = parse_ref(wf_ref)
        d = self.get(wf_id, ver)
        with self.store._lock, self.store._conn:
            n = self.store._conn.execute("UPDATE workflow_defs SET archived=0 WHERE id=? AND version=? AND "
                                         "COALESCE(archived, 0)=1", (d.id, d.version)).rowcount
        if not n:
            raise WorkflowError("conflict", f"{d.ref} is not archived", "only an archived version is restored")
        return {"ref": d.ref, "outcome": "restored"}

    # ---- epic pins
    def pin(self, epic_id: str, wf_ref: str) -> None:
        with self.store._lock, self.store._conn:
            self.store._conn.execute("INSERT OR IGNORE INTO workflow_pins (epic_id, ref, pinned_at) VALUES (?,?,?)",
                                     (epic_id, wf_ref, datetime.now(UTC).isoformat()))

    def pin_of(self, epic_id: str) -> str | None:
        with self.store._lock:
            row = self.store._conn.execute("SELECT ref FROM workflow_pins WHERE epic_id=?", (epic_id,)).fetchone()
        return row[0] if row else None

    def migrate_all(self) -> int:
        """Pin every stored epic that has no pin to Standard@1, in one statement (board open)."""
        with self.store._lock, self.store._conn:
            cur = self.store._conn.execute(
                "INSERT OR IGNORE INTO workflow_pins (epic_id, ref, pinned_at) SELECT id, ?, ? FROM ticket "
                "WHERE kind='epic' AND id NOT IN (SELECT epic_id FROM workflow_pins)",
                (ref(STANDARD_ID, 1), datetime.now(UTC).isoformat()))
            return cur.rowcount or 0

    def pinned_refs(self) -> set[str]:
        with self.store._lock:
            return {r[0] for r in self.store._conn.execute("SELECT DISTINCT ref FROM workflow_pins").fetchall()}

    def migrate_pins(self, epic_ids: list[str]) -> int:
        """Pin every epic that has no pin to Standard@1 (existing epics; idempotent). Returns the count."""
        std = ref(STANDARD_ID, 1)
        n = 0
        for eid in epic_ids:
            if self.pin_of(eid) is None:
                self.pin(eid, std)
                n += 1
        return n


def _delete_outcome(builtin: bool, published: bool, pinned: list[str], archived: bool) -> dict[str, Any]:
    """What DELETE /v1/workflows/<ref> would do, so the Design tab's confirm names it before asking."""
    if builtin:
        return {"action": "refused", "reason": "a built-in preset always stays"}
    if pinned:
        return {"action": "refused", "reason": f"pinned by {len(pinned)} epic{'' if len(pinned) == 1 else 's'}: "
                + ", ".join(pinned)}
    if archived:
        return {"action": "refused", "reason": "already archived; restore it instead"}
    return {"action": "archived" if published else "deleted",
            "reason": "published: hidden from the list, restorable" if published else "an unpublished draft"}


def _applies(p: Precondition, kind: str) -> bool:
    w = p.when
    return not (w and ((w.kinds and kind not in w.kinds) or (w.not_kinds and kind in w.not_kinds)
                       or w.quick_root or w.quick))


_ROLES_FROM = {"checkers": "the checker", "criterion_authors": "a criterion author", "claim": "the assignee"}


def _who(pres: list[Precondition], kind: str) -> str:
    for p in pres:
        if not _applies(p, kind):
            continue
        if p.check == "role_in":
            roles = p.params.get("roles") or [_ROLES_FROM.get(p.params.get("roles_from", ""),
                                                              p.params.get("roles_from", ""))]
            return ", ".join(str(r) for r in roles if r)
        if p.check in ("actor_is_assignee", "assignee_or_claim"):
            return "the assignee"
    return "any seat on it"


def _needs(pres: list[Precondition], kind: str) -> str:
    out = []
    for p in pres:
        if p.check in ("role_in", "actor_is_assignee") or not _applies(p, kind):
            continue
        out.append(p.message.split(":")[0].replace("|", "/") if p.message else p.check)
    return "; ".join(out) or "—"


def lifecycle_md(w: Workflow, kind: str) -> str:
    """The lifecycle of `kind` under this workflow as Markdown: every edge with who takes it and what it
    needs (board-carried edges marked), the gates with their answerers, and the checker. The /epic and
    /ticket skills render their lifecycle section from this, so it never drifts from what the board
    enforces (§4.14(d))."""
    probe = type("T", (), {"kind": kind, "work_type": "feature", "parent_id": None if kind == "epic" else "p"})()
    rule = next((r for r in w.d.checkers if when_matches(r.when, probe, quick=False)), None)
    lines = [f"### {kind} lifecycle — workflow {w.ref}", "",
             "| From | To | Who | Needs |", "|---|---|---|---|"]
    for tr in w.d.transitions:
        carried = tr.auto and not (tr.auto_when and tr.auto_when.kinds and kind not in tr.auto_when.kinds)
        who = "*board*" if carried else _who(tr.requires, kind)
        lines.append(f"| {tr.from_} | {tr.to} | {who} | {_needs(tr.requires, kind)} |")
    lines += ["", "| Gate | Answered by |", "|---|---|"]
    lines += [f"| {g.id} | {', '.join(g.answerers)} |" for g in w.d.gates]
    lines += ["", f"Checks the {kind}'s criteria: **{rule.role if rule else 'nobody'}**. "
              f"Terminal: {', '.join(w.d.terminal)}."]
    return "\n".join(lines)


def dump(d: WorkflowDef) -> dict[str, Any]:
    return json.loads(d.model_dump_json(by_alias=True))


# ----------------------------------------------------------------------------- the update gate's CLI

def workflows_cmd(argv: list[str]) -> int:
    """`heronry workflows check --db <path> [--json]` (S3 registers this as cli.py's `workflows` command;
    also `python -m edp8.workflow check …`): the §4.14(e).4 compatibility check on a scratch copy of the DB
    (the live DB is never written). Exit 0 all ok, 1 any failure, 2 usage error (steer m-f0835edaca)."""
    import argparse
    import sys

    from .brand import CLI_NAME

    ap = argparse.ArgumentParser(prog=f"{CLI_NAME} workflows", exit_on_error=False)
    sub = ap.add_subparsers(dest="action")
    chk = sub.add_parser("check", exit_on_error=False,
                         help="migrate + validate every published workflow and pin in a scratch copy")
    chk.add_argument("--db", required=True, help="the board database (read-only)")
    chk.add_argument("--json", action="store_true", help="print a JSON list of {workflow, version, ok, errors}")
    try:
        args = ap.parse_args(argv)
    except (argparse.ArgumentError, SystemExit) as e:
        print(f"{CLI_NAME} workflows: {e}", file=sys.stderr)
        return 2
    if args.action != "check":
        print(f"usage: {CLI_NAME} workflows check --db <path> [--json]", file=sys.stderr)
        return 2
    try:
        rows = check_db(args.db)
    except FileNotFoundError as e:
        print(f"{CLI_NAME} workflows: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{'ok  ' if r['ok'] else 'FAIL'}  {r['workflow']}@{r['version']}")
            for err in r["errors"]:
                print(f"      {err}")
        print(f"{sum(r['ok'] for r in rows)}/{len(rows)} ok")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":  # python -m edp8.workflow check --db <path> [--json]
    import sys as _sys
    raise SystemExit(workflows_cmd(_sys.argv[1:]))
