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
from pathlib import Path
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


def reachable(timeout: float = 2.0) -> bool:
    """Fast liveness probe (design §22 rule 4: spawn/resume must refuse within 2s when the pool
    does not answer, instead of hanging on the 90s spawn timeout). GET /v1/limits is cheap."""
    try:
        r = httpx.get(f"{_env('EDP_POOL_URL', POOL_URL)}/v1/limits", timeout=timeout)
        return r.status_code < 500
    except httpx.HTTPError:
        return False


# ----------------------------------------------------------------------------- verbs


def foreign_board_reason() -> str | None:
    """Why THIS process must not spawn shells on the pool, or None when it is the fleet board.

    The pool serves exactly one agent home (EDP_POOL_AGENT_HOME, exported to every seat). A board
    whose EDP8_HOME is anywhere else — an e2e board in a temp dir, a private test instance, a seat's
    experiment — is a foreign board: its epics do not exist on the fleet board, so any seat it
    spawned would boot into nothing and burn a live shell (2026-09-08: qa.epic-2b3bea99e0). The
    gate sits here, the one choke point every spawn path (service tool, S22 pairing) goes through."""
    agent_home = os.environ.get("EDP_POOL_AGENT_HOME") or os.environ.get("EDP_AGENT_HOME")
    home = os.environ.get("EDP8_HOME")
    if not agent_home or not home:
        return None
    try:
        same = Path(home).resolve() == Path(agent_home).resolve()
    except OSError:
        same = False
    if same:
        return None
    return (f"this board's EDP8_HOME ({home}) is not the pool's agent home ({agent_home}): a test or "
            "private board never spawns shells on the fleet pool")


