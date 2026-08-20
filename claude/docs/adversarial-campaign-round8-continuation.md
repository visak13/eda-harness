# Adversarial campaign — Round 8 continuation doc

**Purpose:** resume the Sol adversarial campaign after a session compact.
Everything through Round 7 (F40) is merged and pushed. Round 8 is NOT
started. The campaign runs until a round returns an empty findings array,
then the final "compact, recognizable framework" polish sweep.

---

## Where the campaign stands

Repo: https://github.com/visak13/eda-harness — `main` @ `9b32d5e`.
Suites: claude **1586** pass, edp-pool **308**, edp-broker **29** — all
green except `test_phoenix_reachable` (environment only, :6006 down).

**The live fleet needs a STACK RESTART** — pool code changed in F36
(spawn/wiring), F37 (env secret strip), and F40 (EDP_PARENT lineage
stamp). Until restarted, live acceptors/curiosities still lack ask_above
routing + recipe-attributed spend.

### Rounds shipped (ledger: `claude/docs/observations-qa.md`, F33–F40)

| Round | Lens | Findings | Ledger |
|---|---|---|---|
| R1–R4 | prompts/cards · memory/state · FSM/gates · spawn/wiring | 20+13+23+15 | F33–F36 |
| R5 | role surfaces & trust | 12 → 7 fixed + 2 halves; auth REJECTED | F37 |
| R6 | delegation bridge & external seams | 15 → all fixed | F38 |
| — | live /pain catch (deaf acceptor) + F38 post-review | 3 fixed | F39 |
| R7 | **convergence re-attack on F35/F37/F38/F39** | 14 → 12 fixed, 2 rejected | F40 |

Raw outputs: `claude/.sol_review_out-r<N>.txt` (gitignored).

### Owner doctrine (binding, settled — do not re-litigate)

- **Threat model:** single-operator LOCAL fleet. The adversary is a
  confused/prompt-injected AGENT + plain bugs (wrong results, lost state,
  silent failure, runaway spend, deadlock). Multi-tenant auth for
  pool/broker and policy-file signing are REJECTED classes (R5 #2/#4,
  R7 #1) — tell Sol so in the charter, or it wastes findings on them.
- **Accepted residuals (recorded, don't re-fix):** threads.json unlocked
  RMW (worst case = one fresh thread, R7 #8) · remaining sync store
  writes on the loop (F36) · flow-down stays declaration-level ·
  grounding-echo cross-action tolerance for batch heads (F35).
- Acceptor keeps EDIT ("fix what it safely can") — owner ruling F37.
- models.json is the truth for fleet models; Fable-5 = advisor seat
  (curiosity + acceptor); no Sonnet / no Opus 5 seats.
- House rules: no incident lore in agent-visible text · compact strategic
  prompts · advisory-before-hard-gate · MCP tools launch NO external
  programs (sol bridge is the one sanctioned subprocess) · never end a
  turn with an MCP call in flight · cards recompiled via
  `python -m edp_claude.bootdocs` when guides-src changes (budgets in
  `docs/guides-src/manifest.json` — worker card is near its 2600 cap).

### The R7 meta-lesson (apply during every adjudication)

R7's yield was almost entirely **unfixed TWINS** of patched seams: the
generic CRUD guard got ownership but the native planner verbs didn't;
worker ownership was plan-granular not action-granular; effect reuse
checked existence not content; `_sender` stamped only-if-absent. When
fixing any finding, hunt its siblings — same rule, other verbs; same
check, other granularity; same stamp, overwrite-vs-absent.

## How to run Round 8 (mechanics)

From `C:\Projects\Learning\eda-base3\claude`, write a script (charter +
lens < 30_000 bytes) and run it BACKGROUND with output to
`.sol_review_out-r8.txt`:

```python
from edp_claude.tools.sol_bridge import run_sol
run = run_sol(
    prompt=CHARTER + LENS,
    workdir=r"C:\\Projects\\Learning\\eda-base3",
    sandbox="read-only", caller="base-shell-campaign", advisor="sol",
    effort="high", new_thread=True, timeout_secs=1800)
print(run.ok, run.error); print(run.last_message)
```

- The CHARTER text (subsystem map + JSON findings contract + the threat
  model paragraph) is in the R7 script; reuse it verbatim from
  `.sol_review_out-r7.txt`'s generator or re-derive from
  `docs/adversarial-campaign.md` + the doctrine section above. ALWAYS
  include the threat-model paragraph and the accepted-residuals list.
- Known cosmetic: the run may print "code-mode host failed to spawn —
  wrong codex binary" as run.error; the findings still arrive in
  last_message (happened R5–R7; read-only reviews are unaffected).
- Takes ~10–20 min at effort=high. One artifact per turn; a too-broad
  lens bursts the per-turn cap.

### Round 8 lens (recommendation)

A second convergence pass, aimed where R7's fixes landed + the surfaces
no round has re-visited since heavy churn:

1. **F40's own fixes** (the twin-hunt applied to itself): the five
   planner-verb guards' consistency, the batch-sibling allowance
   (can a batch worker skip a sibling it never reached?), EDP_PARENT
   consumers (does anything else derive parents and disagree?),
   the audit-degraded latch lifecycle (who clears it?).
2. **Memory/state layer re-visit** (R2 was 5 rounds of churn ago):
   tiering round-trips, inbox cursors vs the new framing field,
   recipe-brief determinism with the F37 framing line.
3. If BOTH come back near-empty → declare convergence, run the final
   compact-framework polish sweep (the owner's standing mandate).

## Adjudication protocol (per round — unchanged)

1. Findings are PROPOSALS: CONFIRM / PARTIAL / REJECT each with a reason;
   verify every evidence pointer in the code before fixing.
2. Fix confirmed ones + their TWINS; add regression tests
   (`tests/test_f<N>_round8.py`); run FULL suites (claude + edp-pool +
   edp-broker — pool via `cd edp-pool && uv run pytest -q`; broker via
   `uv run --with pytest --with pytest-asyncio --with httpx python -m
   pytest -q`); recompile bootdocs if cards changed.
3. Record as F41 in `observations-qa.md` (verdict table + reject
   reasons); commit + push with
   `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
4. Run the full POOL suite before writing ledger counts (an F40 lesson:
   a targeted file passing ≠ the seam wired — the NameError only showed
   fleet-wide).

## Open threads NOT part of the campaign (don't lose)

- Stack restart (above) — the operator runs it.
- `/pain` ledger (`docs/pain-points.jsonl`) — check for NEW entries from
  live runs at session start; F39 came from there.
- Delete shadow.py/shadow_spawner.py once stable · F2 Layer-2 advisor
  brief · F17 worked-example sweep · steer-ack nested-ack fix ·
  rx.orphaned dash/colon fix · whoami identity block unpopulated
  (memory: it reports "neuron" for every role).
- `claude/.sol/threads.json` churn stays uncommitted by design.
