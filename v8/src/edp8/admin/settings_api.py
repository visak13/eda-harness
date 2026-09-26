"""Admin → Settings (design-e963c656f5 §4.8): every registry key, with its value and where it came from.

GET lists every visible declared setting (grouped) with type, doc, default, value, source (env | config |
default), restart_required and whether it can be edited here. A value given by the environment is shown
read-only (env wins, so editing the file would change nothing); an `env_only` key (process/OS/identity)
is never written to a file. A secret is write-only: GET says only whether it is set. Each row carries the
registry's tier (basic | advanced), plain label and help line and number unit (t-5dd0cc18ea); an `internal`
key (identity, OS, install layout, brand) is never listed and a PUT to it is refused.

PUT `{"values": {<key or ENV name>: value | null}}` validates every entry first (all or nothing), then
writes plain keys to config.toml and secret keys to the owner-only secrets settings file; null removes
the key (back to its default). The answer lists the services to restart for the change to apply.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from edp_contracts.settings import secrets as secret_files
from edp_contracts.settings._core import _coerce, _flatten

from .. import settings
from ..schemas import Participant
from ..setup import render_toml, write_config
from .context import AdminContext

MASK = "********"


class SettingsPut(BaseModel):
    values: dict[str, Any]


def _jsonable(v: Any) -> Any:
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, list | tuple):
        return [_jsonable(x) for x in v]
    if v is None or isinstance(v, bool | int | float | str):
        return v
    return str(v)


def read_only_reason(s: settings.Setting) -> str | None:
    if s.env_only:
        return f"environment-only ({s.env}): a process/identity value, never kept in a file"
    if settings.env_raw(s.env) is not None:
        return f"set by the environment variable {s.env} (read-only here; unset it to edit)"
    return None


def row(s: settings.Setting) -> dict[str, Any]:
    src = settings.source(s.env)
    out: dict[str, Any] = {
        "key": s.key, "env": s.env, "type": s.type, "group": s.group, "doc": s.doc, "secret": s.secret,
        "restart_required": s.restart_required, "env_only": s.env_only, "choices": list(s.choices),
        "tier": s.tier, "label": s.label, "help": s.help, "unit": s.unit,
        "source": src, "set": src != "default",
    }
    reason = read_only_reason(s)
    out["read_only"] = reason is not None
    out["read_only_reason"] = reason
    if s.secret:
        out["value"] = MASK if src != "default" else None
        out["default"] = None
        return out
    try:
        out["value"] = _jsonable(settings.get(s.env))
    except Exception as e:  # noqa: BLE001 — a derived default that cannot resolve here still renders
        out["value"] = None
        out["error"] = f"{type(e).__name__}: {e}"
    try:
        out["default"] = _jsonable(s.default_value())
    except Exception:  # noqa: BLE001
        out["default"] = None
    if s.default_doc:
        out["default_doc"] = s.default_doc
    return out


def listing() -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in settings.all_settings():
        if s.tier == "internal":
            continue
        groups.setdefault(s.group, []).append(row(s))
    return {"config_file": str(settings.config_file()),
            "groups": [{"group": g, "settings": rows} for g, rows in sorted(groups.items())]}


def _lookup(name: str) -> settings.Setting:
    for s in settings.all_settings():
        if name in (s.key, s.env):
            return s
    raise HTTPException(404, f"{name!r} is not a declared setting")


def _stored(s: settings.Setting, raw: Any) -> Any:
    """The value to keep in TOML, validated by the registry's own coercion."""
    try:
        v = _coerce(s, raw)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"{s.key}: not a valid {s.type} ({e})") from None
    if s.choices and str(v) not in s.choices:
        raise HTTPException(400, f"{s.key}: must be one of {', '.join(s.choices)}")
    if isinstance(v, Path):
        return str(v)
    return v


def write_secret_settings(updates: dict[str, Any], remove: list[str]) -> Path:
    """Merge into the owner-only secrets settings file: a fresh private temp file replaces it (the ACL /
    0600 travels with the new file), so a secret never lands in config.toml."""
    f = settings.secret_settings_file()
    current: dict[str, Any] = {}
    if f.is_file():
        current = _flatten(tomllib.loads(f.read_text(encoding="utf-8")))
    current.update(updates)
    for k in remove:
        current.pop(k, None)
    tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    secret_files.write_secret(tmp, render_toml(current, "# Secret settings written from Admin → Settings."))
    os.replace(tmp, f)
    return f


def apply(values: dict[str, Any]) -> dict[str, Any]:
    plain: dict[str, Any] = {}
    plain_rm: list[str] = []
    secret: dict[str, Any] = {}
    secret_rm: list[str] = []
    touched: list[settings.Setting] = []
    for name, raw in values.items():
        s = _lookup(name)
        reason = read_only_reason(s)
        if reason:
            raise HTTPException(409, f"{s.key}: {reason}")
        if s.tier == "internal":
            raise HTTPException(409, f"{s.key}: an internal setting (the install layout owns it), not edited here")
        if raw is None:
            (secret_rm if s.secret else plain_rm).append(s.key)
        else:
            (secret if s.secret else plain)[s.key] = _stored(s, raw)
        touched.append(s)
    if plain or plain_rm:
        write_config(plain, plain_rm)
    if secret or secret_rm:
        write_secret_settings(secret, secret_rm)
    restart = sorted({s.restart_required for s in touched if s.restart_required != "none"})
    return {"updated": [row(s) for s in touched], "restart_required": restart}


def router(ctx: AdminContext, admin_actor) -> APIRouter:
    r = APIRouter()

    @r.get("/v1/admin/settings")
    def settings_get(a: Participant = Depends(admin_actor)):
        return {"ok": True, "value": listing(), "hint": ""}

    @r.put("/v1/admin/settings")
    def settings_put(b: SettingsPut, a: Participant = Depends(admin_actor)):
        out = apply(b.values)
        hint = (f"restart {', '.join(out['restart_required'])} to apply" if out["restart_required"]
                else "applied (no restart needed)")
        return {"ok": True, "value": out, "hint": hint}

    return r
