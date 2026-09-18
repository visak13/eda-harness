# Genuine source observations — 2026-09-18

Supersedes earlier all-null Claude checkpoint; does not supersede native-Firefox gaps.
No credentials/account identifiers/session IDs/raw statusline payload retained.

## Codex 0.153.4, supported app-server read

Collected 08:15:53Z and 08:16:59Z via owned stdio process using
account/rateLimits/read, no model turn. Primary duration **10080 minutes**, **92%** used,
reset epoch **1789807430** = **2026-09-19T08:43:50Z**. Secondary absent; by-limit codex pool
same weekly window. Five-hour absence accepted conditionally by owner m-92f8d92ec1;
ordinary absent→present→absent duration-driven fixture tests pass. Never map slot name
primary to 5h without checking duration. Updated event documented, not observed changing.

## Claude Code 2.1.270, supported statusline

Owner consent m-d9522fe9a7 enabled one new claude-personal session only. Wrapper selects
.claude-personal and forwards --settings. Owner restored expired login independently;
architect verified owner /status reports **Claude Max account** (m-1c06016692). Agent did
not change login/config/account, launch a model session or send a prompt. Architect inspected
owner screenshot m-143292cc15 and confirmed (m-0401b734b6) successful Claude Max login,
owner-initiated **'hi' greeting** with completed response, and both windows received.
This was independently user-entered, not business-work evidence or an agent-generated prompt.
The unrelated executable-in-use auto-update warning is not a reason to stop sibling sessions.

Authorized helper's genuine allowlisted sample, read at 08:57Z:

```json
{
  "rate_limits": {
    "five_hour": {"used_percentage": 0, "resets_at": 1789738200},
    "seven_day": {"used_percentage": 15, "resets_at": 1790251200}
  },
  "received_at": "2026-09-18T08:56:52.591135+00:00"
}
```

5h reset **2026-09-18T13:30:00Z**, weekly reset **2026-09-24T12:00:00Z**.
Here **0 is genuinely reported**, not a missing-value fallback. Prior receipts at
08:43:14Z and 08:55:06Z normalized all four fields to null; helper accurately shows
"windows incomplete" for missing OR invalid fields and cannot distinguish those after
projection. New sample contains both valid numeric core windows; no parser edit was needed.

The receipt timestamp is **NOT original provider observation time**. The documented
statusline rate-limit windows contain no observation timestamp. Repeated receipts must
not renew freshness of an unchanged provider observation. Production must label observation
freshness unknown/potentially stale and keep receipt separately; do not pretend UI refresh
fetches Claude's provider. Clear expired windows; no token-count/spend substitute. Fable
unavailable remains accepted by m-58bca3fdcc.

## Proof limits

This demonstrates installed legitimate source shape/core values, not production board
participant-to-subscription authorization or ongoing adapter deployment. Codex host account
binding still requires explicit owner mapping; Claude binding is the owner's reported
Max account in the personally selected wrapper, with no account details exported. The
current sample is historical evidence and must not be rendered as current indefinitely.
Final criterion verdict belongs to consolidated QA. Native Firefox 20x4 click proof is
still unperformed; isolated API/fixture smokes do not waive it.
