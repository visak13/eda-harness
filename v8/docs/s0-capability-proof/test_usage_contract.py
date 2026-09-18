import unittest
from codex_probe import safe_snapshot
from usage_contract import core_windows


class CoreWindowTests(unittest.TestCase):
    def test_absent_present_absent_on_ordinary_replacement(self):
        weekly = {"usedPercent": 92, "windowDurationMins": 10080, "resetsAt": 1789807430}
        five = {"usedPercent": 0, "windowDurationMins": 300, "resetsAt": 1789735430}
        # Primary is deliberately weekly in the first/last update and 5h in middle.
        events = [{"primary": weekly}, {"primary": five, "secondary": weekly}, {"primary": weekly}]
        normalized = [core_windows(safe_snapshot({"rateLimits": event})) for event in events]
        self.assertEqual([n[0]["status"] for n in normalized],
                         ["unavailable", "sample_received", "unavailable"])
        self.assertEqual(normalized[1][0]["used_percent"], 0)
        self.assertIsNone(normalized[2][0]["used_percent"])
        self.assertEqual([n[1]["used_percent"] for n in normalized], [92, 92, 92])

    def test_codex_pool_preferred_no_other_pool_substitution(self):
        source = {"rateLimits": {"primary": {"usedPercent": 99, "windowDurationMins": 300,
                                             "resetsAt": 1789735430}},
                  "rateLimitsByLimitId": {"codex": {}, "some-other": {}}}
        self.assertEqual(core_windows(safe_snapshot(source))[0]["status"], "unavailable")

    def test_invalid_and_duplicate_buckets_unavailable(self):
        for used in (True, -1, 101, float('nan'), '0'):
            normalized = core_windows({"windows": [{"usedPercent": used,
                                      "windowDurationMins": 300, "resetsAt": 1789735430}]})
            self.assertIsNone(normalized[0]["used_percent"])
        window = {"usedPercent": 10, "windowDurationMins": 300, "resetsAt": 1789735430}
        self.assertEqual(core_windows({"windows": [window, window]})[0]["status"], "unavailable")


if __name__ == '__main__':
    unittest.main()
