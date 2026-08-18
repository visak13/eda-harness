# Full-framework adversarial review campaign — continuation doc

**Owner order (2026-08-18):** use Codex (GPT-5.6 via the sol bridge) to
adversarially review the ENTIRE framework — "everything from prompts to
memory layer to framework" — with the reviewer EXPLORING the repo in detail
before judging. Multiple rounds of review → adjudicate → fix → test →
commit. This doc is the campaign state; resume from here after compaction.

## Where things stand (start of campaign)

- Repo: https://github.com/visak13/eda-harness — `main` @ `4a3ab2b`.
  All of F1-F32 is merged and pushed (see `docs/observations-qa.md` for the
  full ledger). Suite: **1508 passed**; `test_phoenix_reachable` fails only
  when the Phoenix telemetry backend (:6006) is down — environment, not code.
- The running fleet still needs a STACK RESTART to pick up the new code/cards.
- Round-1 (design-record-only) review already ran: 17 findings, all
  adjudicated (F30-F32). Raw output: `claude/.sol_review_out.txt` (local,
  gitignored). That round saw NO source code — this campaign is the real one.

## How to run a repo-exploring round (mechanics)

Do NOT use `bridge.delegate_call` — it pins the workdir to a temp dir.
Call `run_sol` directly so Codex gets the REPO as its read-only workspace
and explores files itself (it is agentic; it reads what it decides to chase):

```python
# uv run python - <<EOF   (from C:\Projects\Learning\eda-base3\claude)
from edp_claude.tools.sol_bridge import run_sol
run = run_sol(
    prompt=CHARTER + ROUND_LENS,          # keep under 30_000 bytes (argv cap)
    workdir=r"C:\\Projects\\Learning\\eda-base3",  # the WHOLE framework
    sandbox="read-only",
    caller="base-shell-campaign", advisor="sol",
    effort="high",                        # deep rounds earn high effort
    new_thread=True)                      # fresh thread per round — no sympathy
print(run.ok, run.error); print(run.last_message)
# EOF
```

- Save each round's raw output to `claude/.sol_review_out-r<N>.txt`
  (gitignored pattern below; add if missing).
- Fleet slot cap protects the ChatGPT plan — one round at a time.
- A round on `effort="high"` can take several minutes: run it FOREGROUND in
  one Bash call with timeout 600000; never end the turn with it in flight.

## The master charter (prepend to every round)

> YOU ARE THE INDEPENDENT ADVERSARY reviewing a Claude Code multi-agent
> orchestration framework ("eda-harness"). Your working directory is the
> whole repo, read-only. EXPLORE BEFORE YOU JUDGE: list directories, read
> the code and prompts this round's lens names — never review from file
> names or comments alone. The subsystems: `claude/.claude/commands/*`
> (role prompt cards) · `claude/docs/guides-src` + `docs/guides` (prompt
> sources + deep guides) · `claude/src/edp_claude/fsm/` (recipe/plan state
> machines) · `claude/src/edp_claude/tools/_tools.py` (~14k lines: every
> MCP verb + gates) · `claude/src/edp_claude/store/` (memory layer: recipe
> store, tiering/dehydration, embeddings sidecars, spec store, north star,
> edge index, brief renderer) · `claude/src/edp_claude/reactive/` (rx
> driver/runtime/registry — the wake plane) · `edp-pool/` (shell spawner,
> pty/console launchers, watchdogs, capacity) · `edp-broker/` (message
> store) · `claude/models.json` (seat registry) · `claude/tests/`.
> You never write code. OUTPUT: a JSON array of findings, most severe
> first, each {finding, evidence (file:line where possible), severity:
> high|medium|low, target, suggested_fix (proposal, not a patch),
> failure_scenario (concrete inputs/state → wrong outcome)}. No praise,
> no design summary. An empty array means a real hunt found nothing.

## The rounds (run in order; adjudicate + fix between each)