def spawn(role: str, participant_id: str, *, parent_session: str | None = None, model: str | None = None,
          mode: str | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Spawn a shell for `participant_id` running `/<role>`. Returns {session_id}.

    `env` is extra environment for the shell (the pool records it as spawn_settings and
    injects it); S20 passes the per-seat `EDP8_TOKEN` here so the shell authenticates.
    Refused with code `foreign_board` when this process is not the fleet board (see
    foreign_board_reason)."""
    why = foreign_board_reason()
    if why:
        return _envelope(False, error=why, code="foreign_board",
                         hint="run the fleet board from the pool's agent home, or use a stub pool adapter in tests")
    body: dict[str, Any] = {"role": role, "handle": participant_id}
    if parent_session:
        body["parent_session"] = parent_session
    if model:
        body["model"] = model
    if mode:
        body["mode"] = mode
    if env:
        body["env"] = env
    out = _post("/v1/spawn", body)
    if out["ok"]:
        out["hint"] = f"shell for {participant_id} is starting; it boots with whoami → subscribe → context"
    return out


def resume(participant_id: str) -> dict[str, Any]:
    """Fork-resume the parked shell of a participant (same session, same context)."""
    return _post(f"/v1/resume/{participant_id}")


def resume_closed(participant_id: str) -> dict[str, Any]:
    """Fork-resume a CLOSED (done) shell from its stored claude_session_id with the
    role/cwd/env/settings recorded at spawn (spawn_settings). The pool re-takes the handle
    lock and returns the new session. Design §18.3 (owner m-6ffe756cf7)."""
    return _post(f"/v1/resume_closed/{participant_id}")


def close(participant_id: str, reason: str) -> dict[str, Any]:
    """Gracefully close a named participant's active shell with `reason` (distinct from
    reap, which force-kills). Idempotent: no active session == already closed."""
    got = sessions()
    if not got["ok"]:
        return got
    rows = got["value"] if isinstance(got["value"], list) else got["value"].get("sessions", [])
    sid = next((s.get("session_id") for s in rows
                if s.get("handle") == participant_id and s.get("state") in ("active", "alive", "starting", "parked")),
               None)
    if not sid:
        return _envelope(True, value={"closed": True, "session_id": None, "reason": "already closed"},
                         hint="no active session for that participant; nothing to do")
    out = _post(f"/v1/release/{sid}", {"reason": reason})
    if out["ok"]:
        out["value"] = {"closed": True, "session_id": sid, "reason": reason}
    return out


def capabilities() -> dict[str, Any]:
    """What the pool supports: {resume_parked, resume_closed, park, spawn} booleans as the
    pool reports them (GET /v1/pool/capabilities). Never hard-coded by the board."""
    return _get("/v1/pool/capabilities")


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
# pool row states in which a shell is still LIVE and worth a liveness probe (design §18.3).
# done/released/reaped are TERMINAL and carry their own dead_reason — never re-probed.
_LIVE_POOL_STATES = ("active", "starting", "parked", "resuming")
# a live pool row we could not freshly probe falls back to the pool's own row state, mapped —
# never to dead (that was the false-death bug). active/starting → alive, parked → parked.
_POOL_STATE_MAP = {"active": SessionState.alive, "starting": SessionState.alive,
                   "parked": SessionState.parked, "resuming": SessionState.alive,
                   "stalled": SessionState.stalled}


def _liveness_via(client: httpx.Client, handle: str) -> dict[str, Any]:
    """One liveness GET on a SHARED keep-alive client (no fresh socket per row). Returns
    {answered: bool, state: str|None, reason: str}. A transport error / 4xx / missing or
    'unknown' state is a NON-ANSWER (answered may be True but state None)."""
    try:
        r = client.get(f"{_env('EDP_POOL_URL', POOL_URL)}/v1/liveness/{handle}")
    except httpx.HTTPError as e:
        return {"answered": False, "state": None, "reason": str(e)}
    if r.status_code >= 400:
        return {"answered": False, "state": None, "reason": r.text}
    data = r.json() if r.content else {}
    st = data.get("state")
    return {"answered": st not in (None, "unknown"), "state": st,
            "reason": data.get("dead_reason") or data.get("reason") or ""}


def sync_sessions(board_url: str | None = None, admin_token: str | None = None) -> dict[str, Any]:
    """Mirror pool sessions into the board's session objects (admin). Design §18.3 / criterion
    c-1a82925acb — no false deaths, no port flood:

    (a) liveness is polled ONLY for rows the pool reports live (active/parked/resuming/starting);
        terminal rows (done/released/reaped) are mirrored dead WITH their own dead_reason, never
        re-probed;
    (b) one keep-alive httpx.Client carries the whole sweep — the single session list, every
        liveness GET and every board PUT — so nothing opens a fresh socket per row;
    (c) the pool's 'active' maps to alive; a failed/timed-out/'unknown' liveness answer for a
        live row KEEPS the board's previous state and stamps presence_stale_since, emitting no
        event (silence is never rendered as Closed);
    (d) a shell_dead/crashed event is emitted by the board only on a positive 'dead' answer
        carrying the pool's dead_reason (or the pool's own crash sweep, elsewhere)."""
    board_url = board_url or _env("EDP8_BOARD_URL", "http://127.0.0.1:9400")
    admin_token = admin_token or _env("EDP8_ADMIN_TOKEN", "dev")
    got = sessions()  # exactly ONE session list for the whole sweep — never re-listed per row
    if not got["ok"]:
        return got
    rows = got["value"] if isinstance(got["value"], list) else got["value"].get("sessions", [])
    n = 0
    stale = 0
    failed: list[str] = []
    with httpx.Client(timeout=10.0) as client:
        for s in rows:
            handle = s.get("handle")
            if not handle:
                continue
            sid = s.get("session_id")
            pool_state = s.get("state")
            ticket_id = handle.split(".", 1)[1] if "." in handle else None
            body: dict[str, Any] = {"participant_id": handle, "ticket_id": ticket_id, "pool_id": POOL_ID}
            if pool_state in _LIVE_POOL_STATES:
                ans = _liveness_via(client, handle)
                if not ans["answered"]:
                    # (c) non-answer: keep the board's previous state, stamp staleness, no event.
                    body["state"] = _POOL_STATE_MAP.get(pool_state, SessionState.alive).value
                    body["presence_stale"] = True
                    stale += 1
                elif ans["state"] == "dead":
                    body["state"] = SessionState.dead.value
                    body["reason"] = ans["reason"] or s.get("dead_reason") or ""
                else:
                    body["state"] = _STATE_MAP.get(ans["state"], SessionState.alive).value
            else:
                # (a) terminal pool row: mirror dead with its recorded reason (a positive close),
                # not a probe. session_upsert only emits on a state TRANSITION, so a long-dead
                # row re-mirrored every sweep raises no new event.
                body["state"] = SessionState.dead.value
                body["reason"] = s.get("dead_reason") or "closed (no reason recorded)"
            try:
                client.put(f"{board_url}/v1/sessions/{sid}", json=body, headers={"X-Admin": admin_token})
                n += 1
            except httpx.HTTPError as e:
                failed.append(f"{handle}: {e}")
    return _envelope(True, value={"mirrored": n, "stale": stale, "failed": failed},
                     hint="" if not failed else "some sessions could not be mirrored; see failed")
