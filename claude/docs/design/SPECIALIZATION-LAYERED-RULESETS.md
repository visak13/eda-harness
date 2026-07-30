# Layered specialization rulesets + deterministic snippet serving (2026-06-01)

**Status:** agreed (user sign-off 2026-06-01). Implementation staged below.
**Builds on:** `philosophy/specialization-neurons-vision.md` (the neuron DB +
`specialization_recipe` of links), `OBJECT-MODEL.md` (the `spec` object),
and the eda-designs *deterministic-MCP-server blueprint* (CORE/CUSTOM
additive layering, serve-don't-generate, cross-cutting scoped to one axis).

## Problem

Today a `Specialization` is a flat `list[SpecEntry]` where each entry is
`{kind, text, note}` and `kind ∈ {step, link, checklist, anti_pattern,
preference, work_order}`. Three gaps:

1. **No adherence strength.** Every entry is equal-weight prose. Nothing
   says "Spring layering is non-negotiable" vs "this is a style lean."
2. **No role-typing of links.** `kind="link"` is undifferentiated — a
   *ruleset you must obey*, a *checklist*, a *design guideline*, and a
   *reference you may skim* are all the same `link`.
3. **No universal layer and no MCP binding.** A top-level "every worker
   follows SOLID / logging / tests" doc has nowhere to attach, and
   nothing tells a worker to *fetch a deterministic snippet* from an MCP
   server instead of generating code.

## The thesis (blueprint, one level up)

The eda-designs blueprint serves **deterministic primitives**, pushes
**composition outside** via a documented contract, layers **CORE/CUSTOM
additively**, and scopes **cross-cutting concerns to one axis**. We apply
the same shape to the worker/specialization system:

| Blueprint | Worker system |
|---|---|
| Deterministic primitive (served, not generated) | **MCP snippet** handed to the worker — the snippet *is* the few-shot |
| CORE (plain, canonical, everyone gets it) | **Universal coding standards** — OOP, SOLID, logging, tests, no-regex |
| CUSTOM = `core ⊕ delta`, additive, never edits core | **Tech specialization** — Spring/React rules *extend* universal |
| Cross-cutting scoped to one axis (§4.4) | **Security/OWASP** as one composable layer, pulled per action |
| ASSEMBLE recipe (consumer composes, fixed order) | Worker assembles its effective ruleset at branch time |

Worker behavior is an orthogonal composition:

```
WORKER_BEHAVIOR = UNIVERSAL ⊗ CROSS_CUTTING(security…) ⊗ TECH(Spring|React…) ⊗ MCP_SNIPPETS
```

## Decision 1 — rules are enforced at VERIFY, not as upfront coder constraints

The FSM already flows `pending → in_progress → verify → done`. The coding
worker builds; a **verify worker checks-and-fixes**. The *same* spec is
read by two roles for two purposes — **do not overload the coder**:

```
       ┌──────────────── the ONE specialization (authored knowledge) ────────────────┐
   CODER worker → CONSTRUCTIVE view              VERIFY worker → ENFORCED view
   · work_order / steps                          · checklists
   · design guidelines                           · required/expected rules + adherence
   · anti-patterns                               · the MCP *checking* tools (SAST, Playwright)
   · MCP *snippet* bindings (fetch, don't gen)   · "meets the standard? fix the gap"
   → builds the logic, free to think             → enforces standards, blocks/fixes
```

Rationale: determinism comes from **handing the coder a working base**
(the snippet), not from piling on constraints. Too many upfront rules and
Claude Code stops thinking out-of-box and just does as told. The standards
are enforced *downstream* by a worker whose whole job is to check. **We do
NOT auto-compile must-rules into coder-side gates.** (Supersedes the
earlier "compile must into the coder's verify block" idea.)

**The verify worker FLAGS; it does not itself patch code.** The existing
`reviewer.md` is review-only by design (a coder fork does the fixing). So
"checks-and-fixes" is realized by the *step*, not one shell: the reviewer
flags each gap by adherence, a `required` gap blocks `done` and **routes a
coder re-dispatch** to close it, then it is re-verified. This keeps the
review/fix separation the architecture already has — "use the system,
don't force one worker to do everything."

## Decision 2 — adherence taxonomy defined by verify-worker BEHAVIOR

Vague modality (`must/should/advisory`) gets discarded by the LLM. Each
level instead names a concrete verify action, defined in the spec doc so
it carries weight by definition:

| `adherence` | Verify worker behavior | Example |
|---|---|---|
| **`required`** | **Blocks `done`.** Must hold or the verify worker fixes it / fails the action. | logging on failure paths; tests exist for logical components; controller carries no business logic |
| **`expected`** | **Checks and fixes** if the gap is clear; a *justified, recorded* exception is allowed; does not hard-block. | short methods; naming conventions |
| **`preferred`** | The **coder's house-style default**; verify only *notes* a deviation, never blocks. | "prefer composition here" |

`required` vs `expected` = **"blocks done"** vs **"fixed if clear,
exception allowed."** `preferred` survives because it's the coder's
*default*, not "optional."

## Decision 3 — two layering mechanisms (do not conflate)

**(a) Static `extends` — the spec author's declaration (tech → universal).**
`Specialization.extends: list[str]` (spec_ids). Default `["spec-universal"]`.
A leaf may extend a family base:

```
spec-universal ◀─extends─ spec-java ◀─extends─ spec-spring-boot
   (CORE)                   (family)             (leaf neuron)
```

Resolution is fixed + additive, universal first, most-specific last
(blueprint's fixed emit order): `universal → java → spring-boot`. A later
layer **adds** but never **deletes/redefines** an earlier rule — the
"custom never edits core" law, applied to rulesets. Cycles are rejected at
write time; a missing parent is an instruction-shaped error, not a crash.

**(b) Dynamic per-action `concerns` — the planner's call (cross-cutting).**
Security / a11y / perf are *orthogonal to tech* (not every Spring action
is security-critical). They are NOT in `extends`. The planner tags the
**action**: `concerns: ["security"]` when it touches auth / user input /
external data. The worker assembles:

```
WORKER RULESET = spec-universal           (always)
               ⊕ tech extends-chain        (static, from the spec)
               ⊕ action.concerns           (dynamic, planner-tagged per action)
```

## Decision 4 — cross-cutting non-leak (capability + fill)

`spec-security` exists **exactly once** (OWASP links, checklist, required
rules, the scanner MCP tool). It is **never** pasted into a tech spec.
The action exposes an empty `concerns` slot; the **planner is the one
axis** allowed to fill it, only on in-scope actions. A non-tagged action
(e.g. pure layout) has security *structurally absent* → it cannot leak.
A security-tagged action's verify step is a **security-reviewer** worker
running the OWASP checklist + scanner.

## Decision 5 — verification is itself specialized

The verify step forks the **reviewer that matches the action's tech +
concerns** (reuses `branch_reviewer` / `reviewer.md`): a Spring action →
Spring-reviewer; a security-tagged action → security-reviewer. Not one
generic verifier. The reviewer reads the ENFORCED view of the assembled
ruleset.

## Decision 6 — universal home + global MCP availability

"Universal" means two separate things, both real:

1. **Universal coding standards** → `docs/guides/coding-standards.md`
   (human-authored, the **seed** list, refined on iterative learning) +
   a `spec-universal` DB row created by an `ensure_universal()` floor
   (mirrors `ensure_orchestrator`) whose entries link the doc and carry
   adherence levels. The doc is the readable source; the spec is the
   versioned, composable handle every worker starts from.
2. **Universal MCP availability** → a **global plugin registry**, always
   discoverable/installed. Workers do not install per-task; plugins are
   already there. The spec only declares *which* server to prefer for
   *which* subtask.

## Decision 7 — MCP bindings: two kinds, both global, install is gated

| Kind | Bound in | Example | Use |
|---|---|---|---|
| **Snippet / determinism server** | the **tech spec** | eda-designs (React/Tailwind → Java, Angular) | "for a React component, *fetch* the snippet, don't generate" |
| **Tool server** | the **concern / work-type** | Playwright (testing), a SAST (security) | "to verify behavior, drive Playwright" |

Both are globally available; the binding declares *prefer X for subtask Y;
fallback to generate-per-rules if X can't serve it.* **Installation** is
rare: training discovers a capability gap *not already global* → proposes
it → **user approves** (global install is outward-facing → always gated)
→ it joins the registry → the spec binds it. eda-designs is in-domain;
Playwright-for-tests is the out-of-domain example.

## Schema changes (all additive — defaults keep existing data valid)

```
SpecEntry      + adherence: required | expected | preferred   (default: expected)
               + link_role: ruleset | checklist | guideline | reference | mcp_binding | null
Specialization + extends: list[str]                           (default: ["spec-universal"])
Action         + concerns: list[str]                          (default: [])
```

`kind` is NOT overloaded (Decision: add fields, per sign-off). Old entries
load unchanged: `adherence` defaults to `expected`, `link_role` to null,
`extends` to the universal parent, `concerns` to empty.

## The whole picture

```
        docs/guides/coding-standards.md  (seed, refined over time)
                     │ linked by
                     ▼
              spec-universal ─extends◀─ spec-java ─extends◀─ spec-spring-boot
              (CORE, adherence)            (family)            (leaf neuron)
                     │ ALWAYS                  static extends-chain │
                     ▼                                              ▼
            ┌──────────────  ASSEMBLE at the action  ──────────────┐
            │  universal ⊕ extends-chain ⊕ action.concerns([security?])
            └───────────┬───────────────────────────┬─────────────┘
               CONSTRUCTIVE view              ENFORCED view
               → CODER worker                 → VERIFY reviewer fork
               (snippets, work-order;          (checklists, required/expected;
                free to think)                  SAST/Playwright MCP; fixes)
                        │                               │
           global MCP registry (snippet servers + tool servers, always available)
```

## Staged implementation

1. **Schema (additive) + tests** — the four fields above; prove old
   entries load and new fields default. No behavior change yet.
2. **`spec-universal` floor + `coding-standards.md` seed** —
   `ensure_universal()` idempotent; seed the eight standards as entries
   with adherence levels linking the doc.
3. **Assemble resolution** — `get_specialization` (or a new
   `assemble_ruleset`) resolves `extends`-chain + action `concerns` into
   an ordered, deduped ruleset, split into CONSTRUCTIVE vs ENFORCED views;
   reject cycles + missing parents with instruction-shaped errors.
4. **Briefs + training** — `specialist.md` (enriched entries + adherence
   + MCP binding + gated install), `worker.md` (CONSTRUCTIVE view +
   snippet-fetch), `reviewer.md` (ENFORCED view + adherence behaviors),
   planner author guide (tag `action.concerns`; fork matching reviewer at
   verify).

## Acceptance checklist ("the layering is correct")

Status as of 2026-06-01 — Stages 1–4 landed (316 tests green, ruff clean).

- [x] Old specializations (flat entries, no `extends`) load and assemble
      unchanged, gaining only `spec-universal` as the implicit parent.
      (`test_legacy_*`)
- [x] `extends` resolves universal-first, most-specific-last; additivity
      is **structural** — each layer is a separate spec file, so a tech
      spec cannot edit `spec-universal` (no cross-layer delete path to
      police). (`test_extends_chain_*`, `test_additive_union_*`)
- [x] A cycle or missing parent in `extends`/`concerns` is refused with an
      instruction-shaped error, not crashed. (`test_cycle_is_refused`,
      `test_missing_parent_is_refused_not_partial`)
- [x] A concern (`spec-security`) is reached only via an action's
      `concerns`; it is never pasted into a tech spec (specialist brief
      forbids it). (`test_concern_chain_appends_after_tech`,
      `test_specialist_authors_*`)
- [x] `ensure_universal()` is idempotent (cold-start floor); the seed
      standards carry adherence levels and link the doc.
      (`test_ensure_universal_*`, `test_universal_spec_is_root_*`)
- [x] The assembled ruleset splits cleanly into CONSTRUCTIVE (coder) and
      ENFORCED (verify) views + `mcp_bindings`.
      (`test_split_into_constructive_enforced_*`)
- [x] No coder-side hard gate is auto-generated from must-rules; the coder
      uses the constructive view + snippet fetch, the reviewer enforces.
      (`test_worker_uses_constructive_view_*`,
      `test_reviewer_enforces_layered_ruleset_by_adherence`)

## Follow-up tasks (2026-06-01)

- [x] **(a) Stale-spec cleanup.** A 2026-05-30 reset wiped the neuron
      registry but left six domain spec files from a prior project (none
      branchable — no `base_session_id`). `scripts/archive_stale_specs.py`
      reversibly moved them to `.specs/.archived/` and archived the one
      lingering `trained` neuron row. The active set is now just the
      comprehension seeds + orchestrator (+ universal on first floor).
- [x] **(b) Concern-matched reviewer dispatch.** `branch_reviewer` now
      takes + forwards `concerns`, so the reviewer `assemble_ruleset`s the
      full layered ruleset (universal + tech + concerns) and enforces all
      of it. neuron-phase-e passes the plan's concerns and prefers a
      concern-matched specialist (e.g. a security reviewer) when one
      exists, falling back to the tech reviewer enforcing the rules when
      not. (`test_branch_reviewer_forwards_concerns`,
      `test_phase_e_passes_concerns_and_prefers_matched_reviewer`)
- [ ] **(c) First live specialist** — the user trains one (React/Java) to
      prove the train → approve → branch → assemble loop end-to-end.
- [x] **(d) MCP registry — DESCOPED (intentionally external).**

## Not yet wired (next increments)

- **DESCOPED — the global MCP plugin registry is intentionally external.**
  The local snippet server (eda-designs) is developed/improved outside this
  shell; marketplace servers are installed separately by the user. So a
  binding simply *names* an assumed-present server (Stage 4) — there is no
  registry to build here. Training surfaces a needed-but-absent server to
  the user for a gated install; it never installs silently.
