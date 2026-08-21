# Planner high-level strategy: acceptance-repair-chain

> **OPTIONAL ACCELERATOR** — a pitfall checklist for a DAG you already
> drew (planner-phase-author Step 1). Never contort work to fit this
> file; a DAG matching no strategy is normal — proceed with your DAG.
> Legitimized from live use: repair recipes already ran this chain
> unnamed; the library now names it so its pitfalls are teachable.

**When this strategy applies:** a step whose goal is "make the FAILED
acceptance pass" — a rejected deliverable, a recipe reopened after the
user's own walk failed, a green-on-paper close that did not survive
contact ("all outcomes met" but the app never started). The prior
attempt's EVIDENCE exists and is wrong; the work is to close the gap
between what was recorded and what the user experiences.

## Plan structure: W → D → R → W′

**W — Walk (1 action)**
- Reproduce the REJECTION first, from the user's seat: run the app,
  open the site, follow the recorded `user_path` cold. The acceptance
  is a concrete failure observation ("start command exits 1 at …",
  "page renders offline banner"). Never start from the old evidence —
  it already lied once.

**D — Diagnose (1-2 actions)**
- For each observed failure, find why the ORIGINAL acceptance passed
  while the walk fails: a verify that checked file existence instead of
  behavior, a test against a mock seam, evidence citing tests/commits
  for a visual bar. Name the evidence gap explicitly — it feeds the
  repaired acceptance in R.

**R — Repair (1-N actions)**
- Fix the deliverable AND the acceptance that let it through: the
  repaired action carries a verify that would have caught the original
  rejection (exercise-the-artifact, not file-stat).

**W′ — Re-walk (1 action)**
- The SAME cold walk as W, now expected to pass, plus the original
  outcome's verification. This is the only action that may feed
  `mark_outcome_met` evidence.

## Anti-patterns

- **Repair without the walk.** Fixing what the old worklog says is
  broken re-trusts the record that already failed the user.
- **Patching evidence, not the deliverable** — re-running the old green
  suite and re-citing it. If the acceptance that passed is untouched,
  the rejection will recur.
- **Skipping D.** A repair chain that never names WHY the gate lied
  leaves the same gate lying for the next recipe — flow the gap back
  (`emit_recipe_event(kind="learning", …)`).
- **Batching W′ into R.** The re-walk must be independent of the hands
  that repaired, or it inherits their blind spot; on a big repair make
  it a review leg (`leg_kind="review"`).
