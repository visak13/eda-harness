"""W15 (a11) — the reground payload RELOADS the neuron's role-discipline guides.

W13's compact-reground restores recipe STATE (the digest) + WIRING (the rewire
block) but NOT the neuron's ROLE-DISCIPLINE guides, so after a /compact the
neuron reloads state while its operating discipline (the orchestrator launch
contract + its current phase guide) stays thinned out. This module pins the FIX:

  * ``next_action(reground=true)`` (and the STALE-epoch path) now attach a
    ``reload_role_guides`` block to the reground payload naming
    ``orchestrator-launch`` + ``neuron-phase-<current-phase>``.
  * The phase is PHASE-AWARE and DETERMINISTIC (principle-6, NO LLM): it is
    read straight from the digest's already-computed ``recap.phase``
    (recipe state -> neuron phase via the single ``_phase_for`` source).
  * It is O(1): the block carries guide NAMES to reload, never guide BODIES.
  * The compaction hook ``_BANNER`` reminds the shell of the reload.

Env discipline (d7/d8): every assertion is pure Python — no POSIX shell, no
grep. The hook is imported by file path; leaked worker env is neutralised
in-process. The full W1 digest + W2 rewire shape is covered in
tests/test_epochs.py + tests/test_rewire.py and is NOT duplicated here (d7).
"""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from edp_contracts import ToolOk

from edp_claude.fsm.recipe_fsm import recipe_context
from edp_claude.schemas import Recipe
from edp_claude.tools._tools import _reload_role_guides_block

REPO = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO / ".claude" / "hooks" / "reground-on-compact.py"


# ── env discipline (d7/d8): clear inherited worker env in-process ─────────────
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
    """A recipe with one idle spawn_planner step so next_action makes no
    forward move — the reground trigger table is clean to read."""
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


# ── load the hyphenated hook script by file path ──────────────────────────────
def _load_hook():
    assert HOOK_PATH.exists(), f"W13 hook missing at {HOOK_PATH}"
    spec = importlib.util.spec_from_file_location("reground_on_compact",
                                                  HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. reground=true includes the role-guide reload directive (CORE claim) ────
async def test_reground_payload_names_orchestrator_and_current_phase_guide(env):
    rid = _mk_recipe(env, state="executing")   # EXECUTING -> neuron phase 'd'
    rg = await _reground(env, rid)

    block = rg["reload_role_guides"]
    assert block["phase"] == "d"
    guides = block["guides"]
    # names the launch contract + the CURRENT phase guide (phase-aware).
    assert "orchestrator-launch" in guides
    assert "neuron-phase-d" in guides
    # the note actually DIRECTS a reload via get_guide.
    assert "get_guide" in block["note"]


# ── 2a. PHASE-AWARE (deterministic assembly, no LLM): the block reads the
#      phase straight from the digest's recap and names that phase's guide. ────
@pytest.mark.parametrize("phase", ["a", "b", "c", "d", "e"])
def test_reload_block_is_phase_aware_over_the_digest(phase):
    block = _reload_role_guides_block({"recap": {"phase": phase}})
    assert block["phase"] == phase
    assert block["guides"] == ["orchestrator-launch", f"neuron-phase-{phase}"]


def test_reload_block_degrades_gracefully_when_phase_absent():
    # a digest with no resolvable phase → still name the launch contract; no
    # bogus 'neuron-phase-None' guide is emitted.
    for digest in ({}, {"recap": {}}, {"recap": {"phase": None}}):
        block = _reload_role_guides_block(digest)
        assert block["guides"] == ["orchestrator-launch"]
        assert all("None" not in g for g in block["guides"])


# ── 2b. FAITHFUL PASSTHROUGH: the block's phase equals the digest's recap
#      phase on the REAL reground path (state -> neuron phase, one source). ────
async def test_block_phase_matches_the_live_digest_recap_phase(env):
    rid = _mk_recipe(env, state="executing")
    rg = await _reground(env, rid)
    live_phase = recipe_context(env.ctx.recipes.load(rid))["phase"]
    block = rg["reload_role_guides"]
    assert block["phase"] == live_phase
    assert f"neuron-phase-{live_phase}" in block["guides"]
    assert "orchestrator-launch" in block["guides"]


# ── 3. O(1): the block carries guide NAMES, never guide BODIES ────────────────
async def test_reload_directive_is_o1_names_not_bodies(env):
    rid = _mk_recipe(env, state="executing")
    rg = await _reground(env, rid)
    block = rg["reload_role_guides"]
    # every guide entry is a short slug (a name), not a document body.
    for g in block["guides"]:
        assert isinstance(g, str) and "\n" not in g and len(g) < 60, g
    assert len(block["guides"]) == 2      # exactly launch + one phase guide
    # the whole block stays tiny — a fixed directive, not recipe-size output.
    import json
    assert len(json.dumps(block)) < 1500


# ── 4. the banner points the shell at the reload block (reground + stale) ─────
async def test_reground_banner_directs_role_guide_reload(env):
    rid = _mk_recipe(env, state="executing")
    rg = await _reground(env, rid)
    assert "reload_role_guides" in rg["banner"]
    assert "RE-GROUND REQUESTED" in rg["banner"]

    # the STALE-epoch path carries the same block + banner cue.
    d = _ok(await env.call("next_action", handle=rid, handle_type="recipe",
                           ack_epoch="deadbeefdead"))
    stale = d["context"]["reground"]
    assert "GROUND CHANGED" in stale["banner"]
    assert "reload_role_guides" in stale["banner"]
    assert "orchestrator-launch" in stale["reload_role_guides"]["guides"]


# ── 5. the compaction hook _BANNER reminds of the role-guide reload ───────────
def test_hook_banner_mentions_role_discipline_reload():
    hook = _load_hook()
    banner = hook._BANNER
    assert "role-discipline" in banner
    assert "orchestrator-launch" in banner
    assert "neuron-phase" in banner
    # it still POINTS at the reground path (does not inline the guides).
    assert "next_action(reground=true)" in banner
    assert "reload_role_guides" in banner
