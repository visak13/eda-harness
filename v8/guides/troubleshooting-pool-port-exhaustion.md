# Troubleshooting: pool port exhaustion / false shell deaths
<!-- roles: doctor -->

**Symptom.** Bursts of `shell_dead` events with no reason, seats marked dead that are still working, or
spawns that fail with connection errors while the host is otherwise fine.

**Evidence.**
- `doctor_pool`: the pool is reachable and lists its sessions. A session listed there but reported dead
  on the board is a false death.
- `doctor_logs("pool")`: errors such as "address already in use", "only one usage of each socket
  address", or connection timeouts to 127.0.0.1.
- The deaths come in bursts, many seats at once, not one after another.

**Cause.** The board's mirror of the pool opens many short connections. Under load they pile up in
TIME_WAIT until no local port is free, so liveness checks fail and seats look dead. A wedged pool listener
gives the same picture.

**Fix.**
- A wedged listener (the pool does not answer at all): `propose_fix`
  `{kind: "service.restart", service: "pool", keep_seats: true}`. The pool's state persists and the
  running seats are re-adopted. Never propose `force: true` for this.
- Exhaustion alone clears within a few minutes once the burst stops. Tell the person to wait, and check
  `doctor_pool` again before proposing anything.

**Verify.** `doctor_pool` lists the seats as live and no new reason-less deaths appear.
