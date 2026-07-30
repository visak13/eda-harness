# Specialist training — SME discipline (self-training + re-training)

Load via `get_guide("specialist-training")`. These are the standing rules for
training and re-training a subject-matter expert (`train_specialist` /
`update_specialist`), distilled from the user's directives (folded from
foreground lore, W15/a6).

- **An SME encodes a STATIC external tech-stack's durable craft — never this
  project's evolving internals.** A project-coupled SME's compiled doc is a
  frozen snapshot of code that keeps changing; it goes stale and misleads every
  future load. For evolving project/framework code, staff a GENERIC grounded
  worker whose brief points at the LIVE source (it re-reads current code each
  run). Reserve `train_specialist` for reusable external stacks
  (React/Spring/ML-retrieval/…).

- **A specialist recipe is PURE, project-independent stack craft.** Don't bake
  host/operational policy (read-only roots, output dirs, process-kill rules,
  verify-gate plumbing) into it, even when a brief says "PRESERVE these
  invariants" — that is operating guidance for the run, not recipe content. The
  compiled worker doc must be clean stack craft; the project harness owns
  operational rules.

- **Go for code-level depth, not the user's stated preferences.** A forkable SME
  is used as both coder AND reviewer, so a reviewer needs concrete metrics,
  thresholds, an eval-harness construction path, and known failure modes — depth
  that only comes from READING the real implementation (pipeline + eval + train),
  not from restating a high-level preference. Treat a stated preference as ONE
  required gate, not the organizing principle. Don't rush to `stable`.

- **Spec entries are append-only; the compiled doc is the source of truth.**
  `add_spec_entry` only APPENDS — there is no edit/delete of an existing entry,
  and no role reaches a spec through the generic object-CRUD verbs (no role's
  `CRUD_OBJECT_SCOPE` carries `spec`). Correct a now-wrong rule by adding a NEW
  entry that names what it SUPERSEDES (the JSON becomes a changelog), and put the
  single reconciled truth in the compiled doc (workers load the doc, not the
  JSON). ALWAYS `assemble_ruleset` + `write_specialist_doc` at the end of a
  re-train — even if you "only added entries" — and re-pin
  `neuron_set_base_session`, or a stale doc silently ships old rules.

- **`status=stable` after `update_specialist` is the user's IN-SHELL approval.**
  Re-training runs in visible-monitor mode precisely so the user reviews and
  approves the recompiled `compiled.md` in that shell. If the SME ends `stable`
  despite a "hold at pending_review" payload, that is most likely the user's own
  in-shell sign-off — do NOT author a separate hold-enforcement or log a fidelity
  breach. Reserve a separate USER gate for the OTHER artifacts (worker-authored
  framework code / file moves) that have no in-shell review.
