# Framework: OCAK (validation, not lens)

Ported verbatim from `evolving-deep-agent/docs/guides/framework-ocak.md`
(the original; preserved here as the authoritative description of what
OCAK is for in this stack).

OCAK is a **post-reasoning completeness check**. It runs AFTER the LLM
has already produced its options. Its job is to catch what was missed,
not to *generate* the reasoning.

This is the single most common misuse of OCAK in this codebase's
history: trying to apply OCAK as a thinking lens ("now reason through
Observation, then Comprehension…") rather than as an audit ("here's
my plan — does it survive each OCAK question?"). The former produces
stilted, scaffolded reasoning that the LLM doesn't believe. The latter
produces real catches.

If you find yourself writing "Step 1: Observation —" before you have
options, you're doing it wrong.

## The four questions (audit form)

Given a generated plan with N options (or, for a recipe, a clarified
goal + draft outcome), ask each question of each option:

**O — Observation**
> "What prior approach to this goal-class did I notice? Did I apply
> it?"

This is a recall-driven check. If `recall("approach for
<goal-class>")` returns prior patterns and the current plan doesn't
reference them, that's a finding.

If there's no prior approach in memory, this question is null — not a
failure, just no signal yet.

**C — Comprehension**
> "Is this plan addressing the symptom or the root cause? Is the
> stated goal the real goal, or a proxy?"

For bug-fix plans: classify as symptom-fix vs root-cause-fix. Both are
valid, but only one matches the user's actual need on a given day.

For project plans: state the *real goal* explicitly. "Write a net
worth script" might have a real goal of "track financial position
over time" — which changes what "done" means.

**A — Awareness**
> "Does the proposed approach address the actual class of error, or
> just this instance?"

A fix that patches one symptom without addressing the structural
cause is an instance fix. Both instance and class fixes can be valid;
the failure mode is *not noticing which one you picked*.

**K — Concerns**
> "Effort, risk, maintenance — what's the K-cost?"

This is the only OCAK question that doesn't catch a *missing*
dimension; it forces explicit accounting of cost. Pin each option to
(low/medium/high) effort + a one-line risk + a maintenance note.

## What OCAK catches well

- Plans that skip a known-prior-approach (Observation).
- Symptom-fixes labeled as bug-fixes (Comprehension).
- Instance-fixes that won't survive the next sibling case (Awareness).
- High-effort options without an explicit cost justification
  (Concerns).

## What OCAK doesn't catch (and don't pretend it does)

- **Quality of reasoning within an option.** OCAK validates that the
  right *kinds* of dimensions are considered, not that the analysis on
  each is good.
- **External constraints** (legal, deadline, third-party
  dependencies). OCAK is internal-completeness; constraints are a
  separate check.
- **Whether the user *agrees* with the option.** OCAK is your audit;
  user sign-off is independent.

## Application procedure

After options have been generated (planner-level) or after the goal
has been clarified into a draft outcome (recipe-level):

```
For each option in plan_options (or for the draft outcome):
  Q_O = recall("approach for {goal_class}") → does this reflect priors?
  Q_C = symptom vs root-cause? state real-goal explicitly.
  Q_A = instance-fix or class-fix? if instance, name the sibling cases
        it won't survive.
  Q_K = (effort, risk, maintenance) tuple for THIS option.

Emit a one-line audit verdict per option/outcome. Any "missed" answer
is a finding to surface to the user before sign-off.
```

The audit verdict is recorded on the recipe (via
`record_audit_verdict` or similar) and on the worklog. A worklog
`reflection` entry is the long-form home.

## When to skip OCAK

- Fast-path goals (trivial, single-step, "just do it"): OCAK overhead
  exceeds the value.
- Single-step plans: OCAK has nothing to compare across.
- Plans where the user has explicitly said "just do it, I trust you":
  their call. OCAK is for *catching what they'd want caught*, not
  enforcing process.

## Anti-patterns

- **"OCAK-driven planning"** — using O→C→A→K as a sequential thinking
  template. This produces over-structured reasoning the LLM doesn't
  believe and the user can't critique. Generate options naturally;
  THEN audit with OCAK.
- **OCAK as ritual** — answering every question with a paragraph
  regardless of signal. A null answer is fine ("Q_O: no prior approach
  in memory"). Performance theater erodes trust in the framework.
- **OCAK after sign-off** — running it as documentation after the
  user has already approved makes it a CYA exercise. The point is to
  *change* the plan or surface a question. Run it before the user
  commits.
