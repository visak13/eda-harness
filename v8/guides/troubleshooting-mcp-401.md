# Troubleshooting: MCP 401 / a seat without its token
<!-- roles: doctor -->

**Symptom.** A seat reports that every board tool (whoami, context) answers 401 or "missing token",
while the board itself is up.

**Evidence.**
- `doctor_health`: the board and mcp rows are running (otherwise see `troubleshooting-service-down`).
- `participants`: the seat exists and is live.
- `doctor_logs("mcp")`: the 401 lines and the handle they name.

**Causes.**
1. The shared MCP proxy started without a valid token in its own environment. Then every seat's call
   401s, even though each seat's own token works against the board directly. Many seats failing at once
   points here.
2. A seat resumed by the pool lost its token (it has an empty token in its environment). One seat fails
   and the others work.
3. The seat's agent token was revoked or rotated while the seat was running.

**Fix.**
- Cause 1: `propose_fix` `{kind: "service.restart", service: "mcp"}`. The restart re-reads the token.
- Cause 2 or 3: the seat's architect or the owner respawns it. Say which seat, and why.
- A token known to have leaked: `{kind: "agent_token.revoke", handle: "<seat>"}` for an agent, or
  `{kind: "teammate.rotate_token", handle: "<human>"}` for a person. The new token is shown once, to the
  admin who approves.

**Verify.** Ask the seat's owner to retry, or read `doctor_logs("mcp")` for fresh successful calls.
