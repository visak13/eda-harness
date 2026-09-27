"""The `code` service: code-server behind the loopback host guard, on every OS (S21 s-0cfebd3862, design R21).

A port of ``scripts/start-code.ps1`` / ``stop-code.ps1`` (s-3c8c2512d6, s-03c7e9168b, s-17c13096e5) to the one
launcher's process control (``edp_contracts.proc``: detach, ProcId, kill_tree, named jobs). Every channel runs
this module: ``heronry start|stop|restart code``, the supervisor's control port (Admin → Services, the Code
tab's Start), the desktop tray, and the legacy scripts, which are thin wrappers over the CLI.

The guarantees the scripts gave are kept:

* ``edp8.code_guard`` holds ``127.0.0.1:<code_server.port>``; code-server runs on a random inner loopback port
  with ``--auth password`` and a per-start secret (``$HASHED_PASSWORD``, by environment only), so a
  DNS-rebinding page that finds the inner port meets the login wall.
* A per-start mint key reaches the guard by environment and the board through ``<run>/code.json``
  (``mint_key``), the record ``api_code`` reads (port, guard_pid, version, user_dir).
* code-server's environment has every ``EDP_*``/``EDP8_*`` variable removed (dec-ea925a2d30: terminals and
  extensions never inherit seat or board secrets), plus the variables that would change how it reads or logs
  the password. The guard keeps only the home variables, so it reports this home's id.
* Loopback only: any other ``EDP_CODE_HOST`` is refused. A listener on the port that is not this home's guard
  fails the start loudly and is never killed.
* Start is idempotent: this home's guard with its recorded code-server alive is ``already_running``.
* Stop acts only on the recorded (pid, create_time) of the server and the guard (ll-craft 2/2), plus their
  named jobs; never by image name. A record written by the old script (pid + creation_date) is matched the
  same way, to the second.

code-server itself is found by the ``code_server.path`` setting, else (a source checkout) the pinned install
``scripts/install-code-server.ps1`` leaves under ``.tools/code-server``, else ``code-server`` on PATH. Not
found: the state is ``not_installed`` with the official per-OS install command.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from edp_contracts.identity import home_id_of
from edp_contracts.proc import ProcId, assign_job, detach, job_name, kill_tree, terminate_job
from edp_contracts.toolpath import find_tool, tool_argv

from . import run_state, settings

SERVICE = "code"
GUARD_MODULE = "edp8.code_guard"
#: the name the bundle's `--heronry-service` re-entry runs the guard under (cli._SERVICE_MODULES)
GUARD_SERVICE = "code-guard"
LOOPBACK = "127.0.0.1"
#: variables that would change how code-server reads or logs the password (a cookie suffix renames the
#: cookie the guard injects; trace logging writes the password out), and the one-shot handoffs
_SCRUB = ("LOG_LEVEL", "PASSWORD", "HASHED_PASSWORD", "CODE_SERVER_COOKIE_SUFFIX", "VSCODE_OPTIONS",
          "CODE_SERVER_CONFIG", "CODE_GUARD_SESSION", "CODE_GUARD_MINT_KEY")
#: the only EDP variables the guard keeps: the ones that name this home (its /__edp/home answer)
_HOME_KEYS = ("EDP_HOME", "EDP8_HOME", "EDP8_DATA", "EDP8_RUN_DIR", "EDP_CONFIG_DIR")
_PROBE_TIMEOUT_S = 3.0

INSTALL_HINTS = {
    "win32": "npm install -g code-server  (Node.js 22; see https://coder.com/docs/code-server/install#windows), "
             "or set code_server.path",
    "darwin": "brew install code-server  (see https://coder.com/docs/code-server/install#macos), or set "
              "code_server.path",
    "linux": "curl -fsSL https://code-server.dev/install.sh | sh  (see https://coder.com/docs/code-server/install), "
             "or set code_server.path",
}


class CodeError(RuntimeError):
    """The code service could not be started or stopped; the message is one plain line for the user."""


def install_hint(platform: str | None = None) -> str:
    return INSTALL_HINTS.get(platform or sys.platform, INSTALL_HINTS["linux"])


# ------------------------------------------------------------------------------------------ settings

def port() -> int:
    return int(settings.get("EDP_CODE_PORT"))


def bind_host() -> str:
    """Loopback only: anyone who reaches code-server owns the host through its terminal."""
    raw = str(settings.get("EDP_CODE_HOST") or LOOPBACK).strip()
    if raw.lower() not in (LOOPBACK, "localhost"):
        raise CodeError(f"refusing EDP_CODE_HOST={raw}: code-server (behind its guard) binds {LOOPBACK} only")
    return LOOPBACK


def autostart() -> bool:
    return bool(settings.get("EDP_CODE_AUTOSTART"))


def data_root() -> Path:
    return Path(settings.get("EDP_CODE_DATA"))


def user_dir() -> Path:
    return data_root() / "user"


def ext_dir() -> Path:
    return data_root() / "extensions"


def record_path() -> Path:
    return settings.run_dir() / "code.json"


def url() -> str:
    return f"http://{LOOPBACK}:{port()}/"


def _board_url() -> str:
    from . import launcher
    return str(launcher.url("board") or f"http://{LOOPBACK}:9400").rstrip("/")


def _origins() -> list[str]:
    """The guard's WebSocket Origin allowlist beyond its own two: the board, and its public origin."""
    from . import launcher
    bp = launcher.port("board")
    out = [f"http://{LOOPBACK}:{bp}", f"http://localhost:{bp}"]
    public = str(settings.get("EDP8_PUBLIC_URL") or "").strip()
    m = re.match(r"^(https?://[^/]+)", public)
    if m:
        out.append(m.group(1))
    return out


