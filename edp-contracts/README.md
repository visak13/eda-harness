# edp-contracts

Single-sourced base contracts for the `eda-base` system. Every microservice,
MCP tool, and skill conforms to these so the system stays standardized as it
scales.

**Design authority:** `claude/docs/design/components/base-contracts/`
(`*-HLD.md`, `*-LLD.md`, `*-TESTPLAN.md`). This package implements that LLD.

## What's in here

| Module | Contract |
|--------|----------|
| `service` | `Microservice` ABC, `HealthStatus`, `mount()` (FastAPI wired uniformly) |
| `tool` | `Tool` ABC, `ToolOk`/`ToolError` envelopes, verbatim error propagation |
| `skill` | `SkillHeader` schema + `validate_skill()` structural validator |
| `broker` | `BrokerMessage` envelope, `BrokerKind` registry, `register_kind()` |
| `logging` | `get_logger()` — one structured-JSON line schema, never `print()` |
| `errors` | Stable machine error codes (the `code` field of `ToolError`) |

## Dependency discipline

Hard deps: **pydantic + stdlib only**. FastAPI is an optional extra
(`edp-contracts[service]`) used only by `mount()`, lazily imported, so
importers that just need the `Tool` ABC stay light.

## Versioning

Semver. Breaking an ABC/envelope = major. Adding a broker kind / error code =
minor. Consumers pin `edp-contracts==X.Y.Z`; CI fails a floating pin.
