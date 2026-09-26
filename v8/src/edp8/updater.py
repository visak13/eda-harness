"""`heronry update`: check for and apply a new app release (design-e963c656f5 §4.10 app row,
strategyhl-86b4805322 §4, S3 s-870e401942).

``heronry update --check`` asks GitHub for the latest release (ETag, at most daily, silent offline,
opt-out ``HERONRY_NO_UPDATE_CHECK=1``); ``start`` runs the same check quietly. ``heronry update`` applies:

1. fetch the release (GitHub latest, or ``--release-url <dir|http base>``) into ``<data>/updates/<ver>``
   and verify every wheel against ``SHA256SUMS``; a downgrade is refused;
2. **compat check** (S13, architect m-3ab493d55b): the NEW release's ``heronry workflows check --db <live
   db> --json`` through ``uv tool run``. Exit 1 aborts with a per-workflow report; exit 2 (usage error or
   no DB) refuses unless ``--skip-compat``. Nothing has changed at this point;
3. refuse while seats are live (unless ``--force``: the pool stop takes them offline);
4. back up the DB (SQLite backup + ``integrity_check``) to ``<data>/backups/edp8-<old>-<ts>.db``, keep 5;
5. stop the supervisor and every service;
6. start the detached helper (:mod:`edp8.update_helper`) outside the tool venv and exit, so no process
   holds the venv; it runs ``uv tool install --force <edp8 wheel> --with <siblings>``, starts, checks
   health, and rolls back (previous cached artefacts + the DB backup) on any failure.

Progress goes to ``<logs>/update.log``; the outcome to ``<run>/update-result.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import settings

#: the wheels a release ships (wheel-file distribution names); edp8 is the tool, the rest go --with
WHEELS = ("edp8", "edp_contracts", "edp_pool", "edp_broker")
KEEP_BACKUPS = 5
CHECK_EVERY_S = 24 * 3600
DOCTOR_HINT = "run `heronry doctor` (the workflow section) to see how to fix each one"


class UpdateError(RuntimeError):
    """The update stopped; the message is one plain line and nothing was changed unless it says so."""


# ------------------------------------------------------------------------------------------ versions

def current_version() -> str:
    from importlib.metadata import version
    try:
        return version("edp8")
    except Exception:  # noqa: BLE001
        return "0"


def _v(s: str) -> tuple[int, ...]:
    """The numeric release segment ('v0.9.1' -> (0, 9, 1)); edp8 publishes plain X.Y.Z versions, so no
    `packaging` dependency is taken for this."""
    head = s.strip().removeprefix("v").split("+")[0]
    nums = []
    for part in head.split("."):
        digits = "".join(ch for ch in part if ch.isdigit()) if part[:1].isdigit() else ""
        if not digits:
            break
        nums.append(int(digits))
    while len(nums) > 1 and nums[-1] == 0:
        nums.pop()
    return tuple(nums) or (0,)


def wheel_dist(name: str) -> tuple[str, str] | None:
    """('edp8', '0.9.0') for 'edp8-0.9.0-py3-none-any.whl'."""
    if not name.endswith(".whl"):
        return None
    parts = name[:-4].split("-")
    return (parts[0], parts[1]) if len(parts) >= 5 else None


# ------------------------------------------------------------------------------------------ release

@dataclass
class Release:
    version: str
    files: dict[str, str]                       # file name -> URL or local path
    sums: dict[str, str] = field(default_factory=dict)
    notes: str = ""


def _get(url: str, *, timeout: float = 30.0, headers: dict[str, str] | None = None):
    import httpx
    return httpx.get(url, timeout=timeout, headers=headers or {}, follow_redirects=True)


def _read(src: str) -> bytes:
    if src.startswith(("http://", "https://")):
        r = _get(src, timeout=120.0)
        r.raise_for_status()
        return r.content
    return Path(src.removeprefix("file://")).read_bytes()


def parse_sums(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and len(parts[0]) == 64:
            out[parts[1].lstrip("*")] = parts[0].lower()
    return out


def fetch_release(url: str | None) -> Release:
    """The release at `url` (a local dir or an http base holding SHA256SUMS and the wheels), else GitHub's
    latest release of `update.repo`."""
    if url:
        base = url.rstrip("/")
        sums = parse_sums(_read(f"{base}/SHA256SUMS").decode("utf-8"))
        files = {n: f"{base}/{n}" for n in sums}
    else:
        r = _get(f"https://api.github.com/repos/{settings.get('EDP_UPDATE_REPO')}/releases/latest",
                 headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        rel = r.json()
        files = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        if "SHA256SUMS" not in files:
            raise UpdateError(f"release {rel.get('tag_name')} has no SHA256SUMS; refusing an unverifiable update")
        sums = parse_sums(_read(files["SHA256SUMS"]).decode("utf-8"))
    wheels = {wheel_dist(n)[0]: n for n in files if wheel_dist(n)}
    missing = [w for w in WHEELS if w not in wheels]
    if missing:
        raise UpdateError(f"the release lacks wheel(s) {', '.join(missing)}")
    return Release(version=wheel_dist(wheels["edp8"])[1], files={wheels[w]: files[wheels[w]] for w in WHEELS},
                   sums=sums)


def download(rel: Release) -> dict[str, Path]:
    """Every wheel into <data>/updates/<ver>/, each verified against SHA256SUMS: {dist: path}."""
    dest = settings.data_dir() / "updates" / rel.version
    dest.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for name, src in rel.files.items():
        want = rel.sums.get(name)
        if not want:
            raise UpdateError(f"{name} is not listed in SHA256SUMS; refusing it")
        data = _read(src)
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            raise UpdateError(f"SHA256 mismatch for {name} (expected {want[:12]}…, got {got[:12]}…); nothing changed")
        p = dest / name
        p.write_bytes(data)
        out[wheel_dist(name)[0]] = p
    (dest / "SHA256SUMS").write_text("".join(f"{rel.sums[n]}  {n}\n" for n in rel.files), encoding="utf-8")
    return out


def cached(version: str) -> dict[str, Path] | None:
    """The verified wheels of `version` kept by an earlier update/install, for a rollback."""
    d = settings.data_dir() / "updates" / version
    sums_f = d / "SHA256SUMS"
    if not sums_f.is_file():
        return None
    sums = parse_sums(sums_f.read_text(encoding="utf-8"))
    out: dict[str, Path] = {}
    for name, want in sums.items():
        p, dist = d / name, wheel_dist(name)
        if dist and p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == want:
            out[dist[0]] = p
    return out if all(w in out for w in WHEELS) else None


# ------------------------------------------------------------------------------------------ commands

def _override(env: str, subst: dict[str, list[str]]) -> list[str] | None:
    raw = settings.env_raw(env)
    if not raw:
        return None
    argv: list[str] = []
    for tok in json.loads(raw):
        argv.extend(subst.get(tok, [tok]))
    return argv


def _uv() -> str:
    from edp_contracts.toolpath import find_tool
    uv = find_tool("uv")
    if not uv:
        raise UpdateError("uv is not on PATH (the installer puts it there); run the install script again")
    return uv


def install_argv(wheels: dict[str, Path]) -> list[str]:
    siblings = [str(wheels[w]) for w in WHEELS if w != "edp8"]
    over = _override("EDP_UPDATE_INSTALL_CMD", {"{wheel}": [str(wheels["edp8"])], "{with}": siblings})
    if over is not None:
        return over
    argv = [_uv(), "tool", "install", "--force", str(wheels["edp8"])]
    for s in siblings:
        argv += ["--with", s]
    return argv


def compat_argv(wheels: dict[str, Path], db: Path) -> list[str]:
    over = _override("EDP_UPDATE_COMPAT_CMD", {"{db}": [str(db)], "{wheel}": [str(wheels["edp8"])]})
    if over is not None:
        return over
    argv = [_uv(), "tool", "run", "--from", str(wheels["edp8"])]
    for w in WHEELS[1:]:
        argv += ["--with", str(wheels[w])]
    return [*argv, "heronry", "workflows", "check", "--db", str(db), "--json"]


def compat_check(wheels: dict[str, Path], db: Path) -> tuple[int, list[dict[str, Any]], str]:
    """THE seam (architect m-3ab493d55b): (exit code, rows, stderr) of the new release's workflow check."""
    r = subprocess.run(compat_argv(wheels, db), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600, stdin=subprocess.DEVNULL)
    try:
        rows = json.loads(r.stdout or "[]")
        rows = rows if isinstance(rows, list) else []
    except ValueError:
        rows = []
    return r.returncode, rows, r.stderr.strip()


