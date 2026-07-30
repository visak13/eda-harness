"""W2 leg 1 (DESIGN-v6 §W2) — STATELESS GROUNDING EPOCHS + ack_epoch/reground.

The bar this pins:

* `grounding_epoch(r)` is a 12-hex-char sha256 over the recipe's LOAD-BEARING
  GROUND — active load-bearing decisions (id+text), active constraints/bans
  (`derive_active_constraints`), and pending-unacked load-bearing assumption
  ids. It is RECOMPUTED from persisted state on every call — never stored
  (d13: no `last_acked_epoch`; the recipe IS the state). Two loads of the same
  recipe → the same epoch; a real ground change → a different epoch; a mere
  reorder or a non-load-bearing edit → the SAME epoch.
* The epoch is CARRIED on every `recipe_context()` push and on the
  `read_object('action')` grounding seam.
* `next_action` AND `reconcile` accept `ack_epoch: str|None` + `reground: bool`
  and honor the trigger table: match -> steady (pointer / W7 short-circuit),
  stale -> full digest + 'ground changed' banner, absent -> steady + epoch
  echoed, reground=true -> full digest + rewire block unconditionally.
* NO server-side ack store: a stale ack that triggered a re-ground does not
  persist anything — a subsequent matching ack returns steady.
* o6/d24: the legacy fixture 0e7ca8 still loads byte-identically AND
  `grounding_epoch` computes on it without touching the recipe.

Env discipline (d7/d8): this runner may itself be a spawned worker whose
EDP_ROLE/EDP_HANDLE/EDP_TIER_WRITE leak into pytest — they are neutralised
IN-PROCESS via monkeypatch (no `env` prefix, no external shell). Every
assertion is done in PYTHON — never grep (the acceptance verify shell has
neither env nor grep).
"""

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from edp_contracts import ToolOk

from edp_claude.cadence import RECONCILE_LOOP_CRON_PROMPT
from edp_claude.fsm import grounding_epoch, recipe_context
from edp_claude.schemas import Plan, Recipe

HEX12 = re.compile(r"^[0-9a-f]{12}$")


# ── env discipline (d7/d8): clear the inherited worker env so every test
# starts from a known baseline; all env control is in-process. ────────────────
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_TIER_WRITE"):
        monkeypatch.delenv(var, raising=False)


def _now():
    return datetime.now(timezone.utc)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _decision(did, text, *, load_bearing=False, constraint=None, status="active"):
    d = {"id": did, "text": text, "rationale": "r", "by": "neuron",
         "at": _now().isoformat()}
    if load_bearing:
        d["load_bearing"] = True
    if constraint is not None:
        d["constraint"] = constraint
    if status != "active":
        d["status"] = status
    return d


def _assumption(aid, text, *, load_bearing=True):
    a = {"id": aid, "text": text, "by": "neuron", "at": _now().isoformat()}
    if load_bearing:
        a["load_bearing"] = True
    return a


def _mk_recipe(env, rid="r-epoch", *, decisions=(), assumptions=(),
               rejected=(), state="executing", step_status="in_progress"):
    """An EXECUTING recipe with one spawn_planner step (idle -> WAIT), so
    next_action makes no forward move and the trigger table is easy to read."""
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="user asked for X",
        user_goal_distilled="g", domain="software_engineering", state=state,
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": step_status, "depends_on": [],
                "execution": "spawn_planner"}],
        context={"decisions": list(decisions),
                 "assumptions": list(assumptions),
                 "rejected_options": list(rejected)},
        created_at=_now(), updated_at=_now(),
    )))
    return rid


def _mk_plan(env, pid, rid, *, action_status="in_progress"):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id=rid, recipe_step_id="s1", domain="generic",
        shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "build",
                  "status": action_status, "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "tests_pass"}}],
        context={},
    )))
    return pid


CONSTRAINT = {"match": "nomic", "match_kind": "substring",
              "applies_to": ["spec_doc"], "message": "use MiniLM, never nomic"}


