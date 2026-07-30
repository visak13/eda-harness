# IMPACT — activators must read the env brief (change to built #2)

**Trigger:** manual HITL 2026-05-18 step 3.5. A spawned `/worker`
launched correctly (agent-home, profile, MCP) but **dropped into an
interactive menu asking the user for the brief** instead of reading it
from the environment. `SubprocessSpawner.build_env` already sets
`EDP_ROLE` / `EDP_HANDLE` / `EDP_BROKER_URL`; the activator prose
(`worker.md`, `agentic-plan.md`) was generic and never wired to that
contract. §5.5 note before the change.

## What changes (prose only — no code, no schema, no contract)
- **`.claude/commands/worker.md`**: first action = read
  `EDP_ROLE/EDP_HANDLE/EDP_BROKER_URL` (via the Bash tool). For a worker
  `EDP_HANDLE = "<plan_id>:<action_id>"`. Read `.plans/<plan_id>.json`,
  find the matching action = the brief, execute it,
  `record_action_status(done, evidence)`. **Autonomous: never prompt the
  user / never render a choice menu.** If `EDP_HANDLE` is empty OR the
  plan/action is not found → report cleanly and stop (preserve the
  no-invent-work discipline that already works).
- **`.claude/commands/agentic-plan.md`**: same env-read preamble;
  `EDP_HANDLE = "<recipe_id>:<step_id>"`; then the existing `next_action`
  loop. Non-interactive.
- **`neuron.md` unchanged** — the neuron is the user's *main* shell; its
  goal comes from the human (`/neuron <goal>`), not from spawn env.

## Blast radius
- `eda-base/claude/.claude/commands/` markdown only. No Python, no MCP
  tools, no schemas, no `edp-contracts`. No other repo touched.
- `worker.md`/`agentic-plan.md` are activator commands, not `Skill`-
  contract skills, so `validate_skill` does not apply (only ocak/
  goal-keeper-check/critic-review carry SkillHeader). No test breakage.
- Adds a light test asserting the activators reference `EDP_HANDLE` and
  state "do not ask the user" (guards against regressing to the
  interactive-menu behaviour).

## Risk + mitigation
- Reading env relies on the spawned claude using the Bash tool
  (`$env:EDP_HANDLE`). Acceptable — claude has Bash; this is the
  standard way an agent inspects its environment. (A future `whoami`
  MCP tool could make it tool-native; out of scope now — incremental.)
- Known *separate* gap (NOT fixed here, flagged): the MCP server
  (`edp_claude.mcp_server`) uses `make_context` = **stub** broker/pool.
  Fine for the isolated worker-with-brief test (worker reads plan +
  writes `record_action_status` to disk via the real stores; no
  cross-shell broker needed). The full `/neuron` spine will need the
  MCP server on `make_http_context` (real broker/pool) — its own
  change, flagged for that milestone.

## Verdict
Minimal prose wiring to an already-existing env contract; isolates the
exact HITL failure. Proceed.

## Addendum — 2026-05-18 HITL #4 PASS + bash-syntax nit
Re-run PASSED end-to-end: worker read env brief, read plan, created
`.demo-scratch/hello.txt`=`edp ok`, called `edp-claude`
`record_action_status(done)`, stopped cleanly. Isolated
worker-with-brief loop proven live. Nit: env-read hint used PowerShell
`$env:VAR` but the Bash tool runs **bash** (first attempt printed
`:EDP_ROLE`; worker self-corrected). `worker.md`/`agentic-plan.md` now
lead with bash `$VAR`. Regression tests still green.
