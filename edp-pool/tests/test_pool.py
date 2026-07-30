"""TESTPLAN POOL-1..8 (HLD §6)."""

import pytest
from fastapi.testclient import TestClient

from edp_pool.service import PoolService, create_app
from edp_pool.spawner import FakeSpawner


@pytest.fixture
def svc():
    return PoolService(FakeSpawner())


@pytest.fixture
def client():
    return TestClient(create_app(FakeSpawner()))


def test_pool_1_spawn_records_map(svc):
    sid = svc.spawn("planner", "r1:s2", parent=None)
    assert isinstance(sid, str)
    assert svc.sessions[sid]["handle"] == "r1:s2"
    assert svc.locks["r1:s2"] == sid


def test_pool_2_seventh_worker_capacity_envelope(svc):
    # DESIGN-v7 1.2: default worker cap raised 3 → 6. The 6th spawns, the
    # 7th is refused — and the refusal NAMES the env knob so the operator's
    # fix is one env var, not a code read.
    for i in range(6):
        assert isinstance(svc.spawn("worker", f"p:a{i}", None), str)
    res = svc.spawn("worker", "p:a7", None)
    assert not isinstance(res, str)  # ToolError
    assert res.code == "pool_capacity_exceeded"
    assert res.retryable is True
    assert "max workers = 6" in res.message  # verbatim, LLM-actionable
    assert "EDP_MAX_WORKERS" in res.message  # the knob, named


def test_pool_locks_endpoint_lists_held(client):
    """OBJECT-MODEL inc3: GET /v1/locks lists held locks w/ liveness."""
    client.post("/v1/spawn", json={"role": "worker", "handle": "p:a1"})
    locks = client.get("/v1/locks").json()
    assert any(lk["handle"] == "p:a1" and lk["liveness"] == "alive"
               for lk in locks)


def test_pool_lock_list_marks_dead_holder_phantom(svc):
    sid = svc.spawn("worker", "p:a1", None)
    svc.spawner.kill(sid)  # holder dead, lock not yet reaped → phantom
    rows = svc.lock_list()
    held = next(lk for lk in rows if lk["handle"] == "p:a1")
    assert held["liveness"] == "dead" and held["session_id"] == sid


def test_pool_3_lock_by_spawn_refuses_duplicate(svc):
    svc.spawn("worker", "p:a1", None)
    res = svc.spawn("worker", "p:a1", None)
    assert not isinstance(res, str) and res.code == "pool_unknown_handle"


def test_pool_3b_stale_lock_reaped_on_respawn(svc):
    # 2026-05-21: liveness-aware lock reaping. A worker that crashed
    # holds a phantom lock. The crash-recovery re-dispatch (claude
    # Phase 7) must be able to re-spawn the same handle. The pool reaps
    # the stale lock when the holder is dead.
    sid1 = svc.spawn("worker", "p:a1", None)
    svc.spawner.kill(sid1)  # worker crashed/killed — lock now stale
    sid2 = svc.spawn("worker", "p:a1", None)
    assert isinstance(sid2, str)  # re-spawn SUCCEEDS (stale lock reaped)
    assert sid2 != sid1
    assert svc.locks["p:a1"] == sid2  # lock now held by the fresh worker
    # the dead holder is marked done
    assert svc.sessions[sid1]["state"] == "done"


def test_pool_3c_live_lock_still_refused(svc):
    # Regression: a LIVE holder must still block the duplicate (we only
    # reap DEAD holders, never steal an active lock).
    svc.spawn("worker", "p:a1", None)
    res = svc.spawn("worker", "p:a1", None)  # holder still alive
    assert not isinstance(res, str) and res.code == "pool_unknown_handle"


def test_pool_reap_kills_holder_and_frees_lock(svc):
    # 2026-05-25: the DELIBERATE escape — reap a stuck worker by handle so
    # the deadlock (force-failed-but-alive worker holding its lock) breaks
    # and re-dispatch can proceed.
    sid = svc.spawn("worker", "p:a1", None)
    assert svc.liveness("p:a1") == "alive"
    out = svc.reap("p:a1")
    assert out["reaped"] == sid
    assert not svc.spawner.alive(sid)        # process killed
    assert "p:a1" not in svc.locks            # lock freed
    assert svc.sessions[sid]["state"] == "done"
    # re-dispatch now succeeds (lock is free)
    sid2 = svc.spawn("worker", "p:a1", None)
    assert isinstance(sid2, str) and sid2 != sid


def test_pool_reap_unknown_handle_is_noop(svc):
    out = svc.reap("p:nope")
    assert out["reaped"] is None


