"""Per-person UI settings (epic-44a0576511 · s-7f663c6322): profile, notifications, Slack.

One JSON file at the agent home (`EDP8_HOME/ui-settings.json`, EDP8_UI_SETTINGS overrides),
keyed by the person's @handle so the Slack bridge can merge it straight over `slack_map.json`
(people are keyed by handle there too). Same failure-tolerant, atomic-write shape as
`avatar_preferences.py`: an absent or damaged file behaves like an empty one. Secrets never
leave this file in the clear — `public()` masks the webhook before it reaches the SPA.
"""

from __future__ import annotations

import ipaddress
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Finding 12: save_settings is read-merge-write against one shared JSON file. Two people (two
# request threads) saving at once raced — on Windows one hit PermissionError (the atomic replace
# lost to the other's open temp handle → a 500) and only one person's settings survived. Serialise
# the whole read-merge-write so concurrent saves are last-writer-wins per field but never lose a
# person or 500. One process owns the file (single board), so a threading.Lock is sufficient.
_SAVE_LOCK = threading.Lock()

_MAX_NAME = 80
_MAX_URL = 400
MASK_PREFIX = "https://***"  # legacy mask marker, still recognised on the echo path
MASK_MARK = "…"  # the ellipsis in a masked webhook — a real Slack webhook never contains it


def webhook_hosts() -> set[str]:
    """The webhook host allow-list: hooks.slack.com plus any operator-provisioned hosts in
    EDP8_SLACK_WEBHOOK_HOSTS (comma-separated). The board must never POST thread content to an
    arbitrary internal or external address (qa finding 10)."""
    hosts = {"hooks.slack.com"}
    extra = os.environ.get("EDP8_SLACK_WEBHOOK_HOSTS", "")
    hosts |= {h.strip().lower() for h in extra.split(",") if h.strip()}
    return hosts


def is_masked_webhook(url: str) -> bool:
    """A value the SPA echoed back from public() — never a real destination to store or post to."""
    return bool(url) and (url.startswith(MASK_PREFIX) or MASK_MARK in url)


def valid_webhook(url: str) -> bool:
    """A webhook URL is postable only if it is https, carries no userinfo (finding 17), is not an IP
    literal, and its host is on the allow-list (finding 10). Enforced at save AND at send, so a
    stored legacy value on a now-disallowed host is never posted to."""
    if not url or is_masked_webhook(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme != "https":
        return False
    if parts.username or parts.password or "@" in (parts.netloc or ""):
        return False
    host = (parts.hostname or "").lower()
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return False  # reject IP literals outright
    except ValueError:
        pass
    return host in webhook_hosts()


def settings_path() -> Path:
    override = os.environ.get("EDP8_UI_SETTINGS")
    if override:
        return Path(override)
    home = Path(os.environ.get("EDP8_HOME", str(Path(__file__).resolve().parents[2])))
    return home / "ui-settings.json"


def default_settings() -> dict[str, Any]:
    return {
        "profile": {"display_name": "", "timezone": ""},
        "notifications": {"browser": False, "quiet": None},
        "slack": {"enabled": False, "slack_id": "", "webhook_url": "", "quiet": None},
    }


def _quiet(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        start, end = int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None
    if not (0 <= start <= 23 and 0 <= end <= 23) or start == end:
        return None
    return [start, end]


def normalise(raw: Any) -> dict[str, Any]:
    """Coerce a submitted or stored blob into the canonical shape; unknown keys are dropped."""
    out = default_settings()
    if not isinstance(raw, dict):
        return out
    prof = raw.get("profile") if isinstance(raw.get("profile"), dict) else {}
    out["profile"]["display_name"] = str(prof.get("display_name") or "")[:_MAX_NAME].strip()
    out["profile"]["timezone"] = str(prof.get("timezone") or "")[:64].strip()
    notif = raw.get("notifications") if isinstance(raw.get("notifications"), dict) else {}
    out["notifications"]["browser"] = bool(notif.get("browser", False))
    out["notifications"]["quiet"] = _quiet(notif.get("quiet"))
    slack = raw.get("slack") if isinstance(raw.get("slack"), dict) else {}
    out["slack"]["enabled"] = bool(slack.get("enabled", False))
    out["slack"]["slack_id"] = str(slack.get("slack_id") or "")[:64].strip()
    url = str(slack.get("webhook_url") or "")[:_MAX_URL].strip()
    out["slack"]["webhook_url"] = url if valid_webhook(url) else ""
    out["slack"]["quiet"] = _quiet(slack.get("quiet"))
    return out


def load_all(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    target = Path(path) if path is not None else settings_path()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {str(handle): normalise(blob) for handle, blob in value.items() if isinstance(blob, dict)}


def load_settings(handle: str, path: str | Path | None = None) -> dict[str, Any]:
    return load_all(path).get(str(handle)) or default_settings()


def save_settings(handle: str, raw: Any, path: str | Path | None = None) -> dict[str, Any]:
    """Atomically replace one person's settings; returns the stored (normalised) blob.

    Finding 12: the read-merge-write is serialised under `_SAVE_LOCK` so two people saving at the
    same time cannot lose a person or trip a Windows PermissionError during the atomic replace."""
    target = Path(path) if path is not None else settings_path()
    with _SAVE_LOCK:
        target.parent.mkdir(parents=True, exist_ok=True)
        everything = load_all(target)
        stored = normalise(raw)
        # the SPA echoes the masked webhook back on every save: keep the one on disk
        submitted = str(((raw or {}).get("slack") or {}).get("webhook_url") or "") if isinstance(raw, dict) else ""
        if is_masked_webhook(submitted):
            previous = everything.get(str(handle)) or default_settings()
            stored["slack"]["webhook_url"] = previous["slack"]["webhook_url"]
        everything[str(handle)] = stored
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                                             prefix=f".{target.name}.", suffix=".tmp",
                                             delete=False) as stream:
                json.dump(everything, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
                temporary = Path(stream.name)
            temporary.replace(target)
        finally:
            if temporary is not None and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass
    return stored


def public(settings: dict[str, Any]) -> dict[str, Any]:
    """What the SPA sees: the webhook is masked to scheme + host + the last 4 characters of the
    path, never the secret token (finding 17: the old mask leaked URL userinfo)."""
    out = json.loads(json.dumps(settings))
    url = out["slack"].get("webhook_url") or ""
    if url:
        parts = urlsplit(url)
        host = parts.hostname or "slack"
        tail = parts.path[-4:] if parts.path else ""
        out["slack"]["webhook_url"] = f"{parts.scheme or 'https'}://{host}/{MASK_MARK}{tail}"
        out["slack"]["webhook_set"] = True
    else:
        out["slack"]["webhook_set"] = False
    return out


def bridge_people(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """The Slack bridge's view: handle → {slack_id, webhook_url, quiet} for every person who
    switched Slack on and gave the bridge somewhere to post."""
    people: dict[str, dict[str, Any]] = {}
    for handle, s in load_all(path).items():
        slack = s["slack"]
        if not slack["enabled"] or not (slack["slack_id"] or slack["webhook_url"]):
            continue
        people[handle] = {"slack_id": slack["slack_id"] or None,
                          "webhook_url": slack["webhook_url"] or None,
                          "quiet": slack["quiet"] or s["notifications"]["quiet"]}
    return people
