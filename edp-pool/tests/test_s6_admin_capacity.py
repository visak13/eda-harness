"""S6 (design §4.14(d), c-002a8ba1b5): Admin → Services → Capacity writes through `/v1/limits`. Beyond the
S13 class caps, the operator can override the live-shells ceiling and any role's own cap (over the
workflow role's declared max_concurrent); every value clamps to >= 1; overrides persist in the registry,
so a pool restart keeps them; GET ?usage=1 reports live usage per class and role."""

import pytest

from edp_pool.service import PoolService
from edp_pool.spawner import FakeSpawner


@pytest.fixture
def state(tmp_path):
    return tmp_path / "pool-state.json"


def test_live_ceiling_and_role_caps_override_and_clamp(state):
    svc = PoolService(FakeSpawner(), state_path=state)
    out = svc.set_limits({"max_live_shells": 0, "max_total_shells": 7,
                          "role_caps": {"engineer": 0, "designer": 3}})
    assert out["max_live_shells"] == 1          # clamped: 0 is not a pause
    assert out["max_total_shells"] == 7
    assert out["role_caps"] == {"engineer": 1, "designer": 3}
    # the override wins over the workflow role's declared max_concurrent
    assert isinstance(svc.spawn("engineer", "engineer.s-1", None, capacity_class="builder",
                                max_concurrent=5), str)
    res = svc.spawn("engineer", "engineer.s-2", None, capacity_class="builder", max_concurrent=5)
    assert not isinstance(res, str)
    assert "max concurrent engineer = 1" in res.message and "Admin" in res.message
    # null clears back to the declared cap
    svc.set_limits({"role_caps": {"engineer": None}, "max_live_shells": None})
    assert "role_caps" not in svc.limit_overrides or "engineer" not in svc.limit_overrides["role_caps"]
    assert svc.max_live_shells() == svc.max_total_shells() * 2
    assert isinstance(svc.spawn("engineer", "engineer.s-2", None, capacity_class="builder",
                                max_concurrent=5), str)


def test_overrides_survive_a_pool_restart(state):
    svc = PoolService(FakeSpawner(), state_path=state)
    svc.set_limits({"max_workers": 2, "max_live_shells": 9, "role_caps": {"sme": 1}})
    again = PoolService(FakeSpawner(), state_path=state)
    lim = again.effective_limits()
    assert lim["max_workers"] == 2 and lim["max_live_shells"] == 9 and lim["role_caps"] == {"sme": 1}


def test_usage_counts_per_class_and_role(state):
    svc = PoolService(FakeSpawner(), state_path=state)
    svc.spawn("engineer", "engineer.s-1", None, capacity_class="builder")
    svc.spawn("sme", "sme.s-1", None, capacity_class="builder")
    svc.spawn("architect", "architect.epic-1", None, capacity_class="planner")
    svc.spawn("qa", "qa.epic-1", None, capacity_class="checker")
    u = svc.usage()
    assert u["total"] == 4 and u["live"] == 4
    assert u["classes"] == {"builder": 2, "planner": 1, "checker": 1}
    assert u["roles"] == {"engineer": 1, "sme": 1, "architect": 1, "qa": 1}
