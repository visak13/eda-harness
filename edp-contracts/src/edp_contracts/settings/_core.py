"""The settings registry core: every knob declared once, resolved env > config.toml > default.

This module (with its sibling key modules) is the ONLY place in the four packages' ``src/`` trees that
reads ``os.environ`` (design-e963c656f5 §4.2, §4.8, OCAK A1). Everything else asks :func:`get` for a
declared setting, or uses :func:`environ_copy` / :func:`set_env` / :func:`pop_env` for the process
environment a child is launched with. ``tests/test_settings_registry.py`` enforces it.

Resolution is live on every call, so a test's ``monkeypatch.setenv`` is seen; only ``config.toml`` is
cached, by path and mtime.
"""
from __future__ import annotations

import os
import tomllib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import platformdirs

#: The per-OS directory name (the brand's CLI name, R8a); internal module names stay (R8b).
APP_DIR_NAME = "heronry"

TYPES = ("str", "int", "float", "bool", "path", "list", "url")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

Default = Any | Callable[[], Any]


class SettingsError(RuntimeError):
    """A setting is undeclared, declared twice, or refused (e.g. the `dev` admin token outside dev mode)."""


@dataclass(frozen=True)
class Setting:
    key: str                 # dotted config.toml key, e.g. "board.port"
    env: str                 # the environment variable name
    type: str                # one of TYPES
    default: Default         # a value, or a zero-arg callable for a derived default
    group: str               # Admin → Settings group (§4.8)
    doc: str                 # one line: what it does
    secret: bool = False     # write-only in the admin UI, masked on read
    restart_required: str = "none"  # the service to restart after a change, or "none"
    aliases: tuple[str, ...] = ()   # legacy env names, read after `env`
    env_only: bool = False   # process/identity/OS value: never read from config.toml
    default_doc: str = ""    # how a callable default is derived, for docs/UI
    choices: tuple[str, ...] = field(default=())

    def default_value(self) -> Any:
        return self.default() if callable(self.default) else self.default


REGISTRY: dict[str, Setting] = {}
_BY_KEY: dict[str, Setting] = {}


def declare(key: str, env: str, type: str, default: Default, group: str, doc: str, **kw: Any) -> Setting:
    """Declare one knob. A second declaration of the same env name or key is an error."""
    if type not in TYPES:
        raise SettingsError(f"{env}: unknown type {type!r}")
    if not doc.strip():
        raise SettingsError(f"{env}: a doc line is required")
    if env in REGISTRY or key in _BY_KEY:
        raise SettingsError(f"{env} / {key}: declared twice")
    s = Setting(key=key, env=env, type=type, default=default, group=group, doc=doc, **kw)
    REGISTRY[env] = s
    _BY_KEY[key] = s
    return s


def setting(env: str) -> Setting:
    try:
        return REGISTRY[env]
    except KeyError:
        raise SettingsError(f"{env} is not a declared setting (declare it in edp_contracts.settings)") from None


def all_settings() -> Iterator[Setting]:
    return iter(sorted(REGISTRY.values(), key=lambda s: (s.group, s.key)))


# ----------------------------------------------------------------------------- process environment

def environ_copy() -> dict[str, str]:
    """A copy of the process environment, for a child process's env."""
    return dict(os.environ)


def set_env(name: str, value: str) -> None:
    """Set a variable in this process's environment (inherited by children)."""
    os.environ[name] = value


def pop_env(name: str) -> str | None:
    """Remove a variable from this process's environment, returning it (a one-shot secret handoff)."""
    return os.environ.pop(name, None)


def env_raw(name: str) -> str | None:
    """The raw environment string of a DECLARED setting (primary name, then aliases); None when unset
    or blank. For sites that must tell "set" from "defaulted"."""
    s = setting(name)
    for n in (s.env, *s.aliases):
        v = os.environ.get(n)
        if v is not None and v.strip():
            return v
    return None


# ----------------------------------------------------------------------------- config.toml

_toml_cache: dict[Path, tuple[float, dict[str, Any]]] = {}


