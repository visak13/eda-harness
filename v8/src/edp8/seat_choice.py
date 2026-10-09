"""The epic's seat choice — which MODEL and EFFORT every seat of an epic runs on.

Owner ruling 2026-09-17 (m-2d7ef9243d / m-3238155d2e): the owner picks model + effort for an epic
when creating it in the web UI, BEFORE any launch, and creating an epic never forces a spawn.
Every later spawn on that epic (architect, engineer, qa, sme, adversary — the `spawn` MCP tool,
POST /v1/sessions/spawn, and the board's auto-pairing) inherits the choice unless the spawn names
its own model.

STORAGE (least invasive, no schema migration): entries in the EPIC ticket's `tags` list —
    model:<role>=<id>              the per-role pick (S-ROLES), one per role
    seat-model:<claude|astra|…>    the OLD whole-epic pick, still honoured as a fallback: a
                                   models.json SEAT NAME ("claude" = the Claude `roles` column,
                                   i.e. no per-spawn model: the pool resolves role→seat as today)
    seat-effort:<role>=<low|medium|high>  the per-role effort (S-UI), one per role
    seat-effort:<low|medium|high>  the OLD whole-epic effort, still honoured as a fallback
Tags already exist on every ticket, are settable at creation (ticket_create / POST /v1/tickets
`tags`) and editable later (ticket_update `tags`), are indexed for ticket_query(tag=), and are
returned by every ticket read — so a spawn path reads the epic once and has the choice. A ticket
that is not an epic never carries these tags; the choice is resolved from its epic.

PER ROLE (S-ROLES, design-34bf11cc07 §4.1, owner m-bba708e10e): models.json `role_models` is the
per-role catalog (role → [model ids], first = default). Resolution for a spawn of `role`: the
spawn's own model wins, else the epic's `model:<role>=` tag, else the old `seat-model:` tag, else
the role's first catalog entry, else the catalog's `default_model` (a role with no catalog row).
The pool routes by the entry's `harness`, regardless of id spelling.

CAP: Each catalog entry names its effort cap (low, medium or high; never above high: the owner's §6 words). resolve()
clamps the chosen effort to it, and the pool clamps again at /v1/spawn and at launch.

OPTION LISTS AND STORY PICKS (epic-0cec8d1c31 S7, design §4.E):
    model:<role>=<id>@<effort>|<id>@<effort>   an ORDERED list of options for the role; the first is the
                                               default. `@<effort>` is optional; the legacy single
                                               `model:<role>=<id>` is a list of one.
    seat:<role>=<id>@<effort>                  on a STORY: this story's seat of <role> runs on that option.
                                               It names any model of the role's catalog row within its cap
                                               (board check; RC2 F2: the epic's list is not a limit), and is
                                               written by the owner or the epic's architect only.
Precedence for a spawn of a role: the spawn's own arg > the story's `seat:` pick > the role's first option >
the old whole-epic `seat-model:` > the catalog default; the effort follows the same order, and every step is
clamped to the chosen model's cap.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from edp8 import harness, settings
from edp_contracts.roles import is_non_agent, refuse_non_agent
from edp_contracts.seats import EFFORT_LEVELS, catalog_keys, clamp_effort, effort_cap_of

MODEL_TAG = "seat-model:"
ROLE_MODEL_TAG = "model:"    # model:<role>=<id>[@<effort>][|<id>[@<effort>]...], one per role (S-ROLES)
STORY_TAG = "seat:"          # seat:<role>=<id>[@<effort>], on a story (S7)
EFFORT_TAG = "seat-effort:"
OPTION_SEP = "|"
EFFORTS = EFFORT_LEVELS
CLAUDE = "claude"            # the sentinel seat name: no per-spawn model, the Claude roles column
CLAUDE_EFFORT_CAP = "medium"  # a model with no catalog row is capped here
CATALOG_KEY = "role_models"  # models.json: {role: [model ids]}, first entry = the role's default

Option = tuple[str, "str | None"]  # (model id, effort or None)


@dataclass(frozen=True)
class SeatChoice:
    model: str | None        # per-spawn model (catalog id, seat name or exact id); None = roles column
    effort: str | None       # low | medium | high (already capped for Claude)
    note: str | None = None  # e.g. "effort high capped to medium (Claude seat)"

    def as_dict(self) -> dict[str, Any]:
        return {"model": self.model, "effort": self.effort, "note": self.note}

    @property
    def pool_model(self) -> str | None:
        """Model ids are opaque; the pool resolves the harness from catalog metadata."""
        return self.model


def choice_from_tags(tags: Iterable[str] | None) -> tuple[str | None, str | None]:
    """PURE. The old whole-epic (model, effort) recorded on a ticket's tags; (None, None) when absent."""
    model = effort = None
    for t in tags or []:
        if t.startswith(MODEL_TAG):
            model = t[len(MODEL_TAG):].strip() or None
        elif t.startswith(EFFORT_TAG) and "=" not in t:  # `seat-effort:<role>=` is per role
            effort = t[len(EFFORT_TAG):].strip() or None
    return model, effort


