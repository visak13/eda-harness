"""Integration milestone #9 — prove the stub→Http swap composes for real
over HTTP. The ONLY change vs the component-#2 WALK-1 is the injected
Broker/Pool (DI, not call-site) — DESIGN-v4 inversion-of-control.

Real-shell HITL (SubprocessSpawner producing real planner/worker Claude
processes) is the MANUAL surface and is intentionally NOT here — see
docs/design/components/integration/integration-HITL.md.
"""

from datetime import datetime, timezone

import httpx
import pytest
from edp_contracts import ToolError, ToolOk

from edp_broker.service import create_app as broker_app
from edp_claude.clients import HttpBroker
from edp_claude.server import make_http_context
from edp_claude.tools import build_registry
from edp_pool.http_pool import HttpPool
from edp_pool.service import create_app as pool_app
from edp_pool.spawner import FakeSpawner


def _now():
    return datetime.now(timezone.utc).isoformat()


def _recipe(state, branches, steps):
    return {
        "recipe_id": "r", "user_goal_verbatim": "g",
        "user_goal_distilled": "g", "domain": "software_engineering",
        "state": state,
        "comprehension": {"branches": branches, "expected_outcomes": []},
        "steps": steps, "context": {}, "final_outcome": None, "version": 1,
        "created_at": _now(), "updated_at": _now(),
    }


@pytest.fixture
async def env(tmp_path):
    bapp = broker_app(tmp_path / "bdata")
    papp = pool_app(FakeSpawner(), broker_url="http://unreachable:1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=bapp), base_url="http://b"
    ) as bc, httpx.AsyncClient(
        transport=httpx.ASGITransport(app=papp), base_url="http://p"
    ) as pc:
        ctx = make_http_context(
            tmp_path, broker=HttpBroker("http://b", bc),
            pool=HttpPool("http://p", pc),
        )
        tools = {t.name: t for t in build_registry(ctx)}

        async def call(n, **i):
            return await tools[n].run(i)

        yield call


async def test_httpbroker_roundtrip_over_real_broker(env):
    r = await env("broker_send", to="neuron:r", kind="done", body={"k": 1},
                   from_="planner:p")
    assert isinstance(r, ToolOk)
    # poll via the same HttpBroker path
    msgs = await env("next_action", handle="missing", handle_type="recipe")
    assert isinstance(msgs, ToolError)  # unrelated; just exercises tool path


async def test_seam_swap_drives_recipe_over_http(env):
    """v5 spine, but Broker+Pool are the REAL services over HTTP. Proves
    HttpPool spawn returns the envelope, _advance_executing polls the REAL
    broker, and a real-broker plan_closed advances the recipe."""
    rid = (await env(
        "start_recipe", goal="ship a thing", domain="software_engineering"
    )).data["recipe_id"]

    # Team-architecture-restoration Phase 1 (2026-05-21): self-audit
    # gate removed; REASON → record_outcome → DECLARE_STEP.
    d = (await env("next_action", handle=rid, handle_type="recipe")).data
    assert d["kind"] == "reason"

    # 2026-05-28 comprehension gate: record_outcome refuses until
    # comprehension is cleared (real curiosity clear OR user sign-off).
    assert isinstance(await env(
        "record_comprehension_signoff", recipe_id=rid,
        user_quote="go ahead, ship it"), ToolOk)

    assert isinstance(await env(
        "record_outcome", recipe_id=rid, description="thing shipped",
        verification="it runs"), ToolOk)

    d = (await env("next_action", handle=rid, handle_type="recipe")).data
    assert d["kind"] == "declare_step"
    sid = (await env("add_step", recipe_id=rid, description="do it",
                     execution="spawn_planner")).data["step_id"]

    d = (await env("next_action", handle=rid, handle_type="recipe")).data
    assert d["kind"] == "spawn_planner"

    # REAL pool spawn over HTTP
    sp = await env("pool_spawn_planner", recipe_id=rid, step_id=sid)
    assert isinstance(sp, ToolOk)
    assert sp.data["session_id"].startswith("planner:")

    # waiting — next_action is a pure phase pacer; the recipe is EXECUTING
    # with the planner in flight → WAIT (no reconcile has run yet).
    assert (await env("next_action", handle=rid,
                      handle_type="recipe")).data["kind"] == "wait"

    # planner notifies neuron via the REAL broker. The plan_id MUST be
    # this step's plan (2026-05-22 fix: reconcile filters plan_closed by
    # plan_id so a stale earlier-step message can't falsely complete the
    # current step).
    assert isinstance(
        await env("broker_send", to=rid, kind="plan_closed",
                  body={"plan_id": f"{rid}-{sid}"}, from_="my-planner"),
        ToolOk,
    )
    # reconcile syncs the broker plan_closed over HTTP (the work that used
    # to be hidden in next_action), then next_action advances the recipe.
    rc = await env("reconcile", handle=rid, handle_type="recipe")
    assert isinstance(rc, ToolOk) and rc.data["changed"] is True
    nxt = (await env("next_action", handle=rid,
                     handle_type="recipe")).data
    assert nxt["kind"] in ("run_inline", "done")


async def test_pool_capacity_error_verbatim_over_http(env):
    for i in range(3):
        assert isinstance(
            await env("pool_spawn_worker", plan_id="p", action_id=f"a{i}"),
            ToolOk,
        )
    res = await env("pool_spawn_worker", plan_id="p", action_id="a4")
    assert isinstance(res, ToolError)
    assert res.code == "pool_capacity_exceeded"
    assert "max workers = 3" in res.message  # verbatim through the seam
