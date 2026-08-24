# Operating v8 — the owner's guide

## 1. Start / stop
- `start-v8.bat` (repo root) — board on :9400 (web UI at /ui) + pool on :9301, participants registered.
- `stop-v8.bat` — tears both down. Docker is NOT required for local use.

## 2. Your entrypoint: the owner shell

One command does everything: **`owner.bat`** (repo root) — starts board + pool if needed and
drops you into your owner shell. The manual steps below are what it does:
    cd v8
    set EDP_HANDLE=owner
    claude
    /owner
The card boots you: whoami -> subscribe (run the returned monitor once, cron once) -> your feed is live.
You are the project manager. Everything reaches you as feed events; you answer in this shell.

## 3. Kick off work
Say your goal to the shell and have it create the epic verbatim, then spawn the coordinator:
- ticket_create(kind=epic, work_type=feature|bug|rnd|creative|chore, title=<your words, verbatim>)
- spawn(role=coordinator, participant_id=coordinator)
From here the board runs it: coordinator -> architect (design, /ocak, stories, criteria) -> your
design_signoff gate -> engineers/reviewers per story -> adversarial review story -> qa -> your
acceptance gate -> close.

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
- The coordinator recovers dead/stalled shells itself; you can steer it ("resume X", "replace Y").
- Framework fights an agent -> it files /pain (v8/.pain/pain-points.jsonl) and continues; read it.

## 7. Knowledge that persists
- Domain + strategy docs (sme-authored) persist across epics; learnings are folded in at close.
- Every epic's design, reports, thread and verdicts stay on the board — the record IS the docs.

## 8. Optional
- Plane portal: v8/docs/PLANE.md (their installer + API key + EDP8_PLANE_* env + webhook).
- Docker board: `docker compose up -d board` in v8/ (compose file included).
- Teammates: register a participant for them (any role); their shell = EDP_HANDLE=<their id>.
