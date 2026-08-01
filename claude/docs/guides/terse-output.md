# Output discipline — every role, every turn

Two failure modes, one guide. Measured live: ~80% of a neuron session was
self-narration (a closing status ritual on all 77 wakes + re-derivations of
things the record already held). The first fix suppressed volume; this
revision adds what was missing — STRUCTURE. Terse does not mean fragmentary:
an unstructured trickle of half-sentences is as unreadable as the essay it
replaced.

## When you write, write pyramid

Every message that carries content follows this shape — no exceptions:

1. **Line 1 = the point.** The verdict, the action taken, or the ask —
   stated as a complete sentence a reader could act on alone.
   `a3 failed its verify: the CSV export writes 0 rows.` Not the journey,
   not "Looking at a3…".
2. **Then the support, as bullets.** 2-5 bullets max, one fact each:
   evidence pointer, the record id it rests on with a 5-10 word gloss
   (`d35 — escrow slots settle at close`), the constraint that binds. A
   bare id with no gloss is cryptic, not terse.
3. **Then the next move, if any.** One line: what you will do, or the ONE
   question with its options and your recommendation.
4. **Stop.** No recap of what you just said, no restated state, no
   closing ritual.

Tables for enumerable state (3+ rows of the same shape); prose sentences
for reasoning; bullets for support. Never a stream of clause-fragments —
complete sentences, just few of them.

## What never gets written

- **A no-change wake emits NOTHING.** `reconcile.changed=false` + wait ⇒
  end the turn silently. The state machine is queryable.
- **No narrated grounding.** Call the tool; don't announce before and
  after. The tool trail is the narration.
- **No re-derivation of settled record.** Cite the id + gloss (see above);
  if your framing differs from the record, the record wins.
- **No re-explanation of a standing condition** you already explained this
  session. Once.
- **No preamble** ("Great", "Let me", restating the ask) and **no closer**
  ("ending the turn, s8 at 2 done…").
- **Self-corrections are one line**: `Correcting: X, not Y (per dN).`

## Reports and verdicts

Done work: line 1 = what shipped; bullets = evidence pointers (paths,
counts, verify output); `record_action_status` carries the full evidence —
the message is the receipt, not the report. Reviewer verdicts: line 1 =
pass/concerns/fail + the one decisive reason; findings as bullets ordered
most-severe first.

## Why this is safe

Nothing here hides information: every state this prose used to restate is
in the recipe/plan record, the digest, or the worklog — queryable, durable,
cheaper there. The rules cut restatement and fragmentation, never evidence.
