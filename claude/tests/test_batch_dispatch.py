"""DESIGN-v7 1.4 Stage A — ACTION BATCHING (batch_group).

A small serial chain of actions sharing a `batch_group` dispatches as ONE
unit: the FSM stamps every unit member in_progress atomically and emits one
head instruction carrying `batch_action_ids`; `pool_spawn_worker` spawns ONE
shell for the unit (handle = `<plan_id>:<head_action_id>`) with every
pre-launch guard run over EVERY member and every rollback covering every
member; the worker executes members in declared order and records status PER
MEMBER (worker.md member loop).

This suite proves the batching invariants on the live tool seam (no
broker/pool restart, no LLM — principle 6), the same discipline as
test_all_ready_wave.py:

  (a) a single-dispatch tick on a batch head stamps ALL members in ONE
      atomic save and the instruction carries `batch_action_ids`;
  (b) unit membership honours the DAG: a member whose dep is outside the
      unit and not yet done stays pending and is NOT absorbed; an in-unit
      dep must be declared EARLIER (declared order IS execution order);
  (c) the spawn guards check EVERY member (done member → unit refused;
      live member → unit refused, no rollback) and a failed/refused spawn
      rolls EVERY member back to pending;
  (d) per-member record_action_status works, and a mid-batch failure
      releases the not-yet-started later members back to pending.

(The wave-side invariant — a batch group is ONE wave slot — is pinned in
test_all_ready_wave.py::test_wave_counts_a_batch_group_as_one_slot, next to
the other wave shape pins.)
"""

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Plan

RID = "recipe-batch"
SID = "s1"
PID = f"{RID}-{SID}"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _err(res):
    assert isinstance(res, ToolError), res
    return res


def _action(aid, deps, status="pending", group=None):
    a = dict(action_id=aid, description=f"do {aid}", status=status,
             depends_on=deps, executor_mode="subagent",
             acceptance={"kind": "tests_pass"})
    if group:
        a["batch_group"] = group
    return a


def _chain(group="g1", n=3, prefix="b"):
    """b1 <- b2 <- b3 …: the dominant serial-chain batch shape."""
    out = []
    for i in range(1, n + 1):
        deps = [f"{prefix}{i - 1}"] if i > 1 else []
        out.append(_action(f"{prefix}{i}", deps, group=group))
    return out


def _save_plan(env, actions, *, state="dispatching", pid=PID):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id=RID, recipe_step_id=SID, domain="generic",
        shape="x", goal="drive the batch", state=state, actions=actions,
    )))


def _statuses(env, pid=PID):
    return {a.action_id: a.status for a in env.ctx.plans.load(pid).actions}


async def _tick(env, pid=PID):
    """One single-action next_action tick (NOT the wave)."""
    return _ok(await env.call("next_action", handle=pid, handle_type="plan"))


# ════════════════════════════════════════════════════════════════════════
# (a) single dispatch: atomic stamp + batch_action_ids on the head
# ════════════════════════════════════════════════════════════════════════
async def test_batch_dispatch_stamps_all_members_atomically(env):
    _save_plan(env, _chain())

    saves = {"n": 0}
    real_save = env.ctx.plans.save

    def counting_save(plan):
        saves["n"] += 1
        return real_save(plan)

    env.ctx.plans.save = counting_save
    try:
        v_before = env.ctx.plans.load(PID).version
        instr = await _tick(env)
    finally:
        env.ctx.plans.save = real_save

    assert instr["kind"] == "dispatch_action"
    assert instr["args"]["action_id"] == "b1"          # the head
    assert instr["args"]["batch_action_ids"] == ["b1", "b2", "b3"]
    assert instr["args"]["batch_group"] == "g1"
    # ONE save persisted the WHOLE unit — a partial failure can neither
    # half-stamp nor strand a member (the same argument as the wave's).
    assert saves["n"] == 1, saves
    assert env.ctx.plans.load(PID).version - v_before == 1
    assert _statuses(env) == {"b1": "in_progress", "b2": "in_progress",
                              "b3": "in_progress"}


async def test_unbatched_action_dispatches_exactly_as_before(env):
    """No batch_group → the pre-v7 descriptor shape, no new keys."""
    _save_plan(env, [_action("a1", []), _action("a2", ["a1"])])
    instr = await _tick(env)
    assert instr["kind"] == "dispatch_action"
    assert instr["args"]["action_id"] == "a1"
    assert "batch_action_ids" not in instr["args"]
    assert "batch_group" not in instr["args"]
    assert _statuses(env) == {"a1": "in_progress", "a2": "pending"}