# ── 1. grounding_epoch shape + statelessness ────────────────────────────────
def test_epoch_is_12_hex_and_stateless(env):
    rid = _mk_recipe(env, decisions=[
        _decision("d1", "SETTLED: use MiniLM.", load_bearing=True)])
    r = env.ctx.recipes.load(rid)
    e1 = grounding_epoch(r)
    assert HEX12.match(e1), e1
    # recompute on the SAME object and on a FRESH load → identical (no store).
    assert grounding_epoch(r) == e1
    assert grounding_epoch(env.ctx.recipes.load(rid)) == e1
    # the recipe schema carries NO grounding_epoch field (it is derived, d13).
    assert "grounding_epoch" not in Recipe.model_fields
    raw = (env.ctx.recipes.root / rid / "recipe.json").read_text(
        encoding="utf-8")
    assert "grounding_epoch" not in raw


# ── 2. what moves the epoch (real ground change) vs what does not ───────────
def test_epoch_moves_on_load_bearing_decision(env):
    e0 = grounding_epoch(env.ctx.recipes.load(_mk_recipe(env, "r-a")))
    e1 = grounding_epoch(env.ctx.recipes.load(_mk_recipe(
        env, "r-b", decisions=[_decision("d1", "X", load_bearing=True)])))
    assert e0 != e1


def test_epoch_moves_when_lb_decision_text_changes(env):
    r1 = env.ctx.recipes.load(_mk_recipe(
        env, "r-t1", decisions=[_decision("d1", "OLD", load_bearing=True)]))
    r2 = env.ctx.recipes.load(_mk_recipe(
        env, "r-t2", decisions=[_decision("d1", "NEW", load_bearing=True)]))
    assert grounding_epoch(r1) != grounding_epoch(r2)


def test_epoch_moves_on_constraint_and_on_pending_assumption(env):
    base = grounding_epoch(env.ctx.recipes.load(_mk_recipe(env, "r-c0")))
    with_con = grounding_epoch(env.ctx.recipes.load(_mk_recipe(
        env, "r-c1",
        decisions=[_decision("d1", "D", load_bearing=True,
                             constraint=CONSTRAINT)])))
    with_asm = grounding_epoch(env.ctx.recipes.load(_mk_recipe(
        env, "r-c2",
        assumptions=[_assumption("a1", "load-bearing assumption")])))
    assert base != with_con
    assert base != with_asm
    assert with_con != with_asm


def test_epoch_stable_under_reorder_and_non_load_bearing(env):
    d1 = _decision("d1", "ALPHA", load_bearing=True)
    d2 = _decision("d2", "BETA", load_bearing=True)
    e_fwd = grounding_epoch(env.ctx.recipes.load(
        _mk_recipe(env, "r-o1", decisions=[d1, d2])))
    e_rev = grounding_epoch(env.ctx.recipes.load(
        _mk_recipe(env, "r-o2", decisions=[d2, d1])))
    assert e_fwd == e_rev                        # sorted by id → reorder-stable
    # a NON-load-bearing decision does not touch the ground.
    e_plus_nlb = grounding_epoch(env.ctx.recipes.load(_mk_recipe(
        env, "r-o3", decisions=[d1, d2, _decision("d3", "noise")])))
    assert e_plus_nlb == e_fwd


def test_epoch_moves_when_lb_decision_superseded(env):
    active = grounding_epoch(env.ctx.recipes.load(_mk_recipe(
        env, "r-s1", decisions=[_decision("d1", "D", load_bearing=True)])))
    gone = grounding_epoch(env.ctx.recipes.load(_mk_recipe(
        env, "r-s2", decisions=[_decision("d1", "D", load_bearing=True,
                                          status="superseded")])))
    assert active != gone                        # superseded leaves the ground


# ── 3. the epoch is CARRIED in recipe_context + read_object('action') ───────
def test_recipe_context_carries_epoch(env):
    rid = _mk_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    r = env.ctx.recipes.load(rid)
    assert recipe_context(r)["grounding_epoch"] == grounding_epoch(r)


async def test_read_object_action_carries_epoch(env):
    rid = _mk_recipe(env, "r-ro",
                     decisions=[_decision("d1", "D", load_bearing=True)])
    pid = _mk_plan(env, "r-ro-s1", rid)
    from edp_claude import objects
    view = await objects.read_object(env.ctx, "action",
                                     plan_id=pid, action_id="a1")
    assert view["grounding_epoch"] == grounding_epoch(env.ctx.recipes.load(rid))


