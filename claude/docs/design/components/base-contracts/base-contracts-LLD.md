# LLD — Base Contracts (component #1)

**Stage:** S2 (Low-Level Design). Signatures + schemas + pseudocode only. **No implementation** (that is S3).
**Reads from:** `base-contracts-HLD.md` (frozen at S1 gate).
**Produces:** the exact module layout, signatures, Pydantic schemas, error codes, and the test list (→ `base-contracts-TESTPLAN.md`).

---

## 1. Repo + module layout

```
eda-base/edp-contracts/
├── pyproject.toml                 # name="edp-contracts"; deps: pydantic>=2; python>=3.12
├── src/edp_contracts/
│   ├── __init__.py                # re-exports the public surface (HLD §5)
│   ├── service.py                 # Microservice ABC, HealthStatus, mount()
│   ├── tool.py                    # Tool ABC, ToolOk, ToolError, propagate()
│   ├── skill.py                   # SkillHeader model, validate_skill(), Violation
│   ├── broker.py                  # BrokerMessage, BrokerKind, register_kind(), CORE_KINDS
│   ├── logging.py                 # get_logger(), LogRecordModel
│   └── errors.py                  # ErrorCode constants, exception->envelope helper
└── tests/
    ├── test_service.py
    ├── test_tool.py
    ├── test_skill.py
    ├── test_broker.py
    └── test_logging.py
```

`__init__.py` re-exports exactly the HLD §5 surface; nothing else is public.

---

## 2. `service.py`

```python
class HealthStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "degraded", "starting", "stopping"]
    version: str                       # semver of the /v1 surface
    detail: str = ""
    deps: dict[str, Literal["ok", "down", "unknown"]] = Field(default_factory=dict)

class Microservice(ABC):
    name: str                          # class attr, set by subclass
    version: str                       # class attr, semver

    @abstractmethod
    async def startup(self) -> None: ...
    @abstractmethod
    async def shutdown(self) -> None: ...
    @abstractmethod
    async def health(self) -> HealthStatus: ...

def mount(app: "FastAPI", service: Microservice) -> None:
    """
    Wire the uniform surface onto a FastAPI app WITHOUT importing FastAPI at
    module import time (lazy import inside the function — keeps edp-contracts
    dependency-light per HLD §2.2). Adds:
      - GET /v1/health           -> service.health()
      - startup/shutdown hooks   -> service.startup()/shutdown()
      - logging middleware       -> emits LogRecordModel per request
      - exception handler        -> any unhandled exc => ToolError-shaped JSON
    """
    # pseudocode:
    #   from fastapi import FastAPI            # lazy
    #   app.add_event_handler("startup", service.startup)
    #   app.add_event_handler("shutdown", service.shutdown)
    #   @app.get("/v1/health") -> (await service.health()).model_dump()
    #   app.add_middleware(_StructuredLogMiddleware, svc=service.name)
    #   app.add_exception_handler(Exception, _envelope_exception_handler)
```

Design notes:
- `mount()` lazy-imports FastAPI so `claude/` (which imports `Tool`/envelopes but is not a FastAPI app) never pays for it.
- `version` is the **HTTP-surface** semver, not the package version. Breaking `/v1` → ship `/v2`, bump.

---

## 3. `tool.py` — the load-bearing contract

```python
class ToolOk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[True] = True
    data: dict                          # the tool's OutputModel, dumped

class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[False] = False
    source: str                         # microservice name, or "tool" for local validation
    code: str                           # stable machine code (see errors.py)
    message: str                        # VERBATIM upstream text — never rewritten
    retryable: bool = False

ToolResult = ToolOk | ToolError

class Tool(ABC):
    name: str                           # class attr
    backing: Literal["python", "masked_llm"]
    idempotent: bool
    InputModel: type[BaseModel]         # class attr
    OutputModel: type[BaseModel]        # class attr

    @abstractmethod
    async def run(self, inp: BaseModel) -> ToolResult: ...

    @staticmethod
    def ok(output: BaseModel) -> ToolOk:
        return ToolOk(data=output.model_dump(mode="json"))

    @staticmethod
    def propagate(*, source: str, code: str, message: str,
                  retryable: bool = False) -> ToolError:
        """
        Construct a ToolError that preserves the upstream message byte-for-byte.
        This is the ONLY sanctioned way to surface an upstream failure.
        There is deliberately no helper that summarizes/translates a message —
        the type system + code review enforce 'never digest an error'
        (DESIGN-v4 §13.2).
        """
        return ToolError(source=source, code=code, message=message,
                         retryable=retryable)

    @staticmethod
    def from_upstream(resp: "HttpResponseLike") -> ToolError:
        """
        Adapter: take a microservice's JSON error body (already in envelope
        shape because every Microservice emits the envelope) and re-wrap
        unchanged. Asserts resp.json has {source, code, message}; if a
        microservice violates the envelope, raise EnvelopeViolation (a bug
        in that microservice, surfaced loudly — not silently digested).
        """
```

