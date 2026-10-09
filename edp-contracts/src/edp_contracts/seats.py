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
  * Effort is capped at HIGH fleet-wide (owner §6 words, "max effort high"): an entry asking for
    xhigh/max is a config ERROR, loudly, at stack start.
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

from . import settings

_CONFIG_ENV = "EDP_MODELS_CONFIG"

#: Every effort a seat may be given, lowest first. No seat runs above `high` (owner §6 words "max effort high", epic-0cec8d1c31):
#: Claude's own xhigh/max levels are never passed.
EFFORT_LEVELS = ("low", "medium", "high")
#: What a seat runs at when nothing names an effort; clamped to the model's cap like any other.
DEFAULT_EFFORT = "medium"
#: Claude seats and harness seats share one ceiling now (the owner's §6 words, "max effort high", lifted the old Claude-only medium cap).
ALLOWED_EFFORT = EFFORT_LEVELS
HARNESS_EFFORT = EFFORT_LEVELS


#: Claude Code runs a model's 1M window only when the id carries this suffix; without it the window is ~200K
#: whatever the catalog row says (les-fc5068b78a), so auto_compact above 200K never fires in time.
ONE_M_SUFFIX = "[1m]"
ONE_M_WINDOW = 1_000_000
CLAUDE_DEFAULT_WINDOW = 200_000


def catalog_keys(model: str) -> list[str]:
    """The catalog keys a launch id may name: itself, then without the `[1m]` the launcher appends (qa
    m-1b272db80b: `claude-opus-5-5[1m]` is the `claude-opus-5-5` row). A row keyed with the suffix still wins."""
    if model.lower().endswith(ONE_M_SUFFIX):
        return [model, model[:-len(ONE_M_SUFFIX)]]
    return [model]


def wants_one_m(model: str | None, row: dict | None) -> bool:
    """A Claude row whose `context_window` is at least 1M: the launcher appends `[1m]` to its id."""
    return (isinstance(row, dict) and row.get("harness", "claude") == "claude"
            and isinstance(row.get("context_window"), int) and row["context_window"] >= ONE_M_WINDOW)


def window_problems(models: dict) -> list[dict]:
    """PURE. What the doctor warns about in a catalog's Claude rows, as {model, code, what, fix}:
    `compact_above_window` — auto_compact above the window the seat really gets (a row that will not be
    launched as 1M has Claude's ~200K, whatever its context_window says), and `one_m_without_window` — an id
    that names `[1m]` on a row whose context_window is under 1M."""
    out: list[dict] = []
    for mid, row in (models or {}).items():
        if not isinstance(row, dict) or row.get("harness", "claude") != "claude":
            continue
        window = row.get("context_window") if isinstance(row.get("context_window"), int) else None
        compact = row.get("auto_compact") if isinstance(row.get("auto_compact"), int) else None
        named_1m = str(mid).lower().endswith(ONE_M_SUFFIX)
        if named_1m and (window or 0) < ONE_M_WINDOW:
            out.append({"model": mid, "code": "one_m_without_window",
                        "what": f"{mid} asks for the 1M window but its context_window is {window}",
                        "fix": f"set context_window to {ONE_M_WINDOW} on {mid}, or drop the {ONE_M_SUFFIX} suffix"})
            continue
        real = ONE_M_WINDOW if (named_1m or wants_one_m(mid, row)) else CLAUDE_DEFAULT_WINDOW
        if compact is not None and compact > real:
            out.append({"model": mid, "code": "compact_above_window",
                        "what": f"{mid} compacts at {compact} tokens but its real window is {real}, so it hits "
                                f"the limit before it compacts",
                        "fix": f"lower auto_compact on {mid} below {real}, or give it a 1M context_window"})
    return out


def effort_cap_of(row: dict | None) -> str:
    """The highest effort a catalog row (or legacy seat) allows: its `effort_cap`, else `high` for a
    Pi/Codex row and `medium` for anything else. Unknown or out-of-range caps fall to `medium`."""
    if not isinstance(row, dict):
        return DEFAULT_EFFORT
    cap = str(row.get("effort_cap") or ("high" if row.get("harness") in ("pi", "codex") else DEFAULT_EFFORT))
    return cap if cap in EFFORT_LEVELS else DEFAULT_EFFORT


