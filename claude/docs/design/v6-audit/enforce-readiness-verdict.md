# EDP_ROLE_SCOPE enforce-readiness verdict

> ## Disposition by action a4 (s25, 2026-07-10)
>
> a4 landed a1's **SAFE TO LAND NOW** list and touched nothing on **MUST NOT be
> attempted**. `EDP_ROLE_SCOPE` is still `warn` in every source, script and pool
> env. **The verdict below stands: NOT READY.**
>
> | Blocker | State after a4 |
> |---|---|
> | 1. Warn-mode logging blind for bare handles (**CRITICAL**) | **CLOSED.** `_role_scope_worklog_plan_id` → `_role_scope_worklog_key`; a bare-handle role now logs under a handle-keyed trail instead of being dropped, and every event carries `handle`. All six blind roles are tested. |
> | 2. `enforce` logs nothing / never explains itself | **OPEN — deliberately.** On a1's MUST-NOT list (changes the registered MCP surface; needs its own step + a stack restart). |
> | 3. Seven guide↔toolset gaps | **CLOSED, all seven.** Five by derived-floor grants, two by guide fixes. See the disposition note in `KNOWN_GUIDE_TOOLSET_GAPS`, which is now **empty**. |
> | 4. Three-role fail-open over-grant | **CLOSED.** `curiosity` / `goal_keeper` / `pattern_observer` have read-only `ROLE_TOOLSETS` + `CRUD_OBJECT_SCOPE` rows, keyed by the underscore strings, with a source-derived test over `http_pool.py`. |
> | 5. The d17 gate's corpus is too narrow | **CLOSED.** `_role_docs` now walks `get_guide` transitively (without descending into shared reference docs) plus an explicit `EXTRA_ROLE_GUIDES` declaration. The **eighth gap** (`specialist-training.md:31`) is now visible and dispositioned. |
> | 6. `## CURIOSITY` doc/code mismatch + hyphen/underscore trap | **CLOSED.** Code gained the three rows; the derived doc is reconciled; the trap is pinned by a mutation-proved test. |
> | 7. Derived doc names five unregistered tools | **OPEN, documented.** Confirmed still true, and `pattern_observer_analyze` is a **sixth**. Recorded in the doc as a transcription landmine; `build_mcp` still fails closed. |
> | 8. Gate has no object-type dimension | **OPEN.** Latent; not in scope. |
>
> **Correction to a1, on the record.** a1's SAFE item 2 proposed granting the
> planner `broker_send` (32→35) on the `roles.py:73-89` precedent. That precedent
> is conditional on its own test — *the grant must confer no new reach* — and
> `broker_send` fails it: it takes an arbitrary `to=`, where the planner's
> `reply`/`notify_above`/`ask_above`/`emit_recipe_event` are lineage-scoped. All
> three of its call sites addressed the planner's **parent**, and a planner's
> parent *is* the `<recipe_id>`; `plan_closed` and `question` are both in
> `CORE_KINDS`, and `NotifyAbove` sends `to=parent` with an arbitrary kind. The
> **guides were fixed** to `notify_above(kind="plan_closed", …)` and
> `ask_above(audience="neuron")` instead. Planner floor: **32→34**
> (`status_ping` + `neuron_search` only). Adjudicated by the planner after a2
> raised the objection independently.
>
> **a1's own acceptance criterion was vacuous and a1 said so. So is a4's.**
> a4's gate is `uv run pytest -q` — a genuine regression bar, but it is *not*
> evidence that these fixes are correct: it passes just as well with the corpus
> narrowed or the matcher weakened. The criterion that actually guards this work
> is the **mutation battery**, recorded verbatim in a4's `record_action_status`
> evidence: each new assertion was watched RED for the right reason and GREEN on
> revert. Two mutations did **not** go red, and that negative result is reported
> rather than hidden.

**Verdict: NOT READY.** Flipping `EDP_ROLE_SCOPE=warn → enforce` today would
break at least three roles at their prescribed happy path, and — worse — the
warn-mode evidence being used to justify the flip is structurally incapable of
seeing four of the six scoped roles.