async def test_read_object_action_omits_epoch_without_recipe(env):
    # a plan whose recipe does not exist → no epoch key (packet shape stable).
    pid = _mk_plan(env, "p-orphan", "recipe-does-not-exist")
    from edp_claude import objects
    view = await objects.read_object(env.ctx, "action",
                                     plan_id=pid, action_id="a1")
    assert "grounding_epoch" not in view


# ── 4. trigger table on next_action (recipe handle) ─────────────────────────
async def _na(env, handle, htype="recipe", **extra):
    return _ok(await env.call("next_action", handle=handle,
                              handle_type=htype, **extra))


async def test_next_action_absent_echoes_epoch_no_reground(env):
    rid = _mk_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    d = await _na(env, rid)                       # no ack_epoch → absent
    assert d["context"]["grounding_epoch"] == grounding_epoch(
        env.ctx.recipes.load(rid))
    assert "reground" not in d["context"]


async def test_next_action_match_is_steady(env):
    rid = _mk_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    epoch = grounding_epoch(env.ctx.recipes.load(rid))
    d = await _na(env, rid, ack_epoch=epoch)
    assert "reground" not in d["context"]
    assert d["context"]["grounding_epoch"] == epoch


async def test_next_action_stale_delivers_digest_and_banner(env):
    rid = _mk_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    d = await _na(env, rid, ack_epoch="deadbeefdead")   # stale
    rg = d["context"]["reground"]
    assert "GROUND CHANGED" in rg["banner"]
    assert rg["grounding_epoch"] == grounding_epoch(env.ctx.recipes.load(rid))
    # the FULL W1 digest is embedded (north_star + active_decisions parts).
    assert "north_star" in rg["digest"] and "active_decisions" in rg["digest"]
    # W2 leg 2 (a3): the rewire hand-back rides on STALE too, not only on an
    # explicit reground. DESIGN-v6 §W2 section 2 ("Monitor rewire hand-back")
    # states verbatim "The reground=true (and stale-epoch) response ALSO
    # includes a rewire block" — a stale ground often means a freshly-hydrated
    # shell that also lost its Monitor wiring. (Supersedes the earlier
    # "rewire only on explicit reground" assertion; the full block is covered
    # by tests/test_rewire.py.)
    assert rg["rewire"]["cron_prompt"] == RECONCILE_LOOP_CRON_PROMPT


async def test_next_action_reground_true_delivers_digest_and_rewire(env):
    rid = _mk_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    epoch = grounding_epoch(env.ctx.recipes.load(rid))
    # reground wins even when the ack_epoch MATCHES.
    d = await _na(env, rid, ack_epoch=epoch, reground=True)
    rg = d["context"]["reground"]
    assert "RE-GROUND REQUESTED" in rg["banner"]
    assert "north_star" in rg["digest"]
    assert rg["rewire"]["cron_prompt"] == RECONCILE_LOOP_CRON_PROMPT
    assert set(rg["rewire"]["roles"]) == {"neuron", "planner"}


# ── 5. trigger table on reconcile (recipe + plan handles) ───────────────────
async def test_reconcile_echoes_epoch_and_reground(env):
    rid = _mk_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    epoch = grounding_epoch(env.ctx.recipes.load(rid))
    steady = _ok(await env.call("reconcile", handle=rid, handle_type="recipe",
                                ack_epoch=epoch))
    assert steady["grounding_epoch"] == epoch and steady["reground"] is None
    stale = _ok(await env.call("reconcile", handle=rid, handle_type="recipe",
                               ack_epoch="0" * 12))
    assert stale["reground"] is not None
    assert "GROUND CHANGED" in stale["reground"]["banner"]


async def test_reconcile_plan_grounds_against_recipe(env):
    rid = _mk_recipe(env, "r-pl",
                     decisions=[_decision("d1", "D", load_bearing=True)])
    pid = _mk_plan(env, "r-pl-s1", rid)
    epoch = grounding_epoch(env.ctx.recipes.load(rid))
    rc = _ok(await env.call("reconcile", handle=pid, handle_type="plan",
                            ack_epoch=epoch))
    assert rc["grounding_epoch"] == epoch
    stale = _ok(await env.call("reconcile", handle=pid, handle_type="plan",
                               reground=True))
    assert stale["reground"]["rewire"]["cron_prompt"] == RECONCILE_LOOP_CRON_PROMPT


