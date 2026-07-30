# Universal coding standards (the CORE layer every worker extends)

These are the standards **every** worker is held to, regardless of tech.
A tech specialization (`spec-java`, `spec-react`, …) `extends` this layer
**additively** — it may *add* stricter rules but may never *delete* or
*weaken* one of these. This is the seed set; it is refined on iterative
learning (see SPECIALIZATION-LAYERED-RULESETS.md).

## Who reads this, and how (do NOT straitjacket the coder)

The same standards are read by two roles for two purposes:

- The **coder worker** uses the *constructive* guidance to build well — and
  stays free to think. It is NOT pre-loaded with every rule as a hard
  constraint; over-constraining kills out-of-box problem-solving.
- The **verify worker** (a reviewer fork) enforces these standards on the
  coder's output: it **flags** each gap by adherence and the action only
  reaches `done` once the gap is closed — usually by routing a quick coder
  re-dispatch to fix it (the reviewer judges; it does not itself patch
  code).

So the standards land at the **verify** step, not as upfront pressure on
the coder.

## Adherence levels — defined by what the VERIFY worker does

Vague modality ("should") gets ignored. Each level names a concrete verify
behavior, so the words carry weight by definition:

| Level | The verify worker… | Means |
|---|---|---|
| **`required`** | **blocks `done`** until it holds — flags the gap and routes a fix (a coder re-dispatch); fails the action if it genuinely can't be fixed | non-negotiable |
| **`expected`** | flags it; fixed via re-dispatch if the gap is clear; a *justified, recorded* exception is allowed; does not hard-block | strong default |
| **`preferred`** | only **notes** a deviation; never blocks — it is the coder's house-style default | house style |

`required` ≠ "fail the action" — usually the gap is closed by a quick coder
re-dispatch (rename, add the missing test, re-layer the logic), then the
gate passes. It fails the action only when the gap genuinely can't be
closed.

## The standards (seed)

1. **Object-oriented design** — `required`. Behavior lives on objects with
   clear responsibilities, not in procedural dumping grounds.
2. **Standard naming conventions** — `required`. Consistent, conventional
   names throughout; the verify worker renames to conform.
3. **SOLID, single-responsibility per layer** — `required`. Controllers
   only route; repositories only do CRUD; only service classes hold
   business logic; one business concern per class. Misplaced logic is
   re-layered at verify.
4. **Traceable logging** — `required`. Log on failure/exception paths (not
   just happy paths) so a failure can be traced after the fact.
5. **Separation of concerns** — `required`. No module owns two concerns;
   conflated concerns are split at verify.
6. **Unit AND integration tests for logical components** — `required`. The
   verify worker adds missing tests before `done`.
7. **No regex without user approval** — `required`, **escalate**. Regex in
   code is flagged and **escalated for approval** — the verify worker never
   silently keeps or strips it; the user decides.
8. **Short, readable methods** — `expected`. No hard line limit; the bar is
   "a future reader follows it without untangling." A justified long method
   (with a note saying why) is allowed.
9. **Documentation of non-obvious logic** — `expected`. Document the
   *intent* of non-obvious logic so a future session still makes sense of
   it. Don't narrate trivial code (that's noise); trivial code is exempt.
10. **Close resources where you open them** — `required`. A resource a
    block/class opens (file, socket, connection, lock, process, handle) is
    closed by that same scope — `with`/`try-finally`/`using`/RAII — so it
    can't leak on the error path. Don't hand ownership off implicitly and
    hope someone else closes it.
11. **Never silently swallow exceptions** — `required`. Every caught
    exception is either **handled** (a real recovery action) or **logged**
    with its cause — never an empty `catch`/`except: pass`. Don't catch
    broader than you can handle, and preserve the original error/cause when
    re-raising.
12. **No secrets in code or logs** — `required`. Never hardcode
    credentials/keys/tokens, and never log them — read from config/env and
    redact in any log line.
