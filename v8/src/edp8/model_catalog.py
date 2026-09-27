"""Editable model catalog, stored in the data directory rather than the agent home."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from edp_contracts.seats import config_path

from . import settings

HARNESSES = {"claude", "codex", "pi"}
EFFORTS = {"low", "medium", "high"}
#: the fields a catalog row may carry, with their meaning (the project site's models reference renders this, S15)
MODEL_FIELD_DOCS = {
    "harness": "the program that runs the seat: claude, codex or pi",
    "provider": "who serves the model (for pi, the provider name Pi is configured with)",
    "model": "the model name passed to the harness, when it differs from the row's id",
    "context_window": "the model's context window, in tokens",
    "auto_compact": "the context size, in tokens, at which the seat compacts its conversation",
    "effort_cap": "the highest reasoning effort a seat on this model may be given: low, medium or high",
}
MODEL_FIELDS = set(MODEL_FIELD_DOCS)
#: the catalog's top-level keys, with their meaning (S15 site reference)
CATALOG_KEY_DOCS = {
    "models": "every model a seat may run on: model id → a row (below)",
    "role_models": "role → the ordered list of model ids that role may run on; the first is its default",
    "default_model": "the model any role absent from role_models spawns on (custom workflow roles too)",
}
DEFAULT_KEY = "default_model"  # the model any role absent from role_models spawns on (custom roles too)
SHIPPED_KEY = "_shipped"       # snapshot of the shipped catalog last merged into the data-dir copy
#: harnesses whose window and compaction come from the harness itself when a row leaves them unset
HARNESS_WINDOWS = {"codex"}
#: the 272k/200k pair S12's first migration invented for every Codex row (owner m-bfe93b313c: wrong)
_INVENTED_CODEX = (272_000, 200_000)


def path() -> Path:
    return Path(settings.get("EDP_MODELS_CONFIG") or settings.data_dir() / "models.json")


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """One-time conversion of the historic host catalog; preserve every binding and its order."""
    result = json.loads(json.dumps(raw))
    models = dict(result.get("models") or {})
    seats = result.get("seats") or {}
    for ids in (result.get("role_models") or {}).values():
        for model in ids:
            if model in models:
                continue
            # Legacy inference happens only here. Runtime routing never examines an id's prefix.
            if model in seats:
                row = seats[model]
                harness = row.get("harness") or "claude"
                provider = row.get("provider") or ("openai-codex" if harness == "pi" else harness)
                window = row.get("context_window", 1_000_000)
                compact = row.get("auto_compact", 350_000)
            else:
                harness = "pi" if model.startswith(("openai/", "openai-codex/")) else (
                    "codex" if model.startswith(("gpt-", "codex/")) else "claude")
                provider = model.split("/", 1)[0] if harness == "pi" else harness
                window = 272_000 if harness != "claude" else 1_000_000
                compact = 200_000 if harness != "claude" else 350_000
            row = {"harness": harness, "provider": provider,
                   "context_window": window, "auto_compact": compact,
                   "effort_cap": "medium" if harness == "claude" else "high"}
            if harness in HARNESS_WINDOWS:  # the harness reports its own window and compaction
                del row["context_window"], row["auto_compact"]
            models[model] = row
    for row in seats.values():
        row.setdefault("harness", "claude")
        row.setdefault("provider", "openai-codex" if row["harness"] == "pi" else row["harness"])
        row.setdefault("effort_cap", "medium" if row["harness"] == "claude" else "high")
    result["models"] = models
    result.pop("harnesses", None)
    result.pop("_harnesses_note", None)
    return result


def read(agent_home: Path | None = None) -> dict[str, Any]:
    source = config_path(agent_home or settings.agent_home())
    return json.loads(source.read_text(encoding="utf-8"))


def shipped_path() -> Path:
    """The catalog this version ships: the agent home's copy, else the package source tree's."""
    source = settings.agent_home() / "models.json"
    if not source.is_file():
        from .materialise import source_root
        source = source_root() / "models.json"
    return source


def snapshot(shipped: dict[str, Any]) -> dict[str, Any]:
    """What a merge remembers of the shipped catalog: its rows, roles, default and a content version."""
    core = {"models": shipped.get("models") or {}, "role_models": shipped.get("role_models") or {},
            DEFAULT_KEY: shipped.get(DEFAULT_KEY)}
    version = hashlib.sha256(json.dumps(core, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return {"version": version, **json.loads(json.dumps(core))}


def merge(data: dict[str, Any], shipped: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """PURE. Bring a newer shipped catalog into the data-dir copy (architect m-cea5526782).

    Adds shipped models, roles and role entries the copy lacks; never overwrites a row the owner edited
    and never restores one the owner removed. "Removed" and "edited" are judged against the snapshot of
    the shipped catalog last merged (`_shipped`): a row the snapshot held that the copy lacks was removed;
    a copy row still equal to its snapshot row was never edited, so it follows the new shipped row.
    A copy with no snapshot (made before merging existed) only gains what it lacks, plus one repair:
    a Codex row still carrying the invented 272k/200k pair drops it and follows Codex's own numbers."""
    out = json.loads(json.dumps(data))
    changes: list[str] = []
    prev = out.get(SHIPPED_KEY) if isinstance(out.get(SHIPPED_KEY), dict) else None
    prev_models = (prev or {}).get("models") or {}
    prev_roles = (prev or {}).get("role_models") or {}
    models = out.setdefault("models", {})
    for mid, row in (shipped.get("models") or {}).items():
        cur = models.get(mid)
        if cur is None:
            if mid in prev_models:
                continue  # the owner removed it
            models[mid] = json.loads(json.dumps(row))
            changes.append(f"added model {mid}")
        elif cur != row and prev is not None and prev_models.get(mid) == cur:
            models[mid] = json.loads(json.dumps(row))
            changes.append(f"updated unedited model {mid}")
        elif (prev is None and cur.get("harness") in HARNESS_WINDOWS and "context_window" not in row
              and (cur.get("context_window"), cur.get("auto_compact")) == _INVENTED_CODEX):
            cur.pop("context_window", None)
            cur.pop("auto_compact", None)
            changes.append(f"model {mid} now takes its window from {cur['harness']}")
    roles = out.setdefault("role_models", {})
    for role, ids in (shipped.get("role_models") or {}).items():
        if role not in roles:
            if role in prev_roles:
                continue  # the owner removed the role's catalog
            keep = [m for m in ids if m in models]
            if keep:
                roles[role] = keep
                changes.append(f"added role {role}")
            continue
        cur_ids = roles[role]
        for m in ids:
            if m not in cur_ids and m not in (prev_roles.get(role) or []) and m in models:
                cur_ids.append(m)
                changes.append(f"added {m} to {role}")
    new_default = shipped.get(DEFAULT_KEY)
    old_default = out.get(DEFAULT_KEY)
    if new_default and new_default in models and old_default != new_default and (
            not old_default or (prev is not None and old_default == prev.get(DEFAULT_KEY))):
        out[DEFAULT_KEY] = new_default
        changes.append(f"default model {new_default}")
    for key, value in shipped.items():  # new top-level tables (seats, notes) the copy has never seen
        if key not in out and key != SHIPPED_KEY:
            out[key] = json.loads(json.dumps(value))
    snap = snapshot(shipped)
    if (prev or {}).get("version") != snap["version"]:
        changes.append(f"shipped catalog {snap['version']}")
    out[SHIPPED_KEY] = snap
    return out, changes


