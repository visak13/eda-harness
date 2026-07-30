# REFACTOR — Base Contracts (component #1, stage S3b)

**Stage:** S3b (Refactor) — runs after S3a Dev, before S3c Tests. Mandated by user 2026-05-16.
**Scope of pass:** extract hard-coded values → named constants; detect enums that earn their keep; detect interface/ABC opportunities. Record what changed and why.
**Outcome:** applied in-place to `eda-base/edp-contracts/src/edp_contracts/`. No behavioural change intended; one LLD signature deviation flagged for the gate (§4).

---

## 1. Enums introduced (each justified)

| New enum | Module | Was | Why it earns its keep |
|---|---|---|---|
| `ErrorCode(StrEnum)` | `errors.py` | ~10 loose `str` constants | Type-safe refs (`ErrorCode.POOL_CAPACITY_EXCEEDED`), `list(ErrorCode)` for tests, `ALL_CODES = frozenset(ErrorCode)` derives automatically. StrEnum stays str-compatible so `ToolError.code: str` still accepts unknown upstream codes. LLD §7 explicitly asked this be evaluated — verdict: yes. |
| `SkillRule(StrEnum)` | `skill.py` | scattered `"R1"`..`"R5"` literals in `validate_skill` + `Violation.rule: str` | Eliminates literal drift; `Violation.rule: SkillRule` is now type-checked; tests reference `SkillRule.R2` not a magic string. |

**Enums deliberately NOT introduced** (documented so the next reviewer doesn't redo this analysis):
- `HealthState`, `DepState`, `LogLevel`, `Tool.backing` stay `Literal`. They are only ever Pydantic field types / class-attr annotations where `Literal` gives identical validation with no extra import. A StrEnum here would be churn for no gain.

## 2. Constants extracted (hard-coded values → named)

| Constant | Module | Replaced |
|---|---|---|
| `HEALTH_PATH = "/v1/health"` | `service.py` | inline route string |
| `_KIND_REQUEST_IN/_OUT/_UNHANDLED` | `service.py` | inline log-kind strings in `mount()` |
| `_REQUIRED_ENVELOPE_KEYS` | `tool.py` | inline `("source","code","message")` tuple in `from_upstream` |
| `_UNLOAD_SENTINELS` | `skill.py` | inline `"unload"`/`"end skill"` literals in R3 |
| `_LOGGER_NAMESPACE`, `_DEFAULT_SVC`, `_DEFAULT_KIND` | `logging.py` | inline `"edp."`, `"unknown"`, `"log"` |

`CORE_KINDS` (broker) was already a single named dict — left as-is (it was correct).

## 3. Interface / ABC opportunities applied

| Change | Module | Rationale |
|---|---|---|
| `Tool` is now a real `abc.ABC` with `@abstractmethod run` | `tool.py` | S3a had `raise NotImplementedError` — that does NOT prevent instantiating an incomplete tool. ABC does. (Class-attr presence still a contract-test concern — documented in the class docstring; an ABC can't enforce class attrs at instantiation.) |
| `LoggerLike(Protocol)` added; `get_logger -> LoggerLike` | `logging.py` | Consumers/tests can type against the interface and inject a fake logger instead of depending on the concrete `_Logger`. Matches the existing `HttpResponseLike` Protocol style. |

`HttpResponseLike` (tool) and `Microservice` (service ABC) were already correct interface shapes from S3a — no change.

## 4. LLD deviation flagged for the S3b gate

`parse_skill_header` LLD §4 signature was `-> tuple[SkillHeader | None, str]` (header, body). **Implemented as 3-tuple `(SkillHeader | None, body, parse_error)`.** Reason: R1's `Violation.detail` needs the human-readable parse failure reason; a 2-tuple forced re-deriving it. This is a strict improvement but it is an LLD deviation, so it is surfaced here rather than absorbed silently (METHODOLOGY §5.4). **Gate decision needed:** accept the 3-tuple and amend the LLD, or revert.

## 5. TESTPLAN impact

`base-contracts-TESTPLAN.md` references error codes and skill-rule ids as bare tokens (e.g. "code == `TOOL_PRECONDITION`", "`Violation{rule:"R2"}`"). After this refactor those map to `ErrorCode.TOOL_PRECONDITION` and `SkillRule.R2`. The test assertions are unchanged in intent (StrEnum compares equal to its string value), but S3c test code should reference the enum members. No TESTPLAN rows are invalidated; one clarifying note will be added at S3c.

## 6. What did NOT change

- No behavioural logic was altered. Same validation rules, same envelope semantics, same broker registry behaviour.
- Public surface grew by exactly three additive exports (`ErrorCode`, `SkillRule`, `LoggerLike`) — a minor (additive) version per LLD §8; package still `0.1.0` (pre-release, no consumers yet).
- Dependency set unchanged (pydantic + stdlib; FastAPI still optional/lazy).

## 7. Verification status

- Static re-read complete; module graph is acyclic (`__init__` → submodules; `service.mount` lazy-imports errors/logging/tool to avoid an import cycle and to keep FastAPI optional).
- **Runtime smoke PASSED** via `uv run` (Python not on PATH; uv 0.9.11 resolves pydantic and runs):
  - import OK; `ErrorCode`=10 members; `CORE_KINDS`=11; 25 public exports; `SkillRule`=R1..R5; `Tool` is a real `abc.ABCMeta`.
  - `Tool.propagate()` preserves the message byte-for-byte; `retryable` defaults True for `POOL_CAPACITY_EXCEEDED`.
  - `BrokerMessage` round-trips with the `from` wire-alias; `from_` never leaks to the wire.
  - Unregistered broker kind is rejected at construction with the expected message.
- This is smoke (load-bearing guarantees), NOT the TESTPLAN. Full unit/contract/static gates (ST-1 clean-venv install, ST-2 <200ms import, coverage, ruff/flake8-print) remain S3c.

## 8. S3b exit gate

User confirms: **"Refactor is right. Proceed to S3c (tests)."**
Plus the one explicit decision: **accept the `parse_skill_header` 3-tuple (and amend LLD §4), or revert to 2-tuple?**
