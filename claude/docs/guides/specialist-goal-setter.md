# Specialist guide: goal-setter

Translate a clarified user goal into a concrete, verifiable goal
statement the planner can act on.

## When to consult

After comprehension gates have cleared (feasibility / actor / role /
concerns), to translate the user's goal into a concrete, verifiable
statement. Also when a feedback event invalidates the prior goal
statement (e.g., user clarification reshaped what "done" means).

## Criteria

A good goal statement has:

- **A verifiable end state**: "the dashboard shows daily reps for the
  past 7 days" beats "a dashboard for daily reps."
- **Boundaries**: what's in scope, what's deferred. Otherwise scope
  drift sneaks in.
- **An owner/role for each verification step**: who looks at the
  dashboard? Who checks the reps are accurate?
- **Time horizon, if any**: deadline, milestone, or "no rush" — be
  explicit.

Useful signals: the user's own verbs and noun phrases (use them
verbatim where possible); recall facts about prior goals of the same
class. Useless signals: aesthetic prose; abstractions that don't tie
to a concrete artefact.

## Verdict shape

```json
{
  "goal_statement": "<the rewritten goal in one or two sentences>",
  "verification_criteria": ["<criterion>", ...],
  "in_scope": ["<short label>", ...],
  "out_of_scope": ["<short label>", ...],
  "time_horizon": "<string or null>",
  "evidence": "<one-line summary>"
}
```

## Anti-patterns

- Don't invent verification criteria the user didn't agree to. If a
  criterion isn't grounded in the goal or earlier clarification, drop
  it.
- Don't rewrite the goal into something the user didn't intend. Stay
  close to their words; clarify ambiguities, don't replace meaning.
