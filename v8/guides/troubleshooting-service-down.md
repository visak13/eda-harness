# Troubleshooting: a service is down
<!-- roles: doctor -->

**Symptom.** The UI shows "board unreachable", seats stop answering, `heronry status` shows a row that is
not `running`, or MCP calls fail with a connection error.

**Evidence.**
- `doctor_health` lists every service (board, broker, pool, mcp, bridge) and the supervisor, and names a
  `service_down`, `supervisor_down` or `pool_unreachable` cause.
- `doctor_logs(service)` gives the redacted tail of that service's log. Look for the last traceback, a
  "port in use" error, or an out-of-memory kill.

**Causes, most common first.**
1. The host ran low on memory and the process was killed. The log just stops, with no error.
2. The port is taken by another process, often a leftover test instance.
3. A config or settings error at start (the log shows "refusing …" and exits).
4. The supervisor itself is down, so nothing restarts the service.

**Fix.**
- A crashed service with a healthy supervisor: `propose_fix` with
  `{kind: "service.restart", service: "<name>"}`. For the pool, add `keep_seats: true` to restart the
  process and re-adopt the running seats. `force: true` takes live seats offline, so say that in `effect`.
- The supervisor is down: no action can reach it. Tell the person to run `heronry start` on the host.
- A port clash or a config refusal: a restart repeats the failure. Give the person the log line and the
  setting to change (Admin → Settings), then propose the restart.

**Verify.** `doctor_health` again: the row reads running and the cause is gone.
