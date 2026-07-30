# LLD — claude/ skeleton (component #2)

**Stage:** S2 (Low-Level Design). Signatures + schemas + pseudocode + test list. **No implementation** (S3a).
**Reads from:** `claude-skeleton-HLD.md` (S1 gate closed 2026-05-17, all 6 boundaries resolved).
**Depends on:** `edp-contracts==0.1.0` (pinned).

---

## 1. Repo + module layout

```
eda-base/claude/
├── pyproject.toml                 # name="edp-claude"; deps: edp-contracts==0.1.0, pydantic>=2.6; py>=3.12
├── src/edp_claude/
│   ├── __init__.py
│   ├── schemas/
│   │   ├── recipe.py              # Recipe, RecipeStep, RecipeContext, Branch, Outcome
│   │   ├── plan.py                # Plan, Action, Acceptance, PlanContext
│   │   └── instruction.py         # Instruction, InstructionKind, RecipeState, PlanState
│   ├── store/
│   │   ├── atomic.py              # write_atomic(path, text) tmpfile+os.replace; snapshot()
│   │   ├── recipe_store.py        # load/save Recipe + snapshot + events.jsonl append
│   │   └── plan_store.py          # load/save Plan + worklog.jsonl + snapshot
│   ├── ports.py                   # PoolPort, BrokerPort, MemoryPort, FsmPort (ABCs)
│   ├── stubs/
│   │   ├── stub_pool.py           # in-proc spawn-intent recorder
│   │   ├── stub_broker.py         # in-proc inbox lists; BrokerMessage envelope
│   │   ├── file_memory.py         # recall/remember over .memory/facts.jsonl + domain kg_filter
│   │   └── stub_fsm.py            # always returns FSM_UNDECIDABLE  # TODO(edp-fsm,#5)
│   ├── fsm/
│   │   ├── recipe_fsm.py          # recipe_next_action(recipe, ports) -> Instruction
│   │   └── plan_fsm.py            # plan_next_action(plan, ports) -> Instruction
│   ├── tools/
│   │   ├── base.py                # _ClaudeTool(Tool) shared input-validate + envelope helpers
│   │   ├── next_action.py
│   │   ├── record_recipe.py  record_plan.py  record_step.py
│   │   ├── record_step_result.py  record_action_status.py  record_user_answer.py
│   │   ├── record_decision.py  record_assumption.py  record_rejected_option.py
│   │   ├── pool_spawn.py          # pool_spawn_planner, pool_spawn_worker
│   │   ├── broker_send.py
│   │   ├── memory.py              # recall, remember
│   │   └── registry.py            # REGISTRY: list[Tool]; wired into the MCP server
│   ├── domains/
│   │   ├── software_engineering/{success_criteria.py,capabilities.yaml,kg_filter.py,default_shapes.yaml}
│   │   └── generic/{success_criteria.py,capabilities.yaml,kg_filter.py,default_shapes.yaml}
│   └── server.py                  # MCP server: register REGISTRY tools
├── .claude/commands/              # neuron.md agentic-plan.md worker.md ocak.md
│   │                              # goal-keeper-check.md critic-review.md
└── tests/
```

`# TODO(revisit,#2): consolidate record_decision/assumption/rejected_option into
record_context(kind,…) once real usage frequency is known.` (user 2026-05-17)

---

## 2. Schemas (`schemas/`)

### 2.1 instruction.py

```python
class RecipeState(StrEnum):
    CREATED = "created"; COMPREHENDING = "comprehending"; PLANNING = "planning"
    EXECUTING = "executing"; REVIEWING = "reviewing"; CLOSED = "closed"

class PlanState(StrEnum):
    DRAFTED = "drafted"; DISPATCHING = "dispatching"
    ACCEPTANCE_REVIEW = "acceptance_review"; TERMINAL = "terminal"

class InstructionKind(StrEnum):
    INVOKE_SKILL = "invoke_skill"; ASK_USER = "ask_user"
    RECORD_STEP = "record_step"; SPAWN_PLANNER = "spawn_planner"
    RUN_INLINE = "run_inline"; DISPATCH_ACTION = "dispatch_action"
    RECORD_RESULT = "record_result"; REPLAN = "replan"
    ASK_NEURON = "ask_neuron"; WAIT = "wait"; DONE = "done"

class Instruction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: InstructionKind
    args: dict = Field(default_factory=dict)
    rationale: str                      # human-readable WHY (always populated)
    updates_suggested: list[dict] = []  # confirm-first patches (TODO(edp-fsm,#5))
```

