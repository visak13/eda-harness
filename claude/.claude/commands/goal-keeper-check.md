---
skill: goal-keeper-check
hosts: [neuron]
inputs:
  recipe_id: str
outputs:
  writes: [recipe.comprehension.expected_outcomes]
  via: [record_recipe]
unload: after emitting the drift verdict, end skill
---
You are the goal-keeper check. Compare the recipe's current trajectory to
`user_goal_verbatim` + `expected_outcomes`. Decide: aligned, or drifted.

If aligned and all outcomes verifiably met, mark each outcome `met` and
persist via record_recipe(recipe). If drifted, add a `needs_user_input`
branch describing the drift and persist via record_recipe(recipe) so the
harness reopens comprehension.

# TODO(edp-fsm,#5 / cluster): a richer drift score belongs in the
# masked-LLM path; the skeleton uses this deterministic-ish check.

After emitting the verdict, end skill (unload).
