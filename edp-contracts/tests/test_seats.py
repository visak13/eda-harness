"""Seat registry (v7 §2.4b) — validation rules are the contract."""

import json

import pytest

from edp_contracts.seats import Seat, SeatsError, load, parse, seat_for_role


def _raw(**over):
    base = {
        "seats": {
            "judgment": {"model": "claude-fable-5", "effort": "medium"},
            "workhorse": {"model": "claude-sonnet-5", "auto_compact": 200000,
                          "max_output": 16000},
        },
        "roles": {"neuron": "judgment", "worker": "workhorse"},
    }
    base.update(over)
    return base


def test_parse_roundtrip_and_defaults():
    seats, roles = parse(_raw())
    assert seats["judgment"].effort == "medium"
    assert seats["judgment"].max_output is None
    assert seats["workhorse"].auto_compact == 200000
    assert roles["neuron"] == "judgment"


def test_effort_above_high_refused_high_allowed_on_claude():
    """owner §6 words (epic-0cec8d1c31): the cap is high for every seat, Claude included; xhigh/max are refused."""
    raw = _raw()
    raw["seats"]["judgment"]["effort"] = "high"
    seats, _ = parse(raw)
    assert seats["judgment"].effort == "high"
    for above in ("xhigh", "max"):
        raw["seats"]["judgment"]["effort"] = above
        with pytest.raises(SeatsError, match="HIGH cap"):
            parse(raw)


def test_pi_seat_may_ask_high_effort():
    raw = _raw()
    raw["seats"]["astra"] = {"model": "openai-codex/gpt-6-astra", "effort": "high",
                             "harness": "pi", "thinking": "high", "context_window": 272000,
                             "auto_compact": 200000}
    seats, _ = parse(raw)
    assert seats["astra"].effort == "high" and seats["astra"].harness == "pi"


def test_clamp_effort_and_cap_of():
    from edp_contracts.seats import clamp_effort, effort_cap_of
    assert clamp_effort("high", "medium") == ("medium", "effort high capped to medium (catalog entry cap)")
    assert clamp_effort("HIGH", "high") == ("high", None)
    assert clamp_effort("max", "high") == (None, None)
    assert clamp_effort(None, "high") == (None, None)
    assert effort_cap_of({"harness": "claude", "effort_cap": "high"}) == "high"
    assert effort_cap_of({"harness": "codex"}) == "high"
    assert effort_cap_of({"harness": "claude"}) == "medium"
    assert effort_cap_of({"harness": "claude", "effort_cap": "max"}) == "medium"
    assert effort_cap_of(None) == "medium"


def test_launch_effort_clamps_to_the_models_catalog_cap(tmp_path, monkeypatch):
    from edp_contracts.seats import launch_effort
    cat = {"models": {"hi": {"harness": "claude", "effort_cap": "high"},
                      "lo": {"harness": "claude", "effort_cap": "medium"}}}
    (tmp_path / "models.json").write_text(json.dumps(cat), encoding="utf-8")
    monkeypatch.setenv("EDP_MODELS_CONFIG", str(tmp_path / "models.json"))
    assert launch_effort(tmp_path, "hi", "high") == ("high", None)
    assert launch_effort(tmp_path, "lo", "high")[0] == "medium"
    assert launch_effort(tmp_path, "lo", "high")[1] and "capped" in launch_effort(tmp_path, "lo", "high")[1]
    assert launch_effort(tmp_path, "hi", None) == ("medium", None)       # nothing named: the default
    assert launch_effort(tmp_path, "ghost", "high")[0] == "medium"      # no catalog row: capped at medium
    assert launch_effort(tmp_path, "hi", "xhigh") == ("medium", None)   # outside the levels: the default


def test_alias_model_ids_refused():
    raw = _raw()
    raw["seats"]["judgment"]["model"] = "claude-fable-latest"
    with pytest.raises(SeatsError, match="alias"):
        parse(raw)