### 2.2 recipe.py (DESIGN-v4 §2.1, made concrete)

```python
class Branch(BaseModel):
    id: str; question: str
    status: Literal["open","needs_user_input","resolved","deferred"]
    verdict: str | None = None; rationale: str = ""

class Outcome(BaseModel):
    id: str; description: str; verification: str
    met: bool = False

class Decision(BaseModel):    id:str; text:str; rationale:str; by:str; at:datetime
class Assumption(BaseModel):  id:str; text:str; by:str; at:datetime
class RejectedOption(BaseModel): id:str; text:str; reason:str

class RecipeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assumptions: list[Assumption] = []
    decisions: list[Decision] = []
    rejected_options: list[RejectedOption] = []
    open_questions: list[dict] = []      # {id, for_branch, question, asked_at}

class RecipeStep(BaseModel):
    step_id: str; kind: str              # FREE TEXT (user #5 prior round) — no enum
    description: str
    status: Literal["pending","in_progress","done","skipped"]
    depends_on: list[str] = []
    execution: Literal["inline","spawn_planner"]
    plan_ref: str | None = None
    outputs: list[str] = []
    rationale_for_next: str = ""

class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipe_id: str
    user_goal_verbatim: str              # never paraphrased
    user_goal_distilled: str
    domain: str                          # registry key
    state: RecipeState
    comprehension: dict                  # {branches:[Branch], expected_outcomes:[Outcome]}
    steps: list[RecipeStep] = []
    context: RecipeContext = RecipeContext()
    version: int = 1
    created_at: datetime; updated_at: datetime

    @model_validator(mode="after")
    def _clear_test_invariants(self):
        # The /clear-test guard: a recipe leaving CREATED must carry the
        # verbatim goal + domain; leaving COMPREHENDING must have no
        # `needs_user_input` branch. Enforced here so a half-built recipe
        # cannot advance (P4/P5).
        ...
```

### 2.3 plan.py (DESIGN-v4 §2.2)

```python
class Acceptance(BaseModel):
    kind: str                            # "tests_pass" | "integration_test_pass" | "manual_review" | ...
    expected: str = ""; actual: str | None = None

class Action(BaseModel):
    action_id: str; description: str
    status: Literal["pending","in_progress","done","failed","skipped","needs_review"]
    depends_on: list[str] = []
    executor_mode: Literal["inline","subagent"]
    acceptance: Acceptance
    result_ref: str | None = None; attempt: int = 0

class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str; recipe_id: str; recipe_step_id: str
    domain: str; shape: str; goal: str
    actions: list[Action] = []
    context: dict = Field(default_factory=dict)  # {carried_from_recipe, assumptions, rejected}
    terminal_status: Literal["succeeded","superseded","aborted","partial"] | None = None
    version: int = 1
```

---

## 3. Ports (`ports.py`) — the IoC seam (HLD §2)

```python
class PoolPort(ABC):
    @abstractmethod
    async def spawn_planner(self, recipe_id: str, step_id: str) -> ToolResult: ...
    @abstractmethod
    async def spawn_worker(self, plan_id: str, action_id: str) -> ToolResult: ...
    @abstractmethod
    async def liveness(self, handle: str) -> Literal["alive","dead","unknown"]: ...

class BrokerPort(ABC):
    @abstractmethod
    async def send(self, msg: BrokerMessage) -> ToolResult: ...
    @abstractmethod
    async def poll(self, recipient: str, since_ts: datetime | None) -> list[BrokerMessage]: ...

class MemoryPort(ABC):
    @abstractmethod
    async def recall(self, query: str, scope: str | None) -> list[dict]: ...
    @abstractmethod
    async def remember(self, fact: dict, domain: str) -> ToolResult: ...

class FsmPort(ABC):
    # The nuanced next_action path. Stub returns FSM_UNDECIDABLE until #5.
    @abstractmethod
    async def decide(self, handle: str, snapshot: dict, events: list[dict]) -> Instruction | ToolError: ...
```