def sync(dest: Path | None = None, source: Path | None = None) -> list[str]:
    """Merge the shipped catalog into the data-dir copy; runs at `init` and at every board start (so after
    `heronry update`, whose helper starts the board). Returns what changed; [] leaves the file untouched."""
    target = dest or path()
    if not target.is_file():
        return []
    shipped = migrate(json.loads((source or shipped_path()).read_text(encoding="utf-8")))
    data = json.loads(target.read_text(encoding="utf-8"))
    merged, changes = merge(data, shipped)
    if merged != data:
        write(merged, target)
    return changes


def materialise() -> Path:
    """Create the editable copy on first run, else merge the shipped catalog into it."""
    dest = path()
    if dest.is_file():
        sync(dest)
        return dest
    raw = migrate(json.loads(shipped_path().read_text(encoding="utf-8")))
    raw[SHIPPED_KEY] = snapshot(raw)
    write(raw, dest)
    return dest


_codex_windows: dict[str, dict[str, int]] | None = None


def codex_windows(refresh: bool = False) -> dict[str, dict[str, int]]:
    """Each Codex model's window from Codex itself (`codex debug models`, the CLI's raw catalog):
    {slug: {context_window, max_context_window, auto_compact}}. `auto_compact` is Codex's own default,
    90% of context_window (what codex-rs applies when neither the model nor config sets
    model_auto_compact_token_limit). {} when codex is absent or the call fails."""
    global _codex_windows
    if _codex_windows is not None and not refresh:
        return _codex_windows
    from edp_contracts.toolpath import find_tool
    exe = find_tool("codex", key="EDP_CODEX_BIN")
    out: dict[str, dict[str, int]] = {}
    if exe:
        try:
            proc = subprocess.run([str(exe), "debug", "models"], capture_output=True, text=True,
                                  encoding="utf-8", timeout=30, stdin=subprocess.DEVNULL,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for m in (json.loads(proc.stdout).get("models") or []):
                window = int(m.get("context_window") or 0)
                if m.get("slug") and window > 0:
                    out[str(m["slug"])] = {"context_window": window,
                                           "max_context_window": int(m.get("max_context_window") or window),
                                           "auto_compact": window * 9 // 10}
        except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
            out = {}
    _codex_windows = out
    return out


def write(raw: dict[str, Any], dest: Path | None = None) -> None:
    target = dest or path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def validate(models: dict[str, Any], role_models: dict[str, Any],
             default_model: str | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(models, dict) or not isinstance(role_models, dict):
        return ["models and role_models must be objects"]
    for mid, row in models.items():
        if not isinstance(mid, str) or not mid.strip() or not isinstance(row, dict):
            errors.append(f"invalid model entry {mid!r}")
            continue
        if row.get("harness") not in HARNESSES:
            errors.append(f"{mid}: unknown harness {row.get('harness')!r}")
        extra = set(row) - MODEL_FIELDS
        if extra:
            errors.append(f"{mid}: unsupported fields {sorted(extra)}; credentials belong in secret settings")
        if not isinstance(row.get("provider"), str) or not re.fullmatch(r"[A-Za-z0-9_-]+", row["provider"]):
            errors.append(f"{mid}: provider is required")
        cap = row.get("effort_cap")
        if cap not in EFFORTS or (row.get("harness") == "claude" and cap == "high"):
            errors.append(f"{mid}: invalid effort_cap {cap!r}")
        errors += _window_errors(mid, row)
    for role, ids in role_models.items():
        if not isinstance(ids, list) or not ids:
            errors.append(f"{role}: catalog needs at least one model")
        else:
            for mid in ids:
                if mid not in models:
                    errors.append(f"{role}: unknown model {mid!r}")
    if default_model is not None and default_model not in models:
        errors.append(f"default model {default_model!r} is not in the catalog")
    return errors


def _window_errors(mid: str, row: dict[str, Any]) -> list[str]:
    """A Codex row may leave either number unset (Codex supplies it); every other row needs both."""
    window, compact = row.get("context_window"), row.get("auto_compact")
    optional = row.get("harness") in HARNESS_WINDOWS
    for name, value in (("context_window", window), ("auto_compact", compact)):
        if value is None and optional:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return [f"{mid}: {name} must be a positive integer"]
    if window is not None and compact is not None and not compact < window:
        return [f"{mid}: auto_compact must be below context_window"]
    return []
