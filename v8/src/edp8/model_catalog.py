"""Editable model catalog, stored in the data directory rather than the agent home."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from edp_contracts.seats import config_path

from . import settings

HARNESSES = {"claude", "codex", "pi"}
EFFORTS = {"low", "medium", "high"}
MODEL_FIELDS = {"harness", "provider", "model", "context_window", "auto_compact", "effort_cap"}


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
            models[model] = {"harness": harness, "provider": provider,
                             "context_window": window, "auto_compact": compact,
                             "effort_cap": "medium" if harness == "claude" else "high"}
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


def materialise() -> Path:
    """Create the editable copy once; package/agent-home defaults remain read-only."""
    dest = path()
    if dest.is_file():
        return dest
    source = settings.agent_home() / "models.json"
    if not source.is_file():
        from .materialise import source_root
        source = source_root() / "models.json"
    raw = migrate(json.loads(source.read_text(encoding="utf-8")))
    write(raw, dest)
    return dest


def write(raw: dict[str, Any], dest: Path | None = None) -> None:
    target = dest or path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def validate(models: dict[str, Any], role_models: dict[str, Any]) -> list[str]:
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
        try:
            window, compact = int(row["context_window"]), int(row["auto_compact"])
            if window <= 0 or not 0 < compact < window:
                errors.append(f"{mid}: auto_compact must be below context_window")
        except (KeyError, ValueError, TypeError):
            errors.append(f"{mid}: context_window and auto_compact must be integers")
    for role, ids in role_models.items():
        if not isinstance(ids, list) or not ids:
            errors.append(f"{role}: catalog needs at least one model")
        else:
            for mid in ids:
                if mid not in models:
                    errors.append(f"{role}: unknown model {mid!r}")
    return errors
