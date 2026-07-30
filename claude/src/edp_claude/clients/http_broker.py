"""HttpBroker — BrokerPort over the real edp-broker (component #3).

The consumer owns the port impl. Swapping StubBroker→HttpBroker is a single
line in server.py; no call site changes (the IoC seam, DESIGN-v4).
Upstream errors are re-wrapped via Tool.from_upstream — verbatim, and it
raises EnvelopeViolation loudly if the broker ever breaks the envelope.
"""

from datetime import datetime

import httpx
from edp_contracts import BrokerMessage, Tool
from pydantic import BaseModel

from ..ports import BrokerPort, ToolResult

# C2 (DESIGN-v6 s18): the fast per-tick poll must NOT ride the shared 30s httpx
# client — a hung broker would otherwise stall a reconcile tick for 30s. Give
# poll a dedicated short timeout (bounded to the 2-5s window).
POLL_TIMEOUT_S = 3.0


class _Sent(BaseModel):
    msg_id: str


class HttpBroker(BrokerPort):
    def __init__(self, base_url: str, client: httpx.AsyncClient):
        self.base = base_url.rstrip("/")
        self.client = client

    async def send(self, msg: BrokerMessage) -> ToolResult:
        r = await self.client.post(
            f"{self.base}/v1/publish",
            json=msg.model_dump(mode="json", by_alias=True),
        )
        if r.status_code // 100 == 2:
            return Tool.ok(_Sent(msg_id=r.json()["msg_id"]))
        return Tool.from_upstream(r)  # verbatim or EnvelopeViolation

    async def poll(
        self, recipient: str, since_ts: datetime | None = None
    ) -> list[BrokerMessage]:
        params = {}
        if since_ts is not None:
            params["since_ts"] = since_ts.isoformat()
        r = await self.client.get(
            f"{self.base}/v1/inbox/{recipient}", params=params,
            timeout=POLL_TIMEOUT_S,
        )
        r.raise_for_status()
        return [BrokerMessage.model_validate(x) for x in r.json()]

    async def get_message(self, msg_id: str) -> BrokerMessage | None:
        # Phase 2.5 (2026-05-21): needed by Reply tool. The real
        # edp-broker `/v1/message/{msg_id}` endpoint lands when this
        # path is first exercised live; until then HttpBroker stubs
        # cleanly. (TODO: implement broker-side index + endpoint.)
        r = await self.client.get(f"{self.base}/v1/message/{msg_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return BrokerMessage.model_validate(r.json())

    async def query(
        self,
        to: str | None = None,
        from_: str | None = None,
        kind: str | None = None,
        since: datetime | None = None,
    ) -> list[BrokerMessage]:
        # GET /v1/messages cross-inbox inspection (object-model reader).
        params: dict[str, str] = {}
        if to is not None:
            params["to"] = to
        if from_ is not None:
            params["from"] = from_
        if kind is not None:
            params["kind"] = kind
        if since is not None:
            params["since_ts"] = since.isoformat()
        r = await self.client.get(f"{self.base}/v1/messages", params=params)
        r.raise_for_status()
        return [BrokerMessage.model_validate(x) for x in r.json()]

    async def register_alias(
        self, alias: str, target: str, owner_session: str = "*"
    ) -> None:
        # s12(c): POST /v1/alias — same absolute (ownerless) bridge the pool
        # registers for a planner's colon→dash handle (edp-pool/service.py:
        # 356-371). Best-effort: a broker that is down must NOT fail the
        # neuron's reconcile tick; the next tick re-asserts (idempotent).
        try:
            await self.client.post(
                f"{self.base}/v1/alias",
                json={
                    "owner_session": owner_session,
                    "alias": alias,
                    "target": target,
                },
            )
        except Exception:  # noqa: BLE001 — broker down ≠ tick failure
            pass
