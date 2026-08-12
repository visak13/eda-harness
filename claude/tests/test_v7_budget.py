"""v7 WS3 §2.6c — budget fields (star + step estimates) and budget_status."""

import json

import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_budget_declared_at_start_and_reported(env):
    res = await env.call("start_recipe", goal="budgeted build", domain="test",
                         budget={"claude_tokens": 500_000,
                                 "delegate_usd": 5.0})
    rid = res.data["recipe_id"]
    await env.call("add_step", recipe_id=rid, description="step one",
                   execution="inline", estimate={"tokens": 80_000,
                                                 "hours": 2.0})
    # a fake delegate audit sidecar — budget_status sums every audit file
    home = env.ctx.recipes.root.parent
    bdir = home / ".bridge"
    bdir.mkdir(exist_ok=True)
    rows = [
        {"kind": "generate", "tokens_in": 1000, "tokens_out": 4000,
         "cost_usd": 0.012, "ok": True},
        {"kind": "challenge", "tokens_in": 500, "tokens_out": 100,
         "cost_usd": 0.0, "ok": False, "error": "HTTP 429"},
    ]
    (bdir / "audit-plan-x-a1.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    st = await env.call("budget_status", recipe_id=rid)
    assert st.ok
    d = st.data
    assert d["budget"] == {"claude_tokens": 500_000, "delegate_usd": 5.0}
    assert d["step_estimates"][0]["estimate"] == {"tokens": 80_000,
                                                  "hours": 2.0}
    assert d["delegate_actuals"] == {"calls": 2, "tokens_in": 1500,
                                     "tokens_out": 4100, "cost_usd": 0.012,
                                     "failures": 1}
    assert d["steps_done"] == 0 and d["steps_total"] == 1
    assert "unmeasured" in d["claude_tokens_note"]


async def test_budget_omitted_is_legacy_shape(env):
    res = await env.call("start_recipe", goal="no budget", domain="test")
    rid = res.data["recipe_id"]
    raw = json.loads(
        (env.ctx.recipes.root / rid / "recipe.json").read_text("utf-8"))
    assert "budget" not in raw          # emission gate holds
    st = await env.call("budget_status", recipe_id=rid)
    assert st.ok and st.data["budget"] == {}


async def test_worklog_rolls_like_events(env, monkeypatch):
    """v7 §2.1 — plan worklogs roll at threshold into segment + digest."""
    from edp_claude.store import recipe_store as rs
    monkeypatch.setattr(rs, "EVENTS_ROLLUP_THRESHOLD", 10)
    monkeypatch.setattr(rs, "EVENTS_TAIL_KEEP", 3)
    res = await env.call("start_recipe", goal="worklog roll", domain="test")
    rid = res.data["recipe_id"]
    await env.call("add_step", recipe_id=rid, description="s",
                   execution="spawn_planner", estimate={"hours": 1})
    pres = await env.call("create_plan", recipe_id=rid, step_id="s1",
                          goal="g", shape="linear-build")
    pid = pres.data["plan_id"]
    for i in range(12):
        env.ctx.plans.append_worklog(pid, {"kind": "note", "i": i})
    pdir = env.ctx.plans.root / pid
    hot = (pdir / "worklog.jsonl").read_text("utf-8").strip().splitlines()
    # the invariant: the hot file stays BOUNDED below the threshold (tail +
    # post-roll appends), never grows monotonically like the 558KB live case
    assert len(hot) < 10
    assert (pdir / "worklog.0001.jsonl").is_file()
    digest = (pdir / "worklog.0001.digest.md").read_text("utf-8")
    assert digest.startswith("# worklog segment 0001 digest")


async def test_g6_budget_advisory_in_reconcile(env):
    """v7 §2.6c — reconcile surfaces the G6 rung only past a DECLARED cap."""
    import json as _json
    res = await env.call("start_recipe", goal="g6", domain="test",
                         budget={"delegate_usd": 0.01})
    rid = res.data["recipe_id"]
    home = env.ctx.recipes.root.parent
    (home / ".bridge").mkdir(exist_ok=True)
    (home / ".bridge" / "audit-x.jsonl").write_text(
        _json.dumps({"cost_usd": 0.05, "ok": True}) + "\n", encoding="utf-8")
    rec = await env.call("reconcile", handle=rid, handle_type="recipe")
    assert rec.ok
    assert rec.data["budget_advisory"] and "G6 BUDGET GATE" in rec.data["budget_advisory"]
    # a budget-less recipe never pays for or surfaces the rung
    res2 = await env.call("start_recipe", goal="no cap", domain="test")
    rec2 = await env.call("reconcile", handle=res2.data["recipe_id"],
                          handle_type="recipe")
    assert rec2.ok and rec2.data["budget_advisory"] is None
