"""v7 WS4 §2.4b — the seat registry overrides spawn model resolution, and the
live claude/models.json is always valid."""

import json

import pytest

from edp_claude.tools.roles import HOST_DEFAULT_MODEL, spawn_model_for


def test_live_models_json_is_valid_and_maps_every_pool_role():
    from edp_contracts.seats import load
    from pathlib import Path
    home = Path(__file__).resolve().parents[1]
    loaded = load(home)
    assert loaded is not None, "claude/models.json must exist and parse"
    seats, roles = loaded
    for role in ("neuron", "planner", "worker", "reviewer", "specialist",
                 "consult", "curiosity"):
        assert role in roles, f"role {role} unmapped in models.json"
    # the fleet-wide rulings hold in the LIVE file
    assert all(s.effort in ("low", "medium") for s in seats.values())


def test_registry_wins_over_tier_table(tmp_path, monkeypatch):
    (tmp_path / "models.json").write_text(json.dumps({
        "seats": {"w": {"model": "claude-sonnet-5"}},
        "roles": {"worker": "w"},
    }), encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("EDP_MODELS_CONFIG", raising=False)
    assert spawn_model_for("worker") == "claude-sonnet-5"
    # unmapped role → legacy tier path (Opus default → no flag)
    assert spawn_model_for("planner") is None


def test_registry_host_default_still_passes_no_flag(tmp_path, monkeypatch):
    (tmp_path / "models.json").write_text(json.dumps({
        "seats": {"j": {"model": HOST_DEFAULT_MODEL}},
        "roles": {"neuron": "j"},
    }), encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("EDP_MODELS_CONFIG", raising=False)
    assert spawn_model_for("neuron") is None      # byte-identical spawn


def test_absent_registry_is_pure_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("EDP_MODELS_CONFIG", raising=False)
    assert spawn_model_for("worker") is None      # Opus default, no flag