Stub behaviours: `StubPool.spawn_*` records `(parent, child, handle)` and returns `Tool.ok(...)`; `liveness` returns `"alive"` for any recorded handle. `StubBroker` keeps `dict[recipient, list[BrokerMessage]]`. `FileMemory` appends to / scans `.memory/facts.jsonl`, applies `domains/<d>/kg_filter`. `StubFsm.decide` → `Tool.propagate(source="edp-fsm", code=ErrorCode.FSM_UNDECIDABLE, message="masked-LLM not built (component #5)")`. Swap to `Http*` in #3/#4 is a DI change in `server.py`, zero call-site edits.

---

## 4. State machine (`fsm/`) — the heart, deterministic

`recipe_next_action(recipe, ports) -> Instruction` implements DESIGN-v4 §2.1 transition table verbatim. Pseudocode:

```python
def recipe_next_action(r, ports):
    if r.state == CREATED:
        return Instruction(INVOKE_SKILL, {"skill":"ocak"}, "comprehend the goal")
    if r.state == COMPREHENDING:
        unresolved = [b for b in branches(r) if b.status == "needs_user_input"]
        if unresolved:
            return Instruction(ASK_USER, {...unresolved[0]...}, "branch needs user")
        if any(b.status not in ("resolved","deferred") for b in branches(r)):
            return Instruction(INVOKE_SKILL, {"skill":"ocak"}, "finish open branches")
        if not r.steps:
            return Instruction(INVOKE_SKILL, {"skill":"ocak"}, "derive steps")
        r.state = PLANNING; return recipe_next_action(r, ports)   # tail
    if r.state == PLANNING:
        nxt = first_ready_step(r)            # deps met, status pending
        if nxt is None:                      # all steps terminal
            r.state = REVIEWING; return recipe_next_action(r, ports)
        if nxt.execution == "inline":
            return Instruction(RUN_INLINE, {"step_id":nxt.step_id}, nxt.description)
        return Instruction(SPAWN_PLANNER, {"step_id":nxt.step_id}, nxt.description)
    if r.state == EXECUTING:
        # a spawn_planner step is out for materialization; check liveness +
        # broker for plan_closed; FsmPort consulted only when ambiguous.
        ev = ports... ; if plan_closed: mark step done; r.state=PLANNING; recurse
        if stale(step, ports.liveness): defer to ports.fsm.decide(...)  # TODO(edp-fsm,#5)
        return Instruction(WAIT, {}, "planner in progress")
    if r.state == REVIEWING:
        if all(o.met for o in outcomes(r)):
            return Instruction(INVOKE_SKILL, {"skill":"critic-review"}, "pre-close audit")
        # critic clean -> DONE; drift -> add branch, state=COMPREHENDING
        return Instruction(DONE, {...}, "all outcomes met")
    if r.state == CLOSED:
        return Instruction(DONE, {}, "recipe closed")
```

`plan_next_action(plan, ports)` mirrors DESIGN-v4 §2.2 (drafted→dispatching→acceptance_review→terminal), wave-aware: `runnable = deps-met & pending`, dispatch each via `DISPATCH_ACTION`; when all terminal → `INVOKE_SKILL(acceptance-review)`; terminal_status via `domains/<d>/success_criteria`.

All transitions pure & total; every `Instruction.rationale` non-empty. Tests in §7 assert each row of the DESIGN-v4 §2 tables.

---

## 5. Tools (`tools/`) — each a `Tool` from edp-contracts

Shared base:
```python
class _ClaudeTool(Tool):
    backing = "python"
    async def run(self, inp):
        try: model = self.InputModel.model_validate(inp)
        except ValidationError as e:
            return Tool.propagate(source="tool",
                code=ErrorCode.TOOL_INPUT_INVALID, message=_fmt(e))
        return await self._run(model)        # subclass impl
```

