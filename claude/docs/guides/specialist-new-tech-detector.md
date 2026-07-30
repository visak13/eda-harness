# Specialist guide: new-tech-detector

Detect technology, libraries, or services in a goal that the system
has no prior knowledge of, and flag them for capability-gap research.

## When to consult

When the recipe's goal mentions concrete tech names, OR when feedback
surfaces a tool/library the executor hit and struggled with. The
output drives capability-gap detection during planning.

## Criteria

A tech reference is **known** when:

- `recall("known patterns for <tech>")` returns ≥1 substantive fact,
  OR
- `list_capabilities` shows an existing tool/skill covering it, OR
- The system has shipped multiple plans touching it (worklog history).

A tech reference is **unknown** when none of the above hold.

Useful signals: explicit named SDKs ("kite-connect", "boto3"),
domain-specific terms ("vector store", "GraphQL federation"), version
numbers ("Python 3.12"). Useless signals: generic CS terms ("a
database", "some API"); whether the user sounds confident about the
tech.

## Verdict shape

```json
{
  "tech_refs": [
    {
      "ref": "<term from goal>",
      "status": "known" | "unknown",
      "evidence_source": "recall" | "capabilities" | "worklog" | null
    }
  ],
  "unknown_count": <int>,
  "evidence": "<one-line summary>"
}
```

## Anti-patterns

- Don't classify based on the LLM's general knowledge of a tech. The
  question is whether the SYSTEM has prior facts, not whether you do.
- Don't speculate about versions or compatibility. List what's named.
