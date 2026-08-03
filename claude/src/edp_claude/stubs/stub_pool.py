"""In-process pool stub (LLD §3). Records spawn intents; no real shells."""

import uuid

from edp_contracts import Tool
from pydantic import BaseModel

from ..ports import PoolPort, ToolResult


class _Spawned(BaseModel):
    handle: str
    # W11: mirrors HttpPool's _Spawned — the pinned claude session id, echoed
    # back so a caller tested against this stub reads the same field it reads
    # in prod. None for spawns that pin nothing (worker).
    claude_session_id: str | None = None


class _Released(BaseModel):
    released: str


class _Armed(BaseModel):
    """s26 item 1 — mirrors HttpPool's _Armed so a caller tested against this
    stub reads the same fields it reads in prod."""
    session_id: str
    armed: bool
    reason: str = ""


class _Resumed(BaseModel):
    """DESIGN-v7 1.5.3 — mirrors HttpPool's _Resumed (loose pass-through of
    the pool's /v1/resume reply) so a caller tested against this stub reads
    the same fields it reads in prod."""
    model_config = {"extra": "allow"}
    handle: str
    resumed: bool = False


class StubPool(PoolPort):
    def __init__(self) -> None:
        self.spawns: list[dict] = []  # observable by tests
        # s26 item 1: every close_when_idle ARM, observable by tests. The stub
        # never reaps — it records the intent. The reap is the pool's.
        self.armed_closes: list[dict] = []
        # DESIGN-v7 1.5.3: every resume(handle) call, observable by tests. The
        # stub forks nothing — it records the intent; the CAS is the pool's.
        self.resumes: list[str] = []
        # DESIGN-v7 1.5.2: handles a test marked PARKED (mark_parked) so
        # liveness() can answer the third state and the tool layer's
        # parked-is-owned handling is assertable in-process.
        self._parked: set[str] = set()
        self._dead: set[str] = set()  # handles marked dead (crash sim)
        # W7: simulated PTY-drain-log mtime per handle (the busyness
        # signal). Mirrors the real pool deriving last_output_ts from a
        # log file's st_mtime; None (absent) until a test sets it.
        self._output_ts: dict[str, float] = {}
        # W11: the last `recipe_id` filter sessions() was called with (None
        # when unfiltered). Recorded, NOT applied — which rows a filtered
        # listing returns is edp-pool's semantics to define, and this stub
        # will not invent them. Assert the FORWARDING here; assert the
        # filtering against the real pool.
        self.last_sessions_filter: str | None = None

    def mark_dead(self, handle: str) -> None:
        """Test helper: simulate a crashed/killed child shell so
        liveness(handle) returns state 'dead'."""
        self._dead.add(handle)

    def mark_parked(self, handle: str) -> None:
        """Test helper (DESIGN-v7 1.5.2): simulate a PARKED shell so
        liveness(handle) returns the third state 'parked' — neither alive
        nor dead. A parked handle still OWNS its lock/step; the tool layer
        must treat it as owned (never re-dispatch, never crash-recover)."""
        self._parked.add(handle)
        self._dead.discard(handle)

    def _record(self, row: dict) -> None:
        """Record a spawn intent, and RESURRECT the handle.

        W11/a6: `_dead` used to be sticky, so a handle that was reaped and then
        SPAWNED AGAIN still reported `dead` from liveness() and `done` from
        sessions() — the stub could not model a re-spawn at all. That is exactly
        the shape suspend→resume produces (reap the planner, put it back), and
        a resume looks idempotent-broken against it for no real reason. A newly
        spawned shell on a handle is ALIVE; the crash simulation applies to the
        shell that died, not to the handle forever."""
        handle = row.get("handle")
        if handle:
            self._dead.discard(handle)
            self._parked.discard(handle)   # 1.5.2: a fresh spawn un-parks
        self.spawns.append(row)

    def set_output_ts(self, handle: str, ts: float) -> None:
        """Test helper: simulate recent shell output at epoch `ts`, so
        liveness(handle)['last_output_ts'] returns it."""
        self._output_ts[handle] = ts

    async def spawn_planner(
        self, recipe_id: str, step_id: str, model: str | None = None,
        resume_session: str | None = None,
    ) -> ToolResult:
        # W11: signature parity with HttpPool. Pin a fresh uuid4 and echo it
        # back exactly as the real client does, so a caller under test reads
        # the same `claude_session_id`; record `resume_session` so the
        # fork-resume dispatch can be asserted. No fork is simulated — this
        # stub spawns no shells.
        claude_session = str(uuid.uuid4())
        self._record(
            {"role": "planner", "handle": f"{recipe_id}:{step_id}",
             "model": model, "claude_session": claude_session,
             "resume_session": resume_session}
        )
        return Tool.ok(_Spawned(handle=f"{recipe_id}:{step_id}",
                                claude_session_id=claude_session))

    async def spawn_worker(
        self, plan_id: str, action_id: str, model: str | None = None,
        role: str = "worker",
    ) -> ToolResult:
        # s17 FA3: record the optional per-action model override so tests can
        # assert the dispatch path threads it (None when no tier was stamped).
        # s26 item 6b: `role` is recorded the same way so a test can assert a
        # reviewer leg really dispatches as EDP_ROLE=reviewer.
        self._record(
            {"role": role, "handle": f"{plan_id}:{action_id}",
             "model": model}
        )
        return Tool.ok(_Spawned(handle=f"{plan_id}:{action_id}"))

    # (spawn_goal_keeper / spawn_pattern_observer stubs lived here — DELETED
    # with their roles, owner ruling 2026-08-04.)

    async def spawn_curiosity(
        self, parent_id: str, curiosity_id: str, model: str | None = None
    ) -> ToolResult:
        self._record(
            {"role": "curiosity", "handle": curiosity_id,
             "parent": parent_id, "model": model}
        )
        return Tool.ok(_Spawned(handle=curiosity_id))

    async def spawn_specialist(
        self, parent_id: str, specialist_id: str,
        claude_session: str | None = None,
        mode: str = "headless",
        resume_session: str | None = None,
        model: str | None = None,
    ) -> ToolResult:
        self._record(
            {"role": "specialist", "handle": specialist_id,
             "parent": parent_id, "claude_session": claude_session,
             "mode": mode, "resume_session": resume_session,
             "model": model}
        )
        return Tool.ok(_Spawned(handle=specialist_id))

    async def spawn_reviewer(
        self, parent_id: str, handle: str, session_id: str,
        model: str | None = None,
    ) -> ToolResult:
        self._record(
            {"role": "reviewer", "handle": handle, "parent": parent_id,
             "claude_session": session_id, "resume_session": None,
             "base_session": None, "fork_session": session_id,
             "model": model}
        )
        return Tool.ok(_Spawned(handle=handle))

    async def spawn_consult(
        self, parent_id: str, consult_id: str,
        mode: str = "monitor",
        model: str | None = None,
    ) -> ToolResult:
        # W5: record mode + the resolved tier so tests can assert the
        # convene_consult dispatch threads them (mode=monitor, model=opus).
        self._record(
            {"role": "consult", "handle": consult_id,
             "parent": parent_id, "mode": mode, "model": model}
        )
        return Tool.ok(_Spawned(handle=consult_id))

    async def liveness(self, handle: str) -> dict:
        # W7: {state, last_output_ts} mirroring HttpPool. state is the
        # crash/alive signal; last_output_ts is the (simulated) drain-log
        # mtime (None unless a test set it via set_output_ts).
        # DESIGN-v7 1.5.2: 'parked' is a THIRD answer of its own (neither
        # alive nor dead — the real pool reports it for a parked handle so
        # crash recovery never reincarnates a deliberately-parked planner).
        if handle in self._parked:
            state = "parked"
        elif handle in self._dead:
            state = "dead"
        elif any(s["handle"] == handle for s in self.spawns):
            state = "alive"
        else:
            state = "unknown"
        return {"state": state, "last_output_ts": self._output_ts.get(handle)}

    async def sessions(self, recipe_id: str | None = None) -> list[dict]:
        """GET-backed session list (object-model `session` reader). Maps
        recorded spawns to session dicts; alive unless marked dead.

        W11: `recipe_id` is RECORDED on `last_sessions_filter` and returned
        rows are unchanged — see the __init__ note. Assert forwarding here."""
        self.last_sessions_filter = recipe_id
        out = []
        for s in self.spawns:
            h = s.get("handle")
            out.append({
                "session_id": s.get("session_id", s.get("role", "") + ":" + str(h)),
                "role": s.get("role"),
                "handle": h,
                "parent": s.get("parent"),
                # DESIGN-v7 1.5.2: a parked handle's row survives as
                # state="parked" (the real pool's third state — it does NOT
                # count against the active cap and is not done).
                "state": ("parked" if h in self._parked
                          else "done" if h in self._dead else "active"),
                # W11: the session the shell was LAUNCHED with, mirroring the
                # real pool's row (edp-pool/service.py). suspend_recipe's
                # manifest snapshots it so a resume can fork the planner; a
                # worker pins none, so this is None for one — exactly as in
                # prod. Without it the stub would silently hide the field the
                # manifest depends on.
                "claude_session_id": s.get("claude_session"),
            })
        return out

    async def locks(self) -> list[dict]:
        """GET-backed lock list (object-model `lock` reader). Each held
        handle with truthful liveness; dead handles surface as a phantom
        lock (liveness=dead) until reaped, mirroring the real pool."""
        out = []
        for s in self.spawns:
            h = s.get("handle")
            if not h:
                continue
            out.append({
                "handle": h,
                "session_id": s.get("session_id",
                                    s.get("role", "") + ":" + str(h)),
                "liveness": "dead" if h in self._dead else "alive",
            })
        return out

    async def release(self, session_id: str, park: bool = False) -> ToolResult:
        # DESIGN-v7 1.5.2: a park-release keeps the spawn row (the real pool
        # keeps the session row + lock as the resume token) and marks the
        # handle parked; a plain release drops it, as before.
        if park:
            for s in self.spawns:
                if s.get("session_id") == session_id:
                    h = s.get("handle")
                    if h:
                        self._parked.add(h)
            return Tool.ok(_Released(released=session_id))
        self.spawns = [s for s in self.spawns
                       if s.get("session_id") != session_id]
        return Tool.ok(_Released(released=session_id))

    async def close_when_idle(
        self, session_id: str, idle_secs: float, reason: str = "",
        park: bool = False,
    ) -> ToolResult:
        # s26 item 1. Records the ARM (test-observable) without reaping — the
        # real pool defers the reap until the shell falls idle. Tests assert
        # THAT THE ARM HAPPENED; the reap itself is tested against the pool.
        # DESIGN-v7 1.5.2: `park` rides the same recorded intent — tests
        # assert the self-park ARM was made; the park itself is the pool's.
        self.armed_closes.append(
            {"session_id": session_id, "idle_secs": idle_secs,
             "reason": reason, "park": park}
        )
        return Tool.ok(_Armed(session_id=session_id, armed=True))

    async def resume(self, handle: str) -> ToolResult:
        # DESIGN-v7 1.5.3: record the resume intent (test-observable) and
        # un-park the handle — the real pool's fork-resume/CAS semantics are
        # tested against the pool, not re-invented here.
        self.resumes.append(handle)
        was_parked = handle in self._parked
        self._parked.discard(handle)
        return Tool.ok(_Resumed(handle=handle, resumed=was_parked))

    async def reap(self, handle: str) -> ToolResult:
        # mark the handle's spawn dead + drop it (test-observable)
        self._dead.add(handle)
        self.spawns = [s for s in self.spawns if s.get("handle") != handle]
        return Tool.ok(_Released(released=handle))
