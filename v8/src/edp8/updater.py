"""`heronry update`: check for and apply a new app release (design-e963c656f5 §4.10 app row,
strategyhl-86b4805322 §4, S3 s-870e401942).

``heronry update --check`` asks GitHub for the latest release (ETag, at most daily, silent offline,
opt-out ``HERONRY_NO_UPDATE_CHECK=1``); ``start`` runs the same check quietly. ``heronry update`` applies:

1. fetch the release (GitHub latest, or ``--release-url <dir|http base>``) into ``<data>/updates/<ver>``
   and verify every wheel against ``SHA256SUMS``; a downgrade is refused;
2. **compat check** (S13, architect m-3ab493d55b): the NEW release's ``heronry workflows check --db <live
   db> --json`` through ``uv tool run``, run by the detached helper outside this process tree (owner AV ruling
   m-631a9ad2a7: the installed app never launches uv itself; unsigned exe -> uv -> python is what
   behaviour-based AV flags), which writes ``<run>/update-compat.json`` for this process to read. Exit 1 aborts with a per-workflow report; exit 2 (usage error or
   no DB) refuses unless ``--skip-compat``. Nothing has changed at this point;
3. secure the installed version's rollback (wheels, or its MSI; the cache, else its release, or ``--previous-url``)
   and refuse without it unless ``--force``; an unanswering pool (seats can't be parked) refuses unless ``--force``;
4. back up the DB (SQLite backup + ``integrity_check``) to ``<data>/backups/edp8-<old>-<ts>.db``, keep 5;
5. **park** the live seats (the pool resumes them afterwards: S10 #7), stop the supervisor and every service
   through the launcher;
6. start the detached runner (:mod:`edp8.update_helper`, stdlib only) from a copy OUTSIDE the install folder
   and exit, so nothing holds the install: the uv path runs ``uv tool install --force <edp8 wheel> --with
   <siblings>`` (receipt extras kept); the MSI path (the desktop bundle) closes the app and runs ``msiexec /i
   <new>.msi /qn`` (per-user MajorUpgrade, never ``/qb``). It then starts, checks health, and on any failure
   rolls back (the cached previous artefact + the DB backup) with a plain reason, resumes the seats and
   relaunches the app.

``apply`` is THE entry: ``heronry update`` and the tray's Install update both call it. Progress goes to
``<logs>/update.log``; the outcome to ``update-result.json`` (``<home>/update`` for the MSI runner, ``<run>``
for the uv helper) and a board event; ``last_result`` / ``result_text`` read it back.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import settings, update_lock

#: the wheels a release ships (wheel-file distribution names); edp8 is the tool, the rest go --with
WHEELS = ("edp8", "edp_contracts", "edp_pool", "edp_broker")
KEEP_BACKUPS = 5
CHECK_EVERY_S = 24 * 3600
DOCTOR_HINT = "run `heronry doctor` (the workflow section) to see how to fix each one"


class UpdateError(RuntimeError):
    """The update stopped; the message is one plain line and nothing was changed unless it says so."""


# ------------------------------------------------------------------------------------------ versions

def current_version() -> str:
    from . import __version__
    return __version__


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
        # maxsplit: an MSI's name holds a space ("Heronry Desktop-0.9.1.msi"); S2 found a plain split() dropped it
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and len(parts[0]) == 64:
            out[parts[1].lstrip("*")] = parts[0].lower()
    return out


def releases_url(tag: str | None = None) -> str:
    """GitHub's latest-release endpoint (or the release tagged `tag`) for `update.repo` under `update.api_url`."""
    base = f"{str(settings.get('EDP_UPDATE_API')).rstrip('/')}/repos/{settings.get('EDP_UPDATE_REPO')}/releases"
    return f"{base}/tags/{tag}" if tag else f"{base}/latest"


