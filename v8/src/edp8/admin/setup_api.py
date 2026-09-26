"""The first-run wizard's record (design-e963c656f5 §4.8 Onboarding; S6 s-e6b4fa59d5).

`heronry start` opens `/ui/setup` while this install has no finished setup: it issues a one-time sign-in code
for the init human through the same invite store the Teammates panel uses (so the address bar never carries a
token) and opens the browser. The wizard (admin sign-in → harness detection → optional remote access → first
teammate) ends with POST `/v1/admin/setup/done`, which writes `setup.json` beside the DB; after that `start`
prints the board URL and opens nothing.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from .. import settings
from ..schemas import Participant
from .context import AdminContext

SETUP_FILE = "setup.json"


def setup_path() -> Path:
    return settings.data_dir() / SETUP_FILE


def state() -> dict[str, Any]:
    try:
        raw = json.loads(setup_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"done": False, "at": None, "by": None}
    return {"done": bool(raw.get("done")), "at": raw.get("at"), "by": raw.get("by")}


def mark_done(by: str) -> dict[str, Any]:
    p = setup_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    out = {"done": True, "at": datetime.now(UTC).isoformat(), "by": by}
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    os.replace(tmp, p)
    return out


def issue_setup_code() -> str:
    """A one-time sign-in code for the init human (24 h), redeemed by the wizard through /v1/join."""
    from .teammates import INVITES_FILE, InviteStore
    code, _ = InviteStore(settings.secrets_dir() / INVITES_FILE).issue(str(settings.get("EDP8_OWNER")), "heronry start",
                                                                            keep_token=True)
    return code


def router(ctx: AdminContext, admin_actor) -> APIRouter:
    r = APIRouter()

    @r.get("/v1/admin/setup")
    def setup_get(a: Participant = Depends(admin_actor)):
        return {"ok": True, "value": state(), "hint": ""}

    @r.post("/v1/admin/setup/done")
    def setup_done(a: Participant = Depends(admin_actor)):
        return {"ok": True, "value": mark_done(a.handle.lstrip("@")),
                "hint": "setup finished: `heronry start` opens the board from now on"}

    return r
