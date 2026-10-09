# Bounded F1–F5 / Q1 recheck

Product revision: `b4b35b1b`, incorporating fix `8e751c9e`.
Verdict: **F1, F3, F4, F5 and Q1 pass; F2 retains a consecutive-selection defect.**

## Results actually run

| Command / scope | Result |
| --- | --- |
| From v8: `.venv/Scripts/python.exe -m pytest tests/test_requirements.py tests/test_e0cec_s5_guest.py tests/test_admin_access.py -q` | 76 passed in 53.60s. |
| From v8: `.venv/Scripts/python.exe -m pytest docs/evidence/s-aa76-recheck/test_reopen_boundary.py -q` | 5 passed in 1.19s. |
| Private snapshot: QuoteCard, QuoteLayer, Requirements and retiredLabels tests | 21 passed. |
| Private snapshot: `RequirementRecheck.test.tsx` | 1 failed: the second selected passage still has a disabled “Marked as requirement” button. |

The independent F4 matrix checks done/partial reopen once with the exact board trigger and hint; dropped/in_progress stay unchanged. Duplicate marks, reads, links, ordinary messages and refused marks do not reopen a completed epic. Only a new valid mark does.

## F2 residual reproduction

1. Select “first” in a message containing “first second”.
2. Press Mark as requirement and wait for success. One request records range `[0,5)`.
3. Directly drag-select “second”, without dismissing the popup between selections.
4. The new selection is “second”, but the mark button remains disabled and says “Marked as requirement”. No second requirement is recorded.

`QuoteLayer.tsx:156` changes the selection but preserves its unkeyed `MarkButton` at line 250. `QuoteCard.tsx:56` retains the old done state, and line 71 disables the button. State must be bound/reset to the selection identity, including handling stale asynchronous completions.

Copy `RequirementRecheck.test.tsx` into an isolated snapshot's `web/src/components/`, then run from that `web`:

```text
npx vitest run src/components/RequirementRecheck.test.tsx
```

The test asserts desired fixed behavior and intentionally fails at `toBeEnabled()` on the reviewed revision. A second run with the incidental people lookup mocked failed identically without an MSW warning.

The web tests used `git archive b4b35b1b v8/web` extracted over this seat's existing private snapshot, retaining the same locked dependency installation. The snapshot path's d1622ad2 suffix is historical; its tracked source was overwritten from b4b35b1b before testing. No shared dist build, live service restart, product edits, full suite or installed-build UI verdict was performed. No test processes remain running.
