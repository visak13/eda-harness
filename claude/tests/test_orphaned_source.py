"""`rx.orphaned` — the orphaned-action edge (2026-07-25).

WHY THIS SOURCE EXISTS, because the test is meaningless without it.

A worker that finishes its file and then exits WITHOUT recording status emits
nothing on any existing plane. There is no crash, so no `child_crashed`; the
shell simply stops appearing in the pool snapshot. `rx.pool` is a LEVEL, and a
level that stops arriving is indistinguishable from a quiet channel — so the one
event a planner most needs was the one event structurally incapable of reaching
it. The stall stayed invisible until somebody happened to call `reconcile`,
which made the heartbeat interval the de-facto stall detector.

The nastiest half is BATCH RESOLUTION, and it is the first test below. A batch
unit runs as ONE shell registered under the HEAD action's handle; a non-head
member has no handle of its own. Probe `<plan_id>:<member>` and you ask about a
handle that never existed, get nothing back, and read a perfectly healthy member
as orphaned. Get this wrong in the safe direction and the source cries wolf on
every batch; get it wrong in the other direction and it stays silent for the
exact failure it was built for.
"""

import json
import threading
from pathlib import Path

import pytest

from edp_claude.reactive import driver as drv
from edp_claude.reactive.driver import RealConfig, RealSources


def _write_plan(root: Path, plan_id: str, actions: list[dict]) -> None:
    plans = root / ".plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / f"{plan_id}.json").write_text(
        json.dumps({"plan_id": plan_id, "actions": actions}), encoding="utf-8")


def _write_recipe(root: Path, recipe_id: str, steps: list[dict]) -> None:
    d = root / ".recipes" / recipe_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.json").write_text(
        json.dumps({"recipe_id": recipe_id, "steps": steps}), encoding="utf-8")


class _FakeResp:
    status_code = 200

    def __init__(self, rows):
        self._rows = rows

    def json(self):
        return self._rows


@pytest.fixture()
def fake_locks(monkeypatch):
    """Control what the pool reports as alive."""
    state = {"rows": []}

    def fake_get(url, timeout=None):  # noqa: ANN001
        return _FakeResp(state["rows"])

    import httpx
    monkeypatch.setattr(httpx, "get", fake_get)
    return state


def _first_emission(obs, timeout=6.0):
    """Subscribe and return the first emitted value, or None if NOTHING was
    emitted before the timeout.

    `None` is the meaningful healthy answer, not a test artefact: the driver's
    change-detector deliberately swallows the opening empty snapshot, so a
    plan with nothing wrong emits NO WAKE AT ALL rather than an empty list.
    That is the property that keeps this signal rare enough to be trusted, so
    the healthy-path tests below assert silence, not `[]`.
    """
    got, seen = [], threading.Event()
    sub = obs.subscribe(
        on_next=lambda v: (got.append(v), seen.set()))
    try:
        seen.wait(timeout)
    finally:
        sub.dispose()
    return got[0] if got else None


def test_batch_member_with_live_head_is_NOT_orphaned(tmp_path, fake_locks):
    """THE REGRESSION. a2 is a batch member whose head a1 holds the only shell.

    a2 has no handle of its own, so a naive liveness probe on `p1:a2` finds
    nothing and would report a healthy member as orphaned — which would fire on
    every batch that exists and train everyone to ignore the signal.
    """
    _write_plan(tmp_path, "p1", [
        {"action_id": "a1", "status": "in_progress", "batch_group": "g"},
        {"action_id": "a2", "status": "in_progress", "batch_group": "g"},
    ])
    fake_locks["rows"] = [{"handle": "p1:a1", "liveness": "alive"}]

    src = RealSources(RealConfig(repo_root=tmp_path, poll_ms=50))
    out = _first_emission(src._src_orphaned(plan_id="p1", grace_secs=0),
                          timeout=1.5)
    assert out is None, f"live batch head must cover its members, got {out}"


def test_batch_member_orphaned_when_head_shell_is_gone(tmp_path, fake_locks):
    """The failure that actually happened: the head recorded itself done and
    the shell exited, leaving the member dispatched with nothing behind it."""
    _write_plan(tmp_path, "p1", [
        {"action_id": "a1", "status": "done", "batch_group": "g"},
        {"action_id": "a2", "status": "in_progress", "batch_group": "g"},
    ])
    fake_locks["rows"] = []          # the batch shell exited cleanly

    src = RealSources(RealConfig(repo_root=tmp_path, poll_ms=50))
    out = _first_emission(src._src_orphaned(plan_id="p1", grace_secs=0))
    assert out and len(out) == 1
    assert out[0]["action_id"] == "a2"
    assert out[0]["backing_handle"] == "p1:a1"     # resolved to the HEAD
    assert "head" in out[0]["reason"]


