"""HttpPool — PoolPort over the real edp-pool (component #4).

The consumer owns its port impl (like HttpBroker). edp-claude does NOT
depend on the edp-pool package — it implements edp_claude.ports.PoolPort
directly. Upstream errors (e.g. pool_capacity_exceeded) are re-wrapped
verbatim via Tool.from_upstream — the LLM acts on them, nothing digests.
"""

import uuid

import httpx
from edp_contracts import Tool
from pydantic import BaseModel

from ..ports import PoolPort, ToolResult

# C2 (DESIGN-v6 s18): the fast liveness/poll path must NOT ride the shared 30s
# httpx client — a hung pool would then stall a whole reconcile tick for 30s.
# Give it a dedicated short timeout (bounded to the 2-5s window).
LIVENESS_TIMEOUT_S = 3.0


class _Spawned(BaseModel):
    handle: str
    session_id: str
    # W11: the claude session id PINNED in the /v1/spawn body, echoed back so
    # the caller never re-derives it (suspend_recipe's manifest and
    # resume_recipe's fork both need it). None when the spawn pinned none.
    claude_session_id: str | None = None


class _Released(BaseModel):
    released: str


class _Armed(BaseModel):
    """s26 item 1 — the pool's ack of a one-shot deferred reap. `armed=False`
    means the session was already gone/inactive (the shell closed itself
    first), which is the HEALTHY path, not an error."""
    session_id: str
    armed: bool
    reason: str = ""


class _Resumed(BaseModel):
    """DESIGN-v7 1.5.3 — the pool's POST /v1/resume/{handle} reply, passed
    through loosely (extra='allow'): `resumed=False` with `no_op=True` is the
    HEALTHY double-caller case (the watchdog got there first and the session
    is already resuming/active), not an error. The pool owns the full field
    set (reason/state/session_id/…); this client does not re-model it."""
    model_config = {"extra": "allow"}
    handle: str
    resumed: bool = False


