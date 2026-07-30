"""North-star store (DESIGN-v6 W1 / W1.1).

The **north star** is the per-recipe anchor that keeps a long, evolving recipe
honest about *what the user actually asked for* while its shape drifts:

- `user_goal_verbatim` — the user's words, **immutable**. It is sourced from
  the recipe at creation and can NEVER be patched to a different value: the
  store `update` raises a `NorthStarImmutable` guard (mirroring the
  "immutable history — hard block, no override" pattern the object surface
  already uses for closed steps/plans). The record_context tool renders that
  guard as a `_precondition` refusal.
- `current_shape` — a short label for the recipe's *current* approach; it may
  change as the recipe evolves.
- `active_constraints` — an **auto-derived, read-only** projection computed
  from the recipe's ACTIVE `Decision.constraint` / `RejectedOption.constraint`
  (see `derive_active_constraints`). It is NEVER hand-written and NEVER
  persisted as authoritative state — it is recomputed from the live recipe
  every time the north star is read/rendered, so it cannot go stale or be
  forged.
- `evolution_log` — append-only trail of shape changes; each entry's text is
  capped at `EVOLUTION_ENTRY_MAX` (400) chars at append time.

Storage: `north_star.json` (+ a rendered `north_star.md`) live INSIDE the
recipe dir, alongside `recipe.json` — the store shares the `.recipes` root
with `RecipeStore` and keys by `recipe_id`.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .atomic import write_atomic

# Append-time cap for one evolution_log entry (DESIGN-v6 W1). Kept here as
# data, next to the schema it bounds.
EVOLUTION_ENTRY_MAX = 400


class NorthStarImmutable(Exception):
    """A patch tried to change `user_goal_verbatim`. Hard block, no override —
    the north star's whole point is that the user's words don't drift."""


class EvolutionEntry(BaseModel):
    """One append-only shape-evolution note. `text` is capped at append time
    (in `NorthStar.append_evolution`), NOT by a schema validator — a legacy
    entry must always deserialize back unchanged (byte-identity discipline)."""

    model_config = ConfigDict(extra="forbid")
    at: datetime
    text: str
    by: str = ""


class ActiveConstraint(BaseModel):
    """One entry of the auto-derived `active_constraints` view. Mirrors the
    recipe's `Constraint` plus the source pointer it was derived from — so a
    reader can trace each active constraint back to its decision/ban."""

    model_config = ConfigDict(extra="forbid")
    source: Literal["decision", "rejected_option"]
    source_id: str
    match: str
    match_kind: str
    applies_to: list[str] = Field(default_factory=list)
    message: str = ""


class NorthStar(BaseModel):
    """The persisted north-star state. NOTE: `active_constraints` is NOT a
    field here — it is derived at read time (`derive_active_constraints`) so it
    can never be hand-written or persisted stale. `user_goal_verbatim` is
    immutable (enforced by `NorthStarStore.update`)."""

    model_config = ConfigDict(extra="forbid")
    recipe_id: str = Field(min_length=1)
    user_goal_verbatim: str = Field(min_length=1)  # IMMUTABLE post-creation
    current_shape: str = ""
    evolution_log: list[EvolutionEntry] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    def append_evolution(self, text: str, by: str, at: datetime) -> None:
        """Append one evolution entry, capping the text at EVOLUTION_ENTRY_MAX
        chars. Append-only: existing entries are never rewritten."""
        capped = (text or "").strip()
        if len(capped) > EVOLUTION_ENTRY_MAX:
            capped = capped[:EVOLUTION_ENTRY_MAX].rstrip() + "…"
        self.evolution_log.append(EvolutionEntry(at=at, text=capped, by=by))
        self.updated_at = at


