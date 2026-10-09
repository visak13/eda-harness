# edp.ps1 — how fleet services are started, stopped, restarted and updated

Moved here from shared-host-rules (S20 token-cost rework): seats only need the rule that points here;
the human/owner runs the procedure.

`edp.ps1` at the repo root replaces every ad-hoc procedure (`start.ps1 -Restart`, `stop.ps1`,
`scripts\start-*.ps1`, hand-killing pids): `.\edp.ps1 status | start | stop | restart <board|mcp|pool|broker|bridge|supervisor|all> | update`,
`-WhatIf` prints the plan and changes nothing. It is run by the human/owner; a seat runs only
`status` and `-WhatIf` against the fleet.

**The `code` service** (code-server for the Code tab, epic-91fcd3b370 S2) is the exception a seat
may start/stop: `.\edp.ps1 start|stop|restart|status code` on 127.0.0.1:`EDP_CODE_PORT` (9410),
health `GET /healthz`. `all` includes it (t-86f4ae3569, owner m-03b329ede2): `start all` starts it
LAST, after heronry started the fleet; `stop all` stops it FIRST; `restart all` does both. A code
failure inside `all` never hides or aborts the fleet: the fleet's rows are printed, code's failure is
printed with its log path, and the run exits 10 ("only code failed"; exit 4 = a fleet service
failed). A failed start is kept in `.run\code.last-error.txt` until the next good start/stop.
`update` never touches it, the supervisor does not watch it, and by name (`start|stop|restart code`)
it touches no other service. A seat starts/stops it by name only, never with `all`. `status` names a
reason for every service that is not up (not running / exited + log path / start failed / not
installed / unhealthy). Start/stop run
`v8\scripts\start-code.ps1` / `stop-code.ps1`, thin wrappers (S21) over `heronry start code` /
`heronry stop code` (edp8.code_service, the same on every OS; the Admin console, the tray and the Code
tab's Start run it too): pinned install (`vscode-ext\code-server.lock.json`, sha256 before extraction,
`install-code-server.ps1`), sha-checked Open VSX extensions (`vscode-ext\extensions.txt` +
`extensions.lock.json`), loopback behind the guard with a per-start password, every `EDP_*`/`EDP8_*`
stripped from its env, `.run\code.json`; the stop kills the recorded (pid, start time) trees of
code-server and the guard (extension host, pty host, terminal shells) and never a reused pid. Re-runnable evidence: `v8\scripts\verify-code-service.ps1`.

**How to restart safely** (what the script does, so nobody improvises it): every service is two or
more processes with one command line (uv / shim → venv launcher → interpreter owning the port).
`edp.ps1` finds that chain from the port's LISTEN owner and its same-service ancestors (never by
image name, never from `.run/<svc>.json` alone — it can hold a stale or null pid), stops each pid
with `Stop-Process -Id` and NO tree kill (seat shells are children of the pool; `taskkill /T` on the
pool kills the fleet; each kill goes through a handle checked against the discovered start time, so
a reused pid is never hit), pauses a running supervisor around the restart, starts the service with
`start.ps1 -Only <svc>` launched WITHOUT handle inheritance (a started service must never hold the
caller's stdout pipe: that hung the first live run), fails loudly on a non-zero launcher exit, waits
for its health route (bounded, `-TimeoutSec`, default 60) and prints the new process chain (listener
marked `*`) + rev. Only the anchor's own launcher images (python/uv/edp8-board) join a chain; a foreign
listener on a service port is left alone. The pool, alone or in `all`,
lists the seats it takes offline and refuses without `-Force`; after a pool restart it prints each
seat's liveness. `update` refuses a dirty tree (modified or untracked) without `-Force`, pulls
`--ff-only`, stops the supervisor and then every affected service BEFORE syncing deps (Windows locks
loaded files), rebuilds the SPA when `v8/web/` changed, starts board → broker → pool (only with
`-Force`) → mcp → bridge, then the supervisor; a failure names what is still down, and a re-run at an
unchanged HEAD fails loudly while core services are down.
This supersedes the memory notes never-taskkill-board-by-image, pool-restart-tree-kill-takes-seats
and start-ps1-restart-noop-kill-both-pids as procedures (they stay as the reasons).