| Tool | backing | idempotent | In→Out | _run does |
|---|---|---|---|---|
| `next_action` | python | yes | `{handle, hint?}` → `Instruction` | load artifact; `recipe_next_action`/`plan_next_action`. **NOT read-only:** persists pure bookkeeping state advances (created→comprehending, planning→executing, …) — without that a resumed process can't progress. Idempotent *at a resting state* (the /clear-test guarantee), not across a transition. (Amended 2026-05-17 S4, accept-by-recommendation.) |
| `record_recipe` | python | no | `{recipe}` → `{version}` | validate `Recipe`; atomic write; snapshot; precondition→`ToolError(TOOL_PRECONDITION)` |
| `record_plan` | python | no | `{plan}` → `{version}` | same for `Plan` |
| `record_step` | python | no | `{recipe_id, step}` → `{step_id}` | append/update step |
| `record_step_result` | python | no | `{recipe_id, step_id, result}` | mark inline step done + evidence |
| `record_action_status` | python | no | `{plan_id, action_id, status, evidence?}` | refuse terminal w/o evidence |
| `record_user_answer` | python | no | `{branch_or_q_id, answer}` | resolve open question/branch |
| `record_decision` / `record_assumption` / `record_rejected_option` | python | no | `{handle, …}` | append to context (3 tools; TODO consolidate) |
| `pool_spawn_planner` / `pool_spawn_worker` | python | no | `{…}` | delegate to `PoolPort` |
| `broker_send` | python | no | `{to, kind, body}` | build `BrokerMessage`, `BrokerPort.send` |
| `recall` / `remember` | python | recall=yes | `{query|fact,…}` | delegate to `MemoryPort` |

Error semantics: every tool returns `ToolOk`/`ToolError` only; upstream (port) errors propagated verbatim via `Tool.from_upstream` — never digested (edp-contracts §13.2).

New error codes needed beyond edp-contracts `ErrorCode`? Expected: none — preconditions ride `TOOL_PRECONDITION` with an instruction message. **If S3a finds a genuine new code, it is an `edp-contracts` minor bump + impact note (METHODOLOGY §5.5) — flagged here, not silently added.**

---

## 6. Slash bodies + skills (`.claude/commands/`, one dir, explicit-invocation)

Six markdown files, each ≤~30 lines, each carrying the `edp-contracts` `Skill` front-matter where it is a skill (ocak/goal-keeper-check/critic-review) so `validate_skill` passes; activators (neuron/agentic-plan/worker) carry a minimal header (no `outputs.writes`). Bodies are the DESIGN-v4 §3 activator texts. `goal-keeper-check`/`critic-review` ship with `# TODO(<component>)` where they need a not-yet-built backend (user #3).

---

## 7. Test list (full TESTPLAN at S2 → `claude-skeleton-TESTPLAN.md`)

- **WALK-1 (binding S4):** the DESIGN-v4 §7 22-row trace as one integration test over stubs — assert every state/transition/instruction in order.
- **FSM unit:** every row of DESIGN-v4 §2.1 + §2.2 tables → one test each (transition + trigger + effect).
- **/clear-test:** drive to mid-recipe, drop in-memory state, reload `recipe.json` only, assert `next_action` returns the identical `Instruction`.
- **Tools:** each `record_*` — atomic write + snapshot emitted + bad input → `ToolError(TOOL_INPUT_INVALID|TOOL_PRECONDITION)` (never raises); port-backed tools propagate upstream `ToolError` verbatim.
- **Ports interchangeability:** one parametrized test over `Stub*` (and `Http*` xfail until #3/#4).
- **Skill/activator files:** `edp_contracts.validate_skill` clean on the three skills.
- **Static:** ruff incl flake8-print; `edp-contracts` pinned exactly (no float).

---

## 8. S2 exit gate

User confirms: **"schemas, state-machine pseudocode, port seams, tool surface right — proceed to S3a (implement)."** Flagged: (a) the recipe `_clear_test_invariants` validator set; (b) confirmation that no new `edp-contracts` error codes are expected (else minor bump + impact note); (c) the 3-tool record_* with the consolidation TODO.