# ------------------------------------------------------------------------------------------ locate

@dataclass(frozen=True)
class Install:
    argv: list[str]        # the prefix that runs code-server
    tag: str               # the install path: the record's install_dir, the guard's --tag
    version: str | None
    source: str            # setting | pinned | path


def _pinned() -> Install | None:
    """A source checkout's pinned build (vscode-ext/code-server.lock.json, installed and verified under
    .tools/code-server by scripts/install-code-server.ps1)."""
    home = settings.home()
    if home is None or not settings.dev_mode():
        return None
    try:
        lock = json.loads((home / "vscode-ext" / "code-server.lock.json").read_text(encoding="utf-8"))
        install = home / ".tools" / "code-server" / lock["version"]
        server = install / lock["server_dir"]
        node = server / lock["node"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not ((install / ".verified").is_file() and node.is_file()):
        return None
    return Install([str(node), str(server)], str(install), str(lock["version"]), "pinned")


def _from_path(path: str, source: str) -> Install | None:
    """An argv prefix for a configured or PATH code-server: a release dir (lib/node + the dir), a ``.js`` entry
    (node), a ``.py`` entry (this interpreter: the test stub), a Windows npm shim (node + its entry.js, so no
    cmd.exe sits between us and the server), else the executable itself."""
    p = Path(path).expanduser()
    if p.is_dir():
        node = next((n for n in (p / "lib" / "node.exe", p / "lib" / "node") if n.is_file()), None)
        if node is None:
            return None
        return Install([str(node), str(p)], str(p), None, source)
    if not p.is_file():
        return None
    low = p.name.lower()
    if low.endswith(".py"):
        return Install([sys.executable, str(p)], str(p.parent), None, source)
    if sys.platform == "win32" and low.endswith((".cmd", ".bat", ".ps1")):
        entry = p.parent / "node_modules" / "code-server" / "out" / "node" / "entry.js"
        node = p.parent / "node.exe"
        if entry.is_file():
            nodes = [str(node)] if node.is_file() else [find_tool("node") or ""]
            if nodes[0]:
                return Install([nodes[0], str(entry)], str(entry.parents[2]), None, source)
    try:
        return Install(tool_argv(str(p)), str(p.parent), None, source)
    except FileNotFoundError:
        return None


def locate() -> Install | None:
    """The code-server to run: the ``code_server.path`` setting, else a checkout's pinned build, else PATH."""
    configured = settings.get("EDP_CODE_SERVER_PATH")
    if configured:
        return _from_path(str(configured), "setting")
    pinned = _pinned()
    if pinned is not None:
        return pinned
    found = find_tool("code-server", key="EDP_CODE_SERVER_PATH")
    return _from_path(found, "path") if found else None


# ------------------------------------------------------------------------------------------ environment

def _fleet_key(k: str) -> bool:
    u = k.upper()
    return u.startswith("EDP_") or u.startswith("EDP8_")


def server_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """code-server's environment: every EDP_*/EDP8_* variable and the password-bearing ones removed."""
    env = dict(settings.environ_copy() if base is None else base)
    scrub = {s.upper() for s in _SCRUB}
    return {k: v for k, v in env.items() if not _fleet_key(k) and k.upper() not in scrub}


def guard_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """The guard's environment: code-server's, plus only the variables that name this home."""
    env = dict(settings.environ_copy() if base is None else base)
    out = server_env(env)
    for k, v in env.items():
        if k.upper() in _HOME_KEYS:
            out[k] = v
    # a home that came from config/defaults still has to reach the guard as the same home
    home = settings.home()
    if home is not None:
        out["EDP_HOME"] = str(home)
    out["EDP8_DATA"] = str(settings.data_dir().resolve())
    out["EDP8_RUN_DIR"] = str(settings.run_dir())
    return out


# ------------------------------------------------------------------------------------------ record

def record() -> dict[str, Any]:
    try:
        data = json.loads(record_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_record(rec: dict[str, Any]) -> None:
    path = record_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    # the mint key is in it: the owner's account only (POSIX 0600; Windows keeps the profile's ACL)
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2)
    os.replace(tmp, path)


def _clear_record() -> None:
    with contextlib.suppress(OSError):
        record_path().unlink()


_ISO_FRACTION = re.compile(r"(\.\d{6})\d+")


def _legacy_ident(pid: Any, creation: Any) -> ProcId | None:
    """A process the old start-code.ps1 recorded (pid + a .NET "o" creation date), fingerprinted now when the
    live process started within a second of it; None otherwise (a reused pid is never taken for ours)."""
    try:
        when = datetime.fromisoformat(_ISO_FRACTION.sub(r"\1", str(creation)).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.astimezone()
        ident = ProcId.try_of(int(pid))
    except (TypeError, ValueError):
        return None
    if ident is None or abs(ident.create_time - when.timestamp()) > 1.0:
        return None
    return ident


def _idents(rec: dict[str, Any]) -> tuple[ProcId | None, ProcId | None]:
    """(server, guard) identities from the record: the ProcId fields, else the old script's pid + date."""
    server = ProcId.from_json(rec.get("server")) or _legacy_ident(rec.get("pid"), rec.get("creation_date"))
    guard = ProcId.from_json(rec.get("guard")) or _legacy_ident(rec.get("guard_pid"), rec.get("guard_creation_date"))
    return server, guard


def _in_tree(ident: ProcId | None, pid: int | None) -> bool:
    root = ident.live() if ident is not None else None
    if root is None or not pid:
        return False
    if root.pid == pid:
        return True
    try:
        return any(c.pid == pid for c in root.children(recursive=True))
    except Exception:  # noqa: BLE001 — a vanished child: not provably ours
        return False


# ------------------------------------------------------------------------------------------ probes

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_a, **_k):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get(url_: str, cookie: str | None = None, timeout: float = _PROBE_TIMEOUT_S) -> tuple[int, dict[str, str], bytes]:
    """(status, headers, body) with no redirect followed; (0, {}, b"") when nothing answers."""
    req = urllib.request.Request(url_, headers={"Cookie": cookie} if cookie else {})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(65536)
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, b""
    except (urllib.error.URLError, OSError, ValueError):
        return 0, {}, b""


def healthy(p: int | None = None) -> bool:
    return _get(f"http://{LOOPBACK}:{p or port()}/healthz")[0] == 200


def guard_home_id(p: int | None = None) -> str | None:
    """The home id this port's guard reports (``GET /__edp/home``); None when it reports none."""
    from .code_guard import HOME_PATH
    code, _, body = _get(f"http://{LOOPBACK}:{p or port()}{HOME_PATH}")
    if code != 200:
        return None
    try:
        hid = json.loads(body.decode("utf-8")).get("home_id")
    except (ValueError, AttributeError):
        return None
    return hid if isinstance(hid, str) and hid else None


def my_home_id() -> str:
    return home_id_of(settings.data_dir())


def workbench(mint_key: str | None, p: int | None = None) -> bool:
    """The guard is gated and the workbench answers through it once signed in: without the guard cookie / is
    401; a login with a fresh token sets the cookie; with it, / is the workbench and no code-server login
    (the guard's session cookie is the one code-server expects)."""
    from .code_guard import GUARD_COOKIE, LOGIN_PATH, mint_token
    if not mint_key:
        return False
    base = f"http://{LOOPBACK}:{p or port()}"
    if _get(base + "/")[0] != 401:
        return False
    token, _ = mint_token(mint_key)
    code, headers, _ = _get(f"{base}{LOGIN_PATH}?t={token}&next=%2F")
    m = re.match(rf"^({GUARD_COOKIE}=[^;]+)", headers.get("set-cookie", ""))
    if code != 302 or headers.get("location") != "/" or not m:
        return False
    code, headers, _ = _get(base + "/", cookie=m.group(1))
    return code == 200 or (code == 302 and "login" not in headers.get("location", ""))


def _listening(p: int) -> bool:
    return run_state._port_listening(p)


def _free_port(avoid: int) -> int:
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((LOOPBACK, 0))
            got = s.getsockname()[1]
        if got != avoid:
            return got


# ------------------------------------------------------------------------------------------ status

def status() -> dict[str, Any]:
    """{service, state, port, url, pid, guard_pid, version, installed, install_hint, reason}. state is up (this
    home's guard answers with its recorded code-server alive), down, foreign (another program or home holds
    the port), or not_installed (down, and no code-server to start)."""
    p = port()
    rec = record()
    server, guard = _idents(rec)
    inst = locate()
    row: dict[str, Any] = {"service": SERVICE, "port": p, "url": url(), "pid": None, "guard_pid": None,
                           "version": rec.get("version") or (inst.version if inst else None),
                           "installed": inst is not None, "install_hint": None if inst else install_hint(),
                           "autostart": autostart(), "state": "down", "reason": None}
    if _listening(p):
        hid = guard_home_id(p)
        mine = hid == my_home_id() if hid else (guard is not None and _in_tree(guard, run_state.listener_pid(p)))
        if not mine:
            row.update(state="foreign", pid=run_state.listener_pid(p),
                       reason=f"port {p} is held by another Heronry's code-server or another program")
            return row
        if server is not None and server.live() is not None and healthy(p):
            row.update(state="up", pid=server.pid, guard_pid=guard.pid if guard else rec.get("guard_pid"))
            return row
        row.update(reason="this home's guard answers, but its recorded code-server is gone: heronry restart code")
        return row
    if inst is None:
        row.update(state="not_installed", reason=f"code-server is not installed: {install_hint()}")
    else:
        row.update(reason="not running: `heronry start code` starts it")
    return row


# ------------------------------------------------------------------------------------------ seeding

def _default_folder() -> str:
    """The folder a plain /ui/code opens: the board's own tree (the agent home), in code-server's URL form."""
    d = str(settings.agent_home().resolve()).replace("\\", "/").rstrip("/")
    m = re.match(r"^([A-Za-z]):(.*)$", d)
    return f"/{m.group(1).lower()}:{m.group(2)}" if m else d


def _seed_coder_json() -> str:
    """t-6356c06c40: with no last folder/workspace, seed the default folder (not a CLI positional)."""
    path = user_dir() / "coder.json"
    raw = ""
    with contextlib.suppress(OSError):
        raw = path.read_text(encoding="utf-8-sig")
    coder: Any = None
    if raw.strip():
        try:
            coder = json.loads(raw)
        except ValueError:
            return "default folder: coder.json unreadable; left as is"
        if not isinstance(coder, dict):
            return "default folder: coder.json unreadable; left as is"
    q = (coder or {}).get("query") if isinstance(coder, dict) else None
    if isinstance(q, dict) and (q.get("folder") or q.get("workspace")):
        return "default folder: code-server reopens its last folder/workspace"
    coder = coder or {}
    coder["query"] = {"folder": _default_folder()}
    path.write_text(json.dumps(coder, indent=2), encoding="utf-8")
    return f"default folder: seeded {coder['query']['folder']}"


def _vendor_dir() -> Path | None:
    """The vendored extension list (a source checkout's vscode-ext); None when absent (an installed wheel)."""
    home = settings.home()
    d = home / "vscode-ext" if home is not None else None
    return d if d is not None and (d / "extensions.txt").is_file() and (d / "extensions.lock.json").is_file() else None


def _pins(vendor: Path) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    lines = (vendor / "extensions.txt").read_text(encoding="utf-8").splitlines()
    pins = [tuple(t.split("@", 1)) for t in (x.strip() for x in lines) if t and not t.startswith("#") and "@" in t]
    lock = json.loads((vendor / "extensions.lock.json").read_text(encoding="utf-8")).get("extensions") or {}
    return [(a, b) for a, b in pins], lock


def _terminal_profiles() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    profiles: dict[str, Any] = {
        "PowerShell": {"path": str(Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"),
                       "icon": "terminal-powershell"},
        "Command Prompt": {"path": str(Path(root) / "System32" / "cmd.exe"), "icon": "terminal-cmd"},
    }
    from edp_contracts.toolpath import git_bash
    with contextlib.suppress(Exception):
        bash = git_bash()
        if bash:
            profiles["Git Bash"] = {"path": bash, "args": ["--login", "-i"], "icon": "terminal-bash"}
    return {"terminal.integrated.profiles.windows": profiles, "terminal.integrated.defaultProfile.windows": "PowerShell"}


def _seed_settings(pins: list[tuple[str, str]], lock: dict[str, Any]) -> str:
    """User settings: merge the managed keys, keep everything else the user set."""
    path = user_dir() / "User" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    cur: dict[str, Any] = {}
    note = "settings.json: managed keys merged"
    if path.is_file():
        try:
            got = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
            cur = got if isinstance(got, dict) else {}
        except ValueError:
            bak = path.with_name(f"settings.json.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}")
            bak.write_bytes(path.read_bytes())
            note = f"settings.json did not parse as JSON; kept a copy at {bak} and re-seeded"
    exclude = {g: True for g in ("**/.venv/**", "**/node_modules/**", "**/.data/**", "**/.run/**", "**/.tools/**",
                                 "**/web/dist/**")}
    board = _board_url()
    managed: dict[str, Any] = {
        "git.openRepositoryInParentFolders": "always",
        "extensions.autoUpdate": False,
        "extensions.autoCheckUpdates": True,
        "files.watcherExclude": exclude,
        "search.exclude": exclude,
        "gitlens.autolinks": [{"prefix": pre, "url": f"{board}/ui/ticket/{pre}<num>", "alphanumeric": True,
                               "ignoreCase": False, "title": f"Open {pre}<num> on the board"}
                              for pre in ("t-", "s-", "epic-", "m-")],
        "gitlens.hovers.currentLine.over": "line",
        "telemetry.telemetryLevel": "off",
        "update.mode": "none",
        "files.refactoring.autoSave": False,
        **_terminal_profiles(),
    }
    if pins:
        allowed: dict[str, Any] = {}
        for ext_id, ver in pins:
            tp = (lock.get(ext_id) or {}).get("target_platform")
            allowed[ext_id] = [f"{ver}@{tp}" if tp and tp != "universal" else ver]
        allowed["edp.edp-code"] = True
        managed["extensions.allowed"] = allowed
    cur.update(managed)
    chrome = {"window.menuBarVisibility": "classic", "workbench.activityBar.location": "default",
              "workbench.statusBar.visible": True, "zenMode.restore": False}
    for k, v in chrome.items():
        cur.setdefault(k, v)
    path.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    return note


def _cli(inst: Install, args: list[str], timeout: float = 600.0) -> tuple[int, list[str]]:
    """code-server in CLI mode (extension installs) with the fleet env stripped and no gallery: with one,
    a vsix's pack/dependencies were fetched from Open VSX unchecked and replaced our files."""
    import subprocess

    from edp_contracts.proc import hidden_flags
    env = server_env()
    env["EXTENSIONS_GALLERY"] = "{}"
    argv = [*inst.argv, "--user-data-dir", str(user_dir()), "--extensions-dir", str(ext_dir()), *args]
    out = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                         creationflags=hidden_flags())
    lines = [ln for ln in (out.stdout + "\n" + out.stderr).splitlines()
             if ln.strip() and "DeprecationWarning" not in ln and "trace-deprecation" not in ln]
    return out.returncode, lines


def _install_extensions(inst: Install, vendor: Path, pins: list[tuple[str, str]], lock: dict[str, Any]) -> str:
    """Install the missing pins from sha256-checked .vsix files, in ONE call (a file-by-file install fetched
    a missing dependency from the gallery), then verify every pin is at its version."""
    cache = (settings.home() or data_root()) / ".tools" / "vsix"
    cache.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    for ext_id, ver in pins:
        e = lock.get(ext_id) or {}
        if e.get("version") != ver:
            raise CodeError(f"{ext_id}@{ver} has no matching entry in {vendor / 'extensions.lock.json'}")
        pat = re.compile("^" + re.escape(f"{ext_id}-{ver}") + r"(-[a-z0-9]+(-[a-z0-9]+)?)?$")
        if ext_dir().is_dir() and any(pat.match(d.name) for d in ext_dir().iterdir() if d.is_dir()):
            continue
        f = cache / Path(urllib.parse.urlparse(e["url"]).path).name
        if not f.is_file():
            part = f.with_name(f.name + ".part")
            with urllib.request.urlopen(e["url"], timeout=120) as r, open(part, "wb") as out:
                while chunk := r.read(1 << 20):
                    out.write(chunk)
            os.replace(part, f)
        got = hashlib.sha256(f.read_bytes()).hexdigest()
        if got != str(e.get("sha256", "")).lower():
            f.unlink(missing_ok=True)
            raise CodeError(f"sha256 mismatch for {ext_id}@{ver} (lock {e.get('sha256')}, file {got}); not installed")
        missing.append(str(f))
    if missing:
        args: list[str] = []
        for f in missing:
            args += ["--install-extension", f]
        rc, lines = _cli(inst, [*args, "--force"])
        if rc != 0:
            raise CodeError(f"installing {', '.join(missing)} failed ({rc}): {' | '.join(lines[-5:])}")
    rc, lines = _cli(inst, ["--list-extensions", "--show-versions"])
    have = {m.group(1).lower(): m.group(2) for m in (re.match(r"^([\w.-]+)@(\S+)$", ln) for ln in lines) if m}
    wrong = [f"{i}@{v} (installed: {have.get(i.lower())})" for i, v in pins if have.get(i.lower()) != v]
    if wrong:
        raise CodeError(f"extensions not at their pins: {'; '.join(wrong)}")
    vsix = sorted((vendor / "edp-code").glob("*.vsix"), key=lambda p: p.stat().st_mtime, reverse=True)
    if vsix:
        rc, lines = _cli(inst, ["--install-extension", str(vsix[0]), "--force"])
        if rc != 0:
            raise CodeError(f"installing {vsix[0].name} failed ({rc}): {' | '.join(lines[-5:])}")
    return f"extensions: all {len(pins)} pins installed at their pinned versions"


# ------------------------------------------------------------------------------------------ start

@contextlib.contextmanager
def _start_lock() -> Iterator[None]:
    """One start at a time: a retry must not race the first start's seeding or its listener check."""
    path = settings.run_dir() / "code.start.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # a lock left by a crashed start (its pid gone) is taken over; a live one refuses
        try:
            holder = ProcId.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            holder = None
        if holder is not None and holder.live() is not None:
            raise CodeError(f"another code start is running (pid {holder.pid} holds {path}); wait for it") from None
        path.unlink(missing_ok=True)
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ProcId.of(os.getpid()).to_json(), f)
        yield
    finally:
        path.unlink(missing_ok=True)


