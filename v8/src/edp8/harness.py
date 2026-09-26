"""Harness choice and the Fable adversary fallback (design-e963c656f5 §4.11, owner rulings R4 and R5).

Claude, codex and Pi are the seat harnesses. models.json `harnesses` names the ones this install uses
(absent = all three, today's behaviour); at least one of claude/codex must be selected, and the role
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
HARNESS_KEY = "harnesses"  # models.json: ["claude", "codex"], absent = every harness
FABLE = "claude-fable-5-1"
ACK_FILE = "fable-risk-ack.json"

FABLE_RISK_NOTICE = (
    "Codex is not selected, so the adversary role runs on Fable (claude-fable-5-1). Fable's safety "
    "safeguards are strict: an adversarial or security review may be declined or softened. Review its "
    "findings before trusting a clean result.")


def harness_of(model: str | None, seats: dict[str, Any] | None = None) -> str:
    """The harness a catalog id runs on: a models.json seat's own `harness`, a GPT id or `codex/…` →
    codex, an `openai/…`/`openai-codex/…` id → pi, anything else → claude. PURE."""
    m = (model or "").strip()
    seat = (seats or {}).get(m)
    if isinstance(seat, dict) and seat.get("harness") in HARNESSES:
        return str(seat["harness"])
    if m.startswith(("openai/", "openai-codex/")):
        return "pi"
    if m.startswith("codex/") or m.lower().startswith("gpt-"):
        return "codex"
    return "claude"


def selected(registry: dict[str, Any]) -> tuple[str, ...]:
    """The selected harnesses from models.json (the registry dict); absent or malformed = all three. A list
    that selects neither claude nor codex is invalid and also answers all three (fail open to today's
    fleet; `validate` names the problem)."""
    raw = registry.get(HARNESS_KEY)
    if not isinstance(raw, list):
        return HARNESSES
    picked = tuple(h for h in HARNESSES if h in {str(x).strip().lower() for x in raw})
    return picked if validate(picked) is None else HARNESSES


def validate(picked: tuple[str, ...] | list[str]) -> str | None:
    """None when the selection is usable; the reason otherwise (at least one of claude/codex)."""
    if not ({"claude", "codex"} & set(picked)):
        return "select at least one of claude and codex"
    return None


def filter_catalog(table: dict[str, list[str]], registry: dict[str, Any]) -> dict[str, list[str]]:
    """The per-role catalog keeping only models on a selected harness; the adversary falls back to Fable
    when codex is not selected (R5). A role left with no model is dropped (the pool's default applies)."""
    picked = selected(registry)
    seats = registry.get("seats") if isinstance(registry.get("seats"), dict) else {}
    out: dict[str, list[str]] = {}
    for role, ids in table.items():
        keep = [m for m in ids if harness_of(m, seats) in picked]
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
