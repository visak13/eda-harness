# TESTPLAN — Base Contracts (component #1)

**Stage:** written at S2, executed at S3. Each test below is binding acceptance for S3.
**Reads from:** `base-contracts-LLD.md` §9.
**Convention:** every test has an ID, a target, the setup, and the pass condition. S3 is not "done" until every `MUST` test is green.

---

## 1. Unit — `service.py`

| ID | Target | Setup | Pass condition |
|---|---|---|---|
| SVC-1 MUST | `Microservice` ABC | define a conforming mock (`name`, `version`, all 3 async methods) | instantiates; `health()` returns a valid `HealthStatus` |
| SVC-2 MUST | ABC enforcement | define a mock missing `shutdown()` | instantiation raises `TypeError` (abstract method) |
| SVC-3 MUST | `HealthStatus` | construct with bad `status="up"` | `ValidationError` (Literal mismatch) |
| SVC-4 MUST | `mount()` lazy import | import `edp_contracts.service` without FastAPI installed in a clean venv | import succeeds; calling `mount()` without FastAPI raises a clear ImportError naming FastAPI |
| SVC-5 SHOULD | `mount()` wiring | mount a mock on a TestClient app | `GET /v1/health` → 200 + HealthStatus JSON; startup/shutdown hooks fire |

## 2. Unit — `tool.py` (load-bearing)

| ID | Target | Setup | Pass condition |
|---|---|---|---|
| TOOL-1 MUST | `Tool` ABC | conforming mock tool | `run()` returns `ToolOk`; `.ok(model)` round-trips the OutputModel |
| TOOL-2 MUST | `propagate()` verbatim | call with `message="max workers = 3; 3 active"` | `ToolError.message` is byte-identical; nothing appended/prefixed |
| TOOL-3 MUST | no-digest enforcement | static check + API surface test | there is **no** public constructor/method on `Tool`/`ToolError` that transforms `message`; only `propagate`/`from_upstream` exist; `ToolError` has no `summarize` |
| TOOL-4 MUST | `from_upstream()` | feed a well-formed envelope JSON | re-wrapped unchanged (source/code/message preserved) |
| TOOL-5 MUST | envelope integrity | feed a malformed (non-envelope) upstream error | raises `EnvelopeViolation`, NOT a silent `ToolError` |
| TOOL-6 MUST | union serialization | dump `ToolOk` and `ToolError` to JSON | both serialize; `ok` discriminator present and correct |
| TOOL-7 SHOULD | `TOOL_PRECONDITION` shape | construct an instruction-shaped error | message reads as an actionable instruction ("call X first"), code == `TOOL_PRECONDITION` |

## 3. Unit — `skill.py`

| ID | Target | Setup | Pass condition |
|---|---|---|---|
| SKL-1 MUST | R1 header parse | fixture skill with valid front-matter | `validate_skill` → `[]` |
| SKL-2 MUST | R1 missing header | fixture with no front-matter | one `Violation{rule:"R1"}` |
| SKL-3 MUST | R2 undeclared tool | body calls `record_plan(` but `via=["record_recipe"]` | `Violation{rule:"R2"}` naming `record_plan` |
| SKL-4 MUST | R3 missing unload | header.unload set but body has no unload instruction | `Violation{rule:"R3"}` |
| SKL-5 MUST | R4 bad host | `hosts:[orchestrator]` | `Violation{rule:"R4"}` |
| SKL-6 MUST | R5 worker spawn | host=worker, body calls `pool.spawn_worker(` | `Violation{rule:"R5"}` |
| SKL-7 SHOULD | R2 over-declare ok | `via` lists a tool the body never calls | no violation (over-declaration is allowed) |

## 4. Unit — `broker.py`

| ID | Target | Setup | Pass condition |
|---|---|---|---|
| BRK-1 MUST | round-trip | build `BrokerMessage`, dump, reload | equal; `ts` stays tz-aware UTC |
| BRK-2 MUST | `from` alias | serialize | wire JSON has key `"from"`, not `"from_"`; reload maps back |
| BRK-3 MUST | unregistered kind | construct with `kind="frobnicate"` | `ValidationError` mentioning register_kind |
| BRK-4 MUST | CORE_KINDS present | import module | all 11 CORE_KINDS registered with non-empty docs |
| BRK-5 MUST | register idempotent | `register_kind("done", <same doc>)` | no error; conflicting doc raises |
| BRK-6 SHOULD | extensibility | `register_kind("custom", "x")` then build msg kind=custom | succeeds |

## 5. Unit — `logging.py`

| ID | Target | Setup | Pass condition |
|---|---|---|---|
| LOG-1 MUST | mandatory fields | `get_logger("edp-pool").info("spawned","detail")` capture output | one JSON line with ts/svc/level/kind/detail all present |
| LOG-2 MUST | recommended fields ride | `.info("k","d", recipe_id="r1")` | `recipe_id:"r1"` present (extra=allow) |
| LOG-3 MUST | level fidelity | `.error(...)` | `level:"error"` |
| LOG-4 MUST | no-print static check | run ruff with flake8-print on `src/` | zero `print(` findings |

## 6. Contract tests

| ID | Target | Setup | Pass condition |
|---|---|---|---|
| CON-1 MUST | spec-correct health | mock microservice via `mount()` on TestClient | `/v1/health` schema matches `HealthStatus` exactly (extra=forbid honored) |
| CON-2 MUST | exception → envelope | mock route raises a bare `Exception` | response body is `ToolError`-shaped JSON, not a stack trace |
| CON-3 MUST | envelope-violation loud | mock upstream returns `{"err":"boom"}` to `from_upstream` | `EnvelopeViolation` raised (caught by test), not returned as ToolError |

## 7. Static / CI gates (not pytest, but binding for S3)

- ST-1 MUST: `edp-contracts` installs in a venv whose only deps are `pydantic` + stdlib (no FastAPI/httpx in the dependency tree). Verified by `uv pip tree`.
- ST-2 MUST: package import time < 200 ms cold (protects the `claude/` <2 s startup budget).
- ST-3 MUST: `ruff` clean (incl. flake8-print) on `src/`.
- ST-4 SHOULD: 100% line coverage on `tool.py` and `broker.py` (the two highest-risk modules); ≥90% elsewhere.

## 8. Exit criteria for S3 (per METHODOLOGY)

All `MUST` rows green + all `ST-*` MUST gates pass. Then S4 HITL: the user, by hand, (a) installs `edp-contracts` into a fresh venv, (b) writes a 10-line mock microservice using `mount()`, hits `/v1/health`, (c) constructs a `ToolError` via `propagate()` and confirms the message is verbatim. User signs `base-contracts-HITL.md`.
