# Planner shape: modular-build

> **OPTIONAL ACCELERATOR** — a pitfall checklist for a DAG you already
> drew (planner-phase-author Step 1). Never contort work to fit this
> file; a DAG matching no shape is normal — proceed with your DAG.

**When this shape applies:** the goal has predictable **axes of
variation** the user will plausibly want next. Caesar+Brutus →
Caesar+Cleopatra+Egypt is the canonical case: characters and scene
are obvious config inputs to the same engine. Building a hard-coded
version creates rework when the variation request arrives.

The fix is **module decomposition** so the produced system is
config-driven from day one.

## Mandatory pre-step — axes-of-variation question

Before authoring the plan, ask the neuron (or the user, escalated
via the neuron) which axes are likely to change:

```
ask_above(question="Axes of variation likely to change?",
          body={"examples": [
            "different inputs (characters, dates, files)",
            "different outputs (format, channel, language)",
            "different scale (one item → batch)"
          ]})
```

End your turn, wait for the answer. Without this, you'll guess the
wrong split.

## Plan structure

- Decompose into **modules** along the named axes. Each module is a
  set of actions producing a self-contained, config-consumed
  component.
- Actions per module typically: `define interface` → `implement` →
  `test`. Each module's `test` action's acceptance is a contract test
  that validates the module against its interface, not the system.
- A final integration action wires the modules together; its
  acceptance is an end-to-end smoke test.

## Action sizing

- Each module should be one focused unit of work — typically 2-4
  actions per module.
- Total plan: ~3 modules × 3 actions ≈ 9 actions. If you find
  yourself with 6+ modules, the decomposition is too fine.

## Anti-patterns

- **Hard-coding the first variant.** Defeats the purpose of this
  shape. If your first action is "implement Caesar's monologue,"
  you're in linear-build, not modular-build.
- **Skipping the axes question.** Going on intuition picks the wrong
  axes 50% of the time. Ask.
- **Decomposing into modules that don't share an interface.** Then
  you've just made a flat plan with extra rituals.
