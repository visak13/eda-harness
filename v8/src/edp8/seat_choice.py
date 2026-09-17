"""The epic's seat choice — which MODEL and EFFORT every seat of an epic runs on.

Owner ruling 2026-09-17 (m-2d7ef9243d / m-3238155d2e): the owner picks model + effort for an epic
when creating it in the web UI, BEFORE any launch, and creating an epic never forces a spawn.
Every later spawn on that epic (architect, engineer, qa, reviewer, sme, adversary — the `spawn`
MCP tool, POST /v1/sessions/spawn, and the board's auto-pairing) inherits the choice unless the
spawn names its own model.

STORAGE (least invasive, no schema migration): two entries in the EPIC ticket's `tags` list —
    seat-model:<claude|astra|…>    a models.json SEAT NAME ("claude" = the Claude `roles` column,
                                   i.e. no per-spawn model: the pool resolves role→seat as today)
    seat-effort:<low|medium|high>
Tags already exist on every ticket, are settable at creation (ticket_create / POST /v1/tickets
`tags`) and editable later (ticket_update `tags`), are indexed for ticket_query(tag=), and are
returned by every ticket read — so a spawn path reads the epic once and has the choice. A ticket
that is not an epic never carries these tags; the choice is resolved from its epic.

CAP: Claude effort is capped fleet-wide at MEDIUM (user ruling 2026-08-04, enforced by the seat
registry). "high" therefore applies only to a Pi/GPT seat (astra); a Claude seat asked for high
runs at medium, and the resolution says so in its `note`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

MODEL_TAG = "seat-model:"
EFFORT_TAG = "seat-effort:"
EFFORTS = ("low", "medium", "high")
CLAUDE = "claude"            # the sentinel seat name: no per-spawn model, the Claude roles column
CLAUDE_EFFORT_CAP = "medium"


@dataclass(frozen=True)
class SeatChoice:
    model: str | None        # per-spawn model (seat name or exact id); None = Claude roles column
    effort: str | None       # low | medium | high (already capped for Claude)
    note: str | None = None  # e.g. "effort high capped to medium (Claude seat)"

    def as_dict(self) -> dict[str, Any]:
        return {"model": self.model, "effort": self.effort, "note": self.note}


def choice_from_tags(tags: Iterable[str] | None) -> tuple[str | None, str | None]:
    """PURE. The (model, effort) recorded on a ticket's tags; (None, None) when absent."""
    model = effort = None
    for t in tags or []:
        if t.startswith(MODEL_TAG):
            model = t[len(MODEL_TAG):].strip() or None
        elif t.startswith(EFFORT_TAG):
            effort = t[len(EFFORT_TAG):].strip() or None
    return model, effort


def tags_for_choice(model: str | None, effort: str | None) -> list[str]:
    """PURE. The tag entries that record a choice (what the web dialog sends)."""
    out: list[str] = []
    if model:
        out.append(f"{MODEL_TAG}{model}")
    if effort:
        out.append(f"{EFFORT_TAG}{effort}")
    return out


def agent_home() -> Path:
    """The v8 agent home (models.json lives here): EDP8_HOME, else this checkout's v8/."""
    return Path(os.environ.get("EDP8_HOME", str(Path(__file__).resolve().parents[2])))


def is_pi_seat(model: str | None, agent_home: str | os.PathLike | None) -> bool:
    """A model that runs on the Pi harness: an openai/… id, or a models.json seat whose
    harness is `pi`. Reads models.json directly (the board does not depend on edp_contracts);
    any registry trouble answers False — the pool re-resolves at its own seam."""
    if not model:
        return False
    if model.startswith(("openai/", "openai-codex/")):
        return True
    if not agent_home:
        return False
    f = Path(agent_home) / "models.json"
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
        seat = (raw.get("seats") or {}).get(model) or {}
        return seat.get("harness") == "pi"
    except (OSError, ValueError, AttributeError):
        return False


def resolve(model: str | None, effort: str | None, epic_tags: Iterable[str] | None,
            agent_home: str | os.PathLike | None) -> SeatChoice:
    """PURE (given the registry). The spawn's explicit `model`/`effort` win; a missing one comes
    from the epic's tags; "claude" (or nothing) means no per-spawn model. Effort outside
    low/medium/high is dropped; a Claude seat is capped at medium."""
    tag_model, tag_effort = choice_from_tags(epic_tags)
    m = (model or tag_model or "").strip() or None
    if m and m.lower() == CLAUDE:
        m = None
    e = (effort or tag_effort or "").strip().lower() or None
    if e is not None and e not in EFFORTS:
        e = None
    note = None
    if e == "high" and not is_pi_seat(m, agent_home):
        e = CLAUDE_EFFORT_CAP
        note = "effort high capped to medium (Claude seat; user ruling 2026-08-04)"
    return SeatChoice(model=m, effort=e, note=note)
