# Round 11 adversarial review — full-framework convergence sweep
from edp_claude.tools.sol_bridge import run_sol

CHARTER = """YOU ARE THE INDEPENDENT ADVERSARY reviewing a Claude Code multi-agent \
orchestration framework ("eda-harness"). Your working directory is the whole repo, \
read-only. EXPLORE BEFORE YOU JUDGE: list directories, read the code and prompts \
you attack — never review from file names or comments alone. The subsystems: \
claude/.claude/commands/* (role prompt cards) · claude/docs/guides-src + docs/guides \
(prompt sources + deep guides) · claude/src/edp_claude/fsm/ (recipe/plan state \
machines) · claude/src/edp_claude/tools/_tools.py (~15k lines: every MCP verb + \
gates) · claude/src/edp_claude/store/ (memory layer) · claude/src/edp_claude/reactive/ \
(rx driver/runtime/registry — the wake plane) · edp-pool/ (shell spawner, pty/console \
launchers, watchdogs, capacity) · edp-broker/ (message store) · claude/models.json \
(seat registry) · claude/tests/. \
You never write code. OUTPUT: a JSON array of findings, most severe first, each \
{finding, evidence (file:line where possible), severity: high|medium|low, target, \
suggested_fix (proposal, not a patch), failure_scenario (concrete inputs/state -> \
wrong outcome)}. No praise, no design summary. An empty array means a real hunt \
found nothing.

THREAT MODEL (binding — findings outside it will be rejected): this is a \
single-operator LOCAL fleet on one machine. The adversary is a confused or \
prompt-injected AGENT plus plain bugs (wrong results, lost state, silent failure, \
runaway spend, deadlock). There is NO hostile local process: multi-tenant \
authentication for pool/broker, policy-file signing/hash-pinning, and \
filesystem-permission hardening against local writers are REJECTED classes — do not \
report them again. Accepted residuals (recorded; do not re-report): threads.json \
unlocked read-modify-write · remaining synchronous store writes on the event loop · \
delegation flow-down stays declaration-level · grounding-echo cross-action tolerance \
for batch heads · north_star save is single-writer LWW (immutable-goal guarded) · \
audit-degraded is a loud note, deliberately NOT a fail-closed latch · the \
grounding-brief 6000-char injection clip is loud at both ends by design (no ack \
gate) · _sender is a transport-stamped claim, framed as such (no broker auth) · \
batch spawn member-set equality is deferred (canonical nonterminal head + \
declared-order + unique-ids shipped) · a durable outstanding-steer ledger is \
deferred (steer records are pinned to the hot tail) · acceptance fingerprints \
cover delivery substance (per-action evidence digests), not artifact-file hashes.
"""

LENS = """
ROUND 11 LENS — FULL-FRAMEWORK CONVERGENCE SWEEP. Ten fix-rounds have landed \
(git log F33-F43; regression pins in claude/tests/test_f3*_*.py and \
test_f40_round7.py through test_f43_round10.py). Every subsystem has now had a \
post-churn re-visit: prompts/cards (R1, R10), memory/state (R2, R8), FSM/gates \
(R3, R10), spawn/wiring (R4), role trust (R5), the bridge (R6), the wake plane \
(R9), plus three convergence passes on the fixes themselves (R7, R8, R9, R10).

This round is the CONVERGENCE TEST: sweep the WHOLE framework with fresh eyes \
and report only defects that (a) you can evidence at file:line, (b) fall inside \
the threat model, and (c) are not accepted residuals. Prioritize: \
1. cross-subsystem interactions no single-lens round could see (a store \
   guarantee one tool relies on but another breaks; a gate whose input another \
   fix changed; wake-plane state vs FSM state disagreeing); \
2. the freshest fixes (F43: G-RUNS cmd matching, delivery fingerprints, the \
   nonterminal canonical head, the all-steps reconcile sweep, rule \
   generations, the composite drain) — hunt their twins and edge cases; \
3. anything plainly broken that ten rounds somehow never touched.

Severity honesty matters more than volume: do not restate known residuals, do \
not manufacture findings. AN EMPTY ARRAY IS A VALID AND MEANINGFUL RESULT — it \
declares the framework converged under this threat model. Return findings only \
if a real hunt surfaced real defects.
"""

run = run_sol(
    prompt=CHARTER + LENS,
    workdir=r"C:\Projects\Learning\eda-base3",
    sandbox="read-only",
    caller="base-shell-campaign",
    advisor="sol",
    effort="high",
    new_thread=True,
    timeout_secs=1800,
)
print(run.ok, run.error)
print(run.last_message)
