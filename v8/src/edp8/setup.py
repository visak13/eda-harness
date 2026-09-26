"""`heronry init` and `heronry doctor` (design-e963c656f5 §4.2, §4.4, §4.11; S3 s-870e401942).

init: the directories, config.toml, the random admin token and the first human's token (owner-only
files, S1 ``write_secret``), the agent home (S1 ``materialise``), the harness choice (at least one of
claude/codex; codex-less prints the Fable adversary notice), and claude's folder-trust entry for the agent
home in the pool's claude store (S2 finding m-33f96d11c9: an untrusted seat home stops at a dialog the
pool never answers). Re-running init repairs what is missing and never replaces a secret.

doctor: prerequisites and harnesses (with install links), ports, secret-file protection, the trust
entry and claude's sign-in for pool seats, and the control port. Exit 1 when anything FAILs.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import tomllib
from pathlib import Path
from typing import Any

from edp_contracts.settings import secrets as secret_files
from edp_contracts.settings._core import _flatten

from . import settings

INSTALL_LINKS = {
    "uv": "https://docs.astral.sh/uv/getting-started/installation/",
    "claude": "https://code.claude.com/docs/en/setup",
    "codex": "https://github.com/openai/codex#installation",
    "pi": "npm install -g @earendil-works/pi-coding-agent (guides/pi-seat.md)",
    "git": "https://git-scm.com/downloads",
    "node": "https://nodejs.org/en/download",
}
HARNESS_CHOICES = ("claude", "codex", "pi")


# ------------------------------------------------------------------------------------------ config.toml

def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return str(v)
    if isinstance(v, list | tuple):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v))  # a JSON string is a valid TOML basic string


def render_toml(values: dict[str, Any], header: str = "") -> str:
    """Dotted keys -> TOML tables (one level: `a.b` -> [a] b = …; `a.b.c` -> [a.b] c = …)."""
    tables: dict[str, dict[str, Any]] = {}
    for key, val in sorted(values.items()):
        table, _, leaf = key.rpartition(".")
        tables.setdefault(table, {})[leaf] = val
    out = [header.rstrip()] if header else []
    for table in sorted(tables):
        if table:
            out.append(f"\n[{table}]")
        for leaf, val in tables[table].items():
            out.append(f"{leaf} = {_toml_value(val)}")
    return "\n".join(out).lstrip("\n") + "\n"


_HEADER = """# Heronry configuration (written by `heronry init`; `heronry import` merges a v8 .env into it).
# Resolution: environment variable > this file > built-in default. Secrets are not kept here:
# the admin token and the participants' tokens live in the secrets directory (owner-only files)."""


def write_config(updates: dict[str, Any], remove: tuple[str, ...] | list[str] = ()) -> Path:
    """Merge dotted `updates` into config.toml (created when missing) and drop the `remove` keys (back to
    the default). Keys must be declared settings."""
    by_key = {s.key: s for s in settings.all_settings()}
    for k in [*updates, *remove]:
        if k not in by_key:
            raise settings.SettingsError(f"{k} is not a declared setting")
        if by_key[k].env_only:
            raise settings.SettingsError(f"{k} is environment-only and cannot live in config.toml")
    f = settings.config_file()
    current: dict[str, Any] = {}
    if f.is_file():
        current = _flatten(tomllib.loads(f.read_text(encoding="utf-8")))
    current.update({k: v for k, v in updates.items() if v is not None})
    for k in remove:
        current.pop(k, None)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(render_toml(current, _HEADER), encoding="utf-8")
    os.replace(tmp, f)
    return f


# ------------------------------------------------------------------------------------------ harnesses

def detect_harnesses() -> dict[str, str | None]:
    """{harness: path or None} via the S2 tool lookup (setting, else PATH)."""
    from edp_contracts.toolpath import find_tool
    keys = {"claude": "EDP_CLAUDE_BIN", "codex": "EDP_CODEX_BIN", "pi": "EDP_PI_BIN"}
    return {h: find_tool(h, key=keys[h]) for h in HARNESS_CHOICES}


