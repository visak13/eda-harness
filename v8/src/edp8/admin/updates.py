"""Admin → Updates (design-e963c656f5 §4.8): the Releases check and apply.

* GET  /v1/admin/updates — current version, the latest release (the same once-a-day, ETag-cached GitHub
  check `heronry update --check` makes; `?force=true` checks now), and the last apply: the request
  (who, when), the helper's outcome (update-result.json) and the tail of the update log.
* POST /v1/admin/updates/apply — refuses what `heronry update` would refuse up front (dev checkout,
  desktop bundle, not a `uv tool` install, live seats without force), then asks the supervisor (control
  port `/update`) to run `heronry update` detached. That command does backup → stop → upgrade → start, so
  the board answering this request is among what it stops; the answer is 202 and the UI polls `/healthz`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import control, launcher, settings, updater
from ..schemas import Participant
from .context import AdminContext


class ApplyIn(BaseModel):
    force: bool = False         # take live seats offline
    skip_compat: bool = False   # skip the custom-workflow compatibility check
    release_url: str | None = None  # a release folder/URL instead of GitHub's latest (tests, air-gapped)
    previous_url: str | None = None  # the installed version's release, for the rollback wheels (S11 F7)


def _read_json(f: Path) -> dict[str, Any] | None:
    try:
        v = json.loads(f.read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def _tail(f: Path, n: int = 20) -> list[str]:
    try:
        return f.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def last_apply() -> dict[str, Any]:
    run = settings.run_dir()
    req = _read_json(run / "update-request.json")
    return {"request": req, "result": _read_json(run / "update-result.json"),
            "log": _tail(settings.logs_dir() / "update.log") or _tail(settings.logs_dir() / "update-run.out")}


def refusal(force: bool) -> str | None:
    """What `heronry update` would refuse before touching anything (the rest it checks itself)."""
    if launcher.bundled():
        return "the desktop bundle updates through its installer; download the new release"
    if settings.dev_mode():
        return "this is a source checkout (dev mode): update it with git"
    if not updater._uv_tool_env() and not settings.env_raw("EDP_UPDATE_INSTALL_CMD"):
        return "this install was not made by `uv tool install`; re-run the install script instead"
    if not force:
        return launcher.seat_block(launcher.live_seats() if launcher.running("pool") else [],
                                   "apply with force to take them offline")
    return None


def router(ctx: AdminContext, admin_actor) -> APIRouter:
    r = APIRouter()

    @r.get("/v1/admin/updates")
    def updates_get(force: bool = False, a: Participant = Depends(admin_actor)):
        got = updater.check(force=force, timeout=10.0)
        cur = updater.current_version()
        return {"ok": True, "value": {
            "current": cur, "latest": (got or {}).get("latest"), "available": bool(got and got["newer"]),
            "url": (got or {}).get("url"), "checked": got is not None,
            "apply_refusal": refusal(force=True), "last": last_apply()},
            "hint": "" if got else "no answer from the releases API (offline, rate-limited, opted out or dev mode)"}

    @r.post("/v1/admin/updates/apply")
    def updates_apply(b: ApplyIn | None = None, a: Participant = Depends(admin_actor)):
        b = b or ApplyIn()
        why = refusal(b.force)
        if why:
            raise HTTPException(409, f"update refused: {why}")
        body = {"by": a.handle.lstrip("@"), "force": b.force, "skip_compat": b.skip_compat,
                "release_url": b.release_url, "previous_url": b.previous_url}
        try:
            code, out = control.request("/update", body, timeout=60.0)
        except control.ControlUnavailable as e:
            raise HTTPException(503, f"the supervisor is not running, so nothing can apply the update: {e}") from None
        if code != 202:
            raise HTTPException(code if code >= 400 else 502, str(out.get("error") or out))
        return JSONResponse(status_code=202, content={
            "ok": True, "value": out,
            "hint": "backing up, stopping, upgrading and starting; poll /healthz for a new started_at"})

    return r
