"""s26 self-pacing cluster — backlog items 8, 10, 11, 12.

Four defects that all charged the same tax: tokens burned on every heartbeat
tick, whether or not anything happened.

  (8)  The rx wake predicate filtered on message KIND; the W7 idle
       short-circuit's inbox check did not. A `progress` ping the neuron would
       have absorbed and dropped therefore defeated the idle collapse and
       bought a full LLM turn.
  (10) Escalation counted next_action ticks that reset only on a RECIPE-level
       change, so a plan advancing briskly underneath was indistinguishable
       from a wedged one. It cried wolf twice on 2026-07-09.
  (11) That count was compared against a tick threshold, never a duration, so
       the real patience was whatever the caller's cron happened to be — a
       quantity `wait_hint` knows nothing about.
  (12) The neuron is a WRITER on the flowback channel it subscribes to, and
       the wake predicate did not filter on SENDER. Its own emissions woke it.

Every assertion here is MUTATION-PROVED: see the action's evidence for the
mutation applied, the RED failure text observed, and the revert. Each item is
asserted in BOTH directions — a filter that swallows everything satisfies the
suppression half and guards nothing.
"""

from pathlib import Path

import reactivex as rx
from edp_contracts import ToolOk

from edp_claude import cadence
from edp_claude.fsm import pacing_hint
from edp_claude.fsm.state_machines import PACING
from edp_claude.reactive import (
    NEURON_SELF_AUTHOR,
    ROLE_PRIMARY_WAKES,
    ROLE_WAKE_KINDS,
    RxRuntime,
    wake_kinds,
)
from edp_claude.schemas import InstructionKind
from edp_claude.tools import _tools
from edp_claude.tools._tools import _should_wake

# The kind chosen to prove "a genuine wake still wakes". It must REMAIN in the
# neuron's broker wake-set after item 8 drops `progress` — asserting the wake
# half against a kind we just removed would prove nothing. `question` is also a
# ROLE_PRIMARY_WAKE, so it cannot be dropped without failing the W7 guard.
RETAINED_WAKE_KIND = "question"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _freeze(monkeypatch, start=1000.0):
    """Patches `_wait_clock` (monotonic, patience only), never the module's
    `_now` (wall-clock datetime). See test_proactive_wait._freeze."""
    clock = {"t": start}
    monkeypatch.setattr(_tools, "_wait_clock", lambda: clock["t"])
    return clock


async def _executing_recipe(env, rid, step_status="in_progress"):
    from datetime import datetime, timezone

    from edp_claude.schemas import Recipe
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": step_status, "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))


async def _paced_tick(env, rid):
    """One tick of the real reconcile-loop: the collapse is opt-in via
    reconcile_changed=False, exactly as cadence.RECONCILE_LOOP_CRON_PROMPT
    drives it."""
    return (await env.call("next_action", handle=rid, handle_type="recipe",
                           reconcile_changed=False)).data


# ══ item 8 — the doorbell: the idle check must be kind-aware ═══════════════

def test_neuron_wake_set_drops_progress_but_keeps_its_primaries():
    broker = ROLE_WAKE_KINDS["neuron"]["broker"]
    assert "progress" not in broker           # absorb-and-drop liveness noise
    assert set(ROLE_PRIMARY_WAKES["neuron"]) <= set(broker)
    assert RETAINED_WAKE_KIND in broker       # the kind the wake half uses


def test_wake_kinds_accessor_is_the_single_source_of_truth():
    assert wake_kinds("neuron") == set(ROLE_WAKE_KINDS["neuron"]["broker"])
    assert wake_kinds("neuron", "recipe_events") == set(
        ROLE_WAKE_KINDS["neuron"]["recipe_events"])
    # An unmapped role must read as kind-BLIND (None), never as an empty set:
    # empty would silently swallow every wake.
    assert wake_kinds("nobody") is None
    assert wake_kinds("neuron", "no_such_source") is None


