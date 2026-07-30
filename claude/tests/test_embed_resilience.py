"""Embed-backend resilience — the live-hang regression (2026-07-12).

A live neuron's `search_context` on recipe -0e7ca8 (a LEGACY recipe with no
embeddings sidecar) wedged for hours: the lazy backfill awaited the embed
backend per context item (~370 items) with no per-call bound, no breaker,
and no budget, against an unreachable ollama with a 30s client timeout.

The production contract now pinned here:
  * per-call hard timeout (`_embed_timeout_s`, env-tunable);
  * CIRCUIT BREAKER — the first failure stops all further backend calls in
    a backfill pass; remaining entries rank by token overlap;
  * NO DEGRADED PERSIST — the sidecar is written only when every entry
    embedded, so a transient outage can never permanently poison a recipe's
    semantic search (absent sidecar = backfill retries next search);
  * a healthy backend still backfills fully, persists once, and steady-state
    searches never re-enter backfill.
"""

import asyncio
from datetime import datetime, timezone

from edp_contracts import ToolOk

from edp_claude.schemas import Recipe

RID = "recipe-embed-res"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _save_recipe(env, n_decisions=5):
    now = datetime.now(timezone.utc)
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=RID, user_goal_verbatim="build the widget",
        domain="generic", state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={"decisions": [
            {"id": f"d{i}", "text": f"decision {i}: prefer widget batching",
             "rationale": "r", "by": "neuron", "at": now.isoformat()}
            for i in range(1, n_decisions + 1)]},
        created_at=now, updated_at=now,
    )))


class _DownEmbed:
    """A backend that is down: every call raises after counting."""

    def __init__(self):
        self.calls = 0

    async def embed(self, text, kind="document"):
        self.calls += 1
        raise ConnectionError("embed backend unreachable")


class _HangingEmbed:
    """A backend that accepts and never answers (the ollama-hang shape)."""

    def __init__(self):
        self.calls = 0

    async def embed(self, text, kind="document"):
        self.calls += 1
        await asyncio.sleep(3600)


def _sidecar(env):
    return (env.ctx.recipes.root / RID / "context" / "embeddings.jsonl")


async def test_down_backend_trips_the_breaker_after_one_call(env):
    _save_recipe(env, n_decisions=8)
    down = _DownEmbed()
    env.ctx.embed = down
    res = _ok(await env.call("search_context", query="widget batching",
                             recipe_id=RID, top_k=3))
    # ranked results still come back, by token overlap
    assert res["mode"] == "text-fallback"
    assert res["matches"], "degraded search must still answer"
    # breaker: 1 query embed + 1 backfill probe — NEVER one per item
    assert down.calls <= 2, (
        f"{down.calls} embed calls for 8 items — the per-item loop is back "
        "(the exact shape that hung the live neuron for hours)")


async def test_hanging_backend_is_bounded_by_the_per_call_timeout(
        env, monkeypatch):
    monkeypatch.setenv("EDP_EMBED_TIMEOUT_S", "0.2")
    _save_recipe(env, n_decisions=8)
    hang = _HangingEmbed()
    env.ctx.embed = hang
    async with asyncio.timeout(5):   # the whole call must finish FAST
        res = _ok(await env.call("search_context", query="widget batching",
                                 recipe_id=RID, top_k=3))
    assert res["mode"] == "text-fallback"
    assert hang.calls <= 2


async def test_degraded_backfill_is_not_persisted_and_retries(env):
    _save_recipe(env, n_decisions=4)
    env.ctx.embed = _DownEmbed()
    _ok(await env.call("search_context", query="widget", recipe_id=RID))
    assert not _sidecar(env).exists(), (
        "a degraded backfill persisted the sidecar — that makes the outage "
        "PERMANENT (sidecar existence disables backfill)")
    # backend comes back (conftest's stub embeds deterministically)
    from edp_claude.stubs.stub_embed import StubEmbed
    env.ctx.embed = StubEmbed()
    res = _ok(await env.call("search_context", query="widget batching",
                             recipe_id=RID, top_k=3))
    assert res["mode"] == "embedding"
    assert _sidecar(env).exists(), "recovered backend must complete backfill"


async def test_healthy_backend_backfills_persists_and_goes_steady_state(env):
    _save_recipe(env, n_decisions=4)
    res = _ok(await env.call("search_context", query="widget batching",
                             recipe_id=RID, top_k=3))
    assert res["mode"] == "embedding" and res["matches"]
    assert _sidecar(env).exists()
    # steady state: the next search must NOT re-enter backfill (only the
    # query itself is embedded)
    calls = {"doc": 0}
    real = env.ctx.embed

    class _Spy:
        async def embed(self, text, kind="document"):
            if kind == "document":
                calls["doc"] += 1
            return await real.embed(text, kind)
    env.ctx.embed = _Spy()
    _ok(await env.call("search_context", query="again", recipe_id=RID))
    assert calls["doc"] == 0, "steady-state search re-entered backfill"
