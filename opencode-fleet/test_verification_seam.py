"""Focused tests for the repository-rooted harness verification seam."""
import unittest
from pathlib import Path

from verification_seam import (
    POLICY_SUITE,
    REPOSITORY_ROOT,
    REQUIRED_BEHAVIORS,
    run_harness_policy_verification,
)


class VerificationSeamTests(unittest.TestCase):
    def test_canonical_local_verification_resolves_this_repository(self):
        self.assertEqual(Path(__file__).resolve().parent, REPOSITORY_ROOT)
        self.assertEqual(REPOSITORY_ROOT / "test_opencode_policy.py", POLICY_SUITE)
        self.assertTrue(POLICY_SUITE.is_file())

    def test_canonical_local_verification_executes_policy_suite_and_reports_behaviors(self):
        result = run_harness_policy_verification()

        self.assertEqual(0, result.returncode)
        self.assertEqual(REPOSITORY_ROOT, result.repository_root)
        self.assertEqual(POLICY_SUITE, result.suite)
        self.assertEqual(
            tuple(f"PASS: {behavior}" for behavior in REQUIRED_BEHAVIORS),
            result.report,
        )
        self.assertEqual(4, len(result.report))


if __name__ == "__main__":
    unittest.main()
