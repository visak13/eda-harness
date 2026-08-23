#!/usr/bin/env python3
"""PreToolUse guard — deny blanket process-kills that nuke the whole stack.

2026-05-31: a worker ran `taskkill /F /IM python.exe` to clear one stray
reactive monitor and killed EVERY python process — the broker, the pool,
all MCP servers, and every sibling agent shell. Prompt prohibitions don't
reliably stop this (an LLM won't dependably obey "don't do X"), so this
hook enforces it DETERMINISTICALLY in the harness, for every shell that
loads `.claude/settings.json`.

Policy: allow TARGETED kills (by a specific PID); DENY kills that target a
process by NAME / image of a critical stack process (which hit every
instance at once). For a stray reactive monitor, use the `TaskStop` tool
on its task id — never a blanket kill.

Reads the PreToolUse JSON on stdin; prints a `deny` decision when matched,
else exits 0 (normal permission flow). Kept dependency-free + tiny so it
adds negligible latency to each Bash/PowerShell call."""
import json
import re
import sys

# critical stack process names — a name-kill of any of these takes down
# the broker/pool/MCP/sibling shells (the whole stack is python).
_CRIT = r"(python|pythonw|node|claude|uvicorn|conhost)"

# (compiled pattern, why) — case-insensitive search over the command.
_DENY = [
    (re.compile(rf"taskkill\b(?=.*/im\b)(?=.*{_CRIT})", re.I),
     "kills ALL processes by image name (`taskkill /IM`)"),
    (re.compile(r"taskkill\b(?=.*/f\b)(?=.*/t\b)(?!.*/pid\b)", re.I),
     "force-kills a whole process tree with no specific `/PID`"),
    (re.compile(rf"stop-process\b(?=.*-name\b)(?=.*{_CRIT})", re.I),
     "`Stop-Process -Name` kills ALL processes by name"),
    (re.compile(rf"\b(pkill|killall)\b.*{_CRIT}", re.I),
     "kills ALL matching processes by name (`pkill`/`killall`)"),
]


def decide(command: str) -> str | None:
    """Return a deny-reason if `command` is a stack-nuking blanket kill,
    else None (allow / normal flow). Pure + importable for tests."""
    for pat, why in _DENY:
        if pat.search(command or ""):
            return why
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 — unparseable input → don't interfere
        return 0
    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    why = decide(cmd)
    if why is None:
        return 0
    reason = (
        f"BLOCKED: this command {why}, which would kill the broker, pool, "
        "MCP servers, and every sibling agent shell — the whole stack "
        "(the 2026-05-31 blackout). Kill the SPECIFIC stray PID instead: "
        "`taskkill /PID <pid> /F` or `Stop-Process -Id <pid>`. To stop a "
        "reactive monitor, use the `TaskStop` tool on its task id — never "
        "a blanket name/image kill.")
    print(json.dumps({"hookSpecificOutput": {  # noqa: T201 — stdout IS the
        # hook's interface: this deny-JSON is read by the harness.
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
