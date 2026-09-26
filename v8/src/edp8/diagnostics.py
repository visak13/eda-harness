"""S19 diagnostics (design-e963c656f5 §4.14(e).5): the redaction scrubber and `heronry doctor --bundle`.

`Scrubber` removes what must never leave the machine in a diagnostics zip or a doctor log tail:
- every known secret VALUE (tokens.json leaves, the admin token, secret settings, token-shaped env vars);
- user-profile paths (`C:\\Users\\<u>`, `/home/<u>`, `/Users/<u>`, in any slash style, JSON-escaped too)
  and the literal home directory;
- the OS username;
- email addresses;
- generic token shapes (Bearer values, `token=`/`X-Token:` values, `sk-…`, GitHub/Slack tokens, long
  mixed-case base64url runs).

`write_bundle` builds the zip a user attaches to a GitHub issue: versions, the masked settings listing,
service status, log tails and the workflow definitions. Every text member goes through one scrubber.
"""

from __future__ import annotations

import getpass
import json
import os
import platform
import re
import sys
import tempfile
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import settings

MIN_SECRET = 6
LOG_LINES = 400
_ENV_SECRET = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|_KEY$", re.I)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# a Windows profile path in any slash style, including JSON's doubled backslash
_WIN_HOME = re.compile(r"(?i)\b([A-Z]:)(\\\\|\\|/)(Users|Documents and Settings)(\\\\|\\|/)[^\\/\s\"'<>|:;,]+")
_POSIX_HOME = re.compile(r"(?<![\w.])/(home|Users)/[^/\s\"'<>|:;,]+")
_TOKEN_SHAPES = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1<token>"),
    (re.compile(r"(?i)((?:x-token|x-admin|x-edp-control|authorization|token|secret|password|passwd|"
                r"api[_-]?key|access[_-]?key)[\"']?\s*[:=]\s*[\"']?)(?!<)[^\s\"',;&}]{6,}"), r"\1<token>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "<token>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "<token>"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "<token>"),
    (re.compile(r"\btskey-[A-Za-z0-9-]{10,}"), "<token>"),
]
# token_urlsafe-style runs: >= 24 chars mixing upper, lower and digits (a hex hash or a word never matches)
_LONG_RUN = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_-])")


def _looks_random(s: str) -> bool:
    return any(c.isupper() for c in s) and any(c.islower() for c in s) and any(c.isdigit() for c in s)


