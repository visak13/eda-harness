# S10 review-a2 verdict

**Verdict:** Fail on the supplied objective gate, with implementation defects
fixed inline and all stronger implementation checks passing.

## Inline fixes

- Corrected `route_finding` so regex syntax is routing-neutral and cannot make
  unsafe or out-of-scope work eligible for inline Sol repair.
- Added explicit out-of-scope coverage to the remediation route tests.
- Made the startup contract support and validate all nine local wrappers and
  compare its expected model with each wrapper's actual frontmatter model.
- Made every wrapper explicitly give the local policy precedence and expanded
  tests to enforce wrapper/model completeness and precedence.

## Fresh verification

- `python -m unittest -v test_opencode_policy.py`: 6/6 passed.
- `python -m py_compile opencode_policy.py startup_contract.py test_opencode_policy.py`:
  passed.
- `startup_contract.py` for all nine roles: passed; worker selected Terra and
  every judgment/QA/SME role selected Sol.
- `opencode debug config` and agent resolution for worker, reviewer, and
  specialist: passed and loaded the local policy-bearing prompts.
- Direct rooted repository count found 2,908 files, satisfying the intended
  minimum of three.

## Blocking gate defect

The acceptance criterion's verbatim Windows absolute glob
`C:\Projects\Learning\eda-base3\opencode-fleet\**\*` returned no matches in
the harness glob runner. The equivalent rooted search proves the files exist,
but reviewer protocol does not permit replacing a failed supplied criterion
with an equivalent and calling it passed.

Remediation brief: `finding=malformed absolute glob acceptance criterion`;
`scope=plan acceptance metadata`; `safety=out-of-scope for QA`; `route=terra`;
`requires_fresh_sol_review=true`. Replace the criterion with a supported rooted
glob or deterministic local command, then dispatch a fresh Sol review.

No sibling Claude file was edited during this review. This workspace has no
Git metadata, so repository history cannot independently prove the prior
worker's boundary; all implementation artifacts inspected and all inline
changes made here are under `opencode-fleet`.