async def test_next_action_plan_handle_accepts_epoch_inputs(env):
    rid = _mk_recipe(env, "r-nap",
                     decisions=[_decision("d1", "D", load_bearing=True)])
    pid = _mk_plan(env, "r-nap-s1", rid)
    d = await _na(env, pid, "plan", ack_epoch="stale00stale")
    assert "GROUND CHANGED" in d["context"]["reground"]["banner"]


# ── 6. NO server-side ack store: a re-ground persists nothing ───────────────
async def test_no_ack_store_stale_then_match_returns_steady(env):
    rid = _mk_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    epoch = grounding_epoch(env.ctx.recipes.load(rid))
    # a stale ack triggers a re-ground …
    d_stale = await _na(env, rid, ack_epoch="ffffffffffff")
    assert "reground" in d_stale["context"]
    # … but nothing is stored, so the very next matching ack is steady again.
    d_match = await _na(env, rid, ack_epoch=epoch)
    assert "reground" not in d_match["context"]
    # and the recipe on disk still carries no epoch field.
    raw = (env.ctx.recipes.root / rid / "recipe.json").read_text(
        encoding="utf-8")
    assert "grounding_epoch" not in raw


# ── 7. o6/d24 REGRESSION BAR: legacy fixture loads byte-identically AND the
#     epoch computes on it (no schema/hydration validator added). ────────────
LEGACY_RID = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"
RECIPES = Path(__file__).resolve().parents[1] / ".recipes"


def test_o6_legacy_fixture_byte_identical_and_epoch_computes(monkeypatch, tmp_path):
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
        "legacy fixture round-trip is NOT byte-identical — an epoch field "
        "leaked into the schema")

    # the epoch computes cleanly on the legacy shape and is stable.
    e = grounding_epoch(model)
    assert HEX12.match(e), e
    assert grounding_epoch(model) == e


# ── DESIGN-v7 P5.3 — the epoch/rewire seam on WORKER-CALLED surfaces ─────────
# Workers/reviewers never run next_action/reconcile, so before v7 a compacted
# worker had NO surface that could hand back the rewire block — its Monitor
# wake plane was lost permanently. check_inbox/status_ping now accept the same
# ack_epoch echo and return the same reground block on a stale echo.

async def test_check_inbox_stale_ack_returns_reground(env):
    rid = _mk_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    d = _ok(await env.call("check_inbox", handle=rid,
                           ack_epoch="000000000000"))
    assert d["grounding_epoch"] == grounding_epoch(env.ctx.recipes.load(rid))
    assert d["reground"], "a stale echo must hand back the rewire block"


async def test_check_inbox_matching_ack_is_steady(env):
    rid = _mk_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    epoch = grounding_epoch(env.ctx.recipes.load(rid))
    d = _ok(await env.call("check_inbox", handle=rid, ack_epoch=epoch))
    assert d["grounding_epoch"] == epoch
    assert d["reground"] is None


async def test_check_inbox_without_ack_is_byte_identical(env):
    rid = _mk_recipe(env)
    d = _ok(await env.call("check_inbox", handle=rid))
    assert d["grounding_epoch"] is None and d["reground"] is None


async def test_status_ping_stale_ack_regrounds_the_caller(env, monkeypatch):
    rid = _mk_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    # the CALLER's grounding comes from its own handle, not the pinged child's
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:s1")
    d = _ok(await env.call("status_ping", handle=f"{rid}-s1:a1",
                           ack_epoch="000000000000"))
    assert d["grounding_epoch"] == grounding_epoch(env.ctx.recipes.load(rid))
    assert d["reground"]


# ── DESIGN-v7 P5.2 — the progress rollup on the neuron's tick ────────────────
async def test_recipe_next_action_carries_the_progress_rollup(env):
    rid = _mk_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=f"{rid}-s1", recipe_id=rid, recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[dict(action_id="a1", description="d", status="in_progress",
                      depends_on=[], executor_mode="subagent",
                      acceptance={"kind": "tests_pass"}),
                 dict(action_id="a2", description="d", status="done",
                      depends_on=[], executor_mode="subagent",
                      acceptance={"kind": "tests_pass"})],
    )))
    d = await _na(env, rid)
    roll = d["context"]["progress_rollup"]
    row = next(p for p in roll["plans"] if p["plan_id"] == f"{rid}-s1")
    assert row["action_counts"] == {"in_progress": 1, "done": 1}
    assert row["in_flight"] == ["a1"]
    assert row["parked"] is False
