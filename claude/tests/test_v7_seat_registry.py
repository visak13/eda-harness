"""v7 WS4 §2.4b — the seat registry overrides spawn model resolution, and the
live claude/models.json is always valid."""

import json

import pytest

from edp_claude.tools.roles import spawn_model_for


def test_live_models_json_is_valid_and_maps_every_pool_role():
    from edp_contracts.seats import load
    from pathlib import Path
    home = Path(__file__).resolve().parents[1]
    loaded = load(home)
    assert loaded is not None, "claude/models.json must exist and parse"
    seats, roles = loaded
    # ("consult" left this list 2026-08-12 — the consult shell role is retired
    # and its seat mapping was deleted with it.)
    for role in ("neuron", "planner", "worker", "reviewer", "specialist",
                 "curiosity"):
        assert role in roles, f"role {role} unmapped in models.json"
    assert "consult" not in roles, "the retired consult role is mapped again"
    # the fleet-wide rulings hold in the LIVE file
    assert all(s.effort in ("low", "medium") for s in seats.values())


def test_registry_is_the_only_resolver(tmp_path, monkeypatch):
    """(Was `test_registry_wins_over_tier_table` — the W10b tier table was
    retired 2026-08-12; the registry no longer 'wins', it is all there is.)"""
    (tmp_path / "models.json").write_text(json.dumps({
        "seats": {"w": {"model": "claude-sonnet-5"}},
        "roles": {"worker": "w"},
    }), encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("EDP_MODELS_CONFIG", raising=False)
    assert spawn_model_for("worker") == "claude-sonnet-5"
    # unmapped role → no --model flag (pool config default rules)
    assert spawn_model_for("planner") is None


def test_registry_seat_model_is_passed_verbatim(tmp_path, monkeypatch):
    """(Was `test_registry_host_default_still_passes_no_flag`: with the tier
    table retired there is no host-default sentinel to equal — a mapped seat's
    pinned model is emitted explicitly. Explicit beats implicit at the spawn
    seam; the live models.json pins every seat anyway.)"""
    (tmp_path / "models.json").write_text(json.dumps({
        "seats": {"j": {"model": "claude-opus-4-6"}},
        "roles": {"neuron": "j"},
    }), encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("EDP_MODELS_CONFIG", raising=False)
    assert spawn_model_for("neuron") == "claude-opus-4-6"


def test_absent_registry_resolves_no_model(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("EDP_MODELS_CONFIG", raising=False)
    assert spawn_model_for("worker") is None      # no flag; pool default rules
