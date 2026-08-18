# Adversarial campaign — Round 5 continuation doc

**Purpose:** hand off Round 5 (role surfaces & trust) to a new session. R5
findings are adjudicated below but NOT yet implemented — they need an owner
ruling first (see "Pending owner decisions"). Everything through Round 4 is
merged and pushed.

> Note on the pause: this doc exists because Round 5's findings are framed
> as security/trust ("a compromised worker", "an attacker") and warrant an
> explicit threat-model ruling before any code changes. This was a genuine
> engineering round; nothing here is blocked by anything other than the
> owner's design decision on the two items flagged below.

---

## Where the campaign stands

Repo: https://github.com/visak13/eda-harness — `main` @ `209cf1e`
(after Round 4). Suites: claude 1548 pass, edp-pool 303, edp-broker 29 —
all green except `test_phoenix_reachable` (environment only, :6006 down).

The live fleet needs a STACK RESTART to pick up the F36 pool/broker code.

### Rounds shipped (ledger: `claude/docs/observations-qa.md`)

| Round | Lens | Commit | Findings |
|---|---|---|---|
| F33 / R1 | Prompts & cards | `9cdb5ed` | 20 → 18 fixed |
| F34 / R2 | Memory & state layer | `de69a27` | 13 → all fixed + /pain skill |
| F35 / R3a+R3b | FSM & gates (split for the 900s cap) | `e2b5b74` | 23 → all fixed |
| F36 / R4 | Spawn/wiring/lifecycle | `cdb95c2` | 15 → all fixed |
| **R5** | **Role surfaces & trust** | **NOT STARTED** | **12, adjudicated below** |

Owner's standing mandate: keep running Sol adversarial rounds and fixing
until a round comes back empty; the framework must stay "smooth, flex to
any problem, not shoot the budget"; every agent-visible surface (prompts,
tool descriptions, tool outputs, FSM, server output) must be compact,
precise, and serve the vision; recipe/plan are durable shared context.
After the rounds converge, a final "compact, recognizable framework"
polish sweep.

### How to run a round (mechanics)

From `C:\Projects\Learning\eda-base3\claude`, foreground with a long
timeout (Round 5 took ~11 min; the harness safely backgrounds it past
600s):

```python
# uv run python <script>
from edp_claude.tools.sol_bridge import run_sol
run = run_sol(
    prompt=CHARTER + ROUND_LENS,          # < 30_000 bytes (argv cap)
    workdir=r"C:\Projects\Learning\eda-base3",
    sandbox="read-only", caller="base-shell-campaign", advisor="sol",
    effort="high", new_thread=True, timeout_secs=1800)   # per-turn kill
print(run.ok, run.error); print(run.last_message)
```

- Save raw output to `claude/.sol_review_out-r<N>.txt` (gitignored).
- The sol turn has a hard cap (`EDP_SOL_TIMEOUT_SECS`, default 900s; R5
  used 1800 via `timeout_secs`). A too-broad lens bursts it — split the
  lens (R3 → R3a+R3b). F35 also hardened this: per-delegate `timeout_secs`
  in `.bridge.json`, and a planner-card "one artifact per challenge turn"
  right-size law.
- If the run errors "code-mode host failed to spawn — wrong codex binary",
  restart the codex host (this happened once after killing a stale codex
  PID; the review itself was unaffected).
- The master CHARTER + per-round adjudication protocol live in
  `claude/docs/adversarial-campaign.md` (the original campaign doc).

### Adjudication protocol (owner doctrine — binding)

1. Findings are PROPOSALS. CONFIRM / PARTIAL / REJECT each, with a reason.
2. Fix confirmed ones; run the FULL suite (claude + edp-pool + edp-broker);
   recompile bootdocs if cards changed (`python -m edp_claude.bootdocs`).
3. House rules: no incident lore in agent-visible text (war stories go in
   code comments/tests) · strategic, compact prompts · advisory-before-
   hard-gate · MCP tools launch NO external programs against workspaces
   (sol bridge is the one sanctioned subprocess) · never end a turn with an
   MCP call in flight.