# ════════════════════════════════════════════════════════════════════════
# (b) unit membership honours the DAG
# ════════════════════════════════════════════════════════════════════════
async def test_member_with_unmet_external_dep_stays_pending(env):
    """A group member gated on work OUTSIDE the unit is not absorbed: it
    stays pending and dispatches later, when its dep really closes."""
    _save_plan(env, [
        _action("b1", [], group="g1"),
        _action("ext", []),                       # independent, NOT in g1
        _action("b2", ["b1", "ext"], group="g1"),  # gated on ext too
    ])
    instr = await _tick(env)
    assert instr["args"]["action_id"] == "b1"
    assert instr["args"]["batch_action_ids"] == ["b1"]   # b2 NOT absorbed
    st = _statuses(env)
    assert st["b2"] == "pending"
    assert st["ext"] == "pending"    # a different slot, not this unit's


async def test_in_unit_dep_must_be_declared_earlier(env):
    """Declared order IS execution order: a member depending on a LATER
    sibling is left out rather than executed before its dep."""
    _save_plan(env, [
        _action("b1", [], group="g1"),
        _action("b2", ["b3"], group="g1"),   # depends on the LATER b3
        _action("b3", ["b1"], group="g1"),
    ])
    instr = await _tick(env)
    # b3's dep (b1) is in-unit and earlier → absorbed; b2's dep (b3) is
    # declared AFTER b2 → excluded, stays pending.
    assert instr["args"]["batch_action_ids"] == ["b1", "b3"]
    assert _statuses(env)["b2"] == "pending"


async def test_batch_member_already_done_satisfies_the_chain(env):
    _save_plan(env, [
        _action("b1", [], status="done", group="g1"),
        _action("b2", ["b1"], group="g1"),
        _action("b3", ["b2"], group="g1"),
    ])
    instr = await _tick(env)
    assert instr["args"]["action_id"] == "b2"
    assert instr["args"]["batch_action_ids"] == ["b2", "b3"]


# ════════════════════════════════════════════════════════════════════════
# (c) the spawn guards check EVERY member; rollbacks cover EVERY member
# ════════════════════════════════════════════════════════════════════════
async def test_spawn_accepts_the_unit_and_holds_one_handle(env):
    _save_plan(env, _chain())
    instr = await _tick(env)
    ids = instr["args"]["batch_action_ids"]

    _ok(await env.call("pool_spawn_worker", plan_id=PID, action_id="b1",
                       action_ids=ids))
    spawns = [s for s in env.ctx.pool.spawns if s["role"] == "worker"]
    assert len(spawns) == 1                       # ONE shell for the unit
    assert spawns[0]["handle"] == f"{PID}:b1"      # the HEAD's handle
    # members stay in_progress — the unit is now really backed by a shell
    assert set(_statuses(env).values()) == {"in_progress"}


async def test_spawn_refuses_when_head_not_in_action_ids(env):
    _save_plan(env, _chain())
    await _tick(env)
    res = _err(await env.call("pool_spawn_worker", plan_id=PID,
                              action_id="b1", action_ids=["b2", "b3"]))
    assert "does not contain the head" in res.message
    assert env.ctx.pool.spawns == []


async def test_spawn_refuses_unknown_member_and_rolls_back_the_unit(env):
    _save_plan(env, _chain())
    await _tick(env)
    res = _err(await env.call(
        "pool_spawn_worker", plan_id=PID, action_id="b1",
        action_ids=["b1", "b2", "nope"]))
    assert "do not exist" in res.message
    assert env.ctx.pool.spawns == []
    # the pre-stamped unit is FULLY rolled back — no phantom tail
    assert _statuses(env) == {"b1": "pending", "b2": "pending",
                              "b3": "pending"}


async def test_spawn_refuses_a_done_member_and_rolls_back_the_rest(env):
    """A stale batch list naming delivered work refuses the WHOLE unit (a
    batch never half-executes) and releases the pre-stamps."""
    _save_plan(env, _chain())
    await _tick(env)
    # someone else completed b2 between the tick and the spawn
    p = env.ctx.plans.load(PID)
    next(a for a in p.actions if a.action_id == "b2").status = "done"
    next(a for a in p.actions
         if a.action_id == "b2").acceptance.actual = "delivered"
    env.ctx.plans.save(p)

    res = _err(await env.call("pool_spawn_worker", plan_id=PID,
                              action_id="b1",
                              action_ids=["b1", "b2", "b3"]))
    assert "already 'done'" in res.message
    assert env.ctx.pool.spawns == []
    st = _statuses(env)
    assert st == {"b1": "pending", "b2": "done", "b3": "pending"}


async def test_spawn_refuses_a_live_member_without_rolling_back(env):
    """A member with a LIVE shell (an earlier solo dispatch) refuses the unit
    — and deliberately does NOT roll back, exactly like the solo live-guard:
    a live worker legitimately owns that member."""
    _save_plan(env, _chain())
    # a live shell already holds b2's own handle
    await env.ctx.pool.spawn_worker(PID, "b2")
    await _tick(env)   # the FSM's own unit EXCLUDES live b2 (s27/C7 input);
    # this spawn passes a hand-built stale list that still names it
    res = _err(await env.call("pool_spawn_worker", plan_id=PID,
                              action_id="b1",
                              action_ids=["b1", "b2", "b3"]))
    assert "already has a LIVE worker" in res.message
    # no rollback on the live-guard path (the running worker owns b2)
    assert "b2" in res.message