def test_wake_predicate_is_pure_and_each_term_wakes_independently():
    """wake <=> kind != WAIT or reconcile.changed or alert or kind in WAKE_KINDS"""
    idle = dict(instr_kind=InstructionKind.WAIT, reconcile_changed=False,
                record_changed=False, alert=False, inbox_wake=False)
    assert _should_wake(**idle) is False                      # the collapse
    assert _should_wake(**{**idle, "instr_kind": InstructionKind.DISPATCH_ACTION})
    assert _should_wake(**{**idle, "reconcile_changed": True})
    assert _should_wake(**{**idle, "reconcile_changed": None})  # bare call
    assert _should_wake(**{**idle, "record_changed": True})
    assert _should_wake(**{**idle, "alert": True})
    assert _should_wake(**{**idle, "inbox_wake": True})


async def test_inbox_check_is_kind_filtered_against_the_wake_set(env):
    """The unit under the integration test: the same poll, two verdicts."""
    rid = "recipe-item8-unit"
    await env.call("broker_send", to=rid, kind="progress",
                   body={"phase": "still working"})
    assert await _tools._inbox_has_new(env.ctx, rid) is True          # blind
    assert await _tools._inbox_has_new(
        env.ctx, rid, wake_kinds("neuron")) is False                  # filtered
    await env.call("broker_send", to=rid, kind=RETAINED_WAKE_KIND,
                   body={"q": "?"})
    assert await _tools._inbox_has_new(
        env.ctx, rid, wake_kinds("neuron")) is True                   # real wake


async def test_progress_ping_during_executing_collapses_tick_to_no_change(
        env, monkeypatch):
    """Direction 1 (suppress). RED before item 8: bool(msgs) saw the ping and
    woke a full instruction+context push."""
    _tools._WAIT_STATE.clear()
    _freeze(monkeypatch)
    rid = "recipe-item8-progress"
    await _executing_recipe(env, rid)
    assert (await _paced_tick(env, rid)).get("no_change") is True   # baseline

    await env.call("broker_send", to=rid, kind="progress",
                   body={"phase": "step 3 of 7"})
    d = await _paced_tick(env, rid)
    assert d.get("no_change") is True
    assert "context" not in d           # no expensive re-grounding push


async def test_a_retained_wake_kind_still_wakes_a_full_turn(env, monkeypatch):
    """Direction 2 (do not swallow everything). A filter that suppressed all
    kinds would pass the test above and guard nothing."""
    _tools._WAIT_STATE.clear()
    _freeze(monkeypatch)
    rid = "recipe-item8-question"
    await _executing_recipe(env, rid)
    assert (await _paced_tick(env, rid)).get("no_change") is True   # baseline

    await env.call("broker_send", to=rid, kind=RETAINED_WAKE_KIND,
                   body={"question": "which embedder?"})
    d = await _paced_tick(env, rid)
    assert d.get("no_change") is None            # full instruction, not a stub
    assert d["kind"] == "wait" and "context" in d


async def test_the_suppressed_progress_message_is_kept_not_dropped(env):
    """Item 8 suppresses a WAKE, never a MESSAGE. check_inbox still delivers."""
    rid = "recipe-item8-kept"
    await env.call("broker_send", to=rid, kind="progress", body={"phase": "x"})
    got = _ok(await env.call("check_inbox", handle=rid))
    assert [m["kind"] for m in got["messages"]] == ["progress"]


# ══ items 10 + 11 — escalation resets on progress, and counts SECONDS ══════

async def _plan_under(env, rid):
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id="s1",
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="work"))
    return pid


def _action_statuses(env, pid):
    return tuple(a.status for a in env.ctx.plans.load(pid).actions)


