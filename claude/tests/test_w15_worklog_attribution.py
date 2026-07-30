"""W15 (DESIGN-v6, a4) — actor attribution on recipe + plan worklogs.

The a2 shared helper store/attribution.actor() resolves {role, handle} IN
CODE from the environment (principle-6, never LLM-supplied). a4 reuses that
ONE helper (no second implementation) so the store-authored `recipe_saved`
(events.jsonl) and `plan_saved` (worklog.jsonl) records each carry
by:{role,handle} — attribution identical across every store.

  * A recipe worklog write (RecipeStore.save → recipe_saved) carries
    by:{role,handle} resolved from the environment.
  * A plan worklog write (PlanStore.save → plan_saved) carries
    by:{role,handle}, ALONGSIDE the pre-existing agent_role field.
  * CRITICAL o6/d7: the `by` field is ADDITIVE to NEW records only — the
    legacy fixture 0e7ca8 loads BYTE-IDENTICAL after a no-op load (the store
    change touches save(), never load()/serialization), so no existing
    recipe.json / events shape is altered.
"""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from edp_claude.schemas import Plan, Recipe
from edp_claude.schemas.instruction import PlanState, RecipeState
from edp_claude.store.attribution import actor
from edp_claude.store.plan_store import PlanStore
from edp_claude.store.recipe_store import RecipeStore


def _now():
    return datetime.now(UTC)


def _make_recipe(rid, state=RecipeState.EXECUTING):
    return Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="user asked for X",
        user_goal_distilled="g", domain="software_engineering",
        state=state,
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "short",
                "status": "pending", "depends_on": [], "execution": "inline"}],
        context={"decisions": []},
        created_at=_now(), updated_at=_now(),
    ))


def _make_plan(pid, state=PlanState.DISPATCHING):
    return Plan.model_validate(dict(
        plan_id=pid, recipe_id="r-w15", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state=state,
        actions=[{"action_id": "a1", "description": "build",
                  "status": "pending", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "artifact", "expected": "e",
                                 "actual": None}}],
        context={},
    ))


def _records(path: Path) -> list[dict]:
    return [json.loads(x) for x in
            path.read_text(encoding="utf-8").splitlines() if x.strip()]


# ── recipe worklog (events.jsonl) carries by:{role,handle} ──────────────────

def test_recipe_saved_worklog_carries_by_role_handle(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "plan-r:a4")
    store = RecipeStore(tmp_path / ".recipes")
    store.save(_make_recipe("r-attr"))

    recs = _records(tmp_path / ".recipes" / "r-attr" / "events.jsonl")
    saved = [r for r in recs if r.get("kind") == "recipe_saved"]
    assert saved, "no recipe_saved worklog record written"
    assert saved[-1]["by"] == {"role": "worker", "handle": "plan-r:a4"}


# ── plan worklog (worklog.jsonl) carries by:{role,handle} ───────────────────

def test_plan_saved_worklog_carries_by_role_handle(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "plan-p:s7")
    store = PlanStore(tmp_path / ".plans")
    store.save(_make_plan("p-attr"))

    recs = _records(tmp_path / ".plans" / "p-attr" / "worklog.jsonl")
    saved = [r for r in recs if r.get("kind") == "plan_saved"]
    assert saved, "no plan_saved worklog record written"
    assert saved[-1]["by"] == {"role": "planner", "handle": "plan-p:s7"}
    # the additive `by` sits ALONGSIDE the pre-existing agent_role field.
    assert saved[-1]["agent_role"] == "planner"


# ── attribution reuses the ONE a2 helper, resolved from env (principle-6) ────

def test_by_uses_shared_actor_helper_defaulting_unknown(tmp_path, monkeypatch):
    # env absent (e.g. a neuron shell with no EDP_HANDLE) → concrete `by`,
    # matching the shared helper's contract — not a re-implementation.
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    assert actor() == {"role": "unknown", "handle": "unknown"}

    store = RecipeStore(tmp_path / ".recipes")
    store.save(_make_recipe("r-unknown"))
    recs = _records(tmp_path / ".recipes" / "r-unknown" / "events.jsonl")
    saved = [r for r in recs if r.get("kind") == "recipe_saved"]
    assert saved[-1]["by"] == {"role": "unknown", "handle": "unknown"}


# ── o6: legacy fixture 0e7ca8 byte-identical after a no-op load ──────────────

LEGACY_RID = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"
RECIPES = Path(__file__).resolve().parents[1] / ".recipes"


def test_o6_legacy_0e7ca8_byte_identical_after_noop_load(monkeypatch, tmp_path):
    """The by:{role,handle} attribution is ADDITIVE to NEW recipe_saved
    records ONLY — it lives in save(), never in load()/serialization — so the
    pre-`by` legacy fixture re-serializes byte-identically on a no-op load."""
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
    # a9: dehydrate into tmp_path, never the live fixture dir. For an
    # already-reffed field dehydrate ALWAYS re-writes the sidecar
    # (tiering.py:97), so pointing it at `rdir` rewrites 370 real files
    # per run and races test_w1_context_diet's copytree. The payload is
    # root-independent, so this changes nothing the test ASSERTS.
    payload = dehydrate_recipe_payload(model.model_dump(mode="json"), tmp_path)
    reserialized = json.dumps(payload, indent=2)
    assert reserialized == original, (
        "legacy fixture round-trip is NOT byte-identical — the `by` "
        "attribution field must be additive to NEW worklog records only")
