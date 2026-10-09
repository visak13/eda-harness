# S10 security scan: bandit + semgrep + pip-audit (criterion c-ca6e7a5637, second clause)

**Status: bandit and pip-audit ran locally (pip reaches PyPI from the desktop build venv; uv does not, WinError 10013); semgrep cannot run on
native Windows (no semgrep-core), so its rules were read by grep and the first CI run is its check.** A finding CI shows that is absent
here is added to this table with a decision and a reason, never ignored.

Local runs, 2026-10-02, on the S10 tree (commits through P4), same configs and pins as CI:
- `bandit -r -ll -c .github/security/bandit.yaml v8/src edp-pool/src edp-broker/src edp-contracts/src` (1.9.4): **0 medium, 0 high**, 5 sites
  suppressed by a reasoned `# nosec`, 156 low (not gated), 43178 lines. Output kept in the S10 report.
- `pip-audit --strict --no-deps --disable-pip -r <uv export of v8/uv.lock>` (2.10.1): the first run **found 16 advisories**: pyjwt 2.13.0 (13,
  fixed in 2.14.0/2.15.0) and urllib3 2.7.0 (3, fixed in 2.8.0). Fixed by raising both in `v8/uv.lock` (2.15.0, 2.8.0; hashes from PyPI;
  uv cannot relock on this host, so by hand as 3c03345 did); the rerun reports **No known vulnerabilities found**. edp-contracts, edp-pool
  and edp-broker are resolved fresh in CI (`uv pip compile`), so they take the current releases; that part is CI's check.

Job: `security` in `.github/workflows/ci.yml` (ubuntu only, 15 min, uv cache). Tools pinned: bandit 1.9.4, semgrep 1.179.0,
pip-audit 2.10.1 (PyPI latest on 2026-10-02). Config: `.github/security/` (bandit.yaml, semgrep-rules.yml, pip-audit-ignore.txt).

| finding | where | decision | reason |
|---|---|---|---|
| B324 / weak-hash-for-security: `hashlib.sha1` | v8/src/edp8/api_views.py:181, codex_seat/tools.py:153, tool_paging.py:46, edp-pool/src/edp_pool/pty/_posix.py:26 | fixed | an ETag, a short id, a cache key and a socket-name hash: not security controls; now `usedforsecurity=False` |
| B605 / os-system: `os.system(f"title {handle} ...")` | v8/src/edp8/codex_seat/run.py:141 | fixed | the seat handle went through a cmd.exe shell; now `SetConsoleTitleW` (ctypes), no shell |
| B310 urlopen scheme | v8/src/edp8/code_service.py:568 | fixed + nosec | the lock's URL must be https (checked first); the download is sha256-verified |
| B310 urlopen scheme | v8/src/edp8/harvest_cost.py:214 | fixed + nosec | the board URL must be http(s) (checked first) |
| B310 urlopen scheme | v8/src/edp8/update_helper.py (health probe, `_http`) | nosec | loopback URLs from the runner's own plan (`http://127.0.0.1:<port>`), never user input; `# nosec B310  # reason` on both lines |
| B108 hardcoded /tmp | edp-pool/src/edp_pool/pty/_posix.py:34 | nosec | the AF_UNIX path limit forces a short dir; the file name is a hash of the seat name |
| B104 bind to 0.0.0.0 | v8/src/edp8/service.py:348, launcher.py:166, desktop.py:179, edp-contracts settings/keys_common.py:80 | baseline (config skip) | public mode (EDP8_PUBLIC_URL) is the explicit opt-in to be reachable; the default is 127.0.0.1; the others map a bind-all host to loopback to connect |
| B608 SQL by string formatting | v8/src/edp8/store.py (11 sites), search.py:100, update_helper.py:183 | baseline (config skip) | only table/column names from the closed OBJECT_TYPES / _INDEXED maps (KeyError before any SQL) and `?` placeholder lists are interpolated; values are bound. semgrep `sql-concat` still catches `%` / `+` built SQL |
| pip-audit | v8 (uv.lock) | fixed | pyjwt 2.13.0 -> 2.15.0 (13 advisories) and urllib3 2.7.0 -> 2.8.0 (3) in uv.lock; ignore list stays empty |
| pip-audit | edp-contracts, edp-pool, edp-broker | none known | resolved fresh in CI; ignore list is empty; an entry needs an advisory id and a reason |
| semgrep local rules | all four src trees | none found (grep; semgrep itself runs only in CI) | shell-true, os-system, eval-exec, unsafe-deserialise, tls-verify-disabled, tempfile-mktemp, weak-hash-for-security, sql-concat: no hit after the fixes above |

Baseline mechanism: bandit `skips` in bandit.yaml (class-wide, reason in the file) or `# nosec Bxxx  # reason` (a test
fails a nosec without an id and a reason); semgrep `# nosemgrep: <rule-id>  # reason`; pip-audit `<id>  # reason` lines in
pip-audit-ignore.txt. Tests: `v8/tests/test_ci_security_job.py` (8).