async def test_plan_level_progress_resets_the_patience_clock(env, monkeypatch):
    """Item 10, direction 1. The recipe never changes — step s1 stays
    in_progress throughout — yet an action transition inside its plan IS
    progress and must restart the clock. RED before the fix: the old counter
    saw only the recipe and escalated straight through the transition."""
    monkeypatch.setenv("EDP_WAIT_ESCALATE_MULTIPLIER", "3")
    _tools._WAIT_STATE.clear()
    clock = _freeze(monkeypatch)
    rid = "recipe-item10-reset"
    await _executing_recipe(env, rid)
    pid = await _plan_under(env, rid)

    before = _action_statuses(env, pid)
    d = await _paced_tick(env, rid)
    assert d.get("no_change") is True

    clock["t"] += 1700                                   # just short of 1800
    assert (await _paced_tick(env, rid)).get("no_change") is True

    # Real FSM progress underneath: the plan dispatches a1 (pending→in_progress).
    await env.call("next_action", handle=pid, handle_type="plan")
    after = _action_statuses(env, pid)
    assert after != before, "fixture must actually move an action"

    clock["t"] += 50
    await _paced_tick(env, rid)                          # observes the new sig
    assert _tools._WAIT_STATE[rid].cycles == 1           # clock restarted

    # 1700s more: 3450s since the wait began, but only 1700s since progress.
    clock["t"] += 1700
    d = (await env.call("next_action", handle=rid, handle_type="recipe")).data
    assert "proactive escalation" not in d["rationale"].lower()
    assert d["args"]["waited_secs"] == 1700

    # The recipe itself never moved — proving the reset came from the PLAN.
    assert [s.status for s in env.ctx.recipes.load(rid).steps] == ["in_progress"]


async def test_without_progress_the_same_elapsed_time_does_escalate(
        env, monkeypatch):
    """Item 10, direction 2. Same clock, same recipe, no action transition:
    escalation MUST fire. A 'reset' that never lets escalation happen would
    pass the test above and guard nothing."""
    monkeypatch.setenv("EDP_WAIT_ESCALATE_MULTIPLIER", "3")
    _tools._WAIT_STATE.clear()
    clock = _freeze(monkeypatch)
    rid = "recipe-item10-fires"
    await _executing_recipe(env, rid)
    await _plan_under(env, rid)

    await _paced_tick(env, rid)
    clock["t"] += 1700
    assert (await _paced_tick(env, rid)).get("no_change") is True
    clock["t"] += 50                       # no progress driven here
    await _paced_tick(env, rid)
    clock["t"] += 1700                     # 3450s total, all of it silent
    d = (await env.call("next_action", handle=rid, handle_type="recipe")).data
    assert "proactive escalation" in d["rationale"].lower()


async def test_a_due_escalation_beats_the_idle_collapse(env, monkeypatch):
    """Items 8 + 11 interact: item 8 collapses idle ticks, and a collapsed tick
    renders no rationale. An escalation the caller never sees is not an
    escalation, so `alert` must defeat the collapse."""
    monkeypatch.setenv("EDP_WAIT_ESCALATE_MULTIPLIER", "3")
    _tools._WAIT_STATE.clear()
    clock = _freeze(monkeypatch)
    rid = "recipe-item11-alert"
    await _executing_recipe(env, rid)

    assert (await _paced_tick(env, rid)).get("no_change") is True
    clock["t"] += 1800
    d = await _paced_tick(env, rid)          # same opted-in paced call
    assert d.get("no_change") is None
    assert "proactive escalation" in d["rationale"].lower()


def test_threshold_is_time_derived_from_the_pacing_hint(monkeypatch):
    """Item 11. The threshold is SECONDS, computed from the state's own
    wait_hint — the quantity the loop is told to obey."""
    monkeypatch.setenv("EDP_WAIT_ESCALATE_MULTIPLIER", "3")
    monkeypatch.delenv("EDP_WAIT_ESCALATE_SECS", raising=False)
    hint_mins, _ = pacing_hint("child_in_progress_recent_output")
    assert hint_mins == 10
    assert cadence.wait_escalate_secs(hint_mins * 60) == 1800