def parse_option(token: str) -> tuple[Option, str | None]:
    """PURE. `<id>[@<effort>]` → ((id, effort|None), problem|None). An effort outside low/medium/high keeps
    the id, drops the effort and names the problem, so the board can refuse it with a clear reason."""
    head, sep, tail = token.strip().rpartition("@")
    if not sep:
        return (token.strip(), None), None
    e = tail.strip().lower()
    if e in EFFORTS:
        return (head.strip(), e), None
    return (head.strip(), None), f"effort {tail.strip()!r} is not one of {list(EFFORTS)}"


def format_option(opt: Option) -> str:
    return f"{opt[0]}@{opt[1]}" if opt[1] else opt[0]


def role_options_from_tags(tags: Iterable[str] | None) -> dict[str, list[Option]]:
    """PURE. The per-role OPTION lists on an epic's tags: `model:<role>=<id>@<effort>|<id>@<effort>` →
    {role: [(id, effort|None), ...]}, first = the default; last tag per role wins; empty items dropped."""
    out: dict[str, list[Option]] = {}
    for t in tags or []:
        if t.startswith(ROLE_MODEL_TAG):
            role, sep, rest = t[len(ROLE_MODEL_TAG):].partition("=")
            opts = [parse_option(x)[0] for x in rest.split(OPTION_SEP) if x.strip()]
            opts = [o for o in opts if o[0]]
            if sep and role.strip() and opts:
                out[role.strip()] = opts
    return out


def role_models_from_tags(tags: Iterable[str] | None) -> dict[str, str]:
    """PURE. The per-role DEFAULT model on an epic's tags: the first option of `model:<role>=…` → {role: id}."""
    return {r: opts[0][0] for r, opts in role_options_from_tags(tags).items()}


def story_picks_from_tags(tags: Iterable[str] | None) -> dict[str, Option]:
    """PURE. A story's `seat:<role>=<id>@<effort>` picks → {role: (id, effort|None)}; last wins."""
    out: dict[str, Option] = {}
    for t in tags or []:
        if t.startswith(STORY_TAG):
            role, sep, rest = t[len(STORY_TAG):].partition("=")
            opt = parse_option(rest)[0] if rest.strip() else ("", None)
            if sep and role.strip() and opt[0]:
                out[role.strip()] = opt
    return out


def tags_for_role_options(picks: dict[str, list[Option]] | None) -> list[str]:
    """PURE. The `model:<role>=<id>@<effort>|…` tags that record per-role option lists (the web dialogs)."""
    return [f"{ROLE_MODEL_TAG}{r}={OPTION_SEP.join(format_option(o) for o in opts)}"
            for r, opts in (picks or {}).items() if r and opts]


def tag_for_story_pick(role: str, opt: Option) -> str:
    """PURE. The `seat:<role>=<id>@<effort>` tag that records a story's pick."""
    return f"{STORY_TAG}{role}={format_option(opt)}"


def option_problems(role: str, opts: list[Option], home: str | os.PathLike | None) -> list[str]:
    """Reasons an option list is refused: an id the catalog does not list for the role, an effort outside
    low/medium/high (parse_option names it) or above the model's own cap. [] = fine."""
    out: list[str] = []
    for mid, eff in opts:
        why = unknown_model(role, mid, home)
        if why:
            out.append(why)
        elif eff and clamp_effort(eff, _effort_cap(mid, home))[1]:
            out.append(f"{mid} is capped at {_effort_cap(mid, home)}; {eff!r} is above its cap")
    return out


def story_pick_problem(role: str, pick: Option, epic_tags: Iterable[str] | None,
                       home: str | os.PathLike | None) -> str | None:
    """Why a story's `seat:<role>=` pick is refused, or None. RC2 F2 (owner: "an epic can set a model and effort
    per story"; architect m-1f09a47214): a story may run its role on ANY model of the role's catalog row (or an
    id the epic's own `model:<role>=` list names), at any effort up to that model's cap. The epic's list is the
    role's default and its quick choices, not a limit on a story."""
    mid, eff = pick
    allowed = list(catalog(home).get(role) or []) + [o[0] for o in role_options_from_tags(epic_tags).get(role) or []]
    if not allowed:
        return None  # a role with no catalog row and no epic list: nothing to be one of
    if mid not in allowed:
        return f"{mid!r} is not a {role} model in the catalog: {sorted(set(allowed))}"
    if eff and clamp_effort(eff, _effort_cap(mid, home))[1]:
        return f"{mid} is capped at {_effort_cap(mid, home)}; {eff!r} is above its cap"
    return None


