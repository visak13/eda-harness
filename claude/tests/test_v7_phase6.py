"""DESIGN-v7 Phase 6 — compaction resilience + recipe-size hygiene.

  * 6.1 ack ledger: an epoch MATCH baselines what the handle internalized;
    the next reground leads with `changes_since_your_last_ground` — the
    code-computed screenful — instead of the digest cold.
  * 6.2 fold_decisions: one atomic call folds a settled cluster into a
    summary decision; reconcile nags past EDP_DECISION_FOLD_THRESHOLD.
  * 6.3 state synthesis: record_step_result refreshes
    context/state-synthesis.md; get_recipe_digest(synthesis=true) returns
    the same markdown.
"""

from datetime import datetime, timezone

from edp_contracts import ToolOk

from edp_claude.fsm import grounding_epoch
from edp_claude.schemas import Recipe

RID = "recipe-p6"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _now():
    return datetime.now(timezone.utc)


def _decision(did, text, *, load_bearing=False, status="active"):
    d = {"id": did, "text": text, "rationale": "r", "by": "neuron",
         "at": _now().isoformat()}
    if load_bearing:
        d["load_bearing"] = True
    if status != "active":
        d["status"] = status
    return d


def _save_recipe(env, decisions=(), step_status="in_progress"):
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=RID, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": step_status, "depends_on": [],
                "execution": "spawn_planner"}],
        context={"decisions": list(decisions)},
        created_at=_now(), updated_at=_now(),
    )))


# ── 6.1 ack ledger + reground delta ──────────────────────────────────────────
async def test_match_then_change_then_reground_leads_with_the_delta(env):
    _save_recipe(env, decisions=[_decision("d1", "old truth",
                                           load_bearing=True)])
    epoch = grounding_epoch(env.ctx.recipes.load(RID))
    # 1: a matching ack baselines the ledger for this handle
    _ok(await env.call("next_action", handle=RID, handle_type="recipe",
                       ack_epoch=epoch))
    assert RID in env.ctx.recipes.read_ack_ledger(RID)
    # 2: the ground changes (new load-bearing decision + step closes)
    r = env.ctx.recipes.load(RID)
    from edp_claude.schemas import Decision
    r.context.decisions.append(Decision(
        id="d2", text="NEW direction", rationale="r", by="neuron",
        at=_now(), load_bearing=True))
    r.steps[0].status = "done"
    env.ctx.recipes.save(r)
    # 3: the stale echo's reground leads with the code-computed delta
    d = _ok(await env.call("next_action", handle=RID, handle_type="recipe",
                           ack_epoch=epoch))
    delta = d["context"]["reground"]["changes_since_your_last_ground"]
    assert delta, "a ledgered handle must get the delta, not digest-only"
    assert any("d2" in x for x in delta["decisions_added"])
    assert "s1" in delta["steps_closed"]


async def test_no_ledger_degrades_to_digest_only(env):
    _save_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    d = _ok(await env.call("next_action", handle=RID, handle_type="recipe",
                           ack_epoch="000000000000"))
    rg = d["context"]["reground"]
    assert rg["digest"], "the full digest is the fallback"
    assert rg["changes_since_your_last_ground"] is None


# ── 6.2 fold_decisions ───────────────────────────────────────────────────────
async def test_fold_supersedes_members_atomically_and_inherits_lb(env):
    _save_recipe(env, decisions=[
        _decision("d1", "iterate 1"), _decision("d2", "iterate 2",
                                                load_bearing=True),
        _decision("d3", "unrelated, stays")])
    out = _ok(await env.call("fold_decisions", recipe_id=RID,
                             decision_ids=["d1", "d2"],
                             summary_text="settled: the folded truth"))
    r = env.ctx.recipes.load(RID)
    by = {d.id: d for d in r.context.decisions}
    assert by["d1"].status == "superseded"
    assert by["d1"].superseded_by == out["summary_id"]
    assert by["d2"].status == "superseded"
    assert by["d3"].status == "active"
    summary = by[out["summary_id"]]
    assert summary.load_bearing is True, "any-lb member => lb summary"
    assert out["active_decisions"] == 2  # d3 + the summary


async def test_fold_refuses_unknown_and_inactive_members(env):
    _save_recipe(env, decisions=[
        _decision("d1", "a"), _decision("d2", "b", status="superseded")])
    res = await env.call("fold_decisions", recipe_id=RID,
                         decision_ids=["d1", "dX"], summary_text="s")
    assert not isinstance(res, ToolOk) and "dX" in str(res)
    res = await env.call("fold_decisions", recipe_id=RID,
                         decision_ids=["d1", "d2"], summary_text="s")
    assert not isinstance(res, ToolOk) and "d2" in str(res)


async def test_reconcile_nags_past_the_fold_threshold(env, monkeypatch):
    monkeypatch.setenv("EDP_DECISION_FOLD_THRESHOLD", "3")
    _save_recipe(env, decisions=[_decision(f"d{i}", f"t{i}")
                                 for i in range(1, 6)])
    d = _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    adv = d.get("fold_advisory") or ""
    assert "fold_decisions" in adv and "5 ACTIVE" in adv
    monkeypatch.setenv("EDP_DECISION_FOLD_THRESHOLD", "100")
    d = _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    assert d.get("fold_advisory") is None


# ── 6.3 state synthesis ──────────────────────────────────────────────────────
async def test_step_close_writes_the_synthesis_sidecar(env):
    _save_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    _ok(await env.call("record_step_result", recipe_id=RID, step_id="s1",
                       result={"outputs": ["out"]}))
    path = env.ctx.recipes.root / RID / "context" / "state-synthesis.md"
    text = path.read_text(encoding="utf-8")
    assert "# State of the recipe" in text
    assert "[x] s1" in text
    assert "d1: D" in text


async def test_digest_synthesis_mode_returns_the_markdown(env):
    _save_recipe(env, decisions=[_decision("d1", "D", load_bearing=True)])
    d = _ok(await env.call("get_recipe_digest", recipe_id=RID,
                           synthesis=True))
    assert d["synthesis_md"] and "# State of the recipe" in d["synthesis_md"]
    d = _ok(await env.call("get_recipe_digest", recipe_id=RID))
    assert d["synthesis_md"] is None
