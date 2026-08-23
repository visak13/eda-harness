#!/usr/bin/env python
"""Notification hook — surface blocked-on-user moments as a Windows toast.

THE GAP THIS CLOSES (user ruling, 2026-08-12): the harness computes
AWAIT_USER / permission-wait states but surfaces them nowhere; the operator
discovers a stalled fleet by walking the consoles. Claude Code's native
`Notification` hook event fires exactly at those moments
(notification_type: permission_prompt | agent_needs_input | idle_prompt),
so this hook is the whole feature — no pool plumbing, no panel.

Mechanism: WinRT toast via a hidden PowerShell (zero-install, Win10/11);
fallback to a console beep if the toast pipeline errors. Rate-limited to
one toast per WINDOW_S per (role, type) so a wake storm can't become a
toast storm. Gated by EDP_TOASTS (default on; set 0 to silence).

FAIL-OPEN, ALWAYS: a notifier must never break a shell.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

WINDOW_S = 30.0
STATE = Path(__file__).resolve().parent.parent.parent / ".logs" / "notify-user-state.json"

_TOAST_PS = r"""
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@"
<toast><visual><binding template='ToastGeneric'><text>{title}</text><text>{body}</text></binding></visual></toast>
"@)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Claude Code').Show(
    [Windows.UI.Notifications.ToastNotification]::new($xml))
"""

_TYPE_TITLES = {
    "permission_prompt": "needs permission",
    "agent_needs_input": "needs input",
    "idle_prompt": "waiting on you",
    "elicitation_dialog": "asking a question",
}


def _rate_limited(key: str) -> bool:
    try:
        state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except (OSError, ValueError):
        state = {}
    now = time.time()
    last = state.get(key, 0)
    if now - last < WINDOW_S:
        return True
    state[key] = now
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass
    return False


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace("'", "&apos;"))


def main() -> int:
    if os.environ.get("EDP_TOASTS", "1") == "0" or sys.platform != "win32":
        return 0
    try:
        payload = json.loads((sys.stdin.read() or "{}").lstrip("﻿"))
    except ValueError:
        return 0
    ntype = payload.get("notification_type", "")
    if ntype not in _TYPE_TITLES:
        return 0
    role = os.environ.get("EDP_ROLE", "") or "neuron (foreground)"
    handle = os.environ.get("EDP_HANDLE", "")
    if _rate_limited(f"{role}:{ntype}"):
        return 0
    title = _xml_escape(f"{role} {_TYPE_TITLES[ntype]}")
    body = _xml_escape(handle or payload.get("cwd", ""))
    script = _TOAST_PS.replace("{title}", title).replace("{body}", body)
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        try:
            print("\a", end="", file=sys.stderr)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
