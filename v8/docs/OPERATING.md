# Operating v8 — the owner's guide

## 1. Start / stop
- `start-v8.bat` (repo root) — broker on :9300 (inboxes, the wake plane) + board on :9400
  (web UI at /ui, the state-transfer record) + pool on :9301 (shells), participants registered.
- `stop-v8.bat` — tears all three down. Docker is NOT required for local use.
- The planes: the BOARD holds state (tickets, criteria, docs, gates); the BROKER delivers —
  every addressed message/gate is mirrored to the recipient's inbox, the pool's watchdog
  resumes a parked shell when its inbox grows; each shell's Monitor tails board feed + broker
  inbox (event-driven), with a 30-min cron heartbeat as the only fallback.

## 2. Your entrypoint: the owner shell

One command does everything: **`owner.bat`** (repo root) — starts board + pool if needed and
drops you into your owner shell pinned to the fleet standard: model claude-opus-4-8, 350k
auto-compact window. Overrides per launch: `owner.bat 500000` (bigger window this session),
`owner.bat 350000 <model-id>` (model too); env EDP8_ACW / EDP8_OWNER_MODEL also work. The manual steps below are what it does:
    cd v8
    set EDP_HANDLE=owner
    claude
    /owner
The card boots you: whoami -> subscribe (run the returned monitor once, cron once) -> your feed is live.
You are the project manager. Planning conversations happen in the ARCHITECT'S shell (its window
is yours to talk in; your feed only gets a one-line pointer). Direct questions/gates/demos reach
your feed and you answer here.

## 3. Kick off work — the owner shell spawns every seat (only SMEs come from the architect)
Say your goal to the shell; it creates the epic verbatim and spawns the architect:
- ticket_create(kind=epic, work_type=feature|bug|rnd|creative|chore, title=<your words, verbatim>)
- spawn(role=architect, ticket_id=<epic>) — the pool opens the architect's window with /architect.
Then go talk in the ARCHITECT'S window (it plans in plan mode): it designs, spawns SMEs for the
high- and low-level strategy docs (assemble_ruleset composes them), writes stories + criteria,
and opens your design_signoff gate. SMEs closed + plan signed = architect stands down.
From there your shell spawns each phase as the feed announces it:
engineer per ready story -> reviewer on in_review -> adversary on the adversarial review story
(codex consult; you pick the findings to take up; iterate till you close the gate) -> qa when
the acceptance gate opens -> your acceptance answer -> close.

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
- Your feed (owner shell) carries questions, gates, demos, findings, status notes — nothing else.
- Any spawned shell window is yours to type into; whatever you say there lands on its ticket.

## 6. When something looks stuck
- Board truth first: /ui/epic/<id> — who owns the open gate? whose criteria are pending?
- Your shell recovers: a shell_dead feed line on a live ticket -> resume(<participant>) or
  spawn the seat again; reap only what is truly stuck. A parked shell wakes by itself when a
  message lands in its broker inbox; the cron heartbeat is the last-resort nudge.
- Framework fights an agent -> it files /pain (v8/.pain/pain-points.jsonl) and continues; read it.

## 7. Knowledge that persists
- Domain + strategy docs (sme-authored) persist across epics; learnings are folded in at close.
- Every epic's design, reports, thread and verdicts stay on the board — the record IS the docs.

## 8. Co-working with humans
Teammates join with a browser, zero tokens: docs/TEAM.md — Tailscale connect, register +
token, `/ui/me` inbox (questions, gates, reply forms), @mentions, per-owner epic scoping,
optional Slack doorbell (`slack_map.json` + start-bridge.ps1).

## 9. Optional
- Plane portal: v8/docs/PLANE.md (their installer + API key + EDP8_PLANE_* env + webhook).
- Docker board: `docker compose up -d board` in v8/ (compose file included).
- Teammates: register a participant for them (any role); their shell = EDP_HANDLE=<their id>.
