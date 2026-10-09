"""Run the edp-wake mod's tests from the repo: `uv run --no-sync python scripts/test_wake_mod.py` (plain `python` works too).

The mod's tests (`.claude/mods/edp-wake/hooks/*.test.ts`) import their kit from `claude-code/testing`, so only the Claude
Code binary can run them (`claude plugin test <dir>`). That command refuses where the user's own Claude Code settings
turn hook modules off (`disableAllHooks` in ~/.claude/settings.json: "hooks modules are turned off here"). This wrapper runs
it with a fresh, empty config dir and from a scratch working directory, so neither the user settings nor the project
settings of the checkout can switch the modules off. An organisation policy (managed settings) still can, and the
command then says so. Exit code: the test run's (0 = all passed), 2 = no `claude` on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MOD = Path(__file__).resolve().parents[1] / ".claude" / "mods" / "edp-wake"


def main() -> int:
    claude = shutil.which("claude")
    if claude is None:
        print("claude is not on PATH: install Claude Code (it runs the mod's tests: `claude plugin test`)", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="edp-wake-config-") as cfg, tempfile.TemporaryDirectory(prefix="edp-wake-cwd-") as cwd:
        env = {**os.environ, "CLAUDE_CONFIG_DIR": cfg}
        done = subprocess.run([claude, "plugin", "test", str(MOD)], cwd=cwd, env=env, text=True, capture_output=True)
    sys.stdout.write(done.stdout)
    sys.stderr.write(done.stderr)
    if "turned off here" in (done.stdout + done.stderr):
        print("an organisation policy (managed settings) turns hook modules off on this machine; the tests cannot run here",
              file=sys.stderr)
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
