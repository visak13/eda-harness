# Adversarial campaign — Round 15 continuation doc

**Purpose:** resume the Sol adversarial campaign after a session compact.
Everything through Round 14 (F47) is merged and pushed. Round 15 is NOT
started. This doc supersedes `adversarial-campaign-round12-continuation.md`.

---

## Where the campaign stands

Repo: https://github.com/visak13/eda-harness — `main` @ the F47 commit
(after `52851d0`; `git log -1` shows it). Suites: claude **1656** pass,
edp-pool **319**, edp-broker **33** — green except `test_phoenix_reachable`
(environment only, :6006 down).

**The live fleet still needs a STACK RESTART** — pool code changed in
F36/F37/F40/F44/F45/F46/F47, broker in F44/F45. Until restarted the live
processes run old code.

### Rounds shipped (ledger: `claude/docs/observations-qa.md`, F33–F47)

| Round | Lens | Yield | Ledger |
|---|---|---|---|
| R1–R6 | per-subsystem harvest | 13–23/round | F33–F38 (+F39 live /pain) |
| R7–R10 | convergence re-attacks | 12, 8, 13, 8 | F40–F43 |
| R11 | 1st whole-framework sweep | 9 (3 cross-subsystem races) | F44 |
| R12 | 2nd sweep, F44 fixes targeted | 8, no new class | F45 |
| R13 | 3rd sweep, F45 fixes targeted | 5, no new class | F46 |
| R14 | 4th sweep, F46 fixes targeted | 6, ALL TOCTOU/transactional | F47 |

~150 findings adjudicated; ~10 rejected with written reasons. Raw
outputs: `claude/.sol_review_out-r<N>.txt` (gitignored). Charter scripts:
`scratchpad/run_r14.py` (session temp — may be gone) and the tracked copy
`claude/.sol_review_charter-r11.py` (untracked file, base text).

### QUALITY-vs-QUANTITY verdict (owner asked, 2026-08-21)

