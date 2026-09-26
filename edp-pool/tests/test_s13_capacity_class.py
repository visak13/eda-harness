"""S13 (design §4.14(d), c-2c02d34d7f): pool caps are keyed by the CAPACITY CLASS the board resolves from
the epic's pinned workflow role, plus an optional per-role `max_concurrent` — so a custom role is capped
with no pool code change. Standard: builder = engineer/sme (max_workers 6), planner = architect
(max_planners 4), checker = qa/adversary (total only). Architect ruling m-bdfe7eb9a6."""

import pytest

from edp_pool.service import PoolService
from edp_pool.spawner import FakeSpawner


@pytest.fixture
def svc():
    return PoolService(FakeSpawner())


def test_seventh_concurrent_builder_is_refused_naming_the_cap(svc):
    for i in range(3):
        assert isinstance(svc.spawn("engineer", f"engineer.s-{i}", None, capacity_class="builder"), str)
    for i in range(3):
        assert isinstance(svc.spawn("sme", f"sme.s-{i}", None, capacity_class="builder"), str)
    res = svc.spawn("engineer", "engineer.s-7", None, capacity_class="builder")
    assert not isinstance(res, str)
    assert res.code == "pool_capacity_exceeded"
    assert "max workers = 6" in res.message and "EDP_MAX_WORKERS" in res.message
    # a checker still spawns: it counts toward the total only
    assert isinstance(svc.spawn("qa", "qa.epic-1", None, capacity_class="checker"), str)


def test_planner_class_caps_architects(svc):
    for i in range(4):
        assert isinstance(svc.spawn("architect", f"architect.epic-{i}", None, capacity_class="planner"), str)
    res = svc.spawn("architect", "architect.epic-5", None, capacity_class="planner")
    assert not isinstance(res, str) and "EDP_MAX_PLANNERS" in res.message


def test_custom_role_class_and_own_cap_need_no_pool_code(svc):
    # `designer` is not a name the pool knows: its class and cap come from the spawn body alone
    assert isinstance(svc.spawn("designer", "designer.epic-1", None, capacity_class="planner",
                                max_concurrent=2), str)
    assert isinstance(svc.spawn("designer", "designer.epic-2", None, capacity_class="planner",
                                max_concurrent=2), str)
    res = svc.spawn("designer", "designer.epic-3", None, capacity_class="planner", max_concurrent=2)
    assert not isinstance(res, str)
    assert "max concurrent designer = 2" in res.message
    # it counted toward the planner class too: 2 designers + 2 architects fill max_planners 4
    for i in range(2):
        assert isinstance(svc.spawn("architect", f"architect.epic-{i}", None, capacity_class="planner"), str)
    assert not isinstance(svc.spawn("architect", "architect.epic-9", None, capacity_class="planner"), str)


def test_class_survives_activation_and_legacy_names_still_map(svc):
    sid = svc.spawn("engineer", "engineer.s-1", None, capacity_class="builder")
    row = svc.sessions[sid]
    assert row["capacity_class"] == "builder" and row["state"] == "active"
    assert row["spawn_settings"]["capacity_class"] == "builder"  # a resume re-applies it
    assert svc.active_workers() == 1
    svc.spawn("worker", "p:a1", None)  # legacy pool role → builder by name
    assert svc.active_workers() == 2
    # a spawn with no class (an unknown role, or an old board) is exempt, as before
    assert isinstance(svc.spawn("engineer", "engineer.s-2", None), str)
    assert svc.active_workers() == 2
