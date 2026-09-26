"""Harness choice and the Fable adversary fallback (design-e963c656f5 §4.11, owner rulings R4 and R5).

Claude, codex and Pi are the seat harnesses. `seats.harnesses` in init configuration names the selected
ones (absent = all three); at least one of claude/codex must be selected, and the role
catalog (seat_choice.catalog) keeps only models whose harness is selected.

The adversary runs on codex when codex is selected. When it is not, the adversary runs on Fable
(claude-fable-5-1), and the board refuses every adversary spawn on Fable until a human has acknowledged
the risk once: Fable's safeguards are strict, so an adversarial or security review may be declined or
softened, and a clean result is not proof. The acknowledgement is a small JSON record next to the board's
database (who, when, the notice text), written by POST /v1/harness/fable-ack.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

HARNESSES = ("claude", "codex", "pi")
HARNESS_KEY = "harnesses"  # legacy catalog key; ignored in favour of init configuration
FABLE = "claude-fable-5-1"
ACK_FILE = "fable-risk-ack.json"

FABLE_RISK_NOTICE = (
    "Codex is not selected, so the adversary role runs on Fable (claude-fable-5-1). Fable's safety "
    "safeguards are strict: an adversarial or security review may be declined or softened. Review its "
    "findings before trusting a clean result.")


def harness_of(model: str | None, entries: dict[str, Any] | None = None) -> str | None:
    """Resolve a catalog id through its explicit harness; model spelling has no routing meaning."""
    m = (model or "").strip()
    row = (entries or {}).get(m)
    return str(row["harness"]) if isinstance(row, dict) and row.get("harness") in HARNESSES else None


def selected(registry: dict[str, Any]) -> tuple[str, ...]:
    """The selected harnesses from init configuration; catalog content cannot override them."""
    raw = _configured()
    if not isinstance(raw, list):
        return HARNESSES
    picked = tuple(h for h in HARNESSES if h in {str(x).strip().lower() for x in raw})
    return picked if validate(picked) is None else HARNESSES


def _configured() -> list[str] | None:
    """`heronry init --harness …` records the choice as the setting EDP_HARNESSES (config.toml
    seats.harnesses), so the shipped models.json stays unedited and keeps receiving catalog updates."""
    from . import settings
    val = settings.get("EDP_HARNESSES")
    return list(val) if val else None


def validate(picked: tuple[str, ...] | list[str]) -> str | None:
    """None when the selection is usable; the reason otherwise (at least one of claude/codex)."""
    if not ({"claude", "codex"} & set(picked)):
        return "select at least one of claude and codex"
    return None


def filter_catalog(table: dict[str, list[str]], registry: dict[str, Any]) -> dict[str, list[str]]:
    """The per-role catalog keeping only models on a selected harness; the adversary falls back to Fable
    when codex is not selected (R5). A role left with no model is dropped (the pool's default applies)."""
    picked = selected(registry)
    entries = registry.get("models") if isinstance(registry.get("models"), dict) else {}
    out: dict[str, list[str]] = {}
    for role, ids in table.items():
        keep = [m for m in ids if harness_of(m, entries) in picked]
        if role == "adversary" and "codex" not in picked:
            keep = [FABLE] + [m for m in keep if m != FABLE]
        if keep:
            out[role] = keep
    return out


def ack_path(db_path: str | os.PathLike[str] | None) -> Path | None:
    """The acknowledgement record beside the board's database; None for an in-memory board (which then
    can never hold an acknowledgement, so a Fable adversary spawn there is always refused)."""
    if db_path and str(db_path) != ":memory:":
        return Path(db_path).resolve().parent / ACK_FILE
    return None


def read_ack(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("by") else None


def write_ack(path: Path, by: str) -> dict[str, Any]:
    rec = {"by": by, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "notice": FABLE_RISK_NOTICE}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    os.replace(tmp, path)
    return rec


def fable_refusal(role: str | None, model: str | None, path: Path | None) -> str | None:
    """The refusal text for an adversary spawn on Fable before the risk is acknowledged, else None."""
    if role != "adversary" or (model or "") != FABLE or read_ack(path) is not None:
        return None
    return f"adversary spawn on Fable refused until a human acknowledges the risk: {FABLE_RISK_NOTICE}"
