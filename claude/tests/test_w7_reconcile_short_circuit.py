"""DESIGN-v6 W7 item 3 (line 384) — the reconcile->next_action short-circuit.

The bar: on an IDLE tick the reconcile->next_action PAIR collapses to a
one-line ``{no_change: true, wait_hint, wait_reason}`` payload instead of
next_action's full instruction+context push — and any REAL change (a new inbox
message, a state transition, or reconcile itself having mutated the record)
restores the full instruction on the very next tick.

Two invariants the design pins:

* It rides the EXISTING ``changed=False`` path — the short-circuit is a cheap
  deterministic RETURN (principle 6), never an LLM decision.
* It is STATELESS (d13 + neuron steer): the primary signal is
  ``reconcile changed=False`` + an empty inbox-diff. There is NO
  ``last_acked_epoch`` store and none is built here; ``ack_epoch`` is surfaced
  best-effort only and never gates correctness.

The signal is OPT-IN: the paced RECONCILE-LOOP passes reconcile's ``changed``
result into ``next_action(reconcile_changed=...)``. A bare ``next_action`` call
(the item-1 wait_hint surface + every legacy caller) is UNCHANGED — it still
returns the full WAIT instruction with wait_hint in ``args``. That is what lets
item 1 (wait_hint on the instruction) and item 3 (idle collapse) coexist.

d7 discipline: this runner may itself be a spawned worker whose
EDP_ROLE/EDP_HANDLE leak into pytest — clear them so role-scoping / addressing
don't skew the tick.
"""

from datetime import datetime, timezone

import pytest
from edp_contracts import ToolOk

from edp_claude.schemas import Plan, Recipe

RID = "recipe-sc"
SID = "s1"
PID = f"{RID}-{SID}"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _save_plan(env, pid, actions, state="dispatching"):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id="r-x", recipe_step_id="s1", domain="generic",
        shape="x", goal="g", state=state,
        actions=[dict(action_id=a["id"], description="d", status=a["status"],
                      depends_on=a.get("depends_on", []),
                      executor_mode="subagent",
                      acceptance={"kind": "tests_pass"})
                 for a in actions],
    )))


