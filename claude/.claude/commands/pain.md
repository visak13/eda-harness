# /pain — report a framework pain point (any role, mid-work)

You hit a place where the FRAMEWORK — not your task — fought you. This
skill files that observation as ONE structured record and returns you to
work. It is a flight recorder, not an escalation: filing a pain point
never replaces `ask_above`/`notify_above` for a blocker you still need
resolved.

## WHEN to trigger (any of these, the moment it happens)

- A tool REFUSED you and the refusal contradicts your card, a guide, or
  an instruction you were given (told to do X; X is refused).
- An instruction names a verb/tool/field that does not exist on your
  surface (phantom verb, unknown kwarg silently dropped, wrong schema).
- A wake that should have fired didn't (Monitor silent, cron dead,
  reply landed but nothing woke you), or you were woken for nothing
  repeatedly.
- The record contradicts reality (object state says X, disk/pool says
  Y) and no tool exists to reconcile it from your seat.
- You had to IMPROVISE AROUND the framework (hand-compose what a tool
  should have returned, re-derive state a digest should carry, retry a
  verb with guessed arguments until one stuck).
- Two authoritative texts disagree (card vs guide vs refusal text) and
  you had to pick one.
- A gate/budget/cap fired in a way that cost real time without
  protecting anything (name the cost).

Do NOT file: your own mistakes, task-domain problems (failing tests in
the USER'S project), transient environment noise (network blip), or
anything already filed this session for the same cause (one cause = one
record; add nothing on repeat hits).

## WHAT to do (exactly this, then back to work)

Append ONE line — a single-line JSON object, no pretty-printing — to
**`C:\Projects\Learning\eda-base3\claude\docs\pain-points.jsonl`**
(create the file if missing; NEVER rewrite or edit existing lines).
Use your shell (Bash/PowerShell) to append; do not open an editor.

Record shape (all keys present; use "" / [] when empty):

```json
{"ts": "<ISO-8601 UTC now>", "role": "<EDP_ROLE or 'base'>",
 "handle": "<EDP_HANDLE or session id>", "severity": "high|medium|low",
 "area": "prompts|tools|gates|fsm|memory|wake|spawn|broker|other",
 "symptom": "<what happened, one factual sentence>",
 "expected": "<what the card/guide/tool led you to expect>",
 "evidence": "<verbatim refusal text / tool name+args / file:line — the
              thing a fixer can grep for>",
 "workaround": "<what you did instead, or 'blocked'>",
 "cost": "<rough time/tokens lost, e.g. '2 wakes', '20min'>"}
```

Rules of the record:
- `severity`: high = blocked or wrong result shipped; medium = real
  time lost, work continued; low = friction/confusion, no loss.
- `evidence` is the contract: verbatim strings beat paraphrase — a
  maintenance session must be able to reproduce the hunt from it.
- One line = one pain point = one root cause. Two symptoms of one
  cause: one record, both symptoms in `symptom`.
- Never include secrets, user content, or task deliverables.

After the append: say nothing beyond one line (`pain point filed:
<area> — <symptom>`) and CONTINUE your task exactly where you left it.
If the pain point also blocks you, route the blocker through your
normal escalation (`ask_above`) — the record is telemetry, not a
request for help.

## Who reads it

Maintenance/campaign sessions and the operator read
`docs/pain-points.jsonl` newest-first and fix causes, not symptoms.
The file is append-only history; resolved entries are never deleted —
fixes reference them by `ts` in commits and the F-ledger
(`docs/observations-qa.md`).