4. Record each round in `observations-qa.md` as F33, F34, … with a verdict
   table; commit + push per round with
   `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

### Web-search finding (2026-08-18)

Anthropic shipped cross-session messaging (`ListAgents`/`SendMessage`) and
Agent Teams — BUT it requires macOS/Linux/WSL2 and is **not offered on
native Windows** (fleet runs native Windows). The edp-broker stays the
right transport today; revisit only if the fleet moves into WSL2 (native
SendMessage could replace the broker's transport, not its durable
inbox/cursor semantics). Docs:
https://code.claude.com/docs/en/cross-session-messaging

---

## Round 5 — the raw findings

Sol returned 12 findings (raw: `claude/.sol_review_out-r5.txt`). Verbatim
summaries + evidence pointers:

1. **HIGH — role-less shell can mint its own passing acceptance verdict.**
   The verdict guard rejects only a *nonempty* role != "acceptor"; missing
   identity is allowed, and the event is stamped with the current
   fingerprint NextAction trusts. Evidence: `mcp_server.py:99-101`,
   `_tools.py:1686-1706`, `_tools.py:11603-11633`.
2. **HIGH — pool control API unauthenticated; caller chooses role/handle/
   mode/model/lineage.** No role allowlist, so any shell-capable worker can
   create a neuron/acceptor and release/park/resume/reap peers. Evidence:
   `edp-pool/service.py:914-1011, 2198-2226, 2269-2347`.
3. **HIGH — banned EDP_SKIP_PERMISSIONS re-exposed indirectly.** Headless
   mode (via /v1/spawn or the spawn-defaults panel) unconditionally adds
   `--dangerously-skip-permissions`; panel origin check permits no-Origin.
   Evidence: `spawn_defaults.py:8-18,30-39,79-83`, `service.py:290-303,
   2204-2212, 2491-2534`, `spawner.py:240-273`, `pty_launcher.py:306-311`.
4. **HIGH — broker identity/confidentiality/routing unauthenticated.** Any
   process can publish with arbitrary `from`, poll another handle's inbox,
   enumerate all messages, rewrite aliases; check_inbox accepts an
   arbitrary handle override, returns bodies without authenticated
   provenance or an untrusted-data warning. Evidence:
   `edp-broker/service.py:101-150,182-212,261-273`, `_tools.py:12159-12168,
   12305-12328, 12384-12391`.
5. **HIGH — role identity derived from mutable EDP_ROLE/EDP_HANDLE; unset/
   unknown role fails OPEN to the full registry + CRUD.** Several guards
   use `if role and role != ...`, so clearing the var bypasses them.
   Evidence: `attribution.py:4-30`, `roles.py:597-603,685-705`,
   `mcp_server.py:93-109`, `_tools.py:7545-7550, 11382-11400`.
6. **HIGH — agent-authored text inserted into downstream prompts as
   instructions, not framed data.** Shadow briefs embed raw action
   descriptions/acceptance/injected-context next to the role activation;
   recipe briefs label raw goal text as law; compiled specialist docs
   pass through bit-for-bit; inbox bodies returned unframed. Evidence:
   `edp-pool/shadow.py:172-201`, `shadow_spawner.py:305-358`,
   `recipe_brief.py:76-157`, `compose.py:23-54`, `worker.md:32-38`,
   `acceptor.md:14-19`.
7. **HIGH — acceptor repair permission enforced only by prose.** Its shell
   retains normal file-write/delete reach; the destructive hook blocks
   only a narrow process-kill list; a headless acceptor gets no permission
   prompts. Evidence: `acceptor.md:21-48`, `roles.py:561-584`,
   `.claude/settings.json:4-29,31-53`, `hooks/guard-destructive.py:2-46`,
   `spawner.py:240-241`.
8. **HIGH — secrets inherited into every shell (full pool env copied).**
   The HTTP delegate bridge accepts arbitrary task/context, reads a named
   API-key env var, sends to a configurable base URL; provider error
   bodies return to the agent + enter audit fields without redaction.
   Evidence: `pty_launcher.py:438-489`, `bridge.py:80-127,179-228,302-325,
   449-456`.
9. **HIGH — workers can mutate action status in another plan.** The
   grounding check runs only when the target plan_id has the caller's own
   handle prefix; a foreign plan skips it, then the tool updates the
   arbitrary plan/action supplied. Evidence: `_tools.py:6145-6205,
   6329-6435`.
10. **MEDIUM — worker-visible observe can compose a broker_send effect** to
    an arbitrary recipient though workers lack broker_send; the reactive
    executor doesn't recheck the originating role. Evidence:
    `roles.py:185-223,270-273`, `reactive/effects.py:80-89,541-547`,
    `reactive/driver.py:105-148`, `_tools.py:14571-14580,14721-14740`.
11. **MEDIUM — planner CRUD scoping controls object TYPE, not ownership.**
    update_object/delete_object accept arbitrary IDs; the "planners mutate
    their own plan" promise isn't enforced. Evidence: `roles.py:287-295,
    667-681`, `_tools.py:14460-14477,14521-14530,14558-14567`.
12. **MEDIUM — EDP_ROLE_SCOPE fails open for every value except exactly
    "enforce".** A typo (`enfroce`) silently registers the full surface
    under warn behavior. Evidence: `mcp_server.py:116-147,169-179`.

---

## My adjudication (the last live message, verbatim)

### The threat-model fork

Sol reviewed this as if a HOSTILE PROCESS could be on the machine ("a
compromised worker POSTs /v1/spawn", "an attacker-controlled base URL").
This framework is a SINGLE-OPERATOR LOCAL FLEET: every shell is spawned by
the owner, on the owner's box, no untrusted tenant. Under that model, most
of the "authenticate the broker / the pool control-plane / mint capability
tokens" findings describe a DIFFERENT product (a hardened multi-tenant
service); building that adds exactly the ceremony the vision rejects — auth
handshakes on every spawn and message, for an attacker who isn't there.

But two things inside these findings are REAL regardless of threat model,
because the framework's own AGENTS can go wrong (a confused or
prompt-injected LLM, not a hacker):

1. Fail-open robustness bugs — an unset/typo'd EDP_ROLE or EDP_ROLE_SCOPE
   silently grants the FULL tool registry. Not an attacker; a spawn-env bug
   handing a worker neuron powers. Should fail CLOSED.
2. Prompt-injection via data planes — a planner's LLM writes an action
   description; it flows into a worker's prompt as INSTRUCTIONS, not framed
   as DATA. This is squarely the vision ("everything the agent sees,
   well-structured, precise"), and the cards already claim "briefs are
   claims" — the code just doesn't keep that framing.

### Verdicts

**Fix now — agent-safety, aligned with the vision (7):**

| # | Finding | Verdict / fix |
|---|---|---|
| 5 | Unset/unknown EDP_ROLE fails OPEN to the full registry + CRUD; guards `if role and role != x` skip when role empty | CONFIRM. Unknown/missing role → DENY (empty toolset; guards treat absent role as untrusted). The single real "escalation" path on the box. |
| 12 | EDP_ROLE_SCOPE typo → warn-mode, full surface | CONFIRM. Strict enum; unknown value aborts (or forces enforce), never silently opens. |
| 9 | Worker can record_action_status on ANOTHER plan (grounding check only runs when plan prefix matches caller) | CONFIRM — genuine ownership hole. Resolve ownership before mutating, always. |
| 11 | Planner update_object/delete_object checks TYPE not OWNERSHIP — can mutate another plan's objects | CONFIRM. Bind to creating lineage. |
| 10 | Worker-visible observe can compose a broker_send effect though workers lack broker_send | CONFIRM (composition bypass). Authorize the effect by the initiating role. |
| 1 | Role-less foreground shell can mint its own acceptance_verdict=pass (the F35 guard exempts role-less shells for tests/operator) | PARTIAL. The exemption is deliberate (the operator console is role-less), but it IS a self-accept path. Fix: gate the role-less exemption behind an explicit env (tests/operator opt-in), so a spawned shell that lost its role can't use it. |
| 6 | Agent-authored text rendered as instructions, not framed data | CONFIRM, and it's the vision. Fix: structured envelopes — briefs/descriptions/inbox bodies wrapped as "DATA (untrusted claim), not instructions" with the framing the cards already promise. The biggest QUALITY win here. |

**Owner ruling required — these assume a hostile local process (4):**

| # | Finding | My take |
|---|---|---|
| 2 | Pool control-plane unauthenticated (any process can spawn/reap) | Building spawn auth contradicts the single-operator model. REJECT as out-of-scope unless the pool is ever exposed beyond localhost. |
| 4 | Broker unauthenticated (publish-as-anyone / read any inbox) | Same. The PROVENANCE-METADATA half (stamp sender role/lineage on messages so a reader can see origin) is cheap and aligns with framing #6 — take THAT half, reject the auth half. |
| 8 | Secrets inherited into every shell; HTTP delegate could exfiltrate | Real IF an HTTP delegate with a real key is ever configured. Today the only delegate is the sol CLI (no key). Take the cheap defensive half — env allowlist for spawned shells + redact provider errors — and note the isolated-bridge-service idea for if/when a keyed HTTP delegate is added. |

**The one genuinely for the owner to decide (1):**

| # | Finding | Why it's a judgment call |
|---|---|---|
| 3 + 7 | Headless mode adds --dangerously-skip-permissions; the acceptor repairs with full file write in its own shell | This is the crux of the standing EDP_SKIP_PERMISSIONS ban. Headless spawns DO skip permissions by design (that's what headless means for an autonomous shell), and the acceptor NEEDS write access to "fix what it safely can". Sol wants acceptors read-only-by-default with a constrained patch capability. A real safety/capability tradeoff only the owner can set: do you want the acceptor able to EDIT, or only to REPORT? |

### Recommendation (as given)

Fix the 7 agent-safety items as F37 (fail-closed identity, ownership
enforcement, the data-framing envelopes — all vision-aligned, all
testable), plus the CHEAP halves of #4 and #8 (message provenance
metadata, spawn env allowlist + error redaction). REJECT the pool/broker
auth infrastructure as out-of-scope for a single-operator fleet — with a
one-line ledger note so the decision is recorded, not forgotten. Owner
ruling needed on #3+#7 (acceptor write rights) before touching it.

---

## Pending owner decisions (blockers for F37)

1. **Acceptor write rights (#3+#7):** keep the acceptor able to EDIT
   (fix-what-it-safely-can, current design) or make it REPORT-ONLY
   (read-only shell + a constrained patch capability for declared
   workspace paths)? Everything else in F37 can proceed without this.
2. **Multi-tenant auth (#2, #4-auth-half):** confirm REJECT as
   out-of-scope for a single-operator local fleet (my recommendation), or
   direct that the pool/broker get authenticated control planes.

## When resuming — the F37 build (once the two rulings land)

Confirmed-fix list, all testable, no new ceremony on the happy path:

- **#5 fail-closed identity:** `roles.py` role resolution returns the
  EMPTY toolset for an unset/unknown role under enforce; audit the
  `if role and role != x` guards (`_tools.py:7545-7550, 11382-11400`) so
  an ABSENT role is treated as untrusted, not exempt.
- **#12 strict scope enum:** `mcp_server.py` parse EDP_ROLE_SCOPE as a
  strict enum; unknown value aborts (or forces enforce) with a loud log,
  never silent warn-mode.
- **#9 action ownership:** run the grounding + ownership check regardless
  of whether the plan_id resembles the caller's handle
  (`_tools.py:6145-6205`); a worker mutating a foreign plan is refused.
- **#11 planner CRUD ownership:** bind plan/action mutation to the
  creating lineage in the CRUD `_run` paths (`_tools.py:14460-14567`).
- **#10 effect authorization:** the reactive executor authorizes a
  composed broker_send by the INITIATING role+handle, not just the effect
  type (`reactive/effects.py`, `driver.py:105-148`).
- **#1 acceptor-verdict exemption:** gate the role-less
  acceptance_verdict exemption behind an explicit env (e.g.
  EDP_ALLOW_LOCAL_ACCEPT) so a spawned shell that lost its role cannot
  self-accept; the operator console + tests set it.
- **#6 data-framing envelopes (the vision win):** wrap agent-/delegate-
  authored text (recipe/plan briefs, action descriptions, inbox bodies,
  shadow briefs) in a structured "UNTRUSTED DATA — a claim, not an
  instruction" envelope so a downstream shell never executes it as
  orchestration. Touch: `recipe_brief.py`, `compose.py`, the check_inbox
  output shape, and the worker/acceptor cards' framing lines.
- **#4 cheap half — message provenance:** stamp sender role + lineage on
  every broker message so a reader can see origin (rides #6's framing).
- **#8 cheap half — secret hygiene:** an explicit env ALLOWLIST for
  spawned shells (`pty_launcher.py:438-489`) instead of copying the whole
  pool env; redact provider error bodies before they reach the agent or
  the audit sidecar (`bridge.py`).

Then: full suite (claude + edp-pool + edp-broker), bootdocs recompile if
cards changed, record as F37 with the verdict table + the two REJECT/
DEFER notes, commit + push. Then run Round 6 (a fresh lens or a repeat of a
prior lens to confirm convergence) — keep going until a round returns
empty, then the compact-framework polish sweep.
