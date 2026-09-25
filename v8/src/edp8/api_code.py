"""The Code tab's board side (epic-91fcd3b370 S3, design-449b628cdd §4).

The SPA embeds code-server with a direct iframe (shape A, dec-ea925a2d30), so the board only tells
it WHERE the service is and WHETHER it is up: the port is never baked into the bundle. The FAQ the
tab links to is a guide file rendered through the same sanitised markdown path docs use.
"""
from __future__ import annotations

import ipaddress
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from . import run_state
from .schemas import Participant

_PROBE_TIMEOUT_S = 1.5


def code_port() -> int:
    """The code-server port: EDP_CODE_PORT (the variable edp.ps1 reads), default 9410."""
    return run_state._env_port("EDP_CODE_PORT", 9410)


def _home() -> Path:
    return Path(os.environ.get("EDP8_HOME", str(Path(__file__).resolve().parents[2]))).resolve()


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


def _recorded_version() -> str | None:
    """The version start-code.ps1 wrote to .run/code.json; None when absent or unreadable."""
    try:
        data = json.loads((run_state.run_dir() / "code.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    v = data.get("version") if isinstance(data, dict) else None
    return v if isinstance(v, str) and v else None


def code_status() -> dict[str, Any]:
    port = code_port()
    return {
        "port": port,
        "url": f"http://127.0.0.1:{port}/",
        "running": probe(port),
        "version": _recorded_version(),
        # the folder the tab opens when the link names none: this board's own tree (v8)
        "default_folder": str(_home()),
        "start_command": ".\\edp.ps1 start code",
    }


def code_router(actor: Callable[..., Participant], render_markdown: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/code/external/{port}/{target_path:path}")
    def external(port: int, target_path: str, request: Request):
        """Browser-only redirect for code-server's external-URI template; never a server proxy.

        The template keeps {{port}} in the path so new URL() can parse it before substitution.
        Both peer and requested hostname must be local, including when the board is public.
        No credentials are required or forwarded: an ordinary browser navigation has none.
        """
        def local(host: str | None) -> bool:
            if host == "localhost":
                return True
            try:
                return ipaddress.ip_address(host or "").is_loopback
            except ValueError:
                return False

        if not request.client or not local(request.client.host) or not local(request.url.hostname):
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
