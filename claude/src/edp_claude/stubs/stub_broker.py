"""In-process broker stub (LLD §3). Same BrokerMessage envelope as the real
edp-broker; swapping to HttpBroker (#3) is DI-only."""

from datetime import datetime

from edp_contracts import BrokerMessage, Tool
from pydantic import BaseModel

from ..ports import BrokerPort, ToolResult


class _Sent(BaseModel):
    msg_id: str


class StubBroker(BrokerPort):
    def __init__(self) -> None:
        self.inboxes: dict[str, list[BrokerMessage]] = {}
        # s12(c): absolute alias map (mirrors the real broker's AliasStore).
        # Resolved on BOTH the store (send) and read (poll/query) paths so a
        # publish to an aliased name and a poll on the live name hit the same
        # inbox — keeps the tools-level regression test hermetic.
        self._aliases: dict[str, str] = {}

    def _resolve(self, recipient: str) -> str:
        # Identity fallback for unmapped recipients (edp-broker store.py:80).
        return self._aliases.get(recipient, recipient)

    async def register_alias(
        self, alias: str, target: str, owner_session: str = "*"
    ) -> None:
        # s12(c): in-memory absolute (ownerless) bridge `alias → target`.
        # Idempotent: same (alias, target) re-asserted each reconcile tick.
        self._aliases[alias] = target

    async def send(self, msg: BrokerMessage) -> ToolResult:
        self.inboxes.setdefault(self._resolve(msg.to), []).append(msg)
        return Tool.ok(_Sent(msg_id=msg.msg_id))

    async def poll(
        self, recipient: str, since_ts: datetime | None = None
    ) -> list[BrokerMessage]:
        msgs = self.inboxes.get(self._resolve(recipient), [])
        if since_ts is None:
            return list(msgs)
        return [m for m in msgs if m.ts > since_ts]

    async def get_message(self, msg_id: str) -> BrokerMessage | None:
        # Scan across inboxes — msg counts are small per recipient.
        # The HttpBroker version uses a real index.
        for msgs in self.inboxes.values():
            for m in msgs:
                if m.msg_id == msg_id:
                    return m
        return None

    async def query(
        self,
        to: str | None = None,
        from_: str | None = None,
        kind: str | None = None,
        since: datetime | None = None,
    ) -> list[BrokerMessage]:
        # Cross-inbox query (object-model `message` reader) — mirrors the
        # real broker's GET /v1/messages server-side filter.
        if to is not None:
            pools = [self.inboxes.get(self._resolve(to), [])]
        else:
            pools = list(self.inboxes.values())
        out: list[BrokerMessage] = []
        for msgs in pools:
            for m in msgs:
                if from_ is not None and m.from_ != from_:
                    continue
                if kind is not None and m.kind != kind:
                    continue
                if since is not None and not (m.ts > since):
                    continue
                out.append(m)
        out.sort(key=lambda m: m.ts)
        return out
