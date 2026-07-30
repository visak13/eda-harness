"""W11 (DESIGN-v6 §W11) — the two new optional Recipe fields.

The bar this pins:

* `suspended_at` (tz-aware UTC ISO when set) and `neuron_session_id` exist on
  `Recipe` and round-trip when set.
* o6 / RP-A emission gate: a never-suspended recipe serializes WITHOUT either
  key, so a pre-restart `extra='forbid'` reader never sees them.
* Both shapes load: a recipe.json carrying the keys, and a legacy one lacking
  them.
* The o6 REGRESSION BAR: the legacy fixture 0e7ca8 re-serializes byte-identical
  to its on-disk bytes (technique mirrored from
  `test_w5_consult.py::test_o6_legacy_fixture_byte_identical`).

Suspension is ORTHOGONAL to the FSM `state` — nothing here touches the state
enum or its transition table.

Env discipline (d7): EDP_ROLE/EDP_HANDLE/EDP_TIER_WRITE that leak from a
launching worker shell are neutralised IN-PROCESS by the autouse conftest
fixture; every assertion is done in PYTHON (the acceptance verify shell has
neither `env` nor `grep`).
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from edp_claude.schemas import Recipe


def _now():
    return datetime.now(timezone.utc)


def _recipe_payload(**over):
    """A PLANNING recipe (past COMPREHENDING, so the invariant validator is
    satisfied) carrying no consult traffic — the resting shape."""
    return dict(
        recipe_id="r-w11", user_goal_verbatim="user asked for X",
        user_goal_distilled="g", domain="software_engineering",
        state="planning",
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "pending", "depends_on": [],
                "execution": "spawn_planner"}],
        context={"decisions": [], "assumptions": [], "rejected_options": []},
        created_at=_now(), updated_at=_now(), **over,
    )


# ── (a) resting defaults: NEITHER key is emitted ─────────────────────────────
def test_w11_fields_emission_gated_at_defaults():
    r = Recipe.model_validate(_recipe_payload())
    assert r.suspended_at is None
    assert r.neuron_session_id is None

    dumped = r.model_dump(mode="json")
    assert "suspended_at" not in dumped
    assert "neuron_session_id" not in dumped


# ── (b) set: BOTH keys are emitted and round-trip ────────────────────────────
def test_w11_fields_emitted_and_round_trip_when_set():
    stamp = _now().isoformat()
    r = Recipe.model_validate(_recipe_payload(
        suspended_at=stamp, neuron_session_id="sess-abc123"))

    dumped = r.model_dump(mode="json")
    assert dumped["suspended_at"] == stamp
    assert dumped["neuron_session_id"] == "sess-abc123"

    # a full JSON round-trip preserves both under extra='forbid'
    again = Recipe.model_validate(json.loads(json.dumps(dumped)))
    assert again.suspended_at == stamp
    assert again.neuron_session_id == "sess-abc123"


# ── (c) a legacy payload lacking both keys loads under extra='forbid' ────────
def test_w11_legacy_payload_without_keys_loads():
    payload = _recipe_payload()
    assert "suspended_at" not in payload
    assert "neuron_session_id" not in payload

    r = Recipe.model_validate(payload)      # must NOT raise
    assert r.suspended_at is None
    assert r.neuron_session_id is None
    # suspension is orthogonal to the FSM state — loading did not touch it
    assert r.state.value == "planning"


# ── (d) o6 REGRESSION BAR: legacy fixture 0e7ca8 is byte-identical ───────────
LEGACY_RID = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"
RECIPES = Path(__file__).resolve().parents[1] / ".recipes"


def test_o6_legacy_fixture_byte_identical(monkeypatch, tmp_path):
    """Sidecars are READ from the real dir; the dehydrate is pointed at tmp so
    the real fixture is never mutated. `EDP_TIER_WRITE` gates ADOPTION only —
    a field that already carries a `*_ref` (as 0e7ca8's decisions do) is
    re-dehydrated on every save regardless of the flag, so aiming dehydrate at
    the real dir would rewrite its 370 sidecars and race any concurrent
    `copytree` of that fixture."""
    monkeypatch.delenv("EDP_TIER_WRITE", raising=False)   # tiering OFF
    from edp_claude.store.tiering import (
        dehydrate_recipe_payload,
        hydrate_recipe_payload,
    )

    rdir = RECIPES / LEGACY_RID
    assert (rdir / "recipe.json").exists(), (
        f"legacy fixture {LEGACY_RID} missing under {RECIPES}")
    original = (rdir / "recipe.json").read_text(encoding="utf-8")

    raw = json.loads(original)
    model = Recipe.model_validate(
        hydrate_recipe_payload(copy.deepcopy(raw), rdir))
    payload = dehydrate_recipe_payload(model.model_dump(mode="json"), tmp_path)
    reserialized = json.dumps(payload, indent=2)
    assert reserialized == original, (
        "legacy fixture round-trip is NOT byte-identical — a W11 suspend/"
        "resume field leaked into the schema")