def test_re_dispatched_member_with_its_OWN_shell_is_NOT_orphaned(
        tmp_path, fake_locks):
    """The false positive that fired ~100 times against a healthy worker.

    When a batch shell exits between members, the planner re-dispatches the
    stranded member STANDALONE, so it now holds a live session under its own
    handle. But `batch_group` is immutable post-authoring, so the record still
    points at the dead head — and resolving to the head alone declares a
    perfectly healthy worker unbacked, every poll, forever, with no move
    available to the planner that fixes it.

    An action's OWN live session is better evidence than a stale grouping
    field, so it must be consulted FIRST. This is the case neither test above
    covers: `..._with_live_head_...` has no own-session, and
    `..._when_head_shell_is_gone` has no session at all.
    """
    _write_plan(tmp_path, "p1", [
        {"action_id": "a1", "status": "done", "batch_group": "g"},
        {"action_id": "a2", "status": "in_progress", "batch_group": "g"},
    ])
    # the batch head's shell is gone; the member was re-dispatched on its own
    fake_locks["rows"] = [{"handle": "p1:a2", "liveness": "alive"}]

    src = RealSources(RealConfig(repo_root=tmp_path, poll_ms=50))
    out = _first_emission(src._src_orphaned(plan_id="p1", grace_secs=0),
                          timeout=1.5)
    assert out is None, (
        "a member with its own live session is not orphaned, whatever its "
        f"stale batch_group says; got {out}")


def test_healthy_plan_never_wakes_you(tmp_path, fake_locks):
    """Terminal and pending actions need no worker. A quiet plan must stay
    quiet or the signal becomes noise and gets ignored."""
    _write_plan(tmp_path, "p1", [
        {"action_id": "a1", "status": "done"},
        {"action_id": "a2", "status": "pending"},
        {"action_id": "a3", "status": "in_progress"},
    ])
    fake_locks["rows"] = [{"handle": "p1:a3", "liveness": "alive"}]

    src = RealSources(RealConfig(repo_root=tmp_path, poll_ms=50))
    assert _first_emission(src._src_orphaned(plan_id="p1", grace_secs=0),
                           timeout=1.5) is None


def test_grace_window_suppresses_the_spawn_gap(tmp_path, fake_locks):
    """`next_action` stamps in_progress before the spawn completes, so an
    action legitimately sits dispatched-without-a-lock for a moment. Reporting
    that as an orphan would fire on every single dispatch."""
    _write_plan(tmp_path, "p1", [
        {"action_id": "a1", "status": "in_progress"},
    ])
    fake_locks["rows"] = []

    src = RealSources(RealConfig(repo_root=tmp_path, poll_ms=50))
    out = _first_emission(src._src_orphaned(plan_id="p1", grace_secs=300),
                          timeout=1.5)
    assert out is None, "inside the grace window nothing may be reported"


def test_neuron_scope_step_with_no_live_planner(tmp_path, fake_locks):
    """The neuron's half of the same defect: a planner that exits without
    recording leaves a step in_progress and the neuron waiting on a
    `plan_closed` that will never be sent. Note the DASH handle form."""
    _write_recipe(tmp_path, "r1", [
        {"step_id": "s1", "status": "in_progress",
         "execution": "spawn_planner"},
        {"step_id": "s2", "status": "pending", "execution": "spawn_planner"},
    ])
    fake_locks["rows"] = []

    src = RealSources(RealConfig(repo_root=tmp_path, poll_ms=50))
    out = _first_emission(src._src_orphaned(recipe_id="r1", grace_secs=0))
    assert out and len(out) == 1
    assert out[0]["step_id"] == "s1"
    assert out[0]["backing_handle"] == "r1-s1"     # dash, not colon


def test_neuron_scope_quiet_while_planner_alive(tmp_path, fake_locks):
    _write_recipe(tmp_path, "r1", [
        {"step_id": "s1", "status": "in_progress",
         "execution": "spawn_planner"},
    ])
    fake_locks["rows"] = [{"handle": "r1-s1", "liveness": "alive"}]

    src = RealSources(RealConfig(repo_root=tmp_path, poll_ms=50))
    assert _first_emission(src._src_orphaned(recipe_id="r1", grace_secs=0),
                           timeout=1.5) is None


def test_needs_a_scope(tmp_path):
    src = RealSources(RealConfig(repo_root=tmp_path))
    with pytest.raises(ValueError):
        src._src_orphaned()


def test_registered_as_rate_limitable_not_critical():
    """It is a polled LEVEL and the orphan condition is STICKY, so sampling it
    can only delay a wake, never discard one. It must not be filed with the
    once-only edges that may never be dropped."""
    from edp_claude.reactive.runtime import (
        CRITICAL_SOURCES,
        RATE_LIMITABLE_SOURCES,
    )
    assert "orphaned" in RATE_LIMITABLE_SOURCES
    assert "orphaned" not in CRITICAL_SOURCES
