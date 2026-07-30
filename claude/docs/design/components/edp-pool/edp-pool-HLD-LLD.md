# HLD+LLD — edp-pool (component #4)

**Stage:** S1+S2 combined (simple service; proportionate depth per METHODOLOGY). Case-a S4. Depends on `edp-contracts==0.1.0`, talks to `edp-broker` for alias registration.

## 1. Responsibility
Spawn-on-demand Claude shells; own the `session ↔ role ↔ handle` map; **lock-by-spawn-lifetime** (the spawn IS the action lock — DESIGN-v4 collapses the two; LLM never sees a lock); worker-liveness; **max 3 workers** with the capacity error returned **verbatim** so the LLM acts (user 2026-05-17); register relative-ref aliases into the broker so `my-planner` resolves.

Out of scope: recipe/plan semantics; message transport (broker's job).

## 2. The Spawner seam (IoC, like ports)
Real subprocess launch is OS-heavy + not unit-testable, so it sits behind:
```python
class Spawner(ABC):
    def launch(self, session_id, role, handle) -> None
    def alive(self, session_id) -> bool
    def kill(self, session_id) -> None
class FakeSpawner(Spawner):   # in-memory alive set — tests + this component's S4
class SubprocessSpawner(Spawner):
    # TODO(integration,#9): launch the real edp-shell/claude wrapper.
    # Fully testable logic uses FakeSpawner now; real spawn is the
    # manual-HITL surface at the integration milestone.
```

## 3. Interface (`/v1`, Microservice ABC)
- `POST /v1/spawn` `{role, handle, parent_session?}` → allocate `session_id`; if `role=="worker"` and active workers ≥ 3 → `ToolError(pool_capacity_exceeded, retryable)` @409 (verbatim); acquire lock on `handle` (refuse duplicate active handle → `pool_unknown_handle`); `spawner.launch`; record map; if `parent_session` → `broker POST /v1/alias {owner=parent, alias="my-<role>", target=session_id}`. Returns `{session_id}`.
- `POST /v1/release/{session_id}` → release handle lock; mark done; (broker `done`); idempotent.
- `GET /v1/sessions` → list `{session_id, role, handle, state}` (observability only).
- `GET /v1/liveness/{handle}` → `alive|dead|unknown` (from spawner + map).
- `GET /v1/health`.

## 4. State (in-proc; restart = empty fleet, by design — spawns are ephemeral)
`_sessions: dict[sid, {role,handle,parent,state}]`; `_locks: dict[handle, sid]`. No disk: a pool restart means in-flight shells are gone; the neuron/planner re-derive from recipe/plan state on disk (that's the whole point of artifact-as-truth).

## 5. Consumer client (edp-claude `clients/http_pool.py`)
`HttpPool(PoolPort)`: `spawn_planner/spawn_worker` → `POST /v1/spawn`; 2xx→ToolOk, else `Tool.from_upstream` (capacity error reaches the LLM verbatim → it waits/dispatches-fewer). `liveness` → `GET /v1/liveness/{handle}`.

## 6. Tests (binding S3c)
POOL-1 spawn returns session_id + records map; POOL-2 4th worker → pool_capacity_exceeded envelope (not 500); POOL-3 lock-by-spawn: duplicate active handle refused; POOL-4 release frees lock, re-spawn ok; POOL-5 liveness alive/dead/unknown via FakeSpawner; POOL-6 parent spawn registers broker alias (FakeBroker records call); POOL-7 /v1/health conforms; POOL-8 sessions list. Static: ruff+flake8-print, edp-contracts pinned. (HttpPool exercised at integration #9, not here — deploy independence.)

## 7. No open questions — boundaries dictated by DESIGN-v4 + edp-contracts. Proceed.
