# S0 capability proof — incomplete / blocked

2026-09-18. Design `design-f716d0d138` v7 §§4.9–4.10; plan `note-5a6ada0fc4`.
Only this directory is owned by this probe. No production integration or service restart.

## Observed inventory

- Agent host: Windows NT 10.0.26200.0 (`[Environment]::OSVersion.VersionString`).
- Standard installed Firefox binary: ProductVersion/FileVersion **156.0** at
  `C:\Program Files\Mozilla Firefox\firefox.exe`. This does NOT establish the owner's
  active browser/profile, origin, permission or desktop state.
- `codex --version`: **codex-cli 0.153.4**.
- `claude --version`: **2.1.270 (Claude Code)**.
- Owner canonical origin subsequently confirmed via architect: `http://127.0.0.1:9400`, Firefox.
  Latest ruling `m-92f8d92ec1` (relayed `m-aa6391c930`) says test Firefox, not Chrome.
  No owner's live tabs/profile were accessed. Dedicated test profiles only.

## Legitimate Codex source result

`codex_probe.py` starts an owned native app-server stdio process, initializes, sends
only `account/rateLimits/read`, then closes/reaps that PID. It never reads credentials,
requests a model turn, modifies CLI settings, or logs raw replies/errors. Existing CLI
login is consumed by the supported CLI itself. This is host CLI telemetry, NOT proof
that the account is authorized for any particular board participant.

Two reads at 08:15:53Z and 08:16:59Z returned:

```json
{"primary":{"usedPercent":92,"windowDurationMins":10080,"resetsAt":1789807430},"secondary":null}
```

The second read also inspected `rateLimitsByLimitId`: only `codex`, same weekly window.
No 300-minute bucket was observed. **Do not label primary as 5h.**
Owner ruling `m-92f8d92ec1` now accepts this absence conditional on automatic display
when an ordinary future source update includes it. `usage_contract.py` is a pure fixture
contract demonstrating duration-driven absent→present→absent replacement without a
sticky feature flag. S6 still must integrate that behavior; S0 does not ship a widget.
No provider observation timestamp was supplied; `received_at` is collection time only.
Actual provider account identifiers/plan/credits are intentionally not retained.
Events were not demonstrated by a changing limit in this short-lived probe.

Rerun from repository root in Git Bash (installed path on this host):

```sh
".venv/Scripts/python.exe" docs/s0-capability-proof/codex_probe.py --codex-exe 'C:/nvm4w/nodejs/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
".venv/Scripts/python.exe" -m unittest discover -s docs/s0-capability-proof -p 'test_*.py' -v
```

Use only for an authorized local account, not an arbitrary fleet participant. Output is
an allowlisted **raw source shape**, not a production normalization/authorization adapter.

## Supported public contracts (retrieved 2026-09-18)

- https://developers.openai.com/codex/app-server : documents
  `account/rateLimits/read` and `account/rateLimits/updated`, primary/secondary,
  `usedPercent`, `windowDurationMins`, `resetsAt`, `rateLimitsByLimitId`.
- https://code.claude.com/docs/en/statusline.md : documents
  `rate_limits.five_hour` and `rate_limits.seven_day`, each with
  `used_percentage` (0–100) and `resets_at` (epoch seconds). For claude.ai Pro/Max,
  only after the first API response; windows independently absent and removed after
  their reset time passes. Gateway `spend_limit` is not subscription utilization.
  The HTML URL returned HTTPError to urllib; Markdown URL succeeded using curl.
- Claude installed version alone does not prove real statusline values. **No legitimate
  Claude core sample captured.** No prompt was generated to populate one. An owner-approved
  additive capture of already-authorized ordinary session activity is needed; do not dump
  full statusline payload (it includes transcript paths/session IDs/workspace details).
- No Fable source verified. Unavailable is accepted by owner `m-58bca3fdcc`
  (quoted in design v7 §1), not 0%.

## Proposed integration boundary, not a delivered adapter

Each bucket: provider, authorized masked account binding, source, window minutes,
nullable used_percent/resets_at/observed_at, received_at, status and safe reason.
Match 300 and 10080 minutes by duration, not slot order. Preserve additional durations
without silently merging model pools. Unknown/missing is unavailable, never zero.
Validate finite numeric percentages 0–100 and epoch units at normalization boundary.
Use original provider observation time when available; receipt is not observation.
A cached Claude statusline refreshed by unrelated UI activity cannot renew freshness;
if underlying observation time cannot be established, report unknown freshness instead
of inventing it. Five minutes is the design's potential-staleness threshold.
Expired windows must not be presented as current. Do not substitute tokens or spending.

Synthetic normalized examples (not real proof):

