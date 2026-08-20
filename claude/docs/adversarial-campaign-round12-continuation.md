# Adversarial campaign — Round 12 continuation doc

**Purpose:** resume the Sol adversarial campaign after a session compact.
Everything through Round 11 (F44) is merged and pushed. Round 12 is NOT
started. The campaign runs until a round returns an empty (or noise-only)
findings array, then the final "compact, recognizable framework" polish
sweep (the owner's standing mandate).

---

## Where the campaign stands

Repo: https://github.com/visak13/eda-harness — `main` @ `f32e8e6`.
Suites: claude **1625** pass, edp-pool **311**, edp-broker **30** — all
green except `test_phoenix_reachable` (environment only, :6006 down).

**The live fleet still needs a STACK RESTART** — pool code changed in
F36/F37/F40 and now F44 (starting-reservation admission), broker code in
F44 (append lock). Until restarted the live processes run the old code.

### Rounds shipped (ledger: `claude/docs/observations-qa.md`, F33–F44)

| Round | Lens | Yield | Ledger |
|---|---|---|---|
| R1–R4 | prompts/cards · memory/state · FSM/gates · spawn/wiring | 18+13+23+15 | F33–F36 |
| R5–R6 | role trust · delegation bridge | 7(+2 halves)+15 | F37–F38 |
| — | live /pain catch (deaf acceptor) | 3 | F39 |
| R7 | convergence re-attack | 12 fixed, 2 rejected | F40 |
| R8 | F40 fixes + memory/state | 8 fixed, 1 rejected | F41 |
| R9 | F41 fixes + wake plane | 13 fixed | F42 |
| R10 | FSM/gates + cards re-visit | 8 fixed | F43 |
| R11 | full-framework convergence sweep | 9 fixed (3 new cross-subsystem races) | F44 |

Raw outputs: `claude/.sol_review_out-r<N>.txt` (gitignored). ~130
findings adjudicated total; ~10 rejected with written reasons.

### Owner doctrine (binding, settled — do not re-litigate)

- **Threat model:** single-operator LOCAL fleet. The adversary is a
  confused/prompt-injected AGENT + plain bugs. REJECTED classes (tell Sol
  in the charter): multi-tenant pool/broker auth, policy-file
  signing/hash-pinning, filesystem-permission hardening vs local writers.
- **Accepted residuals (recorded; do not re-fix or re-report):**
  threads.json unlocked RMW · remaining sync store writes on the loop ·
  flow-down stays declaration-level · grounding-echo cross-action
  tolerance for batch heads · north_star single-writer LWW
  (immutable-goal guarded) · audit-degraded = loud note, NOT fail-closed
  · grounding-brief 6000-char clip loud at both ends, no ack gate ·
  _sender = transport-stamped claim, framed as such · batch spawn
  member-set equality deferred (canonical ready nonterminal head +
  declared-order + unique ids shipped) · durable outstanding-steer
  ledger deferred (steer records pinned to the hot tail) · acceptance
  fingerprint = delivery substance (evidence digests + review passed
  flags), not artifact-file hashes.
- Acceptor keeps EDIT ("fix what it safely can") — owner ruling F37.
- models.json is the truth for fleet models; Fable-5 = advisor seat
  (curiosity + acceptor); no Sonnet / no Opus 5 seats.
- **Intelligence over guardrails** (owner reverted a caps/checkpoint
  arc): loud notes + honest refusals over hard fail-closed latches.
- House rules: no incident lore in agent-visible text · compact
  strategic prompts · advisory-before-hard-gate · MCP tools launch NO
  external programs (sol bridge is the one sanctioned subprocess) ·
  never end a turn with an MCP call in flight · cards recompiled via
  `python -m edp_claude.bootdocs` when guides-src changes (worker card
  sits at 2599/2600 — trim to add).

### Meta-lessons (apply during every adjudication)

1. **Twin-hunt (R7):** the dominant defect class is the unfixed TWIN of a
   patched seam — same rule/other verbs, same check/coarser granularity,
   existence-vs-content, stamp-if-absent-vs-overwrite. Fix siblings with
   the finding.
2. **Fresh fixes are the next attack surface (R10/R11):** every
   convergence round found defects in the previous round's fixes (F42's
   canonical head deadlock, F43's first-member head, F42's watcher
   scope). Attack your own patch in the same adjudication.
3. **Cross-subsystem races only show to a whole-framework lens (R11):**
   the broker append thread race, the pool starting-reservation steal,
   and the acceptance attempt binding were invisible to every
   single-subsystem round.
4. **Run the FULL suites of every touched component before ledger
   counts** (an F40 NameError only showed fleet-wide; pool via
   `cd edp-pool; uv run pytest -q`; broker via `uv run --with pytest
   --with pytest-asyncio --with httpx python -m pytest -q`).

## How to run Round 12 (mechanics)

The charter + threat model + accepted residuals + "empty array declares
convergence" lens live in the R11 generator — reuse
`C:\Users\aksou\AppData\Local\Temp\claude\...\scratchpad\run_r11.py` if
it survives, else re-derive from this doc (charter text = R11's, update
the residuals list with the F44 lines above and name the F44 fixes as
part C to attack). Save as run_r12.py, output `.sol_review_out-r12.txt`.

- Invocation: `run_sol(prompt=CHARTER+LENS, workdir=r"C:\Projects\
  Learning\eda-base3", sandbox="read-only", caller="base-shell-campaign",
  advisor="sol", effort="high", new_thread=True, timeout_secs=1800)`.
- **Launch DETACHED** (lesson from R11): a foreground/background Bash
  call dies at the 10-min harness cap and ORPHANS the codex process
  (it hung and had to be killed). Use:
  `Start-Process <venv python> -ArgumentList '"run_r12.py"'
  -RedirectStandardOutput .sol_review_out-r12.txt -WindowStyle Hidden`
  then poll with bounded `Wait-Process -Timeout 550` calls.
- ~10–20 min at effort=high. One artifact per turn.

### Round 12 lens (recommendation)

Second full-framework convergence sweep, empty-is-valid charter:
1. F44's own fixes (attempt binding + latch abort, the replacement
   version gate vs legitimate reopen flows, the starting-reservation
   grace, owner-probe recovery, atomic observe).
2. Cross-subsystem protocol/concurrency (the R11 vein): any remaining
   read-modify-write outside a lock, any two components disagreeing
   about one invariant.
3. If empty/noise-only → DECLARE CONVERGENCE → the closing
   compact-framework polish sweep (owner mandate: "compact, recognizable
   framework" — naming, dead code (shadow.py/shadow_spawner.py), doc
   coherence, size).

## Adjudication protocol (unchanged)

Findings are PROPOSALS: CONFIRM/PARTIAL/REJECT each with a reason,
verify every evidence pointer in code first. Fix + twins + regression
tests (`tests/test_f45_round12.py`), full suites of every touched
component, recompile bootdocs if cards changed, ledger as **F45** in
`observations-qa.md`, commit + push with
`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Open threads NOT part of the campaign (don't lose)

- STACK RESTART (above) — the operator runs it.
- `/pain` ledger (`docs/pain-points.jsonl`) — check for NEW entries at
  session start (only the F39 acceptor entry exists as of this doc).
- Delete shadow.py/shadow_spawner.py once stable · F2 Layer-2 advisor
  brief · F17 worked-example sweep · steer-ack nested-ack fix ·
  rx.orphaned dash/colon fix · whoami identity block unpopulated.
- `claude/.sol/threads.json` churn stays uncommitted by design.
