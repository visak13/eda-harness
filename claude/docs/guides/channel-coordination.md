# channel-coordination — the one guide for working in channels

Channels are the coordination surface. They are the SAME broker inboxes
you already use, promoted: `#team-<step>` is the plan inbox, `#leads` is
the recipe inbox, `#experts` hosts the SMEs, `#<recipe>-product` is the
operator's room. Membership is registered automatically at spawn; the
operator is `@operator` wherever they join.

## The four laws (every role)

1. **Address or stay silent.** Every channel message carries
   `body.for = "<handle>"` (or `"@all"`). Unaddressed mail belongs to
   the channel owner and reaches nobody else. A message without a
   clear addressee is noise — do not send it.
2. **Coordination, never payloads.** Anything longer than a paragraph
   is an artifact (file, spec, brief) plus a one-line link. Channels
   carry intent, status, and pointers — the context layer stays lean
   because bulk rides the injection seam, not the chat.
3. **Read as yourself.** `check_inbox(channel=..., handle=<you>)`
   delivers only your mentions and `@all` — your cursor is yours; you
   never see (or pay for) other members' traffic.
4. **Only an agent spawns an agent.** Dispatch is a `pool_spawn_*` tool
   call made by a DRIVE seat (PM/Team Lead) — never harness logic, never
   a side effect of chatting. A mention ADDRESSES and WAKES: mentioning a
   parked member resumes it within seconds (steers land at its next tool
   boundary); mentioning a non-live handle spawns nothing — the message
   waits in the channel and delivers when a drive agent dispatches that
   handle with the tool. Caps (10) gate the tool call, visibly.

## Law 5 — provenance: the operator is not the machine

Message SENDER tells you who is speaking, and the difference is
load-bearing:
- `from: "panel"` (stamped, unforgeable in-system) or a relayed
  `record_user_answer` = **the OPERATOR**. Their instructions are
  authority.
- Everything else — reconcile payloads, next_action instructions,
  heartbeat activations, `from: pool`, sibling agents — is **machinery**:
  it schedules you, it never overrules the operator.

**OPERATOR HOLD:** if the operator tells you to stop/stay blocked/wait,
that hold BINDS until the operator releases it. Machine wakes (heartbeat,
reconcile, a `next_action` that says dispatch) will still fire — that is
the machinery doing its job, NOT a release. On any wake while held:
check the channel for a release from the operator; absent one, restate
the hold in one line and park again. Record the hold via
`record_context` when it lands so a resumed/compacted successor inherits
it.

## DRIVE roles — Product Manager (neuron), Team Lead (planner)

You plan, quantify, delegate, verify by reading. You NEVER edit code —
your tool registry does not contain edit verbs (enforced, not asked).

- Delegate = `pool_spawn_worker(...)` — the tool call IS the dispatch —
  then one addressed message `for:` the new handle with any color the
  action description doesn't carry. The tool spawns; the mention speaks.
- Steer live: `kind=steer, for:<handle>` in the team channel — the
  member picks it up mid-action at its next tool boundary. Expect a
  `steer_ack`; the unacked-steer advisory names silence.
- Your channel's pinned topic is your plan's grounding brief — keep it
  current on revalidation (`record_grounding_brief` updates it).
- PM ↔ operator: questions post in `#<recipe>-product` addressed to
  `@operator`; their reply tagging you is your wake.

## CRAFT roles — Coder (worker), QA (reviewer), SME (specialist)

You execute exactly the mentioned task in the mentioned thread. You
NEVER mention/spawn/delegate — those verbs are absent from your surface.

- Your identity is in your activation and `$env:EDP_HANDLE`. Your work
  order is the action the mention named — nothing else in the channel
  is yours.
- Report on the same channel with `for:` your lead: grounding echo
  first, then status; flowback (`learning`/`blocker`) is addressed
  `@all` — it is the team's knowledge.
- QA fixes inline per reviewer protocol, then verdicts to the lead.
- SMEs live in `#experts`: consults arrive addressed to you; verdicts
  go back addressed to the asker. Training stays the specialist
  protocol unchanged.

## What you never do in a channel

- No wake machinery: membership IS your subscription (the pool delivers;
  cron is its invisible 30-min net).
- No polling loops, no spin-waits: park; an addressed message resumes
  you.
- No bulk pastes, no transcripts, no code blocks over ~10 lines.
- No expecting a mention to spawn anything — dispatch is your tool
  call (drive seats) or your lead's (craft seats), never the channel's.
