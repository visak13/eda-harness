"""Reader for the foreground-session registry (DESIGN-v6 W11).

The registry is written by the `SessionStart` hook
``.claude/hooks/capture-session.py``, which appends one JSON object per line to
``<repo>/.sessions/foreground.jsonl`` each time the USER's foreground shell
starts. This module is the read side: it yields the ``session_id`` and the
``config_dir`` its transcript lives under, so a caller can print a resume
command that actually works.

SCOPE — what this does NOT tell you. The hook records every *foreground* shell
in this repo, not only the neuron's. If the user opens a second foreground
shell here after the neuron starts, that entry lands last. So
``latest_foreground_session()`` is "the most recent foreground session recorded
in this repo" — a FALLBACK, never an authority on which session is the neuron.
``suspend_recipe`` prefers a stamped ``recipe.neuron_session_id`` (bind-time
capture) and falls back to this reader.

The two halves are deliberately decoupled — the hook stays stdlib-only so it
adds no import latency to session start, and therefore restates the log path
rather than importing it from here. ``tests/test_w11_foreground_capture.py``
asserts the two paths resolve identically, so the constants cannot drift.

The log is append-only and never rewritten, so the CURRENT session is always
the LAST well-formed line. A line can be truncated if a session start was
interrupted mid-write; such lines are skipped rather than raising, because a
half-written line must not cost the caller a resume command it could otherwise
recover from an earlier, intact entry.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

_LOG = logging.getLogger(__name__)

# src/edp_claude/sessions.py -> parents[2] == the repo root. Mirrors the
# anchoring in .claude/hooks/capture-session.py (drift-guarded by tests).
REPO_ROOT = Path(__file__).resolve().parents[2]
FOREGROUND_LOG = REPO_ROOT / ".sessions" / "foreground.jsonl"


def _is_well_formed(record: object) -> bool:
    """A usable entry: a dict carrying a non-empty string ``session_id``."""
    return (
        isinstance(record, dict)
        and isinstance(record.get("session_id"), str)
        and bool(record["session_id"].strip())
    )


def _well_formed_records(log_path: Path | str | None) -> list[dict]:
    """Every usable entry in the registry, oldest first; ``[]`` when the file is
    missing, unreadable, or holds nothing well-formed.

    Blank, malformed and wrong-shaped lines are skipped rather than raising: a
    half-written line (an interrupted session start) must not cost the caller an
    entry it could otherwise recover.
    """
    path = Path(log_path) if log_path is not None else FOREGROUND_LOG
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        _LOG.warning("foreground session registry unreadable at %s: %r", path, exc)
        return []

    records: list[dict] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            _LOG.debug("skipping malformed registry line in %s: %r", path, exc)
            continue
        if _is_well_formed(record):
            records.append(record)
        else:
            _LOG.debug("skipping well-formed JSON without a session_id in %s", path)
    return records


def latest_foreground_session(log_path: Path | str | None = None) -> dict | None:
    """Return the most recently recorded FOREGROUND session, or None.

    This is the newest foreground shell started in this repo — NOT necessarily
    the neuron's (see the module docstring). Treat it as a fallback.

    None means "no usable record": the registry is missing, empty, or holds
    nothing well-formed — e.g. the capture hook has never fired in this
    checkout. Callers treat that as "no resume command can be offered", not as
    an error.

    The returned dict carries ``session_id``, ``cwd``, ``config_dir`` and
    ``started_at``. ``config_dir`` may be None (a plain ``claude`` launch); when
    set, it is the ``CLAUDE_CONFIG_DIR`` the transcript lives under and the
    resume command must be issued through the launcher that pins it.
    """
    records = _well_formed_records(log_path)
    return records[-1] if records else None


def foreground_session_by_id(
    session_id: str, log_path: Path | str | None = None
) -> dict | None:
    """The registry entry for exactly ``session_id``, or None when that session
    was never recorded here.

    ``suspend_recipe`` uses this to bind a resolved neuron session id to the
    ``config_dir`` of the shell that actually ran it — correct by construction.
    Reading ``config_dir`` off the LATEST entry instead would pair a real
    session id with a different shell's launcher, printing a resume command that
    fails in a way the user cannot diagnose. A session stamped before this hook
    existed is absent here, and the caller then says so explicitly.

    The NEWEST match wins: ``/clear`` may reuse a session id, and the later
    entry reflects how that shell was most recently launched.
    """
    for record in reversed(_well_formed_records(log_path)):
        if record["session_id"] == session_id:
            return record
    return None
