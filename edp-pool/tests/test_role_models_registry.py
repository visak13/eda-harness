"""S-ROLES (s-a0c67e6aa7): the v8 models.json per-role catalog (`role_models`) still passes the seat
registry validator, and the pool's routing predicates send the board's per-role picks to the right
harness — `codex/<gpt id>` to the codex seat, a bare Claude id to the Claude seat."""
from __future__ import annotations

from pathlib import Path

from edp_contracts.seats import load, seat_for_role
from edp_pool.codex_launcher import is_codex_model
from edp_pool.pi_launcher import is_pi_model

V8 = str(Path(__file__).resolve().parents[2] / "v8")


def test_v8_registry_with_role_models_validates():
    seats, roles = load(V8)
    assert "reviewer" not in roles
    assert seat_for_role(V8, "qa") is not None


def test_board_picks_route_to_the_right_harness():
    for gpt in ("codex/gpt-6-astra", "codex/gpt-6-sol"):
        assert is_codex_model(gpt, V8) and not is_pi_model(gpt, V8)
    for claude in ("claude-fable-5-1", "claude-opus-5-5"):
        assert not is_codex_model(claude, V8) and not is_pi_model(claude, V8)
