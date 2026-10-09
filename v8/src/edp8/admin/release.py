"""Admin → Updates → Cut release (S10 s-b431082892, owner R8 m-45367b2531).

* GET  /v1/admin/release — whether this caller can cut a release and why not: `{can_cut, reason, repo,
  default_ref, token_set, last}`. Only the owner (the init human, `EDP8_OWNER`) can; an admin flag is not enough.
* POST /v1/admin/release/cut — `{version, publish=false, dry_run=true}`: dispatches `release.yml` on the update
  repo through GitHub's REST API with the inputs `tag=v<version>`, `dry_run`, `publish`. A dry run validates only
  (no tag, no build, no release); `dry_run=false` tags when absent, builds and drafts; `publish=true` on top
  publishes. Answers 202 with the Actions run list; the token (setting `update.release_token`) is never echoed.

Every cut is appended to `<data>/release-cuts.jsonl` (who, when, tag, flags, the answer's status) and logged.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import settings
from ..schemas import Participant
from . import net
from .auth import owner_handle
from .context import AdminContext

log = logging.getLogger("edp8.admin.release")

WORKFLOW = "release.yml"
VERSION_RE = re.compile(r"^v?(\d+\.\d+\.\d+)$")


class CutIn(BaseModel):
    version: str
    publish: bool = False
    dry_run: bool = True


def audit_file() -> Path:
    return settings.data_dir() / "release-cuts.jsonl"


def _token() -> str:
    return str(settings.get("EDP_RELEASE_TOKEN") or "").strip()


def repo() -> str:
    return str(settings.get("EDP_UPDATE_REPO"))


def default_ref() -> str:
    return str(settings.get("EDP_RELEASE_REF") or "main")


def is_owner(p: Participant) -> bool:
    return p.type == "human" and p.handle.lstrip("@") == owner_handle()


def refusal(p: Participant) -> str | None:
    if not is_owner(p):
        return f"only the owner ({owner_handle()}) can cut a release"
    if not _token():
        return "no release token is set: add one under Settings → Updates → Release token"
    return None


def dispatch(repo_slug: str, ref: str, inputs: dict[str, str], token: str) -> tuple[int, str]:
    """THE seam (tests replace it): GitHub's workflow_dispatch for release.yml; (status, body text)."""
    url = f"{str(settings.get('EDP_UPDATE_API')).rstrip('/')}/repos/{repo_slug}/actions/workflows/{WORKFLOW}/dispatches"
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
               "X-GitHub-Api-Version": "2022-11-28"}
    with net.client(timeout=20.0) as c:
        r = c.post(url, headers=headers, json={"ref": ref, "inputs": inputs})
    return r.status_code, r.text[:300]


def runs_url(repo_slug: str) -> str:
    return f"https://github.com/{repo_slug}/actions/workflows/{WORKFLOW}"


def _last() -> dict[str, Any] | None:
    try:
        lines = audit_file().read_text(encoding="utf-8").splitlines()
        return json.loads(lines[-1]) if lines else None
    except (OSError, ValueError):
        return None


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def router(ctx: AdminContext, admin_actor) -> APIRouter:
    r = APIRouter()

    @r.get("/v1/admin/release")
    def release_get(a: Participant = Depends(admin_actor)):
        why = refusal(a)
        return {"ok": True, "value": {"can_cut": why is None, "reason": why, "repo": repo(), "default_ref": default_ref(),
                                      "token_set": bool(_token()), "last": _last()},
                "hint": "" if why is None else why}

    @r.post("/v1/admin/release/cut")
    def release_cut(b: CutIn, a: Participant = Depends(admin_actor)):
        m = VERSION_RE.match(b.version.strip())
        if not m:
            raise HTTPException(422, f"{b.version!r} is not a version like 0.10.0")
        why = refusal(a)
        if why:
            raise HTTPException(403, f"release refused: {why}")
        tag = f"v{m.group(1)}"
        publish = b.publish and not b.dry_run
        inputs = {"tag": tag, "dry_run": "true" if b.dry_run else "false", "publish": "true" if publish else "false"}
        token = _token()
        try:
            code, text = dispatch(repo(), default_ref(), inputs, token)
        except Exception as e:  # noqa: BLE001 — a transport error must not carry the token in its text
            raise HTTPException(502, f"could not reach GitHub: {_scrub(f'{type(e).__name__}: {e}', token)}") from None
        row = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "by": a.handle.lstrip("@"), "repo": repo(),
               "ref": default_ref(), **inputs, "status": code}
        try:
            audit_file().parent.mkdir(parents=True, exist_ok=True)
            with audit_file().open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except OSError:
            log.warning("could not append the release audit row")
        log.info("release cut by %s: %s dry_run=%s publish=%s -> %s", row["by"], tag, inputs["dry_run"],
                 inputs["publish"], code)
        if code != 204:
            raise HTTPException(502 if code >= 500 or code in (401, 403, 404, 422) else code,
                                f"GitHub refused the dispatch ({code}): {_scrub(text, token)}")
        return JSONResponse(status_code=202, content={
            "ok": True, "value": {**row, "runs_url": runs_url(repo())},
            "hint": ("dry run: validates only; nothing is tagged, built or published" if b.dry_run else
                     "tagging, building and drafting" + (" then publishing" if publish else "; publish the draft yourself"))})

    return r
