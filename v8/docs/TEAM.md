# Co-working on the v8 board — team guide

The board (:9400) and broker (:9300) are the shared brain; each machine runs its own pool.
Human↔human traffic never touches a model: messages are board objects mirrored into durable
broker inboxes, read and answered in a browser. Agents cost tokens only when a seat does work.

## 1. Connect machines, $0 — Tailscale

1. Host (the machine running board+broker) and every teammate install [Tailscale](https://tailscale.com/download) (free plan).
2. Host shares its node with each teammate's tailnet (Tailscale admin → Share node — free, no shared account).
3. Host starts the services bound beyond loopback:
   ```powershell
   v8\scripts\start-broker.ps1 -BindHost 0.0.0.0
   v8\scripts\start-board.ps1  -BindHost 0.0.0.0
   ```
   and scopes Windows Firewall to the tailnet only (run once, as admin):
   ```powershell
   New-NetFirewallRule -DisplayName "edp8 tailnet" -Direction Inbound -Action Allow `
     -Protocol TCP -LocalPort 9300,9400 -RemoteAddress 100.64.0.0/10
   ```
   (100.64.0.0/10 is Tailscale's CGNAT range; nothing outside the tailnet can connect.)
4. Availability truth: the network is up while the host machine is. The $0 always-on upgrade
   is a free-tier VM (e.g. Oracle Always Free) running `docker compose up` in v8/ — the board
   image exists; add a broker service to the compose file when you take that step.

## 2. Register a teammate (host does this once per person)

```powershell
# identity on the board (role: owner = owns product areas/gates; sme/reviewer/etc. also valid)
curl -X POST http://127.0.0.1:9400/v1/participants -H "X-Admin: dev" -H "Content-Type: application/json" `
  -d '{"type":"human","role":"owner","handle":"x","id":"x"}'
```
Add their secret to `v8\tokens.json` (create it next to models.json):
```json
{ "x": "a-long-random-secret" }
```
Humans listed in tokens.json must present the secret; agents and unlisted identities are
untouched (trusted-machine mode). A shell acting as a tokened human sets `EDP8_TOKEN`.

## 3. Working as a teammate

- Bookmark: `http://<host-tailnet-ip>:9400/ui/me?as=x&token=<secret>` — your inbox: questions
  waiting on you, open gates on epics YOU own, a reply box, your feed. Auto-refreshes.
- Board views: `/ui` (epics), `/ui/epic/<id>`, `/ui/ticket/<id>`, `/ui/doc/<id>`.
- @mention anyone in any message — `"needs @x's input"` lands in x's inbox + feed, any role.
- Ownership: an epic belongs to the human who created it — its gates, phase events, and shell
  deaths reach that person only. Two owners see two disjoint streams.
- Timezones: inboxes are durable files; nothing expires overnight. Answer in your morning —
  the asking shell (parked or live) wakes on your reply automatically.

## 4. A teammate who wants their own agent seats

Clone the repo anywhere → `setup.ps1` → run a local pool pointed at the shared brain:
```powershell
$env:EDP8_BOARD_URL = "http://<host-tailnet-ip>:9400"
$env:EDP_BROKER_URL = "http://<host-tailnet-ip>:9300"
v8\scripts\start-pool.ps1
```
Known v1 limit: the board's session mirror watches ONE pool (the host's) — remote pools run
fine, but their shells' liveness isn't mirrored into board sessions yet.

## 5. Slack pings (optional doorbell)

`v8\slack_map.json` maps handles to Slack; `start-bridge.ps1` runs the notifier (no LLM, no
tokens): when something lands in your inbox, you get a Slack DM with a one-click link to
`/ui/me`. Replies happen on the board, not in Slack (a $0 constraint: Slack→board callbacks
need a public HTTPS endpoint). See the header of `v8/src/edp8/slack_bridge.py` for the config shape.
Claude-in-Slack (@Claude in your workspace) is a future option — it requires the board reachable
at a public URL, which the tailnet deliberately avoids.
