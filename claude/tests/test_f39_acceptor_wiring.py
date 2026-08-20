"""F39 (2026-08-20) — live pain report: the acceptor seat had no wiring
profile, so its card-mandated arm_wiring() refused and the whole acceptance
pass ran deaf (ask_above answers could never wake it).

Pins the fix AND the class: every role whose toolset grants arm_wiring must
have a wiring spec + (non-reconcile roles) a reflex prompt.
"""

import pytest

from edp_claude.server import make_context
from edp_claude.tools import build_registry
from edp_claude.tools._tools import _WIRING_REFLEX_PROMPTS, _WIRING_SPECS
from edp_claude.tools.roles import ROLE_TOOLSETS

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_every_arm_wiring_role_has_a_wiring_profile():
    # the drift gate: granting the verb without the profile is exactly the
    # F39 deaf-acceptor defect.
    for role, toolset in ROLE_TOOLSETS.items():
        if "arm_wiring" not in toolset:
            continue
        assert role in _WIRING_SPECS, (
            f"role {role!r} holds arm_wiring but _WIRING_SPECS has no "
            "profile — its card-mandated boot wiring would refuse and the "
            "shell runs deaf (the F39 acceptor defect).")
        if role not in ("neuron", "planner"):    # reconcile roles use the
            assert role in _WIRING_REFLEX_PROMPTS, (   # canonical prompt
                f"role {role!r} has a wiring spec but no reflex cron "
                "prompt — arm_wiring would KeyError composing cron_prompt.")


async def test_acceptor_arm_wiring_returns_live_wiring(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "acceptor")
    monkeypatch.setenv("EDP_HANDLE", "acceptor-deadbeef")
    monkeypatch.setenv("EDP_ROLE_SCOPE", "enforce")
    ctx = make_context(tmp_path)
    t = {x.name: x for x in build_registry(ctx)}
    res = await t["arm_wiring"].run({})
    assert getattr(res, "ok", False), res
    d = res.data if isinstance(res.data, dict) else res.data.model_dump()
    assert d["spec"] == "rx.broker(me)"
    assert d["monitor_cmd"]
    assert "check_inbox" in d["cron_prompt"]
