# Specialist guide: role-clarity

Decide whether the user's role in the goal is clear — owner, observer,
approver, delegator, or unclear.

## When to consult

When the goal text is non-trivial and you need to verify the user
knows what part they play. Typical examples: multi-stakeholder goals
("the team wants…"), automation-on-behalf goals, or goals that talk
about "us" / "we" without saying who that is.

## Criteria

The user's role falls into one of:

- **owner** — the user drives, makes decisions, signs off. "I want to
  build…" / "Help me ship…"
- **observer** — the user wants to know something but doesn't act.
  "What's the status of…" / "Tell me about…"
- **approver** — the user gates someone else's work. "Review and
  approve the team's plan for…"
- **delegator** — the user wants the system to act on their behalf.
  "Send these emails", "book the trip"
- **unclear** — the goal doesn't reveal which.

Useful signals: pronouns ("I", "we", "the team"), verbs ("build",
"review", "book"), responsibility markers ("on my behalf", "for my
approval"). Useless signals: how excited the user sounds, whether the
goal mentions external systems, length of the goal text.

## Verdict shape

```json
{
  "user_role": "owner" | "observer" | "approver" | "delegator" | "unclear",
  "confidence": 0.0-1.0,
  "ambiguity_flags": ["short note", ...],
  "evidence": "<one-line summary>"
}
```

`ambiguity_flags` is non-empty when `user_role == "unclear"` — list
the specific phrases that created the ambiguity so they can be
surfaced to the user.

## Anti-patterns

- Don't return `unclear` without ambiguity_flags pointing to the
  actual phrases. "It's unclear" without specifics isn't actionable.
- Don't infer roles from outside the goal text. If the user said
  "build me X" you know enough; don't go reading the worklog.