def backup_db(db: Path, version: str) -> Path:
    d = settings.data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = d / f"edp8-{version}-{ts}.db"
    src = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    dst = sqlite3.connect(out)
    try:
        src.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        dst.close()
        src.close()
    if ok != "ok":
        out.unlink(missing_ok=True)
        raise UpdateError(f"the DB backup failed integrity_check ({ok}); nothing changed")
    for old in sorted(d.glob("edp8-*.db"), key=lambda p: p.stat().st_mtime)[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)
    return out


def _uv_tool_env() -> bool:
    """True when this interpreter runs from a `uv tool install` environment (uv writes a receipt)."""
    return (Path(sys.prefix) / "uv-receipt.toml").is_file()


# ------------------------------------------------------------------------------------------ check

def _state_file() -> Path:
    return settings.run_dir() / "update-check.json"


def check(*, force: bool = False, timeout: float = 3.0) -> dict[str, Any] | None:
    """{current, latest, newer} from GitHub's latest release, at most once per CHECK_EVERY_S unless
    forced; None when opted out, in dev mode, or offline (never an error)."""
    if not force and (settings.get("HERONRY_NO_UPDATE_CHECK") or settings.dev_mode()):
        return None
    f = _state_file()
    try:
        state = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    now = time.time()
    if force or now - float(state.get("checked_at", 0)) >= CHECK_EVERY_S:
        headers = {"Accept": "application/vnd.github+json"}
        if state.get("etag"):
            headers["If-None-Match"] = state["etag"]
        try:
            r = _get(f"https://api.github.com/repos/{settings.get('EDP_UPDATE_REPO')}/releases/latest",
                     headers=headers, timeout=timeout)
        except Exception:  # noqa: BLE001 — offline is silent
            return None
        if r.status_code == 200:
            rel = r.json()
            state.update(latest=str(rel.get("tag_name", "")).removeprefix("v"), etag=r.headers.get("ETag"),
                         url=rel.get("html_url"))
        elif r.status_code != 304:
            return None  # 403 rate limit, 404 no release yet: silent
        state["checked_at"] = now
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            pass
    latest, cur = state.get("latest"), current_version()
    if not latest:
        return None
    try:
        newer = _v(latest) > _v(cur)
    except Exception:  # noqa: BLE001
        newer = False
    return {"current": cur, "latest": latest, "newer": newer, "url": state.get("url")}


