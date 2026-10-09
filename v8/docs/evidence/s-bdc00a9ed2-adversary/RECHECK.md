# Selected-finding recheck at 0f8fab4d

Concerns remain in F1 and F2; F3, F4, and the decided Q1 behavior pass. This is the single bounded recheck requested in m-860faaff0c. No product files were changed.

## Actual verification

Copy `recheck_probes.py` to `tests/adversary_s_bdc00a9ed2/test_recheck.py` so `tests/conftest.py` isolates the host. From `v8/`, with `PYTHONPATH=src`, run `.venv/Scripts/python.exe -m pytest tests/test_doc_tools_file_shaped.py tests/adversary_s_bdc00a9ed2/test_recheck.py -q -s`. Remove only the copied file afterwards.

Actual result on Windows: **48 passed in 14.41s** (43 engineer tests and five independent recheck probes). The two residual probes intentionally assert the observed defects; their passing is not a clean verdict.

| Finding | Recheck verdict |
|---|---|
| F1 | Partial. Exhausted real Windows reader retries now restore read-only protection. A subsequent doc commit repairs the queue and failed backfill counts correctly. But a non-doc commit does not repair it, contrary to the selected next-commit repair rule. |
| F2 | Partial. An FTS failure or outer rollback after stage returns cleans its temp. A failure inside stage itself (reproduced by fsync raising after the body is flushed) leaves the full uncommitted body in `.staging/*.tmp`; rollback cleanup was not yet registered. |
| F3 | Pass. HTTP requests for `0`, `-1`, `1.0`, and `1.-2` on unnumbered headings return section_match with a count-from-1 hint, not 500. Explicitly zero-numbered headings intentionally still resolve. |
| F4 | Pass for the picked failures. Midnight-spanning calls stay in the call's window; only successful writes count as changes. |
| Q1 | Pass as decided. Explicit stale front-matter version is rejected; unserved/unpinned edit identifies latest-version fallback and points to expected_version. The checked-in skill names the native-read limitation. |

## Residual reproductions and source references

**F2, P2, obvious residual:** In a mirrored Store, update an existing doc with `UNCOMMITTED_STAGE_FAILURE_MARKER` while mocking `edp8.doc_mirror.os.fsync` to raise OSError. Store.put raises, the DB and final file retain the prior body, but recursive inspection finds the full marker in `.staging`. `src/edp8/doc_mirror.py:40-54` does not remove partial staging output on failure. `src/edp8/store.py:385-386` registers after_rollback only after stage returns. Stage must own cleanup until it successfully hands back its path, or cleanup must be registered before its first write.

**F1, P2, selected-contract gap:** Hold the mirror open with an ordinary Windows Python reader during an edit, then close it. The pending doc and restored read-only file are correct. Commit a changed participant through Store.put; verify that change persisted. The mirror stays stale and queued. Commit another doc; only then is it repaired. `src/edp8/store.py:393-400` retries pending entries exclusively from a doc publication callback, not after every next commit as m-c7e0d9ad8f requested. Either implement bounded next-commit draining or explicitly accept the narrower next-doc-commit trigger.

## Revised baseline reproduced

`.venv/Scripts/python.exe scripts/doc_call_baseline.py --until 2026-10-09` returned 1,714 calls, 219 errors (12.78%), one missing result, 847 successful writes, median 2,880 bytes, mean 3,902 bytes; 997 attempts retain median 2,634 bytes. It enumerated 579 transcript files versus the engineer's earlier 578 because the directory gained a file; the pre-cutoff counts matched exactly. No post-release window was exercised.

Further fixes or rechecks require a fresh architect message. The evidence probes stay outside the normal test suite because they record the current residual behavior.
