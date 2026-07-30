"""W11 — session registry carries what a fork-resume needs.

A suspended recipe's planners must be re-launchable later, so every session
row records the claude session it ran under, when it started, when it was
last seen alive, and which recipe it belongs to. Rows written by an OLDER
pool (no such keys) must still load, and `GET /v1/sessions` without a param
must keep returning the unfiltered full list.
"""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from edp_pool.service import PoolService, create_app
from edp_pool.spawner import FakeSpawner

_NEW_KEYS = {"claude_session_id", "spawned_at", "last_seen", "recipe_id"}


@pytest.fixture
def svc():
    return PoolService(FakeSpawner())


def test_spawn_stores_the_claude_session_id(svc):
    sid = svc.spawn("planner", "rec-x:s1", None,
                    claude_session="a1b2c3d4-0000-4000-8000-000000000001")
    row = svc.sessions[sid]
    assert row["claude_session_id"] == "a1b2c3d4-0000-4000-8000-000000000001"
    # spawned_at is tz-AWARE UTC ISO, and last_seen starts equal to it
    assert row["last_seen"] == row["spawned_at"]
    assert datetime.fromisoformat(row["spawned_at"]).tzinfo is not None


def test_spawn_without_a_claude_session_stores_none(svc):
    """No claude_session (the common planner/worker spawn) ⇒ None, no crash.
    Same for a bare handle with no ':' — it simply has no recipe."""
    sid = svc.spawn("specialist", "spec-python", None)   # no ':' in handle
    row = svc.sessions[sid]
    assert row["claude_session_id"] is None
    assert row["recipe_id"] is None
    assert row["spawned_at"] and row["last_seen"]


def test_recipe_id_is_explicit_planner_prefix_and_worker_inherits(svc):
    """A planner handle is `<recipe>:<step>`; a worker handle is
    `<plan_id>:<action>` whose plan_id is the DASH form of `<recipe>-<step>`,
    so the worker inherits its recipe from the planner row owning the plan."""
    p = svc.spawn("planner", "rec-x:s1", None)
    w = svc.spawn("worker", "rec-x-s1:a1", "rec-x-s1")
    orphan = svc.spawn("worker", "no-such-plan:a1", None)
    assert svc.sessions[p]["recipe_id"] == "rec-x"
    assert svc.sessions[w]["recipe_id"] == "rec-x"
    assert svc.sessions[orphan]["recipe_id"] is None   # unresolvable, not a crash


def test_last_seen_refreshes_when_liveness_is_confirmed(svc):
    """`last_seen` is bumped where the service ALREADY probes liveness —
    no new timer. A dead session is never touched."""
    sid = svc.spawn("worker", "p:a1", None)
    spawned = svc.sessions[sid]["spawned_at"]
    svc.sessions[sid]["last_seen"] = "2000-01-01T00:00:00+00:00"  # stale it

    assert svc.liveness("p:a1") == "alive"
    bumped = svc.sessions[sid]["last_seen"]
    assert bumped > "2000-01-01T00:00:00+00:00" and bumped >= spawned

    svc.sessions[sid]["last_seen"] = "2000-01-01T00:00:00+00:00"
    assert svc.active_workers() == 1          # the other liveness probe
    assert svc.sessions[sid]["last_seen"] > "2000-01-01T00:00:00+00:00"

    # dead → liveness says so and last_seen is NOT refreshed
    svc.spawner.kill(sid)
    svc.sessions[sid]["last_seen"] = "2000-01-01T00:00:00+00:00"
    assert svc.liveness("p:a1") == "dead"
    assert svc.sessions[sid]["last_seen"] == "2000-01-01T00:00:00+00:00"


def test_sessions_endpoint_unfiltered_is_unchanged():
    """COMPATIBILITY: no `recipe_id` param ⇒ the full unfiltered list, in
    order, with every pre-W11 key intact. Callers reading the old shape keep
    working."""
    c = TestClient(create_app(FakeSpawner()))
    c.post("/v1/spawn", json={"role": "planner", "handle": "rec-x:s1"})
    c.post("/v1/spawn", json={"role": "planner", "handle": "rec-y:s1"})

    rows = c.get("/v1/sessions").json()
    assert len(rows) == 2                                  # nothing filtered
    assert [r["handle"] for r in rows] == ["rec-x:s1", "rec-y:s1"]
    old_keys = {"session_id", "role", "handle", "parent", "state", "proc"}
    for r in rows:
        assert old_keys <= set(r)          # every pre-W11 key still present
        assert _NEW_KEYS <= set(r)         # ...alongside the new ones


