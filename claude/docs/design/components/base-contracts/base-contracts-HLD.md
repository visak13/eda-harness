# HLD — Base Contracts (component #1)

**Stage:** S1 (High-Level Design). No code.
**Component:** `base-contracts` — the shared interfaces every microservice, skill, and MCP tool implements.
**Why first:** DESIGN-v4 §13 makes standardization a precondition for building anything. Nothing else can be built until these exist.
**Authority:** `docs/design/METHODOLOGY.md` (stage gates), `docs/design/DESIGN-v4.md` §13 (the mandate).

---

## 1. Responsibility

`base-contracts` is a single tiny installable Python package that defines, in one place:

1. The `Microservice` abstract base + lifecycle + health model.
2. The `Tool` abstract base + the success/error envelope.
3. The `Skill` contract (metadata header schema + a validator) — skills are markdown, not classes, so their "contract" is structural.
4. The `BrokerMessage` envelope + the `BrokerKind` registry.
5. The structured-logging field contract.

It owns **no behaviour** — no broker, no pool, no FSM logic. It is types + tiny helpers + validators. Everything else in `eda-base/` depends on it; it depends on nothing in `eda-base/`.

**Out of scope for this component:** any concrete microservice, any tool implementation, any skill body. Those are later components that *import* this one.

### 1.1 Rationale — this is contract-enforcement, NOT code-reuse (recorded 2026-05-16)

ABCs/interfaces are used for two distinct reasons:

- **(A) Code reuse via inheritance** — a base class with real implementation subclasses inherit so they don't rewrite it. (The classic "reusability" meaning.)
- **(B) Contract enforcement via polymorphism** — an interface that mandates a shape: anything claiming to be an `X` *must* expose these methods/signatures. Almost no shared code; the value is that every implementation is interchangeable at a boundary and violations are caught structurally, not by convention.

**`edp-contracts` is almost entirely (B).** It exists because the old system buried errors inside tool logic (no enforced error contract), spoke ad-hoc inter-shell message dialects, and let every microservice roll its own health/lifecycle/logging — which is how it became unmaintainable. The user's directive (2026-05-16, verbatim): *"the micro-service + skills + mcp tools should all have an interface and abstract class and scale on that. the error patterns, communication protocols to be standardized."*

Consequences of this being (B), not (A):
- It is correct that `Microservice` has **zero method bodies**. An almost-empty ABC is doing the contract job, not failing the reuse job. Components build *to* it, not *from* it.
- The only deliberate sliver of (A) is `Tool.propagate()/ok()` and `mount()` — shared implementation that exists so every tool reuses the *one safe* error path instead of hand-rolling its own (hand-rolled error handling is exactly how the old system buried errors). That reuse is a standardization mechanism, not a DRY convenience.
- Construct choice is deliberate: `abc.ABC` (nominal — must inherit) for things to *enforce* (`Microservice`, `Tool`) so non-conformance fails at instantiation, not in production; `Protocol` (structural) for decoupling/test seams (`HttpResponseLike`, `LoggerLike`) where the goal is fake-injection and interface-typing, not policing a system contract.

---

## 2. Where it lives and how it is consumed

### 2.1 Key design decision — a shared package, not vendored copies