Audited 2026-07-10 by worker `…-s25:a1` (action B3 / d60). Diagnosis only: **no
behaviour was changed and `EDP_ROLE_SCOPE` was not flipped anywhere in the
tree.** Every claim below was re-derived from live source; nothing was carried
forward from the brief on trust. Findings are tagged **VERIFIED** (executed or
read in the live tree) or **INFERRED** (reasoned, not executed).

Baseline confirmed: `EDP_ROLE_SCOPE` is read in exactly two places
(`mcp_server.py:145`, `_tools.py:7605`), both defaulting to `"warn"`, and is set
to `enforce` in **no** source, script, or pool env — `edp-pool` never stamps it
at all, so every spawned shell inherits the warn default. (VERIFIED)

---

## The one-sentence reason

The flip's gating criterion (d14/d15: "a zero-violation recipe") is **unsound as
implemented**: `record_role_scope_violation` silently drops the event for every
role whose `EDP_HANDLE` has no colon — reviewer, specialist, consult, curiosity,
goal-keeper, pattern-observer — so "zero violations" from those roles is
indistinguishable from "never instrumented". Four of the seven known gaps live
in exactly those blind roles.

---

## BLOCKER LIST

### 1. Warn-mode violation logging is blind for every bare-handle role — the flip gate measures nothing (**CRITICAL**) — VERIFIED

`_role_scope_worklog_plan_id()` (`src/edp_claude/tools/_tools.py:7581-7592`)
returns `me` for a planner and `parent` for everyone else. `parent` comes from
`_self_and_parent_addresses()` (`_tools.py:4630-4655`), which returns
`(handle, None)` when the handle contains no `:` (`_tools.py:4647-4649`).
`record_role_scope_violation` then hits `if pid:` (`_tools.py:7607`) and writes
nothing.

Every non-planner, non-worker role is spawned with a **bare** handle:

| role | handle built at | form | colon? |
|---|---|---|---|
| planner | `clients/http_pool.py:75` | `<recipe_id>:<step_id>` | yes |
| worker | `clients/http_pool.py:91` | `<plan_id>:<action_id>` | yes |
| reviewer | `_tools.py:7078` | `review-<neuron_id>-<hex8>` | **no** |
| specialist | `_tools.py:6373`, `:6447` | `specialist-<slug>-<hex8>` | **no** |
| consult | `_tools.py:5222` | `consult-<hex8>` | **no** |
| curiosity | `_tools.py:5334` | `curiosity-<hex8>` | **no** |
| goal_keeper | `_tools.py:5410` | `<recipe_id>-goalkeeper-<hex8>` | **no** |
| pattern_observer | `_tools.py:5465` | `patterns-observer-<hex8>` | **no** |

Executed against the live `record_role_scope_violation` with a real context:

```
role=worker      handle=plan-X:a1                 mode=warn -> LOGGED
role=planner     handle=recipe-Y:s3               mode=warn -> LOGGED
role=reviewer    handle=review-neuron-java-abc123 mode=warn -> NOT LOGGED (silently dropped)
role=specialist  handle=specialist-java-abc123    mode=warn -> NOT LOGGED (silently dropped)
role=consult     handle=consult-abc123            mode=warn -> NOT LOGGED (silently dropped)
```

**Mutation check (B5 discipline).** Handing the *same* reviewer a colon handle
`plan-Z:review-1` makes the write appear (1 worklog line in `plan-Z`). The drop
is caused by the bare handle, not by test scaffolding. The claim is falsifiable
and it failed to be falsified.

**Consequence.** `.plans/*/worklog.jsonl` contains `role_scope_violation` events
for `agent_role: planner` only (the one live corpus, from the scratch recipe and
s24/s25). No reviewer or specialist violation can ever have been recorded — and
gaps 4–7 below are reviewer and specialist gaps. The empirical case for
readiness has a hole shaped exactly like the remaining defects.

**Remediation.** Give `_role_scope_worklog_plan_id()` a fallback for bare
handles (the lineage recipe's worklog, or a recipe-level `role_scope_violation`
event) *before* any flip, then re-run a full recipe in warn to collect real
evidence from all six roles. Do **not** treat today's silence as data.

### 2. `enforce` mode logs nothing and never explains itself (**HIGH**) — VERIFIED

