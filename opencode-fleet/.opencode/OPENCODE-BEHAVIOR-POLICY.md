# OpenCode fleet behavioral policy

This policy is authoritative for behavior implemented by this OpenCode fleet.
It is loaded by every local role wrapper before any shared mechanics reference.
Shared infrastructure may supply tool names and wake-plane mechanics, but it
does not override this policy.

## Seats and review routing

- Terra performs substantial implementation and Terra remediation.
- Sol performs QA and judgment.
- Sol fixes every safe, in-scope finding inline, regardless of size label,
  reruns the affected verification, and reports a truthful verdict.
- A substantial, unsafe, or out-of-scope finding produces a remediation brief
  with `finding`, `scope`, `safety`, `route: terra`, and
  `requires_fresh_sol_review: true`. The original review cannot be final.
- Regex syntax alone is an ordinary technical choice. It creates neither an
  operator-approval gate nor an escalation.

## Closure rule

A reviewed action that failed blocks succeeded closure. Closure is permitted
only after its Terra remediation is recorded and a *new* Sol review passes.
`opencode_policy.py` is the executable adapter for this rule; callers must use
its decision rather than treating a completed failed review as success.
