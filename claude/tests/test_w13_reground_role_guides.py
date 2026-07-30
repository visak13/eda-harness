"""W15 (a11) reground role-discipline reload — Phase 5 CARD contract.

The original block re-pulled orchestrator-launch (~2,757 words) + the current
neuron-phase guide on EVERY compaction. Context-diet Phase 5 replaced that
with the role CONTRACT CARD (<=100 lines): the reground payload names ONE
card to reload; the phase guide survives only as a named on-demand pointer
(`phase_guide`), never a reload obligation. Card selection is handle-aware —
a PLAN handle regrounds a planner (the old block told planners to reload the
NEURON's guides), anything else the neuron.

Env discipline (d7/d8): pure Python, hook imported by file path, leaked
worker env neutralised in-process.
"""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from edp_contracts import ToolOk

from edp_claude.fsm.recipe_fsm import recipe_context
from edp_claude.schemas import Recipe
from edp_claude.tools._tools import _reload_role_guides_block

REPO = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO / ".claude" / "hooks" / "reground-on-compact.py"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_TIER_WRITE"):
        monkeypatch.delenv(var, raising=False)


def _now():
    return datetime.now(timezone.utc)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _mk_recipe(env, rid="r-w15", *, state="executing"):
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", user_goal_distilled="g",
        domain="software_engineering", state=state,
        comprehension={"branches": [], "curiosity_cleared": True,
                       "expected_outcomes": [
                           {"id": "o1", "description": "d",
                            "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner", "attempt": 0}],
        context={"decisions": [
            {"id": "d1", "text": "D", "rationale": "r", "by": "neuron",
             "at": _now().isoformat(), "load_bearing": True}],
                 "assumptions": [], "rejected_options": []},
        created_at=_now(), updated_at=_now(),
    )))
    return rid


async def _reground(env, rid):
    d = _ok(await env.call("next_action", handle=rid, handle_type="recipe",
                           reground=True))
    return d["context"]["reground"]


def _load_hook():
    assert HOOK_PATH.exists(), f"W13 hook missing at {HOOK_PATH}"
    spec = importlib.util.spec_from_file_location("reground_on_compact",
                                                  HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. reground=true reloads the CARD, points at the phase guide ───────────
async def test_reground_payload_names_card_and_phase_pointer(env):
    rid = _mk_recipe(env, state="executing")   # EXECUTING -> neuron phase 'd'
    rg = await _reground(env, rid)

    block = rg["reload_role_guides"]
    assert block["phase"] == "d"
    assert block["guides"] == ["neuron-card"]
    assert block["phase_guide"] == "neuron-phase-d"
    assert "get_guide('neuron-card')" in block["note"]
    # the big guides are NOT reload obligations any more
    assert "orchestrator-launch" not in block["guides"]


# ── 2a. phase-aware, deterministic ─────────────────────────────────────────
@pytest.mark.parametrize("phase", ["a", "b", "c", "d", "e"])
def test_reload_block_is_phase_aware_over_the_digest(phase):
    block = _reload_role_guides_block({"recap": {"phase": phase}})
    assert block["phase"] == phase
    assert block["guides"] == ["neuron-card"]
    assert block["phase_guide"] == f"neuron-phase-{phase}"


def test_reload_block_degrades_gracefully_when_phase_absent():
    for digest in ({}, {"recap": {}}, {"recap": {"phase": None}}):
        block = _reload_role_guides_block(digest)
        assert block["guides"] == ["neuron-card"]
        assert block["phase_guide"] is None


# ── 2b. handle-aware card selection ────────────────────────────────────────
def test_plan_handle_selects_planner_card():
    block = _reload_role_guides_block(
        {"recap": {"phase": "d"}}, handle="recipe-x-s3",
        recipe_id="recipe-x")
    assert block["guides"] == ["planner-card"]
    # the planner has no neuron phase guide obligation
    assert block["phase_guide"] is None
    block2 = _reload_role_guides_block(
        {"recap": {"phase": "d"}}, handle="recipe-x", recipe_id="recipe-x")
    assert block2["guides"] == ["neuron-card"]


# ── 2c. faithful passthrough on the real path ──────────────────────────────
async def test_block_phase_matches_the_live_digest_recap_phase(env):
    rid = _mk_recipe(env, state="executing")
    rg = await _reground(env, rid)
    live_phase = recipe_context(env.ctx.recipes.load(rid))["phase"]
    block = rg["reload_role_guides"]
    assert block["phase"] == live_phase
    assert block["phase_guide"] == f"neuron-phase-{live_phase}"


# ── 3. O(1): names, never bodies — and SMALLER than the pre-card block ─────
async def test_reload_directive_is_o1_names_not_bodies(env):
    rid = _mk_recipe(env, state="executing")
    rg = await _reground(env, rid)
    block = rg["reload_role_guides"]
    for g in block["guides"]:
        assert isinstance(g, str) and "\n" not in g and len(g) < 60, g
    assert len(block["guides"]) == 1      # exactly the card
    import json
    assert len(json.dumps(block)) < 1200


# ── 4. banners still point the shell at the reload block ───────────────────
async def test_reground_banner_directs_role_guide_reload(env):
    rid = _mk_recipe(env, state="executing")
    rg = await _reground(env, rid)
    assert "reload_role_guides" in rg["banner"]
    assert "RE-GROUND REQUESTED" in rg["banner"]

    d = _ok(await env.call("next_action", handle=rid, handle_type="recipe",
                           ack_epoch="deadbeefdead"))
    stale = d["context"]["reground"]
    assert "GROUND CHANGED" in stale["banner"]
    assert "reload_role_guides" in stale["banner"]
    assert stale["reload_role_guides"]["guides"] == ["neuron-card"]


# ── 5. the compaction hook banner speaks card, not full guides ─────────────
def test_hook_banner_mentions_card_reload():
    hook = _load_hook()
    banner = hook._BANNER
    assert "CONTRACT CARD" in banner
    assert "next_action(reground=true)" in banner
    assert "reload_role_guides" in banner
    # the old full-guide reload obligation is gone from the banner
    assert "RE-LOAD your role-discipline guides (orchestrator-launch" \
        not in banner
