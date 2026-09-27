"""S23 routes behind the framework tools that replaced shell workarounds (report-e517e9e87e coverage gaps):

- `/v1/pains` — query, read, file and resolve over the append-only pain log (edp8.pains); any seat files
  and reads; resolve is the owner's, the doctor's or an admin's.
- `GET /v1/services/status` — read-only launcher view of the host services (run_state.snapshot) for the
  owner, the architect and the doctor. Mutating service control stays human (edp.ps1 / admin routes).
- `GET /v1/harvest/cost` — one seat's harvest token cost (edp8.harvest_cost) for qa and the owner.

Every reply is a bounded {ok, value, hint} envelope; nothing here returns a secret or a raw file.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from . import pains
from .admin import is_admin
from .board import Board, BoardError
from .schemas import Participant, Role


def _ok(value: Any, hint: str = "") -> dict[str, Any]:
    return {"ok": True, "value": value, "hint": hint}


class PainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: str
    area: str = Field(max_length=40)
    symptom: str = Field(max_length=2000)
    expected: str = Field(max_length=2000)
    evidence: str = Field(max_length=2000)
    workaround: str = Field(default="", max_length=2000)
    cost: str = Field(default="", max_length=400)
    dup_of: str | None = None
    supersedes: str | None = None


class PainResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    by: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=1000)


def _pain_call(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except pains.PainError as e:
        raise BoardError(e.code, str(e), e.hint) from None


def _role(a: Participant) -> str:
    return a.role.value if hasattr(a.role, "value") else str(a.role)


def tools_router(board: Board, actor: Callable[..., Participant]) -> APIRouter:
    r = APIRouter()

    @r.get("/v1/pains")
    def pain_query(status: str | None = "open", area: str | None = None, q: str | None = None,
                   a: Participant = Depends(actor)):
        rows = _pain_call(lambda: pains.query(status=status, area=area, q=q))
        return _ok(rows, "pain(action='read', id=...) for one record with its resolution and duplicates")

    @r.get("/v1/pains/{pain_id}")
    def pain_read(pain_id: str, a: Participant = Depends(actor)):
        return _ok(_pain_call(lambda: pains.read(pain_id)))

    @r.post("/v1/pains")
    def pain_file(b: PainIn, a: Participant = Depends(actor)):
        rec = _pain_call(lambda: pains.file(b.model_dump(), role=_role(a), handle=a.handle))
        return _ok(rec, "filed; query first next time (pain action=query, q=<words>) and pass dup_of for a repeat")

    @r.post("/v1/pains/{pain_id}/resolve")
    def pain_resolve(pain_id: str, b: PainResolveIn, a: Participant = Depends(actor)):
        if _role(a) not in (Role.owner.value, Role.doctor.value) and not is_admin(a):
            raise BoardError("forbidden", f"role {_role(a)!r} may not resolve pain records",
                             "the owner, the doctor or an admin resolves; file a fix note on your ticket instead")
        return _ok(_pain_call(lambda: pains.resolve(pain_id, b.status, by=b.by or a.handle, note=b.note)))

    @r.get("/v1/services/status")
    def services_status(a: Participant = Depends(actor)):
        if _role(a) not in (Role.owner.value, Role.architect.value, Role.doctor.value) and not is_admin(a):
            raise BoardError("forbidden", f"role {_role(a)!r} may not read service status",
                             "owner, architect and doctor read it; start/stop/restart is a human action (edp.ps1)")
        from . import run_state
        keep = ("service", "state", "pid", "port", "git_rev", "uptime", "version", "last_probe", "note")
        rows = [{k: row.get(k) for k in keep if row.get(k) not in (None, "")} for row in run_state.snapshot()]
        return _ok(rows, "read-only; a down service is a human restart (.\\edp.ps1 restart <svc>): "
                         "record_status(status=blocked) and ask the owner (kind=question) with this evidence; "
                         "never restart it from a seat")

    @r.get("/v1/harvest/cost")
    def harvest_cost(participant_id: str, since: str | None = None, until: str | None = None,
                     a: Participant = Depends(actor)):
        if _role(a) not in (Role.owner.value, Role.qa.value) and not is_admin(a):
            raise BoardError("forbidden", f"role {_role(a)!r} may not read harvest cost", "qa and the owner read it")
        from . import harvest_cost as hc
        from .library import knowledge_view
        try:
            out = hc.compute(participant_id, since=since, until=until, knowledge=knowledge_view(board))
        except LookupError as e:
            raise BoardError("not_found", str(e), "pass since (ISO) when the harvest trigger is not in the log")
        return _ok(out)

    return r
