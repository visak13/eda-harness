import pytest

from edp_claude.server import make_context
from edp_claude.tools import build_registry


@pytest.fixture(autouse=True)
def _clear_leaked_shell_env(monkeypatch):
    """d7 (DESIGN-v6) — neutralise the worker-shell env that leaks into pytest.

    When the suite is launched from a spawned shell (e.g. a `/worker` shell),
    EDP_ROLE / EDP_HANDLE / EDP_TIER_WRITE are set in the ambient environment and
    are inherited by pytest. Lineage / role-scoping tests then resolve those
    ambient values instead of their own pinned ones and fail spuriously (the
    documented worker-shell-env-leak: ~15 lineage/role tests). d7 requires every
    such test to run under a cleared/pinned env; doing it once here makes the
    WHOLE suite deterministic regardless of the launching shell. Tests that need
    a role/handle set them explicitly via their own monkeypatch, so clearing the
    ambient default never removes a value a test depends on (proven: the suite is
    green with these unset)."""
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_TIER_WRITE",
                # v7 WS4: the seat registry resolves from EDP_AGENT_HOME
                # only — an ambient value (or config override) inherited
                # from a spawned shell would leak the LIVE models.json into
                # hermetic tiering tests. Same d7 discipline: tests that
                # need a registry pin their own env.
                "EDP_AGENT_HOME", "EDP_MODELS_CONFIG",
                # 2026-08-13: build_env stamps this into EVERY spawned
                # shell (and eda.bat into the neuron's), so a suite run
                # from inside the fleet inherits it and the staged serves-
                # lineage gate flips ON under tests written for the
                # gate-off default (9 spurious reds). Gate tests pin it.
                "EDP_V7_WRITE_GATES",
                # 2026-08-13: same leak via the launcher's telemetry flag —
                # budget_status's honesty note flips on it and the test
                # asserting the "unmeasured" wording false-fails.
                "CLAUDE_CODE_ENABLE_TELEMETRY"):
        monkeypatch.delenv(var, raising=False)
    # F21/F22 (2026-08-17): the new close-time acceptance gate and the
    # first-dispatch challenge gate default ON in production but OFF for the
    # legacy suite — hundreds of pre-existing tests exercise close/dispatch
    # paths without the new artifacts. The gates' OWN tests re-enable them
    # explicitly (tests/test_f21_f22_gates.py).
    monkeypatch.setenv("EDP_ACCEPT_GATE", "0")
    monkeypatch.setenv("EDP_CHALLENGE_GATE_MIN_ACTIONS", "0")
    # F34 R2 #12 (2026-08-18): saves fsync by default in production so an
    # acknowledged write survives power loss. The suite does thousands of
    # tiny saves where per-save fsync is pure latency — opt out here.
    monkeypatch.setenv("EDP_FSYNC", "0")


@pytest.fixture
def env(tmp_path):
    ctx = make_context(tmp_path)
    tools = {t.name: t for t in build_registry(ctx)}

    async def call(_tool_name, **inp):
        # underscore-prefix avoids collision with tool input fields
        # named `name` (e.g. get_guide).
        return await tools[_tool_name].run(inp)

    return type("Env", (), {"ctx": ctx, "tools": tools, "call": staticmethod(call)})