def test_dead_but_active_worker_does_not_eat_a_slot(svc):
    # 2026-05-25: the phantom "3/3 occupied with one alive" bug. Workers
    # that died without self-closing kept state="active" and consumed
    # capacity. active_workers() must count only LIVE workers.
    s1 = svc.spawn("worker", "p:a1", None)
    s2 = svc.spawn("worker", "p:a2", None)
    svc.spawn("worker", "p:a3", None)        # 3/3 — at cap
    # two die WITHOUT calling release (crash / manual close)
    svc.spawner.kill(s1)
    svc.spawner.kill(s2)
    assert svc.active_workers() == 1          # only the live one counts
    # a new worker now spawns (the phantom slots were freed)
    s4 = svc.spawn("worker", "p:a4", None)
    assert isinstance(s4, str)
    # the dead sessions were reconciled to done + their locks freed
    assert svc.sessions[s1]["state"] == "done"
    assert "p:a1" not in svc.locks


def test_max_workers_env_override(monkeypatch):
    from edp_pool.service import PoolService
    monkeypatch.setenv("EDP_MAX_WORKERS", "5")
    svc = PoolService(FakeSpawner())
    for i in range(5):
        assert isinstance(svc.spawn("worker", f"p:a{i}", None), str)
    res = svc.spawn("worker", "p:a5", None)   # 6th > 5 → refused
    assert not isinstance(res, str)
    assert res.code == "pool_capacity_exceeded"


def test_pool_state_persists_and_reloads(tmp_path):
    # cross-restart-recovery: locks+sessions survive a pool restart.
    state = tmp_path / "pool-state.json"
    svc1 = PoolService(FakeSpawner(), state_path=state)
    sid = svc1.spawn("worker", "p:a1", None)
    assert isinstance(sid, str)
    assert state.exists()

    # "restart": a fresh service with a FRESH spawner reloads the state.
    svc2 = PoolService(FakeSpawner(), state_path=state)
    assert "p:a1" in svc2.locks
    assert sid in svc2.sessions
    # 2026-05-26 fix: the new spawner has NO record of the old session
    # — it could still be running in its own OS process, the pool just
    # doesn't have a handle on it. Truthful liveness is "unknown", NOT
    # "dead". The prior "dead" verdict triggered the recipe-FSM crash-
    # recovery sweep to mass-reincarnate every live planner whenever
    # the pool restarted (the also_debug_this.txt symptom: FSM offered
    # spawn_planner for s1 while the planner was still alive). The
    # FSM's liveness sweep treats "unknown" conservatively (waits) —
    # so a live planner keeps working, while a TRULY orphaned lock
    # gets reaped lazily when something re-spawns the same handle.
    assert svc2.liveness("p:a1") == "unknown"
    # Re-spawn the same handle still SUCCEEDS — spawn()'s own reap
    # path (alive(holder)==False ⇒ del locks[handle]) handles the
    # truly-orphaned case lazily, on demand, not eagerly via liveness.
    # (Note: "unknown" here is because FakeSpawner has no real pid → no
    # fingerprint. A real SubprocessSpawn persists a fingerprint and
    # liveness is RE-ESTABLISHED after restart — see the tests below.)
    sid2 = svc2.spawn("worker", "p:a1", None)
    assert isinstance(sid2, str) and sid2 != sid


def test_liveness_reestablished_after_restart(monkeypatch, tmp_path):
    # 2026-05-31 restart-blackout fix: a session with a persisted process
    # fingerprint is RE-PROBED after a pool restart — a still-running shell
    # becomes "alive" again (not stuck permanently "unknown").
    import edp_pool.service as svc_mod
    state = tmp_path / "pool-state.json"
    svc1 = PoolService(FakeSpawner(), state_path=state)
    sid = svc1.spawn("worker", "p:a1", None)
    # a real SubprocessSpawn would have captured this; inject it.
    svc1.sessions[sid]["proc"] = {"pid": 4242, "create_time": 111.0}
    svc1._persist()

    # RESTART: fresh service + fresh spawner that knows nothing.
    svc2 = PoolService(FakeSpawner(), state_path=state)
    assert svc2.locks["p:a1"] == sid          # lock reloaded from disk

    # the fingerprinted process is still running → "alive" (re-adopted)
    monkeypatch.setattr(svc_mod, "_proc_alive", lambda fp: True)
    assert svc2.liveness("p:a1") == "alive"
    # the process actually exited → "dead"
    monkeypatch.setattr(svc_mod, "_proc_alive", lambda fp: False)
    assert svc2.liveness("p:a1") == "dead"
    # no fingerprint at all → stays conservatively "unknown"
    svc2.sessions[sid]["proc"] = None
    monkeypatch.setattr(svc_mod, "_proc_alive", lambda fp: None)
    assert svc2.liveness("p:a1") == "unknown"
    # a released/closed session never resurrects
    svc2.sessions[sid]["state"] = "done"
    monkeypatch.setattr(svc_mod, "_proc_alive", lambda fp: True)
    assert svc2.liveness("p:a1") == "dead"