def fetch_release(url: str | None, tag: str | None = None) -> Release:
    """The release at `url` (a local dir or an http base holding SHA256SUMS and the wheels), else GitHub's
    release tagged `tag`, else its latest release of `update.repo`."""
    if url:
        base = url.rstrip("/")
        sums = parse_sums(_read(f"{base}/SHA256SUMS").decode("utf-8"))
        files = {n: f"{base}/{n}" for n in sums}
    else:
        r = _get(releases_url(tag),
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
        out["msi" if name.lower().endswith(".msi") else wheel_dist(name)[0]] = p
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


def secure_previous(version: str, url: str | None = None) -> dict[str, Path] | None:
    """The installed version's wheels for a rollback, secured before anything stops (S11 F7): the cache,
    else that release (`url`, else GitHub's tag v<version>) downloaded and verified into the cache. The
    install scripts do not seed the cache, so a first update needs the fetch. None when neither works."""
    got = cached(version)
    if got:
        return got
    try:
        rel = fetch_release(url, tag=None if url else f"v{version}")
        if _v(rel.version) != _v(version):
            return None
        download(rel)
    except Exception:  # noqa: BLE001 — offline, no such release, a bad sum: all mean "not secured"
        return None
    return cached(version)


def recover_hint(version: str) -> str:
    """The manual recovery line for when a rollback cannot reinstall `version`."""
    tag = f"v{version}"
    return (f"reinstall {version} with the install script: `.\\install.ps1 -Version {tag} -Force` "
            f"(Windows) or `sh install.sh --version {tag} --force`, then `heronry start`")


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


def receipt_extras(receipt: Path | None = None) -> list[str]:
    """The `--with` specs the installed tool environment carries beyond the release's own wheels (S2 finding 15: a
    `--force` reinstall rebuilds the environment from its argv alone, and the update dropped `proxy-tools`). Read from
    uv's receipt: a path or URL requirement as that, a named one as `name<specifier>`."""
    import tomllib
    f = receipt if receipt is not None else Path(sys.prefix) / "uv-receipt.toml"
    try:
        reqs = tomllib.loads(f.read_text(encoding="utf-8")).get("tool", {}).get("requirements", [])
    except (OSError, ValueError):
        return []
    own = {w.replace("_", "-") for w in WHEELS}
    out: list[str] = []
    for r in reqs:
        name = str(r.get("name", "")).lower().replace("_", "-")
        if not name or name in own:
            continue
        spec = r.get("path") or r.get("url") or f"{name}{r.get('specifier') or ''}"
        if spec not in out:
            out.append(str(spec))
    return out


def install_argv(wheels: dict[str, Path], extras: list[str] | None = None) -> list[str]:
    siblings = [str(wheels[w]) for w in WHEELS if w != "edp8"]
    over = _override("EDP_UPDATE_INSTALL_CMD", {"{wheel}": [str(wheels["edp8"])], "{with}": siblings})
    if over is not None:
        return over
    argv = [_uv(), "tool", "install", "--force", str(wheels["edp8"])]
    for s in siblings:
        argv += ["--with", s]
    for s in (receipt_extras() if extras is None else extras):
        argv += ["--with", s]
    # keep the embedder the installer added (t-08612be1b0): --force rebuilds the env from this argv alone
    import importlib.util
    if importlib.util.find_spec("fastembed") is not None:
        from edp_contracts.prereqs import by_name
        argv += ["--with", by_name("embedder").install["linux"][0].arg]
    return argv


def compat_argv(wheels: dict[str, Path], db: Path) -> list[str]:
    over = _override("EDP_UPDATE_COMPAT_CMD", {"{db}": [str(db)], "{wheel}": [str(wheels["edp8"])]})
    if over is not None:
        return over
    argv = [_uv(), "tool", "run", "--from", str(wheels["edp8"])]
    for w in WHEELS[1:]:
        argv += ["--with", str(wheels[w])]
    return [*argv, "heronry", "workflows", "check", "--db", str(db), "--json"]


COMPAT_TIMEOUT_S = 600.0


def _stage_helper(run: Path) -> Path:
    """The helper copied into the private run dir, so it runs outside the tool venv (see update_helper)."""
    run.mkdir(parents=True, exist_ok=True)
    helper = run / "update-helper.py"
    shutil.copyfile(Path(__file__).with_name("update_helper.py"), helper)
    shutil.copyfile(Path(__file__).with_name("update_lock.py"), run / "update_lock.py")
    return helper


def _await_compat(out: Path) -> tuple[int, list[dict[str, Any]], str]:
    deadline = time.monotonic() + COMPAT_TIMEOUT_S + 30.0
    while not out.is_file():
        if time.monotonic() > deadline:
            return 2, [], f"the detached compatibility check did not report within {COMPAT_TIMEOUT_S + 30:.0f}s"
        time.sleep(0.25)
    try:
        got = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return 2, [], f"the compatibility check's result could not be read ({e})"
    try:
        rows = json.loads(got.get("stdout") or "[]")
        rows = rows if isinstance(rows, list) else []
    except ValueError:
        rows = []
    return int(got.get("rc", 2)), rows, str(got.get("stderr") or "").strip()


def compat_check(wheels: dict[str, Path], db: Path) -> tuple[int, list[dict[str, Any]], str]:
    """THE seam (architect m-3ab493d55b): (exit code, rows, stderr) of the new release's workflow check.

    The check itself is `uv tool run`, so it runs in the detached helper (`--compat`), never as a child of
    this process (owner AV ruling m-631a9ad2a7); this waits for the helper's result file."""
    run = settings.run_dir()
    helper = _stage_helper(run)
    out = run / "update-compat.json"
    out.unlink(missing_ok=True)
    plan_f = run / "update-compat-plan.json"
    plan_f.write_text(json.dumps({"compat_argv": compat_argv(wheels, db), "compat_out": str(out),
                                  "timeout": COMPAT_TIMEOUT_S}, indent=1), encoding="utf-8")
    from edp_contracts.proc import detach
    py = getattr(sys, "_base_executable", None) or sys.executable
    detach([py, str(helper), "--compat", str(plan_f)], cwd=str(run), env=settings.environ_copy(),
           log=str(run / "update-compat.out"))
    return _await_compat(out)


def msi_compat_check(msi: Path, db: Path, stub: Path) -> tuple[int, list[dict[str, Any]], str]:
    """The same seam for the desktop bundle (S10 #2): the detached runner unpacks the NEW installer (`msiexec /a`),
    runs its own `heronry.exe workflows check --db <live db> --json`, and removes the unpacked copy. Nothing has
    stopped or changed. The unpack lands in a short path (<home>/update/x): the bundle's tree overflows MAX_PATH
    from a deep one."""
    from . import launcher
    from .brand import DESKTOP_APP_NAME
    from .update_helper import msi_property
    dest = update_dir()
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "update-compat.json"
    out.unlink(missing_ok=True)
    plan_f = dest / "update-compat-plan.json"
    plan_f.write_text(json.dumps({
        "extract": {"msi": str(msi), "dir": str(dest / "x"), "exe": launcher.CONSOLE_EXE,
                    "gui": f"{msi_property(str(msi), 'ProductName') or DESKTOP_APP_NAME}.exe"},
        "compat_args": ["workflows", "check", "--db", str(db), "--json"], "compat_out": str(out),
        "timeout": COMPAT_TIMEOUT_S}, indent=1), encoding="utf-8")
    from edp_contracts.proc import detach
    detach([str(stub), str(dest / "update-helper.py"), "--compat", str(plan_f)], cwd=str(dest),
           env=settings.environ_copy(), log=str(dest / "update-compat.out"), via=str(stub))
    return _await_compat(out)


def _compat_gate(opts: dict[str, Any], db: Path, run, version: str) -> int | None:
    """The compat gate both paths share (#2): None = go on; 1 = workflows fail on `version`, nothing changed; a
    refusal (UpdateError) when the check could not run, unless --skip-compat. `run` returns compat_check's triple."""
    if opts.get("skip-compat"):
        print("WARNING: --skip-compat: custom workflows were not checked against the new version")
        return None
    if not db.is_file():
        # S13's check exits 2 on a missing DB too (m-748157ec6e); a never-started install has nothing to check
        print("compat check skipped: no board DB yet")
        return None
    rc, rows, err = run()
    if rc == 1:
        print(f"update aborted: {sum(1 for r in rows if not r.get('ok'))} workflow(s) fail on {version}:")
        _print_rows(rows)
        print(f"nothing changed (DB, services and version as before); {DOCTOR_HINT}")
        return 1
    if rc != 0:
        raise UpdateError(f"the compatibility check could not run (exit {rc}: {err or 'no output'}); "
                          "nothing changed. `--skip-compat` updates without it")
    print(f"compat check passed ({len(rows)} workflow(s))")
    return None


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
            r = _get(releases_url(),
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


def _code_up() -> bool:
    """The optional code server of this home answers now: the helper must stop it before it installs (it holds the
    old extension, and on a uv tool install the tool environment) and start it again after (qa 0.10.7)."""
    from . import code_service
    try:
        return code_service.status().get("state") == "up"
    except Exception:  # noqa: BLE001 -- a status that cannot be read is "not running": the helper's process scan still looks
        return False


def _stop_all() -> None:
    from . import launcher
    launcher.stop_supervisor()
    for svc in reversed(launcher.ORDER):
        out = launcher.stop(svc)
        if out["survivors"]:
            raise UpdateError(f"{svc} did not stop ({out['survivors']}); the DB backup is kept, nothing was installed")


# ------------------------------------------------------------------------------------------ msi (bundle)
# S2 spike (s-725ef36c03, design-b6a55eed13 §4.G): the Windows desktop bundle updates in place through its MSI.
# The runner is update_helper.py on a COPY of the bundle's Python runtime under <home>\update\, so nothing the
# update runs holds a file in the install folder while msiexec replaces it.

def _msi_version(name: str) -> str | None:
    """'0.9.2.dev0' for 'Heronry Desktop-0.9.2.dev0.msi' (Briefcase names an MSI <formal name>-<version>.msi)."""
    if not name.lower().endswith(".msi") or "-" not in name:
        return None
    return name[:-4].rsplit("-", 1)[1] or None


def fetch_msi_release(url: str | None, tag: str | None = None) -> Release:
    """The release's .msi (and its SHA256SUMS line) from `url` (a local dir or http base), else GitHub's release."""
    if url:
        base = url.rstrip("/")
        sums = parse_sums(_read(f"{base}/SHA256SUMS").decode("utf-8"))
        files = {n: f"{base}/{n}" for n in sums}
    else:
        r = _get(releases_url(tag), headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        files = {a["name"]: a["browser_download_url"] for a in r.json().get("assets", [])}
        if "SHA256SUMS" not in files:
            raise UpdateError("the release has no SHA256SUMS; refusing an unverifiable update")
        sums = parse_sums(_read(files["SHA256SUMS"]).decode("utf-8"))
        # GitHub stores an uploaded "Heronry Desktop-1.msi" as "Heronry.Desktop-1.msi" while SHA256SUMS keeps the file
        # name it summed: match the asset to its line on the dotted name too, and key the sum by the asset's own name
        dotted = {k.replace(" ", "."): v for k, v in sums.items()}
        sums = {**sums, **{n: dotted[n.replace(" ", ".")] for n in files if n not in sums and n.replace(" ", ".") in dotted}}
    msis = sorted(n for n in files if _msi_version(n))
    if len(msis) != 1:
        raise UpdateError(f"the release has {len(msis)} .msi files; expected exactly one")
    return Release(version=_msi_version(msis[0]) or "", files={msis[0]: files[msis[0]]}, sums=sums)


def cached_msi(version: str) -> Path | None:
    d = settings.data_dir() / "updates" / version
    sums_f = d / "SHA256SUMS"
    if not sums_f.is_file():
        return None
    for name, want in parse_sums(sums_f.read_text(encoding="utf-8")).items():
        p = d / name
        if _msi_version(name) and p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == want:
            return p
    return None


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def secure_previous_msi(version: str, url: str | None = None) -> Path | None:
    """The installed version's MSI for a rollback (S10 #3), keyed on version AND SHA256 so a stale copy is never used.
    The release v<version> (`url`, else GitHub's tag) is asked for the sum it lists for that MSI: a cached copy is
    used only when its hash equals it, otherwise the release's MSI is downloaded and verified into the cache. Offline,
    a cached copy that still matches its own recorded sum is all there is. None when neither can be secured."""
    got = cached_msi(version)
    try:
        rel = fetch_msi_release(url, tag=None if url else f"v{version}")
    except Exception:  # noqa: BLE001 — offline, no such release: the verified cache is what there is
        return got
    if _v(rel.version) != _v(version):
        return got
    name = next(iter(rel.files))
    if got and got.name == name and _sha256(got) == rel.sums.get(name):
        return got
    try:
        download(rel)
    except Exception:  # noqa: BLE001 — a bad sum or a failed fetch: never fall back to a copy the release disowns
        return None
    return cached_msi(version)


def update_dir() -> Path:
    """<home>\\update: where the runner and its runtime copy live, outside the install folder."""
    home = settings.home()
    return (home if home is not None else settings.data_dir().parent) / "update"


def stage_runner(install_dir: Path) -> Path:
    """Copy the bundle's Python runtime (stub, DLLs, stdlib zip) and app entry plus update_helper.py to
    update_dir(); returns the runtime's console stub, which runs `<stub> update-helper.py <plan>`."""
    from . import launcher
    dest = update_dir()
    rt = dest / "runtime"
    if rt.exists():
        shutil.rmtree(rt)
    (rt / "app_packages").mkdir(parents=True)
    for f in install_dir.iterdir():
        if f.is_file() and (f.suffix.lower() in (".dll", ".pyd", ".zip", "._pth") or f.name == launcher.CONSOLE_EXE):
            shutil.copy2(f, rt / f.name)
    shutil.copytree(install_dir / "app" / "heronry", rt / "app" / "heronry")
    shutil.copyfile(Path(__file__).with_name("update_helper.py"), dest / "update-helper.py")
    shutil.copyfile(Path(__file__).with_name("update_lock.py"), dest / "update_lock.py")
    return rt / launcher.CONSOLE_EXE


def foreign_dirs() -> list[str]:
    return settings.foreign_dirs()  # the S2 guard (1), now in the settings registry: every CLI verb refuses on it


RESULT_NAME = "update-result.json"
STAGED_MAX_AGE_S = 3600.0


def last_result() -> dict[str, Any] | None:
    """The outcome of the latest update, from whichever runner wrote it (the MSI runner: <home>/update; the uv
    helper: the run dir): the newest file wins. Carries `_seen` (the tray already showed it)."""
    best: tuple[float, dict[str, Any]] | None = None
    for f in (update_dir() / RESULT_NAME, settings.run_dir() / RESULT_NAME):
        try:
            st, data = f.stat(), json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and (best is None or st.st_mtime > best[0]):
            best = (st.st_mtime, data)
    if best is None:
        return None
    data = dict(best[1])
    try:
        data["_seen"] = (update_dir() / "update-result.seen").read_text(encoding="utf-8").strip() == str(data.get("finished_at"))
    except OSError:
        data["_seen"] = False
    return data


def mark_result_seen(res: dict[str, Any]) -> None:
    try:
        update_dir().mkdir(parents=True, exist_ok=True)
        (update_dir() / "update-result.seen").write_text(str(res.get("finished_at") or ""), encoding="utf-8")
    except OSError:
        pass


#: RC2 item 6 (t-e338298d88), measured on Claude Code 2.1.283: an open session re-connects to edp8 by itself only
#: when the board is back within seconds; the minute-long stop/install/start of an update outlasts its retries and
#: drops the edp8 tools until /mcp Reconnect. Seats are parked and resumed, so they come back connected.
MCP_RECONNECT_HINT = ("In a Claude Code session that was open during the restart, run /mcp and pick Reconnect "
                      "for edp8 if its tools are missing; seats reconnect on their own")


def result_text(res: dict[str, Any]) -> str:
    """One plain line for the tray and the CLI: 'Updated to X', 'Rolled back: <reason>' or 'Failed: <reason> - <how
    to recover>'."""
    state, reason = res.get("state"), str(res.get("reason") or "").strip()
    if state == "ok":
        n = len(res.get("resumed") or [])
        return f"Updated to {res.get('to')}" + (f"; {n} seat(s) resumed" if n else "") + f". {MCP_RECONNECT_HINT}."
    hint = str(res.get("recover_hint") or "").strip()
    if state == "rolled_back":
        db = f" ({res['db_restore_reason']})" if res.get("db_restore_reason") else ""
        return f"Rolled back to {res.get('from')}: {reason}{db}"
    if state == "incomplete":  # S18-2: installed, but some parked seats did not come back
        return f"Updated, recovery incomplete: {reason}. {MCP_RECONNECT_HINT}."
    return f"Failed: {reason}" + (f" - {hint}" if hint and hint not in reason else "")


def update_staged() -> bool:
    """A runner was started and has not written its outcome yet (a plan newer than any result, recent)."""
    plan = update_dir() / "update-plan.json"
    try:
        age = time.time() - plan.stat().st_mtime
    except OSError:
        return False
    if age > STAGED_MAX_AGE_S:
        return False
    res = update_dir() / RESULT_NAME
    try:
        return res.stat().st_mtime < plan.stat().st_mtime
    except OSError:
        return True


def install_scope_busy() -> bool:
    """Windows Installer is mid-transaction (its Global MSIExecute mutex exists): no second update may start."""
    from .update_helper import _msi_busy
    return _msi_busy()


def gui_exe_name(install_dir: Path, product: str | None = None) -> str:
    """The desktop app's exe in an install folder: Briefcase names it after the product (<ProductName>.exe), which is
    the brand's app name in a release and another name in a side-by-side drill build."""
    from .brand import DESKTOP_APP_NAME
    for name in (product, DESKTOP_APP_NAME):
        if name and (install_dir / f"{name}.exe").is_file():
            return f"{name}.exe"
    return f"{product or DESKTOP_APP_NAME}.exe"


def desktop_pids(install_dir: Path, gui_name: str | None = None) -> list[int]:
    """Desktop app windows open now: processes whose image is this install's GUI exe (not this process)."""
    import psutil

    gui = os.path.normcase(str(install_dir / (gui_name or gui_exe_name(install_dir))))
    out = []
    for p in psutil.process_iter(["pid", "exe"]):
        try:
            if p.info["pid"] != os.getpid() and p.info.get("exe") and os.path.normcase(p.info["exe"]) == gui:
                out.append(int(p.info["pid"]))
        except (psutil.Error, OSError, TypeError):
            continue
    return out


def app_identities(pids: list[int]) -> dict[str, dict[str, Any]]:
    """{pid: {exe, created}} for the app windows found, so the runner closes a pid only while it is still the same
    process (it may kill up to 120 s later; a pid can be reused by then)."""
    import psutil

    out: dict[str, dict[str, Any]] = {}
    for pid in pids:
        try:
            p = psutil.Process(pid)
            out[str(pid)] = {"exe": p.exe(), "created": p.create_time()}
        except (psutil.Error, OSError):
            continue
    return out


def _opt_str(opts: dict[str, Any], name: str) -> str | None:
    v = opts.get(name)
    return v if isinstance(v, str) else None


def _owned_endpoints(launcher: Any) -> dict[str, Any]:
    """The plan keys that act on a service port: the pool (park/resume) and the board (outcome event, which carries
    this home's admin token). A key is present only when THIS home owns that port now; a port another home holds
    (a private install whose own service is down next to a running fleet) is never parked, resumed or sent a token
    (architect review of S10, HIGH/MEDIUM)."""
    out: dict[str, Any] = {"pool_ours": False, "board_ours": False}
    if launcher.owner("pool")[0] == "ours":
        out.update(pool_ours=True, pool_url=f"http://127.0.0.1:{launcher.port('pool')}")
    if launcher.owner("board")[0] == "ours":
        out.update(board_ours=True, board_url=str(launcher.url("board")),
                   admin_token_file=str(settings.admin_token_file()))
    return out


def tracked_shells(pool_url: str | None) -> set[int]:
    """The shell pids of the pool's active rows: the seats the update parks, ends and resumes."""
    from .update_helper import _http
    if not pool_url:
        return set()
    try:
        rows = _http(f"{pool_url}/v1/sessions") or []
    except (OSError, ValueError):
        return set()
    rows = rows.get("sessions", rows) if isinstance(rows, dict) else rows
    rows = rows.values() if isinstance(rows, dict) else rows
    return {int((r.get("proc") or {}).get("pid") or 0) for r in rows
            if r.get("state") in ("active", "starting") and (r.get("proc") or {}).get("pid")}


def refuse_untracked_seats(install_dir: Path, pool_url: str | None) -> None:
    """t-fb8b63874e (architect m-95b5fe285e): the update ends each seat it parks, monitor and all, and the pool
    resumes it once. A live seat the pool does not track as active (a window resumed by hand, an interactive
    session, a seat parked earlier) is never parked or resumed, and stopping its feed monitor, which runs from the
    install folder, would leave it unable to wake. So the update refuses before it parks or stops anything, naming
    each such seat. A refusal costs nothing; a stop and a rollback do."""
    from .update_helper import untracked_reason, untracked_seats
    seats = untracked_seats(str(install_dir), tracked_shells(pool_url))
    if seats:
        raise UpdateError(f"{untracked_reason(seats)}. Nothing changed")


def apply_msi(opts: dict[str, Any]) -> int:
    from . import launcher
    from .update_helper import msi_property, related_products

    if sys.platform != "win32":
        raise UpdateError("the desktop bundle updates in place only on Windows (MSI); download the new release")
    bad = foreign_dirs()
    if bad:
        raise UpdateError(f"EDP_HOME is {settings.home() or 'unset (the default per-user home)'} but "
                          f"{', '.join(bad)} points outside it; an update would stop "
                          "another home's services. Unset those variables; nothing changed")
    if install_scope_busy():
        raise UpdateError("Windows Installer is busy (another installation or a rollback is running); try again in a "
                          "minute. Nothing changed")
    if update_staged() and not opts.get("force"):
        raise UpdateError("an update is already staged (see <home>\\update\\update-result.json); wait for it, or --force")
    install_dir = Path(sys.executable).resolve().parent
    cur = current_version()
    rel = fetch_msi_release(_opt_str(opts, "release-url"))
    print(f"current {cur}, release {rel.version}")
    if _v(rel.version) < _v(cur):
        raise UpdateError(f"{rel.version} is older than {cur}; an MSI cannot downgrade in place")
    if _v(rel.version) == _v(cur) and not opts.get("force"):
        print("already up to date")
        return 0
    refuse_untracked_seats(install_dir, _owned_endpoints(launcher).get("pool_url"))
    t0 = time.monotonic()
    msi = download(rel)["msi"]
    print(f"verified {msi.name} against SHA256SUMS ({time.monotonic() - t0:.1f}s)")
    upgrade_code = msi_property(str(msi), "UpgradeCode")
    if not upgrade_code:
        raise UpdateError(f"{msi.name} is not a readable Windows Installer package; nothing changed")
    mine = [r for r in related_products(upgrade_code) if _v(r["version"]) == _v(cur)]
    if not mine:
        raise UpdateError(f"{msi.name} does not upgrade this install (no installed {cur} shares its UpgradeCode "
                          f"{upgrade_code}); nothing changed")
    prev = secure_previous_msi(cur, _opt_str(opts, "previous-url"))
    if prev:
        print(f"the installed {cur}'s MSI is cached for a rollback ({prev})")
    elif not opts.get("force"):
        raise UpdateError(f"couldn't secure the installed {cur}'s MSI for a rollback; nothing changed. Give "
                          f"`--previous-url <dir|http base>` of the {cur} release, or --force to update without a way back")
    else:
        print(f"WARNING: --force: no rollback to {cur} is possible if the update fails; {recover_hint(cur)}")
    db = Path(settings.get("EDP8_DB"))
    dest = update_dir()
    dest.mkdir(parents=True, exist_ok=True)
    stub = stage_runner(install_dir)  # one copy of the runtime serves the compat check and the update
    gate = _compat_gate(opts, db, lambda: msi_compat_check(msi, db, stub), rel.version)
    if gate is not None:
        return gate
    if opts.get("dry-run"):
        print("dry run: would park seats, stop, install and start; nothing changed")
        return 0
    lock = _take_lock(cur, rel.version)
    backup = backup_db(db, cur) if db.is_file() else None
    if backup:
        _say("backup", f"the DB to {backup}")
    log = settings.logs_dir() / "update.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    result = dest / RESULT_NAME
    result.unlink(missing_ok=True)
    exe = str(install_dir / launcher.CONSOLE_EXE)
    # typed in cmd (PowerShell 5.1 re-quotes INSTALLFOLDER="…" whole, which msiexec refuses with 1639)
    hint = (f'reinstall {cur} from its cached installer, in a Command Prompt (cmd): msiexec /i "{prev}" '
            f'MSIINSTALLPERUSER=1 ALLUSERS=2 INSTALLFOLDER="{install_dir}", then `heronry start`'
            if prev else recover_hint(cur))
    follow = _follow_path()
    gui = gui_exe_name(install_dir, msi_property(str(msi), "ProductName"))
    app_pids = desktop_pids(install_dir, gui)
    relaunch = bool(opts.get("relaunch-app")) or bool(app_pids)
    plan = {"kind": "msi", "caller_pid": os.getpid(), "from_version": cur, "to_version": rel.version,
            "msi": str(msi), "previous_msi": str(prev) if prev else None, "upgrade_code": upgrade_code,
            # S13 F6: the digests verified above; the helper re-checks each file right before msiexec
            "msi_sha256": rel.sums[msi.name], "previous_msi_sha256": _sha256(prev) if prev else None,
            "install_dir": str(install_dir),
            "stop_argv": [exe, "stop", "--force"], "start_argv": [exe, "start", "--no-browser"],
            "app_pids": app_pids, "app_procs": app_identities(app_pids),
            "app_argv": [str(install_dir / gui)] if relaunch else None,
            "health_url": f"{launcher.url('board')}/v1/health", "code_running": _code_up(),
            "db": str(db), "backup": str(backup or ""),
            "log": str(log), "result": str(result), "recover_hint": hint,
            "fault": settings.env_raw("HERONRY_UPDATE_FAULT") or "",
            "update_dir": str(dest), "lock_token": lock["token"],
            # the shell that typed the command follows the update itself (bin/heronry.cmd): no second window
            "no_window": follow is not None,
            **_owned_endpoints(launcher)}
    plan_f = dest / "update-plan.json"
    plan_f.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    from edp_contracts.proc import detach
    ident, _ = detach([str(stub), str(dest / "update-helper.py"), str(plan_f)], cwd=str(dest),
                      env=settings.environ_copy(),
                      log=str(dest / "update-helper.out"), via=str(stub))
    update_lock.add_pid(update_dir(), ident.pid)
    _LOCK["handed_off"] = True
    confirm_started(ident, dest / "update-helper.out", result)
    if follow is not None:
        write_follow(follow, stub, dest / "update-helper.py", dest / update_lock.PROGRESS_NAME, ident, result)
        _say("handed over", f"installing {rel.version} from {dest} (outside the install folder); this shell follows each step to the result; log {log}")
    else:
        _say("handed over", f"installing {rel.version} from {dest} (outside the install folder); the window shows each step; log {log}, outcome {result}")
    print(f"{MCP_RECONNECT_HINT}.")
    return 0


#: set by bin/heronry.cmd: where the CLI writes the script that makes the typing shell follow an update
FOLLOW_ENV = "HERONRY_FOLLOW"


def _follow_path() -> Path | None:
    """The follow script's path when the command came through bin/heronry.cmd on Windows, else None (the tray, a
    direct heronry.exe, another OS): those get the progress window."""
    raw = (settings.env_raw(FOLLOW_ENV) or "").strip()
    return Path(raw) if raw and sys.platform == "win32" else None


def write_follow(path: Path, stub: Path, helper: Path, progress: Path, ident: Any, result: Path) -> None:
    """The script bin/heronry.cmd calls once heronry.exe has exited (owner m-584d63e760): it runs the progress viewer
    from the runtime copy outside the install folder, so the shell that typed `heronry update` blocks through the
    install or the rollback and gets the result's exit code. cmd reads it from %TEMP%, never from the folder the
    installer replaces; the shim deletes it after it ran."""
    created = getattr(ident, "create_time", 0.0) or 0.0
    lines = ["@echo off",
             f'"{stub}" "{helper}" --view "{progress}" --pid {ident.pid} --created {created:.3f} '
             f'--result "{result}" --inline',
             'exit /b %ERRORLEVEL%']
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("mbcs" if sys.platform == "win32" else "utf-8"))


#: how long the CLI watches the detached helper start before it hands over (owner m-8b37e6b58e)
HELPER_START_S = 6.0


def confirm_started(ident: Any, out_log: Path, result: Path, seconds: float | None = None) -> None:
    """The CLI's last look before it hands over: the helper must still be running a few seconds in. 0.10.2's helper
    died at its first import in the bundle (owner m-8b37e6b58e) and the CLI still said "handed over", so the update
    failed with nothing on the screen. A helper that already ended with a result is fine (its result is printed);
    one that ended without a result raises with the tail of its own output."""
    deadline = time.monotonic() + (HELPER_START_S if seconds is None else seconds)
    while time.monotonic() < deadline:
        if ident.live() is None:
            break
        time.sleep(0.25)
    else:
        return
    try:
        res = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        res = None
    if isinstance(res, dict) and res.get("state"):
        print(result_text(res))
        return
    try:
        tail = [ln for ln in out_log.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()][-6:]
    except OSError:
        tail = []
    raise UpdateError("the update helper stopped before it reported anything"
                      + (": " + " | ".join(tail) if tail else f" (no output in {out_log})")
                      + "; the update did not run, and Heronry is as it was")


_LOCK: dict[str, Any] = {"data": None, "handed_off": False}


def _take_lock(from_version: str, to_version: str) -> dict[str, Any]:
    """The update lock (s-4d93970c9f item 2), taken before the seats park. It stays held when the helper has been
    started (it joins and releases it at the result); any earlier exit releases it in `apply`."""
    try:
        data = update_lock.acquire(update_dir(), from_version=from_version, to_version=to_version, step="preparing")
    except RuntimeError as e:
        raise UpdateError(f"{e}; nothing changed") from e
    _LOCK.update(data=data, handed_off=False)
    update_lock.reset_progress(update_dir())
    _say("verified", f"{from_version} -> {to_version}; update lock taken, services will not start until the result")
    return data


def _say(step: str, detail: str = "") -> None:
    """One step of the update on stdout, the lock and the progress file: the same lines the window shows."""
    update_lock.progress(update_dir(), step, detail, echo=True)


def apply(opts: dict[str, Any]) -> int:
    """The update entry; releases the update lock on every exit that did not hand it to the detached helper."""
    _LOCK.update(data=None, handed_off=False)
    try:
        return _apply(opts)
    finally:
        if _LOCK["data"] is not None and not _LOCK["handed_off"]:
            update_lock.release(update_dir())
        _LOCK.update(data=None, handed_off=False)


def _apply(opts: dict[str, Any]) -> int:
    """THE update entry (S10): `heronry update` (main) and the tray's Install update both call this. A bundle goes
    through its MSI (apply_msi); a `uv tool` install through `uv tool install --force`. Both park the live seats
    (the pool resumes them), stop through the launcher, run from a copy outside the install, health-check, and
    roll back with a plain reason; the outcome is update-result.json plus a board event."""
    from . import launcher

    busy = update_lock.held(update_dir())
    if busy is not None:
        raise UpdateError(f"{update_lock.describe(busy)}; nothing changed")
    if launcher.bundled():
        return apply_msi(opts)
    if settings.dev_mode():
        raise UpdateError("this is a source checkout (dev mode): update it with git, not `heronry update`")
    if not _uv_tool_env() and not settings.env_raw("EDP_UPDATE_INSTALL_CMD"):
        raise UpdateError("this install was not made by `uv tool install`; re-run the install script instead")
    bad = foreign_dirs()
    if bad:
        raise UpdateError(f"EDP_HOME is {settings.home() or 'unset (the default per-user home)'} but "
                          f"{', '.join(bad)} points outside it; an update would stop "
                          "another home's services. Unset those variables; nothing changed")

    cur = current_version()
    rel = fetch_release(_opt_str(opts, "release-url"))
    print(f"current {cur}, release {rel.version}")
    if _v(rel.version) < _v(cur) and not opts.get("allow-downgrade"):
        raise UpdateError(f"{rel.version} is older than {cur}; refusing a downgrade (--allow-downgrade)")
    if _v(rel.version) == _v(cur) and not opts.get("force"):
        print("already up to date")
        return 0
    wheels = download(rel)
    print(f"verified {len(wheels)} wheels against SHA256SUMS")

    db = Path(settings.get("EDP8_DB"))
    gate = _compat_gate(opts, db, lambda: compat_check(wheels, db), rel.version)
    if gate is not None:
        return gate

    if not opts.get("force") and launcher.live_seats() is None:
        # live seats are parked and resumed (S10 #7); only an unanswering pool is a stop: it cannot be asked to park
        raise UpdateError(f"{launcher.seat_block(None)}; nothing changed")
    prev = secure_previous(cur, _opt_str(opts, "previous-url"))
    if prev:
        print(f"the installed {cur}'s wheels are cached for a rollback")
    elif not opts.get("force"):
        raise UpdateError(f"couldn't secure the installed {cur}'s wheels for a rollback (not cached, and its release "
                          f"could not be fetched); nothing changed. Retry online, give `--previous-url <dir|http base>` "
                          f"of the {cur} release, or use --force to update without a way back")
    else:
        print(f"WARNING: --force: no rollback to {cur} is possible if the update fails; {recover_hint(cur)}")
    if opts.get("dry-run"):
        print("dry run: would park seats, back up the DB, stop, install and start; nothing changed")
        return 0

    lock = _take_lock(cur, rel.version)
    backup = backup_db(db, cur) if db.is_file() else None
    if backup:
        _say("backup", f"the DB to {backup}")
    run = settings.run_dir()
    run.mkdir(parents=True, exist_ok=True)
    result = run / RESULT_NAME
    result.unlink(missing_ok=True)
    log = settings.logs_dir() / "update.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    from .update_helper import _park, _resume_now, _services_down
    owned = _owned_endpoints(launcher)
    parked = _park({"pool_url": owned["pool_url"], "log": str(log)}) if owned["pool_ours"] else []
    failed = list(getattr(parked, "failed", []))
    if failed:  # S18-2 (CLI as MSI): a live seat that did not park would be killed mid-turn: install nothing
        back = _resume_now({"pool_url": owned["pool_url"], "log": str(log)}, list(parked)) if parked else []
        raise UpdateError(f"seat(s) {', '.join(failed)} could not be parked; nothing was stopped or installed"
                          + (f"; resumed {len(back)} of {len(parked)} parked seat(s)" if parked else ""))
    if parked:
        _say("park", f"{len(parked)} seat(s); they resume after the update")
    try:
        _stop_all()
        if owned["board_ours"] and not _services_down({"health_url": f"{launcher.url('board')}/v1/health"}):
            # S18-2: installing over a board that still answers is refused; start brings the stopped rest back
            raise UpdateError("the services did not stop (the board still answers its health check); nothing was "
                              "installed. `heronry start` restarts anything that did stop")
        _say("stop", "the supervisor and services")

        helper = _stage_helper(run)
        me = [sys.executable, "-m", "edp8.cli"]
        plan = {"caller_pid": os.getpid(), "from_version": cur, "to_version": rel.version,
                "install_argv": install_argv(wheels), "rollback_install_argv": install_argv(prev) if prev else None,
                "start_argv": [*me, "start"], "stop_argv": [*me, "stop", "--force"], "parked": parked,
                "health_url": f"{launcher.url('board')}/v1/health", "code_running": _code_up(),
                "db": str(db), "backup": str(backup or ""),
                "log": str(log), "result": str(result), "recover_hint": recover_hint(cur),
                "update_dir": str(update_dir()), "lock_token": lock["token"], **owned}
        plan_f = run / "update-plan.json"
        plan_f.write_text(json.dumps(plan, indent=1), encoding="utf-8")
        from edp_contracts.proc import detach
        py = getattr(sys, "_base_executable", None) or sys.executable
        ident, _ = detach([py, str(helper), str(plan_f)], cwd=str(run), env=settings.environ_copy(),
                          log=str(run / "update-helper.out"))
        update_lock.add_pid(update_dir(), ident.pid)
        _LOCK["handed_off"] = True
        confirm_started(ident, run / "update-helper.out", result)
    except BaseException:
        # nothing is installing: seats parked above must not stay parked (a pool already stopped resumes them
        # itself at its next start, they carry park_for_update)
        if parked:
            back = _resume_now({"pool_url": owned["pool_url"], "log": str(log)}, parked)
            print(f"the update did not start; resumed {len(back)} of {len(parked)} parked seat(s)", file=sys.stderr)
        raise
    _say("handed over", f"installing {rel.version} in the background; the window shows each step; log {log}, outcome {result}. "
          "`heronry status` shows the services when it is done.")
    print(f"{MCP_RECONNECT_HINT}.")
    return 0


def main(argv: list[str]) -> int:
    from .cli import _split

    _, opts = _split(argv)
    if opts.get("lock-status"):  # the installers ask this before replacing an install: rc 3 = an update is running
        busy = update_lock.held(update_dir())
        print(update_lock.describe(busy) if busy else "no update in progress")
        return 3 if busy else 0
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
