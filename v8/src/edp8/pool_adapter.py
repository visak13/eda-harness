"""edp8 pool adapter — spawn/resume/park/reap shells via the edp-pool service.

Contract with edp-pool (unchanged service): `POST /v1/spawn {role, handle,
parent_session?, model?}`; the pool activates the shell with `/<role>` and
sets EDP_ROLE=<role>, EDP_HANDLE=<handle>. v8 uses the PARTICIPANT ID as the
handle, so the spawned shell's MCP resolves its identity from EDP_HANDLE.
The pool process itself is started with EDP_AGENT_HOME=<v8 dir> and
EDP8_BOARD_URL so every shell inherits the board address.

Sessions are mirrored into the board (`PUT /v1/sessions/{id}`, admin) by
`sync_sessions()` so `context()`/feeds can see liveness without asking the pool.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .schemas import SessionState

POOL_URL = os.environ.get("EDP_POOL_URL", "http://127.0.0.1:9301")
POOL_ID = os.environ.get("EDP8_POOL_ID", "local")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _envelope(ok: bool, value: Any = None, error: str = "", hint: str = "", code: str = "pool") -> dict[str, Any]:
    return ({"ok": True, "value": value, "hint": hint} if ok
            else {"ok": False, "error": {"code": code, "message": error}, "hint": hint})


def _post(path: str, body: dict[str, Any] | None = None, timeout: float = 90.0) -> dict[str, Any]:
    try:
        r = httpx.post(f"{_env('EDP_POOL_URL', POOL_URL)}{path}", json=body or {}, timeout=timeout)
    except httpx.HTTPError as e:
        return _envelope(False, error=f"pool unreachable: {e}", hint="start the pool (edp-pool) and retry",
                         code="unavailable")
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text}
    if r.status_code >= 400 or (isinstance(data, dict) and data.get("refused")):
        return _envelope(False, error=str(data), code="pool")
    return _envelope(True, value=data)


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        r = httpx.get(f"{_env('EDP_POOL_URL', POOL_URL)}{path}", params=params, timeout=20.0)
    except httpx.HTTPError as e:
        return _envelope(False, error=f"pool unreachable: {e}", code="unavailable")
    return _envelope(r.status_code < 400, value=r.json() if r.content else None, error=r.text)


# ----------------------------------------------------------------------------- verbs


def spawn(role: str, participant_id: str, *, parent_session: str | None = None, model: str | None = None,
          mode: str | None = None) -> dict[str, Any]:
    """Spawn a shell for `participant_id` running `/<role>`. Returns {session_id}."""
    body: dict[str, Any] = {"role": role, "handle": participant_id}
    if parent_session:
        body["parent_session"] = parent_session
    if model:
        body["model"] = model
    if mode:
        body["mode"] = mode
    out = _post("/v1/spawn", body)
    if out["ok"]:
        out["hint"] = f"shell for {participant_id} is starting; it boots with whoami → subscribe → context"
    return out


def resume(participant_id: str) -> dict[str, Any]:
    """Fork-resume the parked shell of a participant (same session, same context)."""
    return _post(f"/v1/resume/{participant_id}")


def park(participant_id: str) -> dict[str, Any]:
    """Park a participant's shell (preserves its session for a later resume)."""
    return _post(f"/v1/park/{participant_id}")


def reap(participant_id: str) -> dict[str, Any]:
    """Force-close a participant's shell. A reasoned act, never automatic."""
    return _post(f"/v1/reap/{participant_id}")


def release_self(participant_id: str, reason: str) -> dict[str, Any]:
    """Synchronous self-close: the shell asserts it is finished and the pool releases its
    session immediately with `reason` as the honest dead_reason (owner ruling 2026-09-06:
    no idle inference, ever — a shell decides when it closes). The pool kills the process
    tree, so the cron/monitor die with it. Idempotent: no active session == already closed."""
    got = sessions()
    if not got["ok"]:
        return got
    rows = got["value"] if isinstance(got["value"], list) else got["value"].get("sessions", [])
    sid = next((s.get("session_id") for s in rows
                if s.get("handle") == participant_id and s.get("state") in ("active", "alive", "starting")), None)
    if not sid:
        return _envelope(True, value={"closed": True, "session_id": None, "reason": "already closed"},
                         hint="no active session for you in the pool; nothing to do — stop calling tools")
    out = _post(f"/v1/release/{sid}", {"reason": reason})
    if out["ok"]:
        out["value"] = {"closed": True, "session_id": sid, "reason": reason}
        out["hint"] = "closed: the pool is ending this shell now — stop calling tools and end the turn"
    return out


def sessions() -> dict[str, Any]:
    """All pool sessions: [{session_id, role, handle, parent, state}]."""
    return _get("/v1/sessions")


def liveness(participant_id: str) -> dict[str, Any]:
    """{state: alive|dead|unknown, last_output_ts} for a participant's shell."""
    return _get(f"/v1/liveness/{participant_id}")


def capacity() -> dict[str, Any]:
    """Pool limits (per-role caps) as the pool reports them."""
    return _get("/v1/limits")


# ----------------------------------------------------------------------------- mirror into the board

_STATE_MAP = {"alive": SessionState.alive, "dead": SessionState.dead, "parked": SessionState.parked,
              "stalled": SessionState.stalled}


def sync_sessions(board_url: str | None = None, admin_token: str | None = None) -> dict[str, Any]:
    """Mirror pool sessions into the board's session objects (admin)."""
    board_url = board_url or _env("EDP8_BOARD_URL", "http://127.0.0.1:9400")
    admin_token = admin_token or _env("EDP8_ADMIN_TOKEN", "dev")
    got = sessions()
    if not got["ok"]:
        return got
    rows = got["value"] if isinstance(got["value"], list) else got["value"].get("sessions", [])
    n = 0
    failed: list[str] = []
    for s in rows:
        handle = s.get("handle")
        if not handle:
            continue
        live = liveness(handle)
        # unknown/legacy pool states (done, released, …) map to DEAD: "your answer is saved
        # for the next shell" is the safe claim; "this wakes it" must never be a lie
        state = _STATE_MAP.get((live.get("value") or {}).get("state", s.get("state", "dead")), SessionState.dead)
        reason = s.get("dead_reason") or ""
        if state == SessionState.dead and not reason:
            # the list snapshot can predate the close: a shell that released itself between the
            # list and the liveness call would otherwise be mirrored as "no reason recorded"
            fresh = sessions()
            if fresh["ok"]:
                frows = fresh["value"] if isinstance(fresh["value"], list) else fresh["value"].get("sessions", [])
                reason = next((r.get("dead_reason") or "" for r in frows
                               if r.get("session_id") == s.get("session_id")), "")
        try:
            ticket_id = handle.split(".", 1)[1] if "." in handle else None
            httpx.put(f"{board_url}/v1/sessions/{s.get('session_id')}",
                      json={"participant_id": handle, "ticket_id": ticket_id, "pool_id": POOL_ID,
                            "state": state.value, "reason": reason},
                      headers={"X-Admin": admin_token}, timeout=10.0)
            n += 1
        except httpx.HTTPError as e:
            failed.append(f"{handle}: {e}")
    return _envelope(True, value={"mirrored": n, "failed": failed},
                     hint="" if not failed else "some sessions could not be mirrored; see failed")