13. **No dead or commented-out code committed** — `required`. Delete
    unused code, old "previous version" comment blocks, and unreachable
    branches — version control is the history, not comments. (This is the
    anti-slop rule: ship the working code, not the scaffolding.)
14. **Fail fast at boundaries** — `expected`. Validate inputs at the public
    edge (API handler, public method, parser) and reject bad input there —
    don't let invalid state propagate inward to fail somewhere obscure.
15. **Timeouts on every outbound I/O** — `required`. Every network / IO /
    external call (HTTP, DB, socket, subprocess, queue) has an explicit
    timeout — never an unbounded wait that can hang forever. (This is the
    rule the specialists kept re-deriving; it's the hang class behind real
    incidents.)
16. **No magic numbers/strings; externalize config** — `expected`. Name
    literals as constants and externalize configuration (paths, hosts,
    hyperparameters, IDs, thresholds) — don't scatter hardcoded values
    inline. A single, justified literal with a clear name is fine.
17. **Clean up on completion; never blind-delete** — `required`. Finishing
    a change means removing what it made obsolete — dead code, references
    left **dangling** by a rename/removal, orphaned files/artifacts. A
    dangling reference to a removed thing is a top bug source (the exact
    class of bug this rule exists to catch). **The reviewer MUST verify
    cleanup is complete.** But deletion is NOT blind: a *consequential*
    removal — a code block / module / file, or an artifact — is **surfaced
    to the user via the neuron and removed only on approval**; never a
    silent delete, and never silently left behind. (Trivial cleanup inside
    your own change — a variable you just added — needs no approval; that's
    part of writing the change.)
18. **O(1)-in-domain tool/response outputs** — `required`. A tool or
    response payload MUST be O(1) in domain size. There are **two output
    classes — treat them differently** (s17 a7):

    **(a) LIST outputs** — one row per decision / action / event / message /
    fact / neuron / rule. These MUST be a bounded **window + cursor**,
    pull-on-demand — **never one row per item**. A list that grows with
    recipe / plan / event count is a defect: window it **by construction**
    (not as a reactive last-resort trim), report the true total plus a
    `cursor`, and preserve a **full-fidelity-one-read** escape
    (`detail='full'` / explicit `fields=[…]` / a wider `limit`) so nothing is
    lost — only the default projection is bounded. (s17: `recipe_context`,
    `get_recipe_digest`, `read_object`/`query_objects`, the `*_list` tools,
    `recall`, `check_specialist_decay`, `read_object('memory')`, and
    `check_inbox` (byte-budget-by-default) are all bounded this way.)

    **(b) CONTENT / GROUNDING-DELIVERY outputs** — a compiled specialist doc,
    an assembled ruleset, a spec dump: an artifact the consumer applies **in
    full**, with **no deferred pull target** (the doc *is* the full-fidelity
    artifact). These MUST **NOT** be windowed or truncated at delivery —
    hard-truncating a grounding payload silently drops `[required]` rules and
    breaks the specialist worker. Bound them at **author time** instead (e.g.
    a size cap/flag in `write_specialist_doc`) and attach a **non-truncating**
    `{approx_tokens, oversize}` signal at delivery so a ballooned payload is
    caught in review — never dropped. (s17: `get_specialist_docs`,
    `assemble_ruleset`, `get_specialization`, `consult_specialist`.)

    **A future worker must NOT hard-truncate a content/grounding payload to
    satisfy this standard** — that turns the guardrail into a footgun. Ask:
    *is this a list of items, or one artifact applied in full?* Window the
    former; author-bound + flag (never truncate) the latter. New tools must
    not reintroduce the one-row-per-item blowout, and must not
    truncate-to-appease on the content path.

