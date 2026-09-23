# Self-improvement, phase 1: a regression tripwire

The memory layer changes every day: new records, retired records, retrieval code changes. Phase 1
of the board's self-improvement design (report-9a85d0418e) guards what already works. It is a
**tripwire**, not an optimiser.

- **What it does.** It replays a tracked set of questions (`v8/tests/rsi/manifest.json`), each naming
  the record ids a correct pack must contain, through the live `lookup`. If a record that the last
  passing run found has gone missing, the run is marked *regressed* and the architect gets **one**
  finding message listing the missing ids.
- **What triggers it.** Either of two things, with no human involved:
  - the records change, measured by a fingerprint over every record and link, once 20 rows differ
    or the last run is more than 24 hours old;
  - the retrieval code the running board actually loaded changes (`knowledge.py`, `search.py`,
    `store.py`, `exam.py`). If the file on disk differs from what is loaded, the tripwire holds until
    the board restarts.
- **What it never touches.** Exams and their answers, the grader and scorer, binding rules,
  deletions, and code (report-9a85d0418e, section 4). Phase 1 writes only its own three tables and that one
  message. It makes **zero** generative model calls, and it fails closed: a broken manifest or a failed
  search is an *error*, never a *pass*.
- **Cost, measured on a copy of the live database** (report-6ec4bcaa1d): a tick takes **1.51 s** at a
  peak of **834.7 MB** with a warm vector cache. The first run, which loads the embedding model, takes
  31 s and peaks at 1,374.6 MB. There are **51 tests** in `v8/tests/test_rsi.py` (commits `de79cf1`,
  `87b0600`, `ca4cbc4`).
- **Turn it on.** Add `EDP8_RSI=1` to `v8/.env`, then run `.\edp.ps1 restart board`. It ticks every 15
  minutes (`EDP8_RSI_INTERVAL_S`, default 900) and holds when free RAM is below 1,500 MB
  (`EDP8_RSI_RAM_FLOOR_MB`). To turn it off, remove the line and restart the board. To tick
  by hand, from `v8\`: `.venv\Scripts\python -m edp8.rsi tick --dry-run --db .data\edp8.db` (or
  `show --db .data\edp8.db` for the last run).

Later phases (outcome capture, a guard against re-proposing a failed idea, continuous curation, and
paired A/B promotion with a human confirming) are designed in report-9a85d0418e, section 9 and not built yet.

