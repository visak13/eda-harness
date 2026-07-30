# Planner — Phase Ground (read the recipe BEFORE you author)

You are a freshly-spawned planner. **Do this phase alone — do NOT load a
shape guide, do NOT call `create_plan`, do NOT author anything yet.**
The single biggest token waste a planner commits is authoring a plan for
the wrong task and discarding it; this phase exists to prevent that, and
it must finish before authoring begins.

`next_action(handle_type="plan")` fails until a plan exists, so don't
call it here. Your step description is a **pointer, not the whole
story** — the recipe is the source of truth, and it carries the context
that keeps you from misreading the job.

## Step 1 — read the recipe through the object surface

Your `EDP_HANDLE` is `<recipe_id>:<step_id>` — split on the **last** `:`.
Read the recipe via the link (your plan will back-link to this
`recipe_id`):

```
read_object("recipe", recipe_id="<recipe_id>")
```

> **NEVER raw-read the `.recipes/…` file** (no `Read`/`cat`/
> `Get-Content`/`ConvertFrom-Json`/`json.load`, no improvised
> PowerShell/python). The path is an implementation detail; guessing it
> (e.g. `edp-pool/.edp_state/…`) is a top wasted-token failure.
> `read_object` knows the path and hands you a clean dict. If the MCP
> tools are unreachable, that is a BLOCKED state to surface — never a
> cue to reach for files.

Then extract:

- **`comprehension.expected_outcomes`** — what this goal must ACHIEVE.
  Your step contributes to these; they define "done".
- **`context.decisions`** — choices already made. Do NOT re-litigate or
  contradict them.
- **`context.assumptions`** — operating constraints to plan within.
- the step whose `step_id` matches your `<step_id>` — its `description`
  is your plan goal.

> **Cold-start / post-compaction re-ground.** On a *fresh* spawn the
> `read_object("recipe")` above is what you want. If instead you are
> re-grounding after a context compaction, pull
> `get_recipe_digest(recipe_id=<recipe_id>)` — a <10k-token,
> code-assembled (no-LLM) packet whose parts are the immutable
> `north_star` (the fixed goal + auto-derived constraints), recap,
> outcomes, active decisions, open steps and recent events, standing in
> for the raw re-read. Load-bearing decisions come back digest-form;
> fetch full text on demand with `read_object("recipe")`.

## Step 2 — the grounding (misread) check

This is your **comprehension** — it's what the neuron gets from
`next_action` and you don't, so you must do it deliberately. Confirm
your reading of the step against the outcomes:

*If the step seems to be about X but no `expected_outcome` supports X,
you have MISREAD it — re-read before authoring.*

Plan **with** the outcomes/decisions, not off the step string and your
own interpretation. Do NOT `broker_send` the neuron asking for context,
do NOT `recall` — it is on disk, behind the `recipe_id` link.

> **Two classes (don't conflate).** Surfacing an ordinary reading as a
> grounding note (flag it, then PROCEED) is UNCHANGED; but if being wrong
> about this would cost the user a day, it is not a grounding note —
> record it via `record_context(kind=assumption, load_bearing=true)` and
> let the gate hold dependent work.

## Step 3 — write the GROUNDING BRIEF (v7 P8, after create_plan)

Your grounding must not die with your context window: the neuron read
the code, you re-read it, and every worker used to re-read it AGAIN —
three explorations, none shared. So once `create_plan` gives you a
plan_id (author phase), your FIRST recorded act is the brief:

```
record_grounding_brief(plan_id=<plan_id>, content="<markdown>",
                       paths=["src/…", "tests/…"])
```

Content: the files in play with a one-line role each, key symbols and
signatures, invariants you discovered, landmines ("X looks unused but
backs Y"), and the test entry points. `paths` is DATA — the same list
arms the staleness gate (a sibling plan's diff touching a named path
forces a revalidation before you dispatch over it). Every worker AND the
reviewer receives the brief automatically at dispatch; when a worker's
`discovery` event contradicts it, re-record the corrected brief — it is
a living map, not a ceremony.

## When you're done

You now hold the grounded goal + outcomes + decisions in context. Go
straight on to author the plan: `get_guide("planner-phase-author")`.
Stay in THIS same shell — authoring (and the dispatch it now interleaves)
needs this grounding fresh, so grounding and authoring are never split
across shells.

## Anti-patterns

- **Loading a shape guide or calling `create_plan` in this phase.** That
  is the author phase. Ground first, author second — never fused.
- **Skipping the misread check** because the step "seems obvious." The
  obvious reading is exactly what drifts from the outcomes.
- **Asking the neuron or `recall`-ing for context** that is already on
  disk behind the `recipe_id`.