In `mcp_server.py:159-164`, `enforce` **filters** the registry and leaves
`off_scope_names` empty. The warn-mode shim at `:186,193-194` is what writes the
violation, so under enforce it never fires. The off-set tool is simply *absent*
from the MCP surface: the agent gets an "unknown tool" error from its client,
not the `_precondition("role-scope refused: …")` refuse-and-explain that
`_guard_object_crud` (`_tools.py:7635-7637`) produces for the CRUD dimension.

Executed:

```
EDP_ROLE_SCOPE=warn     surface= 86 tools   off_scope_shims_that_log=64
EDP_ROLE_SCOPE=enforce  surface= 22 tools   off_scope_shims_that_log=0
```

So the moment you flip, you lose the telemetry that would tell you what the flip
broke, and shells fail with a confusing error instead of a named refusal. The
two dimensions of the same policy behave inconsistently: off-**object-type** is
refused with an explanation and logged; off-**tool** is invisible.

**Remediation.** Under enforce, keep a shim registered for off-set tools that
refuses with `_precondition` naming the role and the verb, and logs the
violation — same shape as `_guard_object_crud`. Filtering the tool away entirely
should be a later, separately-gated hardening, not the first step.

### 3. Seven guide↔toolset gaps, all still open (**HIGH**) — VERIFIED

`tests/test_w4_roles.py:493-526` (`KNOWN_GUIDE_TOOLSET_GAPS`) is a6's table. I
re-derived it mechanically against the live guides and `ROLE_TOOLSETS`, and
**all seven reproduce, byte for byte, with no new entries inside the gate's own
corpus**:

| # | role | verb | instructed at | absent from |
|---|---|---|---|---|
| 3.1 | planner | `broker_send` | `docs/guides/planner-phase-drive.md:56,109` | `roles.py:68-111` |
| 3.2 | planner | `neuron_search` | `docs/guides/planner-phase-drive.md:29` | `roles.py:68-111` |
| 3.3 | planner | `status_ping` | `docs/guides/planner-phase-drive.md:174` | `roles.py:68-111` |
| 3.4 | reviewer | `get_specialist_doc` | `.claude/commands/reviewer.md:62` | `roles.py:116-124` |
| 3.5 | reviewer | `propose_spec_learning` | `.claude/commands/reviewer.md:141` | `roles.py:116-124` |
| 3.6 | specialist | `neuron_set_base_session` | `.claude/commands/specialist.md:137` | `roles.py:128-140` |
| 3.7 | specialist | `neuron_set_status` | `.claude/commands/specialist.md:294,303` | `roles.py:128-140` |

Severity ordering within this blocker: **3.1 is the severe one** — under enforce
a planner cannot execute the close sequence its own guide prescribes
(`planner-phase-drive.md:56` sends `plan_closed`). The disk-reconcile backstop
means the recipe degrades rather than wedges, but the contract is broken. 3.3 is
next: `reconcile`'s own `wait_reason` tells the planner to run `status_ping`, so
the framework would instruct a call the framework then refuses. 3.4 is probably
a **guide** bug, not a toolset bug — `get_specialist_docs` (plural) is in the
reviewer surface and is a pass-through for N=1.

**On the "how many instances of the class" question.** The steer frames
`get_recipe_digest` + `status_ping` as "two instances". Ground beats brief: the
class has **eight** known members — the seven above plus `get_recipe_digest`,
which is already fixed. Three are now *live-confirmed*, not static:
`get_recipe_digest` (s23 planner), `status_ping` (s24 and s25 planners), and
`broker_send` (s24 planner at close, plus the a10 scratch planner, d59). So yes:
**a third live-confirmed instance exists, and it is `broker_send`.**

### 4. The three-role fail-open over-grant (**HIGH**) — VERIFIED

`toolset_for_role()` (`roles.py:181-187`) returns `None` for an unknown role and
`build_mcp` (`mcp_server.py:143-147`) then registers the **full 86-tool
registry** — in *both* warn and enforce. `crud_scope_violation()`
(`roles.py:230-232`) fails open the same way.

