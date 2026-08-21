# Round 14 adversarial review — fourth full-framework convergence sweep
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
batch spawn member-set equality is deferred (canonical ready nonterminal head + \
declared-order + unique-ids shipped) · a durable outstanding-steer ledger is \
deferred (steer records are pinned to the hot tail) · acceptance fingerprints \
cover delivery substance (per-action evidence digests + review-passed flags), \
not artifact-file hashes · the starting-reservation reap grace is a fixed \
180s env-tunable, not adaptive · the whole-object replacement gate keys on \
version-1 payloads against existing v>1 objects (legitimate reopen flows go \
through resume/reopen verbs, not re-record) · G-RUNS allows extra trailing \
arguments after the anchored declared command (full anti-cheat = artifact \
hashing, deferred with the fingerprint residual) · the pool/tools channel \
GET-then-PUT survives only as the fallback for a pre-F45 broker (405) · an \
acceptance verdict WITHOUT acceptor_id (pre-F46 / the operator console) is \
trusted as before at the close gate — attempt binding applies to spawned \
acceptors · reaping a still-registering (starting) pool row defers to \
release-after-registration by design; abandoned reservations are recovered \
by the admission grace, not by reap.
"""

LENS = """
ROUND 14 LENS — FOURTH FULL-FRAMEWORK CONVERGENCE SWEEP. Thirteen fix-rounds \
have landed (git log F33-F46; regression pins in claude/tests/test_f3*_*.py \
and test_f40_round7.py through test_f46_round13.py, plus \
edp-pool/tests/test_f44_*.py / test_f45_release_lock.py / \
test_f46_reap_and_driver_lock.py and edp-broker/tests/test_f44_append_lock.py \
/ test_f45_channel_merge.py). Rounds 11-13 were whole-framework sweeps \
(9 -> 8 -> 5 defects, all fixed); Rounds 12 and 13 found NO new defect class \
— every finding was a twin of a shipped guard or the known \
unlocked-RMW/protocol class, which has now been drained across recipe/plan \
stores, broker inbox + channels, pool sessions/reap/drivers, handle index, \
and rule registry.

This round is the CONVERGENCE RE-TEST: sweep the WHOLE framework with fresh eyes \
and report only defects that (a) you can evidence at file:line, (b) fall inside \
the threat model, and (c) are not accepted residuals. Prioritize: \
1. THE F46 FIXES THEMSELVES — attack the freshest patches: the ATTEMPT-bound \
   acceptance arc (verdict acceptor_id stamping, superseded-emission refusal, \
   the close gate's live-attempt check, the latch's own-verdict settling — \
   all in claude/src/edp_claude/tools/_tools.py), the python `-m`-only \
   G-RUNS wrapper grammar, the locked pool reap()/registration protocol \
   (starting rows flagged, done rows never resurrected), the neuron-driver \
   _driver_lock lifecycle, the locked RuleRegistry; \
2. remaining cross-subsystem protocol/concurrency defects: any \
   read-modify-write outside a lock, any two components disagreeing about one \
   invariant, wake-plane state vs FSM state divergence; \
3. anything plainly broken that thirteen rounds somehow never touched.

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