def guard_argv(args: list[str]) -> list[str]:
    """The guard's argv: the bundle's `--heronry-service code-guard` re-entry, else this interpreter -m."""
    from . import launcher
    if launcher.bundled():
        return [launcher.bundle_exe(), launcher.SERVICE_FLAG, GUARD_SERVICE, *args]
    return [sys.executable, "-m", GUARD_MODULE, *args]


def _log(name: str) -> Path:
    d = settings.logs_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def _cwd() -> str:
    home = settings.home()
    if home is not None and settings.dev_mode():
        return str(home)
    d = settings.data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def start(*, wait_s: float = 60.0, extensions: bool = True, say=None) -> dict[str, Any]:
    """Start the code service unless this home's already runs. Returns {service, state: started |
    already_running | not_installed, pid, guard_pid, url, reason}. Raises CodeError on a refusal or a failed
    start (after rolling back what it launched)."""
    tell = say or (lambda _m: None)
    host = bind_host()
    p = port()
    with _start_lock():
        if _listening(p):
            st = status()
            if st["state"] == "up" and workbench(record().get("mint_key"), p):
                return {"service": SERVICE, "state": "already_running", "pid": st["pid"], "guard_pid": st["guard_pid"],
                        "url": url()}
            if st["state"] == "foreign":
                raise CodeError(f"port {p} is held by pid {st['pid']}, not this Heronry's code server; leaving it "
                                f"alone (choose another port: code_server.port)")
            raise CodeError(f"port {p} is held by this home's code guard, but the recorded code-server behind it is "
                            "missing, unverified or not serving the workbench: heronry restart code")
        inst = locate()
        if inst is None:
            return {"service": SERVICE, "state": "not_installed", "pid": None, "url": None,
                    "reason": f"code-server is not installed: {install_hint()}", "install_hint": install_hint()}
        for d in (data_root(), user_dir() / "User", ext_dir(), settings.run_dir()):
            d.mkdir(parents=True, exist_ok=True)
        inner = _free_port(p)
        config = data_root() / "code-server.yaml"
        # our own config, so a flag-less launch never falls back to :8080; the password is never in it
        config.write_text(f"# written by heronry start code on every start; edits are overwritten\n"
                          f"bind-addr: {host}:{inner}\nauth: password\ncert: false\n", encoding="utf-8")
        tell(_seed_coder_json())
        vendor = _vendor_dir()
        pins, lock = _pins(vendor) if vendor is not None else ([], {})
        tell(_seed_settings(pins, lock))
        if not extensions:
            tell("extensions: skipped")
        elif vendor is None:
            tell("extensions: no vendored list (vscode-ext) here; skipped")
        else:
            tell(_install_extensions(inst, vendor, pins, lock))
        secret, mint_key = secrets.token_hex(32), secrets.token_hex(32)
        server_args = [*inst.argv, "--bind-addr", f"{host}:{inner}", "--auth", "password", "--log", "info",
                       "--disable-telemetry", "--disable-update-check", "--disable-proxy", "--config", str(config),
                       "--user-data-dir", str(user_dir()), "--extensions-dir", str(ext_dir())]
        senv = server_env()
        # code-server deletes $HASHED_PASSWORD after reading it, so terminals never inherit it
        senv["HASHED_PASSWORD"] = secret
        # the original app port in a URL-parseable path: the board redirects the browser, never proxies
        senv["VSCODE_PROXY_URI"] = f"{_board_url()}/v1/code/external/{{{{port}}}}/"
        rec: dict[str, Any] = {"service": SERVICE, "port": p, "inner_port": inner, "version": inst.version,
                               "install_dir": inst.tag, "source": inst.source, "user_dir": str(user_dir()),
                               "started_at": run_state.now_iso(), "git_rev": run_state.git_rev(),
                               "home_id": my_home_id(), "mint_key": mint_key, "restarts": 0,
                               "last_restart_reason": None}
        from . import launcher
        via = launcher._detach_via()
        server, _ = detach(server_args, cwd=_cwd(), env=senv, log=str(_log("code.log")), via=via)
        sjob = job_name("svc", f"code-{p}")
        assign_job(sjob, server.pid)
        # recorded at once, so a failing guard launch never leaves an unrecorded server
        rec.update(pid=server.pid, server=server.to_json(), server_job=sjob,
                   creation_date=datetime.fromtimestamp(server.create_time, timezone.utc).isoformat())
        _write_record(rec)
        try:
            gargs = ["--port", str(p), "--upstream", f"tcp:{host}:{inner}"]
            for o in _origins():
                gargs += ["--allow-origin", o]
            gargs += ["--tag", inst.tag]
            genv = guard_env()
            genv["CODE_GUARD_SESSION"] = secret
            genv["CODE_GUARD_MINT_KEY"] = mint_key
            guard, _ = detach(guard_argv(gargs), cwd=_cwd(), env=genv, log=str(_log("code.guard.log")), via=via)
            gjob = job_name("svc", f"code-guard-{p}")
            assign_job(gjob, guard.pid)
            rec.update(guard_pid=guard.pid, guard=guard.to_json(), guard_job=gjob,
                       guard_creation_date=datetime.fromtimestamp(guard.create_time, timezone.utc).isoformat())
            _write_record(rec)
            _wait_ready(server, guard, p, inner, mint_key, wait_s)
        except BaseException as e:
            rep = stop()
            tail = "" if not rep["survivors"] else f"; survivors {rep['survivors']}"
            if isinstance(e, CodeError):
                raise CodeError(f"{e} (rolled back{tail})") from None
            raise
        lp = run_state.listener_pid(p)
        if lp:
            rec["guard_listener_pid"] = lp
            _write_record(rec)
        return {"service": SERVICE, "state": "started", "pid": server.pid, "guard_pid": guard.pid, "url": url(),
                "inner_port": inner}


