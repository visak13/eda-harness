"""The Code tab's board side (epic-91fcd3b370 S3, design-449b628cdd §4).

The SPA embeds code-server with a direct iframe (shape A, dec-ea925a2d30), so the board only tells
it WHERE the service is and WHETHER it is up: the port is never baked into the bundle. The FAQ the
tab links to is a guide file rendered through the same sanitised markdown path docs use.

S8 (s-17c13096e5): the guard in front of code-server relays only for a browser holding its cookie,
set by a one-time login token that only this board mints, and only for its human owner on the
board host (``POST /v1/code/session``). The mint key is the guard's per-start key from
``.run/code.json``, read on every mint so a code restart rotates it without a board restart.
"""
from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from edp_contracts.identity import home_id_of
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from edp8 import settings

from . import run_state
from .code_guard import HOME_PATH, mint_token
from .schemas import Participant, Role

_PROBE_TIMEOUT_S = 1.5


def code_port() -> int:
    """The code-server port: EDP_CODE_PORT (the variable edp.ps1 reads), default 9410."""
    return run_state._env_port("EDP_CODE_PORT", 9410)


def _home() -> Path:
    return settings.agent_home().resolve()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Whatever listens on the port must not steer the board's probe to another URL."""

    def redirect_request(self, *_args, **_kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def probe(port: int, timeout: float = _PROBE_TIMEOUT_S) -> bool:
    """code-server answers GET /healthz 200 with status alive|expired; expired only means idle.
    A redirect, any other status, a refusal or a timeout all count as not running."""
    try:
        with _OPENER.open(f"http://127.0.0.1:{port}/healthz", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _record() -> dict[str, Any]:
    """.run/code.json as start-code.ps1 wrote it; {} when absent or unreadable."""
    try:
        data = json.loads((run_state.run_dir() / "code.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _record_field(name: str) -> str | None:
    """A string field start-code.ps1 wrote to .run/code.json; None when absent or unreadable."""
    v = _record().get(name)
    return v if isinstance(v, str) and v else None


def listener_home_id(port: int, timeout: float = _PROBE_TIMEOUT_S) -> str | None:
    """The home id the guard on `port` reports (``GET /__edp/home``); None when it reports none."""
    try:
        with _OPENER.open(f"http://127.0.0.1:{port}{HOME_PATH}", timeout=timeout) as r:
            hid = json.loads(r.read(4096).decode("utf-8")).get("home_id") if r.status == 200 else None
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        return None
    return hid if isinstance(hid, str) and hid else None


def ours(port: int) -> bool:
    """The code-server on `port` is this home's: its guard reports this home's id, or (a guard from before the
    id route) it reports none and the listener is the guard pid this home's .run/code.json recorded for that
    port. Another home's listener is never adopted (S8 m-baed3c1589, t-cd13d98674)."""
    hid = listener_home_id(port)
    if hid is not None:
        return hid == home_id_of(settings.data_dir())
    rec = _record()
    try:
        recorded = int(rec.get("port") or 0) == port and int(rec.get("guard_pid") or 0)
    except (TypeError, ValueError):
        return False
    return bool(recorded) and run_state.listener_pid(port) == recorded


def _recorded_version() -> str | None:
    return _record_field("version")


def _local(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def code_status() -> dict[str, Any]:
    port = code_port()
    up = probe(port)
    mine = up and ours(port)
    return {
        "port": port,
        "url": f"http://127.0.0.1:{port}/",
        "running": mine,
        # something answers on the port but it is not this home's code-server: the tab says so, never embeds it
        "foreign": up and not mine,
        "version": _recorded_version(),
        # the folder the tab opens when the link names none: this board's own tree (v8)
        "default_folder": str(_home()),
        "start_command": ".\\edp.ps1 start code",
    }


def reset_layout_stamp() -> Path:
    """The Reset layout stamp the edp-code extension watches: its globalStorage dir under code-server's user
    data dir (``user_dir`` in .run/code.json, else the default ``<data>/code/user``)."""
    user = _record_field("user_dir")
    base = Path(user) if user else settings.data_dir() / "code" / "user"
    return base / "User" / "globalStorage" / "edp.edp-code" / "reset-layout.json"


def code_router(actor: Callable[..., Participant], render_markdown: Callable[[str], str],
                credentialed: Callable[[Participant], bool] = lambda _p: False) -> APIRouter:
    """``credentialed(p)``: p authenticated with a minted token (not a trusted-mode header alone);
    the default refuses every code session."""
    router = APIRouter()

    @router.get("/v1/code/external/{port}/{target_path:path}")
    def external(port: int, target_path: str, request: Request):
        """Browser-only redirect for code-server's external-URI template; never a server proxy.

        The template keeps {{port}} in the path so new URL() can parse it before substitution.
        Both peer and requested hostname must be local, including when the board is public.
        No credentials are required or forwarded: an ordinary browser navigation has none.
        """
        if not request.client or not _local(request.client.host) or not _local(request.url.hostname):
            return JSONResponse(status_code=403, content={"detail": "Code links are available on the board host only"})
        if not 1 <= port <= 65535:
            return JSONResponse(status_code=400, content={"detail": "Invalid localhost port"})
        target = f"http://127.0.0.1:{port}/" + quote(target_path, safe="/:@-._~!$&'()*+,;=")
        query = request.scope.get("query_string", b"").decode("ascii")
        if query:
            target += "?" + query
        return RedirectResponse(target, status_code=307, headers={"Cache-Control": "no-store"})

    @router.get("/v1/code")
    def code(response: Response, _: Participant = Depends(actor)):
        response.headers["Cache-Control"] = "no-store"
        return {"ok": True, "value": code_status(), "hint": ""}

    def owner_only(request: Request, who: Participant) -> JSONResponse | None:
        """403 unless the board's human owner, with a minted token, on the board host."""
        if who.type != "human" or who.role != Role.owner:
            return JSONResponse(status_code=403, content={
                "ok": False, "error": {"code": "forbidden", "message": "only the board's human owner opens the Code tab"},
                "hint": "the code session is minted for the owner's browser; agents never get one"})
        if not credentialed(who):
            # trusted mode takes X-Participant on its own: any local caller could claim the owner
            return JSONResponse(status_code=403, content={
                "ok": False, "error": {"code": "forbidden", "message": "the Code tab needs the owner's minted token (tokens.json)"},
                "hint": "a header-only identity never gets a code session"})
        if not request.client or not _local(request.client.host) or not _local(request.url.hostname):
            return JSONResponse(status_code=403, content={
                "ok": False, "error": {"code": "forbidden", "message": "Code sessions are minted on the board host only"},
                "hint": "open the board on its own machine (127.0.0.1)"})
        return None

    @router.post("/v1/code/session")
    def session(request: Request, response: Response, who: Participant = Depends(actor)):
        """A one-time, 60 s login token for the guard (``<guard>/__edp/login?t=<token>&next=<path>``).
        Only the board's human owner, on the board host: every agent token or seat gets 403."""
        if (refused := owner_only(request, who)) is not None:
            return refused
        key = _record_field("mint_key")
        if not key:
            return JSONResponse(status_code=503, content={
                "ok": False, "error": {"code": "unavailable", "message": "the code service record has no mint key"},
                "hint": "restart the code service (.\\edp.ps1 restart code)"}, headers={"Cache-Control": "no-store"})
        token, exp = mint_token(key)
        response.headers["Cache-Control"] = "no-store"
        return {"ok": True, "value": {"token": token, "expires_at": exp}, "hint": ""}

    @router.post("/v1/code/reset-layout")
    def reset_layout(request: Request, response: Response, who: Participant = Depends(actor)):
        """t-93da8bf09d: Code tab → Reset layout. Stamps a file in the edp-code extension's global storage;
        the extension in every open code-server window watches it and runs exitZenMode + resetViewLocations
        there (the workbench's layout lives in the browser, beyond the board's reach). Owner only, as a session."""
        if (refused := owner_only(request, who)) is not None:
            return refused
        stamp = reset_layout_stamp()
        stamp.parent.mkdir(parents=True, exist_ok=True)
        at = datetime.now(timezone.utc).isoformat()
        stamp.write_text(json.dumps({"at": at, "by": who.id}), encoding="utf-8")
        response.headers["Cache-Control"] = "no-store"
        return {"ok": True, "value": {"at": at}, "hint": "every open editor window leaves Zen mode and resets its views"}

    @router.get("/v1/code/faq")
    def faq(_: Participant = Depends(actor)):
        p = _home() / "guides" / "code-tab-faq.md"
        try:
            body = p.read_text(encoding="utf-8")
        except OSError:
            return JSONResponse(status_code=404, content={
                "ok": False, "error": {"code": "not_found", "message": "guides/code-tab-faq.md is missing"},
                "hint": "the FAQ ships with the board tree under guides/"})
        return {"ok": True, "value": {"name": "code-tab-faq", "path": "guides/code-tab-faq.md",
                                      "html": render_markdown(body)}, "hint": ""}

    return router
