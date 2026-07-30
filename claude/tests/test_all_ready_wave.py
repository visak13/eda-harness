"""ALL-READY-WAVE surface (next_action(all_ready=true)) — DESIGN-v6 B1.

A planner can fire the WHOLE currently-ready action set in ONE turn instead of
one action per tick. This suite proves the four invariants on the live tool
seam (no broker/pool restart, no LLM — principle 6):

  (a) the wave returns EXACTLY the ready frontier for a representative DAG;
  (b) every returned action is stamped in_progress in ONE ATOMIC save
      (asserted via a save-call spy AND the plan.version delta — PlanStore.save
      bumps version once per physical write, so delta==1 <=> a single write);
  (c) NO action with unmet deps is ever returned (full-frontier + partial-deps);
  (d) re-invoking does not double-dispatch an already-in_progress action, and a
      done action is never re-surfaced (the W2 duplicate-dispatch guard +
      depends_on gating stay authoritative when the wave surface is used).

Kept fast (pure in-memory tool calls, seconds).
"""

import pytest
from edp_contracts import ToolOk

from edp_claude.schemas import Plan

RID = "recipe-wave"
SID = "s1"
PID = f"{RID}-{SID}"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _action(aid, deps, status="pending"):
    return dict(action_id=aid, description=f"do {aid}", status=status,
                depends_on=deps, executor_mode="subagent",
                acceptance={"kind": "tests_pass"})


def _save_plan(env, actions, *, state="dispatching", pid=PID):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id=RID, recipe_step_id=SID, domain="generic",
        shape="x", goal="drive the ready-wave", state=state, actions=actions,
    )))


async def _wave(env, pid=PID, **extra):
    return _ok(await env.call("next_action", handle=pid, handle_type="plan",
                              all_ready=True, **extra))


def _ids(wave):
    return {a["args"]["action_id"] for a in wave["actions"]}


def _statuses(env, pid=PID):
    p = env.ctx.plans.load(pid)
    return {a.action_id: a.status for a in p.actions}


# ── (a) exact ready frontier for a representative DAG ────────────────────────
async def test_wave_returns_exactly_the_ready_frontier(env):
    # a1,a2 ready (no deps); a3 needs a1; a4 needs a1+a2 -> both unmet.
    _save_plan(env, [
        _action("a1", []),
        _action("a2", []),
        _action("a3", ["a1"]),
        _action("a4", ["a1", "a2"]),
    ])
    wave = await _wave(env)
    assert wave["kind"] == "dispatch_wave"
    assert _ids(wave) == {"a1", "a2"}, wave
    assert wave["count"] == 2
    # every returned instruction is a DISPATCH_ACTION descriptor.
    assert all(a["kind"] == "dispatch_action" for a in wave["actions"])
    # the frontier is stamped in_progress; unmet-dep actions stay pending.
    st = _statuses(env)
    assert st == {"a1": "in_progress", "a2": "in_progress",
                  "a3": "pending", "a4": "pending"}


# ── (b) all stamped in_progress in ONE atomic save ───────────────────────────
async def test_wave_stamps_all_in_one_atomic_save(env):
    # Five simultaneously-ready actions: a single save must persist ALL of them.
    _save_plan(env, [_action(f"a{i}", []) for i in range(1, 6)])

    saves = {"n": 0}
    real_save = env.ctx.plans.save

    def counting_save(plan):
        saves["n"] += 1
        return real_save(plan)

    env.ctx.plans.save = counting_save
    try:
        v_before = env.ctx.plans.load(PID).version
        wave = await _wave(env)
    finally:
        env.ctx.plans.save = real_save
    v_after = env.ctx.plans.load(PID).version

    assert _ids(wave) == {"a1", "a2", "a3", "a4", "a5"}
    # ONE save call — no per-action interleaved write.
    assert saves["n"] == 1, saves
    # version bumps exactly once => a single physical write_atomic persisted the
    # whole wave (PlanStore.save increments version once per write). This is the
    # atomic-single-save invariant: a partial failure can neither double-stamp
    # nor strand an action.
    assert v_after - v_before == 1, (v_before, v_after)
    assert all(s == "in_progress" for s in _statuses(env).values())


