"""Synthetic privacy/shape checks, NOT legitimate provider or desktop proof."""
import json
import unittest
from unittest.mock import Mock, MagicMock, patch
from codex_probe import probe, safe_snapshot


class SnapshotTests(unittest.TestCase):
    def test_weekly_primary_is_not_assumed_five_hour(self):
        result = safe_snapshot({"rateLimits": {"primary": {
            "usedPercent": 92, "windowDurationMins": 10080, "resetsAt": 1789807430}}})
        self.assertEqual(result["windows"][0]["windowDurationMins"], 10080)
        self.assertEqual(len(result["windows"]), 1)

    def test_missing_is_not_zero(self):
        self.assertEqual(safe_snapshot({})["windows"], [])
        window = safe_snapshot({"rateLimits": {"primary": {}}})["windows"][0]
        self.assertIsNone(window["usedPercent"])

    def test_numeric_zero_preserved_and_boolean_rejected(self):
        window = safe_snapshot({"rateLimits": {"primary": {
            "usedPercent": 0, "resetsAt": True}}})["windows"][0]
        self.assertEqual(window["usedPercent"], 0)
        self.assertIsNone(window["resetsAt"])

    def test_nonfinite_is_null_and_serializable(self):
        result = safe_snapshot({"rateLimits": {"primary": {
            "usedPercent": float("nan"), "resetsAt": float("inf")}}})
        self.assertIsNone(result["windows"][0]["usedPercent"])
        json.dumps(result, allow_nan=False)

    def test_broken_pipe_close_still_reaps_owned_child(self):
        process = Mock()
        process.stdin.close.side_effect = BrokenPipeError()
        process.stdout = MagicMock()
        process.stdout.__iter__.return_value = iter([])
        with patch("codex_probe.subprocess.Popen", return_value=process):
            result = probe("synthetic-executable")
        self.assertEqual(result["status"], "error")
        process.wait.assert_called_once_with(timeout=3)
        process.stdout.close.assert_called_once()

    def test_private_fields_and_arbitrary_labels_omitted(self):
        result = safe_snapshot({"account": "PRIVATE", "rateLimits": {
            "planType": "PRIVATE", "primary": {"usedPercent": "PRIVATE"}},
            "rateLimitsByLimitId": {"PRIVATE": {"secondary": {
                "usedPercent": 5, "windowDurationMins": 300}}}})
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(result["by_limit"][0]["scope"], "other-0")


if __name__ == "__main__":
    unittest.main()