def test_sessions_endpoint_filters_by_recipe_id():
    c = TestClient(create_app(FakeSpawner()))
    c.post("/v1/spawn", json={"role": "planner", "handle": "rec-x:s1"})
    c.post("/v1/spawn", json={"role": "planner", "handle": "rec-y:s1"})
    c.post("/v1/spawn", json={"role": "worker", "handle": "rec-x-s1:a1",
                              "parent_session": "rec-x-s1"})

    rows = c.get("/v1/sessions", params={"recipe_id": "rec-x"}).json()
    assert {r["handle"] for r in rows} == {"rec-x:s1", "rec-x-s1:a1"}
    assert all(r["recipe_id"] == "rec-x" for r in rows)
    assert c.get("/v1/sessions", params={"recipe_id": "nope"}).json() == []


def test_filter_finds_orphan_worker_whose_planner_row_is_gone():
    """ORPHAN-REAP: a worker whose planner row was already reaped (a crash)
    stored recipe_id=None. suspend_recipe finds its workers via this filter
    to REAP them — if the filter missed it, an orphan worker would keep
    running against a suspended recipe. The handle prefix still identifies
    it, so the filter matches on handle when the stored value is None."""
    sp = FakeSpawner()
    c = TestClient(create_app(sp))
    # worker spawned with NO planner row present → recipe_id resolves to None
    c.post("/v1/spawn", json={"role": "worker", "handle": "rec-x-s1:a1",
                              "parent_session": "rec-x-s1"})
    unrelated = c.post("/v1/spawn", json={"role": "worker",
                                          "handle": "rec-y-s1:a1"})
    assert unrelated.status_code == 200

    all_rows = c.get("/v1/sessions").json()
    orphan = next(r for r in all_rows if r["handle"] == "rec-x-s1:a1")
    assert orphan["recipe_id"] is None            # nothing to inherit from

    rows = c.get("/v1/sessions", params={"recipe_id": "rec-x"}).json()
    assert [r["handle"] for r in rows] == ["rec-x-s1:a1"]   # found anyway
    # ...and the prefix match does not drag in another recipe's rows
    assert "rec-y-s1:a1" not in [r["handle"] for r in rows]


def test_new_fields_survive_persist_restart_load(tmp_path):
    state = tmp_path / "pool-state.json"
    svc1 = PoolService(FakeSpawner(), state_path=state)
    sid = svc1.spawn("planner", "rec-x:s1", None, claude_session="sess-uuid-1")
    before = dict(svc1.sessions[sid])

    svc2 = PoolService(FakeSpawner(), state_path=state)   # "restart"
    after = svc2.sessions[sid]
    assert {k: after[k] for k in _NEW_KEYS} == {k: before[k] for k in _NEW_KEYS}
    assert after["recipe_id"] == "rec-x"
    assert after["claude_session_id"] == "sess-uuid-1"


def test_legacy_persisted_row_without_new_keys_loads(tmp_path):
    """A row written by an OLD pool has none of the W11 keys. It must load,
    list, and filter without a KeyError (read with .get, never [...])."""
    state = tmp_path / "pool-state.json"
    legacy = {"session_id": "worker:old", "role": "worker",
              "handle": "p:a1", "parent": None, "state": "active",
              "proc": None}
    state.write_text(json.dumps(
        {"sessions": {"worker:old": legacy}, "locks": {"p:a1": "worker:old"}}),
        encoding="utf-8")

    svc = PoolService(FakeSpawner(), state_path=state)
    assert svc.sessions["worker:old"]["handle"] == "p:a1"
    assert not _NEW_KEYS & set(svc.sessions["worker:old"])   # still absent

    c = TestClient(create_app(FakeSpawner(), state_path=state))
    assert len(c.get("/v1/sessions").json()) == 1            # lists fine
    assert c.get("/v1/sessions", params={"recipe_id": "rec-x"}).json() == []

    # and the legacy row still drives the paths that read it
    assert svc.active_workers() == 0        # FakeSpawner never launched it