```json
[
 {"provider":"codex","window_minutes":300,"used_percent":null,"resets_at":null,"observed_at":null,"status":"unavailable","reason":"source_window_absent"},
 {"provider":"claude","window_minutes":10080,"used_percent":null,"resets_at":null,"observed_at":null,"status":"unavailable","reason":"authorized_capture_pending"}
]
```

Account binding remains an integration prerequisite: no board seat inherits the host's
subscription visibility. Auth errors must fail closed with safe reasons; no tokens in
responses, caches, URLs, logs or worker registry. Codex update events are documented but
not yet observed here. Manual reads >=30s apart and bounded child cleanup; UI opening
must not spawn a new provider process every time.

## Firefox API smoke — PASS, native click proof — NOT RUN

`node docs/s0-capability-proof/firefox-smoke.cjs` passed using installed Playwright
firefox-1538 / Firefox 153.0, headless, disposable profile, ephemeral loopback server
`http://127.0.0.1:54938` on the recorded run. This is NOT stock Firefox 156.0 or the
owner's profile. Secure context true; permission default→granted→default using automation;
service worker showNotification/getNotifications returned one notice then closed it;
clients.matchAll returned two same-origin test tabs. No credentials, board service or
production origin involved. The script reaps its owned browser and HTTP server.
This is API smoke, not proof of an OS toast being visible/clicked or a real permission dialog.

No native toast click trials have been executed (0/20 in each of four groups). No patched
Firefox/fixture result may substitute for installed-owner Firefox. Native desktop interaction
still needs a capable desktop driver or a coordinated owner-run procedure; current exposed
tools do not provide an OS toast click API. No route/draft/participant reuse is proven.

After consent, serve an isolated probe on a confirmed secure loopback test origin,
with a minimal service worker scoped only to that probe. This isolated origin cannot
prove reuse of production tabs; eventual production-origin testing remains necessary.
No push, fetch cache, app shell, shared-service modification or closed-browser delivery.

For each foreground/background/minimized/multi-tab group, record 20 rows:
trial ID, OS/browser/origin/profile, permission, participant registration, eligible
client count, total tabs before/after, intended canonical destination, actual route,
focus result, draft text/caret/attachments before/after, explicit pass/fail/reason.
Use synthetic participants/drafts; do not capture private screen content.

Also test denied/revoked permission, insecure HTTP, offline, different participant tab,
rapid repeated clicks, vanished client and focus failure. Dirty client must be focused
with pending destination rather than silently navigated. Reauthorize destination before
routing. Open at most one window only when no eligible same-origin participant client
remains; failed focus is not permission to open another. Client presence is not identity
authorization. Clear/revalidate registry on identity changes. Cross-tab event dedup needs
an atomic bounded ledger, not notification tag alone. Existing toast/new-shell behavior
is distinct from promising delivery with all tabs closed.

## Criterion status

- `c-7d4ba62ffb`: **NOT PROVEN**, owner-native trials pending, explicit environment/consent blocker.
- `c-c4e77f8c30`: **NOT PROVEN**, real Codex weekly-only; absent 5h condition now accepted
  with dynamic fixture behavior, but Claude core capture/account binding remains unproven.
- Deviation `m-6993f05a22` requests architect/owner resolution. Integrations remain blocked.
- Unit tests characterize projection/privacy and dynamic bucket replacement only, not
  provider/browser acceptance.

## Claude concrete consent proposal (not activated)

Read-only settings-shape inspection: no statusLine key in user
`C:/Users/aksou/.claude/settings.json` or project `v8/.claude/settings.json`;
project settings.local.json and standard `C:/Program Files/ClaudeCode/managed-settings.json`
absent. No other settings values printed/read into the report.
Proposed only for a NEW owner-launched interactive session:
`claude --settings C:/Users/aksou/AppData/Local/Temp/edp8-s0-claude/settings.json`.
New file would configure a scoped helper `docs/s0-capability-proof/claude_capture.py`
(not yet created), retaining only both rate-limit windows and receipt time in
`.../edp8-s0-claude/sample.json`. No existing config edits, no live-session reload, no
synthesized prompt. Owner uses independently intended normal work. If an unexpected
launch-specific/managed statusline exists, stop rather than replace it. Revert closes
only dedicated session and removes only the two temp files; no shared services involved.
Full exact scope sent for relay/consent in `m-3c7dda5d62`; no approval assumed.

## Independent read

Consult run `20260918T082331Z-9f6826be` returned a substantive read of initial probe,
tests and README. Fixed its material pipe-close cleanup defect, added mocked reaping
regression test, rejected nonfinite floats, added serialization test, cited Fable ruling.
It agreed blocked, not acceptance. It did not run tests or independently verify captures.
Manifest provider_model=unavailable despite recovered answer: consultant model attribution
is unverified (named gap), no retry. Later Firefox API smoke/dynamic fixtures were added
following owner steers and are not covered by that read. All are isolated research files.
Pain record p-c8744541: running receipt omitted run_id; recovered from completion feed.