Counts are flat (9→8→5→6) but KIND converged: R1–R10 = wrong/missing
guards (fire in everyday operation); R11–R12 = cross-subsystem races;
R13–R14 = pure TOCTOU/atomicity gaps in guards that already check the
right thing, at ever-lower practical probability. The loop partly feeds
itself (each round's fixes are the next round's targets — F45's python
wrapper CREATED F46's `python pytest` hole). A file-based multi-process
system yields TOCTOU findings nearly indefinitely.

### ROUND 15 STOP CRITERION (stated to the owner pre-compact)

Run Round 15 as the fifth sweep (F47's fixes as prime target). Then:
- If it yields ONLY fix-of-fix / transactional findings with no
  everyday-operation trigger and no new class → **DECLARE CONVERGENCE BY
  CLASS**: record "residual TOCTOU tail at the file-store layer, locked
  at every seam the fleet actually crosses" as an accepted residual, and
  move to the closing polish sweep (owner mandate: "compact, recognizable
  framework" — naming, dead code shadow.py/shadow_spawner.py, doc
  coherence, size). Estimated 70% likely.
- A literally empty array also declares convergence.
- Anything with a new class or everyday trigger → fix as F48, run R16.

### Owner doctrine (binding, settled — do not re-litigate)

- **Threat model:** single-operator LOCAL fleet; adversary = confused/
  prompt-injected AGENT + plain bugs. REJECTED classes: multi-tenant
  pool/broker auth · policy-file signing/hash-pinning · filesystem-
  permission hardening vs local writers.
- **Accepted residuals** (do not re-fix/re-report): threads.json unlocked
  RMW · sync store writes on the loop · declaration-level flow-down ·
  grounding-echo cross-action tolerance · north_star single-writer LWW ·
  audit-degraded = loud note, not fail-closed · brief 6000-char clip loud
  both ends, no ack gate · _sender = transport-stamped claim · batch
  member-set equality deferred · durable steer ledger deferred ·
  fingerprint = delivery substance, not artifact hashes · starting-reap
  grace fixed 180s env-tunable · replacement gate keys on version-1 vs
  existing v>1 · G-RUNS allows trailing args after the anchored declared
  command · channel GET→PUT survives only as pre-F45-broker fallback ·
  verdicts WITHOUT acceptor_id (pre-F46/operator console) trusted at the
  close gate · reaping a still-registering pool row defers to
  release-after-registration; abandoned reservations recovered by the
  admission grace · pool state json.dump may iterate dicts a peer domain
  lock is mutating (persist lock fixes stale-replace, not
  mutation-during-dump).
- Acceptor keeps EDIT (F37) · models.json is the truth (Fable-5 advisor
  seat; no Sonnet/Opus-5 seats) · **intelligence over guardrails** ·
  house rules: no incident lore in agent-visible text · MCP tools launch
  NO external programs (sol bridge = the one sanctioned subprocess) ·
  never end a turn with an MCP call in flight · commits carry
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` · cards
  recompile via `python -m edp_claude.bootdocs` (worker card 2599/2600 —
  trim to add).

### Meta-lessons (apply during every adjudication)

1. **Twin-hunt** — fix the sibling seams with the finding.
2. **Fresh fixes are the next attack surface** — attack your own patch in
   the same adjudication (proven every round since R10).
3. **Cross-subsystem races only show to whole-framework lenses.**
4. **Run FULL suites of every touched component before ledger counts**
   (pool: `cd edp-pool; uv run pytest -q`; broker: `uv run --with pytest
   --with pytest-asyncio --with httpx python -m pytest -q`).
5. **Guards must TRANSACT, not just check** (R14's entire yield): a
   correct check outside the lock that covers its commit is the next
   finding.

## How to run Round 15 (mechanics)

Derive run_r15.py from this doc + the R11 charter base
(`claude/.sol_review_charter-r11.py`): CHARTER = threat model + the FULL
residual list above; LENS = fifth whole-framework sweep, part 1 = F47's
fixes (the sh -c recursion in G-RUNS, the locked close/dispatch recipe
transaction + _reserve_attempt split, the pool _persist_lock, the
supervisor OS-lock singleton, deferred waiver events), part 2 = remaining
check-vs-commit gaps, part 3 = anything 14 rounds never touched;
empty-is-valid clause verbatim.

- `run_sol(prompt=CHARTER+LENS, workdir=r"C:\Projects\Learning\eda-base3",
  sandbox="read-only", caller="base-shell-campaign", advisor="sol",
  effort="high", new_thread=True, timeout_secs=1800)`.
- **Launch DETACHED** (10-min harness cap orphans a foreground codex):
  `Start-Process <claude venv python> -ArgumentList '"run_r15.py"'
  -WorkingDirectory <claude dir> -RedirectStandardOutput
  .sol_review_out-r15.txt -RedirectStandardError .sol_review_err-r15.txt
  -WindowStyle Hidden -PassThru`, then poll with bounded
  `Wait-Process -Timeout 550` background calls. ~15–20 min.

## Adjudication protocol (unchanged)

Findings are PROPOSALS: CONFIRM/PARTIAL/REJECT with reasons; verify every
evidence pointer in code first. Fix + twins + regression tests
(`tests/test_f48_round15.py`), full suites of every touched component,
bootdocs recompile if cards changed, ledger as **F48**, commit + push.

## Open threads NOT part of the campaign (don't lose)

- STACK RESTART (above) — the operator runs it.
- `/pain` ledger `docs/pain-points.jsonl` — check for NEW entries at
  session start (only the F39 acceptor entry exists as of this doc).
- Polish-sweep backlog for after convergence: delete
  shadow.py/shadow_spawner.py · naming/doc coherence/size · F2 Layer-2
  advisor brief · F17 worked-example sweep · steer-ack nested-ack fix ·
  rx.orphaned dash/colon fix · whoami identity block unpopulated.
- `claude/.sol/threads.json` churn stays uncommitted by design.
