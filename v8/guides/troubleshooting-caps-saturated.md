# Troubleshooting: caps saturated
<!-- roles: doctor -->

**Symptom.** Work waits although nothing is broken: a seat is "queued" and never spawns, or new stories do
not start.

**Evidence.**
- `doctor_pool`: the caps (total shells, live shells, builders, planners, per-role caps) against current
  use, a `cap_saturated` cause for each full cap, and `spawns_queued` for the seats waiting.
- `why_stuck(ticket_id)` on a waiting ticket names the full cap.

**Causes.**
1. The work needs more seats than the caps allow. This is normal; the queue drains as seats close.
2. Seats that finished did not close, so they hold slots (`participants` shows them live with nothing
   to do).
3. A cap was set lower than the workflow needs, for example a role cap of 1 with several epics running.

**Fix.**
- Cause 1: tell the person their place in the queue, and that it drains by itself.
- Cause 2: the owner or architect reaps the idle seats; say which.
- Cause 3, or the person wants more parallel work: `propose_fix`
  `{kind: "pool.set_limits", classes: {builder: N}}` (or `max_total_shells`, `max_live_shells`,
  `role_caps: {<role>: N}`). Say the memory cost in `effect`: every extra live seat uses host memory.

**Verify.** `doctor_pool`: the cap has room and the queue shrinks.