def test_proc_fingerprint_and_alive_real_process():
    # _proc_alive against THIS (alive) test process + reuse defeat.
    import os

    from edp_pool.service import _proc_alive, _proc_fingerprint
    fp = _proc_fingerprint(os.getpid())
    assert fp and fp["pid"] == os.getpid()
    if fp.get("create_time") is not None:        # psutil present
        assert _proc_alive(fp) is True
        # same pid, WRONG create_time (pid reuse) → not alive
        assert _proc_alive({"pid": os.getpid(), "create_time": 1.0}) is False
    # a definitely-dead pid → False (or None if psutil absent)
    assert _proc_alive({"pid": 2_000_000_000, "create_time": None}) in (False, None)
    # no fingerprint → can't tell
    assert _proc_alive(None) is None


def test_pool_no_state_path_is_in_memory_only(tmp_path):
    # Backward compatible: no state_path → no persistence, no file.
    svc = PoolService(FakeSpawner())  # state_path defaults None
    svc.spawn("worker", "p:a1", None)
    # nothing written anywhere (tmp_path stays empty of pool state)
    assert list(tmp_path.glob("*.json")) == []


def test_pool_4_release_frees_lock(svc):
    sid = svc.spawn("worker", "p:a1", None)
    svc.release(sid)
    assert "p:a1" not in svc.locks
    assert isinstance(svc.spawn("worker", "p:a1", None), str)  # re-spawn ok
    # release is idempotent
    svc.release(sid)


def test_pool_5_liveness(svc):
    assert svc.liveness("nope") == "unknown"
    sid = svc.spawn("planner", "r1:s1", None)
    assert svc.liveness("r1:s1") == "alive"
    svc.spawner.kill(sid)
    assert svc.liveness("r1:s1") == "dead"


def test_pool_2b_capacity_via_http_is_409_envelope(client):
    for i in range(6):
        client.post("/v1/spawn", json={"role": "worker",
                                       "handle": f"p:a{i}"})
    r = client.post("/v1/spawn", json={"role": "worker", "handle": "p:a9"})
    assert r.status_code == 409
    b = r.json()
    assert b["ok"] is False and b["code"] == "pool_capacity_exceeded"
    assert b["source"] == "edp-pool"


def test_pool_mode_threaded_via_http(client, monkeypatch):
    """POOL-MODE-1 — /v1/spawn accepts `mode`; FakeSpawner ignores it but
    the request must succeed (mode plumbing intact)."""
    r = client.post("/v1/spawn", json={
        "role": "planner", "handle": "r:sX", "mode": "monitor"})
    assert r.status_code == 200 and "session_id" in r.json()


def test_pool_mode_env_default(client, monkeypatch):
    monkeypatch.setenv("EDP_SPAWN_MODE", "monitor")
    r = client.post("/v1/spawn", json={"role": "planner", "handle": "r:sE"})
    assert r.status_code == 200  # env default applied, no body mode


