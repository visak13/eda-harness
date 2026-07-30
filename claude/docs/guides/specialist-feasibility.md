# Specialist guide: feasibility

Decide whether a user request can be done at all — physical/sensor/
irreversible-action blockers, or KG-unknown domains that need user
input.

## When to consult

When the goal asks whether something is physically / technically /
authorizationally possible — typically during initial comprehension on
a fresh recipe, or when feedback reopens a feasibility question.

NOT the right specialist for "should we do this?" (that's
[specialist-concern-validator](specialist-concern-validator.md)) or
"is the user clear on what they want?" (that's
[specialist-role-clarity](specialist-role-clarity.md) /
[specialist-actor-clarity](specialist-actor-clarity.md)).

## Criteria

Three concrete blocker categories make a request infeasible:

- **Physical action** required: "move my car", "pick up the package",
  "open the door". Claude Code cannot operate hardware.
- **Sensor input** required: "measure my heart rate", "scan the
  document on my desk". No camera/microphone/sensor access.
- **Irreversible external action** without auth in scope: "transfer
  money", "submit the application", "post to LinkedIn". These need
  explicit credential paths the request hasn't established.

A request is **feasible** when none of the three apply AND the KG has
relevant prior facts on the domain. When no blocker applies but the
domain is unknown to the KG, return `feasible=true` with
`requires_user_input=true` — surface the assumption so the user
confirms.

## Verdict shape

```json
{
  "feasible": true | false,
  "blockers": ["specific blocker description", ...],
  "requires_user_input": true | false,
  "evidence": "<one-line summary of reasoning>"
}
```

`blockers` MUST be non-empty when `feasible=false`.
`requires_user_input` defaults to false; set true only when the domain
is KG-unknown.

## Anti-patterns

- Don't return `feasible=false` without a specific blocker — vague
  infeasibility is unhelpful, and nothing downstream can act on it.
- Don't speculate about exotic blockers (alien interference, supply-
  chain attacks). Stick to the three concrete categories.
- Don't ask the user a question yourself. Set
  `requires_user_input=true` and let the neuron route through the user.
