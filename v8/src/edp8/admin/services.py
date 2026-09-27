"""Admin → Services (design-e963c656f5 §4.8): status of every service, and start/stop/restart through the
supervisor's loopback control port (strategyll-3b8f4033e0 §5). The board never stops or kills a process
itself: it asks the supervisor, which runs the one launcher path (graceful stop → kill_tree → start) and
records `service_restarted {by=<admin>}`.

Restarting (or stopping) the BOARD cannot be answered by the board that is being replaced, so that request
is handed to the supervisor on a background thread and answered 202 at once with the current
`started_at`; the UI polls `/healthz` until a new `started_at` appears.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import control, launcher, run_state
from ..schemas import Participant
from .context import AdminContext

VERBS = ("start", "stop", "restart")
#: the optional code server's row (S21): Admin names it code-server; the launcher, CLI and supervisor say `code`
CODE_ROW = "code-server"


class ServiceActionIn(BaseModel):
    force: bool = False        # pool stop/restart with live seats: take them offline
    keep_seats: bool = False   # pool: restart the pool process only, seats are re-adopted


def _code_server_row(r: dict[str, Any]) -> dict[str, Any]:
    """launcher.code_row() as Admin shows it: managed through the supervisor like the others (S21); a missing
    code-server says how to install it on this OS, and a port someone else holds is never ours to stop."""
    r = {**r, "service": CODE_ROW, "managed": True, "health": r["state"]}
    if r["state"] == "not_installed":
        r["health"] = "not installed"
        r["note"] = f"code-server is not installed. Install it: {r.get('install_hint')}"
    elif r["state"] == "foreign":
        r["note"] = r.get("reason")
    elif not r.get("autostart"):
        r["note"] = "optional: starts only when you start it (or turn on Start VS Code in the browser with Heronry)"
    return r


def status() -> dict[str, Any]:
    rows = launcher.status_rows()
    paused: list[str] = []
    failed: list[str] = []
    supervisor = {"running": launcher.supervisor_running(), "control": False}
    if supervisor["running"]:
        try:
            code, out = control.request("/status", timeout=10.0)
            if code == 200:
                supervisor["control"] = True
                paused, failed = list(out.get("paused") or []), list(out.get("failed") or [])
        except control.ControlUnavailable as e:
            supervisor["error"] = str(e)
    rows = [_code_server_row(r) if r["service"] == launcher.CODE else r for r in rows]
    for r in rows:
        svc = r["service"]
        if svc == CODE_ROW:
            continue
        rec = run_state.read(svc) or {}
        r["started_at"] = rec.get("started_at")
        r["rev"] = r.get("git_rev") or rec.get("git_rev")
        r["managed"] = svc in launcher.ORDER
        health = r.get("state")
        if svc in failed:
            health = "failed"
        elif svc in paused:
            health = "stopped by admin"
        r["health"] = health
    return {"services": rows, "supervisor": supervisor}


def _refuse_unavailable(e: Exception) -> HTTPException:
    return HTTPException(503, f"the supervisor is not running for this install ({e}); start it with "
                              "`heronry start` — the board never stops or starts services itself")


def router(ctx: AdminContext, admin_actor) -> APIRouter:
    r = APIRouter()

    @r.get("/v1/admin/services")
    def services_get(a: Participant = Depends(admin_actor)):
        return {"ok": True, "value": status(), "hint": ""}

    @r.post("/v1/admin/services/{svc}/{verb}")
    def service_action(svc: str, verb: str, b: ServiceActionIn | None = None,
                       a: Participant = Depends(admin_actor)):
        b = b or ServiceActionIn()
        if verb not in VERBS:
            raise HTTPException(404, f"no action {verb!r} (one of {', '.join(VERBS)})")
        if svc in (CODE_ROW, launcher.CODE):
            svc = launcher.CODE
        elif svc not in launcher.ORDER:
            raise HTTPException(404, f"unknown service {svc!r} (one of {', '.join((*launcher.ORDER, CODE_ROW))})")
        try:
            control.endpoint()
        except control.ControlUnavailable as e:
            raise _refuse_unavailable(e) from None
        body = {"by": a.handle.lstrip("@"), "force": b.force, "keep_seats": b.keep_seats}
        path = f"/services/{svc}/{verb}"
        if svc == "board" and verb in ("stop", "restart"):
            # the supervisor stops THIS process; the request must not wait on its own death
            before = (run_state.read("board") or {}).get("started_at")
            threading.Thread(target=_fire, args=(path, body), name=f"admin-{verb}-board", daemon=True).start()
            return JSONResponse(status_code=202, content={
                "ok": True, "value": {"service": "board", "state": "restarting" if verb == "restart" else "stopping",
                                      "started_at": before},
                "hint": "poll /healthz until started_at changes"})
        try:
            code, out = control.request(path, body)
        except control.ControlUnavailable as e:
            raise _refuse_unavailable(e) from None
        if code >= 400:
            raise HTTPException(code, str(out.get("error") or out))
        return {"ok": True, "value": out, "hint": f"{svc} {verb} done by the supervisor"}

    return r


def _fire(path: str, body: dict[str, Any]) -> None:
    try:
        control.request(path, body)
    except Exception:  # noqa: BLE001 — this process is usually gone before the answer arrives
        pass