**#19 — A COMMENT OR DOCSTRING ASSERTING A UNIVERSAL MUST ENUMERATE OR BE
DELETED `[required]`.** Any wording that claims *every / all / always / never*
about code it does not itself enforce — "every caller reads this", "all writes go
through here", "nothing can reach X" — is **exactly as unverified as a shell's
claim of the same thing, and far more dangerous.** A message from a shell is read
as a claim; **a docstring asserting a global property about the code it sits in is
read as GROUND TRUTH, by every future reader, forever.**

This is not hypothetical. A shared resolver was introduced with a docstring saying
*"every caller reads it"* — one caller did not, and the docstring is what stopped
anyone looking. The defect it hid could steal a live worker's lock and double-
dispatch its action. **The author taught ONE caller and DOCUMENTED ALL OF THEM.**

So, before you write a universal, do one of three things:
1. **PIN IT WITH A TEST** that goes RED when the universal is violated (then it is
   a guarantee, not a promise); or
2. **ENUMERATE** — *"callers X and Y resolve through Z; caller W deliberately does
   not, because &lt;recorded reason&gt;"*. A named exception is verifiable; a universal
   is a promise. **Enumerating is the honest floor**; prefer it when in doubt; or
3. **DELETE THE SENTENCE.** A claim you cannot ground is deleted, never softened.

**Corollary — a correct change still leaves a trail of prose that now lies.** When
you fix code, GREP every comment, docstring and doc that describes the thing you
touched, and confirm you did not falsify a sibling. A fix that corrects file A and
silently makes file B false is a finding of the same class as a fabricated test
result. **Relevancy is a whole-graph property, not a per-file one.** And note the
sharpest form: the summary people REMEMBER is the thing to check — *a guard that is
real, proven, and narrower than the sentence people remember it by* leaves an
honest suite guarding nothing.

## How a tech layer extends this

A tech spec adds its own rules on top — e.g. Spring's "use constructor
injection," React's "components are pure of side effects" — at its own
adherence levels. It composes **after** this CORE layer (universal-first,
most-specific-last), and additively: a Spring rule can make method-length
stricter, but it cannot remove "traceable logging." If a proposed tech rule
would contradict a CORE rule, that is a design error to surface, not a
silent override.

## edp-framework internals — cautions when editing the edp stack itself (W15/a6)

These apply ONLY to work that edits the edp-claude framework code (not general
coding); a generic grounded worker on framework-edit actions reads the live
source and should keep them in mind:

- **`EDP_TIER_WRITE=1` is always on — tiering coverage and its `*_ref` decl must
  land ATOMICALLY.** Adding a field to `store/tiering.py` dehydrate/hydrate
  without declaring the companion `<field>_ref: str|None` on the `extra='forbid'`
  model makes the next save write a key the schema rejects, wedging every plan
  load. The `.py` fix does NOT hot-reload — a running MCP server holds its
  startup schema, so recovery needs a FRESH shell (the neuron's call).
- **A short-circuit on a shared engine tool must be OPT-IN per call** — gate a
  cheap-return branch on an explicit caller signal, not unconditionally (measure
  blast radius first by neutralizing the branch and diffing the full suite).
- **Windows graceful teardown: `CTRL_BREAK_EVENT` hits the whole process
  GROUP.** Spawn children `CREATE_NEW_PROCESS_GROUP` and handle `signal.SIGBREAK`
  in the parent, or a group-kill orphans the parent's lock; verify on a real wire
  (alt ports/temp dirs).
- **Reactive effect dispatch is at-least-once ACROSS a restart** (the idempotency
  seen-set lives in process memory; the broker replays in-window events on
  resubscribe). Persist the seen-set (or advance the rule's `since`) before
  unlocking Tier-2 mutating effects.
- **`EDP_ROLE`/`EDP_HANDLE` leak into pytest subprocesses and skew
  lineage-derived defaults** (a bare scoped-fact write defaults to neuron-only
  `global` and refuses under `EDP_ROLE=worker`). Clear them IN-INTERPRETER before
  running the suite, not via an `env -u` prefix (which exits 127 where the host
  has no `env` binary).
