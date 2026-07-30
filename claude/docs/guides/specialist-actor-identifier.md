# Specialist guide: actor-identifier

Extract the list of actors (people, teams, systems) named or implied
in a goal.

## When to consult

Early in comprehension, before
[specialist-actor-clarity](specialist-actor-clarity.md) (the clarity
check consumes the identified list).

## Criteria

Include an actor when:

- Named directly: "Priya", "the InfraOps team", "Zerodha"
- Referenced by role: "my approver", "the on-call engineer"
- Implied by required interaction: "send the email" implies an email
  service + a recipient — list both.

Useful signals: proper nouns, possessive pronouns, role descriptors,
verbs that require an object (send → recipient; submit → submission
target). Useless signals: tangential mentions ("yesterday I told
Priya"); historic references that don't relate to the current action.

## Verdict shape

```json
{
  "actors": [
    {
      "ref": "<phrase from goal>",
      "actor_type": "person" | "team" | "system" | "role",
      "named": "<extracted name or null>"
    }
  ],
  "evidence": "<one-line summary>"
}
```

## Anti-patterns

- Don't infer beyond the text. If the goal doesn't name a recipient
  but `send X` is in scope, flag `recipient: null` rather than
  guessing.
- Don't deduplicate aggressively. "Priya" and "my wife" might be the
  same person — leave both refs for actor-clarity to resolve.
