"""S23 routes behind the framework tools that replaced shell workarounds (report-e517e9e87e coverage gaps):

- `/v1/pains` — query, read, file and resolve over the board's pain records (edp8.pains; e0cec S6: one store,
  the jsonl files are imported); any seat files and reads; resolve is the owner's, the doctor's, an admin's,
  or an epic's architect for `fixed` with a commit reachable from main.
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
    by: str = Field(default="", max_length=200)  # legacy: a commit sha, read as `commit` when that is empty
    commit: str = Field(default="", max_length=64)
    ticket_id: str = Field(default="", max_length=64)
    dup_of: str = Field(default="", max_length=64)
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

    def _synced() -> None:
        pains.sync(board)  # the repo + installed jsonl stores, mtime-gated; a no-op once imported

    @r.get("/v1/pains")
    def pain_query(status: str | None = "open", area: str | None = None, q: str | None = None,
                   a: Participant = Depends(actor)):
        _synced()
        rows = _pain_call(lambda: pains.query(board.store, status=status, area=area, q=q))
        return _ok(rows, "pain(action='read', id=...) for one record with its resolution and duplicates")

    @r.get("/v1/pains/{pain_id}")
    def pain_read(pain_id: str, a: Participant = Depends(actor)):
        _synced()
        return _ok(_pain_call(lambda: pains.read(board.store, pain_id)))

    @r.post("/v1/pains")
    def pain_file(b: PainIn, a: Participant = Depends(actor)):
        _synced()
        rec = _pain_call(lambda: pains.file(board.store, b.model_dump(), role=_role(a), handle=a.handle))
        return _ok(rec, "filed; query first next time (pain action=query, q=<words>) and pass dup_of for a repeat")

    @r.post("/v1/pains/{pain_id}/resolve")
    def pain_resolve(pain_id: str, b: PainResolveIn, a: Participant = Depends(actor)):
        _synced()
        try:
            has_epic = bool(board.my_epics(a)) if _role(a) == Role.architect.value else False
        except BoardError:
            has_epic = False
        out = _pain_call(lambda: pains.resolve(
            board.store, pain_id, b.status, who=a.handle, role=_role(a), admin=is_admin(a), has_epic=has_epic,
            commit=b.commit or b.by, ticket_id=b.ticket_id, dup_of=b.dup_of, note=b.note))
        return _ok(out, "the board records who resolved it and the commit, ticket or original it names")

    @r.post("/v1/pains/import")
    def pain_import(a: Participant = Depends(actor)):
        if _role(a) not in (Role.owner.value, Role.architect.value, Role.doctor.value) and not is_admin(a):
            raise BoardError("forbidden", f"role {_role(a)!r} may not re-import the pain files",
                             "the owner, an architect, the doctor or an admin runs it")
        return _ok(pains.sync(board, force=True), "the jsonl stores are imported once per id; the board rows win")

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
        except hc.BadTime as e:
            raise BoardError("invalid", f"since/until: {e}", "an ISO-8601 time such as 2026-09-24T10:00:00Z, "
                                                           "or epoch seconds") from e
        except hc.NoLog as e:
            raise BoardError("not_found", str(e), "check the participant id (a seat with no transcript has no cost); "
                                                  "the board searches EDP8_HARVEST_LOG_ROOTS, else the Claude and "
                                                  "codex log roots named here") from e
        except hc.LogUnreadable as e:
            raise BoardError("unavailable", str(e), "the pool may be writing it; retry, or run "
                                                    "scripts/harvest_cost.py on the host") from e
        except LookupError as e:
            raise BoardError("not_found", str(e), "pass since (ISO) when the harvest trigger is not in the log") from e
        except Exception as e:  # a seat log is untrusted input: a malformed one is an error body, never a bare 500
            raise BoardError("internal", f"harvest_cost failed on {participant_id}'s log: {e.__class__.__name__}: {e}",
                             "pass since/until to narrow the window, or run scripts/harvest_cost.py on the host") from e
        return _ok(out)

    return r
