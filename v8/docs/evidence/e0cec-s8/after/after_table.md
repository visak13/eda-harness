# S8 before/after: what a seat turn costs (c-8e33e18581)

`after_table.py` reruns the BEFORE scripts (`wake_costs.py`, `token_split.py`) over the seat transcripts and splits them
into two windows: BEFORE is the corpus up to 2026-10-01, and AFTER starts on 2026-10-05, the first day on 0.10.x
(installed 2026-10-04). Output: `after_table.json`. Dollar figures are list-price estimates; on a subscription the
token counts are the real cost.

| Per unit | Before (09-07..10-01) | After (10-05..10-08) | Change |
|---|---|---|---|
| Turns measured | 4,501 (278 sessions) | 126 (5 sessions) | |
| Cost per turn | $1.13 | $0.51 | −55% |
| Tokens per turn | 1.59 M | 0.77 M | −52% |
| Cost per turn that changed something | $1.88 | $1.05 | −44% |
| Boot context, median (first call) | 48.1 K | 34.7 K (3 boots) | −28% |
| Heartbeat (cron) turns per active day | 29.5 | 0 | gone |
| Turns that did nothing (read-only or no tool) | 40% of turns, 6% of cost | 52% of turns, 12% of cost | worse |
| Monitor wakes that did nothing | 46% | 56% | worse |

Turns are counted once even when a pool transcript is a copy of another seat's file (one AFTER file was; the first
version of this table counted its 57 turns twice). Why the no-action share rose: `wake_rca.md` beside this file.

**Caveat:** the fleet ran on one day of the AFTER window (168 turns on 10-05, 2 on 10-08). The calendar window is
over 24 h, but the sample is small, so read the direction of each row, not its exact size.

**What it shows:** the S8 cuts worked. Heartbeats are gone, the boot context is 28% smaller, and a turn costs less
than half as much. Wasted wakes did not improve: more than half of the monitor wakes ended without an action, which
makes them the next target.
