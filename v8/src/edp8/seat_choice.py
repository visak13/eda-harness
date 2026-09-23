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
the role's first catalog entry. A GPT id (`gpt-…`) runs on the codex seat (dec-3dc3047782): the
pool is handed `codex/<id>` (SeatChoice.pool_model), which its CompositeSpawner routes to codex
app-server with EDP_CODEX_MODEL=<id>.

CAP: Claude effort is capped fleet-wide at MEDIUM (user ruling 2026-08-04, enforced by the seat
registry). "high" therefore applies only to a Pi/GPT seat; a Claude seat asked for high runs at
medium, and the resolution says so in its `note`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

MODEL_TAG = "seat-model:"
ROLE_MODEL_TAG = "model:"    # model:<role>=<id>, one per role (S-ROLES)
EFFORT_TAG = "seat-effort:"
EFFORTS = ("low", "medium", "high")
CLAUDE = "claude"            # the sentinel seat name: no per-spawn model, the Claude roles column
CLAUDE_EFFORT_CAP = "medium"
CATALOG_KEY = "role_models"  # models.json: {role: [model ids]}, first entry = the role's default


@dataclass(frozen=True)
class SeatChoice:
    model: str | None        # per-spawn model (catalog id, seat name or exact id); None = roles column
    effort: str | None       # low | medium | high (already capped for Claude)
    note: str | None = None  # e.g. "effort high capped to medium (Claude seat)"

    def as_dict(self) -> dict[str, Any]:
        return {"model": self.model, "effort": self.effort, "note": self.note}

    @property
    def pool_model(self) -> str | None:
        """The model as the pool routes it: a bare GPT id goes to the codex seat as `codex/<id>`;
        every other value (Claude id, seat name, openai/… Pi id) passes through unchanged."""
        return f"codex/{self.model}" if is_gpt_id(self.model) else self.model


def is_gpt_id(model: str | None) -> bool:
    """PURE. A bare OpenAI GPT model id (`gpt-6-astra`, `gpt-6-sol`) — one the codex seat runs."""
    return bool(model) and str(model).lower().startswith("gpt-")


def choice_from_tags(tags: Iterable[str] | None) -> tuple[str | None, str | None]:
    """PURE. The old whole-epic (model, effort) recorded on a ticket's tags; (None, None) when absent."""
    model = effort = None
    for t in tags or []:
        if t.startswith(MODEL_TAG):
            model = t[len(MODEL_TAG):].strip() or None
        elif t.startswith(EFFORT_TAG) and "=" not in t:  # `seat-effort:<role>=` is per role
            effort = t[len(EFFORT_TAG):].strip() or None
    return model, effort


def role_models_from_tags(tags: Iterable[str] | None) -> dict[str, str]:
    """PURE. The per-role picks on an epic's tags: `model:<role>=<id>` → {role: id}; last wins."""
    out: dict[str, str] = {}
    for t in tags or []:
        if t.startswith(ROLE_MODEL_TAG):
            role, sep, mid = t[len(ROLE_MODEL_TAG):].partition("=")
            if sep and role.strip() and mid.strip():
                out[role.strip()] = mid.strip()
    return out


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
    """The v8 agent home (models.json lives here): EDP8_HOME, else this checkout's v8/."""
    return Path(os.environ.get("EDP8_HOME", str(Path(__file__).resolve().parents[2])))


def _registry(home: str | os.PathLike | None) -> dict[str, Any]:
    """models.json as a dict; {} on any trouble (the board never depends on edp_contracts)."""
    if not home:
        return {}
    try:
        raw = json.loads((Path(home) / "models.json").read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def catalog(home: str | os.PathLike | None) -> dict[str, list[str]]:
    """The per-role model catalog from models.json `role_models` ({role: [ids]}, first = default).
    Absent or malformed answers {} — a spawn then falls to the pool's role→seat default."""
    table = _registry(home).get(CATALOG_KEY)
    if not isinstance(table, dict):
        return {}
    return {str(r): [str(m) for m in ids if m] for r, ids in table.items()
            if isinstance(ids, list) and any(ids)}


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
    """A model that runs on the Pi harness: an openai/… id, or a models.json seat whose
    harness is `pi`. Any registry trouble answers False — the pool re-resolves at its own seam."""
    if not model:
        return False
    if model.startswith(("openai/", "openai-codex/")):
        return True
    seat = (_registry(agent_home).get("seats") or {}).get(model)
    return isinstance(seat, dict) and seat.get("harness") == "pi"


def _uncapped(model: str | None, home: str | os.PathLike | None) -> bool:
    """A model whose effort may run high: a GPT id, a codex/… id, or a Pi/codex-harness seat."""
    if not model:
        return False
    if is_gpt_id(model) or model.startswith("codex/") or is_pi_seat(model, home):
        return True
    seat = (_registry(home).get("seats") or {}).get(model)
    return isinstance(seat, dict) and seat.get("harness") == "codex"


def resolve(model: str | None, effort: str | None, epic_tags: Iterable[str] | None,
            agent_home: str | os.PathLike | None, *, role: str | None = None) -> SeatChoice:
    """PURE (given the registry). Model: the spawn's explicit `model` wins, else the epic's
    `model:<role>=` tag, else its old `seat-model:` tag ("claude" = no per-spawn model, the pool's
    roles column), else the role's first catalog entry. Effort: explicit, else the epic's
    `seat-effort:<role>=` tag, else its old whole-epic `seat-effort:`;
    outside low/medium/high is dropped; a Claude seat is capped at medium."""
    tags = list(epic_tags or [])
    tag_model, tag_effort = choice_from_tags(tags)
    per_role = role_models_from_tags(tags).get(role) if role else None
    m = (model or per_role or tag_model or "").strip() or None
    if m and m.lower() == CLAUDE:
        m = None
    elif m is None and role:
        m = (catalog(agent_home).get(role) or [None])[0]
    role_effort = role_efforts_from_tags(tags).get(role) if role else None
    e = (effort or role_effort or tag_effort or "").strip().lower() or None
    if e is not None and e not in EFFORTS:
        e = None
    note = None
    if e == "high" and not _uncapped(m, agent_home):
        e = CLAUDE_EFFORT_CAP
        note = "effort high capped to medium (Claude seat; user ruling 2026-08-04)"
    return SeatChoice(model=m, effort=e, note=note)
