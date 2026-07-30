# LLD — edp-broker (component #3)

**Stage:** S2. Signatures/schemas/pseudocode + test list. No impl (S3a).

## 1. Layout
```
eda-base/edp-broker/
├── pyproject.toml            # edp-contracts==0.1.0 (path src), fastapi, uvicorn; dev: pytest,httpx,ruff,flake8-print
├── src/edp_broker/
│   ├── __init__.py
│   ├── service.py            # BrokerService(Microservice) + create_app()
│   ├── store.py              # InboxStore: append/read jsonl, AliasStore
│   └── main.py               # uvicorn entrypoint
└── tests/ test_broker_service.py  test_store.py
```

## 2. store.py
```python
class InboxStore:
    def __init__(self, data: Path): ...
    def append(self, msg: BrokerMessage) -> None      # resolve alias→target, write <target>.jsonl
    def read(self, recipient: str, since: datetime|None) -> list[BrokerMessage]
class AliasStore:
    def put(self, owner: str, alias: str, target: str) -> None   # data/aliases.json (atomic)
    def resolve(self, recipient: str) -> str | None  # alias 'owner/alias' → target; passthrough if concrete
```
Recipient validated `^[A-Za-z0-9._:-]{1,128}$` (filesystem-safe) else `broker_no_route`.

## 3. service.py
```python
class BrokerService(Microservice):
    name="edp-broker"; version="1.0.0"
    async def startup/shutdown/health  # health: ready; deps {}
def create_app() -> FastAPI:
    app=FastAPI(); svc=BrokerService(store); mount(app, svc)  # /v1/health, logging, envelope
    @app.post("/v1/publish")  -> validate BrokerMessage; resolve alias;
        on validation/route error return ToolError(...).model_dump(); else store.append; {msg_id}
    @app.get("/v1/inbox/{recipient}") -> store.read(...) (since_ts query)
    @app.get("/v1/events") -> StreamingResponse(text/event-stream):
        yield backlog since since_ts as `data: {json}\n\n`; then periodic keep-alive `: ping`.
        (Replay-on-reconnect = idempotent by since_ts.)
    @app.post("/v1/alias") -> AliasStore.put; {ok:true}
```
Error rule: upstream/validation failures returned as the standard envelope dict (edp-contracts §13.2) — never a raw 500/stack.

## 4. Consumer client (in edp-claude) `clients/http_broker.py`
```python
class HttpBroker(BrokerPort):
    def __init__(self, base_url, client: httpx.AsyncClient): ...
    async def send(msg) -> ToolResult:   POST /v1/publish; 2xx→ToolOk; else Tool.from_upstream(resp)
    async def poll(recipient, since_ts) -> list[BrokerMessage]:  GET /v1/inbox/{r}
```
`from_upstream` enforces the envelope (raises EnvelopeViolation if broker misbehaves — loud, by contract).

## 5. Tests (binding S3c)
- BRK-S-1: publish→inbox round-trip (envelope preserved, from-alias).
- BRK-S-2: unregistered kind → ToolError(broker_unregistered_kind), not 500.
- BRK-S-3: since_ts filter returns only newer.
- BRK-S-4: durability — new InboxStore over same dir sees prior messages.
- BRK-S-5: alias resolve (owner/alias→target); unresolved → broker_no_route.
- BRK-S-6: bad recipient name → broker_no_route (not a path escape).
- BRK-S-7: /v1/health conforms to HealthStatus (CON, via mount).
- BRK-S-8: SSE /v1/events replays backlog since since_ts.
- HttpBroker round-trip against TestClient (ASGI transport).
- Static: ruff incl flake8-print; edp-contracts pinned.

## 6. S2 — no open questions; proceed S3a.