def clamp_effort(effort: str | None, cap: str) -> tuple[str | None, str | None]:
    """PURE. (effort, note): `effort` lower-cased; a value outside low/medium/high is dropped (None); one
    above `cap` is lowered to it with a note. The one clamp the board and the pool both use."""
    e = (effort or "").strip().lower() or None
    if e not in EFFORT_LEVELS:
        return None, None
    if cap in EFFORT_LEVELS and EFFORT_LEVELS.index(e) > EFFORT_LEVELS.index(cap):
        return cap, f"effort {e} capped to {cap} (catalog entry cap)"
    return e, None


#: the per-harness env vars that carry an effort level into a codex or Pi seat (S13 F4)
HARNESS_EFFORT_VARS = ("EDP_SEAT_EFFORT", "EDP_CODEX_EFFORT", "EDP_PI_THINKING")
_ABOVE_HIGH = ("xhigh", "max")


def cap_env_effort(env: dict, cap: str) -> list[str]:
    """S13 F4: lower every effort var in `env` (HARNESS_EFFORT_VARS) that is above `cap`, in place, whatever set
    it (the spawn, a harness default, a pass-through env value). A level below the ladder (e.g. `minimal`) is
    left as is. Returns a note per lowered var."""
    notes = []
    for var in HARNESS_EFFORT_VARS:
        v = str(env.get(var) or "").strip().lower()
        if not v:
            continue
        above = v in _ABOVE_HIGH or (v in EFFORT_LEVELS and cap in EFFORT_LEVELS
                                     and EFFORT_LEVELS.index(v) > EFFORT_LEVELS.index(cap))
        if above:
            env[var] = cap
            notes.append(f"{var} {v} capped to {cap} (catalog entry cap)")
    return notes


def launch_effort(agent_home: str | os.PathLike | None, model: str | None,
                  effort: str | None) -> tuple[str, str | None]:
    """The effort a Claude seat launches at, never above its model's catalog cap: the requested one, else
    DEFAULT_EFFORT, clamped. (effort, note). An unknown model (no catalog row) is capped at medium."""
    row = model_entry(agent_home, model) if agent_home and model else None
    clamped, note = clamp_effort(effort or DEFAULT_EFFORT, effort_cap_of(row))
    return clamped or DEFAULT_EFFORT, note


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
    override = settings.get(_CONFIG_ENV)
    if override:
        return override
    catalog = settings.data_dir() / "models.json"
    home = Path(agent_home)
    return catalog if home == settings.agent_home() and catalog.is_file() else home / "models.json"


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
        harness = str(row["harness"]) if row.get("harness") else None
        if effort not in EFFORT_LEVELS:
            raise SeatsError(
                f"seat {name!r}: effort {effort!r} is above the HIGH cap "
                f"(the owner's §6 words: no seat runs above high). Allowed: {EFFORT_LEVELS}.")
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
                           harness=harness,
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


def model_entry(agent_home: str | os.PathLike, model: str | None) -> dict | None:
    """Look up an opaque model id or legacy seat name without inferring from its spelling."""
    if not model:
        return None
    f = config_path(agent_home)
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for mid in catalog_keys(model):
        for key in ("models", "seats"):
            row = (raw.get(key) or {}).get(mid)
            if isinstance(row, dict):
                return row
    return None


def catalog_model_for(agent_home: str | os.PathLike, role: str | None) -> str | None:
    """S12: the role's default catalog model (`role_models[role][0]`), or with role=None / an unlisted
    role the catalog's `default_model`; None when the file or both keys are absent. Ids are opaque."""
    try:
        raw = json.loads(config_path(agent_home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ids = (raw.get("role_models") or {}).get(role) if role else None
    if isinstance(ids, list) and ids and ids[0]:
        return str(ids[0])
    return str(raw["default_model"]) if role is None and raw.get("default_model") else None


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
