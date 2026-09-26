# Troubleshooting: a harness that is not signed in
<!-- roles: doctor -->

**Symptom.** Seats spawn and die at once, the pool log shows a sign-in or trust prompt, or a seat's first
output asks the person to sign in.

**Evidence.**
- `doctor_health`: the package and harness versions.
- `doctor_logs("pool")` and the seat's own log (`doctor_logs("pool-logs/<name>")`): "not logged in",
  "please run /login", "authentication", or a folder trust question.

**Causes.**
1. The harness (claude, codex) was never signed in on this host, or its sign-in expired.
2. The seat runs with a config folder that is not the signed-in one.
3. The agent home folder is not trusted by the harness.

**Fix.** No approval-card action signs a harness in; the person does it on the host:
- run `claude` (or `codex login`) once in a terminal and complete the sign-in;
- run `heronry doctor`, which checks the harnesses and folder trust and says what is missing;
- then ask the owner or architect to respawn the seats that died.

Never ask for passwords or tokens in the thread.

**Verify.** A new seat spawns and stays live (`doctor_pool`).