def _flatten(d: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        full = f"{prefix}{k}"
        if isinstance(v, Mapping):
            out.update(_flatten(v, full + "."))
        else:
            out[full] = v
    return out


def config_file() -> Path:
    return config_dir() / "config.toml"


def config_values() -> dict[str, Any]:
    """config.toml flattened to dotted keys; {} when absent or unreadable (mtime-cached)."""
    p = config_file()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    hit = _toml_cache.get(p)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        vals = _flatten(tomllib.loads(p.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError):
        vals = {}
    _toml_cache[p] = (mtime, vals)
    return vals


# ----------------------------------------------------------------------------- resolution

def _coerce(s: Setting, raw: Any) -> Any:
    if s.type in ("str", "url"):
        return str(raw)
    if s.type == "int":
        return int(str(raw).strip())
    if s.type == "float":
        return float(str(raw).strip())
    if s.type == "bool":
        if isinstance(raw, bool):
            return raw
        t = str(raw).strip().lower()
        if t in _TRUE:
            return True
        if t in _FALSE:
            return False
        raise ValueError(f"not a bool: {raw!r}")
    if s.type == "path":
        return Path(str(raw)).expanduser()
    if s.type == "list":
        if isinstance(raw, list | tuple):
            return [str(x).strip() for x in raw if str(x).strip()]
        return [x.strip() for x in str(raw).split(",") if x.strip()]
    raise SettingsError(f"{s.env}: unknown type {s.type}")


def source(name: str) -> str:
    """Where `name` resolves from right now: "env", "config" or "default"."""
    s = setting(name)
    if env_raw(name) is not None:
        return "env"
    if not s.env_only and s.key in config_values():
        return "config"
    return "default"


def get(name: str) -> Any:
    """The typed value of a declared setting: env (name, then aliases) > config.toml > default.
    A blank env value counts as unset; an unparseable value falls back to the next source."""
    s = setting(name)
    raw = env_raw(name)
    if raw is not None:
        try:
            return _coerce(s, raw)
        except ValueError:
            pass
    if not s.env_only:
        vals = config_values()
        if s.key in vals:
            try:
                return _coerce(s, vals[s.key])
            except ValueError:
                pass
    d = s.default_value()
    return d


def resolve(name: str) -> tuple[Any, str]:
    """(value, source) — what Admin → Settings shows ("env" is read-only there)."""
    return get(name), source(name)


def is_set(name: str) -> bool:
    """True when the setting is given by env or config.toml (not defaulted)."""
    return source(name) != "default"


# ----------------------------------------------------------------------------- directories

def home() -> Path | None:
    """`EDP_HOME` (legacy `EDP8_HOME`): one root for config, data, run and agent home; None when unset."""
    raw = env_raw("EDP_HOME")
    return Path(raw).expanduser().resolve() if raw else None


def _is_source_checkout(p: Path) -> bool:
    try:
        text = (p / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return False
    return 'name = "edp8"' in text and (p / "src" / "edp8").is_dir()


def dev_mode() -> bool:
    """Dev mode: EDP_HOME is a source checkout (this host: EDP_HOME=<repo>/v8), or EDP_DEV=1."""
    if get("EDP_DEV"):
        return True
    h = home()
    return h is not None and _is_source_checkout(h)


def _platform() -> platformdirs.PlatformDirs:
    # appauthor=False: no `heronry\heronry` nesting on Windows; roaming=False: the DB and tokens must not
    # sync over a roaming profile (strategyhl-86b4805322 §1).
    return platformdirs.PlatformDirs(APP_DIR_NAME, appauthor=False, roaming=False)


def config_dir() -> Path:
    """config.toml (and, installed, secrets/). EDP_HOME: the home itself (today's layout);
    installed: <platform config>/config."""
    raw = env_raw("EDP_CONFIG_DIR")
    if raw:
        return Path(raw).expanduser()
    h = home()
    return h if h is not None else Path(_platform().user_config_dir) / "config"


def secrets_dir() -> Path:
    """Secret files (tokens.json). EDP_HOME: the home (today's v8/tokens.json); installed: <config>/secrets."""
    h = home()
    return h if h is not None and env_raw("EDP_CONFIG_DIR") is None else config_dir() / "secrets"


def data_dir() -> Path:
    """db, uploads, broker data, agent home, backups. EDP_HOME: <home>/.data; installed: <platform data>/data."""
    raw = env_raw("EDP8_DATA")
    if raw:
        return Path(raw).expanduser()
    h = home()
    return h / ".data" if h is not None else Path(_platform().user_data_dir) / "data"


def run_dir() -> Path:
    """pid/state files (never user_runtime_dir: tmpfs/Temp). EDP_HOME: <home>/.run; installed:
    <platform state>/run."""
    raw = env_raw("EDP8_RUN_DIR")
    if raw:
        return Path(raw).expanduser()
    h = home()
    return h / ".run" if h is not None else Path(_platform().user_state_dir) / "run"


def logs_dir() -> Path:
    """Service logs. EDP_HOME: <data>/logs; installed: the platform log dir."""
    h = home()
    return data_dir() / "logs" if h is not None or env_raw("EDP8_DATA") else Path(_platform().user_log_dir)


def agent_home() -> Path:
    """The seats' home (cards, skills, guides, .mcp.json, models.json). Dev mode: EDP_HOME itself
    (the repo's v8/); installed: <data>/agent-home, materialised from package data."""
    raw = env_raw("EDP_AGENT_HOME")
    if raw:
        return Path(raw).expanduser()
    h = home()
    if h is not None and _is_source_checkout(h):
        return h
    if h is not None:
        return h / "agent-home"
    return data_dir() / "agent-home"


def admin_token() -> str:
    """The board admin token. The `dev` default (and an explicit `dev`) is refused outside dev mode."""
    tok = get("EDP8_ADMIN_TOKEN")
    if tok and tok != "dev":
        return tok
    if dev_mode():
        return tok or "dev"
    raise SettingsError(
        "EDP8_ADMIN_TOKEN is required outside dev mode: the 'dev' admin token is refused. "
        f"Set it in the environment or as edp8.admin_token in {config_file()}.")