def test_widening_the_tick_cannot_move_the_threshold(monkeypatch):
    """Item 11, the skew, constructed from REAL values only.

    The smallest hint the PACING table can emit is 1 minute (verify_pending);
    the neuron's heartbeat in this recipe is 30 minutes. So the loop looks once
    per 1800s while the hint asks for 60s — a 30x skew, and `wait_hint` never
    entered the old threshold at all.

    Under the OLD contract patience was `cycles x heartbeat`, so widening the
    heartbeat rescaled patience by 30x — the tick, not the work, decided when
    the neuron cried wolf. The invariant pinned here is stronger and covers
    both directions: the threshold does not depend on heartbeat_secs AT ALL.
    """
    monkeypatch.setenv("EDP_WAIT_ESCALATE_MULTIPLIER", "3")
    monkeypatch.delenv("EDP_WAIT_ESCALATE_SECS", raising=False)
    fastest_hint_mins = min(mins for mins, _ in PACING.values())
    assert fastest_hint_mins == 1                       # 60s, not a made-up 10s
    expected_secs = fastest_hint_mins * 60

    monkeypatch.setenv("EDP_HEARTBEAT_SECS", "60")
    assert cadence.heartbeat_secs() == 60
    narrow = cadence.wait_escalate_secs(expected_secs)
    old_narrow = cadence.wait_escalate_multiplier() * cadence.heartbeat_secs()

    monkeypatch.setenv("EDP_HEARTBEAT_SECS", "1800")    # the 30-min heartbeat
    assert cadence.heartbeat_secs() == 1800
    wide = cadence.wait_escalate_secs(expected_secs)
    old_wide = cadence.wait_escalate_multiplier() * cadence.heartbeat_secs()

    assert narrow == wide == 180          # 3 x 60s, floored at _MIN (60s)
    assert old_narrow != old_wide         # the old contract moved with the tick
    assert old_wide // old_narrow == 30   # by exactly the skew


def test_escalate_secs_has_a_floor_and_an_absolute_override(monkeypatch):
    monkeypatch.setenv("EDP_WAIT_ESCALATE_MULTIPLIER", "1")
    monkeypatch.delenv("EDP_WAIT_ESCALATE_SECS", raising=False)
    assert cadence.wait_escalate_secs(1) == 60            # floor, not 1s
    monkeypatch.setenv("EDP_WAIT_ESCALATE_SECS", "7")
    assert cadence.wait_escalate_secs(600) == 7           # override wins


def test_the_renamed_knob_does_not_answer_to_its_old_name(monkeypatch):
    """The knob changed MEANING (tick count -> patience multiplier). It must not
    keep its old spelling, or a stale env silently sets the wrong thing."""
    monkeypatch.delenv("EDP_WAIT_ESCALATE_MULTIPLIER", raising=False)
    monkeypatch.setenv("EDP_WAIT_ESCALATE_CYCLES", "99")
    assert cadence.wait_escalate_multiplier() == 3        # default, not 99


# ══ item 12 — the neuron must not wake on its own emissions ════════════════

NEURON_ADDR = "recipe-item12"
WORKER_ADDR = f"{NEURON_ADDR}-s1:a1"


def _runtime_with(entries):
    def provider(name, **kw):
        assert name == "worklog" and kw.get("recipe_id")
        return rx.of(*entries)
    return RxRuntime(provider)


def _collect(obs):
    out = []
    obs.subscribe(on_next=out.append)
    return out


def _flowback(kind, sender):
    return {"kind": kind, "channel": "flowback", "from": sender,
            "body": {"summary": "s"}}


# A neuron has no EDP_HANDLE, so `_emit_recipe_event` stamps its events with the
# NEURON_SELF_AUTHOR sentinel — even though the neuron's canonical address IS
# the recipe_id. Both spellings name the same author.
SELF_SPELLINGS = [NEURON_SELF_AUTHOR, NEURON_ADDR]