# ── (c) never returns an unmet-dep action (frontier + partial deps) ──────────
async def test_wave_never_returns_unmet_deps(env):
    # a4 needs BOTH a1 and a2. Start with a1 already done, a2 still pending:
    # a2 is ready, a3 (needs a1) is now ready, a4 (needs a2 too) is NOT.
    _save_plan(env, [
        _action("a1", [], status="done"),
        _action("a2", []),
        _action("a3", ["a1"]),
        _action("a4", ["a1", "a2"]),
    ])
    wave = await _wave(env)
    assert _ids(wave) == {"a2", "a3"}, wave
    assert "a4" not in _ids(wave)          # partially-satisfied deps excluded
    assert env.ctx.plans.load(PID).version  # loads cleanly
    assert _statuses(env)["a4"] == "pending"


async def test_wave_empty_when_nothing_ready(env):
    # a2 depends on a1 which is in_progress (not done) -> nothing is ready.
    _save_plan(env, [
        _action("a1", [], status="in_progress"),
        _action("a2", ["a1"]),
    ])
    v_before = env.ctx.plans.load(PID).version
    wave = await _wave(env)
    assert wave["actions"] == []
    assert wave["count"] == 0
    # a pure no-op wave must NOT spuriously bump the version.
    assert env.ctx.plans.load(PID).version == v_before


# ── (d) re-invoking does not double-dispatch (W2 guard holds) ────────────────
async def test_wave_does_not_double_dispatch(env):
    _save_plan(env, [_action("a1", []), _action("a2", []),
                     _action("a3", ["a1"])])
    first = await _wave(env)
    assert _ids(first) == {"a1", "a2"}

    # Second invocation: a1,a2 are now in_progress (not pending) and a3 still
    # has an unmet dep -> the wave re-surfaces NOTHING. An already-in_progress
    # action is never re-dispatched.
    second = await _wave(env)
    assert second["actions"] == []
    assert second["count"] == 0
    # statuses unchanged by the second call — no re-stamp, no interleaved state.
    assert _statuses(env) == {"a1": "in_progress", "a2": "in_progress",
                              "a3": "pending"}


async def test_wave_never_resurfaces_a_done_action(env):
    _save_plan(env, [_action("a1", [], status="done"), _action("a2", [])])
    wave = await _wave(env)
    assert _ids(wave) == {"a2"}          # done a1 never returned
    assert "a1" not in _ids(wave)


# ── DRAFTED plan advances to DISPATCHING then waves (mirrors single dispatch) ─
async def test_wave_advances_drafted_plan(env):
    _save_plan(env, [_action("a1", []), _action("a2", [])], state="drafted")
    wave = await _wave(env)
    assert _ids(wave) == {"a1", "a2"}
    p = env.ctx.plans.load(PID)
    assert str(p.state) == "dispatching"


# ── DESIGN-v7 1.1: the wave is ANNOTATED (dispatch_order + capacity) ─────────
async def test_wave_carries_dispatch_order_and_capacity(env, monkeypatch):
    """A planner facing a frontier wider than the pool must be able to spawn
    up to headroom instead of eating POOL_CAPACITY_EXCEEDED rollbacks. So the
    wave annotates each instruction with its `dispatch_order` (the
    deterministic spawn order) and the payload with `capacity` = worker cap −
    live active workers, from ONE pool probe."""
    monkeypatch.setenv("EDP_MAX_WORKERS", "3")
    _save_plan(env, [_action(f"a{i}", []) for i in range(1, 5)])
    # one live worker already occupies a slot → headroom = 3 - 1 = 2
    await env.ctx.pool.spawn_worker("other-plan", "x1")

    wave = await _wave(env)
    assert wave["count"] == 4
    assert [a["dispatch_order"] for a in wave["actions"]] == [0, 1, 2, 3]
    # order is deterministic AND matches the returned list order
    assert wave["capacity"] == 2, wave


async def test_wave_capacity_fails_open_to_none_when_pool_unreachable(
        env, monkeypatch):
    """The annotation is an optimisation, never a gate: a dead pool yields
    capacity=None and the wave still delivers every dispatch (the planner
    then behaves exactly as pre-v7 — spawn and let the pool's cap refuse)."""
    async def _boom(recipe_id=None):
        raise RuntimeError("pool down")

    monkeypatch.setattr(env.ctx.pool, "sessions", _boom)
    _save_plan(env, [_action("a1", []), _action("a2", [])])
    wave = await _wave(env)
    assert wave["count"] == 2                      # delivery unaffected
    assert wave["capacity"] is None                # fail-open, not 0


