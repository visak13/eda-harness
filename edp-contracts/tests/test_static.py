"""TESTPLAN §7 — static/CI gates expressible as pytest.

ST-1 (dependency isolation) and ST-2 (import time) run here. ST-3 (ruff
clean incl. flake8-print) and ST-4 (coverage) run as commands in S3c, not
as pytest cases.
"""

import subprocess
import sys
import textwrap


def test_st_1_no_heavy_deps_on_plain_import():
    """ST-1 MUST — `import edp_contracts` must not pull fastapi/httpx.

    Run in a fresh subprocess so the test session's own fastapi import
    (used by service tests) doesn't pollute the check.
    """
    code = textwrap.dedent(
        """
        import sys
        import edp_contracts  # noqa: F401
        bad = [m for m in ('fastapi', 'httpx', 'starlette') if m in sys.modules]
        print(",".join(bad))
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "", f"heavy deps imported: {out.stdout!r}"


def test_st_2_cold_import_under_budget():
    """ST-2 MUST — cold import < 200ms (protects claude/ <2s budget).

    Best of 3 fresh interpreters: each is a cold process import, but a lone sample on a shared CI runner
    also times .pyc compilation and runner noise (macOS run 36324602815 read 200.3ms once)."""
    code = "import time;t=time.perf_counter();import edp_contracts;" \
           "print((time.perf_counter()-t)*1000)"
    samples = [float(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                    check=True).stdout.strip()) for _ in range(3)]
    ms = min(samples)
    assert ms < 200.0, f"cold import {ms:.1f}ms exceeds 200ms budget (samples {samples})"
