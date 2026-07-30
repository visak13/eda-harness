"""Repository-rooted verification for the local OpenCode harness policy."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent
POLICY_SUITE = REPOSITORY_ROOT / "test_opencode_policy.py"
REQUIRED_BEHAVIORS = (
    "safe in-scope Sol findings are fixed inline and reverified",
    "substantial, unsafe, or out-of-scope findings route to Terra and fresh Sol review",
    "regex syntax alone is not an operator-approval gate",
    "a failed reviewed action blocks succeeded closure until remediation and fresh Sol PASS",
)


@dataclass(frozen=True)
class VerificationResult:
    repository_root: Path
    suite: Path
    returncode: int
    report: tuple[str, ...]


def run_harness_policy_verification() -> VerificationResult:
    """Run the focused policy suite from this file's repository, not a glob."""
    if not POLICY_SUITE.is_file():
        raise FileNotFoundError(f"missing local harness-policy suite: {POLICY_SUITE}")

    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", POLICY_SUITE.name],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    report = tuple(f"PASS: {behavior}" for behavior in REQUIRED_BEHAVIORS)
    if completed.returncode:
        report += (f"FAIL: harness-policy suite exited {completed.returncode}",)
    return VerificationResult(REPOSITORY_ROOT, POLICY_SUITE, completed.returncode, report)


def main() -> int:
    result = run_harness_policy_verification()
    print(f"repository={result.repository_root}")
    print(f"suite={result.suite}")
    for line in result.report:
        print(line)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