def test_pool_7_health_conforms(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert set(r.json()) == {"status", "version", "detail", "deps"}


def test_pool_8_sessions_and_release_http(client):
    client.post("/v1/spawn", json={"role": "planner", "handle": "r:s1"})
    rows = client.get("/v1/sessions").json()
    assert len(rows) == 1 and rows[0]["role"] == "planner"
    sid = rows[0]["session_id"]
    assert client.post(f"/v1/release/{sid}").json() == {"ok": True}
    assert client.get("/v1/liveness/r:s1").json()["state"] == "unknown"


def test_pool_6_parent_spawn_registers_alias():
    """POOL-6 — parent spawn best-effort registers a broker alias.
    Broker absent => spawn still succeeds (broker down != spawn failure)."""
    c = TestClient(create_app(FakeSpawner(), broker_url="http://127.0.0.1:1"))
    r = c.post("/v1/spawn", json={"role": "planner", "handle": "r:s2",
                                  "parent_session": "neuron:r"})
    assert r.status_code == 200 and "session_id" in r.json()


def _capture_alias_posts(monkeypatch):
    """Patch the pool's httpx.AsyncClient so the best-effort /v1/alias
    POSTs are captured instead of hitting the network. Returns the list
    that will collect (url, json) tuples."""
    import edp_pool.service as svcmod

    posts: list[tuple[str, dict]] = []

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            posts.append((url, json or {}))
            return object()

    monkeypatch.setattr(svcmod.httpx, "AsyncClient",
                        lambda *a, **k: _FakeClient())
    return posts


def test_pool_s16_planner_spawn_registers_colon_to_dash_alias(monkeypatch):
    """s16 ROOT-CAUSE FIX: spawning a PLANNER registers an ABSOLUTE
    colon→dash bridge so a send to the visible colon EDP_HANDLE reaches
    the dash inbox the planner actually reads on."""
    posts = _capture_alias_posts(monkeypatch)
    c = TestClient(create_app(FakeSpawner(), broker_url="http://broker"))
    r = c.post("/v1/spawn", json={"role": "planner", "handle": "rec-s6:s1",
                                  "parent_session": "neuron:rec"})
    assert r.status_code == 200
    absolute = [j for (_u, j) in posts if j.get("owner_session") == "*"]
    assert any(j.get("alias") == "rec-s6:s1"
               and j.get("target") == "rec-s6-s1" for j in absolute), posts
    # the relative my-planner alias is still registered too (no regression)
    assert any(j.get("alias") == "my-planner" for (_u, j) in posts)


def test_pool_s16_worker_spawn_has_no_colon_bridge(monkeypatch):
    """s16: a WORKER is self-consistent (self_address == colon handle), so
    NO absolute colon→dash bridge is registered for it — only the relative
    my-worker alias."""
    posts = _capture_alias_posts(monkeypatch)
    c = TestClient(create_app(FakeSpawner(), broker_url="http://broker"))
    r = c.post("/v1/spawn", json={"role": "worker", "handle": "plan-x:a1",
                                  "parent_session": "plan-x"})
    assert r.status_code == 200
    assert not [j for (_u, j) in posts if j.get("owner_session") == "*"]
    assert any(j.get("alias") == "my-worker" for (_u, j) in posts)


# ── W7 busyness signal: last_output_ts (PTY-drain-log mtime) ────────────

def test_pool_w7_last_output_ts_delegates_to_spawner(svc):
    """PoolService.last_output_ts(handle) maps handle→sid→spawner mtime.
    None when the handle holds no lock."""
    assert svc.last_output_ts("nope") is None          # no lock
    sid = svc.spawn("worker", "p:a1", None)
    assert svc.last_output_ts("p:a1") is None           # no output yet
    svc.spawner.set_output_ts(sid, 1720000000.5)        # simulate a log write
    assert svc.last_output_ts("p:a1") == 1720000000.5


def test_pool_w7_liveness_endpoint_carries_last_output_ts():
    """GET /v1/liveness/{handle} returns {handle, state, last_output_ts}.
    state unchanged; last_output_ts is the spawner-derived mtime (None
    until output)."""
    sp = FakeSpawner()
    c = TestClient(create_app(sp))
    sid = c.post("/v1/spawn", json={"role": "worker", "handle": "p:a1"}).json()[
        "session_id"]
    body = c.get("/v1/liveness/p:a1").json()
    assert body["state"] == "alive" and body["last_output_ts"] is None
    sp.set_output_ts(sid, 1720000321.0)                 # a drain-log write
    body2 = c.get("/v1/liveness/p:a1").json()
    assert body2["state"] == "alive"
    assert body2["last_output_ts"] == 1720000321.0


def test_pool_w7_unknown_handle_endpoint_has_none_output_ts():
    c = TestClient(create_app(FakeSpawner()))
    body = c.get("/v1/liveness/never:spawned").json()
    assert body["state"] == "unknown" and body["last_output_ts"] is None


def test_subprocess_spawner_last_output_ts_reads_log_mtime(tmp_path):
    """SubprocessSpawner derives last_output_ts from the mtime of the exact
    PTY-drain log its launch object holds — a monitor-mode launch (no
    log_path) or a missing file yields None."""
    from types import SimpleNamespace

    from edp_pool.spawner import SubprocessSpawner

    sp = SubprocessSpawner()
    log = tmp_path / "worker_p_a1.log"
    log.write_bytes(b"\xef\xbb\xbfdrained output\n")
    # headless launch: has a real log_path → its st_mtime is the signal
    sp._launches["headless"] = SimpleNamespace(log_path=log)
    assert sp.last_output_ts("headless") == log.stat().st_mtime
    # monitor launch: no log_path attribute → None (no drain log to stat)
    sp._launches["monitor"] = SimpleNamespace()
    assert sp.last_output_ts("monitor") is None
    # log_path set but file never created → None (OSError swallowed)
    sp._launches["gone"] = SimpleNamespace(log_path=tmp_path / "absent.log")
    assert sp.last_output_ts("gone") is None
    # session this instance never launched (post-restart) → None
    assert sp.last_output_ts("unknown-sid") is None