def _save_executing_recipe(env, rid=RID):
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [],
                       "expected_outcomes": [{"id": "o1", "description": "d",
                                              "verification": "v"}]},
        steps=[{"step_id": SID, "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))


async def _na(env, handle, htype, **extra):
    return _ok(await env.call("next_action", handle=handle,
                              handle_type=htype, **extra))


# ── 1. the core deliverable: idle pair collapses to no_change ────────────────
async def test_idle_plan_pair_collapses_to_no_change(env):
    # A heads-down worker: one action in_progress, nothing in the inbox. The
    # loop reconciles (changed=False), then next_action with that signal.
    _save_plan(env, "p-idle", [{"id": "a1", "status": "in_progress"}])
    rc = _ok(await env.call("reconcile", handle="p-idle", handle_type="plan"))
    assert rc["changed"] is False                       # rides the changed=False path
    d = await _na(env, "p-idle", "plan", reconcile_changed=rc["changed"])
    # collapsed: the one-line payload, NOT the full instruction.
    # Phase 6: the payload now carries the just-in-time zero-prose directive.
    d.pop("directive", None)
    assert d == {"no_change": True, "wait_hint": 10,
                 "wait_reason": "heads-down; leave alone", "ack_epoch": None}
    assert "kind" not in d and "context" not in d       # full push suppressed


async def test_idle_recipe_pair_collapses_to_no_change(env):
    # The recipe branch: an EXECUTING recipe (planner in flight) idles the same
    # way — reconcile changed=False, next_action collapses.
    _save_executing_recipe(env)
    rc = _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    assert rc["changed"] is False
    d = await _na(env, RID, "recipe", reconcile_changed=rc["changed"])
    assert d["no_change"] is True
    assert isinstance(d["wait_hint"], int) and d["wait_reason"]


# ── 2. the short-circuit carries the pacing hint from the shared table ───────
async def test_no_change_carries_pacing_hint(env):
    _save_plan(env, "p-hint", [{"id": "a1", "status": "in_progress"}])
    d = await _na(env, "p-hint", "plan", reconcile_changed=False)
    # heads-down band: 10 min (same table item 1 surfaces on the full path).
    assert d["wait_hint"] == 10
    assert d["wait_reason"] == "heads-down; leave alone"


# ── 3. a NEW inbox message restores the full instruction next tick ───────────
async def test_new_inbox_message_restores_full_instruction(env):
    _save_plan(env, "p-msg", [{"id": "a1", "status": "in_progress"}])
    # empty inbox first → collapses.
    assert (await _na(env, "p-msg", "plan",
                      reconcile_changed=False)).get("no_change") is True
    # a worker/user message lands on the plan's inbox → the inbox-diff is no
    # longer empty → the next tick returns the FULL instruction.
    await env.call("broker_send", to="p-msg", kind="answer",
                   body={"text": "here is your answer"})
    d = await _na(env, "p-msg", "plan", reconcile_changed=False)
    assert "no_change" not in d
    assert d["kind"] == "wait"                    # full WAIT instruction restored
    assert d["args"]["wait_hint"] == 10           # item-1 hint still rides in args


# ── 4. a STATE TRANSITION restores the full instruction next tick ────────────
async def test_state_transition_restores_full_instruction(env):
    # A pending, dependency-free action is READY: next_action DISPATCHES it (a
    # real forward move, non-WAIT, a record mutation) — the short-circuit must
    # NOT fire even though the loop opted in with reconcile_changed=False.
    _save_plan(env, "p-ready", [{"id": "a1", "status": "pending"}])
    d = await _na(env, "p-ready", "plan", reconcile_changed=False)
    assert "no_change" not in d
    assert d["kind"] == "dispatch_action"


async def test_reconcile_having_changed_suppresses_short_circuit(env):
    # If reconcile itself mutated the record (changed=True), the pair is NOT
    # idle — passing reconcile_changed=True must return the full instruction
    # even on a WAIT tick with an empty inbox.
    _save_plan(env, "p-rc", [{"id": "a1", "status": "in_progress"}])
    d = await _na(env, "p-rc", "plan", reconcile_changed=True)
    assert "no_change" not in d
    assert d["kind"] == "wait"


# ── 5. opt-in: a BARE next_action is unchanged (item-1 coexistence) ──────────
async def test_bare_next_action_is_not_short_circuited(env):
    # No reconcile_changed passed → the direct/legacy caller (and item 1's
    # wait_hint surface) still gets the FULL WAIT instruction with the hint in
    # args. This is what keeps every existing next_action test green.
    _save_plan(env, "p-bare", [{"id": "a1", "status": "in_progress"}])
    d = await _na(env, "p-bare", "plan")           # reconcile_changed defaults None
    assert "no_change" not in d
    assert d["kind"] == "wait"
    assert d["args"]["wait_hint"] == 10 and d["args"]["wait_reason"]


# ── 6. stateless: no last_acked_epoch store — collapses repeatedly ───────────
async def test_stateless_no_epoch_store_repeated_ticks_collapse(env):
    # Two idle ticks in a row both collapse — there is no epoch bookkeeping that
    # would make the second tick behave differently. ack_epoch is best-effort
    # (None here) and never gates.
    _save_plan(env, "p-rep", [{"id": "a1", "status": "in_progress"}])
    d1 = await _na(env, "p-rep", "plan", reconcile_changed=False)
    d2 = await _na(env, "p-rep", "plan", reconcile_changed=False)
    assert d1.get("no_change") is True and d2.get("no_change") is True
    assert d1 == d2                                # deterministic, no drift
    assert d1["ack_epoch"] is None                 # best-effort, no store


# ── 7. non-consuming inbox-diff: the message is still delivered ──────────────
async def test_inbox_diff_is_non_consuming(env):
    # The short-circuit's inbox poll must NOT advance the cursor — a real
    # check_inbox still delivers the message that suppressed the collapse.
    _save_plan(env, "p-nc", [{"id": "a1", "status": "in_progress"}])
    await env.call("broker_send", to="p-nc", kind="answer",
                   body={"text": "deliver me"})
    # next_action sees it (suppresses the collapse) but does NOT consume it.
    d = await _na(env, "p-nc", "plan", reconcile_changed=False)
    assert "no_change" not in d
    inbox = _ok(await env.call("check_inbox", handle="p-nc"))
    assert any(mm["body"].get("text") == "deliver me" for mm in inbox["messages"])