Microservices are separate repos with separate venvs (hard requirement from the user's original prompt: "shared venv collisions"). If each repo hand-copies the contracts they will drift, which defeats standardization.

**Decision:** `eda-base/edp-contracts/` is its own repo, an installable package (`edp-contracts`), single-sourced. Every other repo (`claude/`, `edp-broker/`, `edp-pool/`, `edp-fsm/`) depends on it by **pinned version** (uv path-dependency in local dev, git tag in CI). One source of truth; explicit upgrades.

Trade-off considered: a git submodule (rejected — submodules are friction-heavy and easy to desync) vs a published package (chosen — explicit version pin, normal dependency tooling, no special workflow).

This is the most consequential decision in this HLD and is flagged for the user at the S1 gate.

### 2.2 Dependency direction

```
edp-contracts  (this component — depends on: pydantic, stdlib only)
      ▲
      │ imported by
      ├──────────────┬──────────────┬───────────────┐
   claude/        edp-broker/     edp-pool/       edp-fsm/
```

`edp-contracts` must stay dependency-light (pydantic + stdlib). No FastAPI, no httpx — those belong to the microservices. Rationale: the `claude/` repo imports the contracts for the `Tool` ABC and envelopes but must start in <2 s (the old mcp-service learned this the hard way); a heavy contracts package would tax every consumer.

---

## 3. The five contracts (high-level)

### 3.1 `Microservice` ABC
Every microservice implements a uniform lifecycle and health surface so the pool/operator can manage them identically.

- `name: str`, `version: str` (semver of the `/v1` HTTP surface).
- `async startup()`, `async shutdown()`, `async health() -> HealthStatus`.
- A FastAPI mounting helper (`mount(app, service)`) that wires `/v1/health`, the structured-logging middleware, and the error-envelope exception handler so no microservice re-implements them.
- Contract: a microservice cannot be considered "done" (S3) without implementing this ABC and passing the contract-test suite.

### 3.2 `Tool` ABC + envelopes
Every MCP tool the LLM sees is a `Tool`.

- Declares `name`, `backing: "python" | "masked_llm"`, `idempotent: bool`, an `InputModel` and `OutputModel` (both Pydantic).
- `async run(inp) -> ToolOk | ToolError`.
- **Error-propagation rule (DESIGN-v4 §13.2) is enforced structurally:** `run` returns `ToolError` with the upstream message verbatim; it must not raise-and-summarize. The base class provides a `propagate(upstream_response)` helper that constructs a `ToolError` preserving the source microservice's `code` + `message` unchanged.
- The envelopes (`ToolOk`, `ToolError`) are the *only* shapes a tool may return. The MCP server adapter serializes them to the LLM.

### 3.3 `Skill` contract
Skills are markdown prompt fragments, not Python objects. Their contract is a structural one:

- A mandatory YAML front-matter header: `skill`, `hosts` (which roles may invoke), `inputs`, `outputs.writes` (which artifact fields it persists), `outputs.via` (which `record_*` tools it uses), `unload` (the self-unload discipline statement).
- A Python validator `validate_skill(path) -> list[Violation]` that checks: header present + well-formed; body only references `record_*` tools declared in `outputs.via`; an explicit unload instruction exists.
- Contract: a skill cannot ship (S3) unless `validate_skill` is clean and it is exercised by a test.

### 3.4 `BrokerMessage` envelope + `BrokerKind` registry
One message shape for all inter-shell traffic (DESIGN-v4 §13.3).

- `BrokerMessage`: `msg_id`, `ts`, `from_`, `to`, `kind`, `body: dict`, `corr_id: str | None`.
- `BrokerKind`: a registry (not a frozen enum — extensible, but every kind must be *registered* with a docstring). Core kinds at launch: `spawned`, `ready`, `done`, `crashed`, `question`, `answer`, `steer`, `plan_closed`, `step_done`, `consult`, `verdict`. New kinds are added by registering, not by ad-hoc strings — this is how the protocol stays standardized while remaining extensible (mirrors the user's "free-text recipe kinds but suggested vocabulary" instinct, applied to a protocol surface where the discipline must be tighter).

### 3.5 Structured-logging contract
One log-line schema every service emits (DESIGN-v4 carried from DATA-v2 §6).

- Mandatory fields: `ts`, `svc`, `level`, `kind`, `detail`. Recommended: `trace_id`, `corr_id`, `recipe_id`, `plan_id`, `session_id`.
- A `get_logger(svc)` helper returns a logger pre-wired to emit this schema as JSON. Never `print()`.

---

## 4. Failure modes this component must prevent

| Failure (from the audit) | How the contract prevents it |
|---|---|
| Audit #1 / P1 — operational complexity leaks to LLM | `Tool` ABC keeps every tool's surface to InputModel→OutputModel; no protocol prose can hide in a tool. |
| Audit #7 — validators ambush the LLM | `ToolError` envelope: validation failures become structured, instruction-shaped errors, never raw stack traces. |
| Audit #12 — mixed comms paradigms | Single `BrokerMessage` envelope; no component invents its own message shape. |
| Audit #13 — deployment coupling | `Microservice` ABC + versioned `/v1` surface + health model make independent restart + contract-testing uniform. |
| Audit #6 — logging not visualizable | One structured-logging schema makes the future trace-viewer possible without per-service special-casing. |
| Prior-system error-burying (user 2026-05-16) | `Tool.propagate()` preserves upstream `code`+`message` verbatim by construction; a tool *cannot* silently digest an error and still satisfy the type. |

---

## 5. Public interface summary (the ABCs other components code against)

- `from edp_contracts import Microservice, HealthStatus`
- `from edp_contracts import Tool, ToolOk, ToolError`
- `from edp_contracts import BrokerMessage, BrokerKind, register_kind`
- `from edp_contracts import validate_skill, SkillHeader`
- `from edp_contracts import get_logger`

The exact signatures are LLD (S2). This HLD fixes only the shape and the boundaries.

---

## 6. Contract tests this component must pass (defined fully in TESTPLAN at S2)

High-level: the package must prove (a) a conforming mock microservice passes `Microservice` validation; (b) a non-conforming one fails with a clear message; (c) `Tool.propagate()` preserves upstream message byte-for-byte; (d) `validate_skill` catches a missing header / undeclared `record_*` reference / missing unload; (e) `BrokerMessage` round-trips JSON; (f) an unregistered `BrokerKind` is rejected; (g) `get_logger` emits all mandatory fields.

---

## 7. S1 exit gate

User confirms: **"The base-contracts boundaries + the shared-package decision (§2.1) are right. Proceed to LLD."**

Open points explicitly flagged for the gate:
1. **Shared package vs alternative** (§2.1) — agree `edp-contracts` as its own pinned-version repo?
2. **`BrokerKind` as registry-not-enum** (§3.4) — agree extensible-but-registered?
3. **Contracts package stays pydantic+stdlib only** (§2.2) — agree the weight constraint?
