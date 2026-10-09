# S17 live completeness and cost run (c-e8ecddefcf)

Run id `s17live`, 2026-10-03. Code at main 6e7ee10b.

**Completeness holds on 5/6 usable plans.** Codex gpt-6-astra planned each lab story through the real edp8 tools (ticket_read, doc_read and find). The pinned judge claude-opus-5-5 found every must item and must-not item, and the order kept, on all six. A3 is still not usable: its plan sets `"complete": false` and blocks on ambiguity it invented (adversary finding m-a5c1629c35). The judge's truncation check (`s17judge.py:74`) only checks that the word `"complete"` appears, so a `"complete": false` plan passes it.

**The 40% read-cost target is missed.** Live chars read are only 3% below the lab full-pyr run (whole docs) and 28% above lab full-orig. Codex paged through nearly every doc anyway: doc_read is 91.33–93.59% of chars read across the six stories (the adversary's count from the raw ledgers). Reported as measured, with no extra caps added (ruling m-c6cdb0602c).

| Story | lab full-orig | lab full-pyr | live | live vs orig | live vs pyr | score orig | score pyr | score live |
|---|---:|---:|---:|---:|---:|---|---|---|
| A1 | 216,538 | 275,133 | 276,126 | +28% | +0% | 18/18 7/7 3/3 | 18/18 7/7 3/3 | 18/18 7/7 3/3 |
| A2 | 198,054 | 278,194 | 288,617 | +46% | +4% | 16/16 7/7 3/3 | 16/16 7/7 3/3 | 16/16 7/7 3/3 |
| A3 | 197,513 | 276,997 | 255,367 | +29% | -8% | 14/14 8/8 3/3 | 14/14 8/8 3/3 | 14/14 8/8 3/3 |
| B1 | 227,074 | 321,373 | 317,472 | +40% | -1% | 15/16 6/6 3/3 | 16/16 6/6 3/3 | 16/16 6/6 3/3 |
| B2 | 205,808 | 259,132 | 252,187 | +23% | -3% | 15/15 6/6 2/2 | 15/15 6/6 2/2 | 15/15 6/6 2/2 |
| B3 | 259,486 | 316,530 | 284,695 | +10% | -10% | 16/18 5/5 3/3 | 17/18 5/5 3/3 | 18/18 5/5 3/3 |
| **total** | 1,304,473 | 1,727,359 | 1,674,464 | **+28%** | **-3%** | | | |

Scores are must present / must-not ok / order kept. Lab columns are the plan lab's codex `full` runs: whole docs, orig and summary-first (pyr) layouts.

## Memory guard (architect m-7ab6d05e20)

Free memory was checked before each story and every 10 s during it, with a 600 MB floor. The floor was never reached. Per story, the minimum free memory was 1,929–2,595 MB and the peak 2,714–3,419 MB (`run.txt`). One codex ran at a time.

## Files

| File | Contents |
|---|---|
| `run.txt` | per story: rc, seconds, calls, chars by tool, min/peak free MB |
| `judge.txt` | per-story judge verdicts |
| `plans/<sid>.calls.jsonl` | every tool call with its chars |
| `plans/<sid>.last.txt` | the plan |
| `plans/<sid>.judge-claude.json` | the judge's item-by-item grading |
| `s17run.py`, `edpserver.py`, `s17judge.py`, `compare.py` | the harness; `LAB_ROOT` is the private plan lab (not committed) |