def _wait_ready(server: ProcId, guard: ProcId, p: int, inner: int, mint_key: str, wait_s: float) -> None:
    logs = f"see {_log('code.log')} / {_log('code.guard.log')}"
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline and not healthy(p):
        if server.live() is None:
            raise CodeError(f"code-server exited before /healthz answered; {logs}")
        if guard.live() is None:
            raise CodeError(f"the code guard exited before /healthz answered; {logs}")
        time.sleep(0.3)
    if not healthy(p):
        raise CodeError(f"code-server behind the guard did not answer /healthz within {int(wait_s)} s; {logs}")
    # the inner port was free when chosen, but anything could have taken it before code-server bound it: the
    # guard hands its secret to whatever listens there, so that must be this start's code-server
    ip = run_state.listener_pid(inner)
    if not _in_tree(server, ip):
        raise CodeError(f"the inner port {inner} is held by pid {ip}, not this code-server")
    if not _in_tree(guard, run_state.listener_pid(p)):
        raise CodeError(f"port {p} is answered by pid {run_state.listener_pid(p)}, not this start's guard")
    if not workbench(mint_key, p):
        raise CodeError("the guard did not refuse a cookie-less request with 401, or the workbench did not answer "
                        f"through it after a guard login (the session cookie was not accepted); {logs}")


