# S10 OpenCode Harness Root-Cause Report

**Boundary audited:** `C:\Projects\Learning\eda-base3\opencode-fleet` only. No
Claude command, guide, engine, or sibling-stack file was inspected or changed.

## Evidence collected

| Local artifact | Relevant evidence |
| --- | --- |
| `.opencode/agents/edp-reviewer.md:4, 11-19` | QA uses Sol, but delegates its complete protocol to the sibling Claude reviewer command; its only local behavioral statement is “verify and fix inline per protocol.” |
| `.opencode/agents/edp-agentic-plan.md:4, 11-28` | The Team Lead is configured as Terra and likewise delegates planning/dispatch semantics to the sibling command. |
| `.opencode/agents/edp-worker.md:4, 11-19` | Coder is correctly configured as Terra, but has no local routing contract that distinguishes substantial remediation from QA inline repair. |
| `HARNESS.md:3-8, 17-30, 76-94` | The harness calls the sibling commands canonical, says their contents win, and supplies OpenCode harness/coordination substitutions. It contains neither a QA repair boundary nor a review-verdict closure rule. |
| `opencode.json:4, 8-34, 38-53` | Terra/Sol models are registered, but configuration only selects a default model and starts the shared `edp_claude.mcp_server`; it has no routing or terminal-state policy. |
| `m1_smoke.py:3-22` | The only local smoke check exercises OpenCode launch/session capture while importing the external pool launcher. It does not create a review finding, dispatch remediation, or assert plan closure. |
| `shell_tui.cmd:1-16` | The local shell startup script only starts/attaches OpenCode. It performs no role/brief validation. The expected `start-stack.bat` named in the grounding brief is not present in this repository. |

## Root causes

### 1. Sol inline-fix scope is not locally defined or tested

The reviewer wrapper names Sol and says “fix inline,” but it imports all
operative review behavior from a sibling Claude command. Locally there is no
definition of *in-scope*, *safe*, or the required post-fix re-verification;

### 2. Terra/Sol routing is represented as static model labels, not a dispatch rule

`edp-worker` is Terra and `edp-reviewer` is Sol, which is a useful starting
assignment. However, `edp-agentic-plan` is also Terra even though it is the
judgment/dispatch seat, and none of the wrappers or `opencode.json` defines
the required branch: Sol repairs a safe in-scope QA finding; otherwise the
planner creates a Terra remediation action and a fresh Sol review. The shared
MCP server is launched from the sibling environment, so the local fleet has
no adapter that can enforce this branch or generate an auditable remediation
brief.

### 3. Claude-only regex approval leaks through the declared canonical path

No OpenCode-local artifact found in this audit creates a regex approval gate.
The leakage path is instead explicit: every role wrapper points to a sibling
Claude command, while `HARNESS.md` says that command wins. Thus any
Claude-only regex policy reachable from the canonical worker/reviewer stack
becomes operative in OpenCode despite the required OpenCode behavior being
“regex is an ordinary technical choice.” This is a boundary/precedence defect,
not evidence that regex itself needs an operator decision.

### 4. Failed review cannot be made closure-blocking by this repository today

The local repository contains launch/resume helpers and role prompts, but no
plan-state or verdict-transition implementation. `opencode.json` launches
`edp_claude.mcp_server` from the sibling Claude virtual environment, while
`m1_smoke.py` imports `OpencodeSpawner` from the separate `edp-pool`
repository. Therefore there is no local transition that turns a failed reviewed
action into a plan-success blocker, and no local test of that invariant. A
prompt-only change cannot reliably enforce terminal plan state; the state
owner must expose a local policy/adapter seam or a boundary-safe dependency
configuration that is testable from this fleet.

## In-boundary remediation plan

1. **Create an OpenCode-local role-policy asset** under `.opencode/` and have
   each role wrapper load it after `HARNESS.md`. It must state, without
   importing sibling behavioral rules: Sol QA repairs every safe, in-scope
   finding inline (not merely small findings), reruns its gate after repair,
   and reports a truthful verdict; substantial/unsafe/out-of-scope work is
   converted into a Terra remediation action followed by a fresh Sol review.
2. **Correct routing at the wrappers/config boundary.** Keep the worker on
   Terra and reviewer on Sol; move the judgment-heavy Team Lead wrapper to Sol
   or document/test an equivalent Sol decision handoff. Add an explicit
   structured remediation-brief contract containing `finding`, `scope`,
   `safety`, `route`, and `requires_fresh_sol_review` so routing is data, not
   prose alone.
3. **Remove the precedence leak locally.** Replace the blanket “sibling
   command wins” protocol import for OpenCode behavioral policy with a local
   OpenCode protocol/overlay. Retain only genuinely shared mechanics where
   needed, and state that regex syntax alone neither blocks work nor requires
   operator approval. Do not edit the sibling Claude policy.
4. **Add a local lifecycle adapter/policy seam before claiming closure is
   fixed.** The adapter must consume a review verdict and reject plan success
   when the reviewed action failed; it must permit success only after the
   corresponding Terra remediation and fresh Sol PASS. If the shared MCP/pool
   cannot expose such a seam without editing the sibling implementation, this
   is a hard boundary blocker to report upward rather than paper over in
   prompts.
5. **Use `shell_tui.cmd` as the tested local startup path** (or add the
   missing `start-stack.bat` explicitly and update the grounding brief). Its
   smoke test should prove the configured role/model and policy asset are the
   ones actually loaded.

## Required tests for the remediation action

1. A fixture with a safe but non-trivial QA finding asserts Sol edits it,
   reruns verification, and emits PASS only after the re-run.
2. A fixture with substantial work asserts creation of a Terra remediation
   brief and requires a new Sol review; it must not accept the original
   review as final.
3. A regex-containing ordinary implementation fixture asserts no
   operator-approval/escalation transition is generated solely for regex.
4. A failed-review fixture asserts the plan cannot enter succeeded until the
   failed reviewed action is remediated and freshly passed.
5. A startup/config test runs the local `shell_tui.cmd`/configured agent path
   and asserts Terra worker, Sol reviewer, and the local policy asset are
   selected. Keep it isolated from sibling Claude paths.

## Completion boundary

This diagnosis intentionally makes no harness implementation change. The
next action must preserve this repository-only boundary and first establish a
testable local lifecycle seam; otherwise it can improve prompts but cannot
prove the failed-review closure requirement.
