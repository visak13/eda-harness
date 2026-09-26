# Troubleshooting: a stuck ticket
<!-- roles: doctor -->

**Symptom.** A story or epic has not moved for a long time: a gate is open that nobody answers, a check
never happens, or a seat seems to wait forever.

**Evidence.** `why_stuck(ticket_id)` names each root cause it finds:
- `gate_unanswerable`: an open gate that no human on the board may answer, with the refusal it gives
  (usually a missing precondition, such as a design doc or accepted criteria).
- `assignee_seat_down` / `no_assignee`: the doer's seat is gone, or there is none.
- `no_checker`, `checker_missing`, `checker_role_unfilled`: the criteria have no checker, or the checker's
  seat was never spawned.
- `blocked_by`: another ticket blocks it.
- the next step's missing preconditions, from the workflow.
- `cap_saturated` / `pool_unreachable`: the seat it waits for is queued behind a full cap or a dead pool
  (see `troubleshooting-caps-saturated`).

Then use `ticket_read` and `gates` for the detail.

**Fix.**
- A missing precondition: tell the person what to add (the doc, the criteria). That is their work, not a
  fix.
- A gate that should be opened or answered: `propose_fix` `{kind: "gate.open" | "gate.answer",
  ticket_id, gate, note | answer}`. The approving admin runs it as themselves, so the gate's own rules
  still apply.
- A missing seat: say which role needs spawning; the architect or the owner spawns it.

A workflow pin never changes: propose a fixed workflow version for new epics, or the gate or checker
action that unblocks the stuck one.

**Verify.** `why_stuck` again: the cause is gone.
