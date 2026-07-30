#!/usr/bin/env python3
"""PreToolUse hook — route tool-call approvals through the POOL PANEL.

v7 follow-up (2026-07-12, user directive): the operator wants ONE control
surface — the floating panel — where a shell's pending tool calls can be
approved, instead of hunting the console window of whichever pool-spawned
shell is asking.

CONTRACT (fail-open at every seam — this hook may ACCELERATE a decision,
it must never be able to strand a shell):
  * Gated by env EDP_PANEL_APPROVALS == "1". Unset/other → exit 0 instantly:
    the shell's normal permission flow is untouched (today's default).
  * When gated on: POST the call to the pool's approval queue, long-poll the
    verdict for up to ~50s. Operator says allow → emit permissionDecision
    "allow"; deny → "deny" with the operator's reason. Timeout, pool down,
    malformed payload, ANY exception → exit 0, i.e. the shell's own
    permission prompt takes over exactly as if this hook did not exist.
  * The hook decides NOTHING itself and rewrites NOTHING — it relays the
    operator's verdict verbatim or steps aside. (Contrast rtk-pretooluse.py,
    which rewrites input and therefore carries a semantics burden; this one
    is a pure relay.)

Registered in .claude/settings.json for the permission-prompting tools
(Bash / PowerShell / Write / Edit). stdlib-only (urllib): pool shells must
not need extra deps for their hooks.
"""
import json
import os
import sys
import urllib.request

_WAIT_S = 50          # under the hook's own settings.json timeout
_POOL = os.environ.get("EDP_POOL_URL", "http://127.0.0.1:9301").rstrip("/")


def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{_POOL}{path}", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path: str, timeout: float) -> dict:
    with urllib.request.urlopen(f"{_POOL}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    if os.environ.get("EDP_PANEL_APPROVALS") != "1":
        return 0
    try:
        data = json.load(sys.stdin)
        tool = data.get("tool_name") or "?"
        tin = data.get("tool_input") or {}
        summary = (tin.get("command") or tin.get("file_path")
                   or json.dumps(tin, default=str))
        made = _post("/v1/approvals", {
            "handle": os.environ.get("EDP_HANDLE", ""),
            "role": os.environ.get("EDP_ROLE", ""),
            "tool_name": tool,
            "summary": str(summary)[:2000],
        })
        verdict = _get(f"/v1/approvals/{made['id']}/wait?timeout_s={_WAIT_S}",
                       timeout=_WAIT_S + 10)
        decision = verdict.get("decision")
        if decision == "allow":
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason":
                    "approved by the operator via the pool panel",
            }}))
        elif decision == "deny":
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason":
                    f"denied via the pool panel: "
                    f"{verdict.get('reason') or 'no reason given'}",
            }}))
        # decision None (timeout) → say nothing: normal permission flow
        return 0
    except Exception:  # noqa: BLE001 — FAIL-OPEN: never strand a tool call
        return 0


if __name__ == "__main__":
    sys.exit(main())
