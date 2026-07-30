# Terse output — every role, every turn

Measured on a live neuron transcript: ~80% of the burn was the agent's own
prose — a ritual turn-closing status report on all 77 wakes (34.5% of the
whole session) and re-derivations of things the record already held. These
rules delete that class. They bind every role.

## The ten rules

1. **Lead with the action.** First line = what you are doing or what changed.
   No "Great", no "Let me", no restating the ask.
2. **A no-change wake emits ZERO prose.** `reconcile.changed=false` +
   `next_action` says wait ⇒ end the turn silently. The state machine is
   queryable; a report on an unchanged state is pure cost.
3. **No closing status ritual.** Never end a turn with "ending the turn,
   s8 at 2 done…". The record holds the state; anyone who needs it reads it.
4. **Cite ids, don't re-derive.** A settled decision is `d35`, not three
   paragraphs reconstructing it. If your framing differs from the record,
   the record wins — say `per d35` and move.
5. **Ground silently.** Call the tool; don't narrate that you are about to
   check, then narrate that you checked. The tool trail IS the narration.
6. **One statement per fact.** Explained a standing condition once? Do not
   re-explain it on the next wake, or the one after (observed: the same
   queue explained three times at 6, 7 and 10 pending).
7. **Number multi-step work; suppress tangents.** If it doesn't change what
   happens next, it doesn't go in the message.
8. **Questions to the operator: the question, its options, your
   recommendation.** Not the journey that produced it.
9. **Self-corrections are one line.** "Correcting: X, not Y (per dN)." Not a
   re-litigation of the decision you just made.
10. **When work is done, say what shipped and stop.** Evidence pointer, not
    an essay. `record_action_status` is the report; the message is a receipt.

## Why this is safe

Nothing here hides information: every state this prose used to restate is in
the recipe/plan record, the digest, or the worklog — queryable, durable, and
cheaper there. The rules cut restatement, never evidence.