# ------------------------------------------------------------------------------------------ stop

def stop(*, grace: float = 4.0, timeout_s: float = 20.0) -> dict[str, Any]:
    """Stop this home's code service: kill_tree of the recorded server and guard identities (snapshot first)
    plus their named jobs, and this home's guard on the port when unrecorded. A listener that is not this
    home's is never touched. Returns {service, state: stopped|not_running, killed, survivors}."""
    rec = record()
    p = int(rec.get("port") or port())
    server, guard = _idents(rec)
    targets: list[tuple[ProcId, str | None]] = []
    if server is not None and server.live() is not None:
        targets.append((server, rec.get("server_job")))
    if guard is not None and guard.live() is not None:
        targets.append((guard, rec.get("guard_job")))
    lp = run_state.listener_pid(p) if _listening(p) else None
    if lp and not any(_in_tree(t, lp) for t, _ in targets):
        # an unrecorded listener is stopped only when it is this home's guard (its /__edp/home says so)
        lid = ProcId.try_of(lp)
        if lid is not None and guard_home_id(p) == my_home_id():
            targets.append((lid, None))
    if not targets:
        for j in (rec.get("server_job"), rec.get("guard_job")):
            if j:
                terminate_job(j)
        _clear_record()
        return {"service": SERVICE, "state": "not_running", "killed": 0, "survivors": []}
    killed, survivors = 0, []
    for ident, job in targets:
        rep = kill_tree(ident, grace=grace, job=job)
        killed += rep.killed
        survivors.extend(rep.survivors)
    # the port closes once the guard is gone; still held by this home's guard = a survivor
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and _listening(p) and guard_home_id(p) == my_home_id():
        time.sleep(0.25)
    survivors = [s for s in survivors if s.live() is not None]
    if _listening(p) and guard_home_id(p) == my_home_id():
        held = ProcId.try_of(run_state.listener_pid(p))
        if held is not None and all(s.pid != held.pid for s in survivors):
            survivors.append(held)
    if not survivors:
        _clear_record()
    return {"service": SERVICE, "state": "stopped", "killed": killed, "survivors": [s.to_json() for s in survivors]}


def restart(**kw: Any) -> dict[str, Any]:
    old = record()
    out = stop()
    if out["survivors"]:
        raise CodeError(f"code: could not stop {out['survivors']}")
    got = start(**kw)
    if got.get("state") == "started":
        rec = record()
        rec["restarts"] = int(old.get("restarts") or 0) + 1
        _write_record(rec)
        got["state"] = "restarted"
    return got
