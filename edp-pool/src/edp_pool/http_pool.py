"""HttpPool — the PoolPort impl the edp-claude consumer swaps in.

Lives here (not in edp-claude) so edp-claude need not depend on edp-pool's
package; the integration milestone (#9) imports it. It implements the same
PoolPort ABC shape edp-claude defines; capacity errors reach the LLM
VERBATIM (user 2026-05-17) via Tool.from_upstream.
"""

import httpx
from edp_contracts import Tool, ToolError, ToolOk
from pydantic import BaseModel


class _Spawned(BaseModel):
    handle: str
    session_id: str


class _Released(BaseModel):
    released: str


class HttpPool:
    """Duck-types edp_claude.ports.PoolPort."""

    def __init__(self, base_url: str, client: httpx.AsyncClient):
        self.base = base_url.rstrip("/")
        self.client = client

    async def _spawn(self, role, handle, **extra):
        r = await self.client.post(
            f"{self.base}/v1/spawn",
            json={"role": role, "handle": handle, **extra},
        )
        if r.status_code // 100 == 2:
            return Tool.ok(
                _Spawned(handle=handle, session_id=r.json()["session_id"])
            )
        return Tool.from_upstream(r)  # capacity error verbatim

    async def spawn_planner(self, recipe_id: str, step_id: str):
        return await self._spawn(
            "planner", f"{recipe_id}:{step_id}", parent_session=recipe_id
        )

    async def spawn_worker(self, plan_id: str, action_id: str):
        return await self._spawn(
            "worker", f"{plan_id}:{action_id}", parent_session=plan_id
        )

    async def liveness(self, handle: str):
        r = await self.client.get(f"{self.base}/v1/liveness/{handle}")
        r.raise_for_status()
        return r.json()["state"]

    async def release(self, session_id: str):
        r = await self.client.post(f"{self.base}/v1/release/{session_id}")
        if r.status_code // 100 == 2:
            return Tool.ok(_Released(released=session_id))
        return Tool.from_upstream(r)


__all__ = ["HttpPool", "ToolOk", "ToolError"]
