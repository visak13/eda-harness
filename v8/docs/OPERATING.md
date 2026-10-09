# Operating v8 — the owner's guide

## 1. Start / stop
- `edp.ps1` (repo root) is the one ops script: `.\edp.ps1 status`, `.\edp.ps1 start|stop|restart
  <board|mcp|pool|broker|bridge|supervisor|all>`, `.\edp.ps1 update`; add `-WhatIf` to see the plan.
  It brings up broker :9300 (inboxes, the wake plane), board :9400 (web UI at /ui, the
  state-transfer record), pool :9301 (shells), MCP :9402, the Slack bridge and the supervisor.
  Safe-restart rules: `docs/operator/edp-ps1.md`.
- `start-v8.bat` / `stop-v8.bat` are thin wrappers (`edp.ps1 start all` / `edp.ps1 stop all -Force`).
  Docker is NOT required for local use.
- The planes: the BOARD holds state (tickets, criteria, docs, gates); the BROKER delivers —
  every addressed message/gate is mirrored to the recipient's inbox, the pool's watchdog
  resumes a parked shell when its inbox grows. A Claude Code seat is woken by the `edp-wake` mod
  (`.claude/mods/edp-wake`), which runs the feed listener and starts a turn only on a real event, with the
  full text; no Monitor to re-arm. A quiet tick every 30 min is the only fallback.

## 2. Your entrypoint: the web UI

The owner is a person, never an agent: no path launches a shell as the owner role (owner
m-da9a2ae62f). Start the services (`edp.ps1 start all`, or `owner.bat` / `start-v8.bat`, which call
it) and open http://127.0.0.1:9400/ui. You talk to the architect in chat on the epic page and, when
mapped, in Slack; only what no seat can heal reaches you as a plain chat message (for example, no RAM left).

## 3. Kick off work
New epic in the UI (your words verbatim) with "spawn the architect" ticked: the board spawns
`architect.<epic>`. It designs, has SMEs write the strategy docs, writes stories + criteria and
opens your design_signoff gate. From there the architect spawns each phase: an engineer per ready
story, an adversary where it wants a hostile read (it picks which findings to fix), and qa when the
board hints `qa_available` (the epic moved to in_review; the board spawns no seat itself). When every
criterion passes the architect tells you in chat; a new requirement reopens the epic. You can also
spawn an engineer, qa or adversary yourself from Seats / a story page (Spawn seat).

## 4. What you actually do
1. Design sign-off: the architect presents the design; press Approve (or ask questions first).
2. Mark as requirement: select words in any message and press the second button on the quote card. It
   sends no message; the epic cannot finish until the architect links the requirement to a criterion or
   a design section.
3. Answer in chat when the architect asks, including a reply that lifts the story cap (the board checks
   the message id is yours).
Everything else runs without you. Steers any time: message_send(kind=steer) on any ticket.

## 5. Watching
- http://127.0.0.1:9400/ui — epics; /ui/epic/<id> — live tree, gates, thread (auto-refresh);
  /ui/ticket/<id>; /ui/doc/<id> (versions). /docs — raw API.
- Docs mirror: the board writes every doc a seat can see as a read-only `.md` file under `<agent-home>/docs/<scope>/`
  in the same step as the database write; seats Read and grep it, and every edit goes through `doc_edit`.
- Any spawned shell window is yours to type into; whatever you say there lands on its ticket.

## 6. When something looks stuck
- Board truth first: /ui/epic/<id> — who owns the open gate? whose criteria are pending?
- Seats page recovers: a dead seat on a live ticket -> Resume, or Spawn seat again; reap only
  what is truly stuck. **Close** ends a live shell and records it as closed by you (not a crash); it is
  also beside Resume on the epic page. Pool crash and close events go to the architect, who resumes or
  restarts; a parked shell wakes by itself when a message lands in its broker inbox.
- Rules advise, they do not block: only state transitions, who may approve, safety, evidence, doc version
  and the shell cap refuse. Other guards are hints a seat can override. Each role gets only its own tools.
- Framework fights an agent -> it files /pain (a board record; Library > Pains) and continues; read it.

## 7. Knowledge that persists
- Domain + strategy docs (sme-authored) persist across epics; learnings are folded in at close.
- Every epic's design, reports, thread and verdicts stay on the board — the record IS the docs.

## 8. The event matrix (no blind spots — every write fans out)
| write | event (feed, filtered per identity) | broker inbox (durable) | extra |
|---|---|---|---|
| message/comment (any surface) | message_sent {from, from_type, from_role, mentions} | recipient + every @mention | recipient is a CLOSED agent seat → the architect gets a hint naming it |
| criterion verdict (UI or tool) | criterion_checked {by, by_type, verdict, evidence} | — (rides the feed) | auto-advance may fire status_changed |
| gate open / answer | gate_opened / gate_answered {by} | epic's owning human / gated ticket's assignee | Slack doorbell for mapped humans |
| epic to in_review | hint `qa_available` | architect | the architect decides whether to start qa |
| status change | status_changed {from, to, by} | — | owner sees phase boundaries only |
| shell close/death | shell_dead {reason, clean} | architect | reason always present |
Humans are reached identically to agents: `message_send(to='@handle')` → inbox → Slack deep link
to the exact ticket. Agents discover the team with `participants` (rows carry reach).

## 9. Co-working with humans
Teammates join with a browser, zero tokens: docs/TEAM.md — Tailscale connect, register +
token, `/ui/me` inbox (replies, gates, reply forms), @mentions, per-owner epic scoping,
optional Slack doorbell (`slack_map.json` + start-bridge.ps1).

## 10. Optional
- Plane portal: v8/docs/PLANE.md (their installer + API key + EDP8_PLANE_* env + webhook).
- Docker board: `docker compose up -d board` in v8/ (compose file included).
- Teammates: invite them from Admin -> Teammates; people act in the web UI, never through a shell.
