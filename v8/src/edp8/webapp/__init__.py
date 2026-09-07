"""Serving layer for the Folio SPA: a Vite `dist/` mounted under a path prefix.

The build output lives at ``src/edp8/webapp/dist`` (gitignored, hatch force-included
into the wheel). :func:`mount_spa` wires it onto a FastAPI app with an immutable-cached
asset route and an SPA catch-all, degrading to a 503 "not built" page when the bundle is
absent so ``create_app()`` never fails on a source checkout.
"""

from .serve import DIST_DIR, mount_spa

__all__ = ["mount_spa", "DIST_DIR"]
