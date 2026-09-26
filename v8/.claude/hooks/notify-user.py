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

BOARD POST (pain p-73d192bf, owner m-705c0a47f6): a SEAT (EDP_HANDLE = <role>.<ticket>) that stops on
an interactive prompt (permission / elicitation / needs-input — not the ordinary idle wait) also
posts a `question` to the owner on its ticket, so the board shows the seat is blocked and the
owner's Slack/feed fires. No one reads seat consoles. The prompt itself is never bypassed.

FAIL-OPEN, ALWAYS: a notifier must never break a shell.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
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


_BLOCKING = ("permission_prompt", "elicitation_dialog", "agent_needs_input")


def _post_blocked(payload: dict, ntype: str) -> None:
    """Best-effort: tell the owner on the seat's ticket that the shell sits on a prompt."""
    handle = os.environ.get("EDP_HANDLE", "").strip()
    if ntype not in _BLOCKING or "." not in handle or os.environ.get("EDP_BOARD_BLOCKED_POST", "1") == "0":
        return
    ticket = handle.split(".", 1)[1]
    what = str(payload.get("message") or payload.get("title") or _TYPE_TITLES[ntype])[:300]
    body = {"ticket_id": ticket, "to": "owner", "kind": "question", "reply_to": None, "artifacts": [],
            "text": (f"[blocked] {handle} stopped on an interactive prompt ({ntype}): {what} — "
                     "it waits until someone answers it in the seat's console.")}
    headers = {"Content-Type": "application/json", "X-Participant": handle}
    if os.environ.get("EDP8_TOKEN"):
        headers["X-Token"] = os.environ["EDP8_TOKEN"]
    base = (os.environ.get("EDP8_BOARD_URL") or "http://127.0.0.1:9400").rstrip("/")
    try:
        req = urllib.request.Request(f"{base}/v1/messages", data=json.dumps(body).encode(), headers=headers)
        urllib.request.urlopen(req, timeout=3).read(0)
    except Exception:  # noqa: BLE001 — fail-open
        pass


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace("'", "&apos;"))


def main() -> int:
    try:
        payload = json.loads((sys.stdin.read() or "{}").lstrip("﻿"))
    except ValueError:
        return 0
    ntype = payload.get("notification_type", "")
    if ntype not in _TYPE_TITLES:
        return 0
    role = os.environ.get("EDP_ROLE", "") or "neuron (foreground)"
    handle = os.environ.get("EDP_HANDLE", "")
    if _rate_limited(f"{handle or role}:{ntype}"):
        return 0
    _post_blocked(payload, ntype)
    if os.environ.get("EDP_TOASTS", "1") == "0" or sys.platform != "win32":
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