Key LLD decisions:
- `data: dict` (dumped) rather than a generic — keeps `ToolResult` a concrete union the MCP adapter can serialize without per-tool generics gymnastics. The per-tool `OutputModel` is validated *before* dumping into `data`.
- `propagate()` and `from_upstream()` are the only error constructors. No `ToolError.summarize()` exists, by design. Code review rule: a `ToolError(message=f"...{e}...")` that interpolates is a smell; only verbatim upstream text is allowed.
- `EnvelopeViolation` is a hard exception, not an envelope — a microservice that doesn't speak the envelope is a build-time/contract-test failure, not a runtime degradation.

---

## 4. `skill.py`

```python
class SkillIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    writes: list[str]                   # artifact dot-paths, e.g. "recipe.comprehension.branches"
    via: list[str]                      # record_* tool names this skill is allowed to call

class SkillHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill: str
    hosts: list[str]                    # roles allowed to invoke: neuron|planner|worker|fsm
    inputs: dict[str, str]              # arg name -> type hint (free text)
    outputs: SkillIO
    unload: str = Field(min_length=1)   # explicit self-unload instruction

class Violation(BaseModel):
    path: str
    rule: str
    detail: str

# LLD AMENDED 2026-05-16 (S3b gate, user "continue working"): 3-tuple, not
# 2-tuple. The original (header|None, body) forced re-deriving the parse
# failure reason for the R1 Violation.detail. Accepted; revertible if the
# user later objects (REFACTOR.md §4).
def parse_skill_header(
    md_text: str,
) -> tuple[SkillHeader | None, str, str]:
    """Split front-matter from body, parse the supported YAML subset.
    Returns (header|None, body, parse_error). parse_error is '' when ok."""

def validate_skill(path: str) -> list[Violation]:
    """
    Rules enforced:
      R1  front-matter present and parses as SkillHeader
      R2  every record_* / tool token used in body is declared in outputs.via
      R3  body contains a literal unload instruction matching header.unload intent
      R4  hosts ⊆ {neuron, planner, worker, fsm}
      R5  no spawn_* call in a skill whose host is 'worker' (workers don't spawn)
    Returns [] when clean.
    """
```

Note: R2 is a static scan (regex for `record_[a-z_]+(` and known tool names) — intentionally simple; false-positives are acceptable (a skill can over-declare in `via`); false-negatives (using an undeclared tool) are the dangerous case and the scan errs toward catching those.

---

## 5. `broker.py`

```python
class BrokerMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    msg_id: str                         # uuid4 str
    ts: datetime                        # tz-aware UTC
    from_: str = Field(alias="from")    # 'from' is a py keyword; alias on the wire
    to: str                             # role | relative-ref ("my-planner") | session id
    kind: str                           # must be a registered kind
    body: dict
    corr_id: str | None = None

    @model_validator(mode="after")
    def _kind_registered(self):
        if self.kind not in _REGISTRY:
            raise ValueError(f"unregistered BrokerKind {self.kind!r}; "
                             f"register via register_kind() before sending")
        return self

_REGISTRY: dict[str, str] = {}          # kind -> docstring

def register_kind(kind: str, doc: str) -> None:
    """Idempotent; re-register with same doc is a no-op; conflicting doc raises."""

CORE_KINDS = {
  "spawned":     "pool spawned a shell for a handle",
  "ready":       "a spawned shell finished init-ack",
  "done":        "a unit of work completed normally",
  "crashed":     "pool detected a shell crash",
  "question":    "child asks caller for a decision",
  "answer":      "caller answers a child's question",
  "steer":       "caller sends mid-task redirection",
  "plan_closed": "a plan reached terminal_status",
  "step_done":   "a recipe step completed",
  "consult":     "host asks a skill/helper for a verdict",
  "verdict":     "a skill/helper returns a verdict",
}
# CORE_KINDS are register_kind()'d at import time.
```