def test_self_authored_events_do_not_wake_their_author():
    """Direction 1. Both spellings of 'me' are suppressed."""
    entries = [_flowback("review_finding", s) for s in SELF_SPELLINGS]
    got = _collect(_runtime_with(entries).recipe_events(
        NEURON_ADDR, kinds=["review_finding"], exclude_from=NEURON_ADDR))
    assert got == []


def test_the_same_event_from_another_sender_still_wakes():
    """Direction 2. The filter is on SENDER, not on kind — a review_finding
    from a worker is exactly what the flowback channel exists to deliver. A
    filter that swallowed everything would pass the test above."""
    entries = [_flowback("review_finding", WORKER_ADDR)]
    got = _collect(_runtime_with(entries).recipe_events(
        NEURON_ADDR, kinds=["review_finding"], exclude_from=NEURON_ADDR))
    assert [e["from"] for e in got] == [WORKER_ADDR]


def test_mixed_stream_keeps_others_and_drops_only_self():
    entries = [_flowback("learning", NEURON_SELF_AUTHOR),
               _flowback("learning", WORKER_ADDR),
               _flowback("learning", NEURON_ADDR),
               _flowback("learning", "some-other-recipe")]
    got = _collect(_runtime_with(entries).recipe_events(
        NEURON_ADDR, exclude_from=NEURON_ADDR))
    assert [e["from"] for e in got] == [WORKER_ADDR, "some-other-recipe"]


def test_sender_filter_is_opt_in_so_the_wiring_matters():
    """Without exclude_from the echo returns — which is why the neuron guide
    must actually pass it. A filter nobody calls is not a fix."""
    entries = [_flowback("learning", NEURON_SELF_AUTHOR)]
    got = _collect(_runtime_with(entries).recipe_events(NEURON_ADDR))
    assert len(got) == 1


def _neuron_rx_spec() -> str:
    """The neuron guide's ACTUAL rx.merge(...) call form, whitespace-collapsed.

    Deliberately not a substring search over the whole file: the guide also
    EXPLAINS `exclude_from=me` in prose, so `"exclude_from=me" in md` stays true
    even after the call itself loses it — a test that guards a sentence instead
    of the wiring. Mutation 12e caught exactly that."""
    md = Path(".claude/commands/neuron.md").read_text(encoding="utf-8")
    spec = md.split("`rx.merge(")[1].split(")`")[0]
    return " ".join(spec.split())


def test_neuron_guide_wires_the_sender_filter():
    """A filter nobody calls is not a fix."""
    assert "exclude_from=me" in _neuron_rx_spec()


def _neuron_broker_source(spec: str) -> str:
    """Just the `rx.broker(...)` leg of the neuron guide's merge."""
    return "rx.broker(" + spec.split("rx.broker(")[1].split(")")[0] + ")"


def test_neuron_guide_does_not_kind_filter_its_own_directed_inbox():
    """s29/a3b — REPLACES `test_neuron_guide_still_subscribes_to_its_primary_wakes`
    and `test_neuron_guide_does_not_subscribe_to_progress`, and is STRICTLY
    STRONGER than both.

    THE OLD TEST WAS GREEN WHILE THE NEURON WAS DEAF, which is the whole reason it
    is being replaced rather than repaired. It asserted that each of
    ROLE_PRIMARY_WAKES appeared in the guide's `kinds=[...]` list. A list can name
    all four primaries and STILL omit the one kind that must never be dropped —
    and that is exactly what shipped: the neuron's spec carried
    kinds=['question','answer','steer','plan_closed'] and therefore never woke on
    `alert`, the kind reserved for things that must interrupt. It slept through an
    alert that the enforce gate was unsound, one that the objective gate could not
    record its verdict, one that record_context silently drops a constraint — and
    through the message announcing that its own filter had changed. The USER caught
    it; this suite did not, because the property it guarded was "the list contains
    these four", not "nothing addressed to me can be dropped".

    The corrected rule (d115, and the standing restart checklist): the two DRIVING
    roles subscribe with NO kind filter, so no directed message can be silently
    dropped. Guarding the ABSENCE of a filter subsumes the old assertion — with no
    filter every primary wake arrives by construction, and so does `alert`.

    NOTE the scope, so this is not read as more than it is: this pins the GUIDE's
    observe spec (the push plane). The TOOL-layer wake set (`ROLE_WAKE_KINDS`,
    where d53's doorbell drops `progress` from the idle short-circuit's inbox
    check) is a SEPARATE narrowing and is pinned by
    `test_neuron_wake_set_drops_progress_but_keeps_its_primaries` above. The two
    are narrowed independently with no reconciliation between them — a recorded,
    unfixed residual, not an oversight of this test."""
    broker = _neuron_broker_source(_neuron_rx_spec())
    assert "kinds" not in broker, (
        "the neuron's own directed inbox is kind-filtered again. A filter here "
        "silently drops messages ADDRESSED TO IT and nothing reports the drop — "
        "this is how it went deaf to `alert`. Filter the BROADCAST planes "
        f"(rx.recipe_events / rx.pool), never rx.broker. Got: {broker}")

    # ...and the primaries are therefore covered by construction, not by listing.
    for kind in ROLE_PRIMARY_WAKES["neuron"]:
        assert f"'{kind}'" not in broker, (
            f"{kind!r} is named in the broker leg — that means a filter is back")


