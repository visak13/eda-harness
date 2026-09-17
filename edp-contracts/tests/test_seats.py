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


def test_effort_above_medium_refused():
    raw = _raw()
    raw["seats"]["judgment"]["effort"] = "high"
    with pytest.raises(SeatsError, match="MEDIUM cap"):
        parse(raw)


def test_pi_seat_may_ask_high_effort_claude_may_not():
    """owner 2026-09-17 (m-2d7ef9243d): "include effort high as well" — for a harness seat (Pi/Astra)
    high is a thinking level, not the Claude cap; a Claude seat asking high is still refused."""
    raw = _raw()
    raw["seats"]["astra"] = {"model": "openai-codex/gpt-6-astra", "effort": "high",
                             "harness": "pi", "thinking": "high", "context_window": 272000,
                             "auto_compact": 200000}
    seats, _ = parse(raw)
    assert seats["astra"].effort == "high" and seats["astra"].harness == "pi"
    raw["seats"]["judgment"]["effort"] = "high"
    with pytest.raises(SeatsError, match="MEDIUM cap"):
        parse(raw)


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
    raw["roles"]["reviewer"] = "ghost"
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