Design note: registry-not-enum (HLD §3.4) — extensible without editing this file, but `_kind_registered` makes an unregistered kind a *write-time* failure, so the protocol can't silently fork.

---

## 6. `logging.py`

```python
class LogRecordModel(BaseModel):
    model_config = ConfigDict(extra="allow")   # recommended fields are open
    ts: datetime
    svc: str
    level: Literal["debug", "info", "warning", "error"]
    kind: str
    detail: str
    # recommended (extra=allow lets these ride): trace_id, corr_id,
    # recipe_id, plan_id, session_id

def get_logger(svc: str) -> "LoggerAdapter":
    """
    Returns a stdlib-logging adapter whose .info/.warning/.error accept
    (kind: str, detail: str, **fields) and emit one JSON line conforming to
    LogRecordModel. Never writes anything that isn't LogRecordModel-shaped.
    No print() anywhere in the codebase — enforced by a ruff lint rule
    (flake8-print) configured in each repo's pyproject (documented in
    TESTPLAN as a static check).
    """
```

---

## 7. `errors.py`

Stable machine codes (the `code` field of `ToolError`). Grouped by source. This list is the canonical registry; new codes are added here with a one-line meaning.

```
# local tool / validation
TOOL_INPUT_INVALID        "input failed the tool's InputModel"
TOOL_PRECONDITION         "an instruction-shaped 'do X first' error"
# pool
POOL_CAPACITY_EXCEEDED    "max workers reached (=3)"            retryable
POOL_SPAWN_FAILED         "shell failed to start"
POOL_UNKNOWN_HANDLE       "no such recipe/plan/action handle"
# broker
BROKER_UNREGISTERED_KIND  "kind not registered"
BROKER_NO_ROUTE           "no recipient resolves for 'to'"
# fsm
FSM_UNDECIDABLE           "deterministic path punts; LLM path also abstained"
# envelope integrity
ENVELOPE_VIOLATION        "a microservice returned a non-envelope error"  (raises, not returned)
```

`TOOL_PRECONDITION` is how validators-as-instruction (audit #7) is realized: e.g. "cannot mark action done — acceptance.actual is null; call record_action_status with evidence first" comes back as `ToolError(code=TOOL_PRECONDITION, message=<the instruction>)`.

---

## 8. Versioning & change discipline

- `edp-contracts` is semver. A breaking change to any ABC/envelope is a **major** bump; consumers pin and upgrade deliberately.
- Adding a `BrokerKind` or an error `code` is a **minor** bump (additive).
- Every consumer repo pins `edp-contracts==X.Y.Z` in its pyproject. CI fails a consumer if it floats the pin.
- Changing this component after it ships requires an impact-analysis note (METHODOLOGY §5.5) listing every consumer repo.

---

## 9. The test list (full detail in `base-contracts-TESTPLAN.md`)

Unit: service (conforming/non-conforming mock), tool (ok/propagate/from_upstream/no-summarize-helper-exists), skill (R1–R5 each with a fixture), broker (round-trip, alias `from`, unregistered-kind rejected, register idempotency), logging (mandatory fields present, extra allowed, no-print lint).
Contract: a mock microservice using `mount()` exposes a spec-correct `/v1/health`; a deliberately-broken envelope triggers `ENVELOPE_VIOLATION`.

---

## 10. S2 exit gate

User confirms: **"The signatures, schemas, error codes, and versioning discipline are right. Proceed to S3 (implement edp-contracts + tests)."**

Decisions flagged for this gate:
1. `ToolOk.data: dict` (dumped) vs a generic typed envelope — LLD chose `dict` for adapter simplicity (§3). Confirm.
2. No `summarize`-style error constructor exists by design (§3). Confirm this hard stance.
3. `skill.validate_skill` is a static regex scan, deliberately simple, err-toward-catching-undeclared (§4). Confirm acceptable.
4. `edp-contracts` is semver with hard consumer pins + CI float-check (§8). Confirm.
