"""The seat registry — one file binds every seat to an exact model (v7 §2.4b).

WHY. Model choice is volatile by nature: the right mix depends on the vendor
lineup of the month (user rulings 2026-08-04: Sonnet 5 is decent; Opus 5 is
verbose/agentic rather than deterministic — avoided by default; Fable is the
judgment tier today; effort above MEDIUM is waste on Claude models). So the
binding lives in ONE data file — `models.json` at the agent home — and
remixing the whole fleet is editing that file and passing `doctor`. No code
edit, no prose convention, no per-guide model names.

RULES ENFORCED BY THE VALIDATOR (not by convention):
  * EXACT pinned model ids, never aliases (existing MODEL_TIERS doctrine).
  * Claude effort is capped at MEDIUM fleet-wide (user ruling): an entry
    asking for high/xhigh is a config ERROR, loudly, at stack start.
  * auto_compact must sit BELOW the context window (a planned compact at a
    turn boundary beats an unplanned one mid-work).
  * Every role must resolve to a declared seat; an unknown seat is an error
    at load, not a silent host-default at spawn.

Consumed by BOTH sides of the spawn seam: the engine resolves role→seat→model
for spawn requests; the pool stamps per-seat env (auto-compact window) in
build_env. Loader is read-at-call (no import-time IO); `EDP_MODELS_CONFIG`
overrides the path.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

_CONFIG_ENV = "EDP_MODELS_CONFIG"

#: The fleet-wide Claude effort cap (user ruling 2026-08-04).
ALLOWED_EFFORT = ("low", "medium")


class SeatsError(ValueError):
    """A registry problem the operator must fix — always raised loudly at
    load/validate time, never degraded to a silent default at spawn time."""


@dataclass(frozen=True)
class Seat:
    name: str
    model: str                  # exact pinned id
    effort: str = "medium"
    context_window: int = 1_000_000
    auto_compact: int = 350_000
    # v7 §2.8 hard output cap (user ruling: only neuron output is read, and
    # only at gates — everything else is written for no reader). Stamped as
    # CLAUDE_CODE_MAX_OUTPUT_TOKENS at spawn; None = don't stamp (legacy).
    max_output: int | None = None
    # epic-6a8a6020fd (owner m-96cbd61919/m-e6ef892737, 2026-09-14): non-Claude seats carry the
    # harness that runs them and its thinking level; Claude seats leave both None.
    harness: str | None = None
    thinking: str | None = None


def config_path(agent_home: str | os.PathLike) -> Path:
    override = os.environ.get(_CONFIG_ENV, "").strip()
    if override:
        return Path(override)
    return Path(agent_home) / "models.json"


def parse(raw: dict) -> tuple[dict[str, Seat], dict[str, str]]:
    """PURE. raw = {"seats": {name: {model, effort?, context_window?,
    auto_compact?}}, "roles": {role: seat_name}}. Hard validation."""
    seats: dict[str, Seat] = {}
    for name, row in (raw.get("seats") or {}).items():
        if not isinstance(row, dict) or not row.get("model"):
            raise SeatsError(f"seat {name!r}: needs an exact 'model' id")
        model = str(row["model"]).strip()
        if "latest" in model or model.endswith("-*"):
            raise SeatsError(
                f"seat {name!r}: model {model!r} looks like an alias — pin "
                f"the EXACT id (doctrine: never date-suffixed aliases, never "
                f"'latest'); remixing later is editing this file.")
        effort = str(row.get("effort", "medium"))
        if effort not in ALLOWED_EFFORT:
            raise SeatsError(
                f"seat {name!r}: effort {effort!r} exceeds the fleet-wide "
                f"MEDIUM cap (user ruling 2026-08-04: higher is waste on "
                f"Claude models). Allowed: {ALLOWED_EFFORT}.")
        cw = int(row.get("context_window", 1_000_000))
        ac = int(row.get("auto_compact", 350_000))
        if ac >= cw:
            raise SeatsError(
                f"seat {name!r}: auto_compact ({ac}) must sit BELOW the "
                f"context window ({cw}) — quality degrades before the limit "
                f"and a planned compact beats an unplanned one.")
        mo = row.get("max_output")
        if mo is not None:
            mo = int(mo)
            if mo < 1000:
                raise SeatsError(
                    f"seat {name!r}: max_output {mo} is below 1000 tokens — "
                    f"a cap that small breaks tool-heavy turns; raise it or "
                    f"omit it.")
        seats[name] = Seat(name=name, model=model, effort=effort,
                           context_window=cw, auto_compact=ac,
                           max_output=mo,
                           harness=(str(row["harness"]) if row.get("harness") else None),
                           thinking=(str(row["thinking"]) if row.get("thinking") else None))
    roles: dict[str, str] = {}
    for role, seat in (raw.get("roles") or {}).items():
        if seat not in seats:
            raise SeatsError(
                f"role {role!r} maps to unknown seat {seat!r} "
                f"(declared: {sorted(seats)})")
        roles[role] = seat
    # optional harness columns ("roles_openai", "roles_pi", …) are validated the same way; they are
    # OPTIONS next to the Claude column, never a replacement (owner m-e6ef892737)
    for col, table in raw.items():
        if col.startswith("roles_") and isinstance(table, dict):
            for role, seat in table.items():
                if seat not in seats:
                    raise SeatsError(
                        f"{col}: role {role!r} maps to unknown seat {seat!r} "
                        f"(declared: {sorted(seats)})")
    return seats, roles


def load(agent_home: str | os.PathLike
         ) -> tuple[dict[str, Seat], dict[str, str]] | None:
    """Load + validate, or None when no models.json exists (staged rollout:
    absent registry = full legacy MODEL_TIERS behavior). A PRESENT but
    invalid registry raises — misconfiguration is never silently ignored."""
    f = config_path(agent_home)
    if not f.is_file():
        return None
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SeatsError(f"models.json at {f} unreadable: {e}") from e
    return parse(raw)


def seat_for_role(agent_home: str | os.PathLike, role: str,
                  column: str = "roles") -> Seat | None:
    """The seat bound to `role`, or None when no registry / unmapped role
    (both = legacy behavior; an unmapped role is NOT an error so partial
    adoption works — map roles as their boot docs land).
    `column` selects an alternative role table: "roles" (Claude, default) or a
    harness column such as "roles_openai" — an OPTION, so an unmapped role in a
    harness column is None (the caller falls back), never the Claude seat."""
    f = config_path(agent_home)
    if not f.is_file():
        return None
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SeatsError(f"models.json at {f} unreadable: {e}") from e
    seats, roles = parse(raw)
    table = roles if column == "roles" else (raw.get(column) or {})
    name = table.get(role)
    return seats.get(name) if name else None
