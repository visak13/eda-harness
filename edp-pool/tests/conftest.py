"""Suite-wide hermeticity pins.

`build_argv` / `build_env` read the pool-side `spawn_defaults.json` (W12). On a
live host that file EXISTS, so without this fixture the suite's argv/env
assertions would silently depend on whatever the operator last saved in the
panel — green here, red on his machine, or worse: green on both while asserting
different things. d7: a test must not read operator config.

Point it at a path inside the per-test tmp dir that is never created, so
`load_spawn_defaults()` takes its "absent → {}" branch. Tests that WANT
defaults pass them explicitly or write the file themselves.

WHY THIS OWNS A PRIVATE `MonkeyPatch` INSTEAD OF REQUESTING THE `monkeypatch`
FIXTURE. An autouse fixture is set up before the test's own fixtures, so
requesting `monkeypatch` here would construct it FIRST — and pytest tears
fixtures down in reverse, which would then undo every `monkeypatch` in the file
AFTER the other fixtures have already finalized. That inverted
`test_a_transient_probe_failure_is_unknown_not_death`, whose `child` fixture
tore down while its `psutil.Process.create_time` patch was still raising
AccessDenied. A private MonkeyPatch touches only this env var and cannot
reorder anyone else's teardown.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_operator_spawn_defaults(tmp_path):
    mp = pytest.MonkeyPatch()
    mp.setenv(
        "EDP_SPAWN_DEFAULTS", str(tmp_path / "absent-spawn-defaults.json"))
    yield
    mp.undo()
