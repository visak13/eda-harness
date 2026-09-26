"""A service's identity is its home, not its port (t-596660619c).

Two Heronry homes on one host (the fleet next to an install, two installs, a dev
checkout) can hold the same ports. Every service reports ``home_id`` (a stable id of
its resolved data dir) and ``home`` (that path) on its health route, and the launcher
acts on a listener only when the id matches its own: it never adopts, stops or claims
another home's service.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any


def home_id_of(data_dir: str | os.PathLike[str]) -> str:
    """16 hex chars of sha256 over the resolved path (case-folded on Windows/macOS)."""
    try:
        p = Path(data_dir).expanduser().resolve()
    except OSError:
        p = Path(os.path.abspath(Path(data_dir).expanduser()))
    text = str(p)
    if sys.platform in ("win32", "darwin"):
        text = text.casefold()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def home_identity() -> dict[str, Any]:
    """{home_id, home} of THIS process's data dir (EDP8_DATA, else EDP_HOME/.data, else
    the platform data dir). Never raises: an unresolvable home reports no identity."""
    try:
        from . import settings
        d = settings.data_dir()
    except Exception:  # noqa: BLE001 — a health route never fails over its identity
        return {}
    return {"home_id": home_id_of(d), "home": str(d)}
