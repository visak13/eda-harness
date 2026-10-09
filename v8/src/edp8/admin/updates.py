"""Admin → Updates (design-e963c656f5 §4.8): the Releases check and apply.

* GET  /v1/admin/updates — current version, the latest release (the same once-a-day, ETag-cached GitHub
  check `heronry update --check` makes; `?force=true` checks now), and the last apply: the request
  (who, when), the helper's outcome (update-result.json) and the tail of the update log.
* POST /v1/admin/updates/apply — refuses what `heronry update` would refuse up front (dev checkout, an update
  already running, not a `uv tool` install, a pool that cannot be asked to park seats), then asks the supervisor (control
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
    res = updater.last_result()  # whichever runner wrote it (MSI runner or uv helper): the newest file
    if res is not None:
        res = {**{k: v for k, v in res.items() if not k.startswith("_")}, "text": updater.result_text(res)}
    return {"request": _read_json(run / "update-request.json"), "result": res,
            "staged": updater.update_staged(),
            "log": _tail(settings.logs_dir() / "update.log") or _tail(settings.logs_dir() / "update-run.out")}


def refusal(force: bool) -> str | None:
    """What `heronry update` would refuse before touching anything (the rest it checks itself). Live seats are not a
    refusal (S10): the update parks them and the pool resumes them; only a pool that cannot answer is."""
    if settings.dev_mode():
        return "this is a source checkout (dev mode): update it with git"
    if not launcher.bundled() and not updater._uv_tool_env() and not settings.env_raw("EDP_UPDATE_INSTALL_CMD"):
        return "this install was not made by `uv tool install`; re-run the install script instead"
    if updater.update_staged():
        return "an update is already running; wait for its outcome"
    if launcher.bundled() and updater.install_scope_busy():
        return "Windows Installer is busy; try again in a minute"
    if not force and launcher.live_seats() is None:
        return launcher.seat_block(None, "apply with force to update without parking seats")
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
