# Troubleshooting: broker dead mail
<!-- roles: doctor -->

**Symptom.** A message is on the board but its recipient never heard of it.

**Evidence.**
- `doctor_dead_mail`: the broker's `publish_no_route` lines, which are publishes nobody was subscribed to,
  with their time and topic.
- `participants`: whether the recipient existed and was live at that time.
- `doctor_health`: whether the broker is running.

**Causes.**
1. The recipient's seat was not running when the message was published. The message stays on the board,
   and the seat reads it when it next boots.
2. The message was addressed to a handle that does not exist (a typo, or a seat that was never spawned).
3. The broker restarted and the seats have not re-subscribed yet.

**Fix.**
- Cause 1: nothing is lost. Tell the person the seat will read it at boot, or ask the architect to spawn
  it.
- Cause 2: give the person the right handle (from `participants`) so they can resend.
- Cause 3, or a broker that is not running: `propose_fix` `{kind: "service.restart", service: "broker"}`.

**Verify.** No new `publish_no_route` lines for that recipient.
