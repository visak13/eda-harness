import io
import json
from pathlib import Path
import tempfile
import unittest
from claude_capture import capture, project, MAX_INPUT


class CaptureTests(unittest.TestCase):
    def test_only_allowed_fields_retained(self):
        payload = {"transcript_path": "PRIVATE", "session_id": "PRIVATE", "token": "PRIVATE",
                   "rate_limits": {"five_hour": {"used_percentage": 0, "resets_at": 1789735430,
                                                 "extra": "PRIVATE"},
                                   "seven_day": {"used_percentage": 42.5, "resets_at": 1789807430},
                                   "spend_limit": {"used_percentage": 90}}}
        result = project(payload)
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(set(result), {"rate_limits", "received_at"})
        self.assertEqual(set(result["rate_limits"]), {"five_hour", "seven_day"})
        self.assertEqual(result["rate_limits"]["five_hour"]["used_percentage"], 0)
        self.assertNotIn("observed_at", result)

    def test_invalid_values_never_become_usage(self):
        for value in (True, -1, 101, float('nan'), float('inf'), '42'):
            result = project({"rate_limits": {"five_hour": {"used_percentage": value,
                                                           "resets_at": "PRIVATE"}}})
            self.assertIsNone(result["rate_limits"]["five_hour"]["used_percentage"])
            self.assertIsNone(result["rate_limits"]["five_hour"]["resets_at"])
            json.dumps(result, allow_nan=False)

    def test_atomic_replacement_and_missing_windows(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            capture(io.BytesIO(b'{"rate_limits":{"five_hour":{"used_percentage":10,"resets_at":1789735430}}}'), path)
            capture(io.BytesIO(b'{}'), path)
            result = json.loads((path/'sample.json').read_text())
            self.assertIsNone(result['rate_limits']['five_hour']['used_percentage'])
            self.assertEqual([p.name for p in path.iterdir()], ['sample.json'])

    def test_oversize_or_nonobject_never_writes(self):
        with tempfile.TemporaryDirectory() as root:
            for content in (b' ' * (MAX_INPUT + 1), b'[]', b'broken'):
                with self.assertRaises(ValueError):
                    capture(io.BytesIO(content), Path(root))
            self.assertEqual(list(Path(root).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
