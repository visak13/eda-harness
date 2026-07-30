"""Focused tests for the OpenCode-local behavioral and lifecycle policy."""
import unittest
from pathlib import Path
from opencode_policy import ROLE_MODELS, closure_allowed, route_finding
from startup_contract import configured_model, select_role

ROOT = Path(__file__).resolve().parent

class OpenCodePolicyTests(unittest.TestCase):
    def test_safe_nontrivial_finding_is_inline_and_reverified(self):
        route = route_finding(finding="missing validation", scope="form", safety="safe")
        self.assertTrue(route.inline_fix)
        self.assertTrue(route.verification_required)
        self.assertIsNone(route.remediation_brief)

    def test_substantial_finding_routes_terra_then_fresh_sol(self):
        route = route_finding(finding="redesign sync", scope="sync layer", safety="substantial")
        self.assertFalse(route.inline_fix)
        self.assertEqual("terra", route.remediation_brief.route)
        self.assertTrue(route.remediation_brief.requires_fresh_sol_review)

        out_of_scope = route_finding(
            finding="change sibling stack", scope="sibling", safety="safe", in_scope=False
        )
        self.assertFalse(out_of_scope.inline_fix)
        self.assertEqual("terra", out_of_scope.remediation_brief.route)

    def test_regex_alone_never_creates_an_operator_gate(self):
        route = route_finding(finding="use regex", scope="parser", safety="safe", regex_only=True)
        self.assertTrue(route.inline_fix)
        self.assertIsNone(route.remediation_brief)

        unsafe_regex = route_finding(
            finding="unsafe parser rewrite",
            scope="parser",
            safety="unsafe",
            regex_only=True,
        )
        self.assertFalse(unsafe_regex.inline_fix)
        self.assertEqual("terra", unsafe_regex.remediation_brief.route)

    def test_failed_review_blocks_closure_until_terra_and_fresh_sol_pass(self):
        self.assertFalse(closure_allowed(review_failed=True, terra_remediated=False, fresh_sol_passed=False))
        self.assertFalse(closure_allowed(review_failed=True, terra_remediated=True, fresh_sol_passed=False))
        self.assertTrue(closure_allowed(review_failed=True, terra_remediated=True, fresh_sol_passed=True))

    def test_local_startup_contract_selects_terra_sol_and_policy(self):
        for role, expected_model in ROLE_MODELS.items():
            wrapper = ROOT / ".opencode" / "agents" / f"edp-{role}.md"
            self.assertEqual(expected_model, configured_model(wrapper), role)
            self.assertEqual(expected_model, select_role(role, ROOT), role)
        self.assertIn("startup_contract.py", (ROOT / "shell_tui.cmd").read_text())

    def test_every_local_role_wrapper_loads_the_policy(self):
        wrappers = list((ROOT / ".opencode" / "agents").glob("edp-*.md"))
        self.assertEqual(set(ROLE_MODELS), {wrapper.stem.removeprefix("edp-") for wrapper in wrappers})
        for wrapper in wrappers:
            contents = wrapper.read_text()
            self.assertIn("OPENCODE-BEHAVIOR-POLICY.md", contents, wrapper.name)
            self.assertIn("local policy prevails", " ".join(contents.split()), wrapper.name)

if __name__ == "__main__":
    unittest.main()
