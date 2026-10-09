# Runbook: the board across the tailnet (Tailscale https, public mode)

Story C8 (s-a4fd5df319), design-10b21760d9 §4.3. Who runs what: the **owner or the epic architect**
runs `apply`/`remove` (they restart the board; dec-fec86c586c). A seat runs only `tailnet check` and
`-WhatIf`.

## Shape

```
teammate browser / VS Code ──https──▶ tailscale serve (:443 on msi.tail884b19.ts.net, tailnet only)
                                        └──http──▶ board 127.0.0.1:9400  (EDP8_HOST=127.0.0.1)
seats, MCP proxy :9402, pool :9301, broker :9300 ──http──▶ board 127.0.0.1:9400 (loopback, unchanged)
code-server :9410 ── loopback only, never served on the tailnet
```

- `EDP8_PUBLIC_URL=https://msi.tail884b19.ts.net` switches on public mode: the board refuses the default
  admin token and refuses every participant (human or agent) without a valid `X-Token`, loopback included.
  Auth is by token, never by peer address, so the forwarder that makes every tailnet request look like
  127.0.0.1 is not a header-only hole.
- `EDP8_HOST=127.0.0.1` is pinned. Without it, public mode binds the board **and the broker**
  (start.ps1 `$BIND`) to 0.0.0.0.
- Tailscale serve, never Funnel: only tailnet members reach it.

## 1. Check (read-only, any seat)

```powershell
.\edp.ps1 tailnet check        # current config, as if public mode were on now; exit 1 while any BLOCKER
v8\.venv\Scripts\python.exe v8\scripts\tailnet_readiness.py --planned   # as apply will write the env
```

The check never prints a token value. Rows: BLOCKER (must fix), WARN, OK, INFO.

| Row | What it means | Fix |
|---|---|---|
| admin token | `EDP8_ADMIN_TOKEN` is unset or `dev` | `apply` generates one into v8\.env (not shown) |
| bind | `EDP8_HOST` unset or not loopback | `apply` pins 127.0.0.1 |
| real env | a key is set in the User/Machine environment, which beats v8\.env | remove it from that scope |
| tokens.json | no human or no agent credential: the board refuses a public start | invite or mint (§5) |
| seats | a **live seat without a minted token**: its MCP calls and feed 401 after the switch | close it, or reap + respawn it once 2ffb89d is live (below) |
| humans | a human on the board without a token cannot sign in | mint one if they are a real person (`x` is stale: ignore) |
| certificates | tailnet HTTPS certificates off | owner: admin console → DNS → HTTPS Certificates |
| serve | serve config other than `https:443 → http://127.0.0.1:9400`, any Funnel, any :9410, any raw TCP forward | `tailscale serve reset` |
| listen | a fleet port (board, mcp, pool, broker, code-server) not on loopback | rebind it to 127.0.0.1 |

**Why seats matter:** until 2ffb89d the architect's (and owner's) MCP spawn tool called the pool directly and never minted a token,
so seats it started are header-only. 2ffb89d makes it get-or-mint the seat's token
(`POST /v1/sessions/seat-token`) and inject `EDP8_TOKEN`. It reaches seats only after the **board and the
MCP proxy restart** (the proxy loads code at boot); seats spawned before that must close or be respawned.

## 2. Switch-over (owner / architect, when no seat depends on the board)

```powershell
.\edp.ps1 restart mcp          # loads 2ffb89d into the proxy (board restart comes with apply)
#   ...close or respawn every seat the check lists; re-run until 0 BLOCKER:
.\edp.ps1 tailnet check
.\edp.ps1 tailnet apply -WhatIf
.\edp.ps1 tailnet apply
```

`apply`, in order (it stops at the first failure):
1. runs the check with `--planned`; refuses on any BLOCKER unless `-Force`;
2. appends ONE marked block to `v8\.env`: `EDP8_HOST=127.0.0.1`, `EDP8_PUBLIC_URL=https://<tailnet name>`,
   and a generated `EDP8_ADMIN_TOKEN` only when the current one is the default;