async def test_wave_capacity_never_goes_negative(env, monkeypatch):
    monkeypatch.setenv("EDP_MAX_WORKERS", "1")
    await env.ctx.pool.spawn_worker("p-x", "x1")
    await env.ctx.pool.spawn_worker("p-x", "x2")
    _save_plan(env, [_action("a1", [])])
    wave = await _wave(env)
    assert wave["capacity"] == 0                   # floored, never -1


# ── DESIGN-v7 1.4: a batch group is ONE wave slot (the head) ────────────────
async def test_wave_counts_a_batch_group_as_one_slot(env):
    """A serial chain sharing a batch_group dispatches as ONE unit: the wave
    returns the HEAD only (carrying `batch_action_ids`), every member is
    stamped in_progress in the same atomic save, and an independent action
    still gets its own slot."""
    chain = [_action("b1", []), _action("b2", ["b1"]), _action("b3", ["b2"])]
    for a in chain:
        a["batch_group"] = "g1"
    _save_plan(env, chain + [_action("solo", [])])

    wave = await _wave(env)
    assert wave["count"] == 2, wave                # head + solo, NOT 4
    assert _ids(wave) == {"b1", "solo"}
    head = next(a for a in wave["actions"]
                if a["args"]["action_id"] == "b1")
    assert head["args"]["batch_action_ids"] == ["b1", "b2", "b3"]
    # every member stamped in the one atomic wave save
    st = _statuses(env)
    assert st == {"b1": "in_progress", "b2": "in_progress",
                  "b3": "in_progress", "solo": "in_progress"}


# ── DESIGN-v7 1.1 guide-corpus gate: the wave is INSTRUCTED, not just built ──
# The root cause the plan names: the wave surface shipped in W9 and NO guide
# instructed it, so planners kept dispatching one action per tick. The guide
# text is therefore part of the deliverable and is pinned here like any other
# corpus fact (same shape as test_s26_guide_tool_names' corpus pins).
_REPO = __import__("pathlib").Path(__file__).resolve().parents[1]


def test_drive_guide_instructs_the_ready_wave_as_default():
    drive = (_REPO / "docs" / "guides" / "planner-phase-drive.md").read_text(
        encoding="utf-8")
    assert "all_ready" in drive, (
        "planner-phase-drive.md no longer instructs the ready-wave — the "
        "surface regresses to shipped-but-uninstructed (the DESIGN-v7 1.1 "
        "root cause)")
    assert "all_ready=true" in drive
    # and the two annotations the planner is told to act on are named
    assert "dispatch_order" in drive
    assert "capacity" in drive


def test_planner_command_instructs_the_ready_wave_as_default():
    cmd = (_REPO / ".claude" / "commands" / "agentic-plan.md").read_text(
        encoding="utf-8")
    assert "all_ready=true" in cmd, (
        ".claude/commands/agentic-plan.md no longer makes the ready-wave the "
        "default drive call")


# ── DESIGN-v7 1.5.1: all_ready on a RECIPE handle is the STEP-FRONTIER wave ──
# (This replaces the retired test_wave_on_recipe_handle_is_empty_noop —
# serial planners were structural pre-1.5.1, and the empty no-op pinned
# exactly the behaviour the design removes.)

def _step(sid, deps, status="pending", execution="spawn_planner"):
    return {"step_id": sid, "kind": "work", "description": f"do {sid}",
            "status": status, "depends_on": deps, "execution": execution}


def _save_recipe(env, steps, *, state="planning", rid=RID):
    from datetime import datetime, timezone
    from edp_claude.schemas import Recipe
    now = datetime.now(timezone.utc)
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state=state, comprehension={"branches": [], "expected_outcomes": []},
        steps=steps, context={}, created_at=now, updated_at=now,
    )))


async def _recipe_wave(env, rid=RID):
    return _ok(await env.call("next_action", handle=rid,
                              handle_type="recipe", all_ready=True))


def _step_statuses(env, rid=RID):
    r = env.ctx.recipes.load(rid)
    return {s.step_id: s.status for s in r.steps}


async def test_recipe_wave_returns_exactly_the_ready_step_frontier(env):
    # s1,s2 ready (no deps); s3 needs s1 (unmet); s4 needs a done s0-like dep.
    _save_recipe(env, [
        _step("s1", []),
        _step("s2", []),
        _step("s3", ["s1"]),
    ])
    wave = await _recipe_wave(env)
    assert wave["kind"] == "dispatch_wave"
    ids = {a["args"]["step_id"] for a in wave["actions"]}
    assert ids == {"s1", "s2"}, wave
    assert wave["count"] == 2
    # one SPAWN_PLANNER instruction per ready step, in dispatch_order.
    assert all(a["kind"] == "spawn_planner" for a in wave["actions"])
    assert [a["dispatch_order"] for a in wave["actions"]] == [0, 1]
    # the frontier is stamped in_progress; the unmet-dep step stays pending;
    # dispatching moved the recipe to EXECUTING.
    assert _step_statuses(env) == {"s1": "in_progress", "s2": "in_progress",
                                   "s3": "pending"}
    assert str(env.ctx.recipes.load(RID).state) == "executing"


