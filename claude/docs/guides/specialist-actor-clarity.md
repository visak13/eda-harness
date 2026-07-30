# Specialist guide: actor-clarity

Decide whether the actors named in the goal are well-known to the
system or ambiguous and needing user clarification.

## When to consult

After [specialist-actor-identifier](specialist-actor-identifier.md)
has extracted the actor list, or when feedback reopens an actor branch
(e.g., a worklog showed an action was sent to the wrong stakeholder).

## Criteria

An actor is **clear** when:

- It's a well-known role in the user's stored profile (recall surfaced
  the actor's identity), OR
- It's a named external system (Zerodha, IndMoney, Gmail) that the
  system has prior facts about, OR
- The goal text disambiguates ("my wife Priya", "the InfraOps team").

An actor is **ambiguous** when:

- The reference is a pronoun with multiple possible antecedents.
- A first-name or role-only reference matches multiple known actors.
- The actor is unnamed in the goal but plausibly required ("the
  approver", "the team").

Useful signals: recall hits on the actor name, possessive determiners
("my X"), team-name capitalization. Useless signals: how often the
actor is mentioned; whether the actor is the goal's subject or object.

## Verdict shape

```json
{
  "actors": [
    {
      "ref": "<phrase from goal>",
      "status": "clear" | "ambiguous",
      "resolved_identity": "<known name or null>",
      "disambiguation_question": "<one sentence — only when ambiguous>"
    }
  ],
  "all_clear": <bool — true iff every actor.status == "clear">,
  "evidence": "<one-line summary>"
}
```

## Anti-patterns

- Don't fabricate identities. If an actor doesn't surface via recall
  and the goal text doesn't disambiguate, mark `ambiguous`.
- Don't ask the question yourself. Surface in
  `disambiguation_question`; the neuron routes.
