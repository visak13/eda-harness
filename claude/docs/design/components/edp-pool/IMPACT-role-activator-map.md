# IMPACT — role→activator map (change to built #4)

**Process:** §5.5 note before the change.

**Trigger:** HITL — the v5 spine ran end-to-end up to the planner spawn,
then deadlocked. Planner shell: `Unknown command: /planner`. Neuron
`next_action` → `wait` forever (planner never runs → never emits
`plan_closed`).

## Root cause
`pty_launcher.activation_text(role)` returns `f"/{role}"`. The pool
spawns the planner with `role="planner"` → activation `/planner`. But
the planner activator is `.claude/commands/agentic-plan.md` →
`/agentic-plan`. No `/planner` command exists. The worker path worked
only coincidentally (`role="worker"` → `/worker`, and `worker.md`
exists). The role string was never mapped to the actual command name.

## Fix
`activation_text` uses an explicit role→command map:
`{"planner": "/agentic-plan", "worker": "/worker", "neuron": "/neuron"}`
(unknown role → `f"/{role}"` fallback, so it fails loudly rather than
silently mis-activating). Keeps the meaningful `/agentic-plan` name
(the proven concept the user values) while the pool's role string stays
`planner`.

## Blast radius
edp-pool only — `pty_launcher.activation_text`. No schema/contract/other
repo change. `SubprocessSpawner`/`ConsoleLaunch` call it unchanged.
`test_activation_text` updated to assert the mapping for planner/worker;
SUB tests unaffected (they pass role="worker").

## Risk
Low. Pure string-mapping correction. The deadlock is removed only when a
real planner shell actually runs `/agentic-plan` — verified next HITL
(the unit test asserts the mapping; the live run proves the shell
activates and replies).

## Verdict
One-line-class correctness fix unblocking the whole spine. Proceed.