def notice() -> str | None:
    """One line for `start` when a newer release exists (quiet otherwise)."""
    got = check()
    if got and got["newer"]:
        return f"heronry {got['latest']} is available (you have {got['current']}): `heronry update`"
    return None


# ------------------------------------------------------------------------------------------ apply

def _print_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        mark = "ok  " if row.get("ok") else "FAIL"
        print(f"  {mark} {row.get('workflow')}@{row.get('version')}")
        for e in row.get("errors") or []:
            print(f"         - {e}")


def _stop_all() -> None:
    from . import launcher
    launcher.stop_supervisor()
    for svc in reversed(launcher.ORDER):
        out = launcher.stop(svc)
        if out["survivors"]:
            raise UpdateError(f"{svc} did not stop ({out['survivors']}); the DB backup is kept, nothing was installed")


def apply(opts: dict[str, Any]) -> int:
    from . import launcher

    if launcher.bundled():
        raise UpdateError("the desktop bundle updates through its installer; download the new release")
    if settings.dev_mode():
        raise UpdateError("this is a source checkout (dev mode): update it with git, not `heronry update`")
    if not _uv_tool_env() and not settings.env_raw("EDP_UPDATE_INSTALL_CMD"):
        raise UpdateError("this install was not made by `uv tool install`; re-run the install script instead")

    cur = current_version()
    rel = fetch_release(opts.get("release-url") if isinstance(opts.get("release-url"), str) else None)
    print(f"current {cur}, release {rel.version}")
    if _v(rel.version) < _v(cur) and not opts.get("allow-downgrade"):
        raise UpdateError(f"{rel.version} is older than {cur}; refusing a downgrade (--allow-downgrade)")
    if _v(rel.version) == _v(cur) and not opts.get("force"):
        print("already up to date")
        return 0
    wheels = download(rel)
    print(f"verified {len(wheels)} wheels against SHA256SUMS")

    db = Path(settings.get("EDP8_DB"))
    if opts.get("skip-compat"):
        print("WARNING: --skip-compat: custom workflows were not checked against the new version")
    else:
        rc, rows, err = compat_check(wheels, db)
        if rc == 1:
            print(f"update aborted: {sum(1 for r in rows if not r.get('ok'))} workflow(s) fail on {rel.version}:")
            _print_rows(rows)
            print(f"nothing changed (DB, services and version as before); {DOCTOR_HINT}")
            return 1
        if rc != 0:
            raise UpdateError(f"the compatibility check could not run (exit {rc}: {err or 'no output'}); "
                              "nothing changed. `--skip-compat` updates without it")
        print(f"compat check passed ({len(rows)} workflow(s))")

    seats = launcher.live_seats() if launcher.running("pool") else []
    if seats and not opts.get("force"):
        raise UpdateError(f"{len(seats)} seat(s) are live ({', '.join(seats[:5])}); let them finish or park "
                          "them, or repeat with --force to take them offline")
    if opts.get("dry-run"):
        print("dry run: would back up the DB, stop, install and start; nothing changed")
        return 0

    backup = backup_db(db, cur) if db.is_file() else None
    if backup:
        print(f"backed up the DB to {backup}")
    _stop_all()
    print("stopped the supervisor and services")

    prev = cached(cur)
    run = settings.run_dir()
    run.mkdir(parents=True, exist_ok=True)
    result = run / "update-result.json"
    result.unlink(missing_ok=True)
    log = settings.logs_dir() / "update.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    helper = run / "update-helper.py"
    shutil.copyfile(Path(__file__).with_name("update_helper.py"), helper)
    me = [sys.executable, "-m", "edp8.cli"]
    plan = {"caller_pid": os.getpid(), "from_version": cur, "to_version": rel.version,
            "install_argv": install_argv(wheels), "rollback_install_argv": install_argv(prev) if prev else None,
            "start_argv": [*me, "start"], "stop_argv": [*me, "stop", "--force"],
            "health_url": f"{launcher.url('board')}/v1/health", "db": str(db), "backup": str(backup or ""),
            "log": str(log), "result": str(result)}
    plan_f = run / "update-plan.json"
    plan_f.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    from edp_contracts.proc import detach
    py = getattr(sys, "_base_executable", None) or sys.executable
    detach([py, str(helper), str(plan_f)], cwd=str(run), env=settings.environ_copy(),
           log=str(run / "update-helper.out"))
    print(f"installing {rel.version} in the background; progress in {log}, outcome in {result}. "
          "`heronry status` shows the services when it is done.")
    return 0


def main(argv: list[str]) -> int:
    from .cli import _split

    _, opts = _split(argv)
    if opts.get("check"):
        got = check(force=True, timeout=10.0)
        if got is None:
            print("could not reach GitHub (or no release yet)")
            return 0
        print(f"current {got['current']}, latest {got['latest']}"
              + (f" — `heronry update` installs it ({got['url']})" if got["newer"] else " — up to date"))
        return 0
    try:
        return apply(opts)
    except UpdateError as e:
        print(f"update refused: {e}", file=sys.stderr)
        return 2
    except OSError as e:  # httpx.HTTPError is not one; caught below
        print(f"update refused: could not read the release ({e}); nothing changed", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        import httpx
        if isinstance(e, httpx.HTTPError):
            print(f"update refused: could not fetch the release ({e}); nothing changed", file=sys.stderr)
            return 2
        raise
