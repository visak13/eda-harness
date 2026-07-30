---
skill: ocak
hosts: [neuron]
inputs:
  recipe_id: str
outputs:
  writes: []
  via: []
unload: nothing to do here — end skill immediately
---
RETIRED (DESIGN-v5 P1). OCAK is no longer an LLM-invoked skill — that was
skippable/shallowable and recreated guess-and-resolve.

Comprehension is now **forced by the tool**: `next_action` seeds the
fixed OCAK checklist and returns `answer_branch` one branch at a time;
the FSM refuses to advance until each is substantively resolved. You
(the neuron) answer each via `record_branch_verdict`, then
`record_outcome`, then `add_step`.

If something invoked this skill: there is nothing to run — end skill
immediately and return to the `next_action` loop.
