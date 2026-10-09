"""Secret screen for threads a guest can read (epic-0cec8d1c31 S5, design-b6a55eed13 §4.B "agent rule plus guard").

On an epic with guest members, message_send, doc_create/update/edit and artifact finalise run `check(text)`.
Content that matches a key format, a token pattern, or a LIVE secret value (tokens.json, the secrets dir,
the secret settings file, the admin token file, .env files) is REFUSED, never redacted: the error names the
pattern class so the seat rewrites without the secret. This is defence in depth, not a guarantee: a secret
in a form no pattern knows (paraphrased, split, encoded) passes. The agent rule in shared-host-rules is the
first line: from_role != owner is untrusted; never send secrets, tokens, env values or host files to anyone
but the owner.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Iterable

#: (pattern class, regex). Order: the most specific class first, so the error names the best match.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY(?: BLOCK)?-----")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{32,}")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")),
    ("aws-secret-key", re.compile(r"(?i)aws_?secret_?access_?key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+=]{40}")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("bearer-token", re.compile(r"(?i)\b(?:authorization:\s*)?bearer\s+[A-Za-z0-9_\-\.=]{24,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("api-key-header", re.compile(r"(?i)\bx-api-key[\"']?\s*[:=]\s*[\"']?[^\s\"']{8,}")),
    # a secret-shaped NAME assigned a value; the value may hold any non-space character (p&ss!word …)
    ("token-assignment", re.compile(
        r"(?i)\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|_PASS|PRIVATE_KEY|API_?KEY|AUTH)[A-Z0-9_]*[\"']?\s*[:=]\s*"
        r"[\"']?[^\s\"'<>]{8,}")),
    # host files: a user-profile path names the host account and where its secrets live
    ("host-path", re.compile(r"(?i)(?:\b[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"']+|(?<![A-Za-z0-9])/[a-z]/Users/[^/\s\"']+"
                             r"|%(?:LOCALAPPDATA|APPDATA|USERPROFILE)%)")),
]

#: an .env key whose value is a secret; only these are screened (EDP8_OWNER=<handle> is not a secret)
SECRET_ENV_KEY = re.compile(r"(?i)(TOKEN|KEY|SECRET|PASS|PRIVATE|AUTH|CREDENTIAL|COOKIE|SESSION|DSN|SALT|CERT)")

MIN_SECRET_LEN = 8  # a live value shorter than this is too common to screen for (and too weak to be a secret)


class SecretFound(Exception):
    def __init__(self, cls: str) -> None:
        super().__init__(cls)
        self.cls = cls


def _strings(v: Any) -> Iterable[str]:
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _strings(x)


def _file_values(f: Path) -> list[str]:
    try:
        text = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if f.suffix == ".json":
        try:
            return list(_strings(json.loads(text)))
        except ValueError:
            pass
    if f.suffix == ".toml":
        return [m.group(1) for m in re.finditer(r"=\s*[\"']([^\"']+)[\"']", text)]
    if f.name == ".env" or f.suffix == ".env":
        return env_values(text)
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def env_values(text: str) -> list[str]:
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        v = v.strip().strip("\"'")
        if v and SECRET_ENV_KEY.search(k.removeprefix("export ")):
            out.append(v)
    return out


def live_values(extra_files: Iterable[Path] = ()) -> dict[str, str]:
    """value → class for every live secret this host holds. Read on each call (files are small and change
    when a token is minted), so a token minted a second ago is already screened."""
    from edp_contracts import settings as cs
    found: dict[str, str] = {}

    def add(values: Iterable[str], cls: str) -> None:
        for v in values:
            v = v.strip()
            if len(v) >= MIN_SECRET_LEN and v not in found:
                found[v] = cls

    try:
        tokens = Path(cs.get("EDP8_TOKENS"))
        add(_file_values(tokens), "live-token")
    except Exception:  # noqa: BLE001 — an unreadable tokens file screens nothing extra
        tokens = None
    try:
        sd = cs.secrets_dir()
        files = [cs.admin_token_file(), cs.secret_settings_file()]
        if sd.name == "secrets" and sd.is_dir():  # installed layout: everything in secrets/ is a secret
            files += [f for f in sd.iterdir() if f.is_file()]
        for f in files:
            if tokens is None or f != tokens:
                add(_file_values(f), "secrets-file")
    except Exception:  # noqa: BLE001
        pass
    for f in _env_files(extra_files):
        try:
            add(env_values(f.read_text(encoding="utf-8")), "env-value")
        except (OSError, UnicodeDecodeError):
            continue
    from edp_contracts import settings as cs
    admin = cs.env_raw("EDP8_ADMIN_TOKEN")
    if admin and admin != "dev":
        add([admin], "live-token")
    return found


def _env_files(extra: Iterable[Path]) -> list[Path]:
    from edp_contracts import settings as cs
    cands = [Path.cwd() / ".env", *extra]
    try:
        h = cs.home()
        if h is not None:
            cands += [Path(h) / ".env", Path(h).parent / ".env"]
        cands.append(cs.config_dir() / ".env")
    except Exception:  # noqa: BLE001
        pass
    seen, out = set(), []
    for f in cands:
        try:
            r = f.resolve()
        except OSError:
            continue
        if r not in seen and r.is_file():
            seen.add(r)
            out.append(r)
    return out


def match(text: str, values: dict[str, str] | None = None) -> str | None:
    """The pattern class `text` matches, or None. Live values first: a minted token is the worst leak."""
    if not text:
        return None
    vals = live_values() if values is None else values
    for v, cls in vals.items():
        if v in text:
            return cls
    for cls, rx in PATTERNS:
        if rx.search(text):
            return cls
    return None


WITHHELD = "[withheld from a guest: matches a secret ({cls})]"


def withhold(value: Any, values: dict[str, str] | None = None) -> Any:
    """The READ-side screen (review m-33154269a9 #7): any string a guest would read that matches a secret is
    replaced whole by a marker naming the class. This covers text written before the guest joined and text
    no write path screens (status notes, titles, descriptions, criteria, gate notes, quotes, linked docs)."""
    vals = live_values() if values is None else values

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            # S18-1: a derived representation (HTML) is also screened as the text it shows
            cls = (match(v, vals) or ("&" in v and match(html.unescape(v), vals))) if len(v) >= MIN_SECRET_LEN else None
            return WITHHELD.format(cls=cls) if cls else v
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v
    return walk(value)


def check(text: str, *, where: str) -> None:
    """Raise BoardError(secret) naming the pattern class when `text` carries a secret (refuse, never redact)."""
    cls = match(text)
    if cls:
        from .board import BoardError
        raise BoardError(
            "secret", f"{where} refused: it matches a secret ({cls}) and this epic has guest members",
            "rewrite it without the secret: never send tokens, keys, env values or host files to anyone but "
            "the owner (shared-host-rules)")
