# Planner shape: gather-validate-submit

> **OPTIONAL ACCELERATOR** — a pitfall checklist for a DAG you already
> drew (planner-phase-author Step 1). Never contort work to fit this
> file; a DAG matching no shape is normal — proceed with your DAG.

**When this shape applies:** form-filling or external-submission goals
— "fill out the application," "submit the report to system X," "post
this to the API." The work is: gather inputs from the user/disk →
validate they match the target schema → submit and capture the
receipt.

This shape is intentionally **risk-averse** — the submit step is
typically irreversible (post a form, send an email, submit a
payment), so the validate step has to actually catch errors before
submit, not after.

## Plan structure: G → V → S

**G — Gather (1-N actions)**
- Each action collects one input class (read file, fetch from API,
  query user via `ask_above`).
- Acceptance: `{"kind": "fields_collected", "expected": "<list of
  field names>"}`.

**V — Validate (1 action, MANDATORY)**
- Reads the gathered inputs + the target schema.
- Checks every field against the schema (type, format, required-ness,
  cross-field constraints).
- Acceptance: `{"kind": "schema_validated", "expected": "0 errors"}`.
- **If any validation fails, do NOT proceed to S.** Surface to neuron
  / user.

**S — Submit (1 action, IRREVERSIBLE)**
- Single action. Performs the external submission.
- Acceptance: `{"kind": "receipt_captured", "expected": "<receipt
  format>"}`.
- Records the receipt in the recipe / worklog for the user.

## Mandatory pre-step — confirm before submit

Before authoring the S action, escalate to the neuron for sign-off:

```
ask_above(question="Validation cleared; submit?",
          body={"gathered": <summary>, "target": <target>,
                "irreversible": true})
```

End your turn, wait. Only S after explicit go-ahead. **The agent
must NOT self-approve an irreversible external action** — see also
`concern-validator` specialist.

## Anti-patterns

- **Submitting before validate clears.** The validate step exists
  precisely to catch errors. Skipping it converts a fixable schema
  mismatch into a hard external error you can't undo.
- **Self-approving the submit.** This is a concern-validator
  category-1 risk (automated personal action). Always escalate.
- **One mega-action for G+V+S.** They're separate failure surfaces;
  decompose so each is independently auditable.
