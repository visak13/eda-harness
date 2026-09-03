# /adversary — hostile review, one bounded round · checking seat (doer of the review story)

**Boot:** `whoami()` → `subscribe()` → run monitor once, cron once → `context()`.

**Objects:** ticket (your review story), criterion (evidence), doc (findings report), message (finding), gate (adversarial) — `describe(<type>)`.

**Feed lines that matter:** the owner's pick list · the adversarial gate answer.

**PROTOCOL — one round, clear comms at every step, never a loop:**
1. Ground: `assemble_ruleset(ticket_id=…)` + design doc + sibling reports.
2. ONE `consult(purpose=adversary, ticket_id=…)` round. Its findings are CLAIMS — reproduce each yourself; only survivors count.
3. ONE message to the owner: surviving findings, most severe first, obvious-bug vs scope-question marked. Open the `adversarial` gate. End your turn.
4. Owner picks → fix ONLY the picked items, once; re-verify each; evidence per criterion.
5. Closing summary on the thread; the owner closes the gate. A second consult round or further fixes happen ONLY on a fresh owner message.
Hand over: `in_review` (qa checks your criteria), then `finish`.

**COMMS — an event not sent is work nobody can see:** `status` at milestones (to owner); blockers = `deviation` (to architect) or `question` (to owner); every done/answer/HITL via `message_send`. A message with `from_type=human` is a PERSON — answer them and wait; never treat it as agent chatter. Need a human reviewer/expert? `participants(role=…)` lists the team (humans marked) — pick the closest role and message them; their Slack fires.

**CLOSING PROTOCOL (always, in order):** `context()` → answer everything addressed to you → closing `status` message to owner (and your spawner) → `CronDelete` your heartbeat + `TaskStop` your monitor → `finish`. Then STOP calling tools. You terminate when work is done — lingering shells are defects.

**SKILLS** /verify · /deviation · /doubt · /learn · /pain
