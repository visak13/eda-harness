# S4 — Acceptance (Base Contracts, component #1)

**Shape:** internal / non-interactive component (METHODOLOGY S4 case (a)).
`edp-contracts` is a contracts library — no user-facing behaviour to drive
by hand. The automated S3c result is the acceptance evidence; a manual
terminal reproduction would add ceremony without information.

## Evidence reviewed
- 38/38 tests pass via `uv run --extra dev pytest`.
- Ruff clean incl. flake8-print (no-`print()` enforced) + import order.
- Coverage: `tool.py` 100%, `broker.py` 100%, total 96%; ST-1 (pydantic-only
  import), ST-2 (<200 ms cold import) green.
- Load-bearing guarantees proven by tests: verbatim `propagate()`; `Tool`
  ABC blocks incomplete subclasses; `from_upstream` raises loudly on a
  non-envelope error; unregistered broker kinds rejected at construction;
  structured-log mandatory fields; lazy-FastAPI keeps the package light.
- 5 real defects were found and fixed by the suite during S3c.

## Verdict
**ACCEPTED — 2026-05-16** (user: "Please continue"). Component #1 is done.
Proceed to component #2 (`claude/` skeleton).

> Methodology note recorded from this gate: S4 for internal/non-interactive
> components = review automated evidence + sign. Heavyweight by-hand HITL is
> reserved for user-facing behavioural components (the neuron/recipe flow).
