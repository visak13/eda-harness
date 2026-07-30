# REFACTOR — edp-broker (component #3, S3b)

**Constants:** `_VERSION`, `_ENVELOPE_HTTP_STATUS = 409` extracted (was an
inline literal in `_err`). Recipient-validation regex already a module
constant.

**Enums:** none new. `ErrorCode` (edp-contracts) used for the two broker
codes. No status-Literal candidates here.

**ABC/interface:** `BrokerService` implements the `Microservice` ABC;
mounted via `edp_contracts.mount` (uniform `/v1/health`, structured logging,
envelope exception handler). No missing seam.

**LLD deviations:** none. Implemented as specified.

**TODO sweep (§4a):** no TODOs introduced. One documented *limitation* (not
a TODO): `/v1/events` SSE replays the backlog since `since_ts` then emits a
single keep-alive and closes — reconnect-safe and sufficient for the
poll-based `BrokerPort`; a long-lived live-tail stream is a future
enhancement, explicitly out of scope for the launch set (consumers use
`/v1/inbox` polling per DESIGN-v4). Recorded here so it is a known choice,
not an oversight.

**Verification:** 12 tests pass; ruff clean (incl flake8-print); 90% cov
(`main.py` is the uvicorn entrypoint — process glue, not unit-tested by
design).
