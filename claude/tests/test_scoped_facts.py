"""DESIGN-v6 W4/a4 — lineage-scoped facts + recall fan-out.

Facts live under .memory/{global,recipe/<id>,domain/<domain>}/facts.jsonl.
The default scope is LINEAGE-FIRST: a shell whose handle resolves a recipe
records recipe/<R>; only a truly bare shell defaults to global, and
scope='global' is write-gated to the neuron role. recall fans out over
global + the caller's recipe + domain and merges, with a lazy fallback to
the pre-v6 flat trail when no scoped file exists yet.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import Plan
from edp_claude.server import make_context
from edp_claude.tools import build_registry


def _now():
    return datetime.now(timezone.utc)


def _save_recipe(ctx, rid, domain="software_engineering"):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="g", user_goal_distilled="g",
        domain=domain, state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "pending", "depends_on": [], "execution": "inline"}],
        created_at=_now(), updated_at=_now(),
    ))


def _save_plan(ctx, rid, plan_id, domain="software_engineering"):
    ctx.plans.save(Plan(
        plan_id=plan_id, recipe_id=rid, recipe_step_id="s1", domain=domain,
        shape="parallel_multitool", goal="g", state="dispatching"))


def _tools(ctx):
    return {t.name: t for t in build_registry(ctx)}


def _worker_env(mp, plan_id, action_id="a1"):
    mp.setenv("EDP_ROLE", "worker")
    mp.setenv("EDP_HANDLE", f"{plan_id}:{action_id}")


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


# A fact the software_engineering kg_filter keeps (substantive, not chatter).
_FACT_R1 = {"text": "recipe-one chose scoped facts.jsonl per lineage"}
_FACT_R2 = {"text": "recipe-two chose a different serialization"}
_GLOBAL_FACT = {"text": "the atomic append_jsonl helper is the write chokepoint"}


async def test_worker_fact_is_recipe_scoped_and_not_cross_recipe(tmp_path, monkeypatch):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    _save_recipe(ctx, "recipe-r1-aaa")
    _save_recipe(ctx, "recipe-r2-bbb")
    _save_plan(ctx, "recipe-r1-aaa", "recipe-r1-aaa-s1")
    _save_plan(ctx, "recipe-r2-bbb", "recipe-r2-bbb-s1")

    # a WORKER under recipe r1 records a fact with no explicit scope
    _worker_env(monkeypatch, "recipe-r1-aaa-s1")
    res = _ok(await t["record_context"].run(
        {"kind": "fact", "fact": _FACT_R1}))
    assert res["stored"] is True and res["scope"] == "recipe"

    # it landed in the recipe-scoped trail (NOT global, NOT legacy)
    scoped = tmp_path / ".memory" / "recipe" / "recipe-r1-aaa" / "facts.jsonl"
    assert scoped.exists()
    rec = json.loads(scoped.read_text(encoding="utf-8").splitlines()[0])
    assert rec["scope"] == "recipe" and rec["recipe_id"] == "recipe-r1-aaa"
    assert "recipe-one" in rec["text"]
    assert not (tmp_path / ".memory" / "global" / "facts.jsonl").exists()

    # recall IN r1 sees it
    got = _ok(await t["recall"].run({"query": "recipe-one scoped"}))
    assert any("recipe-one" in str(r) for r in got["results"])

    # recall in ANOTHER recipe (r2) does NOT see it
    _worker_env(monkeypatch, "recipe-r2-bbb-s1")
    got2 = _ok(await t["recall"].run({"query": "recipe-one scoped"}))
    assert not any("recipe-one" in str(r) for r in got2["results"])


async def test_global_fact_is_visible_everywhere(tmp_path, monkeypatch):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    _save_recipe(ctx, "recipe-r1-aaa")
    _save_recipe(ctx, "recipe-r2-bbb")
    _save_plan(ctx, "recipe-r1-aaa", "recipe-r1-aaa-s1")
    _save_plan(ctx, "recipe-r2-bbb", "recipe-r2-bbb-s1")

    # the NEURON promotes a fact to global (scope='global' explicit)
    monkeypatch.setenv("EDP_ROLE", "neuron")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    res = _ok(await t["record_context"].run(
        {"kind": "fact", "fact": _GLOBAL_FACT, "scope": "global",
         "domain": "software_engineering"}))
    assert res["stored"] is True and res["scope"] == "global"
    assert (tmp_path / ".memory" / "global" / "facts.jsonl").exists()

    # a worker in r1 AND a worker in r2 both recall it
    for plan_id in ("recipe-r1-aaa-s1", "recipe-r2-bbb-s1"):
        _worker_env(monkeypatch, plan_id)
        got = _ok(await t["recall"].run({"query": "append_jsonl chokepoint"}))
        assert any("chokepoint" in str(r) for r in got["results"]), plan_id


async def test_non_neuron_global_write_is_refused(tmp_path, monkeypatch):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    _save_recipe(ctx, "recipe-r1-aaa")
    _save_plan(ctx, "recipe-r1-aaa", "recipe-r1-aaa-s1")

    _worker_env(monkeypatch, "recipe-r1-aaa-s1")
    res = await t["record_context"].run(
        {"kind": "fact", "fact": _GLOBAL_FACT, "scope": "global",
         "domain": "software_engineering"})
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"
    assert "neuron-only" in res.message
    # nothing was written to the global trail
    assert not (tmp_path / ".memory" / "global" / "facts.jsonl").exists()


async def test_recall_falls_back_to_legacy_trail(tmp_path, monkeypatch):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    _save_recipe(ctx, "recipe-r1-aaa")
    _save_plan(ctx, "recipe-r1-aaa", "recipe-r1-aaa-s1")

    # a pre-v6 flat trail exists; NO scoped files have been written yet
    legacy = tmp_path / ".memory" / "facts.jsonl"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        json.dumps({"text": "legacy pre-v6 fact", "domain": "generic"}) + "\n",
        encoding="utf-8")

    _worker_env(monkeypatch, "recipe-r1-aaa-s1")
    got = _ok(await t["recall"].run({"query": "legacy pre-v6"}))
    assert any("legacy pre-v6" in str(r) for r in got["results"])


async def test_recall_fans_out_over_global_recipe_domain(tmp_path, monkeypatch):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    _save_recipe(ctx, "recipe-r1-aaa", domain="software_engineering")
    _save_plan(ctx, "recipe-r1-aaa", "recipe-r1-aaa-s1")

    # neuron writes a global fact
    monkeypatch.setenv("EDP_ROLE", "neuron")
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    _ok(await t["record_context"].run(
        {"kind": "fact", "fact": {"text": "global scope fact alpha"},
         "scope": "global", "domain": "software_engineering"}))
    # neuron writes a DOMAIN-scoped fact for software_engineering
    _ok(await t["record_context"].run(
        {"kind": "fact", "fact": {"text": "domain scope fact beta"},
         "scope": "domain", "domain": "software_engineering"}))

    # a worker under r1 writes a recipe fact
    _worker_env(monkeypatch, "recipe-r1-aaa-s1")
    _ok(await t["record_context"].run(
        {"kind": "fact", "fact": {"text": "recipe scope fact gamma"}}))

    # one recall from the worker fans out over all three scopes
    got = _ok(await t["recall"].run({"query": "scope fact"}))
    blob = json.dumps(got["results"])
    assert "alpha" in blob   # global
    assert "beta" in blob    # domain (matches the worker's recipe domain)
    assert "gamma" in blob   # recipe

    # the three scoped trails exist on disk (no legacy fallback used)
    root = tmp_path / ".memory"
    assert (root / "global" / "facts.jsonl").exists()
    assert (root / "domain" / "software_engineering" / "facts.jsonl").exists()
    assert (root / "recipe" / "recipe-r1-aaa" / "facts.jsonl").exists()