def parse_harnesses(raw: str | bool | None) -> list[str]:
    if not raw or raw is True:
        return []
    picked = [h.strip().lower() for h in str(raw).replace(";", ",").split(",") if h.strip()]
    bad = [h for h in picked if h not in HARNESS_CHOICES]
    if bad:
        raise SystemExit(f"unknown harness {', '.join(bad)} (choose from {', '.join(HARNESS_CHOICES)})")
    return [h for h in HARNESS_CHOICES if h in picked]


# ------------------------------------------------------------------------------------------ claude trust

def claude_store() -> Path:
    """The CLAUDE_CONFIG_DIR pool-spawned claude seats use (never the operator's personal store)."""
    return Path(settings.get("EDP_CLAUDE_CONFIG_DIR"))


def _trust_key(p: Path) -> str:
    return str(p.resolve()).replace("\\", "/")


def write_trust(agent_home: Path, store: Path | None = None) -> Path:
    """Mark `agent_home` as a trusted folder in the pool's claude store (`projects[<path>]
    .hasTrustDialogAccepted`), preserving everything else in `.claude.json`."""
    store = store or claude_store()
    f = store / ".claude.json"
    data: dict[str, Any] = {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    projects = data.setdefault("projects", {})
    entry = projects.setdefault(_trust_key(agent_home), {})
    entry["hasTrustDialogAccepted"] = True
    store.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".claude.json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, f)
    return f


def trusted(agent_home: Path, store: Path | None = None) -> bool:
    """True when the agent home, or a folder above it, carries claude's trust flag in the pool store."""
    store = store or claude_store()
    try:
        projects = json.loads((store / ".claude.json").read_text(encoding="utf-8")).get("projects") or {}
    except (OSError, ValueError, AttributeError):
        return False
    here = Path(_trust_key(agent_home))
    for p in (here, *here.parents):
        if (projects.get(str(p).replace("\\", "/")) or {}).get("hasTrustDialogAccepted"):
            return True
    return False


def claude_signed_in(store: Path | None = None) -> bool:
    store = store or claude_store()
    if (store / ".credentials.json").is_file():
        return True
    try:
        return bool(json.loads((store / ".claude.json").read_text(encoding="utf-8")).get("oauthAccount"))
    except (OSError, ValueError, AttributeError):
        return False


# ------------------------------------------------------------------------------------------ init

def _say(tag: str, text: str) -> None:
    print(f"  {tag:<7} {text}")


def init_cmd(argv: list[str]) -> int:
    from . import harness, materialise
    from .cli import _split

    _, opts = _split(argv)
    if settings.dev_mode() and not opts.get("force"):
        print("refusing: EDP_HOME is a source checkout (dev mode); its services are configured by its .env. "
              "`heronry init` sets up an installed home (unset EDP_HOME, or point it at an empty folder).",
              file=sys.stderr)
        return 2
    detected = detect_harnesses()
    picked = parse_harnesses(opts.get("harness"))
    if not picked and "harness" not in opts and sys.stdin.isatty() and not opts.get("yes"):
        default = ",".join(h for h in ("claude", "codex") if detected[h]) or "claude"
        try:
            answer = input(f"harnesses to use (claude, codex, pi) [{default}]: ").strip() or default
        except EOFError:  # not really interactive (a pipe that claims a tty): no choice made
            answer = ""
        picked = parse_harnesses(answer)
    problem = harness.validate(picked)
    if problem:
        found = ", ".join(h for h, p in detected.items() if p) or "none"
        print(f"refusing: no harness selected — {problem}. Pass --harness claude,codex "
              f"(detected on this machine: {found}).", file=sys.stderr)
        return 2

    print(f"{settings.get('EDP_PRODUCT_NAME')} init")
    dirs = {"config": settings.config_dir(), "secrets": settings.secrets_dir(), "data": settings.data_dir(),
            "run": settings.run_dir(), "logs": settings.logs_dir(), "backups": settings.data_dir() / "backups"}
    for name, d in dirs.items():
        d.mkdir(parents=True, exist_ok=True)
        _say("dir", f"{name:<8} {d}")

    updates: dict[str, Any] = {"seats.harnesses": picked}
    if opts.get("owner"):
        updates["identity.owner"] = str(opts["owner"])
    for flag, key in (("board-port", "board.port"), ("mcp-port", "mcp.port"), ("pool-port", "pool.port"),
                      ("broker-port", "broker.port")):
        if opts.get(flag):
            updates[key] = int(str(opts[flag]))
    cfg = write_config(updates)
    _say("config", str(cfg))

    # secrets: generated once, never replaced by a re-run
    tok_file = settings.admin_token_file()
    if tok_file.exists():
        _say("keep", f"admin token {tok_file}")
    else:
        given = opts.get("admin-token")
        secret_files.write_secret(tok_file, str(given) if isinstance(given, str) else secrets.token_urlsafe(32))
        _say("secret", f"admin token {tok_file}")
    owner = str(settings.get("EDP8_OWNER"))
    tokens = Path(settings.get("EDP8_TOKENS"))
    if tokens.exists():
        _say("keep", f"tokens {tokens}")
    else:
        human = secrets.token_urlsafe(24)
        secret_files.write_secret(tokens, json.dumps({owner: human, "agents": {}}, indent=2))
        _say("secret", f"tokens {tokens} (first human: {owner})")

    home = settings.agent_home()
    src = opts.get("agent-home-source")  # a source-tree run (tests, CI) has no packaged agent home
    rep = materialise.materialise(home, str(src) if isinstance(src, str) else None)
    _say("agents", f"{home} ({len(rep.written)} new, {len(rep.updated)} updated, {len(rep.conflicts)} kept)")
    trust = write_trust(home)
    _say("trust", f"{home} trusted for claude seats ({trust})")

    _say("harness", ", ".join(f"{h}{'' if detected[h] else ' (not found)'}" for h in picked))
    missing = [h for h in picked if not detected[h]]
    for h in missing:
        _say("install", f"{h}: {INSTALL_LINKS[h]}")
    if "codex" not in picked:
        print()
        print(f"NOTICE: {harness.FABLE_RISK_NOTICE}")
    if "claude" in picked and not claude_signed_in():
        print()
        print(f"claude seats use their own store {claude_store()}: sign in once with "
              f"CLAUDE_CONFIG_DIR set to it, then run `claude` and /login (or copy your .credentials.json there).")
    print()
    print("next: heronry doctor, then heronry start")
    return 0


# ------------------------------------------------------------------------------------------ doctor

class _Report:
    def __init__(self) -> None:
        self.fails = 0
        self.warns = 0

    def ok(self, what: str, detail: str = "") -> None:
        print(f"  ok     {what}{'  ' + detail if detail else ''}")

    def warn(self, what: str, detail: str = "") -> None:
        self.warns += 1
        print(f"  WARN   {what}{'  ' + detail if detail else ''}")

    def fail(self, what: str, detail: str = "") -> None:
        self.fails += 1
        print(f"  FAIL   {what}{'  ' + detail if detail else ''}")


def _port_state(port: int) -> str:
    """free | ours | taken."""
    from . import run_state
    if not run_state._port_listening(port):
        return "free"
    return "listening"


def doctor_cmd(argv: list[str]) -> int:
    from edp_contracts.toolpath import find_tool, probe_version, tool_argv

    from . import control, harness, launcher, run_state

    r = _Report()
    mode = f"dev mode: {settings.home()}" if settings.dev_mode() else "installed"
    print(f"{settings.get('EDP_PRODUCT_NAME')} doctor ({mode})")

    print("prerequisites")
    if sys.version_info >= (3, 12):
        r.ok("python", sys.version.split()[0])
    else:
        r.fail("python", f"{sys.version.split()[0]} (3.12 or newer is required)")
    for tool, needed in (("uv", "updates"), ("git", "seats that commit"), ("node", "Pi seats, the codex Monitor")):
        path = find_tool(tool)
        if path:
            r.ok(tool, path)
        else:
            r.warn(tool, f"not found (needed for {needed}): {INSTALL_LINKS[tool]}")

    print("harnesses")
    picked = harness.selected({})
    detected = detect_harnesses()
    for h in HARNESS_CHOICES:
        path = detected[h]
        chosen = h in picked
        if path:
            ver = probe_version(tool_argv(path)) if h != "pi" else "present"
            if ver is None and chosen:
                r.fail(h, f"{path} does not answer --version")
            else:
                r.ok(h, f"{path} {ver or ''}{'' if chosen else ' (installed, not selected)'}".rstrip())
        elif chosen:
            r.fail(h, f"selected but not found: {INSTALL_LINKS[h]}")
        else:
            print(f"  -      {h}  not selected")
    if harness.validate(picked):
        r.fail("harness choice", "select at least one of claude and codex (heronry init --harness …)")
    if "codex" not in picked:
        r.warn("adversary", harness.FABLE_RISK_NOTICE)

    print("seats")
    home = settings.agent_home()
    if (home / ".claude" / "commands").is_dir():
        r.ok("agent home", str(home))
    else:
        r.fail("agent home", f"{home} has no role cards: run heronry init")
    if "claude" in picked:
        if trusted(home):
            r.ok("claude trust", f"{home} is a trusted folder in {claude_store()}")
        else:
            r.fail("claude trust", f"{home} is not trusted in {claude_store()}: seats stop at claude's folder-trust "
                   "dialog; run heronry init to write the trust entry")
        if claude_signed_in():
            r.ok("claude sign-in", str(claude_store()))
        else:
            r.warn("claude sign-in", f"{claude_store()} holds no sign-in: run claude once with CLAUDE_CONFIG_DIR set "
                   "to it and /login")

    print("secrets")
    try:
        settings.admin_token()
        where = settings.source("EDP8_ADMIN_TOKEN") if settings.is_set("EDP8_ADMIN_TOKEN") else settings.admin_token_file()
        r.ok("admin token", f"from {where}")
    except settings.SettingsError as e:
        r.fail("admin token", str(e))
    if not settings.dev_mode():
        for f in (settings.admin_token_file(), Path(settings.get("EDP8_TOKENS"))):
            if not f.exists():
                continue
            loose = secret_files.problems(f)
            if loose:
                r.fail("private file", "; ".join(loose))
            else:
                r.ok("private file", str(f))

    print("ports")
    for svc in ("board", "broker", "pool", "mcp"):
        p = launcher.port(svc)
        state = _port_state(p)
        if state == "free":
            r.ok(f"{svc} :{p}", "free")
        elif launcher.healthy(svc):
            r.ok(f"{svc} :{p}", f"in use by this {svc} (pid {run_state.listener_pid(p)})")
        else:
            r.fail(f"{svc} :{p}", f"taken by another program (pid {run_state.listener_pid(p)}); set {launcher.SPECS[svc].port_env}")
    cport = settings.get("EDP_CONTROL_PORT")
    if launcher.supervisor_running():
        r.ok("control port", f"127.0.0.1:{(run_state.read('supervisor') or {}).get('control_port')} (supervisor running)")
    else:
        try:
            with socket.socket() as s:
                s.bind(("127.0.0.1", int(cport or 0)))
            r.ok("control port", f"127.0.0.1:{cport or 'any free port'} can bind")
        except OSError as e:
            hint = ("; Windows reserves port ranges for Hyper-V/WinNAT: see `netsh int ipv4 show excludedportrange "
                    "protocol=tcp` and pick EDP_CONTROL_PORT outside them") if sys.platform == "win32" else ""
            r.fail("control port", f"cannot bind 127.0.0.1:{cport}: {e}{hint}")
    _ = control  # the control module is what the supervisor serves; imported so a broken install shows here

    print()
    print(f"{r.fails} failure(s), {r.warns} warning(s)")
    return 1 if r.fails else 0