async def test_recipe_wave_fires_from_executing_for_newly_ready_steps(env):
    # THE parallelism case: s1 runs, s2's dep (s0) just closed — the wave
    # must dispatch s2 WITHOUT waiting for s1 (pre-1.5.1 the EXECUTING
    # branch returned WAIT unconditionally).
    _save_recipe(env, [
        _step("s0", [], status="done"),
        _step("s1", [], status="in_progress"),
        _step("s2", ["s0"]),
    ], state="executing")
    wave = await _recipe_wave(env)
    assert {a["args"]["step_id"] for a in wave["actions"]} == {"s2"}
    st = _step_statuses(env)
    assert st["s2"] == "in_progress"
    assert st["s1"] == "in_progress"        # untouched, still owned


async def test_recipe_wave_does_not_double_dispatch(env):
    _save_recipe(env, [_step("s1", []), _step("s2", [])])
    first = await _recipe_wave(env)
    assert first["count"] == 2
    # Second invocation: both are in_progress now — nothing re-surfaces.
    second = await _recipe_wave(env)
    assert second["actions"] == []
    assert second["count"] == 0
    assert _step_statuses(env) == {"s1": "in_progress", "s2": "in_progress"}


async def test_recipe_wave_parked_planner_step_is_not_redispatched(env):
    # 1.5.2: a PARKED planner is 0 process but still OWNS its step (its
    # session row keeps the handle lock + resume token). Pool liveness says
    # "parked" — the wave must treat that as owned, never re-dispatchable.
    _save_recipe(env, [_step("s1", []), _step("s2", [])])
    env.ctx.pool.mark_parked(f"{RID}:s1")
    wave = await _recipe_wave(env)
    assert {a["args"]["step_id"] for a in wave["actions"]} == {"s2"}, wave
    st = _step_statuses(env)
    assert st["s1"] == "pending"            # owned by the parked planner
    assert st["s2"] == "in_progress"


async def test_recipe_wave_stamps_all_in_one_atomic_save(env):
    _save_recipe(env, [_step(f"s{i}", []) for i in range(1, 5)])
    saves = {"n": 0}
    real_save = env.ctx.recipes.save

    def counting_save(recipe):
        saves["n"] += 1
        return real_save(recipe)

    env.ctx.recipes.save = counting_save
    try:
        wave = await _recipe_wave(env)
    finally:
        env.ctx.recipes.save = real_save
    assert wave["count"] == 4
    # ONE save call persists the whole wave — no per-step interleaved write.
    assert saves["n"] == 1, saves
    assert all(s == "in_progress" for s in _step_statuses(env).values())


async def test_recipe_wave_skips_inline_steps(env):
    # An inline step runs in the CALLER's context — a wave slot is a planner
    # spawn, so the inline step is left pending for the single-step path.
    _save_recipe(env, [_step("s1", []), _step("s2", [], execution="inline")])
    wave = await _recipe_wave(env)
    assert {a["args"]["step_id"] for a in wave["actions"]} == {"s1"}
    assert _step_statuses(env)["s2"] == "pending"


async def test_recipe_wave_does_not_bypass_comprehension(env):
    # The wave is a dispatch surface, not a gate bypass: a COMPREHENDING
    # recipe (brief not signed off) waves nothing.
    _save_recipe(env, [_step("s1", [])], state="comprehending")
    wave = await _recipe_wave(env)
    assert wave["actions"] == []
    assert _step_statuses(env)["s1"] == "pending"


async def test_recipe_wave_carries_planner_capacity(env, monkeypatch):
    # EDP_MAX_PLANNERS headroom (default 4), one live planner → capacity 3.
    monkeypatch.setenv("EDP_MAX_PLANNERS", "4")
    await env.ctx.pool.spawn_planner("other-recipe", "sX")
    _save_recipe(env, [_step("s1", [])])
    wave = await _recipe_wave(env)
    assert wave["count"] == 1
    assert wave["capacity"] == 3, wave
