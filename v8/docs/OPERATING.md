# Operating v8 — the owner's guide

## 1. Start / stop
- `edp.ps1` (repo root) is the one ops script: `.\edp.ps1 status`, `.\edp.ps1 start|stop|restart
  <board|mcp|pool|broker|bridge|supervisor|all>`, `.\edp.ps1 update`; add `-WhatIf` to see the plan.
  It brings up broker :9300 (inboxes, the wake plane), board :9400 (web UI at /ui, the
  state-transfer record), pool :9301 (shells), MCP :9402, the Slack bridge and the supervisor.
  Safe-restart rules: `guides/edp-ps1.md`.
- `start-v8.bat` / `stop-v8.bat` are thin wrappers (`edp.ps1 start all` / `edp.ps1 stop all -Force`).
  Docker is NOT required for local use.
- The planes: the BOARD holds state (tickets, criteria, docs, gates); the BROKER delivers —
  every addressed message/gate is mirrored to the recipient's inbox, the pool's watchdog
  resumes a parked shell when its inbox grows; each shell's Monitor tails board feed + broker
  inbox (event-driven), with a 30-min cron heartbeat as the only fallback.

## 2. Your entrypoint: the web UI

The owner is a person, never an agent: no path launches a shell as the owner role (owner
m-da9a2ae62f). Start the services (`edp.ps1 start all`, or `owner.bat` / `start-v8.bat`, which call
it) and open http://127.0.0.1:9400/ui. Questions, gates, demos and findings reach you there
(Needs you, /ui/me) and, when mapped, in Slack. Planning conversations happen in the ARCHITECT'S
window (it is yours to type into).

## 3. Kick off work
New epic in the UI (your words verbatim) with "spawn the architect" ticked: the board spawns
`architect.<epic>`. It designs, has SMEs write the strategy docs, writes stories + criteria and
opens your design_signoff gate. From there the architect spawns each phase: an engineer per ready
story -> an adversary on the adversarial review story (you pick the findings to take up) -> qa
when the acceptance gate opens -> your acceptance answer -> close. You can also spawn an
engineer, qa or adversary yourself from Seats / a story page (Spawn seat).

## 4. What you actually do (the five touchpoints)
1. design_signoff — the architect presents the design; answer the gate (or ask questions first).
2. POC gate (rnd) — continue / pivot / stop after the proof.
3. demo — look at the artifact a shell shows you; react.
4. adversarial scope findings — Sol found something non-obvious; your call.
5. acceptance — qa's verdict against your words; you accept or name gaps.
Everything else runs without you. Steers any time: message_send(kind=steer) on any ticket —
small = redirect in place; big = the architect is forked to re-comprehend and you re-sign.

## 5. Watching
- http://127.0.0.1:9400/ui — epics; /ui/epic/<id> — live tree, gates, thread (auto-refresh);
  /ui/ticket/<id>; /ui/doc/<id> (versions). /docs — raw API.
- Needs you (/ui/me) carries your questions, gates, demos and findings — nothing else.
- Any spawned shell window is yours to type into; whatever you say there lands on its ticket.

## 6. When something looks stuck
- Board truth first: /ui/epic/<id> — who owns the open gate? whose criteria are pending?
- Seats page recovers: a dead seat on a live ticket -> Resume, or Spawn seat again; reap only
  what is truly stuck. A parked shell wakes by itself when a
  message lands in its broker inbox; the cron heartbeat is the last-resort nudge.
- Framework fights an agent -> it files /pain (v8/.pain/pain-points.jsonl) and continues; read it.

## 7. Knowledge that persists
- Domain + strategy docs (sme-authored) persist across epics; learnings are folded in at close.
- Every epic's design, reports, thread and verdicts stay on the board — the record IS the docs.

## 8. The event matrix (no blind spots — every write fans out)
| write | event (feed, filtered per identity) | broker inbox (durable) | extra |
|---|---|---|---|
| message/comment (any surface) | message_sent {from, from_type, from_role, mentions} | recipient + every @mention | recipient is a CLOSED agent seat → owner gets an fyi naming it |
| criterion verdict (UI or tool) | criterion_checked {by, by_type, verdict, evidence} | — (rides the feed) | auto-advance may fire status_changed |
| gate open / answer | gate_opened / gate_answered {by} | epic's owning human / gated ticket's assignee | Slack doorbell for mapped humans |
| status change | status_changed {from, to, by} | — | owner sees phase boundaries only |
| shell close/death | shell_dead {reason, clean} | owner (crashed/fyi) | reason always present |
Humans are reached identically to agents: `message_send(to='@handle')` → inbox → Slack deep link
to the exact ticket. Agents discover the team with `participants` (rows carry reach).

## 9. Co-working with humans
Teammates join with a browser, zero tokens: docs/TEAM.md — Tailscale connect, register +
token, `/ui/me` inbox (questions, gates, reply forms), @mentions, per-owner epic scoping,
optional Slack doorbell (`slack_map.json` + start-bridge.ps1).

## 10. Optional
- Plane portal: v8/docs/PLANE.md (their installer + API key + EDP8_PLANE_* env + webhook).
- Docker board: `docker compose up -d board` in v8/ (compose file included).
- Teammates: invite them from Admin -> Teammates; people act in the web UI, never through a shell.