`ROLE_TOOLSETS` keys (`roles.py:171-178`) are exactly
`{worker, planner, reviewer, specialist, consult, neuron}`.

The pool stamps `EDP_ROLE` from the string the client sends
(`edp-pool/src/edp_pool/pty_launcher.py:400`), and `clients/http_pool.py` sends
three role strings that are **absent** from that table:

| `EDP_ROLE` stamped | sent at | `toolset_for_role` | `CRUD_OBJECT_SCOPE` |
|---|---|---|---|
| `curiosity` | `http_pool.py:116` | `None` | `None` |
| `goal_keeper` | `http_pool.py:99` | `None` | `None` |
| `pattern_observer` | `http_pool.py:107` | `None` | `None` |

**Blast radius under enforce.** These three shells keep *every* tool, including
`close_recipe`, `suspend_recipe`, `resume_recipe`, `delete_object`,
`pool_spawn_planner`, `record_recipe`, and the `SPECIALIST_ONLY` authoring
verbs — while the six named roles get locked down. Their own command files call
only 5–6 read-only verbs each (`curiosity.md`: `check_inbox`, `get_guide`,
`notify_above`, `observe`, `read_object`, `reply`; `goal-keeper.md`:
`check_inbox`, `read_object`, `reply`; `pattern-observer.md`: those plus
`query_objects`, `recall`). So the over-grant is ~80 tools wide and entirely
unnecessary. It is an over-**grant**, not a break: nothing fails, which is
precisely why it is invisible.

Note the enforce flip makes this *worse in relative terms* — it is the moment
the framework starts claiming that role scope is enforced, while three roles are
exempt.

### 5. The d17 gate's corpus is narrower than "a role's own guides" (**MEDIUM**) — VERIFIED

`test_w4_roles.py:658` (`test_every_tool_a_roles_own_guides_instruct_it_to_call_is_in_its_toolset`)
is a real, mutation-proved gate — but `_role_docs()` (`test_w4_roles.py:587-595`)
defines a role's corpus as *its command file plus the non-shared guides that
command file loads via `get_guide(...)` in one hop*. Measured against the tree:

- **`reviewer.md`, `specialist.md`, and `consult.md` call `get_guide` zero
  times.** Their corpus is one file each. Anything in `docs/guides/` that governs
  them is unscanned.
- The walk is **one hop**. Guides loaded *by guides* are never attributed to a
  role. `environment-discovery.md` is reached only via
  `architecture-vocabulary.md:220`, so it is never scanned — and it instructs
  the planner to call `status_ping('<plan_id>:<action_id>')` (`:20`) and
  `broker_send(to=…, from_=<your dash plan_id>)` (`:51`). Both are gaps 3.3 and
  3.1 restated in a document the gate cannot see.
- Eleven guides are reachable from **no** command file at all:
  `framework-ocak.md`, `verification-craft.md`, `specialist-training.md`, and the
  eight `specialist-*.md` compiled docs.

**The one new instance this uncovers.** `docs/guides/specialist-training.md:31`
tells the specialist that `add_spec_entry` and `update_object(type="spec")`
"only APPEND". `update_object` is absent from `_SPECIALIST` (`roles.py:128-140`),
so under enforce a specialist following its own training guide is refused. This
is a **new, previously unreported member of the class** — found only because the
sweep ignored the gate's corpus rule. (The CRUD dimension is moot here: the verb
is filtered away before `_guard_object_crud` can refuse the object-type.)

I checked the obvious next question and the answer is *no*: broadening the
corpus to the shared guides does **not** yield more real findings. The
call-form heuristic fires on `architecture-vocabulary.md:144,193` and
`reactive-streams.md:191,212,215`, but every one of those is **descriptive
prose** in a role-neutral reference doc (`supersede_decision(...)` explaining
that decisions are archived; `update_object("action", patch={"status":"done"})`
explaining the FSM), not an instruction to a role. Excluding shared guides is a
defensible rule. **Reporting a negative honestly: within the gate's declared
corpus there is no eighth static gap; the eighth gap exists because the corpus
rule is wrong, not because the table is stale.**

### 6. `## CURIOSITY` doc/code mismatch, and the hyphen/underscore key trap (**MEDIUM**) — VERIFIED

