# Resume — what a resumed seat does, and why the transcript is history

Owner ruling m-268fc869f5 (2026-09-18): a resumed seat needs a proper resume command, not a line pasted into
a role card. The command is `resume_self()`. This guide is its contract.

## When you are "resumed"
Any of these means you are resumed, not freshly booted:
- the first input of this shell says "You were resumed" (the pool types that line on park/resume,
  reap/resume and resume-after-close);
- your transcript already holds a hand-off, a close_self, or work you do not remember finishing;
- your context was compacted and you cannot tell whether your Monitor and cron are alive.

A resumed shell is a NEW process. Whatever the transcript shows, its Monitor and cron died with the old
process; nothing wakes you until you arm them again. A hand-off in the transcript does not end this
session: you are live until you close again.

## The command
`resume_self()` regenerates, from the board, everything you must do next. It returns:
- `identity` — who you are (whoami);
- `steps` — the ordered list below;
- `monitor_cmd`, `cron`, `listening` — exactly what subscribe() returns: your wake plane;
- `open_asks` — every steer, question and human message addressed to you that still awaits an answer,
  oldest first, each with its `answer_with` call.
It also posts `[resumed]` on your thread so your spawner and the owner see the resume happened.
It is idempotent: call it again after compaction or whenever you are unsure you are armed.

## The steps, in order
1. Arm: run `monitor_cmd` under the Monitor tool once; CronCreate `cron` once.
2. Answer every open ask, oldest first, with its `answer_with` call. A steer changes your plan.
   A message with `from_type=human` is a person waiting.
3. `context(ticket_id=<your ticket>)` to reload the current state of your work; continue your plan
   from its next unbuilt item (plan doc + story thread are the durable memory, not the transcript).
   A resumed seat never trusts an old cursor: this full `context()` is the resync, and its `cursor` seeds
   every later heartbeat `context_delta(cursor=…)` (`get_guide('context-refresh')`).
4. `record_status` at the next milestone. Never end a turn silently while asks are open or your story is
   in_progress.

## What resume_self is not
- Not `context()`: context loads your tickets; resume_self re-arms you and lists the asks. Call both, in
  that order (resume_self, then context). Not `context_delta()` either: a delta needs a cursor you can
  trust, and a resumed seat has none until its fresh `context()` returns one.
- Not `resume(participant_id)`: that is the SPAWNER's tool, which asks the pool to bring a parked or
  closed seat back. resume_self is what the brought-back seat calls.
- Not the fresh-boot sequence: a fresh shell still runs whoami → subscribe → Monitor once, cron once →
  context, as its role card says.

## For spawners (architects, the owner)
- A seat that never registers after a spawn or a resume shows on your feed as shell_dead / shell_stalled
  (process facts from the pool). A live process that never booted is the gap this guide closes on the
  seat side; detection of that case is a later story.
- Recovery = `reap(participant_id)` then `resume(participant_id)`: the pool relaunches the seat on its own
  conversation (Claude: fork-resume; Pi: its session file) and types the resume line; the seat calls
  resume_self and follows the steps. Never spawn a second shell on a handle that is still held.
