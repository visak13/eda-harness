# Neuron — Phase A (init)

You are at the start of a recipe. This phase decides whether to
**resume** an existing recipe (your work survived a compaction or new
session) or **create** a new one. Either path, you do NOT hand-author
the recipe object.

## Step 1 — resolve before creating

`resolve_recipe(goal=<user's exact text>)`. Act on `decision`:

- `resume` — open recipe exists for this goal.
  **Do not author a new recipe.**
  Use the returned `recipe_id` as your handle. Go to Phase B.
- `confirm` — open recipe(s) exist but the typed text didn't exactly
  match. The result carries `open_recipes` (id + goal, most-recent
  first). **If the user's input was a RESUME intent** ("resume",
  "continue", "keep going", "resume working") **rather than a fresh
  goal**, this IS the resume path: if there's one open recipe, resume
  it (use its `recipe_id`, go to Phase B); if several, surface the
  `open_recipes` list and ask which to resume. Otherwise (the input
  looks like a new goal) surface: *"You have N open recipe(s) — e.g.
  `<recipe_id>` for `<matched_goal>`. Resume one, or start fresh?"* —
  resume or create per their answer. **Never `start_recipe` while an
  open recipe exists without the user choosing — creating orphans the
  open work.**
- `create` — NO open recipe exists at all. Call `start_recipe(goal=
  <verbatim goal>, domain=<one word>)`. The tool fills
  `recipe_id`/state/timestamps; you do NOT hand-author recipe JSON.

Closed recipes are not resumed — re-running a completed goal correctly
starts fresh. (A bare "resume working" with one open recipe → `confirm`
with that recipe in `open_recipes` → resume it; this is the
2026-05-26 fix for resume-by-intent.)

## Step 2 — enter the outer loop

`next_action(handle=<recipe_id>, handle_type="recipe")`. Read its
`context.phase`; the FSM has now advanced you to Phase B. Load that
guide and continue.

## Anti-patterns

- **Hand-authoring the recipe with `record_recipe`.** That's the raw
  escape hatch. Use `start_recipe` (creates) or `resolve_recipe` →
  `resume` (continues).
- **Skipping `resolve_recipe`** — every activation, before creating.
  Otherwise re-running the same goal starts over and loses prior work.
- **Asking the user to confirm before you've even resolved** — only
  the `confirm` branch warrants surfacing; on `resume`/`create` just
  proceed.