`docs/design/v6-audit/role-toolsets-derived.md:52-62` carries a `## CURIOSITY`
section and a `## GOAL-KEEPER / PATTERN-OBSERVER` section. Neither has a
`ROLE_TOOLSETS` entry.

**Which is authoritative: the doc.** The doc is a *derived* snapshot of the
contract sources (its own line 5), the roles genuinely exist, the pool genuinely
spawns them, and `pty_launcher.py:289-303` maps them to real activator commands
(`/curiosity`, `/goal-keeper`, `/pattern-observer`) whose command files exist on
disk. The code is simply incomplete. The doc is right; `roles.py` is missing
three rows.

**The trap, stated precisely.** The doc heads these roles with **hyphens**
(`GOAL-KEEPER / PATTERN-OBSERVER`) and the activator commands use hyphens
(`/goal-keeper`), but `EDP_ROLE` is stamped with **underscores**
(`goal_keeper`, `pattern_observer` — `http_pool.py:99,107`). A `ROLE_TOOLSETS`
entry keyed `"goal-keeper"` would never match, `toolset_for_role` would keep
returning `None`, and the fix would *silently do nothing* while looking landed.
The correct key is the underscore form, and it must be taken from
`http_pool.py`, not from the doc heading or the command filename.

**Correct reconciliation** (recommended, not landed here): add three read-only
rows to `ROLE_TOOLSETS` keyed `curiosity` / `goal_keeper` / `pattern_observer`,
each the union of the verbs its command file actually calls, plus three
`CRUD_OBJECT_SCOPE` rows of `frozenset()`; and add a test that asserts
`set(ROLE_TOOLSETS) ⊇ {every role string `clients/http_pool.py` sends}`, derived
from the source, so the next role added to the pool cannot fail open.

### 7. `role-toolsets-derived.md` names five tools that are not registered (**MEDIUM, landmine**) — VERIFIED

`build_mcp` fails **closed** on drift (`mcp_server.py:150-158`): any name in a
role's frozenset that is not a registered tool raises `RuntimeError` and the
server refuses to start. Today every one of the six toolsets is clean (0 names
missing from the 86-tool registry — VERIFIED).

But the derived doc's floors name `ensure_orchestrator`, `pattern_observer_analyze`,
`append_revision`, `invoke_skill`, and `branch_specialist` — **none of which are
registered tools**. Transcribing the doc's floor into `roles.py` verbatim (the
obvious way to "close the gaps") would take the MCP server down at startup for
every shell. The fail-closed guard is working as designed; this is a warning for
whoever lands the fix, not a defect in the guard.

### 8. The gate has no object-type dimension (**LOW**) — INFERRED

`test_w4_roles.py` checks guide-instructed *verbs* against `ROLE_TOOLSETS`.
Nothing checks guide-instructed *object types* against `CRUD_OBJECT_SCOPE`. A
guide could instruct `update_object(type='recipe')` at a planner (allowed:
`plan`, `action` only — `roles.py:209`) and no test would notice; it would
surface as a runtime `_precondition` refusal after the flip. I found no live
instance of this today, so it is a latent hole, not an open defect.

---

## SAFE TO LAND NOW (scope for action a4)

Land these; they are additive, individually testable, and none of them changes
runtime behaviour under `warn`:

1. **Fix the corpus of the existing gate, don't build a new one.** The
   class-guard test the steer describes **already exists** at
   `test_w4_roles.py:658` and is already mutation-proved. a4's job is to widen
   `_role_docs()` — follow `get_guide` transitively, and add an explicit corpus
   for the three roles whose command files load nothing — then reconcile
   `KNOWN_GUIDE_TOOLSET_GAPS` with what falls out. Mutation check: delete one
   grant from `_PLANNER`, confirm RED.