| R | Lens (append to charter) | Primary files |
|---|---|---|
| 1 | **Prompts & cards**: contradictions between cards/guides, instructions naming verbs a role lacks (cross-check `tools/roles.py`), ambiguity a literal model misreads, Goodhart-able instructions, budget-starved cards | `.claude/commands/*`, `docs/guides-src/*`, `docs/guides/*`, `tools/roles.py`, `tools/catalog.py` |
| 2 | **Memory & state layer**: data loss/corruption/staleness — tiering dehydrate/hydrate round-trips, sidecar drift (embeddings/status restamps), inbox cursors (lost/duplicated mail), events rollup, north-star immutability, brief currency, spec overlay | `src/edp_claude/store/*`, cursor logic in `_tools.py` (check_inbox), `edp-broker/` |
| 3 | **FSM & gates**: states with no legal exit, gates satisfiable while their goal fails, gate interactions (G-ADJ/G-CHALLENGE/G-ACCEPT/G-SPEC/G-STEP/G-OUTCOME ordering), crash-recovery ladders, the reopen path, batch semantics | `src/edp_claude/fsm/*`, gate code in `_tools.py`, `schemas/instruction.py` |
| 4 | **Spawn/wiring/lifecycle**: the next freeze class — event-loop blocking, turn-boundary races, arm_wiring atomicity, driver deafness, park/resume, orphan detection (known dash/colon defect), capacity deadlocks, monitor-mode permission stalls | `edp-pool/src/edp_pool/*`, `reactive/driver.py`+`runtime.py`, arm_wiring/observe in `_tools.py` |
| 5 | **Role surfaces & trust**: privilege escalation between roles, warn-vs-enforce residue, prompt-injection via broker bodies/PTY lines, the acceptor's repair rights, panel/spawn-defaults reach (EDP_SKIP_PERMISSIONS must stay unreachable) | `tools/roles.py`, `mcp_server.py`, `edp-pool/spawn_defaults.py`, seat-law card text |

More rounds if findings warrant (e.g. a dedicated pass on `bridge.py`/
`sol_bridge.py`, or on tests-as-contracts).

## Adjudication protocol (owner doctrine — binding)

1. Findings are PROPOSALS. For each: CONFIRM (evidence checks out) /
   PARTIAL / REJECT (say why). Never obey blindly.
2. Fix confirmed findings in the same round; run the FULL suite; recompile
   bootdocs when cards change (`python -m edp_claude.bootdocs`, budgets in
   `docs/guides-src/manifest.json`).
3. Rules of the house: no incident lore in agent-visible text (generic
   principles only; war stories go in code comments/tests) · strategic
   writing (short, imperative, one example) · advisory-before-hard-gate
   (the G-CHALLENGE serialization lesson) · MCP tools launch NO external
   programs against workspaces (owner ruling; sol bridge is the one
   sanctioned subprocess) · never end a turn with an MCP call in flight.
4. Record each round in `docs/observations-qa.md` as F33, F34, … with
   verdict tables; commit + push per round
   (`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`).

## Session-continuation checklist (post-compaction boot)

1. Read this doc + the F-ledger tail of `docs/observations-qa.md`.
2. Verify clean-ish tree: only `claude/.sol_review_out*.txt`,
   `claude/.sol/threads.json` expected dirty/untracked.
3. Confirm suite baseline: `uv run pytest tests/ -q` → 1508 pass +
   Phoenix env-fail.
4. Run Round 1 per the mechanics above; adjudicate; fix; test; commit; then
   Round 2; etc. One round per sitting is fine — the doc is the state.
5. Known open threads NOT part of this campaign (don't lose them): delete
   shadow.py/shadow_spawner.py once stable · F2 Layer-2 advisor-distilled
   brief · F17 full worked-example sweep · steer-ack nested-ack fix ·
   rx.orphaned dash/colon fix (excluded from composed specs meanwhile) ·
   29 incident refs across 10 deep guides (F17-adjacent sweep) ·
   `claude/.sol/threads.json` state churn left uncommitted by design.
