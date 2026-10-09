# S10 CI security job: the one proof run (criterion c-ca6e7a5637, second clause)

- Run: https://github.com/visak13/eda-harness/actions/runs/36953526575 (push, branch `e0cec/S10-proof`, head a47db1a), conclusion **success**.
- Duration: 33 s for the whole job (checkout 5 s, setup-uv with cache 1 s, bandit 5 s, semgrep 5 s, pip-audit 6 s).
- Job steps, all success: bandit (medium and above), semgrep (local rules), pip-audit (v8 from its lock, the other packages resolved).
- What the branch held: origin/main (7c3e9e9) + the security commit + the lock bump (pyjwt 2.13.0 -> 2.15.0, urllib3 2.7.0 -> 2.8.0; 16 advisories
  that the local pip-audit run had found) + the `# nosec B310  # reason` on the runner's loopback urlopen. `ci.yml` was cut to the `security` job
  on a push to that branch only and every other workflow file was removed there, so nothing else ran (no matrix, no MSI build, nothing on tag,
  release, PR or schedule). The branch is deleted.
- Not proven here, for QA after the merge: the full `ci.yml` (pii-gate, test matrix, install-smoke, security together) and the `release.yml`
  dry-run dispatch (origin/main's release.yml has `workflow_dispatch` with only a `tag` input, so GitHub cannot dispatch the new inputs until
  it is merged; `gh` is not installed on this host). Local proofs: `v8/tests/test_release_workflow.py`, `test_admin_release.py`.
- Baselines and reasons: `security-scan.md`; local bandit output: `bandit-local.txt`.
