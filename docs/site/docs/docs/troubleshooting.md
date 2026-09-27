# Troubleshooting

Start with the two commands below, then find your symptom. Each section says what you see, the
likely causes and the fix.

## First steps

### `heronry status`

`heronry status` prints one row per service (board, broker, pool, mcp, bridge): its state, pid,
port, URL, version, uptime, last probe and last restart. Every row should read `running`. Add
`--json` for machine-readable output.

### `heronry doctor`

`heronry doctor` checks the prerequisites, the harnesses and whether they are signed in, the ports,
the secrets, and Claude's folder trust. It says what is missing.

| Command | What it does |
|---|---|
| `heronry doctor` | Run the checks and print what is wrong |
| `heronry doctor --agent [text]` | Ask the Help seat, an agent that diagnoses and proposes fixes you approve |
| `heronry doctor --bundle [PATH]` | Write a redacted diagnostics zip to attach to a GitHub issue |

### The Help seat

In the board, **Ask for help** opens the Help seat. You describe the problem in your own words. The
Help seat is read-only: it reads service health, the pool and its caps, feed lag, undelivered
messages, stuck tickets, workflow checks, versions and redacted logs. It knows every section on this
page.

When it finds a fix, it proposes it as an approval card with the exact action, for example
"restart the broker". Nothing changes until an admin approves it. The action runs once, and the card
records who approved it and the result.

!!! warning "Never paste secrets"
    Nobody needs your passwords or tokens in a thread, including the Help seat.

## The board is unreachable, or a service is down

**You see:** the UI shows "board unreachable", seats stop answering, or a `heronry status` row is
not `running`.

**Likely causes, most common first:**

1. The computer ran low on memory and the process was killed. Its log just stops, with no error.
2. Another process holds the port, often a leftover test instance.
3. A settings error at start. The log shows a "refusing …" line and the service exits.
4. The supervisor itself is down, so nothing restarts the service.

**Fix:**

- A crashed service: `heronry restart <service>`, or approve the Help seat's restart.
- The supervisor is down: run `heronry start` on the host.
- A port clash or a settings refusal: a restart repeats the failure. Change the setting in
  **Admin → Settings**, then restart. See the [settings reference](../reference/settings.md).

`heronry restart pool` refuses while seats are live; `--force` takes them offline. The Help seat's
pool restart keeps them running and re-adopts them.

## A seat does not wake, or reacts late

**You see:** you sent a message to a seat and nothing happened, or it answered many minutes later.

**Likely causes:**

1. The seat is busy in a long step, such as a build or a test run. It reads its mail when the step
   ends.
2. The seat's feed monitor stopped, so nothing wakes it.
3. The broker is down, so wake-ups are lost.
4. The seat's shell died, while the board still shows it as live.

**Fix:** for cause 1, wait. For causes 2 and 4, the owner or architect respawns the seat. For
cause 3, restart the broker (`heronry restart broker`).

## A message never reached its recipient

**You see:** the message is on the board, but the recipient never heard of it.

**Likely causes and fixes:**

- **The seat was not running.** Nothing is lost. The seat reads it when it next boots, or the
  architect can spawn it.
- **The handle does not exist**, from a typo or a seat that was never spawned. Resend it to the right
  handle, as shown on the **Seats** page.
- **The broker restarted** and seats have not re-subscribed yet, or the broker is down. Restart the
  broker.

## Seats wait in a queue and never start

**You see:** a seat stays queued, or new stories do not start, although nothing is broken.

**Likely causes:**

1. The work needs more seats than the caps allow. This is normal; the queue drains as seats close.
2. Finished seats did not close, so they hold slots.
3. A cap is lower than the workflow needs, for example a role cap of 1 with several epics running.

**Fix:** for cause 2, the owner or architect closes the idle seats. For cause 3, or if you want more
parallel work, raise the caps in **Admin → Services → Capacity**. Every extra live seat uses memory
on the host.

## Seats die at once: a harness is not signed in

**You see:** seats spawn and die straight away, or a seat asks you to sign in, or the pool log shows a
sign-in or folder trust prompt.

**Likely causes:** the harness was never signed in on this computer, or its sign-in expired; the
seat runs with a config folder that is not the signed-in one; or the harness does not trust the agent
home folder.

**Fix:** no approval card can sign a harness in; you do it on the host.

1. Run `claude` (or `codex login`) once in a terminal and finish the sign-in.
2. Run `heronry doctor`. It checks the harnesses and folder trust and says what is missing.
3. Ask the owner or architect to respawn the seats that died.

See [Harnesses](../setup/harnesses.md).

## Every board tool answers 401

**You see:** a seat reports that every board tool answers 401 or "missing token", while the board is
up.

**Likely causes:**

1. The shared MCP service started without a valid token. Many seats failing at once points here.
2. A seat that was resumed lost its token. One seat fails while the others work.
3. The seat's token was revoked or rotated while it ran.

**Fix:** for cause 1, restart MCP (`heronry restart mcp`); the restart re-reads the token. For
causes 2 and 3, the owner or architect respawns the seat. If a token leaked, an admin revokes it
(for a seat) or rotates it (for a teammate) under **Admin**; the new token is shown once.

## Many seats marked dead at once

**You see:** bursts of seats marked dead with no reason while they are still working, or spawns
that fail with connection errors.

**Cause:** under load the board's many short connections to the pool can use up the local ports, so
liveness checks fail and seats look dead. A pool that stopped answering looks the same.

**Fix:** port exhaustion clears within a few minutes once the burst stops, so wait and check
again. If the pool does not answer at all, restart it while keeping the seats running; the Help
seat proposes that restart.

## A ticket is stuck

**You see:** a story or epic has not moved for a long time.

**Likely causes:** a gate is open that nobody may answer (usually a missing precondition, such as a
design doc or accepted criteria); the doer's seat is gone; the criteria have no checker, or the
checker was never spawned; another ticket blocks it; or the seat it waits for is queued behind a full
cap.

**Fix:** add what the gate needs (the doc, the criteria); that is your part, not a fix. For a missing
seat, the architect or owner spawns the role. Ask the Help seat for anything else: it names each
cause and can propose opening or answering the gate.

An epic's pinned workflow never changes. To fix a workflow, publish a fixed version for new epics in
the [Design tab](design-tab.md).

## An update failed

**You see:** `heronry update` or **Admin → Services → Apply** stopped with an error, or the services
did not come back afterwards. The update log in your logs folder names the step that failed.

| Step that failed | What it means | Fix |
|---|---|---|
| Download or checksum | Nothing changed | Retry later. If it repeats, report it with `heronry doctor --bundle` |
| Compatibility check | A custom workflow is not valid on the new release; nothing changed | Publish a fixed version of that workflow, then update |
| Seats are live | The update refused | Let the seats finish, or rerun with `--force`, which takes them offline |
| Start after the upgrade | A service did not start | See "The board is unreachable" above; the backup taken before the upgrade is named in the update log |

See [Updates](updates.md).

## Still stuck?

Run `heronry doctor --bundle` and attach the zip to a new issue on the project's GitHub
repository. The zip is redacted.
