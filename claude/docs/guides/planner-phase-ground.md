# Planner — Phase Ground (read the recipe BEFORE you author)

You are a freshly-spawned planner. **Do this phase alone — no shape
guide, no `create_plan`, no authoring yet.** The single biggest token
waste a planner commits is authoring a plan for the wrong task and
discarding it; this phase prevents that. `next_action(
handle_type="plan")` fails until a plan exists, so don't call it here.
Your step description is a **pointer, not the whole story** — the
recipe is the source of truth.

## Step 1 — read the recipe through the object surface

Your `EDP_HANDLE` is `<recipe_id>:<step_id>` — split on the last `:`.

```
read_object("recipe", recipe_id="<recipe_id>")
```

Never raw-read the `.recipes/…` file — the path is an implementation
detail, and `read_object` hands you a clean dict. If the MCP tools are
unreachable, that is a BLOCKED state to surface, never a cue to reach
for files.

Extract:

- **`comprehension.expected_outcomes`** — what the goal must ACHIEVE;
  they define "done".
- **`context.decisions`** — choices already made. Do not re-litigate
  or contradict them.
- **`context.assumptions`** — operating constraints to plan within.
- the step matching your `<step_id>` — its `description` is your plan
  goal.

Re-grounding after a compaction instead of a fresh spawn? Pull
`get_recipe_digest(recipe_id=<recipe_id>)` — a small code-assembled
packet (north star, recap, outcomes, active decisions, open steps) —
and fetch full text on demand with `read_object("recipe", ...)`.

## Step 2 — the grounding (misread) check

Confirm your reading of the step against the outcomes: *if the step
seems to be about X but no `expected_outcome` supports X, you have
MISREAD it — re-read before authoring.* Plan **with** the
outcomes/decisions, not off the step string alone. Don't ask the
neuron or `recall` for context that is on disk behind the `recipe_id`.

Two classes, don't conflate: an ordinary reading gets surfaced as a
grounding note (flag it, then PROCEED); a reading whose wrongness
would cost the user a day is recorded via
`record_context(kind=assumption, load_bearing=true)` so the gate holds
dependent work.

## Step 3 — write the GROUNDING BRIEF (after create_plan)

Your grounding must not die with your context window. Once
`create_plan` returns a plan_id (author phase), your FIRST recorded
act is:

```
record_grounding_brief(plan_id=<plan_id>, content="<markdown>",
                       paths=["src/…", "tests/…"])
```

Content: the files in play with a one-line role each, key symbols and
signatures, invariants, landmines ("X looks unused but backs Y"), and
the test entry points. `paths` is DATA — it arms the staleness gate (a
sibling diff touching a named path forces revalidation before you
dispatch over it). Every worker and the reviewer receive the brief
automatically at dispatch (truncation is loud at both ends —
enforced); when a worker's `discovery` contradicts it, re-record the
corrected brief — it is a living map, not a ceremony.

## When you're done

You hold the grounded goal + outcomes + decisions. Go straight to
`get_guide("planner-phase-author")` — in THIS same shell: authoring
(and the dispatch it interleaves) needs this grounding fresh.

## Anti-patterns

- Loading a shape guide or calling `create_plan` in this phase.
- Skipping the misread check because the step "seems obvious" — the
  obvious reading is exactly what drifts from the outcomes.
- Asking the neuron or `recall`-ing for context already on disk behind
  the `recipe_id`.