def role_efforts_from_tags(tags: Iterable[str] | None) -> dict[str, str]:
    """PURE. The per-role efforts on an epic's tags: `seat-effort:<role>=<level>` → {role: level};
    last wins; a level outside low/medium/high is dropped."""
    out: dict[str, str] = {}
    for t in tags or []:
        if t.startswith(EFFORT_TAG):
            role, sep, level = t[len(EFFORT_TAG):].partition("=")
            if sep and role.strip() and level.strip().lower() in EFFORTS:
                out[role.strip()] = level.strip().lower()
    return out


def tags_for_role_efforts(picks: dict[str, str] | None) -> list[str]:
    """PURE. The `seat-effort:<role>=<level>` tags that record per-role efforts (the web dialogs)."""
    return [f"{EFFORT_TAG}{r}={e}" for r, e in (picks or {}).items() if r and e]


def tags_for_choice(model: str | None, effort: str | None) -> list[str]:
    """PURE. The old whole-epic tag entries that record a choice."""
    out: list[str] = []
    if model:
        out.append(f"{MODEL_TAG}{model}")
    if effort:
        out.append(f"{EFFORT_TAG}{effort}")
    return out


def tags_for_role_models(picks: dict[str, str] | None) -> list[str]:
    """PURE. The `model:<role>=<id>` tags that record per-role picks (what the web dialog sends)."""
    return [f"{ROLE_MODEL_TAG}{r}={m}" for r, m in (picks or {}).items() if r and m]


def agent_home() -> Path:
    """The seat home; the editable catalog is resolved separately in the data directory."""
    return settings.agent_home()