def derive_active_constraints(recipe) -> list[ActiveConstraint]:
    """Auto-derive the read-only `active_constraints` view from a live recipe:
    every ACTIVE `Decision.constraint` and every `RejectedOption.constraint`.
    Superseded decisions are skipped (they left the active set — that is the
    point of superseding them). NEVER hand-written; always computed here."""
    out: list[ActiveConstraint] = []
    ctx = getattr(recipe, "context", None)
    if ctx is None:
        return out
    for d in getattr(ctx, "decisions", []):
        c = getattr(d, "constraint", None)
        if c is None:
            continue
        if getattr(d, "status", "active") != "active":
            continue
        out.append(ActiveConstraint(
            source="decision", source_id=d.id, match=c.match,
            match_kind=c.match_kind, applies_to=list(c.applies_to),
            message=c.message,
        ))
    for x in getattr(ctx, "rejected_options", []):
        c = getattr(x, "constraint", None)
        if c is None:
            continue
        out.append(ActiveConstraint(
            source="rejected_option", source_id=x.id, match=c.match,
            match_kind=c.match_kind, applies_to=list(c.applies_to),
            message=c.message,
        ))
    return out


def render_north_star_md(ns: NorthStar,
                         active: list[ActiveConstraint]) -> str:
    """Human-readable `north_star.md`. `active` is the derived view (passed in
    so the .md and the read_object view can never disagree)."""
    lines = [
        f"# North star — {ns.recipe_id}",
        "",
        "## User goal (verbatim — immutable)",
        "",
        f"> {ns.user_goal_verbatim}",
        "",
        f"## Current shape",
        "",
        ns.current_shape or "_(not yet set)_",
        "",
        "## Active constraints (auto-derived — never hand-written)",
        "",
    ]
    if active:
        for c in active:
            msg = f" — {c.message}" if c.message else ""
            lines.append(
                f"- `[{c.source}:{c.source_id}]` {c.match_kind} "
                f"`{c.match}` on {c.applies_to or 'any'}{msg}")
    else:
        lines.append("_(none active)_")
    lines += ["", "## Evolution log (append-only)", ""]
    if ns.evolution_log:
        for e in ns.evolution_log:
            lines.append(f"- {e.at.isoformat()} ({e.by or '?'}): {e.text}")
    else:
        lines.append("_(no entries)_")
    lines.append("")
    return "\n".join(lines)


class NorthStarStore:
    """Per-recipe north-star load/save, keyed by recipe_id. Shares the
    `.recipes` root with `RecipeStore` — the north star lives in the recipe
    dir (`<root>/<recipe_id>/north_star.json` + `north_star.md`)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _dir(self, rid: str) -> Path:
        return self.root / rid

    def _file(self, rid: str) -> Path:
        return self._dir(rid) / "north_star.json"

    def _md_file(self, rid: str) -> Path:
        return self._dir(rid) / "north_star.md"

    def exists(self, rid: str) -> bool:
        return self._file(rid).exists()

    def load(self, rid: str) -> NorthStar:
        data = self._file(rid).read_text(encoding="utf-8")
        return NorthStar.model_validate(json.loads(data))

    def save(self, ns: NorthStar,
             active: list[ActiveConstraint] | None = None) -> None:
        """Atomically write north_star.json + the rendered north_star.md,
        enforcing the immutable-goal guard FIRST: if a north star already
        exists for this recipe and the incoming `user_goal_verbatim` differs,
        refuse (NorthStarImmutable) — the single persist path always guards, so
        the user's words can never drift. Mirrors the 'immutable history — hard
        block, no override' pattern.

        `active` (the derived read-only view) is rendered into the .md; pass the
        freshly derived list so the .md never carries stale/hand-written
        constraints."""
        if self.exists(ns.recipe_id):
            existing = self.load(ns.recipe_id)
            if existing.user_goal_verbatim != ns.user_goal_verbatim:
                raise NorthStarImmutable(
                    f"north_star {ns.recipe_id!r}: user_goal_verbatim is "
                    "immutable — it may never be patched to a different value. "
                    "Hard block, no override.")
        write_atomic(self._file(ns.recipe_id),
                     json.dumps(ns.model_dump(mode="json"), indent=2))
        write_atomic(self._md_file(ns.recipe_id),
                     render_north_star_md(ns, active or []))