def test_auto_compact_must_sit_below_window():
    raw = _raw()
    raw["seats"]["workhorse"]["auto_compact"] = 2_000_000
    with pytest.raises(SeatsError, match="BELOW the"):
        parse(raw)


def test_role_to_unknown_seat_refused():
    raw = _raw()
    raw["roles"]["auditor"] = "ghost"
    with pytest.raises(SeatsError, match="unknown seat"):
        parse(raw)


def test_tiny_output_cap_refused():
    raw = _raw()
    raw["seats"]["workhorse"]["max_output"] = 100
    with pytest.raises(SeatsError, match="below 1000"):
        parse(raw)


def test_load_absent_is_none_invalid_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_MODELS_CONFIG", raising=False)
    assert load(tmp_path) is None                    # staged rollout
    (tmp_path / "models.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SeatsError, match="unreadable"):
        load(tmp_path)
    (tmp_path / "models.json").write_text(json.dumps(_raw()),
                                          encoding="utf-8")
    seat = seat_for_role(tmp_path, "worker")
    assert isinstance(seat, Seat) and seat.model == "claude-sonnet-5"
    assert seat_for_role(tmp_path, "unmapped-role") is None


def test_harness_columns_are_options_next_to_the_claude_column(tmp_path):
    """epic-6a8a6020fd (owner m-96cbd61919/m-e6ef892737): roles_openai maps roles to a Pi-run
    seat WITHOUT touching the Claude `roles` column; unknown seats in a harness column are refused;
    an unmapped role in a harness column is None (caller falls back), never the Claude seat."""
    import json
    from edp_contracts import seats as s
    raw = {"seats": {"advisor": {"model": "claude-fable-5-1"},
                     "astra": {"model": "openai-codex/gpt-6-astra", "harness": "pi", "thinking": "medium"}},
           "roles": {"architect": "advisor", "qa": "advisor"},
           "roles_openai": {"architect": "astra"}}
    (tmp_path / "models.json").write_text(json.dumps(raw), encoding="utf-8")
    assert s.seat_for_role(tmp_path, "architect").model == "claude-fable-5-1"
    a = s.seat_for_role(tmp_path, "architect", column="roles_openai")
    assert a.model == "openai-codex/gpt-6-astra" and a.harness == "pi" and a.thinking == "medium"
    assert s.seat_for_role(tmp_path, "qa", column="roles_openai") is None
    assert s.seat_for_role(tmp_path, "architect").harness is None
    raw["roles_openai"]["qa"] = "nope"
    (tmp_path / "models.json").write_text(json.dumps(raw), encoding="utf-8")
    import pytest
    with pytest.raises(s.SeatsError):
        s.load(tmp_path)


def test_a_1m_launch_id_keeps_its_rows_effort_cap(tmp_path, monkeypatch):
    """qa m-1b272db80b: the launcher appends `[1m]` to a 1M row's id; the cap lookup strips it, so
    `claude-opus-5-5[1m]` at high stays high instead of falling to the unknown-model medium."""
    from edp_contracts.seats import launch_effort, model_entry
    cat = {"models": {"claude-opus-5-5": {"harness": "claude", "effort_cap": "high", "context_window": 1000000},
                      "only-1m[1m]": {"harness": "claude", "effort_cap": "high"}}}
    (tmp_path / "models.json").write_text(json.dumps(cat), encoding="utf-8")
    monkeypatch.setenv("EDP_MODELS_CONFIG", str(tmp_path / "models.json"))
    assert launch_effort(tmp_path, "claude-opus-5-5[1m]", "high") == ("high", None)
    assert model_entry(tmp_path, "claude-opus-5-5[1m]")["effort_cap"] == "high"
    assert model_entry(tmp_path, "only-1m[1m]")["effort_cap"] == "high"  # a row keyed with the suffix still matches
    assert launch_effort(tmp_path, "ghost[1m]", "high")[0] == "medium"   # no row either way: capped