async def test_failed_spawn_rolls_back_every_member(env, monkeypatch):
    """The canonical POOL_CAPACITY_EXCEEDED case: the whole unit reverts to
    pending so the FSM can re-dispatch it — no stranded phantom tail."""
    _save_plan(env, _chain())
    instr = await _tick(env)

    class _Fail:
        ok = False
        code = "pool_capacity_exceeded"

    async def fail_spawn(*a, **kw):
        return _Fail()

    monkeypatch.setattr(env.ctx.pool, "spawn_worker", fail_spawn)
    res = await env.call("pool_spawn_worker", plan_id=PID, action_id="b1",
                         action_ids=instr["args"]["batch_action_ids"])
    assert getattr(res, "ok", False) is False
    assert _statuses(env) == {"b1": "pending", "b2": "pending",
                              "b3": "pending"}


# ════════════════════════════════════════════════════════════════════════
# (d) per-member status records; mid-batch failure releases the tail
# ════════════════════════════════════════════════════════════════════════
async def test_record_action_status_per_member_still_works(env):
    _save_plan(env, _chain())
    await _tick(env)
    _ok(await env.call("record_action_status", plan_id=PID, action_id="b1",
                       status="done", evidence="b1 built; gate green"))
    _ok(await env.call("record_action_status", plan_id=PID, action_id="b2",
                       status="done", evidence="b2 wired; gate green"))
    st = _statuses(env)
    assert st == {"b1": "done", "b2": "done", "b3": "in_progress"}
    p = env.ctx.plans.load(PID)
    assert p.actions[0].acceptance.actual == "b1 built; gate green"
    assert p.actions[1].acceptance.actual == "b2 wired; gate green"


async def test_mid_batch_failure_leaves_later_members_pending(env):
    """The worker stops the member loop at the first failure; recording that
    failure releases the not-yet-started later members back to pending —
    deterministically, at the record seam, not by worker goodwill. Members
    BEFORE the failure keep their recorded status."""
    _save_plan(env, _chain(n=4))
    await _tick(env)
    _ok(await env.call("record_action_status", plan_id=PID, action_id="b1",
                       status="done", evidence="b1 done"))
    _ok(await env.call("record_action_status", plan_id=PID, action_id="b2",
                       status="failed", evidence="b2 gate red"))
    st = _statuses(env)
    assert st == {"b1": "done",            # earlier member keeps its record
                  "b2": "failed",          # the failure itself
                  "b3": "pending",         # released — never started
                  "b4": "pending"}


async def test_mid_batch_failure_release_is_scoped_to_the_group(env):
    """Only LATER, SAME-GROUP, in_progress members are released — an
    unrelated in-flight action is never touched."""
    _save_plan(env, [
        _action("b1", [], group="g1"),
        _action("b2", ["b1"], group="g1"),
        _action("other", [], status="in_progress"),   # someone else's work
    ])
    await _tick(env)
    _ok(await env.call("record_action_status", plan_id=PID, action_id="b1",
                       status="failed", evidence="b1 gate red"))
    st = _statuses(env)
    assert st["b2"] == "pending"
    assert st["other"] == "in_progress"   # untouched


async def test_batch_group_is_emission_gated_on_disk(env):
    """o6: an unbatched action serializes byte-shape-identical to pre-v7 —
    the new key appears ONLY when the planner batched it."""
    _save_plan(env, [_action("a1", []), _action("b1", [], group="g1")])
    dumped = env.ctx.plans.load(PID).model_dump(mode="json")
    a1, b1 = dumped["actions"]
    assert "batch_group" not in a1
    assert b1["batch_group"] == "g1"


async def test_add_action_stamps_batch_group_at_authoring_time(env):
    """The planner's authoring path (planner-phase-author.md: batch small
    serial chains) really lands the field."""
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="framework"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="linear", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="c1",
                       description="write it", batch_group="chain-1"))
    _ok(await env.call("add_action", plan_id=pid, action_id="c2",
                       description="test it", depends_on=["c1"],
                       batch_group="chain-1"))
    p = env.ctx.plans.load(pid)
    assert [a.batch_group for a in p.actions] == ["chain-1", "chain-1"]


def test_worker_command_carries_the_member_loop():
    """Guide-corpus pin (same rationale as the 1.1 wave pins): the batching
    machinery is only real if worker.md instructs the member loop."""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    worker = (repo / ".claude" / "commands" / "worker.md").read_text(
        encoding="utf-8")
    assert "batch_group" in worker
    assert "declared order" in worker
    author = (repo / "docs" / "guides" / "planner-phase-author.md").read_text(
        encoding="utf-8")
    assert "batch_group" in author
    assert "task_class" in author       # DESIGN-v7 1.3 authoring stamp
