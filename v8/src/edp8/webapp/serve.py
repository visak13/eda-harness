"""Serve the Vite SPA bundle from FastAPI under a path prefix (design §4.1).

Seam proven in S1: a gitignored `dist/` (force-included into the wheel) is served under
`{prefix}` with an immutable cache on `{prefix}/assets/*` and a no-store SPA fallback that
returns `index.html` for every other `{prefix}` path. A missing/empty build yields a 503
"web app not built" page (architect ruling m-f0a5330767) — a service-unavailable state,
never a failed `create_app()`, so a source checkout still boots and every `/v1` and `/ui`
route is unaffected.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

log = logging.getLogger("edp8.webapp")

# Default build location: src/edp8/webapp/dist (this file is src/edp8/webapp/serve.py).
DIST_DIR = Path(__file__).resolve().parent / "dist"

_IMMUTABLE = "public, max-age=31536000, immutable"
_BUILD_CMD = "npm --prefix web ci && npm --prefix web run build"


def _not_built_page(prefix: str) -> str:
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<title>edp8 — web app not built</title></head><body>"
        "<h1>web app not built</h1>"
        f"<p>The SPA bundle is missing. Build it with: <code>{_BUILD_CMD}</code>, "
        f"then reload <code>{prefix}</code>.</p>"
        "</body></html>"
    )


class _ImmutableStatic(StaticFiles):
    """StaticFiles that stamps a long immutable cache on the fingerprinted assets."""

    async def get_response(self, path: str, scope: Scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = _IMMUTABLE
        return resp


def mount_spa(app: FastAPI, prefix: str, dist: str | Path | None = None) -> bool:
    """Mount the SPA at ``prefix`` (e.g. ``/app``). Returns True when a built bundle was
    found and served, False when the 503 not-built fallback was installed instead.

    Register this AFTER the legacy ``/ui`` router so ``/ui/poll`` and every ``/v1`` route
    keep priority; the catch-all only ever matches paths under ``prefix``.
    """
    prefix = "/" + prefix.strip("/")  # normalise: '/app', never '/app/' or 'app'
    dist_dir = Path(dist) if dist is not None else DIST_DIR
    index = dist_dir / "index.html"

    if not index.is_file():
        log.warning("SPA bundle missing at %s — serving 503 not-built page at %s (build: %s)",
                    dist_dir, prefix, _BUILD_CMD)

        async def not_built(path: str = "") -> HTMLResponse:
            return HTMLResponse(_not_built_page(prefix), status_code=503,
                                headers={"Cache-Control": "no-store"})

        app.add_api_route(prefix, not_built, methods=["GET"], include_in_schema=False)
        app.add_api_route(prefix + "/{path:path}", not_built, methods=["GET"], include_in_schema=False)
        return False

    assets = dist_dir / "assets"
    if assets.is_dir():
        # Fingerprinted, content-addressed files → cache forever. Mounted before the
        # catch-all so `{prefix}/assets/*` is served as static, not rewritten to index.
        app.mount(prefix + "/assets", _ImmutableStatic(directory=str(assets)), name="spa-assets")

    @app.get(prefix + "/notifications-worker.js", include_in_schema=False)
    async def notification_worker() -> FileResponse:
        # An unfingerprinted worker must revalidate, never receive the HTML fallback.
        return FileResponse(dist_dir / "notifications-worker.js", media_type="application/javascript",
                            headers={"Cache-Control": "no-store"})

    async def spa_index(path: str = "") -> FileResponse:
        # SPA fallback: any non-asset path under prefix returns index.html (client routes).
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-store"})

    app.add_api_route(prefix, spa_index, methods=["GET"], include_in_schema=False)
    app.add_api_route(prefix + "/{path:path}", spa_index, methods=["GET"], include_in_schema=False)
    log.info("SPA mounted at %s from %s", prefix, dist_dir)
    return True