2. **Derived-floor bumps, on the settled `roles.py:73-89` precedent** (a verb a
   role's own guides require cannot be folded away; grants no new reach):
   planner `+= status_ping, broker_send, neuron_search` (ceiling 32→35);
   specialist `+= neuron_set_base_session, neuron_set_status` (31→33);
   reviewer `+= propose_spec_learning` (15→16).
3. **Gap 3.4 is a guide fix, not a floor bump.** Change `reviewer.md:62` to name
   `get_specialist_docs`; do not add the singular to the reviewer surface.
4. **Three read-only role rows** for `curiosity` / `goal_keeper` /
   `pattern_observer`, keyed by the underscore strings in `http_pool.py`, plus
   `CRUD_OBJECT_SCOPE` rows of `frozenset()`, plus the source-derived test in
   blocker 6. Mutation check: rename a key to the hyphen form, confirm RED.
5. **The bare-handle logging fallback** (blocker 1). This is the prerequisite for
   *any* future flip decision, and it is a pure fix to `_role_scope_worklog_plan_id`.
   Mutation check: assert a reviewer with a bare handle produces exactly one
   `role_scope_violation`; today that assertion is RED.
6. **`specialist-training.md:31`** — decide guide-vs-floor and land it with the
   other 3.x gaps.

## MUST NOT be attempted now

- **The flip itself.** Blockers 1 and 2 mean a flip is unobservable *and*
  unexplainable. Even a perfect toolset table would be flipped blind.
- **The enforce-mode refuse-and-explain shim** (blocker 2). It changes the shape
  of the registered MCP surface and needs its own step plus a stack restart to
  validate; folding it into a4 mixes a behaviour change into a table fix.
- **Broadening the gate to shared reference guides.** It produces ~30 findings,
  all of which I classified as descriptive prose. Doing it properly needs an
  instruct-vs-describe discriminator — that is design work, and a2 owns the
  feasibility judgement.
- **The `assemble_ruleset` reviewer question.** Still open per
  `role-toolsets-derived.md:42`, which explicitly says *"do not enforce reviewer
  scope before resolving"*. Unresolved; reviewer scope therefore cannot be
  enforced regardless of the gaps above.

## CLOSED — claims from the brief that are refuted or already fixed

- **`(planner, get_recipe_digest)` is FIXED.** Present in `_PLANNER` at
  `roles.py:89`, absent from `KNOWN_GUIDE_TOOLSET_GAPS`, and my independent sweep
  does not report it. Carried forward no further. (VERIFIED)
- **"Role/plan resolution mis-attributes under the hyphen/underscore handle
  trap" — REFUTED as stated.** `_self_and_parent_addresses()` splits on the
  **last** colon (`_tools.py:4647`) and reconstructs the planner's dash plan_id
  explicitly (`_tools.py:4652-4654`). Executed: planner `recipe-x:s25` →
  `recipe-x-s25`; worker `recipe-x-s25:a1` → parent `recipe-x-s25`. Both
  correct. There is **no mis-attribution**. The real defects in this area are
  the *silent drop* on bare handles (blocker 1) and the *role-key* naming
  mismatch (blocker 6) — related, but not the mis-split the brief describes.
- **Registry drift — none.** All six toolsets name only registered tools
  (worker 22, planner 32, reviewer 15, specialist 31, consult 21, neuron 77
  against an 86-tool registry; zero missing). `build_mcp` will not raise today.
  (VERIFIED)
- **"No new static gap inside the gate's corpus."** The seven-entry table is
  exactly right for the corpus it scans. This is a negative result and it is
  reported as one — the table is not stale; the corpus rule is (blocker 5).

---

## A note on this action's own acceptance criterion

`acceptance.verify` for a1 is `{check: file_min_bytes, path:
enforce-readiness-verdict.md, min: 4000}`. Applying the standing rule — *if a
criterion cannot be shown to fail when the thing it guards is broken, it is not
a criterion* — this one is **vacuous**: 4000 bytes of lorem ipsum passes it, and
a correct one-page verdict that happened to be 3900 bytes fails it. It measures
length, not the audit.

I am not silently substituting my own gate. The criterion the reviewer should
re-run instead, and which I have run:

- Each of the four named claims is explicitly ruled in or out above, with
  `file:line` evidence against live source.
- `git grep -n "EDP_ROLE_SCOPE"` returns only the two default-`warn` reads and
  comments — no flip. (VERIFIED)
- The blocker-1 and blocker-2 assertions are executable and were mutation-checked;
  a reviewer can re-run them in a fresh shell.
