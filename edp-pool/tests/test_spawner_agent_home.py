"""0.10.0 (owner m-4d9de28491): a high pick reached the pool, which clamped it to medium.
The codex-by-model CompositeSpawner hid the claude backend's cwd, so the clamp found no agent
home, read no catalog and fell to the default cap."""
import json

from edp_pool.composite_spawner import CompositeSpawner
from edp_pool.service import PoolService


class _Claude:
    def __init__(self, cwd):
        self.cwd = cwd


class _Shadow:
    def __init__(self, legacy):
        self.legacy = legacy


class _Svc:
    _spawner_agent_home = PoolService._spawner_agent_home
    _clamp_seat_effort = PoolService._clamp_seat_effort

    def __init__(self, spawner):
        self.spawner = spawner


def _home(tmp_path, cap):
    (tmp_path / "models.json").write_text(json.dumps(
        {"models": {"claude-opus-5-5": {"harness": "claude", "effort_cap": cap}}}), encoding="utf-8")
    return str(tmp_path)


def test_home_found_through_shadow_and_composite(tmp_path):
    svc = _Svc(_Shadow(CompositeSpawner(_Claude(str(tmp_path)), object())))
    assert svc._spawner_agent_home() == str(tmp_path)


def test_high_pick_survives_the_installed_spawner_stack(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_AGENT_HOME", raising=False)
    monkeypatch.delenv("EDP_MODELS_CONFIG", raising=False)
    home = _home(tmp_path, "high")
    svc = _Svc(_Shadow(CompositeSpawner(_Claude(home), object())))
    out = svc._clamp_seat_effort("architect", "architect.x", "claude-opus-5-5", {"EDP_SEAT_EFFORT": "high"})
    assert out["EDP_SEAT_EFFORT"] == "high"


def test_cap_still_clamps(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_AGENT_HOME", raising=False)
    monkeypatch.delenv("EDP_MODELS_CONFIG", raising=False)
    home = _home(tmp_path, "medium")
    svc = _Svc(_Shadow(CompositeSpawner(_Claude(home), object())))
    out = svc._clamp_seat_effort("architect", "architect.x", "claude-opus-5-5", {"EDP_SEAT_EFFORT": "high"})
    assert out["EDP_SEAT_EFFORT"] == "medium"
