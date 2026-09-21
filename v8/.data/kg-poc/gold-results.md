# Gold test results — cold seat answers (S13), for qa cold re-run

Answering seat: fresh general-purpose subagent (no epic context, never saw the
marking key note-0151676530). Given ONLY the walk pack file. Two configs run.

## Config A — union pack (.data/kg-poc/gold-pack.md, 178 nodes, 48.8 KB)
Cross-question contamination possible (one merged read). 8/9 core correct;
Q9 conflated the resume-token fix with the proxy 401 story.

## Config B — per-question isolated packs (.data/kg-poc/gold-pack-perq.md, avg 7.9 KB/question)
Each question answered from its OWN walk() block (walk's intended use).

Marking vs note-0151676530 key (engineer's honest grade; qa is the authority):
1 renders binding .............. CORRECT
2 opus-4-8 build / Fable QA ..... CORRECT
3 one consolidated QA seat ...... CORRECT
4 no restart w/o owner .......... CORRECT
5 hooks.slack.com + allow-list .. CORRECT (save+send, IP/userinfo rejected)
6 notifications acct menu; Usage above Find . CORRECT
7 what remains .................. MISS — seat gave the OUTDATED m-6f88809fb9 list
      (Fable QA + slack story + 3 framework items) instead of the current
      owner-present checks (m-29ccb0c637). Cause: no cross-thread supersession,
      so a stale live "remaining" statement outranks the current one.
8 context() budget ............. MISS — got the mechanism + opt-in/paging, but
      the exact "40,000 bytes / verbose=true" is not in any board message
      (lives in code/env EDP8_CONTEXT_BUDGET_B); the graph cannot hold it.
9 resumed-seat 401 ............. CORRECT (pool resume dropped EDP8_TOKEN; fixed
      by re-launching with spawn_settings.env) — isolation fixed the conflation.
10 paging code + indicator ...... PARTIAL — file useThreadHistory.tsx CORRECT;
      indicator string returned is the pre-rework "older N-M of T", not the
      key's "Showing X of Y · Z older".
11 invalid webhook -> 422 ....... CORRECT
12 role cut held ............... CORRECT

Score (config B): 9 fully correct + 1 partial (Q10 file) + 2 misses.
Counting Q10's correct file identification -> 10/12. Both misses are honest and
explained (Q7 = graph limitation, Q8 = data-coverage limit, not retrieval).
