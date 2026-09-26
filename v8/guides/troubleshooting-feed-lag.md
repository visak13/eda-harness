# Troubleshooting: feed lag / a seat that does not wake
<!-- roles: doctor -->

**Symptom.** A message was sent to a seat but the seat never reacted, or reacted many minutes late.

**Evidence.**
- `doctor_feed_lag`: for every live seat, the addressed messages newer than its last request, the oldest
  one's age, and the seat's last request. A `feed_lag` cause names a seat whose unread mail is older than
  two minutes.
- `doctor_dead_mail`: the broker never delivered it (see `troubleshooting-broker-dead-mail`).
- `doctor_pool`: the seat's shell is gone, or it is busy.

**Causes.**
1. The seat is busy in a long step (a build, a test run). It reads its mail when the step ends.
2. The seat's feed monitor stopped (it expired or crashed), so nothing wakes it.
3. The broker is down, so wake-ups are lost.
4. The seat's shell died, while the board still shows it as live.

**Fix.**
- Cause 1: wait, and tell the person the seat's last activity.
- Cause 2 or 4: the seat's architect or the owner respawns it; say which seat.
- Cause 3: `propose_fix` `{kind: "service.restart", service: "broker"}`.

**Verify.** `doctor_feed_lag` shows no unread mail older than a minute for that seat.
