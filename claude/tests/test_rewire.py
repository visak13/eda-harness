"""W2 leg 2 (DESIGN-v6 §W2 section 2) — MONITOR REWIRE HAND-BACK + handle->sid
index.

The bar this pins:

* A handle->sid INDEX is written at the `.reactive` ROOT at subscribe time.
  `observe()` associates each subscription with its OWNING handle (owner/me),
  idempotently + dedup, so a compacted shell can be HANDED its wiring back
  instead of reconstructing it.
* A per-handle spec LOOKUP exists and is servable by the reactive driver
  (`serve_handle_specs` + the `--lookup-handle` CLI): it returns every LIVE
  persisted observe subscription (spec + bindings + effect) for a handle, and
  SELF-HEALS past a swept `.spec` artifact.
* The reground/stale-epoch response carries a `rewire` block with (a) the
  handle's ACTUAL persisted observe spec(s) + the exact observe(...) call to
  re-issue, (b) the CANONICAL reconcile-loop cron prompt CONSTANT (never the
  verbatim goal) + cadence, and (c) any durable RuleSupervisor rule OWNED by
  the handle noted as already active. The block rides on BOTH stale AND
  reground (DESIGN-v6 §W2 section 2).
* Deterministic assembly, no LLM (principle 6).
* o6/d24: the legacy fixture 0e7ca8 still loads byte-identically.

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
from edp_claude.fsm import grounding_epoch
from edp_claude.reactive import handle_index
from edp_claude.reactive.driver import main as driver_main
from edp_claude.reactive.driver import serve_handle_specs
from edp_claude.reactive.registry import RuleRegistry
from edp_claude.schemas import Plan, Recipe

HEX12 = re.compile(r"^[0-9a-f]{12}$")
GOAL_VERBATIM = "user asked for the SECRET-GOAL-STRING"


# ── env discipline (d7/d8): clear the inherited worker env in-process ─────────
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_TIER_WRITE"):
        monkeypatch.delenv(var, raising=False)


def _now():
    return datetime.now(timezone.utc)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _reactive_root(env) -> Path:
    """The `.reactive` root the observe layer owns — resolved EXACTLY as
    ObserveStream._run does (ctx.recipes.root.parent / .reactive)."""
    return env.ctx.recipes.root.parent / ".reactive"


def _mk_recipe(env, rid="r-rewire", *, state="executing"):
    """An EXECUTING recipe with one spawn_planner step (idle -> WAIT) so
    next_action makes no forward move and the trigger table is easy to read.
    Carries a distinctive verbatim goal so a test can prove the rewire block
    never leaks it into the cron prompt."""
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim=GOAL_VERBATIM,
        user_goal_distilled="g", domain="software_engineering", state=state,
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={"decisions": [{"id": "d1", "text": "D", "rationale": "r",
                                "by": "neuron", "at": _now().isoformat(),
                                "load_bearing": True}],
                 "assumptions": [], "rejected_options": []},
        created_at=_now(), updated_at=_now(),
    )))
    return rid


def _mk_plan(env, pid, rid):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id=rid, recipe_step_id="s1", domain="generic",
        shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "build",
                  "status": "in_progress", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "tests_pass"}}],
        context={},
    )))
    return pid


async def _observe(env, handle, *, spec="rx.broker(me, kinds=['answer'])",
                   sid=None, **extra):
    inp = dict(spec=spec, bindings={"me": handle})
    if sid is not None:
        inp["subscription_id"] = sid
    inp.update(extra)
    return _ok(await env.call("observe", **inp))


async def _na(env, handle, htype="recipe", **extra):
    return _ok(await env.call("next_action", handle=handle,
                              handle_type=htype, **extra))


# ── 1. handle->sid index written at subscribe time ──────────────────────────
async def test_observe_writes_handle_index(env):
    handle = "recipe-abc-s1:a7"
    res = await _observe(env, handle)
    sid = res["subscription_id"]
    idx_path = handle_index.index_path(_reactive_root(env))
    assert idx_path.exists(), "handle_index.json not written at subscribe time"
    data = json.loads(idx_path.read_text(encoding="utf-8"))
    assert data.get(handle) == [sid]


async def test_index_dedup_and_multi_sub(env):
    handle = "recipe-abc-s1"
    r1 = await _observe(env, handle, sid="sub-fixed", spec="rx.broker(me)")
    # re-arm the SAME subscription (idempotent) — index must NOT duplicate it.
    r2 = await _observe(env, handle, sid="sub-fixed", spec="rx.broker(me)")
    assert r2["reused"] is True and r2["subscription_id"] == r1["subscription_id"]
    # a DIFFERENT subscription accumulates under the same handle. This one
    # binds no `me`, so its owner is passed explicitly (the observe `owner`
    # param takes precedence over bindings["me"]).
    r3 = await _observe(env, handle, spec="rx.worklog(plan_id)",
                        bindings={"plan_id": "recipe-abc-s1"}, owner=handle)
    root = _reactive_root(env)
    sids = handle_index.sids_for_handle(root, handle)
    assert sids == ["sub-fixed", r3["subscription_id"]]   # order-preserving, deduped


async def test_index_isolates_distinct_handles(env):
    ra = await _observe(env, "handle-A")
    rb = await _observe(env, "handle-B")
    root = _reactive_root(env)
    assert handle_index.sids_for_handle(root, "handle-A") == [ra["subscription_id"]]
    assert handle_index.sids_for_handle(root, "handle-B") == [rb["subscription_id"]]


async def test_anonymous_observe_not_indexed(env):
    # owner resolves to "" (empty me + no owner) → nothing to hand back to.
    res = _ok(await env.call("observe", spec="rx.broker(me)",
                             bindings={"me": ""}))
    idx = handle_index.index_path(_reactive_root(env))
    data = json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else {}
    assert res["subscription_id"] not in {s for v in data.values() for s in v}


# ── 2. per-handle lookup: content + self-heal + driver serve ────────────────
async def test_specs_for_handle_returns_spec_and_bindings(env):
    handle = "recipe-lookup:a1"
    spec = "rx.broker(me, kinds=['answer','steer'])"
    await _observe(env, handle, spec=spec)
    subs = handle_index.specs_for_handle(_reactive_root(env), handle)
    assert len(subs) == 1
    assert subs[0]["spec"] == spec
    assert subs[0]["bindings"] == {"me": handle}
    assert subs[0]["effect"] is None


async def test_specs_for_handle_self_heals_swept_spec(env):
    handle = "recipe-heal"
    res = await _observe(env, handle)
    sid = res["subscription_id"]
    # simulate the observe GC sweeping the artifact while the index lingers.
    (_reactive_root(env) / f"{sid}.spec").unlink()
    subs = handle_index.specs_for_handle(_reactive_root(env), handle)
    assert subs == []                              # dead sub dropped, not resurrected
    # the index still lists it — the heal is at read time, non-destructive.
    assert handle_index.sids_for_handle(_reactive_root(env), handle) == [sid]


async def test_driver_serve_handle_specs(env):
    handle = "recipe-serve:a2"
    await _observe(env, handle)
    agent_home = env.ctx.recipes.root.parent
    subs = serve_handle_specs(handle, agent_home=agent_home)
    assert len(subs) == 1 and subs[0]["bindings"] == {"me": handle}


async def test_driver_lookup_handle_cli(env, monkeypatch, capsys):
    handle = "recipe-cli:a3"
    await _observe(env, handle)
    monkeypatch.setenv("EDP_AGENT_HOME",
                       str(env.ctx.recipes.root.parent))
    rc = driver_main(["--lookup-handle", handle])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["handle"] == handle
    assert len(out["subscriptions"]) == 1
    assert out["subscriptions"][0]["bindings"] == {"me": handle}


def test_driver_requires_spec_file_without_lookup():
    # the CLI contract: --spec-file is required UNLESS --lookup-handle is given.
    with pytest.raises(SystemExit):
        driver_main([])


# ── 3. the rewire block: observe_specs + cron constant + durable rules ──────
async def test_reground_rewire_carries_actual_observe_spec(env):
    rid = _mk_recipe(env)
    spec = "rx.broker(me, kinds=['answer','steer'])"
    await _observe(env, rid, spec=spec)             # owner == the recipe handle
    d = await _na(env, rid, reground=True)
    rewire = d["context"]["reground"]["rewire"]
    assert rewire["handle"] == rid
    specs = rewire["observe_specs"]
    assert len(specs) == 1
    got = specs[0]
    assert got["spec"] == spec
    assert got["bindings"] == {"me": rid}
    # the exact observe(...) call to re-issue is handed back verbatim.
    assert got["observe_call"].startswith("observe(spec=")
    assert spec in got["observe_call"]
    # Phase 5 prose diet: the per-entry note is HOISTED — the single
    # top-level note carries the re-issue + Monitor instruction once.
    assert "note" not in got
    rewire = d["context"]["reground"]["rewire"]
    assert "monitor" in rewire["note"].lower()
    assert "observe_call" in rewire["note"]


async def test_rewire_heartbeat_is_canonical_constant_not_goal(env):
    rid = _mk_recipe(env)
    await _observe(env, rid)
    d = await _na(env, rid, reground=True)
    rewire = d["context"]["reground"]["rewire"]
    # (b) the CANONICAL cron prompt CONSTANT — flat + nested — never the goal.
    assert rewire["cron_prompt"] == RECONCILE_LOOP_CRON_PROMPT
    assert rewire["heartbeat"]["cron_prompt"] == RECONCILE_LOOP_CRON_PROMPT
    assert set(rewire["roles"]) == {"neuron", "planner"}
    assert isinstance(rewire["heartbeat"]["heartbeat_secs"], int)
    # the verbatim goal must NEVER leak into the rewire block (it rides in
    # recipe/plan state, not the cron prompt).
    assert GOAL_VERBATIM not in json.dumps(rewire)


async def test_rewire_notes_durable_rule_for_handle(env):
    rid = _mk_recipe(env)
    await _observe(env, rid)
    # register a DURABLE rule owned by this handle + one owned by someone else.
    reg = RuleRegistry(root=_reactive_root(env) / "registry")
    reg.register_rule(name="sixth-sense", spec="rx.broker(me)",
                      effect=None, owner=rid, bindings={"me": rid})
    reg.register_rule(name="not-mine", spec="rx.broker(me)",
                      effect=None, owner="someone-else", bindings={"me": "x"})
    d = await _na(env, rid, reground=True)
    rewire = d["context"]["reground"]["rewire"]
    rules = rewire["durable_rules"]
    names = {r["name"] for r in rules}
    assert names == {"sixth-sense"}                # only THIS handle's rule
    # Phase 5 prose diet: per-rule note hoisted to the single top-level note.
    assert "note" not in rules[0]
    assert "already active" in rewire["note"].lower()


async def test_rewire_empty_when_no_subscriptions(env):
    rid = _mk_recipe(env)                            # no observe() armed
    d = await _na(env, rid, reground=True)
    rewire = d["context"]["reground"]["rewire"]
    assert rewire["observe_specs"] == [] and rewire["durable_rules"] == []
    # the heartbeat hand-back is ALWAYS present even with no subscriptions.
    assert rewire["cron_prompt"] == RECONCILE_LOOP_CRON_PROMPT


# ── 4. the block rides on STALE too, not only explicit reground ─────────────
async def test_stale_epoch_also_carries_rewire(env):
    rid = _mk_recipe(env)
    spec = "rx.broker(me, kinds=['answer'])"
    await _observe(env, rid, spec=spec)
    d = await _na(env, rid, ack_epoch="deadbeefdead")   # STALE, not reground
    rg = d["context"]["reground"]
    assert "GROUND CHANGED" in rg["banner"]
    rewire = rg["rewire"]                                # present on stale
    assert rewire["cron_prompt"] == RECONCILE_LOOP_CRON_PROMPT
    assert [s["spec"] for s in rewire["observe_specs"]] == [spec]


async def test_match_epoch_has_no_reground_block(env):
    rid = _mk_recipe(env)
    await _observe(env, rid)
    epoch = grounding_epoch(env.ctx.recipes.load(rid))
    d = await _na(env, rid, ack_epoch=epoch)            # MATCH → steady
    assert "reground" not in d["context"]               # no rewire churn on match


# ── 5. rewire on the PLAN reconcile path (handle == plan_id) ────────────────
async def test_reconcile_plan_reground_carries_plan_handle_subs(env):
    rid = _mk_recipe(env)
    pid = _mk_plan(env, "r-rewire-s1", rid)
    spec = "rx.broker(me, kinds=['answer'])"
    await _observe(env, pid, spec=spec)             # owner == the PLAN handle
    out = _ok(await env.call("reconcile", handle=pid, handle_type="plan",
                             reground=True))
    rewire = out["reground"]["rewire"]
    assert rewire["handle"] == pid
    assert [s["spec"] for s in rewire["observe_specs"]] == [spec]
    assert rewire["cron_prompt"] == RECONCILE_LOOP_CRON_PROMPT


# ── 6. handle_index unit invariants (pure, no tool) ─────────────────────────
def test_index_register_is_noop_for_empty(tmp_path):
    root = tmp_path / ".reactive"
    handle_index.register_subscription(root, "", "sub-x")
    handle_index.register_subscription(root, "h", "")
    assert not handle_index.index_path(root).exists()   # nothing to hand back


def test_index_corrupt_file_reads_as_empty(tmp_path):
    root = tmp_path / ".reactive"
    root.mkdir()
    handle_index.index_path(root).write_text("{not json", encoding="utf-8")
    assert handle_index.sids_for_handle(root, "h") == []
    # and a subsequent register still works (overwrites the corrupt file).
    handle_index.register_subscription(root, "h", "sub-1")
    assert handle_index.sids_for_handle(root, "h") == ["sub-1"]


def test_index_specs_reads_effect_when_present(tmp_path):
    root = tmp_path / ".reactive"
    root.mkdir()
    (root / "sub-e.spec").write_text("rx.broker(me)", encoding="utf-8")
    (root / "sub-e.bindings.json").write_text('{"me": "h"}', encoding="utf-8")
    (root / "sub-e.effect.json").write_text('{"rule_id": "sub-e"}',
                                            encoding="utf-8")
    handle_index.register_subscription(root, "h", "sub-e")
    subs = handle_index.specs_for_handle(root, "h")
    assert subs == [{"sid": "sub-e", "spec": "rx.broker(me)",
                     "bindings": {"me": "h"}, "effect": {"rule_id": "sub-e"}}]


# ── 7. o6/d24 REGRESSION BAR: legacy fixture loads byte-identically ─────────
LEGACY_RID = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"
RECIPES = Path(__file__).resolve().parents[1] / ".recipes"


def test_o6_legacy_fixture_byte_identical(monkeypatch, tmp_path):
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
        "legacy fixture round-trip is NOT byte-identical — the W2 leg 2 "
        "rewire/index work must add no schema/hydration validator (d24)")
    # the epoch still computes cleanly on the legacy shape.
    assert HEX12.match(grounding_epoch(model))
