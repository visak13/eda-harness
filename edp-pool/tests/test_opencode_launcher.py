"""OpencodeSpawner unit surface (PORT-OPENCODE): tier translation + argv."""

import edp_pool.opencode_launcher as ol


def test_map_model_translates_the_existing_tiers(monkeypatch):
    # MODEL_TIERS is unchanged upstream; this only translates its output.
    assert ol.map_model(None) is None                      # host default
    assert ol.map_model("claude-sonnet-4-6") == "openai/gpt-5.6-terra"
    assert ol.map_model("claude-haiku-4-5") == "openai/gpt-5.6-luna"
    assert ol.map_model("claude-opus-4-6") is None, (
        "the Opus/default tier defers to the ROLE WRAPPER's pinned "
        "model (planner=terra, judgment=sol) - mapping it to sol "
        "overrode the planner ruling")
    assert ol.map_model("openai/gpt-5.6-terra") == "openai/gpt-5.6-terra"
    assert ol.map_model("some-unknown-model") is None       # never guess
    monkeypatch.setenv("EDP_OPENCODE_MODEL_SONNET", "openai/gpt-5.6-luna")
    assert ol.map_model("claude-sonnet-4-6") == "openai/gpt-5.6-luna"


def test_argv_carries_the_mapped_model(monkeypatch):
    monkeypatch.setattr(ol, "resolve_opencode_bin", lambda: "opencode.exe")
    argv = ol.build_argv_opencode(
        "worker", "go", title="t", model="claude-sonnet-4-6")
    i = argv.index("--model")
    assert argv[i + 1] == "openai/gpt-5.6-terra"
    argv = ol.build_argv_opencode("worker", "go", title="t", model=None)
    assert "--model" not in argv, "host default = wrapper's pinned model"


def test_panel_limit_overrides_win_and_persist(tmp_path, monkeypatch):
    from edp_pool.service import PoolService
    from edp_pool.spawner import FakeSpawner
    state = tmp_path / "registry.json"
    svc = PoolService(FakeSpawner(), state_path=str(state))
    monkeypatch.setenv("EDP_MAX_WORKERS", "3")
    monkeypatch.setenv("EDP_MAX_PLANNERS", "1")
    assert svc.max_workers() == 3 and svc.max_planners() == 1  # env layer
    out = svc.set_limits({"max_workers": 2, "max_planners": 1})
    assert out["max_workers"] == 2 and out["overrides"]["max_workers"] == 2
    svc2 = PoolService(FakeSpawner(), state_path=str(state))  # restart
    assert svc2.max_workers() == 2, "panel override must survive a restart"
    svc2.set_limits({"max_workers": None})                    # reset
    assert svc2.max_workers() == 3, "cleared override falls back to env"
    assert svc2.set_limits({"max_planners": 0})["max_planners"] == 1, (
        "caps clamp to >=1 — a 0 cap would deadlock dispatch")