3. restarts board + mcp (+ supervisor when running) — every consumer of the admin token;
4. verifies on loopback that a header-only `whoami` is refused 401 — if not, it does NOT open the front;
5. `tailscale serve --bg --https=443 http://127.0.0.1:9400`.

The pool and broker are not restarted: neither calls the board with the admin token. Re-arm your feed
after the board restart. MCP single-host HTTP upload switches itself off while `EDP8_PUBLIC_URL` is set
(http_upload.py); the MCP upload of a workspace file by path still works.

## 3. Verify

```powershell
curl.exe -s -o NUL -w "%{http_code}\n" https://msi.tail884b19.ts.net/healthz                       # 200 over TLS
curl.exe -s -o NUL -w "%{http_code}\n" -H "X-Participant: owner" https://msi.tail884b19.ts.net/v1/whoami  # 401
netstat -ano | findstr LISTENING | findstr ":9400 :9402 :9301 :9300 :9410"                         # 127.0.0.1 only
tailscale serve status                                                                              # 443 -> :9400 only
```

From another tailnet machine, `http://msi.tail884b19.ts.net:9410/` must not connect.

## 4. Rollback (one line)

```powershell
.\edp.ps1 tailnet remove       # -WhatIf to preview
```

It runs `tailscale serve reset` first (closes the door), deletes the marked block from `v8\.env` (the file
returns to its exact prior content), clears those keys from its own environment, and restarts board +
mcp (+ supervisor). The board is back in trusted mode on 127.0.0.1. Manual equivalent: `tailscale serve
reset`, delete the lines between `# >>> edp tailnet` and `# <<< edp tailnet` in `v8\.env`, then
`.\edp.ps1 restart board` and `.\edp.ps1 restart mcp` from a fresh shell.

## 5. Add a teammate (owner only)

From the UI there is a shorter path. Admin → Teammates → Invite gives a one-time link. A person without a token can also press **Request access** on the sign-in page; an admin approves it under Admin → Teammates → Requests, and that person's browser signs itself in. To take a teammate off the board, use Admin → Teammates → Remove. The manual steps below are the fallback. `alex` is a placeholder handle.

1. **Tailnet access** — owner, in the Tailscale admin console: invite them to the tailnet (Users →
   Invite), or share just this machine (Machines → msi → Share…). Shared-in users reach the machine but
   not the rest of the tailnet. They install Tailscale and sign in; `tailscale status` on their side
   lists `msi`.
2. **Board participant + invite** — Admin → Teammates → Invite, or from an owner seat's MCP tools
   `teammate(action='create', handle='alex', role='qa')`: registers the human and returns a one-time
   invite link (24 h) that signs them in. Nobody edits `tokens.json` by hand and no shell reads it.
3. **Mint a token** (a teammate without a browser, e.g. VS Code only) — Admin → Teammates → Rotate, or
   `teammate(action='mint', handle='alex')`. The secret is in that one reply only: the board never writes
   it to its events or logs and it cannot be read back; minting again replaces it. The admin routes behind
   the tool need an admin human's token, so an agent seat is refused. Send the secret over a private
   channel (not the board, not Slack channels).
4. **SPA sign-in** — they open `https://msi.tail884b19.ts.net/ui?as=alex&token=<secret>` once. The SPA
   moves the token into the tab's session storage and strips it from the address bar; a new tab asks again.
5. **VS Code extension** — install the edp-code vsix, set `edp.boardUrl` to
   `https://msi.tail884b19.ts.net` (machine setting; credentials are only sent to a loopback or https URL),
   then run **EDP: Sign in to board** with their handle and secret (kept in VS Code SecretStorage).
6. **Revoke** — Admin → Teammates → Revoke (or Remove), or `teammate(action='revoke', handle='alex')`; the
   next request 401s. `teammate(action='list')` shows who has a token.

## Not exposed

code-server (:9410) runs `--auth none`: whoever reaches it owns the host. It stays bound to 127.0.0.1 and
is never added to `tailscale serve`. Teammates use their own VS Code with the extension (C6).
