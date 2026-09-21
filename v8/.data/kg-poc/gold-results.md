# Gold test results — cold seat answers (S13), for qa cold re-run

Answering seat: a fresh general-purpose subagent (no epic context, never saw the
marking key note-0151676530), given ONLY the walk pack. Three configs were run;
the numbers below are the FINAL run on the corrected pack (after the
second-opinion fixes). qa is the grading authority — this is the engineer's
honest self-grade.

## Retrieval, measured two ways
- SHAPED seeds (seed terms drawn from the question, which the steer permits):
  answer-node presence 12/12; seed@5 FTS5 11/12, TF-IDF 11/12.
- UNAIDED (raw question text as the seed, no shaping): seed@5 6/12; walk
  answer-node presence 8/12 (walk misses Q2, Q3, Q5, Q12). This is the honest
  unaided retrieval number; do NOT generalise 12/12 to unaided.
- `uses` factor exercised (max uses 36 after warm-up): it evicted NO needed node.

## Answer correctness vs the key (corrected pack)
1 renders binding ............. CORRECT
2 opus-4-8 build / Fable QA ... CORRECT (QA=Fable is inferable only from
      "independent Fable qa verdict"; thin but present)
3 one consolidated QA seat .... CORRECT
4 no restart w/o owner ........ CORRECT
5 hooks.slack.com + allow-list  CORRECT (EDP8_SLACK_WEBHOOK_HOSTS, IP rejected, save+send)
6 notifications acct menu; Usage above Find . CORRECT
7 what remains ................ MISS — seat still gave the OUTDATED m-6f88809fb9
      "not done yet" list, not the current owner-present checks (m-29ccb0c637),
      even though that node's DETAIL (quiet-hours + pool session tokens) was in
      the block. Root cause: no cross-thread supersession/recency ranking, so a
      well-structured stale "remaining" statement out-reads the current one.
8 context() budget ............ MISS — mechanism correct, but the exact
      "40,000 bytes / verbose=true" is NOT extracted (it lives in
      src/edp8/bundles.py:494, not in any ingested board message). Coverage gap,
      not a retrieval failure.
9 resumed-seat 401 ............ BORDERLINE — seat named the proxy-not-forwarding
      token path (fix 561dc3a), which is a related but distinct bug from the
      key's "pool resume() dropped the token" (76b8ea6/f669090). The graph holds
      the proxy/minter token nodes, not the resume-drop node. Count as partial.
10 paging code + indicator ..... CORRECT — useThreadHistory.tsx AND the exact
      indicator "Showing 100 of 132 · 32 older" / "Showing 132 of 132"
      (surfaced by the _detail excerpt-window fix).
11 invalid webhook -> 422 ...... CORRECT
12 role cut held .............. CORRECT

Honest score: 9 solidly correct (Q1-6, 10, 11, 12) + Q9 partial + Q7, Q8 miss.
Counting Q9's essence (token-not-reaching-a-resumed-seat, fixed) -> 10/12.
Both hard misses have named causes and fixes in the findings (report-70411801d5):
Q7 = cross-thread supersession (not built), Q8 = extract code/env facts.