def test_author_of_reads_the_real_record_shapes():
    """The shapes are taken from live records on disk, not invented:
    `_emit_recipe_event` writes `from: <address str>`; `objects._advisories`
    writes `by: attribution.actor()` = {"role","handle"} — a DICT, never a
    string. An earlier draft of this test asserted `by: "planner@x"`, a shape
    the system never produces (d66)."""
    from edp_claude.reactive import author_of
    assert author_of(_flowback("learning", WORKER_ADDR)) == WORKER_ADDR
    real_by = {"kind": "advisory_override", "op": "delete_step",
               "by": {"role": "worker", "handle": WORKER_ADDR}}
    assert author_of(real_by) == WORKER_ADDR
    assert author_of({"kind": "learning"}) is None


def test_a_neuron_cannot_be_identified_by_its_actor_handle():
    """Surfaced, not silently assumed away: `attribution.actor()` reads
    EDP_HANDLE, which a neuron shell does not set, so its `by.handle` is the
    literal "unknown". This is why the flowback self-filter keys on `from` (the
    NEURON_SELF_AUTHOR sentinel) and why a neuron's own advisory_override is
    NOT suppressed today."""
    from edp_claude.reactive import author_of
    neuron_audit = {"kind": "advisory_override",
                    "by": {"role": "unknown", "handle": "unknown"}}
    assert author_of(neuron_audit) == "unknown"
    assert author_of(neuron_audit) != NEURON_ADDR
    assert author_of(neuron_audit) != NEURON_SELF_AUTHOR


# ══ the collision this work caused, pinned so it cannot recur ══════════════

def test_the_patience_clock_and_the_wall_clock_stay_separate():
    """The monotonic patience seam was first named `_now`, silently rebinding
    the module's wall-clock `_now()` for every one of its ~28 timestamp call
    sites. `.isoformat()` on a float reddened 68 tests. The pacing suite passed
    throughout — it only ever exercised the monotonic clock — so ONLY the full
    suite could see it."""
    import datetime as dt
    assert isinstance(_tools._now(), dt.datetime)   # wall clock, for timestamps
    assert isinstance(_tools._wait_clock(), float)  # monotonic, for patience


def test_no_module_level_name_in_tools_is_defined_twice():
    """Python binds a duplicated module-level name to the LAST definition, so a
    shadow is silent until a caller of the first one runs. Cheap to pin."""
    import re
    from collections import Counter
    src = Path(_tools.__file__).read_text(encoding="utf-8")
    names = re.findall(r"^(?:def|class)\s+(\w+)", src, flags=re.M)
    dupes = [n for n, c in Counter(names).items() if c > 1]
    assert dupes == [], f"shadowed module-level names in _tools.py: {dupes}"
