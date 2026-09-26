"""Admin → Services → Capacity (design-e963c656f5 §4.14(d); S6 s-e6b4fa59d5): the pool's shell caps and
live usage in one read, and writes that go through the pool's `/v1/limits` (applied without a restart,
persisted in the pool's registry, so they survive a pool restart).

Caps: the total-shells throughput cap, the hard live-shells ceiling, one cap per capacity class (builder =
the pool's `max_workers`, planner = `max_planners`; checker is exempt from class caps by design and counts
toward the total only) and a per-role cap for every role of every workflow a running epic pins. A per-role
override wins over the workflow role's declared `max_concurrent`; clearing it (null) falls back to that.
Every value is clamped to >= 1 by the pool: a 0 cap would deadlock dispatch, it is not a pause.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import pool_adapter
from ..schemas import Participant, TicketKind, TicketStatus
from .context import AdminContext

#: capacity class → the pool's limit key
CLASS_KEYS = {"builder": "max_workers", "planner": "max_planners"}
_ENDED = {TicketStatus.done.value, TicketStatus.dropped.value, TicketStatus.partial.value}


class CapacityIn(BaseModel):
    max_total_shells: int | None = None
    max_live_shells: int | None = None
    classes: dict[str, int | None] | None = None     # builder / planner
    role_caps: dict[str, int | None] | None = None   # role id → cap; null clears the override
    clear: list[str] | None = None                   # top-level keys to reset to env/default


def pinned_roles(ctx: AdminContext) -> list[dict[str, Any]]:
    """The spawnable roles of every workflow a running (not ended) epic pins, with their class and
    declared max_concurrent. A role pinned by several versions lists each distinct declaration."""
    board = ctx.board
    seen: dict[tuple[str, str | None, int | None], dict[str, Any]] = {}
    for epic in board.tickets(kind=TicketKind.epic.value):
        if str(getattr(epic.status, "value", epic.status)) in _ENDED:
            continue
        wf = board.workflow_of(epic)
        for rid in sorted(wf.spawnable):
            cap = wf.capacity(rid)
            key = (rid, cap["capacity_class"], cap["max_concurrent"])
            row = seen.setdefault(key, {"role": rid, "capacity_class": cap["capacity_class"],
                                        "declared_max": cap["max_concurrent"], "workflows": [], "epics": 0})
            if wf.ref not in row["workflows"]:
                row["workflows"].append(wf.ref)
            row["epics"] += 1
    return sorted(seen.values(), key=lambda r: (r["role"], r["workflows"]))


def _pool_limits(usage: bool = True) -> dict[str, Any]:
    out = pool_adapter._get("/v1/limits", {"usage": "1"} if usage else None)
    if not out["ok"]:
        raise HTTPException(503, f"the pool did not answer its limits ({out.get('error')}); "
                                 "is it running? (Admin → Services)")
    return out["value"] or {}


def view(ctx: AdminContext) -> dict[str, Any]:
    lim = _pool_limits()
    usage = lim.get("usage") or {}
    overrides = lim.get("overrides") or {}
    classes = [{"class": c, "cap": lim.get(k), "overridden": k in overrides, "in_use": (usage.get("classes") or {}).get(c, 0)}
               for c, k in CLASS_KEYS.items()]
    classes.append({"class": "checker", "cap": None, "overridden": False, "exempt": True,
                    "in_use": (usage.get("classes") or {}).get("checker", 0)})
    role_over = lim.get("role_caps") or {}
    roles = []
    for r in pinned_roles(ctx):
        rid = r["role"]
        eff = role_over.get(rid, r["declared_max"])
        roles.append({**r, "cap": eff, "overridden": rid in role_over,
                      "in_use": (usage.get("roles") or {}).get(rid, 0)})
    return {
        "total": {"cap": lim.get("max_total_shells"), "overridden": "max_total_shells" in overrides,
                  "in_use": usage.get("total", 0)},
        "live": {"cap": lim.get("max_live_shells"), "overridden": "max_live_shells" in overrides,
                 "in_use": usage.get("live", 0)},
        "classes": classes,
        "roles": roles,
        "note": "Every cap is at least 1: a 0 cap would deadlock dispatch, it does not pause. "
                "Pausing is its own control. Checkers (qa, adversary) are exempt from class caps and "
                "count toward the total only.",
    }


def router(ctx: AdminContext, admin_actor) -> APIRouter:
    r = APIRouter()

    @r.get("/v1/admin/capacity")
    def capacity_get(a: Participant = Depends(admin_actor)):
        return {"ok": True, "value": view(ctx), "hint": ""}

    @r.put("/v1/admin/capacity")
    def capacity_put(b: CapacityIn, a: Participant = Depends(admin_actor)):
        body: dict[str, Any] = {}
        for k in ("max_total_shells", "max_live_shells"):
            v = getattr(b, k)
            if v is not None:
                body[k] = max(1, int(v))
        for cls, v in (b.classes or {}).items():
            if cls not in CLASS_KEYS:
                raise HTTPException(422, f"no capacity class {cls!r} with a cap (builder, planner; "
                                         "checker is exempt from class caps)")
            body[CLASS_KEYS[cls]] = None if v is None else max(1, int(v))
        for k in b.clear or []:
            key = CLASS_KEYS.get(k, k)
            if key not in ("max_total_shells", "max_live_shells", *CLASS_KEYS.values()):
                raise HTTPException(422, f"cannot clear {k!r}")
            body[key] = None
        if b.role_caps:
            body["role_caps"] = {role: None if v is None else max(1, int(v)) for role, v in b.role_caps.items()}
        if not body:
            raise HTTPException(422, "nothing to change")
        out = pool_adapter._post("/v1/limits", body, timeout=20.0)
        if not out["ok"]:
            raise HTTPException(503, f"the pool refused or did not answer ({out.get('error')})")
        return {"ok": True, "value": view(ctx), "hint": "applied by the pool now; no restart needed"}

    return r