def _leaves(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaves(v)
    elif isinstance(obj, str):
        yield obj


def known_secrets() -> list[str]:
    """Every secret value this install holds: tokens.json, admin.token, the secret settings, and env vars
    whose NAME says token/secret/key/password. Values shorter than MIN_SECRET are skipped (they would
    scrub ordinary words)."""
    out: set[str] = set()
    for f in {Path(settings.get("EDP8_TOKENS")), settings.secrets_dir() / "tokens.json"}:
        try:
            out.update(_leaves(json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            pass
    try:  # the imported legacy human token list (importer._SECRETS); its token fields, never the handles
        for line in (settings.secrets_dir() / "human-tokens.txt").read_text(encoding="utf-8").splitlines():
            out.update(w for w in re.split(r"[\s=:,]+", line) if len(w) >= 16)
    except OSError:
        pass
    try:
        out.add(settings.admin_token() or "")
    except Exception:  # noqa: BLE001 — a missing/looser admin token file is doctor's to report, not ours
        pass
    for s in settings.all_settings():
        if s.secret:
            try:
                v = settings.get(s.env)
            except Exception:  # noqa: BLE001
                continue
            if v:
                out.add(str(v))
    for k, v in os.environ.items():
        if _ENV_SECRET.search(k) and v:
            out.add(v)
    return sorted((s for s in out if s and len(s) >= MIN_SECRET and s.strip() == s), key=len, reverse=True)


def _user_names() -> list[str]:
    names = {os.environ.get("USERNAME", ""), os.environ.get("USER", "")}
    try:
        names.add(getpass.getuser())
    except Exception:  # noqa: BLE001
        pass
    names.add(Path.home().name)
    return sorted((n for n in names if len(n) >= 3), key=len, reverse=True)


class Scrubber:
    """One redaction pass over text. Built once per bundle (the secret list is read once)."""

    def __init__(self, secrets: Iterable[str] | None = None, usernames: Iterable[str] | None = None,
                 homes: Iterable[str] | None = None):
        self.secrets = [s for s in (known_secrets() if secrets is None else secrets) if len(s) >= MIN_SECRET]
        self.usernames = list(_user_names() if usernames is None else usernames)
        hs = [str(Path.home())] if homes is None else list(homes)
        variants: set[str] = set()
        for h in hs:
            if len(h) < 4:
                continue
            variants |= {h, h.replace("\\", "/"), h.replace("\\", "\\\\"), h.replace("/", "\\")}
        self.homes = sorted(variants, key=len, reverse=True)
        self._user_res = [re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(u) + r"(?![A-Za-z0-9])")
                          for u in self.usernames]

    def __call__(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "<secret>")
        for h in self.homes:
            text = text.replace(h, "<home>")
        text = _WIN_HOME.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}<user>", text)
        text = _POSIX_HOME.sub(lambda m: f"/{m.group(1)}/<user>", text)
        text = _EMAIL.sub("<email>", text)
        for rx, rep in _TOKEN_SHAPES:
            text = rx.sub(rep, text)
        text = _LONG_RUN.sub(lambda m: "<token>" if _looks_random(m.group(0)) else m.group(0), text)
        for rx in self._user_res:
            text = rx.sub("<user>", text)
        return text

    def json(self, obj: Any) -> str:
        return self(json.dumps(obj, indent=2, default=str))


def tail(path: Path, lines: int = LOG_LINES) -> str:
    """The last `lines` lines of a text file (read from the end; a huge log is never loaded whole)."""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block, data = 64 * 1024, b""
            while size > 0 and data.count(b"\n") <= lines:
                step = min(block, size)
                size -= step
                f.seek(size)
                data = f.read(step) + data
    except OSError as e:
        return f"<unreadable: {type(e).__name__}>"
    return "\n".join(data.decode("utf-8", "replace").splitlines()[-lines:])


def log_files() -> list[Path]:
    """The service logs (logs_dir: <svc>.log, update-run.out) and the pool's own log folder."""
    dirs = [settings.logs_dir(), settings.data_dir() / "pool-logs"]
    out: list[Path] = []
    for d in dirs:
        try:
            out += sorted(p for p in d.iterdir() if p.is_file() and p.suffix in (".log", ".out", ".txt"))
        except OSError:
            continue
    return out


# ----------------------------------------------------------------------------- the zip's sections
def versions() -> dict[str, Any]:
    from importlib import metadata

    from edp_contracts.toolpath import probe_version, tool_argv

    from .setup import detect_harnesses

    pkgs = {}
    for name in ("edp8", "edp-pool", "edp-broker", "edp-contracts"):
        try:
            pkgs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pkgs[name] = None
    harnesses = {}
    for h, path in detect_harnesses().items():
        ver = None
        if path:
            try:
                ver = probe_version(tool_argv(path))
            except Exception:  # noqa: BLE001 — a broken harness is reported, never fatal to the bundle
                ver = "probe failed"
        harnesses[h] = {"found": bool(path), "path": path, "version": ver}
    return {"product": settings.get("EDP_PRODUCT_NAME"), "packages": pkgs, "python": sys.version.split()[0],
            "platform": platform.platform(), "machine": platform.machine(), "dev_mode": settings.dev_mode(),
            "harnesses": harnesses}


def settings_listing() -> dict[str, Any]:
    from .admin.settings_api import listing
    return listing()


def services() -> dict[str, Any]:
    from . import launcher
    try:
        return {"services": launcher.status_rows()}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def workflows(db_path: Path | None = None) -> dict[str, Any]:
    """Every workflow definition, read from a scratch copy of the DB (the live DB is opened read-only and
    never written, as in workflow.check_db). Built-ins come from code, so they are always listed."""
    import sqlite3

    from .store import Store
    from .workflow import WorkflowRegistry, dump

    src = Path(db_path or settings.get("EDP8_DB"))
    if not src.is_file():
        from .workflow import build_standard
        return {"db": "none yet", "workflows": [dump(build_standard())]}
    with tempfile.TemporaryDirectory(prefix="edp-bundle-") as tmp:
        dst = Path(tmp) / "copy.db"
        s, d = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True), sqlite3.connect(dst)
        try:
            s.backup(d)
        finally:
            s.close()
            d.close()
        store = Store(str(dst))
        try:
            reg = WorkflowRegistry(store)
            rows = []
            for meta in reg.list():
                try:
                    rows.append(dump(reg.get(meta["id"], meta["version"])))
                except Exception as e:  # noqa: BLE001
                    rows.append({"ref": f"{meta['id']}@{meta['version']}", "error": f"{type(e).__name__}: {e}"})
            return {"db": "copy", "workflows": rows, "pinned": sorted(reg.pinned_refs())}
        finally:
            store.close()


def write_bundle(out: Path | None = None, *, lines: int = LOG_LINES, scrub: Scrubber | None = None,
                 db_path: Path | None = None) -> tuple[Path, list[str]]:
    """Write the diagnostics zip; returns (path, member names). Every member is scrubbed text."""
    scrub = scrub or Scrubber()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(out) if out else Path.cwd() / f"heronry-diagnostics-{stamp}.zip"
    if out.is_dir() or out.suffix.lower() != ".zip":  # a folder (existing or not): the zip goes inside it
        out = out / f"heronry-diagnostics-{stamp}.zip"

    def section(fn, *a) -> Any:
        try:
            return fn(*a)
        except Exception as e:  # noqa: BLE001 — one failing section never loses the rest of the bundle
            return {"error": f"{type(e).__name__}: {e}"}

    members: dict[str, str] = {
        "README.txt": ("Heronry diagnostics bundle, " + stamp + ".\n"
                       "Secrets, user paths, usernames, emails and tokens are scrubbed; check before attaching.\n"),
        "versions.json": scrub.json(section(versions)),
        "settings.json": scrub.json(section(settings_listing)),
        "services.json": scrub.json(section(services)),
        "workflows.json": scrub.json(section(workflows, db_path)),
    }
    for f in log_files():
        members[f"logs/{f.parent.name}-{f.name}" if f.parent.name == "pool-logs" else f"logs/{f.name}"] = \
            scrub(tail(f, lines))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, text in members.items():
            z.writestr(name, text)
    os.replace(tmp, out)
    return out, sorted(members)
