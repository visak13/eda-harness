#!/usr/bin/env python3
"""SessionStart hook — capture the FOREGROUND session's id in CODE (W11).

The foreground neuron shell is launched by the USER, not by the pool, so the
harness never learns its Claude Code session id — and an LLM cannot reliably
remember its own. Claude Code hands every SessionStart hook a `session_id` on
stdin; that is the only trustworthy source. This hook appends it to
``<repo>/.sessions/foreground.jsonl`` so `suspend_recipe` can later print a
working ``claude-personal --resume <id>``.

WHY THE `EDP_ROLE` GATE (load-bearing — do not remove):
pool-spawned shells (planner / worker / reviewer) run in this SAME project and
therefore fire this SAME hook. `pty_launcher.py` stamps ``EDP_ROLE`` on every
spawn; the user's foreground shell carries none. Ungated, the newest line in
the registry would routinely be a *worker's* session id and the resume command
would reattach to the wrong shell. Absence of ``EDP_ROLE`` IS the definition of
"foreground" here.

`config_dir` is captured because the user launches via a PowerShell
``claude-personal`` function that sets ``CLAUDE_CONFIG_DIR="$HOME\\.claude-personal"``.
Claude Code stores transcripts under that dir, so a bare ``claude --resume <id>``
would NOT find the session. The reader surfaces `config_dir` so the correct
launcher can be named. The path is never hardcoded — it is read from the env.

Registered for sources ``startup|resume|clear`` (every non-compact start).
`/clear`'s session_id reuse is undocumented, so the log is append-only and the
reader takes the LAST well-formed line: correct whether the id is reused or
replaced.

FAIL-SAFE is mandatory: this is the highest-blast-radius file in the plan — a
hook that raises would break session start for EVERY session in this project.
Every failure collapses to a clean exit 0. Diagnostics go to STDERR only (exit
0 + stderr is debug-log-only per the hooks contract), never stdout — stdout is
the hook's structured interface. Kept dependency-free (stdlib only) so it adds
negligible latency to session start, matching `reground-on-compact.py`.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Anchored to THIS file, not to cwd or CLAUDE_PROJECT_DIR: the hook must record
# the right path no matter where `claude` was launched from.
# .claude/hooks/capture-session.py -> parents[2] == the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
FOREGROUND_LOG = REPO_ROOT / ".sessions" / "foreground.jsonl"


def is_foreground(env: dict) -> bool:
    """True iff this session is the user's foreground shell.

    Pool-spawned shells always carry a non-empty ``EDP_ROLE``; the foreground
    shell never does. See the module docstring — this gate is load-bearing.
    """
    return not (env.get("EDP_ROLE") or "").strip()


def session_record(data: dict, env: dict, now: datetime) -> dict | None:
    """Pure: map a SessionStart payload to the registry record, or None when
    this event must not be recorded (not foreground / no usable session id)."""
    if not isinstance(data, dict):
        return None
    if not is_foreground(env):
        return None  # a pool-spawned planner/worker — not the foreground shell
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    return {
        "session_id": session_id,
        "cwd": data.get("cwd"),
        # Absent for a plain `claude` launch; set by the `claude-personal`
        # launcher. None is a meaningful value, so it is always written.
        "config_dir": env.get("CLAUDE_CONFIG_DIR"),
        "started_at": now.isoformat(),
    }


def append_record(record: dict, log_path: Path) -> None:
    """Append one JSON object as one line. Creates .sessions/ when absent."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.flush()


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception as exc:  # noqa: BLE001 — unreadable stdin → clean no-op
        _warn(f"unreadable SessionStart payload: {exc!r}")
        return 0
    try:
        record = session_record(data, os.environ, datetime.now(timezone.utc))
        if record is None:
            return 0
        append_record(record, FOREGROUND_LOG)
    except Exception as exc:  # noqa: BLE001 — FAIL-SAFE: never break a session
        _warn(f"could not record foreground session: {exc!r}")
    return 0


def _warn(message: str) -> None:
    """Best-effort diagnostic. stderr on a 0-exit is debug-log-only, so it can
    never corrupt the hook's stdout interface or block the session. Guarded so
    that even a broken stderr cannot defeat the fail-safe."""
    try:
        print(f"capture-session: {message}", file=sys.stderr)  # noqa: T201 —
        # STDERR is the only safe diagnostic channel here: stdout is the hook's
        # structured interface, and on a 0-exit the harness routes stderr to the
        # debug log only. This is what keeps the fail-safe from silently
        # swallowing the cause (standard #11).
    except Exception:  # noqa: BLE001 — nothing left to do; stay silent, exit 0
        pass


if __name__ == "__main__":
    sys.exit(main())
