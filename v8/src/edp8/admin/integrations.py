"""Admin → Integrations (design-e963c656f5 §4.8): Slack, Plane, code-server and VS Code, each with a
status, an edit and a test.

* **Slack** keeps `slack_map.json` as the backing store (no migration on this host). GET shows the map with
  the webhook(s) masked and the bot token as set/unset, plus the people the bridge will actually ping
  (the static map merged with each person's Settings). PUT merges: only the keys sent change, every
  other key — known or not — is written back unchanged; a masked value echoed back keeps the stored one;
  null removes a key. The file is rewritten owner-only (it holds the bot token). Test posts one line to
  the default webhook, or to one person's destination.
* **Plane** is four settings (`plane.*`, via the Settings panel's rules) and a test that reads the project.
* **code-server**: status from `api_code` and a probe; started by its own scripts.
* **VS Code**: the release page for the `.vsix`, the board URL and a sign-in deep link per teammate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from edp_contracts.settings import secrets as secret_files

from .. import settings
from ..schemas import Participant
from . import net, settings_api
from .context import AdminContext
from .teammates import VSCODE_EXTENSION_ID, board_url

MASK = settings_api.MASK
SLACK_SECRET_KEYS = ("bot_token",)
SLACK_WEBHOOK_KEYS = ("webhook_url",)
PLANE_KEYS = ("EDP8_PLANE_URL", "EDP8_PLANE_API_KEY", "EDP8_PLANE_WORKSPACE", "EDP8_PLANE_PROJECT",
              "EDP8_PLANE_STATES", "EDP8_PLANE_WEBHOOK_SECRET")


class SlackPut(BaseModel):
    values: dict[str, Any]


class SlackTestIn(BaseModel):
    handle: str | None = None


class PlanePut(BaseModel):
    values: dict[str, Any]


# ------------------------------------------------------------------------------------------ slack

def slack_path() -> Path:
    return Path(settings.get("EDP8_SLACK_MAP"))


def read_slack() -> dict[str, Any]:
    p = slack_path()
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise HTTPException(409, f"{p.name} is not valid JSON ({e}); fix it by hand before editing here") from None
    if not isinstance(raw, dict):
        raise HTTPException(409, f"{p.name} is not a JSON object")
    return raw


def mask_webhook(url: str | None) -> str | None:
    if not url:
        return None
    from ..user_settings import MASK_MARK
    parts = urlsplit(url)
    return f"{parts.scheme or 'https'}://{parts.hostname or ''}/{MASK_MARK}{url[-4:]}"


def _masked_person(person: Any) -> Any:
    if not isinstance(person, dict):
        return person
    out = dict(person)
    if out.get("webhook_url"):
        out["webhook_url"] = mask_webhook(out["webhook_url"])
    return out


def slack_view(cfg: dict[str, Any]) -> dict[str, Any]:
    from ..user_settings import bridge_people
    out: dict[str, Any] = {}
    for k, v in cfg.items():
        if k in SLACK_SECRET_KEYS:
            out[k] = MASK if v else None
        elif k in SLACK_WEBHOOK_KEYS:
            out[k] = mask_webhook(v)
        elif k == "people" and isinstance(v, dict):
            out[k] = {h: _masked_person(p) for h, p in v.items()}
        else:
            out[k] = v
    static = cfg.get("people") if isinstance(cfg.get("people"), dict) else {}
    try:
        per_person = bridge_people()
    except Exception:  # noqa: BLE001 — a broken ui-settings.json must not hide the map
        per_person = {}
    merged = {h: {**_masked_person(p), "source": "slack_map.json"} for h, p in static.items()}
    for h, p in per_person.items():
        merged[h] = {**_masked_person(p), "source": "person settings"}
    return {"path": str(slack_path()), "exists": slack_path().is_file(), "config": out,
            "bot_token_set": bool(cfg.get("bot_token")), "webhook_set": bool(cfg.get("webhook_url")),
            "people_effective": merged}


def _is_echo(v: Any) -> bool:
    from ..user_settings import is_masked_webhook
    return v == MASK or (isinstance(v, str) and is_masked_webhook(v))


def _check_webhook(v: Any, where: str) -> None:
    from ..user_settings import valid_webhook
    if v is not None and not _is_echo(v) and not valid_webhook(str(v)):
        raise HTTPException(400, f"{where}: not an allow-listed https Slack webhook")


def merge_slack(cfg: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    out = dict(cfg)
    for k, v in values.items():
        if v is None:
            out.pop(k, None)
            continue
        if k in (*SLACK_SECRET_KEYS, *SLACK_WEBHOOK_KEYS) and _is_echo(v):
            continue  # the UI echoed the mask back: keep what is stored
        if k in SLACK_WEBHOOK_KEYS:
            _check_webhook(v, k)
        if k == "people":
            if not isinstance(v, dict):
                raise HTTPException(400, "people must be an object of handle -> person")
            old = cfg.get("people") if isinstance(cfg.get("people"), dict) else {}
            people: dict[str, Any] = {}
            for h, p in v.items():
                if not isinstance(p, dict):
                    raise HTTPException(400, f"people.{h} must be an object")
                prev = old.get(h) if isinstance(old.get(h), dict) else {}
                person = dict(p)
                if _is_echo(person.get("webhook_url")):
                    if prev.get("webhook_url"):
                        person["webhook_url"] = prev["webhook_url"]
                    else:
                        person.pop("webhook_url", None)
                _check_webhook(person.get("webhook_url"), f"people.{h}.webhook_url")
                people[h] = person
            v = people
        out[k] = v
    return out


def write_slack(cfg: dict[str, Any]) -> None:
    p = slack_path()
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    secret_files.write_secret(tmp, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, p)


# ------------------------------------------------------------------------------------------ plane

def plane_view() -> dict[str, Any]:
    rows = [settings_api.row(settings.setting(k)) for k in PLANE_KEYS]
    return {"configured": bool(settings.get("EDP8_PLANE_URL")) and bool(settings.get("EDP8_PLANE_API_KEY")),
            "settings": rows}


def plane_test() -> tuple[bool, str]:
    base = (settings.get("EDP8_PLANE_URL") or "").rstrip("/")
    if not base or not settings.get("EDP8_PLANE_API_KEY"):
        return False, "Plane is not configured (plane.url and plane.api_key)"
    ws, proj = settings.get("EDP8_PLANE_WORKSPACE"), settings.get("EDP8_PLANE_PROJECT")
    try:
        with net.client() as c:
            r = c.get(f"{base}/api/v1/workspaces/{ws}/projects/{proj}/",
                      headers={"X-API-Key": str(settings.get("EDP8_PLANE_API_KEY"))})
    except httpx.HTTPError as e:
        return False, f"could not reach Plane: {e}"
    if r.status_code == 200:
        name = (r.json() or {}).get("name") if r.headers.get("content-type", "").startswith("application/json") else None
        return True, f"Plane project reachable{f' ({name})' if name else ''}"
    return False, f"Plane answered HTTP {r.status_code} for workspace {ws!r} project {proj!r}"


# ------------------------------------------------------------------------------------------ router

def router(ctx: AdminContext, admin_actor) -> APIRouter:
    r = APIRouter()

    def _vscode(request: Request) -> dict[str, Any]:
        base = board_url(request)
        repo = settings.get("EDP_UPDATE_REPO")
        humans = sorted(p.handle.lstrip("@") for p in ctx.board.store.query("participant", {}) if p.type == "human")
        return {"extension_id": VSCODE_EXTENSION_ID, "vsix_url": f"https://github.com/{repo}/releases/latest",
                "board_url": base,
                "signin_links": {h: f"vscode://{VSCODE_EXTENSION_ID}/signin?" + urlencode({"board": base, "handle": h})
                                 for h in humans}}

    @r.get("/v1/admin/integrations")
    def integrations(request: Request, a: Participant = Depends(admin_actor)):
        from ..api_code import code_status
        return {"ok": True, "value": {"slack": slack_view(read_slack()), "plane": plane_view(),
                                      "code_server": code_status(), "vscode": _vscode(request)}, "hint": ""}

    @r.get("/v1/admin/integrations/slack")
    def slack_get(a: Participant = Depends(admin_actor)):
        return {"ok": True, "value": slack_view(read_slack()), "hint": ""}

    @r.put("/v1/admin/integrations/slack")
    def slack_put(b: SlackPut, a: Participant = Depends(admin_actor)):
        cfg = merge_slack(read_slack(), b.values)
        write_slack(cfg)
        return {"ok": True, "value": slack_view(cfg), "hint": "restart the Slack bridge to apply"}

    @r.post("/v1/admin/integrations/slack/test")
    def slack_test(b: SlackTestIn | None = None, a: Participant = Depends(admin_actor)):
        from .. import slack_bridge
        cfg = read_slack()
        person: dict[str, Any] = {}
        who = "the default webhook"
        if b and b.handle:
            eff = slack_view(cfg)["people_effective"]
            if b.handle not in eff:
                raise HTTPException(404, f"{b.handle!r} has no Slack destination (map or person settings)")
            from ..user_settings import bridge_people
            static = cfg.get("people") if isinstance(cfg.get("people"), dict) else {}
            person = bridge_people().get(b.handle) or dict(static.get(b.handle) or {})
            who = b.handle
        elif not cfg.get("webhook_url"):
            raise HTTPException(409, "no default webhook_url in slack_map.json to test")
        text = f"Heronry admin test ping from {a.handle.lstrip('@')}: Slack alerts reach {who}."
        if not slack_bridge._post(cfg, person, text):
            raise HTTPException(502, "Slack did not accept the test ping (check the webhook/bot token)")
        return {"ok": True, "value": {"sent": True, "to": who}, "hint": ""}

    @r.get("/v1/admin/integrations/plane")
    def plane_get(a: Participant = Depends(admin_actor)):
        return {"ok": True, "value": plane_view(), "hint": ""}

    @r.put("/v1/admin/integrations/plane")
    def plane_put(b: PlanePut, a: Participant = Depends(admin_actor)):
        allowed = {k for k in PLANE_KEYS} | {settings.setting(k).key for k in PLANE_KEYS}
        extra = sorted(set(b.values) - allowed)
        if extra:
            raise HTTPException(400, f"not Plane settings: {', '.join(extra)}")
        out = settings_api.apply(b.values)
        return {"ok": True, "value": {**plane_view(), "restart_required": out["restart_required"]},
                "hint": "restart the board to apply"}

    @r.post("/v1/admin/integrations/plane/test")
    def plane_check(a: Participant = Depends(admin_actor)):
        ok, msg = plane_test()
        if not ok:
            raise HTTPException(502 if "answered" in msg or "reach" in msg else 409, msg)
        return {"ok": True, "value": {"ok": True, "message": msg}, "hint": ""}

    @r.get("/v1/admin/integrations/code-server")
    def code_get(a: Participant = Depends(admin_actor)):
        from ..api_code import code_status
        return {"ok": True, "value": code_status(), "hint": ""}

    @r.post("/v1/admin/integrations/code-server/test")
    def code_test(a: Participant = Depends(admin_actor)):
        from ..api_code import code_status
        st = code_status()
        if not st["running"]:
            raise HTTPException(502, f"code-server does not answer on 127.0.0.1:{st['port']} "
                                     f"(start it with {st['start_command']})")
        return {"ok": True, "value": st, "hint": ""}

    @r.get("/v1/admin/integrations/vscode")
    def vscode_get(request: Request, a: Participant = Depends(admin_actor)):
        return {"ok": True, "value": _vscode(request), "hint": ""}

    @r.post("/v1/admin/integrations/vscode/test")
    def vscode_test(request: Request, a: Participant = Depends(admin_actor)):
        """The board URL the extension will be given answers /v1/health from here."""
        base = board_url(request)
        try:
            with net.client(timeout=10.0) as c:
                h = c.get(f"{base}/v1/health")
            ok = h.status_code == 200
        except httpx.HTTPError as e:
            raise HTTPException(502, f"{base} is not reachable from the board: {e}") from None
        if not ok:
            raise HTTPException(502, f"{base}/v1/health answered HTTP {h.status_code}")
        return {"ok": True, "value": {"board_url": base, "health": h.json()}, "hint": ""}

    return r
