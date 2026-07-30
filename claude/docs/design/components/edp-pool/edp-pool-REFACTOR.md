# REFACTOR — edp-pool (component #4, S3b)

**Constants:** `_VERSION`, `_MAX_WORKERS = 3`, `_ENVELOPE_HTTP_STATUS = 409`
all module-level (no inline magic numbers). The capacity message embeds
`_MAX_WORKERS` so the verbatim text the LLM sees stays in sync.

**Enums:** none new; `ErrorCode` (edp-contracts) used for the three pool
codes. Session `state` is a 2-value in-memory flag, not a public schema —
plain string is right (no Literal/enum ceremony earned).

**Interface/ABC:** `PoolService` implements `Microservice`;
`Spawner` is an ABC with `FakeSpawner` (test/S4) + `SubprocessSpawner`
(integration). `HttpPool` duck-types `edp_claude.ports.PoolPort`. Seams
clean.

**Deliberate broad except:** the broker-alias registration is wrapped in
`except Exception: pass` — intentional and documented: **broker
unavailability is not a spawn failure** (the spawn is the lock; alias is a
convenience the broker can backfill). Flagged here so it isn't read later
as a swallowed error (it is the one place a non-envelope swallow is
correct, and it's logged-only by design).

**TODO sweep (§4a):** one TODO — `SubprocessSpawner` real launch —
**re-deferred with explicit owner: integration milestone #9**. Pool LOGIC
(locks, capacity, liveness, alias) is fully proven now via `FakeSpawner`;
the real subprocess spawn is precisely the manual-HITL surface, so it
*belongs* at #9, not here. Legitimate per §4a.

**Coverage note:** service.py 97%, spawner 100%. `http_pool.py` (consumer
client) and `main.py` (uvicorn entrypoint) are 0% by design — exercised at
integration #9 / process glue. Same precedent as edp-broker.

**Verification:** 9 tests green, ruff clean (incl flake8-print),
edp-contracts pinned.

---

## S3b delta — real SubprocessSpawner (2026-05-17)

Triggered by user decision + `edp-pool-IMPACT-subprocess-spawner.md`.

- **Constants extracted** in `pty_launcher.py`: `_PROMPT_READY` (`❯`),
  `_READ_SIZE`, `_DEFAULT_COLS/ROWS`, `_SUBMIT_DELAY_ENV/_DEFAULT_MS`.
- **Enums:** none warranted.
- **Interface:** `Spawner` ABC unchanged; `SubprocessSpawner` is now a
  real impl delegating to the ported `PtyLaunch`. Seam intact.
- **TODO sweep (§4a):** prior `# TODO(integration,#9)` on
  `SubprocessSpawner` is **RESOLVED** (implemented). **Zero open TODOs in
  edp-pool.** One documented *limitation* (not a TODO): non-Windows has
  no PTY launcher — `launch` raises a clear error there; Windows is the
  target env, POSIX launcher out of scope until a real need.
- **Ported vs dropped** (user: "launching logic only"): ported =
  bin-resolution, ConPTY spawn, `❯`-ready, activation write, alive/kill.
  dropped = human stdio proxy, meta parser, old BrokerClient WS,
  HTTP-injection POC.
- **Verification:** 18 tests green (9 FakeSpawner regression + 9 SUB
  mocked-winpty), ruff clean, spawner.py 100% / pty_launcher 88% /
  service 97%. The real spawn is untestable here by nature → it IS the
  manual-HITL surface (#9).
