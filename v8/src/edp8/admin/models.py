"""Admin model catalog editor; catalog data is kept outside the agent-home payload."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from edp_contracts.toolpath import find_tool
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import harness, model_catalog, settings
from ..schemas import Participant
from .context import AdminContext


class CatalogIn(BaseModel):
    models: dict[str, dict[str, Any]]
    role_models: dict[str, list[str]]
    default_model: str | None = None  # omitted = keep the catalog's current default


class TestSpawnIn(BaseModel):
    model: str
    role: str
    effort: str | None = None


def _credentials() -> dict[str, Any]:
    raw = settings.get("EDP_PI_PROVIDER_CREDENTIALS") or "{}"
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _credential_present(provider: str) -> bool:
    if provider == "openai-codex":  # subscription login, not an API key
        return True
    row = _credentials().get(provider)
    if isinstance(row, dict) and row.get("api_key"):
        return True
    env = f"{provider.upper().replace('-', '_')}_API_KEY"
    return bool(settings.environ_copy().get(env))


def _warnings(models: dict[str, Any]) -> list[str]:
    keys = {"claude": "EDP_CLAUDE_BIN", "codex": "EDP_CODEX_BIN", "pi": "EDP_PI_BIN"}
    return sorted({f"{mid}: {row['harness']} harness is not installed" for mid, row in models.items()
                   if row.get("harness") in harness.HARNESSES and
                   find_tool(row["harness"], key=keys[row["harness"]]) is None})


def _harness_defaults(models: dict[str, Any]) -> dict[str, Any]:
    """For each Codex row: the window and compaction Codex itself applies (`codex debug models`), which
    the UI shows as "Codex default (N)" wherever the row leaves the number unset."""
    rows = [(mid, row) for mid, row in models.items()
            if isinstance(row, dict) and row.get("harness") in model_catalog.HARNESS_WINDOWS]
    if not rows:
        return {}
    known = model_catalog.codex_windows()
    return {mid: {**known[slug], "source": "codex debug models"}
            for mid, row in rows if (slug := str(row.get("model") or mid)) in known}


def _view(raw: dict[str, Any]) -> dict[str, Any]:
    models = raw.get("models") or {}
    return {"models": models, "role_models": raw.get("role_models") or {},
            "default_model": raw.get(model_catalog.DEFAULT_KEY),
            "harness_defaults": _harness_defaults(models),
            "selected": list(harness.selected(raw)), "warnings": _warnings(models)}


def _unselected_defaults(raw: dict[str, Any], body: CatalogIn, default: str | None) -> list[str]:
    """t-05df836c49: a PUT may not SET a default (a role's first model, or the catalog default) to a model
    whose harness is unselected. A stale default the PUT leaves unchanged is not refused: the page warns
    about it, and refusing would block every other save until the harness is selected."""
    picked = harness.selected(raw)
    old_roles = raw.get("role_models") or {}

    def needs(mid: str | None) -> str | None:
        h = (body.models.get(mid) or {}).get("harness") if mid else None
        return h if h in harness.HARNESSES and h not in picked else None

    errors = []
    for role, ids in body.role_models.items():
        new = ids[0] if ids else None
        if new != ((old_roles.get(role) or [None])[0]) and (h := needs(new)):
            errors.append(f"{role}: default {new} needs the {h} harness: select it or pick another")
    if default != raw.get(model_catalog.DEFAULT_KEY) and (h := needs(default)):
        errors.append(f"default model {default} needs the {h} harness: select it or pick another")
    return errors


def _catalog() -> dict:
    try:
        return model_catalog.read()
    except FileNotFoundError:
        # a plain refusal, never a 500: this home has no catalog and the build ships none
        raise HTTPException(404, "no model catalog on this home: run `heronry init` to create one") from None


def router(ctx: AdminContext, admin_actor) -> APIRouter:
    r = APIRouter()

    @r.get("/v1/admin/models")
    def get_models(a: Participant = Depends(admin_actor)):
        return {"ok": True, "value": _view(_catalog()), "hint": ""}

    @r.put("/v1/admin/models")
    def put_models(body: CatalogIn, a: Participant = Depends(admin_actor)):
        raw = _catalog()
        default = body.default_model if body.default_model is not None else raw.get(model_catalog.DEFAULT_KEY)
        errors = model_catalog.validate(body.models, body.role_models, default)
        for mid, row in body.models.items():
            if row.get("harness") == "pi" and not _credential_present(str(row.get("provider") or "")):
                errors.append(f"{mid}: provider credential missing for {row.get('provider')!r}")
        errors += _unselected_defaults(raw, body, default)
        if errors:
            # a plain sentence, like every other admin refusal: the UI shows error.message verbatim
            raise HTTPException(422, "; ".join(errors))
        raw["models"] = body.models
        raw["role_models"] = body.role_models
        if default:
            raw[model_catalog.DEFAULT_KEY] = default
        model_catalog.write(raw)
        return {"ok": True, "value": _view(raw), "hint": "catalog saved for new spawns"}

    @r.post("/v1/admin/models/test-spawn")
    def test_spawn(body: TestSpawnIn, a: Participant = Depends(admin_actor)):
        raw = _catalog()
        row = (raw.get("models") or {}).get(body.model)
        if not isinstance(row, dict) or body.model not in (raw.get("role_models") or {}).get(body.role, []):
            raise HTTPException(422, "model is not in this role's catalog")
        # A short-lived, isolated stub seat verifies the selected route and prompt/reply plumbing.
        # It does not spend provider tokens or join the resident fleet.
        prompt = "Reply with a short model-routing acknowledgement."
        script = ("import json,os,sys; p=sys.stdin.read(); "
                  "print(json.dumps({'reply':'Stub seat received: '+p,"
                  "'model':os.environ['TEST_MODEL'],'harness':os.environ['TEST_HARNESS'],"
                  "'provider':os.environ['TEST_PROVIDER']}))")
        env = {**settings.environ_copy(), "TEST_MODEL": body.model, "TEST_HARNESS": row["harness"],
               "TEST_PROVIDER": row["provider"]}
        proc = subprocess.run([sys.executable, "-c", script], input=prompt, text=True,
                              capture_output=True, env=env, timeout=10, check=True)
        return {"ok": True, "value": json.loads(proc.stdout), "hint": "private stub seat replied"}

    return r
