# IMPACT — recipe resume (change to built #2)

**Process honesty:** §5.5 wants this note *before* the change. On this
one I went straight to the fix because it is THE core failure the whole
rewrite exists to beat (HITL killer-check: `/neuron <same goal>` after
`/clear` minted a NEW recipe instead of resuming). Note written
immediately after, same session, before trail close. Recording the
order slip rather than backdating.

## Root cause
DESIGN-v4 §A3 / my own AUDIT item 4 specified "on activation, recall an
open recipe for a similar goal and resume — don't restart." It was
**never implemented**: `next_action` requires a concrete `recipe_id`;
there was no code path that, given a goal and no id (post-`/clear`),
finds an open recipe and resumes. So every `/neuron <goal>` created a
fresh recipe — the prior system's exact signature failure (orphaned
work; the stateless-auth restart trilogy).

## What changed
- `RecipeStore.list_ids()` — enumerate recipe dirs on disk (disk is the
  source of truth that survives `/clear`).
- New tool **`resolve_recipe(goal)`** (16th tool). Scans OPEN recipes
  (`state != closed` AND `final_outcome is None`):
  - normalized-exact goal match → `decision=resume` (+recipe_id);
  - else best Jaccard token-overlap ≥ 0.8 → `decision=confirm`
    (neuron asks the user resume-vs-fresh);
  - else → `decision=create`.
  A *finished* recipe is never resumed (resume is for incomplete work;
  re-running a completed goal correctly starts new).
- `neuron.md` Step 0 (DO FIRST every activation): call `resolve_recipe`
  and honour `resume`/`confirm`/`create`. The resume rule is stated as
  the whole point.
- `# TODO(resume-fuzzy)`: normalized-exact + overlap is the
  deterministic MVP; embedding-cosine for reworded goals (DESIGN-v4 §10)
  is the later refinement. The `confirm` path + user judgement covers
  near-matches until then.

## Blast radius
- edp-claude only. Additive tool + a `RecipeStore` read method + neuron
  activator prose. FSM, schemas, other tools, contracts: untouched.
- Registry 15→16: updated the count assertions in `test_mcp_server`;
  +`test_resolve_recipe` (6 cases) + neuron resume regression test.
- Integration unaffected (additive) — 3/3 still green.

## Risk + mitigation
- Over-eager resume (resuming the wrong recipe) → exact-match is strict
  (normalized whitespace/case only); fuzzy only triggers `confirm`
  (user decides), never silent resume. Conservative by design.
- Under-eager (reworded goal not matched) → falls to `create`; the
  embedding refinement (flagged TODO) addresses this later. Acceptable
  MVP: the killer-check (same goal verbatim) is reliably caught.

## Verdict
The single most important fix in the project. Conservative, tested,
additive. The deterministic MVP nails the killer-check; fuzzy is a
flagged later refinement.