class HttpPool(PoolPort):
    def __init__(self, base_url: str, client: httpx.AsyncClient):
        self.base = base_url.rstrip("/")
        self.client = client

    async def _spawn(self, role: str, handle: str, **extra) -> ToolResult:
        body = {"role": role, "handle": handle, **extra}
        r = await self.client.post(f"{self.base}/v1/spawn", json=body)
        if r.status_code // 100 == 2:
            # The response echoes whatever claude session the body pinned —
            # mechanical, no re-derivation. Absent key → None (worker spawns).
            return Tool.ok(_Spawned(
                handle=handle,
                session_id=r.json()["session_id"],
                claude_session_id=body.get("claude_session"),
            ))
        return Tool.from_upstream(r)  # capacity/route error, verbatim

    async def spawn_planner(
        self, recipe_id: str, step_id: str, model: str | None = None,
        resume_session: str | None = None,
    ) -> ToolResult:
        # W10a: optional per-spawn model tier, mirroring spawn_worker's idiom.
        # Omitted when None → that key stays off the /v1/spawn body.
        #
        # W11: ALWAYS pin a fresh claude session id. Without it the CLI
        # auto-generates one the pool never learns (build_session_args(None,
        # None) → []), so a suspended recipe has no planner session to fork.
        # The pinned id is returned to the caller via `claude_session_id`.
        #
        # `resume_session` (W11 fork-resume): paired with the fresh pin,
        # build_session_args emits `--resume <base> --session-id <fork>
        # --fork-session` — the resume path branches the suspended planner
        # rather than mutating it.
        claude_session = str(uuid.uuid4())
        extra = {"model": model} if model else {}
        if resume_session:
            extra["resume_session"] = resume_session
        return await self._spawn(
            "planner", f"{recipe_id}:{step_id}", parent_session=recipe_id,
            claude_session=claude_session, **extra,
        )

    async def spawn_worker(
        self, plan_id: str, action_id: str, model: str | None = None,
        role: str = "worker",
    ) -> ToolResult:
        # s17 FA3: forward an optional per-action model override as a spawn
        # extra. Omitted when None so the /v1/spawn body is byte-identical to
        # pre-FA3 (the pool then uses its default tier, Opus). Only the planner
        # stamps `model` on genuinely narrow worker actions.
        #
        # W11: deliberately NO claude_session pin. Workers are disposable —
        # reaped and re-dispatched fresh, never forked. Nothing to resume.
        #
        # s26 item 6b: `role` ("worker" | "reviewer") selects the pool's
        # activator + the EDP_ROLE it stamps. Default "worker" → the /v1/spawn
        # body is byte-identical to pre-s26.
        #
        # Dispatched as TWO LITERAL BRANCHES rather than `self._spawn(role, …)`.
        # `test_every_pool_spawned_role_has_a_toolset` reads the role strings
        # THIS FILE can send straight out of its source, so that every one of
        # them is proved to have a ROLE_TOOLSETS row — the guard against the
        # fail-open over-grant, where an unknown role makes build_mcp register
        # the FULL registry. A variable here would make the sendable roles
        # invisible to that check and silently blind it. Keep them literal.
        extra = {"model": model} if model else {}
        handle = f"{plan_id}:{action_id}"
        if role == "reviewer":
            return await self._spawn(
                "reviewer", handle, parent_session=plan_id, **extra)
        if role != "worker":
            # Unreachable via the tool (pool_spawn_worker's `role` is a Literal).
            # A wiring mistake must fail loudly, never silently downgrade.
            raise ValueError(f"unspawnable worker-leg role {role!r}")
        return await self._spawn(
            "worker", handle, parent_session=plan_id, **extra
        )

    async def close_when_idle(
        self, session_id: str, idle_secs: float, reason: str = "",
        park: bool = False,
    ) -> ToolResult:
        # s26 item 1. PUSH-ARMED, one-shot, per-session. The pool does not scan
        # and does not poll a store — it is told, by the shell whose action just
        # reached a terminal status, that this ONE session may be reaped once it
        # falls idle. See PoolService.arm_close_when_idle.
        #
        # DESIGN-v7 1.5.2: `park=True` makes the deferred act a PARK — this is
        # how a planner parks ITSELF (arm, end the turn, and the pool parks
        # the quiesced shell). The flag is omitted from the body when False so
        # a plain arm stays byte-identical to the pre-v7 request.
        body: dict = {"idle_secs": idle_secs, "reason": reason}
        if park:
            body["park"] = True
        r = await self.client.post(
            f"{self.base}/v1/close_when_idle/{session_id}", json=body,
        )
        if r.status_code // 100 == 2:
            return Tool.ok(_Armed(**r.json()))
        return Tool.from_upstream(r)

    # (spawn_goal_keeper / spawn_pattern_observer lived here — DELETED with
    # their roles, owner ruling 2026-08-04.)

    async def spawn_curiosity(
        self, parent_id: str, curiosity_id: str, model: str | None = None
    ) -> ToolResult:
        # v2.2: the curiosity neuron (per-decision interrogator).
        extra = {"model": model} if model else {}
        return await self._spawn(
            "curiosity", curiosity_id, parent_session=parent_id, **extra
        )

    async def spawn_specialist(
        self, parent_id: str, specialist_id: str,
        claude_session: str | None = None,
        mode: str = "headless",
        resume_session: str | None = None,
        model: str | None = None,
    ) -> ToolResult:
        # Vision phase 4: SME self-train shell. claude_session pins the
        # session id (phase 5) so the trained base is branchable.
        # mode="monitor" (v2.3) → visible console for interactive training.
        # resume_session (2026-05-24) → resume an existing base to UPDATE.
        extra = {"model": model} if model else {}
        return await self._spawn(
            "specialist", specialist_id, parent_session=parent_id,
            claude_session=claude_session, mode=mode,
            resume_session=resume_session, **extra,
        )

    async def spawn_reviewer(
        self, parent_id: str, handle: str, session_id: str,
        model: str | None = None,
    ) -> ToolResult:
        # 2026-06-02: a FRESH reviewer (no base fork). It loads the
        # specialist's COMPILED doc for its rubric, not the trained chat —
        # resume_session=None → build_session_args emits `--session-id <id>`.
        extra = {"model": model} if model else {}
        return await self._spawn(
            "reviewer", handle, parent_session=parent_id,
            claude_session=session_id, **extra,
        )

    # (spawn_consult — the W5 convened-consult spawn — was DELETED in the
    # 2026-08-12 dead-surface sweep with the consult shell role. Its only
    # caller was the deregistered ConveneConsult tool.)

    async def liveness(self, handle: str) -> dict:
        # W7: return {state, last_output_ts} — state is the pid/fingerprint
        # liveness ("alive"/"dead"/"unknown"); last_output_ts is the epoch
        # mtime of the shell's PTY-drain log (the busyness signal), or None
        # when the endpoint didn't report it (older pool, no drain log, or
        # session orphaned across a restart). `.get(...)` keeps this a
        # pass-through against a pool that predates the field.
        r = await self.client.get(
            f"{self.base}/v1/liveness/{handle}", timeout=LIVENESS_TIMEOUT_S
        )
        r.raise_for_status()
        body = r.json()
        return {
            "state": body["state"],
            "last_output_ts": body.get("last_output_ts"),
        }

    async def sessions(self, recipe_id: str | None = None) -> list[dict]:
        # GET-only inspection: the object-model `session`/`lock` readers.
        # W11: an optional `?recipe_id=` narrows the listing to one recipe's
        # shells (what suspend_recipe's manifest enumerates). Omitted when
        # None — the unfiltered request stays byte-identical to pre-W11.
        kw = {"params": {"recipe_id": recipe_id}} if recipe_id else {}
        r = await self.client.get(f"{self.base}/v1/sessions", **kw)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    async def locks(self) -> list[dict]:
        # GET /v1/locks — truthful held-lock list w/ per-lock liveness.
        r = await self.client.get(f"{self.base}/v1/locks")
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    async def release(self, session_id: str, park: bool = False) -> ToolResult:
        # DESIGN-v7 1.5.2: `{"park": true}` turns the close into an IMMEDIATE
        # park (pool-side park_session: watermark → state="parked" → flush →
        # kill; lock + resume token KEPT). No body when False — the legacy
        # close request stays byte-identical. A shell parking ITSELF should
        # use close_when_idle(park=True) instead (see ports.PoolPort.release).
        r = await self.client.post(
            f"{self.base}/v1/release/{session_id}",
            **({"json": {"park": True}} if park else {}),
        )
        if r.status_code // 100 == 2:
            return Tool.ok(_Released(released=session_id))
        return Tool.from_upstream(r)

    async def resume(self, handle: str) -> ToolResult:
        # DESIGN-v7 1.5.3: fork-resume a parked handle. The parked→resuming
        # CAS is the pool's; a second caller (watchdog + backstop racing) gets
        # a truthful no_op reply, never a double-spawn.
        r = await self.client.post(f"{self.base}/v1/resume/{handle}")
        if r.status_code // 100 == 2:
            return Tool.ok(_Resumed(**r.json()))
        return Tool.from_upstream(r)

    async def reap(self, handle: str) -> ToolResult:
        # 2026-05-25: deliberate lock-release/kill for a stuck worker.
        r = await self.client.post(f"{self.base}/v1/reap/{handle}")
        if r.status_code // 100 == 2:
            return Tool.ok(_Released(released=handle))
        return Tool.from_upstream(r)