def _registry(home: str | os.PathLike | None) -> dict[str, Any]:
    """models.json as a dict; {} on any trouble (the board never depends on edp_contracts)."""
    if not home:
        return {}
    try:
        from edp_contracts.seats import config_path
        source = config_path(home)
        if not source.is_file() and Path(home) == settings.agent_home():
            # t-96df382440: no data-dir copy (materialise failed) and no home copy — the shipped catalog,
            # read-only, never an empty one
            from .model_catalog import migrate, shipped_path
            return migrate(json.loads(shipped_path().read_text(encoding="utf-8")))
        raw = json.loads(source.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def catalog(home: str | os.PathLike | None) -> dict[str, list[str]]:
    """The per-role model catalog from models.json `role_models` ({role: [ids]}, first = default).
    Absent or malformed answers {} — a spawn then falls to the pool's role→seat default."""
    reg = _registry(home)
    table = reg.get(CATALOG_KEY)
    if not isinstance(table, dict):
        return {}
    # S4 (§4.11): only models on a selected harness; the adversary falls back to Fable without codex
    return harness.filter_catalog({str(r): [str(m) for m in ids if m] for r, ids in table.items()
                                   if isinstance(ids, list) and any(ids) and not is_non_agent(r)}, reg)


def default_model(home: str | os.PathLike | None) -> str | None:
    """The model a role absent from `role_models` spawns on, custom roles included (owner bug m-549b8adc3a:
    an unlisted role must never launch a harness on its CLI's own default). models.json `default_model`
    when it sits on a selected harness, else the first selected catalog model; None only for no catalog."""
    reg = _registry(home)
    entries = reg.get("models") if isinstance(reg.get("models"), dict) else {}
    picked = harness.selected(reg)
    want = reg.get("default_model")
    if want and harness.harness_of(str(want), entries) in picked:
        return str(want)
    for ids in catalog(home).values():
        return ids[0]
    return next((m for m in entries if harness.harness_of(m, entries) in picked), None)


def seat_names(home: str | os.PathLike | None) -> set[str]:
    """The legacy seat names in models.json `seats` (e.g. "astra", "builder") — a spawn may still name one."""
    seats = _registry(home).get("seats")
    return {str(k) for k in seats} if isinstance(seats, dict) else set()


def unknown_model(role: str | None, model: str | None, home: str | os.PathLike | None) -> str | None:
    """S-ADV finding 10 (architect m-68e58f99d4): a `model:<role>=<id>` pick and a spawn's model must name
    an id in that role's catalog (GET /v1/models) or a legacy seat name; the reason with the catalog
    listed when they do not, None when the choice is fine or the role has no catalog."""
    if not model or not role:
        return None
    if str(model).lower() == CLAUDE:
        return None
    allowed = catalog(home).get(role) or []
    if not allowed:
        return None
    if model in allowed or model in seat_names(home):
        return None
    return f"{model!r} is not a {role} model; the catalog for {role} is {allowed}"


def role_options_for(tags: Iterable[str] | None,
                     home: str | os.PathLike | None) -> dict[str, list[dict[str, str | None]]]:
    """{role: [{model, effort}, ...]} each catalog role's option list as the Models tab shows it: the epic's
    `model:<role>=` list when it has one, else the role's catalog models (effort None = the role's own
    effort). The first item is what a spawn of the role runs on."""
    listed = role_options_from_tags(tags)
    out: dict[str, list[dict[str, str | None]]] = {}
    for r, ids in catalog(home).items():
        opts = listed.get(r) or [(m, None) for m in ids]
        out[r] = [{"model": m, "effort": e} for m, e in opts]
    return out


def role_models_for(tags: Iterable[str] | None, home: str | os.PathLike | None) -> dict[str, str | None]:
    """{role: model} each catalog role of an epic runs on (resolve() with no spawn-named model).
    The Epic page shows it; None = the pool's roles column (an old `seat-model:claude` epic)."""
    tags = list(tags or [])
    return {r: resolve(None, None, tags, home, role=r).model for r in catalog(home)}


def role_efforts_for(tags: Iterable[str] | None, home: str | os.PathLike | None) -> dict[str, str | None]:
    """{role: effort} each catalog role of an epic runs at (resolve() with no spawn-named effort,
    so already capped for a Claude seat). The Models dialog shows it; None = the seat's own default."""
    tags = list(tags or [])
    return {r: resolve(None, None, tags, home, role=r).effort for r in catalog(home)}


def is_pi_seat(model: str | None, agent_home: str | os.PathLike | None) -> bool:
    """True only when the catalog entry or legacy seat explicitly names Pi."""
    if not model:
        return False
    reg = _registry(agent_home)
    return (harness.harness_of(model, reg.get("models")) == "pi" or
            isinstance((reg.get("seats") or {}).get(model), dict) and
            (reg.get("seats") or {})[model].get("harness") == "pi")


def _effort_cap(model: str | None, home: str | os.PathLike | None) -> str:
    """Read the effort cap from data, not the model name."""
    reg = _registry(home)
    row = next((r for mid in catalog_keys(model or "") for r in ((reg.get("models") or {}).get(mid),
                                                               (reg.get("seats") or {}).get(mid))
                if isinstance(r, dict)), None)
    if not isinstance(row, dict):
        return CLAUDE_EFFORT_CAP
    return effort_cap_of(row)


def resolve(model: str | None, effort: str | None, epic_tags: Iterable[str] | None,
            agent_home: str | os.PathLike | None, *, role: str | None = None,
            story_tags: Iterable[str] | None = None) -> SeatChoice:
    """PURE (given the registry). Model: the spawn's explicit `model` wins, else the story's `seat:<role>=`
    pick (`story_tags`), else the FIRST option of the epic's `model:<role>=` list, else its old
    `seat-model:` tag ("claude" = no per-spawn model, the pool's roles column), else the role's first
    catalog entry, else the catalog default. Effort: explicit, else the story pick's, else the chosen
    option's, else the epic's `seat-effort:<role>=` tag, else its old whole-epic `seat-effort:`; the story
    and option efforts apply only to the model they name. Outside low/medium/high is dropped; the result
    is clamped to the chosen model's catalog cap (never above high). A person's role has no seat model:
    NonAgentRole (owner m-da9a2ae62f)."""
    if role:
        refuse_non_agent(role)
    tags = list(epic_tags or [])
    tag_model, tag_effort = choice_from_tags(tags)
    options = role_options_from_tags(tags).get(role) if role else None
    story = story_picks_from_tags(story_tags).get(role) if role else None
    m = (model or (story[0] if story else None) or (options[0][0] if options else None) or tag_model or "").strip() or None
    if m and m.lower() == CLAUDE:
        m = None
    elif m is None and role:
        m = (catalog(agent_home).get(role) or [None])[0] or default_model(agent_home)
    pick_effort = story[1] if story and story[0] == m else None
    option_effort = next((o[1] for o in options or [] if o[0] == m and o[1]), None)
    role_effort = role_efforts_from_tags(tags).get(role) if role else None
    e, _ = clamp_effort(effort or pick_effort or option_effort or role_effort or tag_effort, "high")
    capped, note = clamp_effort(e, _effort_cap(m, agent_home))
    return SeatChoice(model=m, effort=capped, note=note)
