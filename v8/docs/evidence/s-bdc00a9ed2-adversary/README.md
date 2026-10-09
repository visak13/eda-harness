# Bounded Astra review at 7f8ebe4d

The probes reproduce four defects and one scope question; passing them means the recorded behavior was observed, not that the product is correct. They are outside the regression suite intentionally. No product code changed.

## Reproduce

From `v8/`, copy `docs/evidence/s-bdc00a9ed2-adversary/review_probes.py` to a new file `tests/adversary_s_bdc00a9ed2/test_review_probes.py`. Run with `PYTHONPATH=src` using `.venv/Scripts/python.exe -m pytest tests/adversary_s_bdc00a9ed2/test_review_probes.py -q -s`, then remove only that copied file. The tests must run under `tests/` to inherit the fleet-isolation fixtures in `tests/conftest.py`. They create temporary databases and local in-process TestClients, not listening servers. No live-board data is modified.

## Actual results on Windows, 2026-10-09

- Product tests: `tests/test_doc_tools_file_shaped.py`: **25 passed in 5.69s**.
- Review probes: **15 passed in 13.43s**. This includes an actual Windows open-reader handle causing mirror replacement to fail, without fault injection.
- Neighbor tests: `tests/test_doc_reading.py tests/test_s13_round1_s17.py`: **29 passed in 10.36s**.
- After making evidence relocation independent of file depth, the two measurement probes were checked again: **2 passed, 13 deselected in 1.39s**.
- Synthetic startup backfill: **600 docs, approximately 4.9 MB, 1.755s**; second run `same=600`; stale `.md.tmp` removed. This is a bounded sample, not a throughput or maximum-size guarantee.
- Baseline script, `--until 2026-10-09`: **578 files; 1,714 calls; 219 errors; 12.78%; 997 attempted writes; median argument bytes 2,634**. These reproduce the engineer's numbers; the probes expose limitations in what those numbers measure.

## Findings

| ID | Class | Reproduced result |
|---|---|---|
| F1 | P1, obvious bug. | Hold an ordinary read handle open on a mirror file while editing its doc. The API reports success and DB advances to v2, but the mirror remains v1 and becomes writable. Backfill also reports failed replacement as written. |
| F2 | P2, obvious bug. | Inject an FTS failure after staging: DB and final file stay v1, but the full uncommitted v2 remains readable in `.md.tmp` until another write or startup. |
| F3 | P2, obvious bug. | For unnumbered Alpha/Beta headings, `section=0` returns Beta; `section=1.0` raises IndexError and returns HTTP 500. |
| F4 | P2, obvious counting bug. | A failed call spanning UTC midnight is absent from both windows' error totals. Failed writes also count as `doc_changes`; label the metric as attempted-write bytes or calculate successful-change cost explicitly. |
| Q1 | Scope question. | A native mirror-only reader holding v1 has no read-ledger entry, so its unpinned replace-all applies to new v2 occurrences too. Normal concurrent HTTP readers do conflict correctly. |

## Negative controls

Alias collisions are refused in both HTTP and MCP argument models. Two concurrent HTTP readers yield one success and one version conflict. Thirty hostile scope/id combinations remain inside the mirror root. A guest outside the doc closure gets HTTP 404 and cannot retrieve the file through tested mirror-shaped URLs; a local engineer can already read the same content via HTTP. Healthy read-only enforcement and ordinary ambiguous section candidates are covered by the 25 product tests. Unicode output and revised skill wording also pass there. No probe was refused by model safeguards.

The linked board report supplies source-line references and the handoff verdict. Live deployment, proxy/seat respawn, and a post-release measurement window were not exercised; no service restart was authorized.
